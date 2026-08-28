---
id: task-0f1001
kind: task
title: Lower the scan to the GPU backend
parent: pitch-0f0001
status: in_progress
owner: firecresta
assignees: [firecresta]
reviewers: [siskinbury, jackdawrie]
review_waived: false
start_date: 2026-08-17
priority: very_high
depends_on: []
tags: [hearth, scan-operator, gpu, lowering]
prs: ["kilnlab/hearth#437"]
created_schema_version: 2
person_weeks: 2.0
---

# Lower the scan to the GPU backend

## Problem

`ScanLowering` emits one thing: a `for` over `KDim` carrying the accumulator, wrapped in whatever
the backend calls a kernel. On `hearth_gpu` that is one thread per column and eighty dependent
steps inside it, and the bed solver's forward elimination measures 6.1x slower than the same
stencil on `hearth_cpu`. There is no way to ask for anything else, because there is nothing else
to ask for.

## Solution

A second lowering, `ScanPrefixLowering`, and a choice between the two made from the operator's own
body. The lowering is a block-wide Hillis-Steele pass over the vertical dimension — `log2(nlev)`
rounds inside a block, one small pass carrying the block boundaries — emitted through the same
codegen path as any other backend kernel so it inherits chunking and the launch bounds.

The choice is a whitelist walk in the emitter: descend the operator's body, and take the fast path
only if every operation in it is `add`, `multiply`, `min` or `max` over a field or a scalar. Any
call, any branch, any comparison, and it falls back to the loop. The whitelist is a constant in
`hearth/backends/scan.py`, extended by hand when somebody has a stencil that needs a fifth
operation, and never inferred from a body.

The bed solve's forward elimination qualifies. The first-crack branch has an `if` in it and does
not, and keeps the loop it has today untouched — which is the property the reviewer should check
first, because it is what makes this safe to merge before the benchmark lands.

## Progress

- [x] `ScanPrefixLowering`, block-local pass, green on `embedded`
- [x] block-boundary carry, and the 12-line reproducer from `issue-b3c4d5` as a regression test
- [ ] the whitelist walk, and the fallback assertion for every non-qualifying operator in the suite
- [ ] chunk sizes other than 64 — `chunk_size: 32` is untested and the boundary maths is the part
      that was wrong the first time
- [ ] launch bounds for `nlev` above 128
