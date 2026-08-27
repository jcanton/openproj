"""A room that grows past what may be committed, and what it does after that.

`MAX_BODY_BYTES` bounds what this tool will put in git for ever. A room has no
other bound: `web.py:2554-2558` checks the snapshot and raises, and the raise
lands in `WRITE_FAILURES` and becomes a refusal — a refusal that writes nothing
and keeps the room's base where it was.

There is no path that trims a room, and no frame that stops anybody typing. So
this asks whether a room past the ceiling is a room that can never commit again,
and therefore whether the ceiling is also the upper bound on how much
unpersisted text one room can be holding when the process ends.

The frame ceiling is four times the body ceiling (`web.py:193`), so getting there
takes several frames and no single frame is refused on the way.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_saverace import PATH, TASK  # noqa: E402
from room import Member, Server, commits, plan_at, stored_body  # noqa: E402

from openproj.model import MAX_BODY_BYTES  # noqa: E402


def main(where: Path) -> dict:
    repo, _ = plan_at(where / "plan.git", pitches=4, tasks_each=2)
    report: dict = {"max_body_bytes": MAX_BODY_BYTES}
    with Server(repo) as server:
        ann = Member(server.port, "ann", TASK, 100001, applies=True)

        # A first, ordinary save, so there is a known good commit underneath.
        ann.type(0, "a paragraph somebody wrote\n")
        ann.save()
        time.sleep(2)
        report["first_save"] = [f["t"] for f in ann.told if f["t"] in ("saved", "refused")][-1:]
        report["commits_after_first_save"] = len(commits(repo)) - 1

        # Now past the ceiling, in frames that are each well under the transport
        # bound, which is what typing and pasting actually look like.
        chunk = "".join(f"filling this document up, line {n}\n" for n in range(400))
        while len(ann.body().encode("utf-8")) < MAX_BODY_BYTES + 4096:
            ann.type(0, chunk)
            time.sleep(0.05)
        report["room_bytes"] = len(ann.body().encode("utf-8"))
        report["over_the_ceiling_by"] = report["room_bytes"] - MAX_BODY_BYTES
        report["any_frame_refused_while_growing"] = [f["t"] for f in ann.told if f["t"] == "reload"]

        ann.told.clear()
        ann.save()
        time.sleep(3)
        report["save_over_the_ceiling"] = [
            f["t"] for f in ann.told if f["t"] in ("saved", "refused", "nothing")
        ][-1:]
        report["why"] = [f.get("why", "") for f in ann.told if f["t"] == "refused"][-1:]

        # And the quiet window, which is the other way a room commits.
        ann.told.clear()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not [f for f in ann.told if f["t"] == "refused"]:
            time.sleep(0.5)
        report["quiet_window_also_refuses"] = bool([f for f in ann.told if f["t"] == "refused"])
        report["commits_at_end"] = len(commits(repo)) - 1
        report["git_bytes"] = len(stored_body(repo, PATH).encode("utf-8"))
        report["unpersisted_bytes"] = report["room_bytes"] - report["git_bytes"]

        # Does leaving rescue it? The last person out commits.
        ann.close()
        time.sleep(3)
        report["commits_after_the_last_person_left"] = len(commits(repo)) - 1
        report["git_bytes_after_leaving"] = len(stored_body(repo, PATH).encode("utf-8"))
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
