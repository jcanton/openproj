"""The identity layer's contract, written before the identity layer exists.

Five decisions drive almost every assertion here, and each one is either a way the
whole team gets locked out or a way the write credential gets away from us:

* **Scope `read:org` and nothing else.** The token answers one question — "is this
  person in the org" — and is then discarded. `repo` would put thirty
  write-capable tokens in a session store, which is spec section 13's stated
  worst case, so `test_the_authorize_url_asks_for_read_org_and_nothing_else`
  guards the string rather than the behaviour.
* **Membership is asked of the user's own token.** `GET /user/memberships/orgs/{org}`
  answers as the caller about the caller, so it sees a concealed membership.
  `GET /orgs/{org}/members/{user}` answers from the *requester's* perspective, and
  a live probe of that endpoint today returned `302 → /public_members/ann`, which
  then 404s: concealed membership is GitHub's default, so that endpoint answers
  "no" for most of kilnlab. `test_a_concealed_member_is_still_a_member` stubs the
  rejected endpoints with exactly those answers, so an implementation that reaches
  for them fails here instead of in week one, silently, as a lockout.
* **GitHub reports OAuth failures as HTTP 200 with an `error` key.** Branching on
  `status_code` alone reads an expired code as a successful exchange. Every error
  test below therefore serves status 200.
* **The token is never part of the session.** `identify` consumes it and `User`
  carries `login` and `member` and nothing else. That is the entire difference
  between a signed cookie and a pile of credentials.
* **A cookie is a claim until the signature says otherwise.** `member: true` is
  readable by the person holding it, so tampering, forgery, expiry and absence all
  have to land on the same clean logged-out state — `None`, never an exception.

GitHub is stubbed rather than mocked at the network layer: a test suite that needs
credentials, or a network, is a test suite that stops being run.
"""

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import pytest

from openproj.auth import (
    User,
    exchange_code,
    identify,
    login_url,
    read_session,
    sign_session,
)

CLIENT_ID = "Iv1.0123456789abcdef"
CLIENT_SECRET = "s3cr3t-client-secret"
REDIRECT_URI = "https://openproj.example.org/auth/callback"
STATE = "MnwrhZ3nJgYQ8bTLXkGNmA_9tYtE0rMqQzVGmv1sJcs"
CODE = "e72e16c7e42f292c6912"
TOKEN = "gho_16C7e42F292c6912E7710c838347Ae178B4a"
SECRET = "signing-secret-for-tests"
ORG = "kilnlab"
LOGIN = "ann"

AUTHORIZE = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
MEMBERSHIP_URL = f"https://api.github.com/user/memberships/orgs/{ORG}"

# The endpoint the research rejected, and where GitHub sends it next. Registered
# in the concealed-member test so that using it produces GitHub's real answer.
REJECTED_URL = f"https://api.github.com/orgs/{ORG}/members/{LOGIN}"
REJECTED_REDIRECT = f"https://api.github.com/organizations/10514629/public_members/{LOGIN}"
REJECTED_PUBLIC = f"https://api.github.com/orgs/{ORG}/public_members/{LOGIN}"

# Raised when nobody handled the case. A caller cannot show any of these to a
# person, so none of them counts as "a clear error".
INCIDENTAL = (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError)


# --------------------------------------------------------------------------- #
# A stubbed GitHub
#
# Hand-rolled rather than httpx.MockTransport, so the suite has no opinion about
# which HTTP client the module ends up holding — `client` is injected precisely so
# that this file never opens a socket.
# --------------------------------------------------------------------------- #


def run(coroutine):
    """Drive one coroutine to completion without adding an async pytest plugin.

    pytest-asyncio would be a dependency, a config key and a marker, bought for
    four `await`s.
    """
    return asyncio.run(coroutine)


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    headers: dict[str, str]  # lowercased: httpx header lookup is case-insensitive
    form: dict | None = None
    body: object | None = None  # whatever was passed as `json=`
    extra: dict = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class Response:
    """Enough of httpx.Response that a wrong assumption about httpx fails here.

    `json()` parses `text` on demand, so a form-encoded body raises the same
    `JSONDecodeError` httpx would raise rather than quietly returning a dict.
    """

    def __init__(self, status_code: int, *, payload=None, text: str = "", headers=None):
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else text
        self.headers = {"content-type": "application/json"} if payload is not None else {}
        self.headers.update({k.lower(): v for k, v in (headers or {}).items()})

    def json(self):
        return json.loads(self.text)


