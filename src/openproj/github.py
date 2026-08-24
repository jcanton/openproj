"""A GitHub App installation token, minted when the store needs to push.

Why an App and not a token somebody pastes: an installation token lives under an
hour and is scoped to the repositories the App is installed on. A fine-grained
PAT lives up to a year and dies when the person who made it leaves; a deploy key
lives forever and is scoped to one repository but cannot be attributed. The App
is the only one of the three that is short-lived, not tied to a person, and
narrow — and the narrowness is not a setting on the token, it is the installation
itself, which is why widening it takes a deliberate act in the org rather than an
edited environment variable.

Nothing here is imported unless a deployment configures it. The tool runs against
a local bare repository with no credential at all, which is what the tests and
every development run do.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_API = "https://api.github.com"
# GitHub refuses a JWT that claims more than ten minutes. Nine leaves room for a
# clock a little ahead of theirs without asking for a token they will reject.
_JWT_SECONDS = 9 * 60
# Re-minted this long before it expires. An installation token lasts an hour; a
# write that starts inside the margin cannot finish outside it.
_MARGIN_SECONDS = 5 * 60


def _b64(raw: bytes) -> bytes:
    """base64url without padding, which is what a JWT is made of."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def plan_repository(remote: str) -> str:
    """The `owner/repo` a remote URL names on github.com, or "" for any other.

    An allowlist of exactly the one shape a deployment writes —
    `https://github.com/<owner>/<repo>.git`, per `gcloud_deploy.sh` — rather
    than a parser for everything git accepts: the store pushes over https with
    an installation token, so an ssh or `file://` remote has nowhere to open a
    pull request anyway, and a denylist of URL spellings is never finished.
    """
    prefix = "https://github.com/"
    if not remote.startswith(prefix):
        return ""
    parts = remote.removeprefix(prefix).strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(parts):
        return ""
    return "/".join(parts)


def app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    """A short-lived assertion that we are the App, signed with its own key.

    `iat` is backdated a minute: GitHub rejects a token issued in the future, and
    a container clock a few seconds ahead of theirs is the ordinary case rather
    than the exceptional one.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iat": issued - 60, "exp": issued + _JWT_SECONDS, "iss": app_id}
    signing_input = b".".join(
        _b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
    )
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64(signature)).decode()


@dataclass
class GitHubApp:
    """Mints and holds one installation token, hands out git credentials, and
    opens the pull request that makes a parked branch visible.

    The token is cached because a betting table is a burst of writes and each one
    would otherwise cost two API calls and ~300ms before any git happened. It is
    re-minted inside a safety margin rather than on failure, so "the token expired
    half way through a push" is not a state this can reach.
    """

    app_id: str
    installation_id: str
    private_key_pem: str
    # The plan's `owner/repo` on GitHub, for opening a pull request when the
    # pusher parks a branch. Parsed from the same OPENPROJ_REMOTE the store
    # pushes to — one deployment variable, two readers, no second name to fall
    # out of step — and empty when the remote is not on github.com, which makes
    # `offer_pull_request` refuse rather than guess a host.
    repository: str = ""
    # Every HTTP call this object makes goes through `_client`, which honours
    # this: an httpx transport a test can answer from without a socket. None is
    # the real network.
    transport: httpx.BaseTransport | None = None
    _token: str = field(default="", repr=False)
    _expires: float = 0.0

    NEEDS = ("OPENPROJ_APP_ID", "OPENPROJ_INSTALLATION_ID", "OPENPROJ_APP_KEY")

    @classmethod
    def missing(cls, environ: dict[str, str]) -> list[str]:
        """Which of the three are absent, so a caller can say so.

        Returning None from `from_environment` is right — two of three is a
        deployment somebody stopped half way through — but on its own it produces
        `'NoneType' object has no attribute 'token'` several frames later, which
        names neither the variable nor the mistake.
        """
        return [name for name in cls.NEEDS if not environ.get(name, "").strip()]

    @classmethod
    def from_environment(cls, environ: dict[str, str]) -> GitHubApp | None:
        """Built only when all three are present. Two of three is a deployment
        half-configured, and pushing anonymously would look like it worked."""
        if cls.missing(environ):
            return None
        return cls(
            environ["OPENPROJ_APP_ID"].strip(),
            environ["OPENPROJ_INSTALLATION_ID"].strip(),
            Path(environ["OPENPROJ_APP_KEY"].strip()).read_text(encoding="utf-8"),
            # Read here rather than passed in: the App and the remote already
            # come from one environment, and a second parameter would be a
            # second chance for them to name different repositories.
            repository=plan_repository(environ.get("OPENPROJ_REMOTE", "").strip()),
        )

    def token(self, now: float | None = None) -> str:
        moment = now if now is not None else time.time()
        if self._token and moment < self._expires - _MARGIN_SECONDS:
            return self._token
        self._token, self._expires = self._mint(moment)
        return self._token

    def _client(self) -> httpx.Client:
        """One construction site for every HTTP call this object makes, so a
        test that stubs `transport` has stubbed all of it — a second site would
        be the one call that still quietly reaches the network."""
        return httpx.Client(transport=self.transport, timeout=10.0)

    def _headers(self, bearer: str) -> dict[str, str]:
        """The API headers, once: minting sends the App JWT, everything after
        sends the installation token, and the other two headers must not drift
        between them."""
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def offer_pull_request(self, branch: str, title: str, body: str) -> None:
        """Open a pull request from a parked branch onto main.

        The installation was granted `pull_requests: write` for exactly this
        and stays `repository_selection: selected` — a ref and a PR on the
        plan, nothing else, so the push credential remains structurally
        incapable of touching source. Raises on any refusal, and the CALLER
        treats that as survivable: the branch is already durable on the remote
        by the time this is asked, the PR is only the visibility
        (docs/deferred-push.md), and the store logs rather than dies.
        """
        if not self.repository:
            raise ValueError(
                "the plan's remote is not on github.com, so there is no repository "
                "to open the pull request on"
            )
        with self._client() as client:
            response = client.post(
                f"{_API}/repos/{self.repository}/pulls",
                headers=self._headers(self.token()),
                json={"title": title, "head": branch, "base": "main", "body": body},
            )
        response.raise_for_status()

    def _mint(self, now: float) -> tuple[str, float]:
        with self._client() as client:
            response = client.post(
                f"{_API}/app/installations/{self.installation_id}/access_tokens",
                headers=self._headers(app_jwt(self.app_id, self.private_key_pem, now)),
            )
        response.raise_for_status()
        body = response.json()
        # Their `expires_at` is authoritative over any hour we assume, and it is
        # ISO-8601 with a Z. Parsed rather than trusted to be exactly 3600s away.
        from datetime import datetime

        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        return body["token"], expires.timestamp()

    def callbacks(self):
        """What pygit2 wants. `x-access-token` is the username GitHub expects for
        an installation token; the token itself goes in the password."""
        import pygit2

        return pygit2.RemoteCallbacks(
            credentials=pygit2.UserPass("x-access-token", self.token())
        )
