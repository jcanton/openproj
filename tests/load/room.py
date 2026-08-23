"""A room with many people in it, over real sockets, against a real server.

Not a test and never run by pytest: `tests/load/` is a measuring instrument.
Every probe here starts one `openproj serve` in a child process, drives it with
real TCP websockets for a bounded number of seconds, and kills the child in a
`finally` whether or not the probe succeeded.

**A real server in a child process, not `TestClient` and not an in-process
uvicorn.** Two reasons, and both are the point of the exercise. `TestClient`
speaks ASGI directly and its send never blocks, so backpressure — the whole
subject — does not exist under it. And the number that decides this deployment
is one vCPU: the server has to be a process whose CPU time can be read off
`ps` without the driver's own cost in it, because the driver holds fifteen
CRDT documents and would otherwise be measured as the server.

The driver is therefore deliberately cheap. Most participants read their frames
and drop them; only the pair that measures propagation applies them.

`plan_at` imports `tests/load/corpus.py`, which is another phase of this audit's
own instrument and is committed separately. A probe run without it fails at the
import rather than measuring the wrong thing.
"""

from __future__ import annotations

import base64
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from wsclient import Client  # noqa: E402

from openproj import coedit  # noqa: E402
from openproj.auth import User, sign_session  # noqa: E402
from openproj.web import SESSION_COOKIE  # noqa: E402

SECRET = "load-probe-secret"
# 8900-8999 by instruction: port 8000 is jcanton's.
PORT_BASE = 8930


def free_port(start: int = PORT_BASE) -> int:
    for port in range(start, start + 60):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port in 8900-8999")


