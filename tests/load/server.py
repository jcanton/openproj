"""Run one openproj server against a throwaway plan, for load measurement.

    .venv/bin/python tests/load/server.py <repo.git> <remote.git> <port> [rtt_ms]

`rtt_ms` shims `pygit2.Remote.push` and `.fetch` with a sleep, so a `file://`
remote on the same SSD can stand in for GitHub over HTTPS — the store's own
comment prices a round trip at about 600 ms, and a push that costs a
microsecond measures a machine nobody deploys on. **The shim is in this
harness, never in `src/openproj/`.** It wraps the library call from outside;
the application is byte-for-byte what is deployed.

Binds 127.0.0.1 only, on a port the caller names. It must be given a repository
nobody else is holding: `Store` takes an flock and a second one refuses.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import pygit2  # noqa: E402
import uvicorn  # noqa: E402


def shim(rtt_ms: float) -> None:
    """Charge every remote round trip `rtt_ms`, in the library, out of process
    reach of the application under test."""
    if rtt_ms <= 0:
        return
    delay = rtt_ms / 1000.0
    real_push, real_fetch = pygit2.Remote.push, pygit2.Remote.fetch

    def push(self, *a, **kw):
        time.sleep(delay)
        return real_push(self, *a, **kw)

    def fetch(self, *a, **kw):
        time.sleep(delay)
        return real_fetch(self, *a, **kw)

    pygit2.Remote.push = push
    pygit2.Remote.fetch = fetch


def main() -> None:
    repo, remote, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    rtt = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    shim(rtt)
    from openproj.web import create_app

    app = create_app(
        repo,
        auth="dev",
        secret="dev-secret",
        remote=f"file://{remote}" if str(remote) != "-" else "",
        dev_login=os.environ.get("LOAD_LOGIN", "jcanton"),
        today=date(2026, 8, 17),
    )
    app.state.warm_edited()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
