"""The credential the server pushes with.

Nothing here talks to GitHub. What is worth pinning is the shape of the assertion
we sign, when a cached token is thrown away, and that a deployment which is only
half configured is refused rather than left pushing anonymously.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from openproj.github import GitHubApp, app_jwt, open_pull_requests


@pytest.fixture(scope="module")
def pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def unpad(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def segments(token: str) -> tuple[dict, dict, bytes]:
    head, claims, signature = token.split(".")
    return json.loads(unpad(head)), json.loads(unpad(claims)), unpad(signature)


def test_the_assertion_is_one_github_would_accept(pem: str):
    """RS256 over base64url with no padding, `iss` the app id, and a life inside
    the ten minutes GitHub allows. `iat` is backdated a minute because a container
    clock a few seconds ahead of theirs is ordinary, and they reject a token
    issued in the future."""
    head, claims, signature = segments(app_jwt("123456", pem, now=1_700_000_000))

    assert head == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == "123456"
    assert claims["iat"] == 1_700_000_000 - 60
    assert claims["exp"] - claims["iat"] <= 600
    assert len(signature) == 256


def test_the_assertion_is_actually_signed(pem: str):
    """A JWT nobody verified is three base64 blobs. This is the only test here
    that would catch a signature built over the wrong bytes."""
    token = app_jwt("123456", pem, now=1_700_000_000)
    signed = token.rsplit(".", 1)[0]
    _, _, signature = segments(token)

    serialization.load_pem_private_key(pem.encode(), password=None).public_key().verify(
        signature, signed.encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_a_token_is_reused_until_it_is_nearly_out(pem: str, monkeypatch):
    """A betting table is a burst of writes, and two API calls plus 300ms in front
    of each one is a burst that feels broken. Re-minted inside a margin rather
    than on failure, so "it expired half way through a push" cannot happen."""
    minted = []

    def fake(self, now):
        minted.append(now)
        return f"token-{len(minted)}", now + 3600

    monkeypatch.setattr(GitHubApp, "_mint", fake)
    app = GitHubApp("1", "2", pem)

    assert app.token(now=0) == "token-1"
    assert app.token(now=60) == "token-1", "still fresh"
    assert app.token(now=3000) == "token-1", "inside the hour, outside the margin"
    assert app.token(now=3400) == "token-2", "within five minutes of expiry"
    assert minted == [0, 3400]


def test_half_a_configuration_is_no_configuration(tmp_path: Path, pem: str):
    """Two of the three is a deployment somebody stopped half way through, and
    building the credential from it would push anonymously and look like it
    worked."""
    key = tmp_path / "app.pem"
    key.write_text(pem)
    whole = {
        "OPENPROJ_APP_ID": "1",
        "OPENPROJ_INSTALLATION_ID": "2",
        "OPENPROJ_APP_KEY": str(key),
    }

    assert GitHubApp.from_environment(whole) is not None
    assert GitHubApp.from_environment({}) is None
    for missing in whole:
        assert GitHubApp.from_environment({k: v for k, v in whole.items() if k != missing}) is None
    assert GitHubApp.from_environment({**whole, "OPENPROJ_APP_ID": "   "}) is None


def test_a_remote_that_needs_a_credential_and_has_none_is_refused(tmp_path: Path):
    """`_finish` turns an unreachable remote into `pushed: False` and carries on,
    which is right for a network blip and wrong for a deployment that can never
    push: the tool would look like it was working while every commit stayed on one
    container's disk until it was replaced."""
    import pygit2

    from openproj.web import create_app

    repo = tmp_path / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")

    with pytest.raises(ValueError, match="needs a credential"):
        create_app(repo, remote="https://github.com/jackdawrie/kiln4py-plan.git")

    # A `file://` remote is the local case the tests and every development run
    # use, and it needs nothing.
    create_app(repo, remote=f"file://{tmp_path}/other.git")


def test_the_credential_is_asked_for_every_push_not_held_from_startup(tmp_path: Path):
    """An installation token lives under an hour and a server lives for weeks. A
    credential fetched once at startup stops working on a Tuesday afternoon, with
    no deploy to blame it on.

    Counted against the network calls the file actually makes rather than against
    a number written down here. It used to assert exactly two — "push and fetch
    both" — which was true when those were the only two. The background pusher
    added three more (its own push, its recovery fetch, and the push that strands
    a commit it could not replay), and a hardcoded count answers a change in the
    file's shape with a failure about credentials. What has to stay true is that
    EVERY one of them asks, and that none is handed `None`.
    """
    import inspect
    import re

    from openproj.store import Store

    source = inspect.getsource(Store)
    reaching = re.findall(r"remotes\[_ORIGIN\]\.(?:push|fetch)\(", source)

    assert reaching, "no network call found at all — this test has stopped watching anything"
    assert source.count("callbacks=self._callbacks()") == len(reaching), (
        f"{len(reaching)} calls reach the remote and "
        f"{source.count('callbacks=self._callbacks()')} of them mint a credential; "
        "a token fetched once at startup stops working on a Tuesday afternoon"
    )
    assert "callbacks=None" not in source


