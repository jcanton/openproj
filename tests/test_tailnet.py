"""`--auth tailscale`: who a request is, asked of the tailnet it arrived over.

The daemon is a `MockTransport` that answers the way tailscaled 1.102.3 was
measured answering on 2026-10-06 — 200 with a `UserProfile` for a node's
address, 404 "no match for IP:port" for any other address, 400 for something
that is not an address, 403 for any Host but `local-tailscaled.sock`. The
client address is set per request by `behind`, which does to the scope exactly
what uvicorn's proxy-header middleware does behind a trusted proxy, so one test
client can be several devices — the only way to put two people in one room.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import httpx
import pygit2
import pytest
from fastapi.testclient import TestClient
from test_coedit import Session, log_of, stored_body, waited_for
from test_injection import run_js
from test_store import commit_directly
from test_web import SECRET, SEED, TASK, commit_at, git_head, save

from openproj.auth import User, sign_session
from openproj.cli import main
from openproj.store import Store
from openproj.tailnet import Tailnet, parse_users
from openproj.web import SESSION_COOKIE, create_app

USERS = {"jacopo.canton@gmail.com": "jacopo", "agneseflamingomandelli@gmail.com": "agnese"}
JACOPO, AGNESE, STRANGER, LAN = "100.95.59.109", "100.110.172.117", "100.93.1.1", "192.168.50.20"
DEVICES = {
    JACOPO: "jacopo.canton@gmail.com",
    AGNESE: "agneseflamingomandelli@gmail.com",
    STRANGER: "somebody@example.com",
}


def tailscaled(asked: list[httpx.Request], devices: dict[str, str] = DEVICES):
    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.headers["host"] != "local-tailscaled.sock":
            return httpx.Response(403, text="invalid localapi request\n")
        addr = request.url.params.get("addr", "")
        try:
            ipaddress.ip_address(addr)
        except ValueError:
            return httpx.Response(400, text="invalid 'addr' parameter\n")
        if addr not in devices:
            return httpx.Response(404, text="no match for IP:port\n")
        return httpx.Response(
            200,
            json={
                "Node": {"Name": "device.tail11f108.ts.net.", "Addresses": [f"{addr}/32"]},
                "UserProfile": {"ID": 1, "LoginName": devices[addr], "DisplayName": "Someone"},
                "CapMap": None,
            },
        )

    return httpx.MockTransport(answer)


def behind(app):
    """The app as it is behind a proxy: the client is who `x-client` says.

    In production that rewrite is uvicorn's, from `X-Forwarded-For`, and only
    for a proxy it trusts; here it is a header the test sets, outside the app,
    so that what the app is handed is the same scope either way.
    """

    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            for name, value in scope.get("headers", []):
                if name == b"x-client":
                    scope["client"] = (value.decode(), 50000)
        await app(scope, receive, send)

    return wrapped


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    repo = tmp_path / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, SEED, "seed the corpus")
    return repo


@pytest.fixture
def asked() -> list[httpx.Request]:
    return []


@pytest.fixture
def client(plan: Path, asked: list[httpx.Request]):
    app = create_app(
        plan,
        auth="tailscale",
        secret=SECRET,
        tailscale_users=USERS,
        tailscale_transport=tailscaled(asked),
    )
    with TestClient(behind(app)) as client:
        yield client


def as_device(client: TestClient, address: str) -> TestClient:
    client.headers["x-client"] = address
    return client


# --------------------------------------------------------------------------- #
# Who may write
# --------------------------------------------------------------------------- #


def test_a_device_on_the_list_writes_as_its_plan_login_at_its_tailnet_address(
    client: TestClient, plan: Path
):
    """The point of the whole mode: no password, and the commit still says who.
    The address is the one the person signed in to Tailscale with, not a GitHub
    `noreply` for an account a tailnet plan need not have."""
    as_device(client, JACOPO)
    assert client.get("/api/me").json() == {
        "auth": "tailscale",
        "login": "jacopo",
        "member": True,
        "device": "jacopo",
        "choices": ["agnese", "jacopo"],
    }

    answer = save(client, TASK, {"priority": "high"})
    assert answer.status_code == 200, answer.text
    written = commit_at(plan, answer.json()["commit"])
    assert (written.author.name, written.author.email) == ("jacopo", "jacopo.canton@gmail.com")
    assert written.committer.name == "openproj-bot"


@pytest.mark.parametrize(
    ("address", "because"),
    [
        (STRANGER, "somebody@example.com is on the tailnet and not on this server's list"),
        (LAN, f"{LAN} is not a device on this tailnet"),
        # What Starlette's test client calls itself, and the shape of anything
        # else that is not an address: tailscaled answers 400, which is still
        # an answer — not on the tailnet — and not a fault.
        ("testclient", "testclient is not a device on this tailnet"),
    ],
)
def test_anybody_else_reads_and_is_told_why_they_may_not_write(
    client: TestClient, plan: Path, address: str, because: str
):
    """Read-only, never refused the page: a LAN visitor and a tailnet stranger
    can both see the plan, and neither can change it. The sentence is the
    tailnet's reason, because "forbidden" says nothing a person can act on."""
    as_device(client, address)
    before = git_head(plan)

    assert client.get("/").status_code == 200
    me = client.get("/api/me").json()
    assert me["auth"] == "tailscale" and "login" not in me, me
    assert because in me["refusal"]

    answer = save(client, TASK, {"priority": "high"})
    assert answer.status_code == 403, answer.text
    assert because in answer.json()["detail"]
    assert git_head(plan) == before


