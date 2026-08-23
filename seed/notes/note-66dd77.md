---
id: note-66dd77
title: Two backends is one backend and a switch
status: thinking
written_by: firecresta
written_on: 2026-06-02
tags: [hearth, backend]
became: [proj-000002, pitch-0f0001]
---
Every hearth operator that has been taught to run on the GPU has grown a second
implementation beside the CPU one, and the two are kept in step by hand and by
memory. The scan is where that stopped being tolerable: the carry is threaded on
CPU and per-chunk on GPU, and the reason they differ is not a decision anybody
took — it is that nobody wrote down that they should not.

The half-formed idea is that a backend is one lowering with a switch in it. One
operator definition, one set of semantics, and the device-specific part pushed
down to where the loop is emitted rather than sitting at the top where it can
change what the operator *means*.

What I do not know:

- whether "same semantics, different emission" survives the operators that
  genuinely need a different algorithm on the device, and the scan may be exactly
  one of those
- whether this is one piece of work or a policy — a rule that no operator may
  have two definitions, applied to the twenty that already do
- who owns it. It is not a physics port, so it belongs to none of the boxes that
  currently have owners

Written after two days of chasing a bed-moisture integral that was wrong only on
the GPU and only above 64 cells (issue-b3c4d5).

Split at the cycle-37 betting table: the standing group of backend work became
`proj-000002`, and the first bet under it — the scan operator, because it is the
one that already hurts — became `pitch-0f0001`.
