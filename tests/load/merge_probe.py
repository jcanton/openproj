"""What the three-way merge does with inputs a load test will eventually produce.

    .venv/bin/python tests/load/merge_probe.py

Read-only: it calls `store._merge`, `_merge_body` and `_merge_frontmatter`
directly on strings and touches no repository at all. Each case prints the two
edits and the text that came out, so the report can quote a merge nobody wrote
rather than assert that one is possible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from openproj.store import _merge, _merge_body, _merge_frontmatter  # noqa: E402


def show(title, base, mine, theirs, merged, conflicts):
    print(f"\n--- {title} ---")
    print(f"base   {base!r}")
    print(f"mine   {mine!r}")
    print(f"theirs {theirs!r}")
    print(f"OUT    {merged!r}")
    if conflicts:
        print(f"conflicts {conflicts}")


def body_cases():
    # 1. The ordinary good case: two different paragraphs, cleanly interleaved.
    base = "a\nb\nc\nd\ne\n"
    merged, c = _merge_body(base, "A\nb\nc\nd\ne\n", "a\nb\nc\nd\nE\n")
    show("disjoint lines merge", base, "line1->A", "line5->E", merged, c)

    # 2. An insertion at exactly the first line of somebody else's replacement.
    #    `overlaps` is a half-open test and an empty span (3,3) satisfies
    #    neither arm of it, so this is not reported as a conflict — and the
    #    assembly loop then keeps whichever span the set happened to yield
    #    first and skips the other.
    base = "a\nb\nc\nd\ne\n"
    mine = "a\nb\nc\nINSERTED\nd\ne\n"      # insert before line 4  -> span (3,3)
    theirs = "a\nb\nc\nDDD\ne\n"            # replace line 4        -> span (3,4)
    merged, c = _merge_body(base, mine, theirs)
    show("insert at the head of a replacement", base, mine, theirs, merged, c)
    print("INSERTED survived:", "INSERTED" in (merged or ""))
    print("DDD survived:     ", "DDD" in (merged or ""))

    # 3. The same pair with the sides swapped: whichever way round it is asked,
    #    one side's text is missing and nothing says so.
    merged, c = _merge_body(base, theirs, mine)
    show("the same pair, sides swapped", base, theirs, mine, merged, c)
    print("INSERTED survived:", "INSERTED" in (merged or ""))
    print("DDD survived:     ", "DDD" in (merged or ""))

    # 4. Two people appending to the end of the document — the commonest
    #    co-editing shape there is.
    base = "a\nb\n"
    merged, c = _merge_body(base, "a\nb\nMINE\n", "a\nb\nTHEIRS\n")
    show("two appends at the end", base, "+MINE", "+THEIRS", merged, c)


def front_cases():
    base = "status: shaping\nowner: ann\ncycle: 37\n"
    mine = "status: shelved\nowner: ann\ncycle: 37\n"
    theirs = "status: shaping\nowner: ann\ncycle: 38\nperson_weeks: 4.0\n"
    merged, c = _merge_frontmatter(base, mine, theirs)
    show("two fields, one record", base, "status->shelved", "cycle->38 +size", merged, c)

    base = "---\nstatus: todo\nowner: ann\n---\n\nbody\n"
    merged, report = _merge(
        "tasks/t.md",
        base,
        "---\nstatus: done\nowner: ann\n---\n\nbody\n",
        "---\nstatus: todo\nowner: bob\n---\n\nbody\n",
    )
    show("done by one, reassigned by the other", base, "status->done", "owner->bob", merged, report)


if __name__ == "__main__":
    body_cases()
    front_cases()
