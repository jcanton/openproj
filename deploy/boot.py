"""Container entrypoint: make sure the plan is on disk, then serve it.

Cloud Run's filesystem is in-memory and the service scales to zero, so a cold
start begins with nothing. The durable copy is the git remote; this fetches it
once and hands over to the server, which pushes every commit back.

Cloning at boot rather than baking the plan into the image keeps the image
independent of the data: the same container serves any plan repository, and a
plan change never triggers an image build.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pygit2

from openproj.github import GitHubApp


def main() -> int:
    repo = Path(os.environ.get("OPENPROJ_REPO", "/srv/plan.git"))
    remote = os.environ.get("OPENPROJ_REMOTE", "")
    # The same credential the server pushes with. The clone needs it too, and a
    # private plan repository is the ordinary case rather than the exception —
    # without this the first boot fails with libgit2's "unexpected HTTP status
    # code: 404", which reads like a wrong URL and is a missing token.
    app = GitHubApp.from_environment(dict(os.environ))

    if not repo.exists():
        if not remote:
            print("OPENPROJ_REMOTE is unset and there is no local plan repository", file=sys.stderr)
            return 2
        print(f"cloning {remote.split('@')[-1]} into {repo}", flush=True)
        pygit2.clone_repository(
            remote, str(repo), bare=True, callbacks=app.callbacks() if app else None
        )

    return subprocess.call(
        [
            sys.executable,
            "-m",
            "openproj.cli",
            "serve",
            "--repo",
            str(repo),
            "--auth",
            os.environ.get("OPENPROJ_AUTH", "github"),
            "--org",
            os.environ.get("OPENPROJ_ORG", "C2SM"),
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "8080"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
