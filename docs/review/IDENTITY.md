# An entity's identity is written twice and reconciled nowhere

Found by the round-eight audit of `review_design`, against the branch that has now
been merged. It predates that work entirely, which is why it is here and not there.

Severity: **high**. It loses data silently, and `openproj check` says the plan is
fine while it happens.

## What is true today

An entity says who it is in two places:

- the frontmatter — `id: task-0a1001`
- the filename — `task-0a1001--ci-for-the-standalone-driver-v1-5.md`

Nothing checks that they agree. `parse_text` takes the id from the frontmatter and
never looks at the path. `_path_for` (web.py) finds the file by *name* and never
looks at the frontmatter.

So the two halves of the application resolve a collision in **opposite
directions**: `build_index`'s `by_id = {e.id: e for e in entities}` gives the id to
the **last** file in tree order, while `_path_for` returns the **first** filename
that matches.

## Reproduced on a live server

Commit `tasks/task-0a1009--impostor.md` whose frontmatter says `id: task-0a1001`
and `title: IMPOSTOR`. Then:

- 18 files, 17 entities.
- `/api/index.json` reports `task-0a1001` with the title `IMPOSTOR`; the real
  "CI for the standalone driver v1.5" has silently vanished from the plan.
- `/detail/task-0a1001` renders IMPOSTOR. `/detail/task-0a1009` is a 404.
- **`openproj check` prints `0 blockers, 0 warnings`.**

Then the half that costs you work:

    PATCH /api/entity/task-0a1001 {"fields": {"priority": "low"}}
    -> 200, "committed"

and `git show` proves the commit landed in
`tasks/task-0a1001--ci-for-the-standalone-driver-v1-5.md` — a file that is not in
the index at all, and is **not the record the page was showing**.

A person reads one record on screen, presses save, and a different record changes
on disk. Two hundred, no warning, no conflict.

## How it is reached

Not exotically. A hand-edit, a `git mv`, a copy-pasted template whose `id:` was
never changed, or any rename that leaves the old file behind.

## The shape of the fix

The audit's own suggestion, and it is the right one:

- An id whose file is not named for it, and any id claimed by two files, are
  blocker-class facts. `openproj check` reports them and the pages show them —
  the mechanism exists already, in the `unreadable` banner that round eight built
  for the git door.
- **`_path_for` must refuse rather than pick.** "First match wins" is a coin toss
  about which record a save destroys, and a coin toss is not a resolution.

Two judgement calls to make deliberately rather than by accident:

1. **Does a mismatch make the file unreadable, or a loaded-but-blocked entity?**
   Unreadable drops it from the plan, which is safe but hides the thing you need
   to see to fix it. Loaded-but-blocked keeps it visible and refuses writes to it.
   Prefer the second: "parse permissively, validate strictly" says the record
   loads and the problem is reported, and this is a problem about a record, not a
   file that will not parse.
2. **Which id wins for a duplicate?** Neither. Both files load, both are blockers
   naming each other, and every write to that id is refused until a person
   resolves it. Picking either one is the defect restated.

## What to check when it is fixed

- The impostor corpus above: `check` exits non-zero and names both files; the
  pages say which; the PATCH is refused rather than answered with 200.
- A file renamed so the slug changes but the id still matches — that is legal and
  must stay legal, because the slug is decoration and the id is the fact.
- A `git mv` that changes the id half of the filename — that is the bug, and it
  must be caught.
- The seed corpus and `tests/fixtures/corpus` still load with nothing new
  reported, or the rule is wrong.
