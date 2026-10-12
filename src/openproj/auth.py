"""GitHub sign-in, used to establish identity and nothing else.

The OAuth app asks for `read:org` and no other scope. The token answers two
questions — who are you, and are you in the org — and is then thrown away. It is
never stored in the session and never used to push. Asking for `repo` instead
would put thirty write-capable credentials in a cookie jar; the push credential is
a separate bot token that no person's departure invalidates.

Three details here are not obvious and each was a real trap:

* GitHub answers a failed token exchange with **HTTP 200** and an `error` key.
  Branching on `status_code` alone accepts a failure as a success.
* Membership is asked as *"am I in this org"* against the user's own token, not as
  *"is this person in that org"*. The latter cannot see concealed membership, so it
  answers "no" for every private member and locks out most of the team.
* A membership response of `200` is not enough: an invited-but-not-joined user is
  `200` with `state: "pending"`. Only `active` is a member.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
MEMBERSHIP_URL = "https://api.github.com/user/memberships/orgs/{org}"

SCOPE = "read:org"
USER_AGENT = "openproj"
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": USER_AGENT,
}
_SALT = "openproj.session"

# How long a signature is good for writing: an unrevocable `member: true` for this
# long, which is how long somebody who has left the org keeps write access.
SESSION_SECONDS = 86400
# How long the browser keeps the cookie, which is a different question and is
# deliberately much longer. A cookie past `SESSION_SECONDS` grants nothing — the
# signature check refuses it — but it is still this server's own word that this
# browser signed in, and that is what lets `web.py` send it back through GitHub
# without a click instead of drawing the page signed out. When the two were the
# same 24 hours, the browser threw the cookie away at the very moment it could
# have been renewed, and everybody was signed out once a working day at whatever
# time they had signed in the day before — 2026-10-12, read off the Cloud Run log:
# a re-sign-in at +25.1h, +26.1h, +24.2h, +28.6h, four of them after a save had
# already been refused with a 401.
COOKIE_SECONDS = 30 * 86400
# How old a session may be before a page load renews it. Half the signature's
# life, so that a page opened at any point in a working day leaves the session
# good for the rest of it: the renewal that matters is the one that happens
# BEFORE a save is refused, because the one after it has already cost a save.
RENEW_AFTER_SECONDS = SESSION_SECONDS // 2


class User(BaseModel):
    login: str
    member: bool


class OAuthError(RuntimeError):
    """GitHub refused the exchange. Carries GitHub's own wording, which is better
    than anything this module could invent for the person staring at it."""


def login_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the browser. `state` is carried verbatim so the caller can
    bind it to a cookie and reject a callback it did not start."""
    return f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
        }
    )


async def exchange_code(code: str, client_id: str, client_secret: str, client) -> str:
    """Trade the callback code for a token.

    `Accept: application/json` is required — without it GitHub answers in
    form-encoding and `.json()` raises on a response that actually succeeded.
    """
    response = await client.post(
        TOKEN_URL,
        data={"client_id": client_id, "client_secret": client_secret, "code": code},
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        payload = response.json()
    except ValueError as exc:
        # GitHub answers in form-encoding when the Accept header is missing or
        # stripped by a proxy. That is a configuration fault, and the person
        # staring at the login screen needs a sentence rather than a traceback.
        # The body is deliberately not quoted: on this endpoint it contains the
        # access token, and an error message ends up in logs and on screens.
        raise OAuthError(
            "GitHub answered the token exchange with "
            f"{response.headers.get('content-type', 'an unknown type')} instead of "
            "application/json, so the Accept header was lost in transit."
        ) from exc
    # Not `status_code != 200`: a refused exchange is a 200 with an error key.
    if "error" in payload:
        raise OAuthError(
            f"{payload['error']}: {payload.get('error_description', 'no description')}"
        )
    if SCOPE not in payload.get("scope", "").split(","):
        raise OAuthError(
            f"the granted scope {payload.get('scope', '')!r} does not include {SCOPE}, "
            "so org membership cannot be established"
        )
    return payload["access_token"]


async def identify(token: str, org: str, client) -> User:
    """Who the token belongs to, and whether they are in the org.

    Uses `/user/memberships/orgs/{org}`, which asks about the *caller's own*
    membership and therefore sees it whether it is public or concealed.
    """
    headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
    who = await client.get(USER_URL, headers=headers)
    login = who.json()["login"]

    membership = await client.get(MEMBERSHIP_URL.format(org=org), headers=headers)
    if membership.status_code == 200:
        # "pending" is invited-but-not-joined. Treating it as membership would give
        # write access to anyone who has merely been sent an invitation.
        member = membership.json().get("state") == "active"
    else:
        # 404 is the documented answer for "not affiliated". A 401 or 403 means the
        # token or the app is misconfigured, which is an operator problem — but the
        # safe answer to "may this person write" is still no.
        member = False
    return User(login=login, member=member)


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def sign_session(user: User, secret: str) -> str:
    """The session carries the login and the membership answer — never the token.

    That is the whole difference between a session store and a pile of credentials:
    if this cookie leaks, it impersonates one person on one tracker, and grants
    nothing on GitHub.
    """
    return _serializer(secret).dumps({"login": user.login, "member": user.member})


def read_session(
    cookie: str | None, secret: str, max_age: int = SESSION_SECONDS
) -> User | None:
    """The user this server signed, or None. Never trust a cookie you did not sign."""
    if not cookie:
        return None
    try:
        payload = _serializer(secret).loads(cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return User(login=payload["login"], member=payload["member"])


def signed_at(cookie: str | None, secret: str) -> datetime | None:
    """When this server signed the session, whatever its age, or None if it did not.

    Not a session: an expired signature is still answered here, because the one
    question this exists for is whether a browser that is no longer signed in
    used to be — which only a cookie past its `max_age` can say. Never trust it
    for anything else. Write access is `read_session`'s, and stays bounded by
    `SESSION_SECONDS`.
    """
    if not cookie:
        return None
    try:
        _, stamped = _serializer(secret).loads(cookie, return_timestamp=True)
    except BadSignature:
        return None
    return stamped
