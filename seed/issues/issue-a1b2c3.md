---
id: issue-a1b2c3
title: Halo exchange drops a rank when nproma is not a multiple of the block size
status: ready
reported_by: halungge
opened_on: 2026-08-11
tags: [halo, distributed, mpi]
pitched_into: []
---
Reproduced on Alps with 12 ranks and `nproma: 40`. The last block is short and
`ExchangeRuntime` skips it silently — no error, just a wrong field on rank 11.

Probably worth a pitch rather than a quick fix: the same shape of bug is likely
in the vertical exchange too.
