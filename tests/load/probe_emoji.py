"""Two people splicing either side of an emoji, at once, through a real room.

`AGENTS.md` records this family twice: a splice measured in code points and
applied in UTF-8 bytes (`coedit.byte_offset`), and the browser's half of the same
splice scanning UTF-16 code units so that a boundary inside a surrogate pair cut
half a character. Both were fixed at their own boundary, and `AGENTS.md` also
records that the Ace-surface tests still splice only ASCII.

What no test drives is the **concurrent** shape: two sockets whose updates
interleave around an astral character, and then a commit that has to MERGE —
`store._merge_body` is a line merge, `_body_at` re-reads the file, and
`Room.absorb` splices the difference back into a live document with
`byte_offset` at the boundary. That is three index spaces in one path (Python
code points, UTF-8 bytes, and git's lines of bytes), reached only when somebody
else moved the file while a room was live.

Every assertion here is on bytes: what git holds, and what each participant's
document holds, compared against the characters that were typed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_saverace import PATH, TASK, patch  # noqa: E402
from room import Member, Server, plan_at, stored_body  # noqa: E402

THUMB_UP = "\U0001f44d"
THUMB_DOWN = "\U0001f44e"
DASH = "—"


def main(where: Path) -> dict:
    repo, _ = plan_at(where / "plan.git", pitches=4, tasks_each=2)
    report: dict = {}
    with Server(repo) as server:
        ann = Member(server.port, "ann", TASK, 200001, applies=True)
        bo = Member(server.port, "bo", TASK, 200002, applies=True)

        # A first line that is the hazard: an em dash (three UTF-8 bytes, one
        # code point, one UTF-16 unit) and an emoji (four bytes, one code point,
        # TWO UTF-16 units) with room to splice on both sides of each.
        header = f"AB{THUMB_UP}CD{DASH}EF\n"
        ann.type(0, header)
        time.sleep(0.5)
        report["seeded_line"] = header.strip()
        report["both_agree_after_seed"] = ann.body() == bo.body()

        # Now both of them splice, at once, on either side of the emoji. The
        # indices are into the document's own space, which for `pycrdt` is UTF-8
        # bytes: "AB" is 2, the emoji is 4, so 2 is immediately before it and 6
        # immediately after.
        before_emoji, after_emoji = 2, 2 + 4
        ann.type(before_emoji, "<ann>")
        bo.type(after_emoji, "<bo>")
        time.sleep(1.0)
        report["converged"] = ann.body() == bo.body()
        first = ann.body().splitlines()[0]
        report["first_line_after_concurrent_splice"] = first
        report["emoji_intact"] = THUMB_UP in first
        report["no_replacement_character"] = "�" not in ann.body()
        report["no_lone_surrogate"] = not any(0xD800 <= ord(ch) <= 0xDFFF for ch in ann.body())
        report["both_marks_present"] = "<ann>" in first and "<bo>" in first

        # And a third splice on either side of the em dash while they are at it.
        at_dash = first.index(DASH)
        dash_bytes = len(first[:at_dash].encode("utf-8"))
        ann.type(dash_bytes, "[")
        bo.type(dash_bytes + 3 + 1, "]")
        time.sleep(1.0)
        report["converged_after_dash"] = ann.body() == bo.body()
        report["dash_intact"] = DASH in ann.body().splitlines()[0]

        # --- and now force the merge path -------------------------------------
        # Somebody else moves a DIFFERENT line of the same file, so the room's
        # next commit takes `store._merge` and then `Room.absorb` splices the
        # merged file back into a live document holding astral characters.
        original_tail = "\n".join(ann.body().splitlines()[1:])
        head = ann.welcome["base"]
        status, _ = patch(
            server.port, TASK, "carol", f"{first}\n{original_tail}\nCAROL ADDED A LINE\n", head
        )
        report["patch_status"] = status
        ann.told.clear()
        ann.save()
        time.sleep(3)
        answered = [f["t"] for f in ann.told if f["t"] in ("saved", "refused", "nothing")]
        report["room_save_after_the_move"] = answered[-1:] or ["nothing arrived"]
        committed = stored_body(repo, PATH)
        report["git_first_line"] = committed.splitlines()[0]
        report["git_emoji_intact"] = THUMB_UP in committed
        report["git_dash_intact"] = DASH in committed
        report["git_has_carol"] = "CAROL ADDED A LINE" in committed
        report["git_has_both_marks"] = "<ann>" in committed and "<bo>" in committed
        report["git_no_replacement_character"] = "�" not in committed
        time.sleep(1.0)
        report["room_matches_git_after_absorb"] = ann.body().rstrip("\n") == committed.rstrip("\n")
        report["ann_and_bo_still_agree"] = ann.body() == bo.body()

        ann.close()
        bo.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2, ensure_ascii=False))