def test_a_signed_session_cookie_counts_for_nothing(client: TestClient, plan: Path):
    """A session is a second way of saying who somebody is, forgeable by anyone
    holding the signing secret, on a server whose premise is that the network
    already said it. Ignored both ways: it neither lets a stranger write nor
    renames the person the tailnet named."""
    client.cookies.set(SESSION_COOKIE, sign_session(User(login="ann", member=True), SECRET))

    as_device(client, STRANGER)
    assert save(client, TASK, {"priority": "high"}).status_code == 403

    as_device(client, AGNESE)
    commit = save(client, TASK, {"priority": "high"}).json()["commit"]
    assert commit_at(plan, commit).author.name == "agnese"


def test_a_daemon_that_does_not_answer_holds_writes_and_is_asked_again(plan: Path):
    """Fails closed, and is not remembered: a tailscaled that is restarting
    answers in a moment, and a minute of read-only for everybody over one
    dropped connection is a minute nobody could explain."""
    asked: list[httpx.Request] = []
    answering = tailscaled(asked)
    down = {"now": True}

    def flaky(request: httpx.Request) -> httpx.Response:
        if down["now"]:
            raise httpx.ConnectError("no such file or directory", request=request)
        return answering.handler(request)

    app = create_app(
        plan,
        auth="tailscale",
        secret=SECRET,
        tailscale_users=USERS,
        tailscale_transport=httpx.MockTransport(flaky),
    )
    with TestClient(behind(app)) as client:
        as_device(client, JACOPO)
        refused = save(client, TASK, {"priority": "high"})
        assert refused.status_code == 403
        assert "Tailscale did not say who" in refused.json()["detail"]

        down["now"] = False
        assert save(client, TASK, {"priority": "high"}).status_code == 200


def test_the_daemon_is_asked_once_per_address_by_the_only_name_it_answers_to(
    client: TestClient, asked: list[httpx.Request]
):
    """Every asset of every page goes through the same middleware, so an answer
    is kept for a minute; and the LocalAPI refuses any Host but its own with a
    403, so the name is part of the contract and not a placeholder."""
    as_device(client, JACOPO)
    for _ in range(3):
        client.get("/api/me")
    as_device(client, AGNESE)
    client.get("/api/me")

    assert [request.url.params["addr"] for request in asked] == [JACOPO, AGNESE]
    assert {request.url.path for request in asked} == {"/localapi/v0/whois"}
    assert {request.headers["host"] for request in asked} == {"local-tailscaled.sock"}


# --------------------------------------------------------------------------- #
# The co-editing socket asks the same question
# --------------------------------------------------------------------------- #


