---
id: pitch-5e7b1c
kind: pitch
title: CI for standalone driver v1.5
parent: null
status: wip
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
appetite_weeks: 4.0
shaped_by: null        # REQUIRED from schema_version 2; not in source
assignees: [jcanton, msimberg]
assigned_on: 2026-05-26
cycle: 36
priority: 1
depends_on: []
tags: [greenline, icon4py, standalone-driver, distributed, ci, buggy]
prs: []
---

## Migration note

Imported from row **5b** of the *[Greenline] Open projects TABLE*
(<https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg>, last edited 2026-08-12).

Row 5b, verbatim:

| Nr | Name | Priority | Status | Who | Depends on | PR | Shape doc | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5b | CI for standalone driver v1.5 | High | Buggy | J+Mikael+N | *(empty)* | *(empty)* | *(empty)* | Distributed version of above |

Decisions taken during the import, all of them reversible:

- **Shaping doc was not declared, it was identified.** Row 5b's `Shape doc` cell is empty.
  `OVERVIEW - Cycle 36 05/26` (<https://hackmd.io/@gridtools/SyllbxXxGx>) bets a project
  *[Greenline] Distributed driver* → <https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA> with developers
  Jacopo and Mikael, and that note's Problem statement is precisely this row's subject and status
  (the standalone driver is not bit-identical between single- and multi-rank runs). That note is
  reproduced below and is the basis for `appetite_weeks` and `cycle`. Confidence: medium-high, by
  content and personnel match, not by declaration.
- **`Buggy` is not in the Appetite status enum.** Mapped to `wip` — the distributed standalone
  driver test exists and runs but does not give bit-identical results. The original word is
  preserved losslessly as the `buggy` tag; nothing was invented to represent it.
- **`Who: J+Mikael+N`.** `J` → `jcanton` (Jacopo Canton) and `Mikael` → `msimberg`
  (Mikael Simberg) are safe: both are C2SM/icon4py contributors, both appear in the corpus with
  those exact handles (the shaping note is "Shaped by: @jcanton" and quotes "(Mikael): no funny
  line at equator..."), and the cycle-36 overview lists exactly "Jacopo, Mikael" as developers.
  **`N` was deliberately not resolved.** In this table `N` most likely means "Nikki"
  (→ `nfarabullini`, Nicoletta Farabullini, who is listed under EXCLAIM in the cycle 36/37
  rosters and is the sole developer of the row-17 shaping note whose Who cell is also `N`), but a
  second "Nina" (→ `ninaburg`, Nina Burgdorfer) also appears in the corpus, and the cycle-36 bet
  for this project names only Jacopo and Mikael. Left out rather than guessed.
- **`Depends on` is empty, so `depends_on` is empty.** The Notes cell "Distributed version of
  above" is an implicit dependency on **row 5** (*CI for standalone driver v1*), which is not part
  of this assignment. It is reported in `unresolved` as a raw string instead of being given a
  fabricated id.
- **Priority.** The table uses four levels (High+, High, Medium, Low); mapped order-preservingly
  onto the Appetite scale (High+ → 0, **High → 1**, Medium → 2, Low → 3).
- **`assigned_on: 2026-05-26`** is not stated in the pitch note. It is the cycle-36 **betting
  table** date, stated verbatim in `OVERVIEW - Cycle 36 05/26` ("**Betting table: 26.05.2026**"),
  which is the meeting at which this project was assigned to Jacopo and Mikael; the note itself was
  created that same day. Null it if the importer wants only dates typed on the entity itself.
- **`prs: []`** — the row's PR cell is empty and the shaping note links a branch and a compare
  view, not PRs. Related PRs found elsewhere are named in prose below but were not promoted into
  the field.

---

## Shaping document: [ICON4Py] Distributed driver

Source <https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA> (team permalink
<https://hackmd.io/@gridtools/H1D-S-Qefl>), created 2026-05-26, last changed 2026-06-03,
HackMD tag `cycle 36 05/26`. Shaped by @jcanton. Verified against the live note during migration.
Note the title drift: the cycle-36 overview calls it *[Greenline] Distributed driver*, the note's
own H1 says *[ICON4Py] Distributed driver*.

### Problem

1. The (standalone) driver is not bit-identical between single- and multi-rank runs on any of the
   backends.
2. @ChiaRuiOng seems to have found a bug on the equator when running with 2 GPUs for 7 days.
   (The source note embeds a screenshot, `Screenshot 2026-05-26 at 13.47.01`, not carried over.)

### Appetite

> Appetite (FTEs, weeks): possibly whole cycle
>
> Up to the whole cycle.

Cycle 36 is stated as "Length: 4 weeks" in its overview, and its betting table (26.05.2026) and
review meeting (23.06.2026) are exactly 4.0 weeks apart. Hence `appetite_weeks: 4.0` elapsed weeks.
The source phrases this as an upper bound ("up to"), so treat 4.0 as a ceiling.

### Solution

- Find bug(s), if any.
- Set up bit-identical tests for code validation.

### Rabbit holes / No-gos

Both sections were left as empty template comments in the source.

### Progress (as of the note's last edit, 2026-06-03)

The five open items below were extracted into task entities `task-53a9f0`, `task-5c1d84`, `task-5f062b`,
`task-5a4e39`, `task-58d7c6`. They are the note's own coarse-grained task list, not an invention of this
migration.

---

## Where this sits in the lineage

Related notes, none of which replace the one above:

- **Row 5 (v1), the thing this row is the "distributed version of"**:
  *[Greenline] Warm Bubble: CI for Standalone Driver* <https://hackmd.io/hhDl0NZqQg-O-zMFWHiLHw>.
  Its solution list ends with the truncated bullet "Perform multinode data test when t" — the seed
  of row 5b.
- **Cycle 35 warm-bubble hub** <https://hackmd.io/Uf17TB85RHidh7oDino-cA> lists, among open tasks,
  "Merge at least a gtfn_gpu distributed CI pipeline" and "Distributed GPU standalone driver test"
  — this row, before it got a dedicated shaping note.
- **Cycle 37 continuation**: <https://hackmd.io/wwTnvD2tR1ijrZD1sxbdDg> (listing title
  *[ICON4Py] GPU bitwise reproducibility*; its body H1 is still the stale `# [ICON4Py] Scientific
  validation`). It records that C2SM/icon4py#1303 added a 7-day standalone driver validation test
  expecting bitwise-identical results between 1 and 4 ranks, enabled only for CPU backends with
  `CXXFLAGS=-ffp-contract=off`, and that C2SM/icon4py#1368 later enabled bitwise-identical checks
  for the standalone driver and most static fields. Remaining scope there is GPU backends. Its
  appetite is contradictory across sources (cycle-37 overview: "1-2 weeks"; note body: "One
  cycle"), which is one reason it was not used as this row's appetite source.
- **Superseded duplicate**: *[ICON4Py] Standalone driver single- vs multi-rank debugging*
  <https://hackmd.io/Ms13BCixSwamn2oMr1O8Ig> — created the same day, same developers, but an empty
  template, and its reference in the cycle-36 overview is defined and never used. Not made a
  separate entity.
- **Explicitly NOT this row**: *[Greenline] Distributed tests in CI*
  <https://hackmd.io/O4Fymu1dTxqTZSC8rdiVVw>. An upstream corpus map proposed it for row 5b, but it
  contains no standalone-driver content (it is about distributed unit tests: PR692, PR1012,
  `test_distributed_*`, `test_parallel_*`), and the table itself attaches it to **row 9** via the
  `[MPI CI project]` link. Flagged in `unresolved` so the next stage does not double-assign it.

## Not created

No parent project entity. Row 5b's group is encoded only by blank rows in the source table; there
is no group heading text to name a project after.
