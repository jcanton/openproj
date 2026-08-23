"""What one request pays, measured piece by piece, with nothing concurrent.

Run: `.venv/bin/python tests/load/micro.py <scratch dir>`

Every number the report quotes for the cost of a read, the cost of a rebuild and
the cost of a write comes from here. It opens a Store on a throwaway repository
and closes it again — `Store` takes an flock, so it must never be pointed at a
plan a server is holding.
"""

from __future__ import annotations

import shutil
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus  # noqa: E402

from openproj.index import build_index  # noqa: E402
from openproj.store import Store  # noqa: E402
from openproj.web import _config_at, _records_at  # noqa: E402

TODAY = date(2026, 8, 17)


def timed(label, fn, n=20):
    fn()
    samples = []
    for _ in range(n):
        begun = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - begun) * 1000)
    samples.sort()
    print(
        f"{label:<46} {statistics.median(samples):8.2f} ms  "
        f"(min {samples[0]:.2f}  p95 {samples[int(0.95 * (len(samples) - 1))]:.2f})"
    )
    return statistics.median(samples)


def main(scratch: Path):
    for size in ((10, 5, 10, 10), (40, 10, 60, 60), (80, 20, 120, 120)):
        repo = scratch / f"micro-{size[0]}.git"
        if repo.exists():
            shutil.rmtree(repo)
        corpus.build(repo, *size)
        store = Store(repo)
        try:
            head = store.head()
            count = len(store.blobs(head))
            print(f"\n=== {count} files in the tree ({size}) ===")
            timed("store.head()  (reopens the Repository)", store.head, 200)
            timed("store.blobs(head)  (whole tree walk)", lambda s=store, h=head: s.blobs(h))
            timed("_records_at (warm parse cache)", lambda s=store, h=head: _records_at(s, h))
            records, unreadable = _records_at(store, head)
            config, _ = _config_at(store, head)
            timed(
                "build_index(records, config, today)",
                lambda r=records, c=config, u=unreadable: build_index(r, c, TODAY, u),
            )

            def whole(s=store, h=head):
                config2, u1 = _config_at(s, h)
                ents, u2 = _records_at(s, h)
                return build_index(ents, config2, TODAY, [*u1, *u2])

            timed("full index rebuild (warm parse cache)", whole, 10)
            timed("store.last_edited() full history walk", store.last_edited, 3)
        finally:
            store.close()

    # -- the write path, with and without a remote --------------------------
    print("\n=== write path ===")
    repo = scratch / "write.git"
    remote = scratch / "remote.git"
    for path in (repo, remote):
        if path.exists():
            shutil.rmtree(path)
    corpus.build(repo, 40, 10, 60, 60)
    subprocess.run(["git", "clone", "--bare", str(repo), str(remote)], check=True,
                   capture_output=True)

    store = Store(repo)
    try:
        head = store.head()
        target = next(p for p in store.blobs(head) if p.startswith("tasks/"))
        text = store.read(head, target)
        state = {"n": 0}

        def one_write():
            state["n"] += 1
            body = text + f"\nedit {state['n']}\n"
            return store.write(target, body, store.head(), "jcanton", "load: edit")

        timed("store.write, NO remote", one_write, 20)
    finally:
        store.close()

    store = Store(repo, remote=f"file://{remote}")
    try:
        head = store.head()
        target = next(p for p in store.blobs(head) if p.startswith("tasks/"))
        state = {"n": 0}

        def one_push_write():
            state["n"] += 1
            text2 = store.read(store.head(), target)
            return store.write(
                target, text2 + f"\npush {state['n']}\n", store.head(), "jcanton", "load: edit"
            )

        timed("store.write, file:// remote (push inside lock)", one_push_write, 20)
        timed("store.fetch() alone (one round trip)", store.fetch, 20)
    finally:
        store.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