class FakeGitHub:
    """An httpx.AsyncClient stand-in answering from a routing table.

    A URL that is not in the table raises rather than returning 404, so calling an
    endpoint nobody stubbed is a loud failure and never an accidental
    "not a member".
    """

    def __init__(self, routes: dict[tuple[str, str], Response]):
        self.routes = routes
        self.requests: list[Request] = []

    async def post(self, url, *, data=None, json=None, headers=None, **extra):
        return self._answer("POST", url, form=data, body=json, headers=headers, extra=extra)

    async def get(self, url, *, headers=None, **extra):
        return self._answer("GET", url, headers=headers, extra=extra)

    def _answer(self, method, url, *, form=None, body=None, headers=None, extra=None) -> Response:
        extra = extra or {}
        self.requests.append(
            Request(
                method=method,
                url=str(url),
                headers={k.lower(): v for k, v in dict(headers or {}).items()},
                form=form,
                body=body,
                extra=extra,
            )
        )
        key = (method, str(url).split("?")[0])
        if key not in self.routes:
            raise AssertionError(f"no stub for {method} {url}; stubbed: {sorted(self.routes)}")
        response = self.routes[key]
        if response.status_code in (301, 302, 307, 308) and extra.get("follow_redirects"):
            # httpx does not follow redirects unless asked; when it is asked, this
            # is where the members check quietly becomes a public-members check.
            return self._answer(method, response.headers["location"], headers=headers, extra=extra)
        return response

    def urls(self, method: str = "GET") -> list[str]:
        return [r.url for r in self.requests if r.method == method]


def membership(state: str = "active", role: str = "member") -> dict:
    """The Org Membership object, with the fields the decision is made from."""
    return {
        "state": state,
        "role": role,
        "organization": {"login": ORG},
        "user": {"login": LOGIN},
        "direct_membership": True,
    }


def github(*, user=None, membership_response=None, extra=None) -> FakeGitHub:
    routes = {
        ("POST", TOKEN_URL): Response(
            200, payload={"access_token": TOKEN, "scope": "read:org", "token_type": "bearer"}
        ),
        ("GET", USER_URL): user or Response(200, payload={"login": LOGIN, "id": 1234567}),
        ("GET", MEMBERSHIP_URL): membership_response or Response(200, payload=membership()),
    }
    routes.update(extra or {})
    return FakeGitHub(routes)


def assert_deliberate(error: Exception, mentions: str) -> None:
    """The raise is a decision someone made, and its message can be shown to a person."""
    assert not isinstance(error, INCIDENTAL), (
        f"{type(error).__name__} is what a program does when nobody handled the case; "
        "the browser needs a sentence, not a traceback"
    )
    assert mentions in str(error), f"expected {mentions!r} in the message, got {str(error)!r}"


# --------------------------------------------------------------------------- #
# 1. login_url
# --------------------------------------------------------------------------- #