def test_a_half_set_environment_names_the_variable_it_wants(tmp_path: Path, pem: str):
    """`from_environment` returning None is right, but on its own it surfaces as
    `'NoneType' object has no attribute 'token'` several frames later — which
    names neither the variable nor the mistake. This is what the runbook's check
    and the startup refusal both read."""
    key = tmp_path / "app.pem"
    key.write_text(pem)

    assert GitHubApp.missing({}) == list(GitHubApp.NEEDS)
    assert GitHubApp.missing(
        {"OPENPROJ_INSTALLATION_ID": "154481476", "OPENPROJ_APP_KEY": str(key)}
    ) == ["OPENPROJ_APP_ID"]
    assert (
        GitHubApp.missing(
            {"OPENPROJ_APP_ID": "1", "OPENPROJ_INSTALLATION_ID": "2", "OPENPROJ_APP_KEY": str(key)}
        )
        == []
    )


def test_the_startup_refusal_says_which_variable_is_unset(tmp_path: Path, monkeypatch):
    import pygit2

    from openproj.web import create_app

    repo = tmp_path / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    for name in GitHubApp.NEEDS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENPROJ_APP_ID", "123456")

    with pytest.raises(ValueError) as refusal:
        create_app(repo, remote="https://github.com/jackdawrie/kiln4py-plan.git")

    assert "OPENPROJ_INSTALLATION_ID" in str(refusal.value)
    assert "OPENPROJ_APP_KEY" in str(refusal.value)
    assert "OPENPROJ_APP_ID" not in str(refusal.value), "that one is set"


def _pulls(number: int, title: str) -> dict:
    return {"number": number, "title": title, "state": "open", "user": {"login": "x"}}


def test_the_open_pull_requests_are_read_down_to_what_a_completion_needs():
    """A number and a title, and nothing else off the answer.

    GitHub sends forty fields about a pull request. The completion needs the
    number nobody remembers and the title that finds it; every other one is bytes
    on a page and a field to keep in step with an API somebody else versions.

    One page of a hundred, most recently updated first, and no `Link` following —
    a popup offers eight rows and filters as somebody types, so a loop over a
    paginated list is a request count nobody predicted against a rate limit
    somebody else shares.
    """
    asked = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=[_pulls(1403, "Halo exchange"), _pulls(9, "Two")])

    got = open_pull_requests("kilnlab/kiln4py", transport=httpx.MockTransport(answer))

    assert got == [
        {"number": 1403, "title": "Halo exchange"},
        {"number": 9, "title": "Two"},
    ]
    assert len(asked) == 1, "one page, one call"
    query = dict(asked[0].url.params)
    assert query == {"state": "open", "per_page": "100", "sort": "updated", "direction": "desc"}, (
        query
    )
    assert asked[0].url.path == "/repos/kilnlab/kiln4py/pulls"
    assert "authorization" not in asked[0].headers, "asked as somebody with no App"


def test_a_token_the_code_repository_refuses_falls_back_to_asking_anonymously(
    pem: str, monkeypatch
):
    """The App's installation is scoped to the PLAN repository, and that
    narrowness is the whole argument for using an App at all.

    So a token minted for it is refused by `kilnlab/kiln4py` unless somebody has
    installed the App there too — and both deployments have to work: the one
    where they have (5,000 requests an hour, private repositories) and the one
    where they have not (the anonymous limit, public ones).

    A 500 is deliberately NOT retried: a second identical request does not
    improve a server error, and the caller treats a refusal as "offer what the
    corpus cites" either way.
    """
    monkeypatch.setattr(GitHubApp, "_mint", lambda self, now: ("installation-token", now + 3600))
    seen: list[str | None] = []

    def refuse_then_answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if request.headers.get("authorization"):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=[_pulls(1403, "Halo exchange")])

    app = GitHubApp("1", "2", pem, transport=httpx.MockTransport(refuse_then_answer))
    assert open_pull_requests("kilnlab/kiln4py", app) == [
        {"number": 1403, "title": "Halo exchange"}
    ]
    assert seen == ["Bearer installation-token", None], seen

    # The App's own transport is honoured without being handed over a second
    # time — two names for one seam is two ways for a test to think it had
    # stubbed the network.
    server_error = []

    def broken(request: httpx.Request) -> httpx.Response:
        server_error.append(request.headers.get("authorization"))
        return httpx.Response(500, text="no")

    app.transport = httpx.MockTransport(broken)
    with pytest.raises(httpx.HTTPStatusError):
        open_pull_requests("kilnlab/kiln4py", app)
    assert server_error == ["Bearer installation-token"], (
        f"a 500 was retried anonymously: {server_error}"
    )
