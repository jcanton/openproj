---
id: issue-b3c4d5
title: The GPU backend drops the scan carry across a chunk boundary
status: ready
reported_by: siskinbury
opened_on: 2026-08-05
tags: [hearth, gpu, scan-operator]
pitched_into: [pitch-0f0001]
---
On the 20x4 drum mesh with `chunk_size: 64`, every cell whose index is a multiple
of 64 restarts the accumulation from zero: the carry is initialised per chunk
instead of being threaded through it. The bed-moisture column integral comes out
low by roughly one chunk's worth wherever that happens.

CPU is right, which is why no datatest caught it — the CPU backend runs
unchunked, so the two code paths have never once computed the same thing on the
same input.

Reproducer on branch `scan-carry`, twelve lines, no mesh needed.

Not patchable in place: the carry has to become part of the chunk's state, which
is the interface the GPU lowering is rewriting anyway. Pitched into that work
rather than fixed twice.
