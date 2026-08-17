# Tailoring openproj to how the team actually works

**Status:** decided 2026-08-16; the accepted items are built on `shapeup_feats`.
**Evidence:** the public HackMD notes, read 2026-08-16 — the cycle-37 sheet
(`GGkElar4QK-33TXRhbKxAg`), the Greenline open-projects table (`HvHaFPQrRP-8d9UzMA_Gkg`), the team's
shaping template (`nu2KGoCATcmcPWNCQmTOOw`), and six pitches: turbulence
(`5qZhTIsARRaldJb1fq06_A`), bitwise reproducibility (`wwTnvD2tR1ijrZD1sxbdDg`), domain decomposition
(`3aTBq9-6QbKZrHOtsA-GpA`), GT4Py development (`gftvRMkaTW6t5qrTf_dPnw`), radiation
(`M9oXKVfrQyKIA7BTm5PBxQ`), simplified land (`i8bToj2ZRg6GFwDdU40UqA`).

---

## 0. Context

openproj was specified against Shape Up as written. The team runs something adjacent to it, and the
differences are consistent rather than sloppy. The question this document answered was not "how
close is the tool to the book" but "what does the tool fail to record that the team already writes
down", plus the narrower one the team asked for: which habits from the book are half-adopted here
and would pay for being used fully.

What the notes establish:

- **The pitch template is `Problem / Appetite / Solution / Rabbit holes / No-gos / Progress`**, plus
  `For later` or `Scratchpad`, with a header carrying *Shaped by*, *Appetite (FTEs, weeks)* and
  *Developers*. All six pitches sampled use it.
- **`## Progress` is a checkbox list with PR links** and the instruction to *"add a preliminary list
  of coarse-grained tasks … refine them with finer-grained items"*. It is the team's live progress
  record; openproj had nowhere for it.
- **`Appetite (FTEs, weeks)`** settles the person-weeks question the cycles design decided as D-C4.
  The sheet's `full cycle` is shorthand for staffing, not a second unit.
- **`Shaped by` is frequently two or three people.**
- **No diagrams in any note sampled.** Shaping here is text.
- **Nothing is drawn from the book that the team does not already do**: no hill charts, no backlog
  ranking, no breadboards.

## 1. Decisions

| # | Feature | Decision |
|---|---|---|
| 1 | `## Progress` counted from the body | **Built.** Accepted on the condition that it costs nothing: it is read-only, requires nothing, and shows nothing where there is no list. |
| 2 | Body templates on create | **Built**, from the team's own template rather than from the book. Its guidance stays in HTML comments and is stripped at render. |
| 3 | Missing `No-gos` / `Rabbit holes` | **Built as a printed note on the detail page only** — never a `Problem`, never CI. "We don't use no-gos and rabbit holes enough" is a reason to mention it where somebody is already editing, not to fail a build over it. |
| 4 | `## For later` surfaced | **Built.** |
| 5 | Carryover counted in cycle load | **Built.** |
| 6 | Re-betting as a distinct record | **Deferred.** |
| 7 | `postponed` as an outcome | **Declined** — leaving a pitch `ready` says the same thing. It produced a better idea instead: a **notes box on the cycle**, so what came up at the betting table has somewhere to live. Built. |
| 8 | Betting-table and review-meeting dates | **Deferred.** |
| 9 | Appetite in cycle units | **Declined.** Appetite is person-week effort and the assignees divide it; the tool already does this (D-C4, `schedule._duration_weeks`). `full cycle` on the sheet is staffing shorthand, not a unit openproj needs. |
| 10 | Decide elapsed vs person-weeks | **Already decided** — D-C4, and now stated in the README's mapping table so the next reader does not have to re-derive it. |
| 11 | Multiple shapers | **Built.** |
| 12 | Roster grouped by institution | **Declined.** If institutions turn out to matter, the answer is separate plans and separate deployments, not a grouping column. |
| 13 | Availability that admits uncertainty | **Declined.** "Better a lie that forces a good estimate than a field that accepts `some time > 0`." |
| 14 | A `buggy` status | **Declined.** Work that is wrong does not get merged; it goes back to `in_progress` or is shelved. |
| 15 | Five priority levels | **Built**: `very_high`, `high`, `medium`, `low`, `very_low`. |
| 16 | Timeline rule at the end of build | **Built.** |
| 17 | Realign the seed corpus | **Deferred to go-live**, with real data rather than a demo. |
| 18 | Documentation drift | **Built.** |

## 2. What the built items are

**1 — Progress.** `model.checklist` counts ticked and total task-list items anywhere in a body,
skipping fenced code; `model.sections` reads the headings. `Index.progress` holds the counts, the
entity page gains a row with a meter, and the table gains a derived `progress` column **only once
some body in the plan keeps a list** — this was the condition the feature was accepted under, and a
permanently empty column across fifteen others reads as broken rather than unused.
`predicate=untracked` finds live work with no checklist. Nothing validates, requires or rewrites a
body.

**2 — Templates.** `render.TEMPLATES` carries a pitch, task and project body. The create page has a
picker; switching kind switches template while the box still holds a template, and stops the moment
somebody types. `render._without_comments` strips HTML comments before markdown runs, so the
template's guidance is invisible on the page and a pitch pasted from HackMD no longer arrives with
its own instructions showing.

**3 — Hints.** `render._shaping_hints` prints a muted note on a `ready` or `in_progress` pitch whose
body has no `Rabbit holes` or no `No-gos`. Both spellings of each are accepted. Detail page only.

**4 — For later.** A derived row naming how many items are kept, and `predicate=for_later`. The list
is left where it was written; repeating it beside the body would be two copies of one list.

**5 — Carryover.** `Index.counts_in` decides whether an entity's work lands in a cycle: bet into it,
or bet earlier, still `in_progress`, and overlapping its window. `load` and the cycle page's
"scheduled until" column both ask it, and `carried_into` names what was counted so the number can be
argued with. An undated cycle counts only its own bets — a number with no window is a hypothetical.
A carried item is charged its whole size: nothing records how much of a bet is left, and an invented
percentage is worse than a visible overcount.

**7′ — Cycle notes.** The cycle record always had a body; the page now has a box for it, saved in
the same PUT as the roster and only when it changed.

**11 — Shapers.** `shaped_by` is a list. A bare string parses, and writes back as a bare string,
so no file has to change.

**15 — Priorities.** Five rungs in `PRIORITY_RANK`, ordered highest-first in every picker, with the
graph's border widths following the ladder.

**16 — Build rule.** The timeline draws a solid rule where a cycle stops building — the date an
overrun is measured against — a dashed one where the window closes, and shades the cool-down
between them. Before this a bar could end visibly left of the only rule on the chart and still be
flagged amber.

**18 — Docs.** The README's status table said `todo`/`wip`; the spec's schema said the same and gave
priority as `0..3` ints. Both now match the code, and the README gains a mapping from each HackMD
artifact to its openproj equivalent plus a short statement of where this deliberately departs from
the book.

## 3. Verification

- `uv run openproj check seed` — zero blockers.
- `uv run pytest` — the suite, including new tests for the checklist reader, carryover, the
  templates, the hints and the two timeline rules.
- `uv run openproj render seed out --today 2026-08-17` — the timeline's two rules; the cycle page is
  server-rendered, so `uv run openproj serve --repo seed --auth dev` for the betting table.

## 4. Still open

Deferred, in the order they are likely to matter: re-betting (6) — a standing item like
`[GT4Py] Development work` is bet every cycle and currently reads as a permanent overrun; the two
cycle dates (8); and the seed corpus (17), which still teaches a six-week build the team does not
run.
