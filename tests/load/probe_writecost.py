"""What one commit costs, and therefore what a burst of them costs everybody.

`_commit_room` is the one writer in this application that does NOT run on a
thread (`web.py:2591-2605`), on purpose: between the snapshot it commits and
`room.settled` there must be no `await`, or a keystroke that arrives in the
suspension is deleted by the absorb that follows. So the whole of `store.write`
— the tree build, the three-way merge, the commit, and the PUSH — holds the
event loop, and while it is held nobody's keystroke is relayed, no outbox
drains, and no other room's timer runs.

This times the `saving` -> `saved` gap seen on the wire, which is the loop-held
window as a participant experiences it, under four conditions:

* no remote (a local `openproj serve`) — the floor;
* a `file://` remote, which exercises `_send`, `_absorb_remote` and the
  non-fast-forward arm with no network in them;
* a commit that has to MERGE, because somebody else moved the file — which is
  `SequenceMatcher` over the whole body, twice, on the event loop;
* the same on a body near `MAX_BODY_BYTES`.

The production number this cannot measure is the network. `store.py:783` records
it: about 600 ms per push from a laptop, and about 1.8 s for the collision tail
that rewinds, fetches and retries. Multiply the merge column by that.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygit2  # noqa: E402
from probe_saverace import TASK, patch  # noqa: E402
from room import Member, Server, plan_at  # noqa: E402

SAVES = 8


def settled(member: Member) -> float | None:
    """When this member was told the save was over.

    NOT the `saving` -> `saved` gap. `_to_room({"t": "saving"})` only queues the
    frame (`web.py:2549` through `Outbox.offer`), and the task that puts queued
    frames on the wire needs the event loop that `store.write` is holding — so
    both frames leave together, after the write, and the gap between them is
    zero by construction. Measured: 0.1 ms for every condition below, including
    a merged write over a 210 kB body. That is not a fast write, it is an
    instrument reading its own blind spot, and it is worth writing down: **the
    "saving…" a room shows everybody cannot reach them until the write it is
    announcing has already finished.**
    """
    done = [f["at_"] for f in member.told if f["t"] in ("saved", "refused", "nothing")]
    return done[-1] if done else None


class Health(threading.Thread):
    """`/api/health` in a loop, from outside the loop, as a stopwatch on it.

    The one honest way to see how long `store.write` holds the event loop: a
    request that costs the server almost nothing, whose latency is therefore
    almost entirely the time it spent waiting for the loop to come back.
    """

    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.samples: list[tuple[float, float]] = []
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            began = time.monotonic()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/api/health", timeout=60
                ) as answer:
                    answer.read()
            except Exception:  # noqa: BLE001 - a stalled loop is the measurement
                pass
            self.samples.append((began, time.monotonic() - began))
            time.sleep(0.01)

    def worst_between(self, start: float, end: float) -> float:
        inside = [held for when, held in self.samples if start <= when <= end]
        return round(max(inside) * 1000, 1) if inside else 0.0


def timed(server: Server, member: Member, before_each=None) -> dict:
    health = Health(server.port)
    health.start()
    time.sleep(1.0)
    idle = [held for _, held in health.samples]
    held = []
    for n in range(SAVES):
        if before_each:
            before_each(n)
        member.told.clear()
        member.type(0, f"line {n} typed by the probe\n")
        time.sleep(0.2)
        began = time.monotonic()
        member.save()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if settled(member) is not None:
                break
            time.sleep(0.01)
        held.append(health.worst_between(began, time.monotonic()))
        time.sleep(0.2)
    health.stop.set()
    return {
        "n": len(held),
        "loop_held_mean_ms": round(statistics.mean(held), 1) if held else None,
        "loop_held_max_ms": round(max(held), 1) if held else None,
        "health_idle_mean_ms": round(statistics.mean(idle) * 1000, 1) if idle else None,
    }


def main(where: Path) -> dict:
    report: dict = {}

    # --- no remote ----------------------------------------------------------
    repo, _ = plan_at(where / "bare.git", pitches=20, tasks_each=4)
    with Server(repo) as server:
        ann = Member(server.port, "ann", TASK, 300001, applies=True)
        report["no_remote"] = timed(server, ann)
        ann.close()

    # --- a file:// remote ---------------------------------------------------
    origin, _ = plan_at(where / "origin.git", pitches=20, tasks_each=4)
    clone = where / "clone.git"
    pygit2.clone_repository(f"file://{origin}", str(clone), bare=True)
    git = pygit2.Repository(str(clone))
    if "refs/heads/main" not in git.references:
        git.references.create(
            "refs/heads/main", git.references["refs/remotes/origin/main"].target
        )
    with Server(clone, remote=f"file://{origin}") as server:
        ann = Member(server.port, "ann", TASK, 300002, applies=True)
        report["file_remote"] = timed(server, ann)

        # --- every commit has to merge -------------------------------------
        # A second writer moves a DIFFERENT line of the same file before each
        # save, so `store.write` takes the `_merge` arm rather than the
        # `current == base_commit` fast path, every time.
        original = ann.body()

        def moved(n: int) -> None:
            head = pygit2.Repository(str(clone)).references["refs/heads/main"].target
            patch(server.port, TASK, "bo", original + f"\n\nsomebody else, round {n}\n", str(head))

        report["file_remote_merging"] = timed(server, ann, before_each=moved)
        ann.close()

    # --- a large body -------------------------------------------------------
    with Server(clone, remote=f"file://{origin}") as server:
        ann = Member(server.port, "ann", TASK, 300003, applies=True)
        # Push the document towards the policy ceiling: 200 kB of distinct lines,
        # which is what `SequenceMatcher` has to walk on every merged write.
        big = "".join(f"a line of a shaping document, number {n}\n" for n in range(5000))
        ann.type(0, big)
        time.sleep(1.0)
        report["big_body_chars"] = len(ann.body())
        report["big_body"] = timed(server, ann)
        ann.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
