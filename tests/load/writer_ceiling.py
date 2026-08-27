"""The serialised writer's ceiling, in saves per second, as a function of push latency.

    uv run python tests/load/writer_ceiling.py [scratch-dir] [seconds-per-point]

**No server, no HTTP, no rendering.** `tests/load/run.py` measures what twenty
people experience, which is the right thing to report — but it mixes two
ceilings that have to be separated before either can be extrapolated to another
machine. One is CPU: `GET /detail/<id>` is 240-300 ms of pure Python per record
page and every save is preceded by one, so on a busy instance the save rate can
be limited by rendering that has nothing to do with writing. The other is the
mutex: `store.py` takes `self._writing` and does not release it until the push
has returned, so the write path of the whole service is at most one save per
in-lock round trip.

This measures the second one alone. It opens ONE `Store` — the same object
`web.py` holds — and drives `Store.write` from several threads onto several
different paths, which is exactly the `write-different` shape with the web
framework taken out of the picture. What comes out is a number that depends on
the remote and on nothing else, so it can be carried to a 1 vCPU Cloud Run
instance without carrying a laptop's rendering speed with it.

The push latency is charged by `server.shim`, which wraps
`pygit2.Remote.push`/`.fetch` with a sleep from OUTSIDE the application; the
delay is read from a mutable cell so one process can walk a whole curve.
`src/openproj/` is untouched.

Every thread writes to its OWN path and re-reads HEAD before each write, so
nothing here can conflict and every refusal would be a finding rather than the
scenario. The outcome tally is printed for exactly that reason.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import corpus  # noqa: E402
import pygit2  # noqa: E402

from openproj.store import Store  # noqa: E402

# The shim's delay, in a cell so the sweep can move it between points without
# re-wrapping pygit2 (wrapping a wrapper would charge two sleeps at the second
# point and four at the third, and the curve would look superlinear for a reason
# that was entirely the instrument's).
DELAY = {"seconds": 0.0}

# How many writers push at the lock at once. Above the ceiling by design — the
# question is what the lock can serve, and a demand below capacity measures the
# demand instead.
THREADS = 8


def install_shim() -> None:
    real_push, real_fetch = pygit2.Remote.push, pygit2.Remote.fetch

    def push(self, *a, **kw):
        time.sleep(DELAY["seconds"])
        return real_push(self, *a, **kw)

    def fetch(self, *a, **kw):
        time.sleep(DELAY["seconds"])
        return real_fetch(self, *a, **kw)

    pygit2.Remote.push = push
    pygit2.Remote.fetch = fetch


def task_paths(repo: Path, how_many: int) -> list[str]:
    git = pygit2.Repository(str(repo))
    head = str(git.references["refs/heads/main"].target)
    out = []

    def walk(tree, prefix):
        for entry in tree:
            if entry.type_str == "tree":
                walk(git[entry.id], f"{prefix}{entry.name}/")
            elif prefix.startswith("tasks/"):
                out.append(f"{prefix}{entry.name}")

    walk(git[head].tree, "")
    return sorted(out)[:how_many]


def one_point(store: Store, paths: list[str], seconds: float, rtt_ms: float) -> dict:
    """`THREADS` writers, each on its own file, for `seconds`."""
    DELAY["seconds"] = rtt_ms / 1000.0
    outcomes: dict[str, int] = {}
    latencies: list[float] = []
    guard = threading.Lock()
    stop = time.monotonic() + seconds

    def writer(path: str, who: str) -> None:
        n = 0
        while time.monotonic() < stop:
            n += 1
            head = store.head()
            body = store.read(head, path) or ""
            begun = time.monotonic()
            result = store.write(
                path=path,
                content=body + f"- [ ] WC {who}.{n:04d}\n",
                base_commit=head,
                author=who,
                message=f"{path}: {who} save {n}",
            )
            took = (time.monotonic() - begun) * 1000
            with guard:
                latencies.append(took)
                outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
                # `pushed` is on the result here, where the store returns it. It
                # is what every HTTP write route in web.py then drops.
                key = f"pushed={result.pushed}"
                outcomes[key] = outcomes.get(key, 0) + 1

    began = time.monotonic()
    threads = [
        threading.Thread(target=writer, args=(paths[i % len(paths)], f"w{i}"), daemon=True)
        for i in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=seconds + 120)
    elapsed = time.monotonic() - began
    ordered = sorted(latencies)
    return {
        "rtt_ms": rtt_ms,
        "seconds": round(elapsed, 2),
        "writers": THREADS,
        "saves": len(latencies),
        "saves_per_second": round(len(latencies) / elapsed, 3),
        "in_lock_ms_implied": round(1000 * elapsed / len(latencies), 1) if latencies else None,
        "p50_ms": round(ordered[len(ordered) // 2], 1) if ordered else None,
        "p90_ms": round(ordered[int(0.9 * len(ordered))], 1) if ordered else None,
        "max_ms": round(ordered[-1], 1) if ordered else None,
        "outcomes": dict(sorted(outcomes.items())),
    }


def main(where: Path, seconds: float, points: list[float]) -> dict:
    plan, origin = where / "plan.git", where / "origin.git"
    head = corpus.build(plan, pitches=8, tasks_each=3, notes=4, issues=4)
    subprocess.run(
        ["git", "clone", "--bare", "--quiet", str(plan), str(origin)],
        check=True,
        capture_output=True,
    )
    install_shim()
    paths = task_paths(plan, THREADS)
    store = Store(plan, remote=f"file://{origin}")
    rows = [one_point(store, paths, seconds, rtt) for rtt in points]

    local = str(pygit2.Repository(str(plan)).references["refs/heads/main"].target)
    remote = str(pygit2.Repository(str(origin)).references["refs/heads/main"].target)
    return {
        "base_commit": head[:10],
        "records": 8 + 24 + 4 + 4 + 1,
        "threads": THREADS,
        "seconds_per_point": seconds,
        "points": rows,
        "ended": {"local": local[:10], "origin": remote[:10], "equal": local == remote},
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="wc-"))
    every = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    scratch = Path(tempfile.mkdtemp(prefix="writer-ceiling-", dir=str(root)))
    try:
        report = main(scratch, every, [0.0, 25.0, 50.0, 150.0, 300.0, 600.0])
        print(json.dumps(report, indent=2))
        print("\nrtt_ms   saves/s   implied in-lock ms   p50 ms   p90 ms")
        for row in report["points"]:
            print(
                f"{row['rtt_ms']:>6.0f}{row['saves_per_second']:>10.2f}"
                f"{row['in_lock_ms_implied']:>21.1f}{row['p50_ms']:>9.1f}{row['p90_ms']:>9.1f}"
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
