"""A form Save landing on a record a room is holding, and what happens next.

The room is a cache. `PATCH /api/entity` (`web.py:1812`) knows nothing about it:
it reads `original = store.read(base, path)` off git, patches, and writes. So a
tab whose socket never opened — a proxy that dropped the upgrade, a tab the room
evicted, `curl`, the CLI, somebody's terminal — writes the whole body against a
base, and the room's own in-memory text is not consulted at any point.

Three questions, in order of how much they cost somebody:

A. **The room's uncommitted text is not in git.** A PATCH whose `base_commit`
   equals HEAD takes the `current == base_commit` fast path (`store.py:830`) and
   is committed VERBATIM. Whatever the room has typed since its last commit is
   not merged against, because it is not anywhere a merge can see it.

B. **What the room does afterwards.** The room's `base` did not move, so its
   next commit is a three-way merge of its text against the PATCH's. An overlap
   on the same lines is `outcome == "conflict"`, which is a refusal that writes
   nothing — and the room keeps the same base and retries on the next window,
   for ever, with the text living only in one process's memory.

C. **Whether a refused room ever gets out of it.** Reloading the page rejoins
   the same `Room` object (it is keyed on the entity id and lives in a dict), and
   the join-time absorb is gated on `not room.pending()` (`web.py:2767`), which
   is false for exactly the room that is stuck. So a reload does not clear it.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from room import SECRET, Member, Server, commits, plan_at, stored_body  # noqa: E402

from openproj.auth import User, sign_session  # noqa: E402
from openproj.web import SESSION_COOKIE  # noqa: E402

TASK = "task-000000"
PATH = "tasks/task-000000--task-1.md"


def patch(port: int, entity_id: str, login: str, body: str, base: str) -> tuple[int, str]:
    token = sign_session(User(login=login, member=True), SECRET)
    payload = json.dumps({"body": body, "base_commit": base, "fields": {}}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/entity/{entity_id}",
        data=payload,
        method="PATCH",
        headers={"content-type": "application/json", "cookie": f"{SESSION_COOKIE}={token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main(where: Path) -> dict:
    repo, head = plan_at(where / "plan.git", pitches=4, tasks_each=2)
    report: dict = {}
    with Server(repo) as server:
        ann = Member(server.port, "ann", TASK, 700001, applies=True)
        report["room_base"] = ann.welcome["base"]
        original = ann.body()
        report["original_first_line"] = original.splitlines()[0]

        # --- A: the room types, and nothing is committed yet -------------------
        ann.type(0, "ANN-TYPED-THIS-AND-IT-IS-ONLY-IN-MEMORY\n")
        time.sleep(0.5)
        report["a_commits_so_far"] = len(commits(repo)) - 1
        report["a_room_text_in_git"] = "ANN-TYPED-THIS" in stored_body(repo, PATH)

        # A second person's form Save, against the same base the room has, with a
        # body that is the FILE plus their own line — which is exactly what a tab
        # with no socket sends: its textarea holds what the server rendered.
        status, said = patch(
            server.port, TASK, "bo", "BO-SAVED-THIS-FROM-THE-FORM\n" + original,
            ann.welcome["base"],
        )
        report["a_patch_status"] = status
        report["a_patch_outcome"] = json.loads(said).get("outcome") if status == 200 else said[:200]
        report["a_git_has_bo"] = "BO-SAVED-THIS" in stored_body(repo, PATH)
        report["a_git_has_ann"] = "ANN-TYPED-THIS" in stored_body(repo, PATH)
        report["a_room_still_has_ann"] = "ANN-TYPED-THIS" in ann.body()
        report["a_room_told"] = [f["t"] for f in ann.told]

        # --- B: the room's own next commit, against a base that has moved ------
        ann.save()
        deadline = time.monotonic() + 20
        answer = None
        while time.monotonic() < deadline:
            for frame in list(ann.told):
                if frame["t"] in ("saved", "refused", "nothing"):
                    answer = frame
            if answer:
                break
            time.sleep(0.2)
        report["b_room_save_answer"] = answer["t"] if answer else "nothing arrived"
        report["b_why"] = (answer or {}).get("why", "")[:400]
        report["b_git_has_ann"] = "ANN-TYPED-THIS" in stored_body(repo, PATH)
        report["b_git_has_bo"] = "BO-SAVED-THIS" in stored_body(repo, PATH)
        report["b_commits"] = len(commits(repo)) - 1

        # --- C: does anything clear a refusal? --------------------------------
        # A reload is a new socket into the same room. The join-time absorb is
        # gated on `not room.pending()`, and a refused room is pending.
        ann.told.clear()
        cid = Member(server.port, "ann", TASK, 700003, applies=True)
        report["c_reload_welcome_base"] = cid.welcome["base"]
        report["c_reload_was_told"] = [f["t"] for f in cid.told][:5]
        report["c_reload_body_has_ann"] = "ANN-TYPED-THIS" in cid.body()
        report["c_reload_body_has_bo"] = "BO-SAVED-THIS" in cid.body()
        cid.save()
        time.sleep(3)
        answer2 = [f for f in cid.told if f["t"] in ("saved", "refused", "nothing")]
        report["c_after_reload_save"] = answer2[-1]["t"] if answer2 else "nothing arrived"
        report["c_git_has_ann"] = "ANN-TYPED-THIS" in stored_body(repo, PATH)

        # --- D: does the quiet window keep retrying the same losing merge? -----
        seen = 0
        for _ in range(60):
            time.sleep(0.5)
            seen = len([f for f in cid.told if f["t"] == "refused"])
            if seen >= 2:
                break
        report["d_refusals_seen_in_30s"] = seen
        report["d_commits_at_end"] = len(commits(repo)) - 1
        report["d_git_has_ann"] = "ANN-TYPED-THIS" in stored_body(repo, PATH)

        ann.close()
        cid.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
