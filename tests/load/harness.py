"""Set up and tear down one bounded load run: a plan, a remote, and a server.

    with Harness(seed=7, rtt_ms=600) as world:
        ...                              # world.base is http://127.0.0.1:89xx
    # the server is dead and the temporary directory is gone

What it builds, and why each piece is there:

**A bare plan repository**, from `tests/load/corpus.py`. That generator is the
one already in this directory and it builds a *bare* repository directly —
`tests/plans.py` writes a working tree of markdown, which is the wrong shape for
a server that has no working copy, so `--corpus plans` folds its output through
`build_plan_repository` rather than pointing the server at a directory. Both are
available because they measure different things: `corpus` writes shaping
documents of a realistic length with the seed's real config beside them, which is
what `build_index` and `render_detail` actually cost; `plans` writes the
containment and dependency shape at 208 and 518 records, which is what the graph
and the scheduler cost.

**A bare `origin` beside it, cloned from the plan.** This is not optional and it
is not a detail. `Store.write` pushes INSIDE the writer lock, so the write
throughput of the whole service is one over the push round trip — a harness with
no remote measures a machine nobody deploys on. A `file://` push on the same SSD
is still not GitHub, which is what `--rtt-ms` is for: `tests/load/server.py`'s
shim charges every `pygit2.Remote.push` and `.fetch` a sleep, in the library and
outside the application. `src/openproj/` is never touched.

**One server, on 127.0.0.1, on a port in 8900-8999**, killed by process group in
a `finally` and again by `atexit`. Port 8000 is jcanton's.

Nothing here can reach `seed/` or a plan of anybody's: the plan is built into a
`mkdtemp` and removed on the way out, and `--keep` is the only way to make it
survive a run.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
import room  # noqa: E402  - tests/load/room.py: the Server/Member machinery

from openproj.auth import User, sign_session  # noqa: E402
from openproj.web import SESSION_COOKIE  # noqa: E402

# One secret, named once. `room.Member` signs its own cookie with `room.SECRET`
# and the server reads `OPENPROJ_SECRET`; two spellings of it is a cookie that
# verifies as nobody, which under `--auth dev` is not an error but every
# participant silently becoming one person. Set below, next to the server that
# is handed the same string.
SECRET = "load-harness-secret"
room.SECRET = SECRET

# The login `--auth dev` invents when no cookie verifies. Not a person's name, so
# that a signing mismatch shows up in the commit log instead of hiding in it.
UNSIGNED = "unsigned"

# Six people off the corpus's own roster, so a commit author is a login the plan
# knows and the People page could draw.
PEOPLE = ["jcanton", "nfarabullini", "msimberg", "iomaganaris", "halungge", "edopao"]

_LIVE: list[subprocess.Popen] = []


def _kill_everything() -> None:
    for process in list(_LIVE):
        _kill(process)


atexit.register(_kill_everything)


def _kill(process: subprocess.Popen) -> None:
    """SIGTERM the process group, then SIGKILL it, then stop caring.

    The group and not the pid: a load harness that leaves a uvicorn holding the
    plan's flock is worse than no measurement, because the next run refuses to
    start and the reason is a pid in a file.
    """
    if process.poll() is not None:
        with contextlib.suppress(ValueError):
            _LIVE.remove(process)
        return
    for how in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            break
        try:
            os.killpg(os.getpgid(process.pid), how)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError):
                process.send_signal(how)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=12)
    with contextlib.suppress(ValueError):
        _LIVE.remove(process)


def free_port(low: int = 8900, high: int = 8999) -> int:
    """A port nothing is on, in the range this audit was given.

    Bound and released rather than guessed: two harnesses on one laptop is the
    normal case here, and a race on the bind is a server that never comes up with
    a message about an address in use.
    """
    for port in range(low, high + 1):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in {low}-{high}")


def cookie_for(login: str) -> str:
    """The `Cookie:` header value that signs a request in as `login`."""
    return f"{SESSION_COOKIE}={sign_session(User(login=login, member=True), SECRET)}"


@dataclass
class Corpus:
    """What was built, so a report can say what was measured."""

    kind: str
    records: int
    head: str


class Harness:
    """One world: a plan, a remote, a server. A context manager, so the kill is in
    a `finally` that runs on an exception and on Ctrl-C alike."""

    def __init__(
        self,
        seed: int = 7,
        rtt_ms: float = 0.0,
        corpus: str = "corpus",
        size: str = "medium",
        port: int | None = None,
        keep: bool = False,
        remote: bool = True,
        env: dict[str, str] | None = None,
    ) -> None:
        self.seed = seed
        self.rtt_ms = rtt_ms
        self.corpus_kind = corpus
        self.size = size
        self.keep = keep
        self.wants_remote = remote
        # Extra variables for the child, for a scenario that needs the server
        # configured differently — the same door `LOAD_RTT_MS` comes through, so
        # a shim stays outside the application and `src/openproj/` stays what is
        # deployed.
        self.env = dict(env or {})
        self.port = port or free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.work = Path(tempfile.mkdtemp(prefix="openproj-load-"))
        self.plan = self.work / "plan.git"
        self.origin = self.work / "origin.git"
        self.log = self.work / "server.log"
        self.process: subprocess.Popen | None = None
        self.corpus: Corpus | None = None
        self.startup_seconds: float | None = None

    # -- setup --------------------------------------------------------------

    SIZES = {
        # (pitches, tasks_each, notes, issues) for `corpus`, and
        # (projects, pitches, tasks) for `plans`.
        "small": ((8, 3, 4, 4), (2, 3, 3)),
        "medium": ((40, 10, 60, 60), (8, 6, 5)),
        "large": ((80, 20, 120, 120), (14, 6, 5)),
    }

    def _build_plan(self) -> Corpus:
        if self.corpus_kind == "corpus":
            import corpus as generator  # noqa: PLC0415

            pitches, tasks, notes, issues = self.SIZES[self.size][0]
            head = generator.build(self.plan, pitches, tasks, notes, issues)
            records = 1 + pitches + pitches * tasks + notes + issues
            return Corpus("corpus", records, head)

        # `tests/plans.py`, folded into a bare repository. It writes a working
        # tree, and a working tree is exactly what this server must not have —
        # `store.py`'s module docstring is about eight writers losing 87.5% of
        # their commits to `index.lock` — so the files are read back out and
        # committed with a TreeBuilder instead.
        import plans  # noqa: PLC0415

        from openproj.store import build_plan_repository  # noqa: PLC0415

        staging = self.work / "plan-tree"
        projects, pitches, tasks = self.SIZES[self.size][1]
        records = plans.build(staging, projects, pitches, tasks, seed=self.seed)
        files = {
            found.relative_to(staging).as_posix(): found.read_text(encoding="utf-8")
            for found in sorted(staging.rglob("*"))
            if found.is_file()
        }
        head = build_plan_repository(self.plan, files, "load corpus from tests/plans.py")
        shutil.rmtree(staging)
        return Corpus("plans", records, head)

    def _clone_origin(self) -> None:
        subprocess.run(
            ["git", "clone", "--bare", "--quiet", str(self.plan), str(self.origin)],
            check=True,
            capture_output=True,
        )

    def _start(self) -> None:
        environment = dict(
            os.environ,
            PYTHONUNBUFFERED="1",
            OPENPROJ_SECRET=SECRET,
            LOAD_LOGIN=UNSIGNED,
            LOAD_RTT_MS=str(self.rtt_ms),
            **self.env,
        )
        if self.wants_remote:
            environment["OPENPROJ_REMOTE"] = f"file://{self.origin}"
        else:
            environment.pop("OPENPROJ_REMOTE", None)
        handle = self.log.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, str(HERE / "serve_load.py"), str(self.plan), str(self.port)],
            cwd=str(ROOT),
            env=environment,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
        _LIVE.append(self.process)

    def _wait(self, seconds: float = 60.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"the server exited at once:\n{self.server_log()}")
            try:
                answer = httpx.get(f"{self.base}/api/health", timeout=2.0)
                if answer.status_code == 200 and answer.json().get("ok"):
                    return
            except Exception:  # noqa: BLE001 - not up yet is the ordinary case
                pass
            time.sleep(0.2)
        raise RuntimeError(f"the server never came up:\n{self.server_log()}")

    def __enter__(self) -> Harness:
        try:
            self.corpus = self._build_plan()
            if self.wants_remote:
                self._clone_origin()
            # Timed, because `--min-instances 0` is in the deploy line: the
            # instance is gone after a few idle minutes and the next person to
            # open the plan pays a process start, an import, and the history
            # walk `serve_load.py` does before uvicorn binds. Not the container's
            # own start — that is Cloud Run's and is not on this laptop — but
            # everything after it, which is the part this repository owns.
            begun = time.monotonic()
            self._start()
            self._wait()
            self.startup_seconds = round(time.monotonic() - begun, 2)
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
        if not self.keep:
            shutil.rmtree(self.work, ignore_errors=True)

    # -- during and after ---------------------------------------------------

    def stop(self) -> None:
        """Stop the server and leave the repositories readable.

        SIGTERM first and a real wait, because that is what Cloud Run sends and
        because the graceful path is where a room's last commit happens. A
        harness that SIGKILLed here would report data loss it had caused itself.
        """
        if self.process is not None:
            _kill(self.process)
            self.process = None

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def server_log(self) -> str:
        return self.log.read_text(errors="replace") if self.log.exists() else ""

    def cpu_seconds(self) -> float:
        """Cumulative CPU of the server, from `ps`. macOS, so one-second
        resolution — which is why a run is 60 s and not 6."""
        if self.process is None:
            return 0.0
        out = subprocess.run(
            ["ps", "-p", str(self.process.pid), "-o", "time="], capture_output=True, text=True
        ).stdout.strip()
        if not out:
            return 0.0
        seconds = 0.0
        for part in out.replace("-", ":").split(":"):
            seconds = seconds * 60 + float(part)
        return seconds

    def rss_mb(self) -> float:
        if self.process is None:
            return 0.0
        out = subprocess.run(
            ["ps", "-p", str(self.process.pid), "-o", "rss="], capture_output=True, text=True
        ).stdout.strip()
        return round(float(out) / 1024, 1) if out else 0.0

    def entity_ids(self, prefix: str = "task-") -> list[str]:
        """The ids a driver may aim at, sorted so two runs pick the same ones."""
        payload = httpx.get(f"{self.base}/api/index.json", timeout=30.0).json()
        return sorted(i for i in payload["entities"] if i.startswith(prefix))

    def describe(self) -> dict:
        return {
            "corpus": self.corpus_kind,
            "size": self.size,
            "records": self.corpus.records if self.corpus else None,
            "base_commit": (self.corpus.head[:10] if self.corpus else None),
            "rtt_ms": self.rtt_ms,
            "env": self.env,
            "remote": "file://origin.git" if self.wants_remote else None,
            "port": self.port,
            "startup_seconds": self.startup_seconds,
            "work": str(self.work),
        }


# -- reading the repositories from outside the server -----------------------
#
# The harness may not open a `Store`: it takes an exclusive flock, and the server
# is holding it. So these read the bare repository with pygit2 directly, the same
# way `store.py` does, and never write.


def tree_paths(repo: Path, commit: str) -> list[str]:
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(repo))
    out: list[str] = []

    def walk(tree, prefix: str) -> None:
        for entry in tree:
            here = f"{prefix}{entry.name}"
            if entry.type_str == "tree":
                walk(git[entry.id], f"{here}/")
            else:
                out.append(here)

    walk(git[commit].tree, "")
    return sorted(out)


def read_blob(repo: Path, commit: str, path: str) -> str | None:
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(repo))
    try:
        return (git[commit].tree / path).data.decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return None


def record_paths(repo: Path, commit: str) -> dict[str, str]:
    """`{entity id: path}` at a commit.

    The same rule `web.py:_path_for` uses — a record's file is `<id>.md` or
    `<id>--<slug>.md` inside its kind's directory — asked of `record_paths_in`
    and of `KINDS` rather than restated, so a directory added to the ladder
    lands here on the commit that adds it.
    """
    from openproj.model import KINDS, record_paths_in  # noqa: PLC0415

    directories = tuple(rung.directory for rung in KINDS)
    paths, _ = record_paths_in(directories, tree_paths(repo, commit))
    out: dict[str, str] = {}
    for path in paths:
        directory, _, name = path.partition("/")
        stem = name[: -len(".md")]
        out[stem.split("--", 1)[0]] = f"{directory}/{name}"
    return out


def head_of(repo: Path) -> str:
    import pygit2  # noqa: PLC0415

    return str(pygit2.Repository(str(repo)).references["refs/heads/main"].target)


def strays() -> list[str]:
    """Any server this harness could have left behind, for the report to print.

    Asked of `ps` rather than of our own bookkeeping, because the bookkeeping is
    exactly what fails when a run dies badly.
    """
    out = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True).stdout
    return [
        line.strip()
        for line in out.splitlines()
        if "serve_load.py" in line or "tests/load/server.py" in line
    ]
