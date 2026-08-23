"""What a shutdown rescues, and what it does not.

`--min-instances 0`, so the instance is torn down whenever the service goes idle,
and a deploy replaces it whenever anybody ships. Both arrive as SIGTERM, and
`cli._exit_aware_server` sets `app.state.closing` from uvicorn's own exit hook so
that `_watch` (`web.py:2712`) gets one last commit in.

`_watch`'s loop is `while room.members:`. A room with nobody in it has no
`_watch` task at all — the socket's `finally` cancels it the moment the room
empties (`web.py:2980`). So the shutdown hook covers exactly the rooms somebody
is sitting in, and a warm room with uncommitted text and nobody in it is covered
by nothing. `Rooms.sweep` (`coedit.py:394`) drops such a room after
`LINGER_SECONDS` without asking whether it is pending, and `web.py:2985`
discards what it returns.

Two runs, in order:

1. **Somebody is still in the room.** Type, do not save, SIGTERM. Expect a
   commit, and measure how long the shutdown takes to make it.
2. **Nobody is in the room and the room is pending.** A conflicting `PATCH`
   makes the last-person-out commit refuse, which is the ordinary way to reach
   that state without contriving it. Then SIGTERM. Whatever was typed is either
   in git or it is nowhere.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_saverace import PATH, TASK, patch  # noqa: E402
from room import Member, Server, commits, plan_at, stored_body  # noqa: E402


def occupied(where: Path) -> dict:
    repo, _ = plan_at(where / "one.git", pitches=4, tasks_each=2)
    report: dict = {}
    server = Server(repo)
    with server:
        ann = Member(server.port, "ann", TASK, 400001, applies=True)
        bo = Member(server.port, "bo", TASK, 400002, applies=True)
        ann.type(0, "ANN-UNCOMMITTED\n")
        bo.type(0, "BO-UNCOMMITTED\n")
        time.sleep(1.0)
        report["commits_before_sigterm"] = len(commits(repo)) - 1
        began = time.monotonic()
    report["shutdown_seconds"] = round(time.monotonic() - began, 2)
    report["commits_after_sigterm"] = len(commits(repo)) - 1
    body = stored_body(repo, PATH)
    report["git_has_ann"] = "ANN-UNCOMMITTED" in body
    report["git_has_bo"] = "BO-UNCOMMITTED" in body
    report["commit_message"] = commits(repo)[0][1] if len(commits(repo)) > 1 else ""
    report["commit_author"] = commits(repo)[0][0] if len(commits(repo)) > 1 else ""
    return report


def warm_and_empty(where: Path) -> dict:
    repo, _ = plan_at(where / "two.git", pitches=4, tasks_each=2)
    report: dict = {}
    server = Server(repo)
    with server:
        ann = Member(server.port, "ann", TASK, 400003, applies=True)
        original = ann.body()
        base = ann.welcome["base"]
        ann.type(0, "ANN-WROTE-A-PARAGRAPH\n")
        time.sleep(0.4)
        # Somebody's form Save lands on the same first line, so the room's own
        # commit — including the one its last member's departure triggers — can
        # only be a refusal.
        status, _ = patch(server.port, TASK, "bo", "BO-FROM-THE-FORM\n" + original, base)
        report["patch_status"] = status
        ann.told.clear()
        ann.close()  # the last person out: `_commit_room` runs and refuses
        time.sleep(2.0)
        report["commits_before_sigterm"] = len(commits(repo)) - 1
        report["git_has_ann_before_sigterm"] = "ANN-WROTE-A-PARAGRAPH" in stored_body(repo, PATH)
        began = time.monotonic()
    report["shutdown_seconds"] = round(time.monotonic() - began, 2)
    report["commits_after_sigterm"] = len(commits(repo)) - 1
    report["git_has_ann_after_sigterm"] = "ANN-WROTE-A-PARAGRAPH" in stored_body(repo, PATH)
    report["git_has_bo"] = "BO-FROM-THE-FORM" in stored_body(repo, PATH)
    return report


def many_rooms(where: Path, rooms: int = 20) -> dict:
    """Twenty occupied rooms, all pending, one SIGTERM.

    Every room's `_watch` reaches the `closing` branch on its own next tick and
    calls `_commit_room`, which does not run on a thread — so the twenty commits
    are serialised on the event loop inside one graceful-shutdown window
    (`timeout_graceful_shutdown=10`, and Cloud Run's own SIGTERM grace is ten
    seconds too). What is measured is how many of them land.
    """
    repo, _ = plan_at(where / "three.git", pitches=20, tasks_each=4)
    report: dict = {"rooms": rooms}
    server = Server(repo)
    with server:
        members = [
            Member(server.port, f"w{n:02d}", f"task-{n:06x}", 430000 + n) for n in range(rooms)
        ]
        for n, one in enumerate(members):
            one.type(0, f"ROOM-{n:02d}-UNCOMMITTED\n")
        time.sleep(1.5)
        report["commits_before_sigterm"] = len(commits(repo)) - 1
        began = time.monotonic()
    report["shutdown_seconds"] = round(time.monotonic() - began, 2)
    report["commits_after_sigterm"] = len(commits(repo)) - 1
    report["rooms_rescued"] = report["commits_after_sigterm"]
    report["rooms_lost"] = rooms - report["commits_after_sigterm"]
    return report


def main(where: Path) -> dict:
    return {
        "somebody_is_in_the_room": occupied(where),
        "nobody_is": warm_and_empty(where),
        "twenty_rooms_at_once": many_rooms(where),
    }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
