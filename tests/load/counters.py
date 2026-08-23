"""What one request actually asks the store for, counted.

    .venv/bin/python tests/load/counters.py <scratch dir>

The application is untouched: `openproj.web.Store` is rebound to a counting
subclass BEFORE `create_app` runs, so the app builds its store out of the
counter without knowing it. Every method below is the real one; the subclass
only tallies.

`Store.head()` is the one worth counting. It does not read a cached ref — it
opens a whole new `pygit2.Repository` on every call (`store.py:461-463`,
deliberately, so a commit made in a terminal is visible at once) and that is
0.19 ms of syscalls each time on a warm page cache.
"""

from __future__ import annotations

import collections
import shutil
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus  # noqa: E402

from openproj import web  # noqa: E402
from openproj.store import Store  # noqa: E402

TALLY: collections.Counter = collections.Counter()


class Counting(Store):
    def head(self):
        TALLY["head"] += 1
        return super().head()

    def blobs(self, commit):
        TALLY["blobs (whole tree walk)"] += 1
        return super().blobs(commit)

    def read(self, commit, path):
        TALLY["read (one blob)"] += 1
        return super().read(commit, path)

    def write_all(self, files, base_commit, author, message):
        TALLY["write_all"] += 1
        return super().write_all(files, base_commit, author, message)

    def last_edited(self, known=None):
        TALLY["last_edited (history walk)"] += 1
        return super().last_edited(known)


def main(scratch: Path) -> None:
    from fastapi.testclient import TestClient

    repo, remote = scratch / "counters.git", scratch / "counters-remote.git"
    for path in (repo, remote):
        if path.exists():
            shutil.rmtree(path)
    corpus.build(repo, 40, 10, 60, 60)
    import subprocess

    subprocess.run(["git", "clone", "--bare", "--quiet", str(repo), str(remote)],
                   check=True, capture_output=True)
    subprocess.run(["git", "--git-dir", str(repo), "remote", "add", "origin",
                    f"file://{remote}"], check=True, capture_output=True)

    web.Store = Counting
    app = web.create_app(
        repo, auth="dev", secret="dev-secret", remote=f"file://{remote}",
        dev_login="jcanton", today=date(2026, 8, 17),
    )
    app.state.warm_edited()

    with TestClient(app) as client:
        index = client.get("/api/index.json").json()
        record_id = sorted(i for i in index["records"] if i.startswith("task-"))[0]

        def measure(label, call, repeat=5):
            call()  # warm every cache the app has
            TALLY.clear()
            begun = time.perf_counter()
            for _ in range(repeat):
                call()
            ms = (time.perf_counter() - begun) * 1000 / repeat
            print(f"\n{label}: {ms:.1f} ms per request (warm index cache)")
            for what, n in sorted(TALLY.items()):
                print(f"    {what:<28} {n / repeat:>7.1f} per request")

        measure("GET /api/health", lambda: client.get("/api/health"))
        measure("GET /  (the landing list)", lambda: client.get("/"))
        measure("GET /table", lambda: client.get("/table"))
        measure("GET /api/index.json", lambda: client.get("/api/index.json"))
        measure("GET /detail/<id>", lambda: client.get(f"/detail/{record_id}"))

        # The write, one at a time, each against a base read fresh. Counted
        # separately because the index cache is COLD for it by construction:
        # the write it just made is what invalidated it.
        state = {"n": 0}

        def one_patch():
            state["n"] += 1
            current = client.get("/api/health").json()["head"]
            client.patch(
                f"/api/record/{record_id}",
                json={"base_commit": current,
                      "fields": {"person_weeks": 1.0 + state["n"] % 5 * 0.5},
                      "body": None},
            )

        measure("PATCH /api/record/<id> (+ the /api/health before it)", one_patch)

        # And the read that follows it, which is the one that pays for the write.
        def patch_then_read():
            state["n"] += 1
            current = client.get("/api/health").json()["head"]
            client.patch(
                f"/api/record/{record_id}",
                json={"base_commit": current,
                      "fields": {"person_weeks": 1.0 + state["n"] % 5 * 0.5},
                      "body": None},
            )
            client.get("/")

        measure("the same PATCH, then one GET / (cold index)", patch_then_read)

    print("\nhead() costs one whole pygit2.Repository open each time — see "
          "tests/load/micro.py for what that is in milliseconds.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
