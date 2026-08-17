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
    """Mints and holds one installation token, and hands out git credentials.

    The token is cached because a betting table is a burst of writes and each one
    would otherwise cost two API calls and ~300ms before any git happened. It is
    re-minted inside a safety margin rather than on failure, so "the token expired
    half way through a push" is not a state this can reach.
    """

    app_id: str
    installation_id: str
    private_key_pem: str
    _token: str = field(default="", repr=False)
    _expires: float = 0.0

    @classmethod
    def from_environment(cls, environ: dict[str, str]) -> GitHubApp | None:
        """Built only when all three are present. Two of three is a deployment
        half-configured, and pushing anonymously would look like it worked."""
        app_id = environ.get("OPENPROJ_APP_ID", "").strip()
        installation = environ.get("OPENPROJ_INSTALLATION_ID", "").strip()
        key_path = environ.get("OPENPROJ_APP_KEY", "").strip()
        if not (app_id and installation and key_path):
            return None
        return cls(app_id, installation, Path(key_path).read_text(encoding="utf-8"))

    def token(self, now: float | None = None) -> str:
        moment = now if now is not None else time.time()
        if self._token and moment < self._expires - _MARGIN_SECONDS:
            return self._token
        self._token, self._expires = self._mint(moment)
        return self._token

    def _mint(self, now: float) -> tuple[str, float]:
        response = httpx.post(
            f"{_API}/app/installations/{self.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt(self.app_id, self.private_key_pem, now)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10.0,
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