class Server:
    """One `openproj serve`, on the loopback, killed on the way out.

    A context manager and not a fixture, so the kill is in a `finally` that runs
    on an exception, a KeyboardInterrupt and a normal return alike. `start_new_session`
    puts it in its own process group: uvicorn spawns nothing here, but a probe
    that is interrupted must not leave a server holding the plan's flock.
    """

    def __init__(self, repo: Path, port: int | None = None, remote: str = "") -> None:
        self.repo = repo
        self.port = port or free_port()
        self.remote = remote
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> Server:
        environment = dict(os.environ, OPENPROJ_SECRET=SECRET, PYTHONUNBUFFERED="1")
        if self.remote:
            environment["OPENPROJ_REMOTE"] = self.remote
        self.process = subprocess.Popen(
            [
                str(Path(sys.executable).parent / "openproj"),
                "serve",
                "--repo",
                str(self.repo),
                "--auth",
                "dev",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(ROOT),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(300):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(("127.0.0.1", self.port))
                    return self
                except OSError:
                    time.sleep(0.1)
        self.__exit__(None, None, None)
        raise RuntimeError("the server never came up")

    def __exit__(self, *_: object) -> None:
        if self.process is None:
            return
        with_group = self.process.pid
        for how in (signal.SIGTERM, signal.SIGKILL):
            if self.process.poll() is not None:
                break
            try:
                os.killpg(os.getpgid(with_group), how)
            except (ProcessLookupError, PermissionError):
                try:
                    self.process.send_signal(how)
                except ProcessLookupError:
                    break
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                continue
        self.process = None

    def cpu_seconds(self) -> float:
        """Cumulative CPU time of the server process, from `ps`.

        `ps -o time=` and not `/proc`: this is macOS. Resolution is one second,
        which is why every probe runs for at least sixty.
        """
        if self.process is None:
            return 0.0
        out = subprocess.run(
            ["ps", "-p", str(self.process.pid), "-o", "time="],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not out:
            return 0.0
        parts = out.replace("-", ":").split(":")
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds

    def rss_mb(self) -> float:
        if self.process is None:
            return 0.0
        out = subprocess.run(
            ["ps", "-p", str(self.process.pid), "-o", "rss="], capture_output=True, text=True
        ).stdout.strip()
        return float(out) / 1024 if out else 0.0


class Member:
    """One participant: a real socket, a reader thread, and optionally a document.

    `applies=False` is the ordinary background typist. They read every frame and
    drop it, which is what keeps this driver from being the thing under
    measurement — fifteen pycrdt documents applying eleven hundred updates a
    second is a bigger machine than the server. They still *drain*, so nobody in
    these probes is evicted for being slow unless the probe is about that.
    """

    def __init__(
        self,
        port: int,
        login: str,
        entity_id: str,
        client_id: int,
        applies: bool = False,
        receive_buffer: int = 0,
    ) -> None:
        self.login = login
        self.applies = applies
        self.frames = 0
        self.bytes = 0
        self.gone: str | None = None
        self.marks: dict[str, float] = {}
        self.told: list[dict] = []
        token = sign_session(User(login=login, member=True), SECRET)
        self.client = Client(
            "127.0.0.1",
            port,
            f"/api/coedit/{entity_id}",
            cookie=f"{SESSION_COOKIE}={token}",
            receive_buffer=receive_buffer,
        )
        self.doc = coedit.Doc(client_id=client_id)
        self.doc[coedit.BODY] = coedit.Text()
        self.text = self.doc[coedit.BODY]
        self.client.send_json({"t": "hello", "seed": None, "sv": None})
        welcome = self.client.receive_json()
        if welcome["t"] != "welcome":
            raise RuntimeError(f"{login} was not welcomed: {welcome}")
        self.welcome = welcome
        self.doc.apply_update(base64.b64decode(welcome["update"]))
        # No read deadline once the handshake is done. `wsclient` sets ten
        # seconds so a hung test fails rather than hangs; a load probe has
        # members who are legitimately silent for longer than that, and a
        # timeout here would be reported as a socket that died.
        if not receive_buffer:
            self.client._socket.settimeout(None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            while not self._stop.is_set():
                frame = self.client.receive_json()
                self.frames += 1
                self.bytes += len(json.dumps(frame))
                kind = frame.get("t")
                if kind in ("reload", "refused", "saved", "nothing", "saving", "who"):
                    self.told.append(dict(frame, at_=time.monotonic()))
                if kind == "reload":
                    self.gone = frame.get("why", "")
                    return
                if not self.applies:
                    continue
                carried = frame.get("u") if kind == "update" else frame.get("update")
                if carried:
                    with self._lock:
                        self.doc.apply_update(base64.b64decode(carried))
                    self._mark()
        except Exception as error:  # noqa: BLE001 - a socket ends in many ways
            self.gone = self.gone or f"!{type(error).__name__}"

    def _mark(self) -> None:
        """Timestamp every propagation marker this document has just gained."""
        now = time.monotonic()
        body = str(self.text)
        at = 0
        while True:
            at = body.find("§", at)
            if at < 0:
                return
            end = body.find("§", at + 1)
            if end < 0:
                return
            token = body[at + 1 : end]
            self.marks.setdefault(token, now)
            at = end + 1

    def type(self, at: int, what: str) -> None:
        with self._lock:
            before = self.doc.get_state()
            self.text.insert(at, what)
            update = self.doc.get_update(before)
        self.client.send_json({"t": "update", "u": base64.b64encode(update).decode()})

    def sit(self, at: int) -> None:
        self.client.send_json({"t": "at", "at": at})

    def save(self, fields: dict | None = None) -> None:
        self.client.send_json({"t": "save", "fields": fields or {}})

    def body(self) -> str:
        with self._lock:
            return str(self.text)

    def close(self, rude: bool = False) -> None:
        """Leave. `rude=True` is an RST rather than a close frame.

        A tab that is closed, a laptop lid, a tunnel that drops: none of them
        send a close frame, and the question a seat leak asks is whether the
        server's `finally` runs for that departure as well as for a polite one.
        """
        self._stop.set()
        try:
            if rude:
                self.client._socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, __import__("struct").pack("ii", 1, 0)
                )
                self.client._socket.close()
            else:
                self.client.close()
        except Exception:  # noqa: BLE001 - closing a closed socket
            pass


def plan_at(where: Path, pitches: int = 8, tasks_each: int = 3) -> tuple[Path, str]:
    """A small plan repository to hold a room, built by `corpus.py`."""
    import corpus  # noqa: PLC0415

    if where.exists():
        import shutil  # noqa: PLC0415

        shutil.rmtree(where)
    sha = corpus.build(where, pitches=pitches, tasks_each=tasks_each, notes=4, issues=4)
    return where, sha


sys.path.insert(0, str(Path(__file__).resolve().parent))


def stored_body(repo: Path, path: str) -> str:
    import pygit2  # noqa: PLC0415

    from openproj.model import split_front_matter  # noqa: PLC0415

    git = pygit2.Repository(str(repo))
    tip = git[git.references["refs/heads/main"].target]
    return split_front_matter((tip.tree / path).data.decode("utf-8"))[1]


def commits(repo: Path) -> list[tuple[str, str]]:
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(repo))
    return [
        (one.author.name, one.message.splitlines()[0])
        for one in git.walk(git.references["refs/heads/main"].target)
    ]


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "n": len(ordered),
        "p50": round(at(0.50) * 1000, 1),
        "p90": round(at(0.90) * 1000, 1),
        "p99": round(at(0.99) * 1000, 1),
        "max": round(ordered[-1] * 1000, 1),
    }
