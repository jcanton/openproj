---
id: pitch-48ea9e
kind: pitch
title: Tracer adv needs exchange
parent: null
status: in_progress
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: 2.0
shaped_by: null        # REQUIRED from schema_version 2; not in source
assignees:
  - nfarabullini
  - OngChia
assigned_on: null
cycle: 35
priority: medium
depends_on: []
tags:
  - greenline
  - icon4py
  - tracer-advection
  - halo-exchange
prs: []
---

> **Migration note.** Converted from row 17 of *[Greenline] Open projects TABLE*
> (<https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg>): name "Tracer adv needs exchange", status WIP,
> Who `N`, Priority blank, Depends-on blank, PR blank, Shape doc blank.
> Table note, verbatim: *"Add halo exchanges to tracer adv (seems that exchange has been added in
> advection granule)"*.
>
> Shaping document located at <https://hackmd.io/@gridtools/r1JB9OjnWx> (long id
> `yyFoCEVHSmOFBcccHq-ptg`). The team listing titles it **[ICON4Py] Tracer advection**; the note body's
> own H1 is **[Greenline] Tracer advection exchange**. The table row carries no shape-doc link, so the
> match is by subject: the note is entirely about the failing `p_tracer_new` exchange, which is this
> row's scope. Body below is that note, verbatim apart from the removal of the empty HTML template
> comments. The raw "Who" string in the table is `N`.

Finish tracer advection exchange work

- Shaped by: Nikki
- Appetite (FTEs, weeks): 2 week FTE
- Developers: Nikki, Chia Rui

## Problem

Tracer advection exchange almost validates (but not fully). `p_tracer_new` is the only field that
still has issues with tolerances higher than 2e-5.

## Appetite

2 weeks

## Solution

Figure out where the problem is. Chia Rui will help

## Rabbit holes

Exchange is a black box sometimes.

## No-gos

*(empty in the source note)*

## Progress

*(the source's Progress section holds only the unfilled template placeholder, "Task 1
([PR#xxxx](https://github.com/icon-exclaim/icon4py/pulls))" — no real PR was ever listed, and the
table's PR cell for row 17 is likewise empty. No sub-work is enumerated anywhere in the source, so no
task records were created for this pitch.)*