def test_the_authorize_url_asks_for_read_org_and_nothing_else():
    """The one string in the codebase that decides how much damage a leaked session
    can do. `repo` here — copied in for "we might need it later" — turns every
    login into a write-capable credential for every kilnlab repository.
    """
    url = login_url(CLIENT_ID, REDIRECT_URI, STATE)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "github.com",
        "/login/oauth/authorize",
    )
    assert query["scope"] == ["read:org"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert "repo" not in url
    assert "client_secret" not in query  # the secret has no business in a browser


def test_the_state_is_carried_verbatim_so_the_caller_can_bind_it_to_a_cookie():
    """`login_url` takes the state rather than inventing one: the same value has to
    go into a short-lived cookie, and a function that generated its own would leave
    the caller nothing to compare against on the way back.
    """
    url = login_url(CLIENT_ID, REDIRECT_URI, STATE)

    assert parse_qs(urlparse(url).query)["state"] == [STATE]
    assert login_url(CLIENT_ID, REDIRECT_URI, "other-state") != url


def test_the_redirect_uri_is_percent_encoded_into_the_query():
    """It must arrive byte-identical at the token exchange, and GitHub's matching
    rule is exact. A raw `https://…` spliced into the query string is a
    `redirect_uri_mismatch` that only shows up against the real app.
    """
    url = login_url(CLIENT_ID, REDIRECT_URI, STATE)

    assert "https%3A%2F%2Fopenproj.example.org%2Fauth%2Fcallback" in url
    assert parse_qs(urlparse(url).query)["redirect_uri"] == [REDIRECT_URI]


# --------------------------------------------------------------------------- #
# 2. exchange_code
# --------------------------------------------------------------------------- #


def test_the_code_is_exchanged_for_a_token_at_githubs_token_endpoint():
    """`Accept: application/json` is the load-bearing header: without it GitHub
    answers `access_token=gho_…&scope=…` in form encoding, and the parse of that is
    the next test. The User-Agent is not optional either — api.github.com rejects
    requests that have none.
    """
    client = github()

    token = run(exchange_code(CODE, CLIENT_ID, CLIENT_SECRET, client))

    assert token == TOKEN
    request = client.requests[0]
    assert (request.method, request.url) == ("POST", TOKEN_URL)
    assert request.header("accept") == "application/json"
    assert request.header("user-agent")
    assert request.form == {  # form-encoded, which is what this endpoint takes
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": CODE,
    }
    assert request.body is None
    assert "client_secret" not in request.url  # secrets in query strings end up in logs


@pytest.mark.parametrize(
    ("error", "description"),
    [
        ("bad_verification_code", "The code passed is incorrect or expired."),
        ("incorrect_client_credentials", "The client_id and/or client_secret are incorrect."),
        ("redirect_uri_mismatch", "The redirect_uri MUST match the registered callback URL."),
    ],
)
def test_an_oauth_failure_raises_even_though_github_answers_200(error: str, description: str):
    """The trap this module exists to not fall into: GitHub reports these as HTTP
    200 with an `error` key, so `response.raise_for_status()` sees success and
    `payload["access_token"]` raises KeyError three frames away from the cause.

    `bad_verification_code` is not exotic — it is every user who left the consent
    tab open for ten minutes.
    """
    client = github(
        extra={
            ("POST", TOKEN_URL): Response(
                200,
                payload={
                    "error": error,
                    "error_description": description,
                    "error_uri": "https://docs.github.com/",
                },
            )
        }
    )

    with pytest.raises(Exception) as caught:  # noqa: B017 — the type is the module's to choose
        run(exchange_code(CODE, CLIENT_ID, CLIENT_SECRET, client))

    assert_deliberate(caught.value, error)


def test_a_form_encoded_body_is_an_error_and_never_mistaken_for_a_token():
    """What arrives if the Accept header is ever dropped — by an edit here, or by a
    proxy. The failure has to be a sentence, not a JSONDecodeError from inside the
    HTTP client, and above all not the string `access_token=gho_…` returned as if
    it were the token.
    """
    client = github(
        extra={
            ("POST", TOKEN_URL): Response(
                200,
                text=f"access_token={TOKEN}&scope=read%3Aorg&token_type=bearer",
                headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
            )
        }
    )

    with pytest.raises(Exception) as caught:  # noqa: B017 — the type is the module's to choose
        run(exchange_code(CODE, CLIENT_ID, CLIENT_SECRET, client))

    assert_deliberate(caught.value, "application/json")
    assert TOKEN not in str(caught.value)  # nor does the failure leak the credential


def test_a_grant_that_does_not_include_read_org_is_refused_here():
    """`scope` in the response is what was *granted*, not what was asked for: an org
    with third-party application restrictions can strip it while the exchange still
    succeeds. A token without `read:org` cannot answer the membership question, so
    it would produce a confident `member=False` for a genuine member — the lockout
    again, one endpoint earlier.
    """
    client = github(
        extra={
            ("POST", TOKEN_URL): Response(
                200,
                payload={"access_token": TOKEN, "scope": "", "token_type": "bearer"},
            )
        }
    )

    with pytest.raises(Exception) as caught:  # noqa: B017 — the type is the module's to choose
        run(exchange_code(CODE, CLIENT_ID, CLIENT_SECRET, client))

    assert_deliberate(caught.value, "read:org")


# --------------------------------------------------------------------------- #
# 3. identify
# --------------------------------------------------------------------------- #


def test_identity_is_revalidated_with_the_freshly_exchanged_token():
    """Nothing carried in the callback URL is trusted: the login comes from
    `GET /user` presented with the token itself, and the membership answer from the
    endpoint that asks about the token's own user.
    """
    client = github()

    user = run(identify(TOKEN, ORG, client))

    assert user == User(login=LOGIN, member=True)
    assert client.urls() == [USER_URL, MEMBERSHIP_URL]
    for request in client.requests:
        assert request.header("authorization") == f"Bearer {TOKEN}"
        assert request.header("accept") == "application/vnd.github+json"
        assert request.header("x-github-api-version") == "2022-11-28"
        assert request.header("user-agent")
        assert TOKEN not in request.url  # a token in a URL is a token in an access log


def test_a_concealed_member_is_still_a_member():
    """The test that stops the whole team being locked out.

    Concealed membership is GitHub's default. `/user/memberships/orgs/{org}` is
    evaluated as the token's own user, so it reports a concealed membership
    normally; `/orgs/{org}/members/{login}` is evaluated from the requester's
    perspective, and since the requester here is the person logging in, the
    question is circular. Probed live today:

        GET /orgs/kilnlab/members/<login>            -> 302 …/public_members/<login>
        GET /orgs/kilnlab/public_members/<login>     -> 404

    Both of those are stubbed below with those exact answers, so an implementation
    that reaches for them answers "not a member" for a member and fails here —
    which is the only place that failure is cheap.
    """
    client = github(
        extra={
            ("GET", REJECTED_URL): Response(302, headers={"location": REJECTED_REDIRECT}),
            ("GET", REJECTED_REDIRECT): Response(404, payload={"message": "Not Found"}),
            ("GET", REJECTED_PUBLIC): Response(404, payload={"message": "Not Found"}),
        }
    )

    user = run(identify(TOKEN, ORG, client))

    assert user.member is True
    assert MEMBERSHIP_URL in client.urls()
    assert not [url for url in client.urls() if "/public_members/" in url]


def test_a_person_who_is_not_in_the_org_is_identified_but_cannot_write():
    """404 is GitHub's "not affiliated". Reads need no login at all, so a non-member
    still gets a session — it simply carries `member=False`, and the write
    endpoints are the ones that read that flag.
    """
    client = github(membership_response=Response(404, payload={"message": "Not Found"}))

    user = run(identify(TOKEN, ORG, client))

    assert user == User(login=LOGIN, member=False)


def test_an_invitation_that_was_never_accepted_is_not_membership():
    """200 with `state: "pending"` is an invited user, and treating 200 as the whole
    answer hands write access to anyone who has merely been invited to kilnlab —
    including an invitation sent by mistake and never accepted.
    """
    client = github(membership_response=Response(200, payload=membership(state="pending")))

    assert run(identify(TOKEN, ORG, client)).member is False


def test_any_role_counts_as_membership():
    """`admin`, `member` and `billing_manager` are all in the org. Requiring `admin`
    would leave the planning tool writable by two people.
    """
    for role in ("admin", "member", "billing_manager"):
        client = github(membership_response=Response(200, payload=membership(role=role)))
        assert run(identify(TOKEN, ORG, client)).member is True, role


@pytest.mark.parametrize("status", [401, 403])
def test_a_broken_token_or_an_unapproved_app_is_never_a_yes(status: int):
    """403 means the token lacks `read:org` or the OAuth app is not approved by the
    org, and 401 means the token is revoked. Both are operator misconfigurations
    wearing a user's clothes: the one thing neither may become is `member=True`.

    Raising is a perfectly good answer here — /auth/callback can turn it into a
    page that says what to fix — so the assertion is on the answer that is
    forbidden, not on the mechanism.
    """
    client = github(membership_response=Response(status, payload={"message": "Forbidden"}))

    try:
        user = run(identify(TOKEN, ORG, client))
    except Exception as error:  # the module chooses whether to raise; both answers are fine
        assert not isinstance(error, INCIDENTAL), type(error).__name__
        return
    assert user.member is False


# --------------------------------------------------------------------------- #
# 4. The session
#
# Signed, not encrypted, and holding two fields. Everything below is a way the
# cookie can lie.
# --------------------------------------------------------------------------- #


def _decode(part: str):
    chunk = part.encode() + b"=" * (-len(part) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(chunk))
    except Exception:  # most segments of a signed cookie are not the payload
        return None


def _encode(payload: dict) -> str:
    packed = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(packed).decode().rstrip("=")


def payload_of(cookie: str) -> dict:
    """The readable payload of the signed cookie.

    The cookie is signed, not encrypted — the person holding it can and will read
    it. That is fine for a username and a boolean, and it is exactly why the tests
    below check what is *in* there.
    """
    for part in cookie.split("."):
        decoded = _decode(part)
        if isinstance(decoded, dict):
            return decoded
    pytest.fail(f"no readable payload in {cookie!r}; a signed cookie is base64, not opaque")


def forge(cookie: str, **changes) -> str:
    """Rewrite the payload and keep the original signature — the attack itself.

    The payload is base64, so this is what "editing the cookie" actually looks
    like: decode, change `member`, re-encode, hand it back unchanged otherwise.
    """
    parts = cookie.split(".")
    for i, part in enumerate(parts):
        decoded = _decode(part)
        if isinstance(decoded, dict):
            parts[i] = _encode({**decoded, **changes})
            return ".".join(parts)
    pytest.fail(f"no readable payload in {cookie!r}; a signed cookie is base64, not opaque")


def test_a_session_round_trips_through_the_cookie():
    user = User(login=LOGIN, member=True)

    assert read_session(sign_session(user, SECRET), SECRET) == user


def test_the_member_flag_travels_inside_the_signature():
    """Sign the whole `User`, not just the login. Signing the login and looking the
    membership up from somewhere mutable at read time is how a 24-hour cookie turns
    into an unbounded one, and how a GitHub outage turns into "nobody can save".
    """
    member = sign_session(User(login=LOGIN, member=True), SECRET)
    outsider = sign_session(User(login=LOGIN, member=False), SECRET)

    assert read_session(member, SECRET).member is True
    assert read_session(outsider, SECRET).member is False
    assert member != outsider


def test_editing_member_true_into_a_cookie_does_not_survive_the_signature():
    """The obvious attack, because the payload is readable: log in as anybody, flip
    the boolean, get write access to the plan. The signature is the only thing
    standing between a GitHub account and a commit in a kilnlab repository.
    """
    cookie = sign_session(User(login="mallory", member=False), SECRET)
    assert payload_of(cookie)["member"] is False  # readable, as designed

    forged = forge(cookie, member=True)
    assert payload_of(forged)["member"] is True and forged != cookie

    assert read_session(forged, SECRET) is None


@pytest.mark.parametrize("kind", ["payload", "signature", "junk", "empty", "not-a-cookie"])
def test_a_cookie_we_did_not_sign_is_no_session_and_is_not_an_exception(kind: str):
    """Never trust a cookie you did not sign — and a rejected cookie is a logged-out
    person, not a 500. Anyone can put anything in a cookie jar; the reader has to
    treat all of it as an anonymous request.
    """
    cookie = sign_session(User(login=LOGIN, member=True), SECRET)
    head, _, tail = cookie.rpartition(".")

    def flip(text: str) -> str:
        return ("B" if text[:1] == "A" else "A") + text[1:]

    candidate = {
        "payload": flip(cookie),
        "signature": f"{head}.{flip(tail)}",
        "junk": "\x00 not base64 at all ÿ",
        "empty": "",
        "not-a-cookie": cookie.replace(".", ""),
    }[kind]
    assert candidate != cookie

    assert read_session(candidate, SECRET) is None


def test_a_cookie_signed_with_another_secret_is_rejected():
    """Rotating the signing secret logs everyone out. That is the intended incident
    response, so it has to be a clean logout rather than an error page.
    """
    cookie = sign_session(User(login=LOGIN, member=True), SECRET)

    assert read_session(cookie, "a-different-secret") is None


def test_no_cookie_at_all_is_an_anonymous_reader():
    """Reads need no login, so the absence of a cookie is the normal case on every
    single page load — `None`, not an error, and no branch anywhere that guesses.
    """
    assert read_session(None, SECRET) is None


def test_a_session_older_than_its_max_age_is_refused(monkeypatch: pytest.MonkeyPatch):
    """The cookie is an unrevocable bearer assertion of `member: true`, so its
    lifetime is exactly how long a departed kilnlab member keeps write access. 24
    hours is that number, and the signature's `max_age` — not the browser's
    Max-Age, which the holder controls — is what enforces it.

    The clock is moved rather than the test slept: `time.time()` is what a
    timestamped signer stamps and compares against.
    """
    signed_at = time.time()
    cookie = sign_session(User(login=LOGIN, member=True), SECRET)

    monkeypatch.setattr(time, "time", lambda: signed_at + 86_399)
    assert read_session(cookie, SECRET) is not None  # inside the default day

    monkeypatch.setattr(time, "time", lambda: signed_at + 86_401)
    assert read_session(cookie, SECRET) is None
    assert read_session(cookie, SECRET, max_age=172_800) is not None  # the bound is a parameter


def test_the_token_that_proved_the_identity_is_not_in_the_session():
    """The decision the whole module is shaped around, asserted directly.

    The OAuth token establishes identity once and is dropped on the floor. If it
    were carried in the session instead, the cookie jar of thirty people would be a
    store of live GitHub credentials — and the reason `repo` was refused would have
    been given away for free by the session layer.
    """
    client = github()
    user = run(identify(TOKEN, ORG, client))
    cookie = sign_session(user, SECRET)

    assert user.model_dump() == {"login": LOGIN, "member": True}
    assert set(User.model_fields) == {"login", "member"}
    assert TOKEN not in cookie
    assert TOKEN not in json.dumps(payload_of(cookie))
    assert "token" not in json.dumps(payload_of(cookie)).lower()
    assert read_session(cookie, SECRET).model_dump() == {"login": LOGIN, "member": True}
