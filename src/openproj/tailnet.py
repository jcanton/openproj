"""Tailscale sign-in: who a request is, asked of the tailnet it arrived over.

For a plan served inside a tailnet, a password or a GitHub round trip proves
nothing the network has not already proved: a packet from a tailnet address
came from one device, and tailscaled knows whose. `--auth tailscale` asks it —
the LocalAPI's `whois`, over the daemon's unix socket — and maps the answer
through a list the server was started with (`OPENPROJ_TAILSCALE_USERS`). On the
list, you write as the plan login it names; anywhere else, you read.

Three details here are not obvious and each was measured against a running
tailscaled (1.102.3, 2026-10-06) before a line of this was written:

* The LocalAPI refuses any Host but `local-tailscaled.sock`, with a 403 and
  "invalid localapi request" — its guard against DNS rebinding. So the base URL
  below is not a placeholder; it is the only name that works.
* `whois` takes a bare IP as well as `ip:port`, answers 404 "no match for
  IP:port" for an address no node holds — a LAN client, the loopback — and 400
  for something that is not an address at all, which is what Starlette's test
  client calls itself. Both are an answer ("not on the tailnet"), not a fault.
* A process that is not root gets the read half of the LocalAPI on a unix
  socket, and `whois` is in that half. The container serving this need not be
  root, and is then structurally unable to reconfigure the tailnet it sits on.

The identity is the client ADDRESS, so everything rests on that address being
the client's. Behind a proxy that is uvicorn's `forwarded_allow_ips`, and its
`*` takes the LEFTMOST `X-Forwarded-For` entry — the one the client wrote — so
`serve` refuses to start with both. See `cli._serve`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

SOCKET = "/var/run/tailscale/tailscaled.sock"
LOCALAPI = "http://local-tailscaled.sock"
# Where the answer is left for `viewer` to read. Under a key of this module's
# own, in the ASGI scope both a Request and a WebSocket expose, so the two halves
# of the app read one answer by one name.
SCOPE_KEY = "openproj.tailnet"
# How long an answer is believed. An address keeps its node for the node's life
# and the list is fixed for the process's, so this is about not asking on every
# asset rather than about freshness; a minute bounds how long a device removed
# from the tailnet — whose packets stop arriving anyway — is remembered.
TTL_SECONDS = 60.0
# A bound on the memo, not a tuning knob: the keys are client addresses, and a
# LAN with IPv6 privacy addresses mints new ones every day.
MEMO_LIMIT = 1024


@dataclass(frozen=True)
class Seen:
    """What the tailnet said about one request: the plan login it writes as, or
    the sentence that says why it may only read."""

    login: str = ""
    refusal: str = ""


def parse_users(text: str) -> dict[str, str]:
    """`OPENPROJ_TAILSCALE_USERS` as {tailnet login: plan login}.

    `jacopo.canton@gmail.com=jacopo,agnese@example.com=agnese` — commas between
    pairs, `=` inside one. Refused rather than repaired: this list is the whole
    of the write permission, and a pair read some other way than it was meant
    is a person writing under somebody else's name.

    One tailnet login per plan login, both ways. Two tailnet accounts for one
    person would make the address on that person's commits a guess, and the
    second account is a thing nobody has asked for.
    """
    users: dict[str, str] = {}
    for pair in text.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tailnet, sep, login = (part.strip() for part in pair.partition("="))
        if not sep or not tailnet or not login:
            raise ValueError(
                f"{pair!r} is not `tailnet-login=plan-login`. OPENPROJ_TAILSCALE_USERS is "
                "comma-separated pairs, e.g. `you@example.com=you,them@example.com=them`."
            )
        if tailnet in users:
            raise ValueError(f"{tailnet} is listed twice in OPENPROJ_TAILSCALE_USERS")
        if login in users.values():
            raise ValueError(
                f"{login} is named by two tailnet logins in OPENPROJ_TAILSCALE_USERS, so "
                "which address its commits carry would be a guess"
            )
        users[tailnet] = login
    return users


class Tailnet:
    """The `whois` half of tailscaled, asked once per address per minute."""

    def __init__(
        self,
        users: dict[str, str],
        socket: str = SOCKET,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.users = dict(users)
        # Two seconds, because a socket on the same machine either answers in
        # milliseconds or is not answering; and async, because the wait would
        # otherwise stall every other request on the loop while it lasted.
        self._client = httpx.AsyncClient(
            base_url=LOCALAPI,
            transport=transport or httpx.AsyncHTTPTransport(uds=socket),
            timeout=2.0,
        )
        self._memo: dict[str, tuple[float, Seen]] = {}

    def addresses(self) -> dict[str, str]:
        """{plan login: tailnet login} — the address each person's commits carry.

        The tailnet login is the email the person signed in to Tailscale with,
        which is an address they actually read, where the GitHub `noreply` form
        the store falls back to names an account a tailnet plan may not have.
        """
        return {login: tailnet for tailnet, login in self.users.items()}

    async def seen(self, host: str | None) -> Seen:
        if not host:
            return Seen(refusal="this request carries no client address to ask Tailscale about")
        now = time.monotonic()
        memo = self._memo.get(host)
        if memo is not None and now - memo[0] < TTL_SECONDS:
            return memo[1]
        try:
            response = await self._client.get("/localapi/v0/whois", params={"addr": host})
            answer = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as error:
            # Not remembered: a daemon that is restarting will answer in a
            # moment, and a minute of read-only for everybody because of one
            # dropped connection is a minute nobody can explain.
            return Seen(
                refusal=f"Tailscale did not say who {host} is ({error}), so nothing "
                "may be written from it until it does"
            )
        if response.status_code in (400, 404):
            seen = Seen(
                refusal=f"{host} is not a device on this tailnet; connect through "
                "Tailscale to make changes"
            )
        elif response.status_code != 200:
            return Seen(
                refusal=f"Tailscale answered {response.status_code} when asked who "
                f"{host} is, so nothing may be written from it until it says"
            )
        else:
            seen = self._named(answer, host)
        if len(self._memo) >= MEMO_LIMIT:
            self._memo.clear()
        self._memo[host] = (now, seen)
        return seen

    def _named(self, answer: object, host: str) -> Seen:
        """A `whois` answer, through the list. A tagged node answers with the
        login `tagged-devices`, which is on nobody's list, and so lands here like
        any other stranger."""
        profile = answer.get("UserProfile") if isinstance(answer, dict) else None
        name = profile.get("LoginName", "") if isinstance(profile, dict) else ""
        login = self.users.get(name, "")
        if login:
            return Seen(login=login)
        return Seen(
            refusal=f"{name or host} is on the tailnet and not on this server's list of "
            "who may write (OPENPROJ_TAILSCALE_USERS)"
        )

    async def close(self) -> None:
        await self._client.aclose()


def seen_in(scope: dict) -> Seen:
    """What `Identify` left in this scope. Never absent behind it; if it ever
    is, that is nobody, said in a sentence rather than as an AttributeError."""
    return scope.get(SCOPE_KEY) or Seen(refusal="Tailscale was not asked who this is")


class Identify:
    """ASGI middleware: the tailnet's answer for this request, in its scope.

    Pure ASGI rather than `@app.middleware("http")`, because that decorator never
    sees a WebSocket — and the co-editing socket is a write path that has to ask
    the same question the PATCH does. Asked once, here, so `viewer` stays the
    synchronous function every route already calls and nothing does I/O inside it.
    """

    def __init__(self, app, tailnet: Tailnet) -> None:
        self.app = app
        self.tailnet = tailnet

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            scope[SCOPE_KEY] = await self.tailnet.seen(client[0] if client else None)
        await self.app(scope, receive, send)