def test_a_room_credits_each_device_by_its_tailnet_address(client: TestClient, plan: Path):
    """The socket is a write path, and `@app.middleware("http")` never sees one —
    which is why the tailnet is asked in a pure ASGI layer. Two devices, one
    room: the author and the co-author both carry the address each signed in to
    Tailscale with, the trailer included, since it was a fourth copy of the
    `noreply` spelling."""
    before = len(log_of(plan))
    with (
        client.websocket_connect(f"/api/coedit/{TASK}", headers={"x-client": JACOPO}) as one,
        client.websocket_connect(f"/api/coedit/{TASK}", headers={"x-client": AGNESE}) as two,
    ):
        jacopo, agnese = Session(one, "jacopo"), Session(two, "agnese")
        jacopo.hello()
        agnese.hello()
        jacopo.type(0, "A whole paragraph typed by jacopo, which is most of the characters.\n")
        agnese.until("typed by jacopo")
        agnese.type(0, "x")
        jacopo.until("xA whole")

        agnese.save()
        agnese.take("saved")

    assert len(log_of(plan)) == before + 1
    written = commit_at(plan, git_head(plan))
    assert (written.author.name, written.author.email) == ("jacopo", "jacopo.canton@gmail.com")
    assert dict(written.message_trailers)["Co-authored-by"] == (
        "agnese <agneseflamingomandelli@gmail.com>"
    )
    assert "A whole paragraph typed by jacopo" in stored_body(plan)


def test_a_stranger_is_refused_the_room_in_the_tailnets_words(client: TestClient):
    """The handshake's 403 sentence is about a GitHub org, and there is no org
    here: a tab told "you are not a member of the organisation" on a server that
    has none is a tab sent looking for a thing that does not exist."""
    with client.websocket_connect(f"/api/coedit/{TASK}", headers={"x-client": STRANGER}) as socket:
        stranger = Session(socket, "stranger")
        said = waited_for(stranger, "reload")
        closed = socket.receive()

    assert "not on this server's list" in said["why"], said
    assert "organisation" not in said["why"]
    assert closed["code"] == 4403, closed
    assert len(closed["reason"].encode()) <= 123, closed["reason"]


# --------------------------------------------------------------------------- #
# A shared device
# --------------------------------------------------------------------------- #


def test_a_shared_device_writes_as_whoever_on_the_list_it_was_told_to(
    client: TestClient, plan: Path
):
    """jcanton, 2026-10-10: two people share one tablet, and the tailnet knows
    it by one of them. Anybody on the list may pick anybody else on it, and the
    commit then carries the chosen person's name AND address — the address is
    what makes it theirs in `git log`, so a name alone would be half a switch."""
    as_device(client, JACOPO)
    chosen = client.post("/api/as", json={"login": "agnese"})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["login"] == "agnese" and chosen.json()["device"] == "jacopo"
    assert client.get("/api/me").json()["login"] == "agnese"

    commit = save(client, TASK, {"priority": "high"}).json()["commit"]
    written = commit_at(plan, commit)
    assert (written.author.name, written.author.email) == (
        "agnese",
        "agneseflamingomandelli@gmail.com",
    )

    # Back to the device's own name clears the choice rather than storing it,
    # so a device follows the list if its owner on it ever changes.
    back = client.post("/api/as", json={"login": "jacopo"})
    assert back.status_code == 200 and "openproj_as" not in client.cookies
    assert client.get("/api/me").json()["login"] == "jacopo"


def test_choosing_a_name_grants_nothing_the_list_did_not(client: TestClient, plan: Path):
    """The choice is read only for a request the tailnet already named, and it
    can only name somebody on the list — so a forged cookie buys a stranger
    nothing, and a name off the list is ignored rather than written as."""
    before = git_head(plan)
    client.cookies.set("openproj_as", "agnese")
    as_device(client, STRANGER)
    assert save(client, TASK, {"priority": "high"}).status_code == 403
    assert client.post("/api/as", json={"login": "agnese"}).status_code == 403
    assert git_head(plan) == before

    as_device(client, JACOPO)
    assert client.post("/api/as", json={"login": "mallory"}).status_code == 422
    assert client.post("/api/as", json={"login": "agnese", "as": "x"}).status_code == 422
    client.cookies.set("openproj_as", "mallory")
    assert client.get("/api/me").json()["login"] == "jacopo"


# --------------------------------------------------------------------------- #
# The corner of the nav
# --------------------------------------------------------------------------- #

CORNER = """
(async () => {
  for (let i = 0; i < 50; i++) await null;
  const who = document.getElementById('who');
  return {
    hidden: who.hidden,
    drawn: who.children.map(c => ({tag: c.tagName, text: c.textContent,
                                    klass: c.className, title: c.title || ''})),
  };
})()
"""


