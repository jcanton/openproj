---
id: prod-7c2b81
kind: product
title: hearth
parent: null
# The three keys below are DELIBERATELY WRONG. See "Three fields that are wrong"
# in the body: they are the only file in either corpus that gives the
# `unread_fields` rules something real to fire on.
person_weeks: 2
depends_on: [prod-6d1a70]
owner: redpollard
tags: [hearth, dsl]
created_schema_version: 2
---

# hearth

The stencil DSL the model's kernels are written in, and the backends they are lowered to:
`embedded` for debugging, `hearth_cpu` and `hearth_gpu` for anything that has to run. A change
here reaches every subsystem above it at once, which is why it is a product of its own rather
than a directory inside the model.

Under it: `proj-9a4c25`, the backend work the bed solver is waiting on.

## Three fields that are wrong

`person_weeks`, `depends_on` and `owner` are written into the frontmatter above by hand, on
purpose, and every one of them is a field a product does not read. A product is a grouping: it is
never scheduled, so it has no appetite and no owner, and it waits on nothing because its projects,
pitches and tasks are what wait.

They are here because until this file existed, three validation rules had no document to fire on
anywhere in the repository — they were exercised only by records the tests built in memory, which
proves the rule and not the reading of a file. Two of them report a blocker and one a warning, and
that difference is the point as well: an appetite or a dependency on a container is a claim about
work that is not there, while an owner on it is a name nobody reads. Do not "fix" this file. The
fixture asserts all three.
