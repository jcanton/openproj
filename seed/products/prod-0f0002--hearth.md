---
id: prod-0f0002
kind: product
title: hearth
parent: null
tags: [hearth, dsl, compiler]
created_schema_version: 2
---

# hearth

The stencil DSL every kiln4py kernel is written in, and the backends they are lowered to:
`embedded` for debugging, `hearth_cpu` and `hearth_gpu` for anything that has to run, and
`emberjit` for the experiments nobody has retired yet.

It is a product of its own rather than a directory inside the model because a change here reaches
every subsystem above it in one commit, and because the model is not its only consumer.

```
prod-0f0002  hearth
└── proj-000002  scan_backend
```
