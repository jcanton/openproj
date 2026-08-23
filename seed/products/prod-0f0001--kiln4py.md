---
id: prod-0f0001
kind: product
title: kiln4py
parent: null
tags: [kiln4py, model, port]
created_schema_version: 2
---

# kiln4py

The Python re-implementation of KILN, the plant's Fortran roasting model: one package per
subsystem — transport, throughflow, the bed, the burner — each validated against serialized
Fortran output before it is allowed to replace anything.

A product is a container and carries none of the things work carries: no owner, no dates, no
appetite, no cycle. The project under it holds those, and the pitches under that hold the bets.

```
prod-0f0001  kiln4py
└── proj-000001  whole_roast
```

What it is here for is the edge that crosses it. `task-0c1001`, porting the bed solver, waits on
`task-0f1001` in the other product, because the bed solve is the first stencil that needs a scan
the GPU backend can actually run. Written down in one plan, that is a dependency; kept in two
plans, it is something somebody remembers.
