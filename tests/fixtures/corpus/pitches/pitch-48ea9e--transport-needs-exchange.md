---
id: pitch-48ea9e
kind: pitch
title: Transport needs exchange
parent: null
status: in_progress
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: 2.0
assignees:
  - nightjarelli
  - Oxpeckerly
assigned_on: null
cycle: 35
priority: medium
depends_on: []
tags:
  - griddle
  - kiln4py
  - transport
  - halo-exchange
prs: []
---

> **Where this came from.** The transport module got its halo exchanges
> during the port, and the validation suite went green on everything
> except one field. That was six weeks ago; it is still red. The board
> row reads "Add halo exchanges to transport" — written before anybody
> had looked, and wrong in the way that matters: the exchanges are
> there, they run, and the answer is off in the fifth digit. This is a
> debugging job now, not a porting job.
>
> Worth knowing before reading the plan: the failure is stable — same
> ranks, same mesh, same digits every run — which rules out an
> uninitialised halo and points at either the exchange pattern or the
> order in which the boundary cells are written.

Finish the transport exchange work

- Shaped by: Nightjar
- Appetite (FTEs, weeks): 2 week FTE
- Developers: Nightjar, Oxpecker

## Problem

Transport exchange almost validates (but not fully). `p_aroma_new` is the only field that still has
issues with tolerances higher than 2e-5.

## Appetite

2 weeks

## Solution

Figure out where the problem is. Oxpecker will help

## Rabbit holes

Exchange is a black box sometimes.

## No-gos

*(nothing was written here)*

## Progress

*(Nothing ticked here. No pull request has been opened, and the plan above does not decompose into
anything worth writing down as a task — it is one person reading an exchange pattern until it makes
sense. Progress will be a single PR, or it will be nothing.)*
