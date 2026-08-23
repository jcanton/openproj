---
id: note-a03c59
kind: note
title: Two backends is one backend and a switch
status: thinking
written_by: Whimbrelson
written_on: 2026-07-08
tags: [hearth, backend]
became: [pitch-6f2d18, proj-9a4c25]
created_schema_version: 2
---

Every hearth operator that has been taught to run on the GPU has grown a second implementation
beside the CPU one, and nothing keeps the two in step except whoever last touched both. The scan
is where I stopped being able to argue that this is fine: the carry is threaded on CPU and
per-chunk on the device, and that is not a decision anybody took — it is a thing that happened
twice.

The half-formed idea is that a backend is one lowering with a switch inside it. One operator
definition, one set of semantics, and the device-specific part pushed down to where the loop is
emitted, rather than sitting at the top where it can quietly change what the operator *means*.

What I did not know when I wrote this:

- whether "same semantics, different emission" survives an operator that genuinely wants a
  different algorithm on the device — and the scan is a candidate for exactly that
- whether this is one piece of work or a standing rule applied to twenty operators that already
  have two definitions each
- who it belongs to, since it is not a port of anything and none of the existing groups own it

## What it became

Both answers, in the end, which is why `became` has two entries and one of them is not a pitch.
The standing group — somewhere backend work can hang and wait on the model repository — became
`proj-9a4c25`. The first bet under it, the scan operator, because it is the one already costing
people days, became `pitch-6f2d18`.

A note is promoted the moment *either* target exists, so this would read `promoted` even if the
project had never been written. It is worth knowing that the corpus contains a note that split.
