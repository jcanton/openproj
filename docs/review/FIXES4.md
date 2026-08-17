# Round six — what the final audit found

Everything below was reproduced against a live server in a real browser, not read
out of a diff. Line numbers are from 365486d; confirm before editing.

---

## A. Two ways an ordinary form field breaks the plan permanently

The question that found these: **the same arithmetic is written three times — which
copies got the guard?** `schedule.py:78` has `_runs_past_the_calendar`, whose
docstring describes exactly the failure it prevents. Two other places add weeks to
a date or step a date forward in a loop, and neither was guarded.

**A1 — BLOCKER. `Cycle.ends_on` / `builds_until` (`model.py:64,69`).** Type
`500000` into Cycles → "build weeks", click through the confirmation: commit
written, nine routes answer 500, `/healthz` alone survives. Reachable from a form
field with no bound, by anybody.

**A2 — BLOCKER. `_month_ticks` (`render.py:582`).** Type `31/12/9999` into the
detail page's "Assigned on": commit written, `/timeline` answers 500 permanently.
Worse than A1 in one way — `openproj check` reports "0 blockers, 0 warnings" and
`openproj render` writes no files at all, so both of the tools you would reach for
to diagnose it are silent or dead. This one is twelve lines after the `x()` helper
that was fixed for this exact failure and carries a comment saying so.

Both are the same permanence as before: a commit on a protected branch, and the
500ing pages will not hand over the sha to craft a repair against.

Guard both the way the scheduler already does. Then go back and answer the question
properly: grep every place in the codebase that does date arithmetic or steps a
date in a loop, list them in your report, and say for each whether it is guarded
and why. A fourth copy is the next blocker.

Refuse the write, too. A build-weeks of 500000 is not a number anybody means, and
the refusal belongs beside the one the cycle route already makes.

---

## B. Two ways localStorage loses somebody's work

**B1 — HIGH. The table renders an empty body if storage throws.** `render.py:2141`
is a bare read at the top of the page's main script, so in any browser where
localStorage access throws — private mode, blocked cookies, some enterprise
policies — the table shows a bare heading and "17 of 17 shown" over nothing at all.
That is F1's exact failure, reintroduced by a mechanism rather than by a filter.

Nine of the twelve storage calls in the file are unguarded. The three that are
guarded carry comments proving the hazard was known. Wrap the lot in one helper
that fails to a default, and use it everywhere — a bare `localStorage` should not
appear in the file.

**B2 — HIGH. A restored draft silently reverts a colleague's commit.** The draft
pairs old text with a freshly-rendered `base_commit`, so `store.write`'s
compare-and-swap sees no conflict and takes it. Proven end to end: 0d12423 over
4a364f3, no 409, no conflict report, the other person's edit simply gone.

A draft has to carry the commit it was drafted against, and restoring one has to go
through the same compare-and-swap as any other write — with the conflict report the
other write paths now show.

---

## C. jcanton's frozen-column edge is dead code

He asked for the vertical rule to appear only while the table is scrolled sideways,
or to go. The class toggling shipped and is perfect — absent at `scrollLeft === 0`,
present the moment you drag, gone when you come back.

**The rule it switches on is never painted, in either state.** An *outset*
`box-shadow` on a `<td>` or `<th>` inside a `border-collapse: collapse` table is
not painted by Chrome. Proven: a 14px red shadow forced onto those exact selectors,
class confirmed present, computed value confirmed red — no pixel. Add
`border-collapse: separate` and it appears instantly.

So `render.py:2488-2491` and the `frozenEdge` handler at `render.py:2394` do
nothing. The resting state is accidentally what he wanted; scrolled right, the
frozen pair has no edge at all and half-clipped `+1` badges sit hard against the
title column looking like a clipping bug.

The file already knows the answer one comment earlier (`render.py:2453`): a
collapsed cell needs an **inset** shadow. `inset -1px 0 0 var(--line)` on the same
selector paints on every row.

`tests/test_cascade.py:139` asserts the stylesheet resolves to the right value, so
it passes while nothing is drawn. A test that cannot tell painted from unpainted is
the reason this survived — make it one that can, or say in the test why it cannot.

---

## D. The table still scrolls sideways between 1100 and 1400px

The fit's own floors put the fourteen-column minimum at **1354px**, but the media
query that sheds columns only fires at **1100px**. So every window from 1101 to
1393 scrolls: 293px of overflow at 1101, 114px at 1280, 28px at 1366. Below 1091
the eleven-column layout scrolls too.

Two numbers that have to agree are written in two places, one in CSS and one in
JavaScript, and they do not. The fit is the one that knows: it can compute its own
minimum from the floors and the fixed columns. Drive the shedding from that
measurement instead of from a typed breakpoint, so the two cannot drift again — and
check the eleven-column layout's own minimum the same way.

**D2.** The `+N` badge is clipped by up to a third of its width wherever a clamped
column falls below about 128px, and by 368px when a login is sixty characters. The
badge is the promise the clamp makes; a clipped badge breaks it. Either the floor
accounts for the badge, or the badge is pinned to the right edge of its cell so it
is never the part that gets cut.

---

## E. Two smaller things, both visible

**E1.** On the cycle page the bet table's assignee values are borderless inputs
whose text is cut mid-word — "…jcanto" — with no ellipsis, so they read as broken
text rather than as fields.

**E2.** The detail page states the status twice, as a chip in the meta line and
again as STATUS in the facts column, forty pixels apart. Defensible — the second is
the editable control — but say it once, or make the difference visible.

Not in scope, recorded so it is not lost: the timeline overflows horizontally below
370px, and at a 1500px window three of seventeen titles wrap to two lines, which is
the authorised fallback rather than a defect.
