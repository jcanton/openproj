"""A commit already in git, silently reverted by the next save. End to end.

    .venv/bin/python tests/load/lost_line.py <scratch dir>

`_merge_body` calls two edits a conflict only where they OVERLAP by a half-open
test (`store.py:145`). An insertion has an EMPTY span, so an insertion at line N
and a replacement starting at line N satisfy neither arm of it and are merged
silently. The assembly loop under it (`store.py:157-165`) then walks the union of
both sides' spans with one cursor and skips any span starting behind the cursor —
so of two spans that begin on the same line, the second one the SET happens to
yield is dropped entirely.

Which one that is depends on the hash order of two integer tuples, which is to
say: on the line number. The sweep below shows the same pair of edits keeping
both sides at one offset and dropping one at the next.

When the dropped side is `theirs`, `theirs` is the text ALREADY IN GIT
(`store.py:859` passes `stored` as `theirs`), so the save reverts a colleague's
commit, answers `outcome: "merged"`, and reports no conflict.

Fuzzed: of 50,000 random three-way pairs on 4-12 line documents, 43,237 merged
with no conflict, and 1,192 of those (2.8%) dropped a line the stored commit had.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from openproj.store import Store, _merge_body, build_plan_repository  # noqa: E402

PATH = "tasks/task-000001--merge.md"
FRONT = """---
id: task-000001
kind: task
title: Merge probe
status: todo
created_schema_version: 2
---
"""


def sweep() -> list[int]:
    """The same two edits at every offset. Prints where a side disappears."""
    dropped = []
    print("offset  outcome")
    for k in range(14):
        pad = [f"prose line {i}\n" for i in range(k)]
        base = pad + ["ONE\n", "TWO\n", "THREE\n"]
        mine = pad + ["ANN REWROTE THIS\n", "THREE\n"]
        theirs = pad + ["BOB'S SENTENCE\n", "ONE\n", "TWO\n", "THREE\n"]
        merged, conflicts = _merge_body("".join(base), "".join(mine), "".join(theirs))
        if conflicts:
            verdict = "refused"
        elif "BOB'S SENTENCE" not in merged:
            verdict = "MERGED, and Bob's committed line is gone"
            dropped.append(k)
        elif "ANN REWROTE THIS" not in merged:
            verdict = "MERGED, and Ann's save is gone"
            dropped.append(k)
        else:
            verdict = "merged, both kept"
        print(f"{k:>6}  {verdict}")
    return dropped


def end_to_end(scratch: Path, offset: int) -> int:
    """The same thing through `Store.write`, which is what the PATCH route and
    the co-editing room both end in."""
    pad = "".join(f"prose line {i}\n" for i in range(offset))
    base = f"{FRONT}{pad}ONE\nTWO\nTHREE\n"
    bob = f"{FRONT}{pad}BOB'S SENTENCE\nONE\nTWO\nTHREE\n"
    ann = f"{FRONT}{pad}ANN REWROTE THIS\nTHREE\n"

    repo = scratch / "lost-line.git"
    if repo.exists():
        shutil.rmtree(repo)
    opened = build_plan_repository(repo, {PATH: base}, "the record as both of them opened it")

    store = Store(repo)
    try:
        first = store.write(PATH, bob, opened, "bob", "bob: a sentence at the top")
        print(f"\nbob   -> {first.outcome} {first.commit[:7]}")
        assert "BOB'S SENTENCE" in store.read(first.commit, PATH)

        second = store.write(PATH, ann, opened, "ann", "ann: rewrite the first line")
        print(f"ann   -> {second.outcome} {second.commit and second.commit[:7]} "
              f"conflict={second.conflict}")

        landed = store.read(store.head(), PATH)
        print("\nthe file in git now:\n" + landed)
        if "BOB'S SENTENCE" in landed:
            print("bob's line survived")
            return 0
        print(
            f"LOST — bob's commit {first.commit[:7]} is in the history and his line is "
            f"not in the file. Ann was answered {second.outcome!r}, status 200, with "
            "nothing to read."
        )
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    where = Path(sys.argv[1])
    losing = sweep()
    if not losing:
        print("\nno offset dropped a side on this interpreter")
        raise SystemExit(0)
    raise SystemExit(end_to_end(where, losing[0]))
