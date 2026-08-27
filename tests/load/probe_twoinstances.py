"""What a second instance does to a room. The RUNBOOK says one can happen.

`deploy/RUNBOOK.md:273` — *"Note max-instances *can* be briefly exceeded, so the
`flock` is the real guard."* The flock is `self._path / LOCK_FILE`
(`store.py:439`), and `self._path` is the container's own bare clone
(`deploy/boot.py:34`, `/srv/plan.git`). Two Cloud Run instances have two
container filesystems and therefore two lock files. This probe stands two
servers on two clones of one origin, exactly as two revisions of one service
would be, and asks four things:

1. Does the second `Store` take its flock? (If it does, the guard the RUNBOOK
   names is not a guard against a second instance at all.)
2. Do the two rooms for one record see each other's people? (Presence is
   `Room.members`, a dict on a `Room`, in a `Rooms` dict on one process.)
3. What does git end up holding when both rooms commit?
4. What does the loser see?

`file://` and not HTTPS. `store.py:787` says the two answer differently for a
non-fast-forward push and that only HTTPS is what runs in production, so the
push-rejection arm may behave differently there; every claim below that depends
on the push is marked in the report.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygit2  # noqa: E402
from room import Member, Server, commits, plan_at, stored_body  # noqa: E402

TASK = "task-000000"
PATH = "tasks/task-000000--task-1.md"


def main(where: Path) -> dict:
    origin, _ = plan_at(where / "origin.git", pitches=4, tasks_each=2)
    one = where / "one.git"
    two = where / "two.git"
    pygit2.clone_repository(f"file://{origin}", str(one), bare=True)
    pygit2.clone_repository(f"file://{origin}", str(two), bare=True)
    for clone in (one, two):
        git = pygit2.Repository(str(clone))
        if "refs/heads/main" not in git.references:
            git.references.create(
                "refs/heads/main", git.references["refs/remotes/origin/main"].target
            )

    report: dict = {"remote": "file:// (see the module note)"}
    with (
        Server(one, remote=f"file://{origin}") as a,
        Server(two, port=None, remote=f"file://{origin}") as b,
    ):
        report["both_servers_up"] = True
        report["two_lock_files"] = [
            (clone / "openproj.lock").read_text().strip() for clone in (one, two)
        ]
        report["the_flock_stopped_neither"] = (
            report["two_lock_files"][0] != report["two_lock_files"][1]
        )

        ann = Member(a.port, "ann", TASK, 600001, applies=True)
        bo = Member(b.port, "bo", TASK, 600002, applies=True)
        time.sleep(0.5)
        report["ann_seed"] = ann.welcome["seed"]
        report["bo_seed"] = bo.welcome["seed"]
        report["seeds_agree"] = ann.welcome["seed"] == bo.welcome["seed"]

        ann.type(0, "ANN-ON-INSTANCE-ONE\n")
        bo.type(0, "BO-ON-INSTANCE-TWO\n")
        time.sleep(1.0)
        report["ann_sees_bos_text"] = "BO-ON-INSTANCE-TWO" in ann.body()
        report["bo_sees_anns_text"] = "ANN-ON-INSTANCE-ONE" in bo.body()
        report["ann_roster"] = [f["people"] for f in ann.told if f["t"] == "who"][-1:]
        report["bo_roster"] = [f["people"] for f in bo.told if f["t"] == "who"][-1:]

        # Ann saves. Her instance commits and pushes to the shared origin.
        ann.told.clear()
        bo.told.clear()
        ann.save()
        time.sleep(3)
        report["ann_save"] = [f["t"] for f in ann.told if f["t"] in ("saved", "refused")][-1:]
        report["ann_pushed"] = [f.get("pushed") for f in ann.told if f["t"] == "saved"][-1:]
        report["origin_has_ann"] = "ANN-ON-INSTANCE-ONE" in stored_body(origin, PATH)

        # Bo saves. His instance's HEAD has not moved; his push must lose the race
        # and his room must re-run its merge against what Ann landed.
        bo.save()
        time.sleep(5)
        report["bo_save"] = [f["t"] for f in bo.told if f["t"] in ("saved", "refused")][-1:]
        report["bo_why"] = [f.get("why", "")[:300] for f in bo.told if f["t"] == "refused"][-1:]
        report["origin_has_bo"] = "BO-ON-INSTANCE-TWO" in stored_body(origin, PATH)
        report["origin_still_has_ann"] = "ANN-ON-INSTANCE-ONE" in stored_body(origin, PATH)
        report["origin_commits"] = len(commits(origin)) - 1
        report["bo_room_still_holds_his_line"] = "BO-ON-INSTANCE-TWO" in bo.body()
        report["bo_room_now_holds_anns_line"] = "ANN-ON-INSTANCE-ONE" in bo.body()

        ann.close()
        bo.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
