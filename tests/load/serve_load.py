"""One `openproj serve`, configured the way the deployment is, with a shimmed
remote round trip.

    .venv/bin/python tests/load/serve_load.py <repo.git> <port>

Everything else arrives in the environment, exactly as `cli._serve` reads it —
`OPENPROJ_SECRET`, `OPENPROJ_REMOTE`, plus `LOAD_RTT_MS` and `LOAD_LOGIN` which
belong to this harness. Configuring the server through the same variables the
container sets is the point: a harness that reaches past the CLI and builds its
own app is measuring a deployment nobody has.

Two differences from `tests/load/server.py`, which is the earlier phase's
instrument and stays as it is:

* the server is `cli._exit_aware_server`, not a bare `uvicorn.run`. That hook is
  what sets `app.state.closing` when SIGTERM arrives, which is what lets
  `_watch` make a room's last commit inside the graceful window. A load harness
  that used a plain uvicorn would report every room's text as lost at shutdown
  and the cause would be the harness.
* `LOAD_RTT_MS` is read here rather than passed positionally, so the same
  command line serves every scenario.

The RTT shim itself is imported from `server.py` rather than written twice. It
wraps `pygit2.Remote.push`/`.fetch` from OUTSIDE the application: `src/openproj/`
is byte-for-byte what is deployed, which is the whole rule of this audit.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from server import shim  # noqa: E402  - tests/load/server.py


def charge_accept(ms: float) -> None:
    """Make `await socket.accept()` suspend, the way one of uvicorn's two
    websocket implementations does.

    This is not a fault injection, it is the OTHER supported configuration.
    uvicorn ships two: with `wsproto` installed (which is what this project
    depends on) `WSProtocol.send` writes the accept straight to the transport
    after `await self.writable.wait()`, an already-set `asyncio.Event`, so the
    accept performs no suspension at all. With `websockets` installed — which
    uvicorn prefers whenever it is importable — `WebSocketProtocol.asgi_send`
    ends the accept branch with `await self.handshake_completed_event.wait()`,
    an event set by a different task, which does suspend.

    `web.py`'s join path reads `store.head()` before the accept and uses that
    commit after it, in `room.absorb(_body_at(head, path))` and
    `room.settled(head, ...)`. Whether those two lines straddle a suspension is
    therefore decided by which websocket library is installed. This is how a run
    measures the second case without installing it, and `src/openproj/` is
    untouched either way — the wrapper is on Starlette's `WebSocket`, from out
    here, exactly as `LOAD_RTT_MS` wraps `pygit2`.
    """
    import asyncio  # noqa: PLC0415

    from starlette.websockets import WebSocket  # noqa: PLC0415

    original = WebSocket.accept

    async def accept(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        await asyncio.sleep(ms / 1000.0)
        return await original(self, *args, **kwargs)

    WebSocket.accept = accept


def main() -> None:
    repo, port = Path(sys.argv[1]), int(sys.argv[2])
    shim(float(os.environ.get("LOAD_RTT_MS", "0")))
    if os.environ.get("LOAD_ACCEPT_YIELD"):
        charge_accept(float(os.environ["LOAD_ACCEPT_YIELD"]))

    from openproj.cli import _exit_aware_server  # noqa: PLC0415
    from openproj.web import create_app  # noqa: PLC0415

    app = create_app(
        repo,
        auth="dev",
        secret=os.environ.get("OPENPROJ_SECRET", "dev-secret"),
        remote=os.environ.get("OPENPROJ_REMOTE", ""),
        # Deliberately not a real name. Under `--auth dev` a cookie that does not
        # verify is not an error — `writer` invents this login and permits the
        # write — so a harness whose signing secret disagreed with the server's
        # would run twenty people who were all silently one person, and every
        # attribution measurement would be of the harness. `verify.py` fails a run
        # that finds this name in the commit log.
        dev_login=os.environ.get("LOAD_LOGIN", "unsigned"),
        # The corpus is written around this day. `date.today()` would make two
        # runs a week apart different plans.
        today=date(2026, 8, 17),
    )
    # Startup owns the first history walk, as `cli._serve` does, so it can never
    # ride a request and be measured as one.
    app.state.warm_edited()
    _exit_aware_server(app, "127.0.0.1", port).run()


if __name__ == "__main__":
    main()
