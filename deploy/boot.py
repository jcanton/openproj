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
import sys
from pathlib import Path

import pygit2

from openproj.github import GitHubApp


def main() -> int:
    # Cloud Run terminates TLS upstream and forwards over plain HTTP from an
    # address that is not loopback, so uvicorn's default of trusting
    # `X-Forwarded-Proto` only from 127.0.0.1 drops it — and the app then believes
    # a TLS-only service is plain HTTP. Set here rather than in the CLI because
    # `K_SERVICE` is Cloud Run stating where this is running; the same image run
    # on a laptop keeps the careful default.
    if os.environ.get("K_SERVICE"):
        os.environ.setdefault("OPENPROJ_FORWARDED_ALLOW_IPS", "*")

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

    # `execv` and not `subprocess.call`, and this is a signal-handling fix rather
    # than a tidy-up. The Dockerfile's CMD makes this file PID 1; it installs no
    # signal handler; Python leaves SIGTERM at SIG_DFL; and the kernel DISCARDS a
    # default-disposition signal sent to PID 1. So Cloud Run's SIGTERM reached a
    # process that ignored it, the server underneath never heard about the
    # shutdown, and `Server.handle_exit` — which exists so the streams close
    # themselves while uvicorn waits politely — had never once run in production.
    # Neither had the co-editing room's flush, which commits what somebody has
    # typed and not yet saved. Ten silent seconds, then SIGKILL.
    #
    # Replacing this process rather than forwarding the signal to a child: there
    # is then no wrapper to keep in step, the server's exit status is the
    # container's directly, and there is no window in which a signal arrives
    # before the handler is installed. Everything above has already run — the
    # clone is done — so there is nothing left for this process to do.
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "openproj.cli",
            "serve",
            "--repo",
            str(repo),
            "--auth",
            os.environ.get("OPENPROJ_AUTH", "github"),
            # `serve` reads OPENPROJ_ORG itself and refuses github auth without
            # one; nothing here supplies a team's org on a deployment's behalf.
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "8080"),
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