@pytest.mark.parametrize(
    ("me", "drawn"),
    [
        (
            {"auth": "tailscale", "login": "jacopo", "member": True},
            [{"tag": "SPAN", "text": "jacopo", "klass": "", "title": ""}],
        ),
        (
            {
                "auth": "tailscale",
                "login": "agnese",
                "member": True,
                "device": "jacopo",
                "choices": ["agnese", "jacopo"],
            },
            [
                {
                    "tag": "SELECT",
                    "text": "agnesejacopo (this device)",
                    "klass": "",
                    "title": "Writing as — the name this device saves under",
                }
            ],
        ),
        (
            {"auth": "tailscale", "refusal": "192.168.50.20 is not a device on this tailnet"},
            [
                {
                    "tag": "SPAN",
                    "text": "read-only",
                    "klass": "warn",
                    "title": "192.168.50.20 is not a device on this tailnet",
                }
            ],
        ),
    ],
)
def test_the_corner_offers_no_sign_in_and_no_sign_out(client: TestClient, me: dict, drawn: list):
    """Sign in would lead to a GitHub sign-in no tailnet server has configured,
    and Sign out would answer with the same person on the next request. The
    shell's own script, driven, with `/api/me` answering as this server does."""
    page = as_device(client, JACOPO).get("/").text
    answer = run_js(page, CORNER, page=True, me=me)

    assert answer["value"] == {"hidden": False, "drawn": drawn}, answer


# --------------------------------------------------------------------------- #
# Starting up
# --------------------------------------------------------------------------- #


def test_the_list_is_read_strictly():
    """It is the whole write permission, so a pair read some other way than it
    was meant is somebody writing under another person's name."""
    assert parse_users(" a@x.org=ann , b@y.org=bo ,") == {"a@x.org": "ann", "b@y.org": "bo"}
    for bad, says in [
        ("a@x.org", "is not `tailnet-login=plan-login`"),
        ("a@x.org=", "is not `tailnet-login=plan-login`"),
        ("a@x.org=ann,a@x.org=bo", "listed twice"),
        ("a@x.org=ann,b@y.org=ann", "named by two tailnet logins"),
    ]:
        with pytest.raises(ValueError, match=says):
            parse_users(bad)


def test_the_app_refuses_a_tailnet_with_nobody_on_the_list(plan: Path):
    with pytest.raises(ValueError, match="OPENPROJ_TAILSCALE_USERS"):
        create_app(plan, auth="tailscale", secret=SECRET)


def test_the_list_gives_the_store_its_addresses(plan: Path):
    """One function for the address, and the GitHub `noreply` for anybody it
    does not know, which is every login under `github` and `dev`."""
    store = Store(plan, addresses=Tailnet(USERS).addresses())
    try:
        assert store.address("agnese") == "agneseflamingomandelli@gmail.com"
        assert store.address("ann") == "ann@users.noreply.github.com"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("environment", "says"),
    [
        ({}, "nothing says how people sign in"),
        ({"OPENPROJ_AUTH": "github-ish"}, "OPENPROJ_AUTH='github-ish' is not a way to sign in"),
        ({"OPENPROJ_AUTH": "tailscale"}, "needs OPENPROJ_TAILSCALE_USERS"),
        (
            {"OPENPROJ_AUTH": "tailscale", "OPENPROJ_TAILSCALE_USERS": "a@x.org"},
            "is not `tailnet-login=plan-login`",
        ),
        (
            {
                "OPENPROJ_AUTH": "tailscale",
                "OPENPROJ_TAILSCALE_USERS": "a@x.org=ann",
                "OPENPROJ_FORWARDED_ALLOW_IPS": "*",
            },
            "believes whatever address a client claims",
        ),
    ],
)
def test_serve_refuses_to_guess_who_may_write(
    plan: Path, monkeypatch: pytest.MonkeyPatch, capsys, environment: dict, says: str
):
    """`--auth` had a default, and it was `dev`: a bare `openproj serve` let
    anybody who could reach the port write. Now nothing is assumed — and under
    `tailscale`, where the address is the identity, a proxy setting that believes
    any address a client claims is refused with it."""
    for name in (
        "OPENPROJ_AUTH",
        "OPENPROJ_TAILSCALE_USERS",
        "OPENPROJ_FORWARDED_ALLOW_IPS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert main(["serve", "--repo", str(plan)]) == 2
    assert says in capsys.readouterr().err
