---
id: task-6a5c02
kind: task
title: Lower the scan operator to the GPU backend
parent: pitch-6f2d18
status: in_progress
owner: redpollard
assignees: [redpollard, chiffchaffy]
reviewers: [Whimbrelson]
review_waived: false
assigned_on: 2026-08-17
priority: high
depends_on: []
tags: [hearth, scan-operator, gpu]
prs: ["kilnlab/hearth#802"]
created_schema_version: 2
person_weeks: 1.5
---

# Lower the scan operator to the GPU backend

## Problem

The emitter has one code path for `scan_operator` and it writes a sequential loop over `KDim`.
On `hearth_gpu` that is one thread per column and 80 dependent steps inside it, which is where the
bed solve's forward elimination spends 6.1x what it spends on the CPU.

## Solution

A second lowering, chosen by the emitter, not by the stencil. The kernel is a block-wide
Hillis-Steele prefix pass over the vertical dimension with a second pass carrying the block
boundaries, and the choice between it and the existing loop is made by walking the operator body
against a whitelist of associative operations — add, multiply, min, max. Anything else, including
the first-crack branch, keeps the loop it has today.

## Progress

- [x] whitelist walk over the operator body, with the loop as the default
- [x] block-wide pass emitted and green on `embedded`
- [ ] carry between blocks
- [ ] the bed solve's forward elimination on `Drum_Hex_20x4_50mm`
