---
id: pitch-5e7b1c
kind: pitch
title: CI for standalone driver v1.5
parent: null
status: in_progress
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: 4.0
shaped_by: null        # REQUIRED from schema_version 2; not in source
assignees: [jackdawrie, merganserly]
assigned_on: 2026-05-26
cycle: 36
priority: high
depends_on: []
tags: [griddle, kiln4py, standalone-driver, distributed, ci, buggy]
prs: []
---

## Decisions taken when this was bet

The betting table spent most of its half hour on this one, and it is worth writing down what was
settled, because four of the five decisions are reversible and somebody will want to reverse one.

| Decision | What was agreed | Reversible |
| --- | --- | --- |
| Scope | Bit-identical between 1 and N ranks, CPU backends first | yes |
| Status word | Carried as the `buggy` tag, not as a blocker | yes |
| Third developer | Left off | yes |
| Appetite | Up to the whole cycle, read as a ceiling | no |
| Dependency on v1 | Not recorded as an edge | yes |

**"Buggy" is a real state and the enum does not have it.** The distributed standalone driver test
exists, it runs, and it does not give bit-identical results. That is not `ready` and it is not
`done`; it is work in progress with a known defect, which is what `in_progress` plus the `buggy`
tag says. The word was kept as a tag rather than thrown away, because "there is a test
and it is wrong" is different information from "there is no test", and that difference is the whole
reason this row exists.

**Two developers, not three.** A third name was floated in the room and left off. The argument for
including them was that they know the exchange code better than either of the two named; the
argument against, which won, was that the cycle-36 bet named two people, and a plan that quietly
grows a third assignee has stopped describing what was bet. If the work turns out to need that
person, re-bet it rather than editing the roster.

**The appetite is a ceiling, not an estimate.** The phrase used in the room was "possibly whole
cycle", and cycle 36 runs four weeks from its betting table to its review. Four is therefore the
most this may take, not the amount it is expected to take. That distinction matters here, because
the five tasks underneath already add up to more than four — the validator says so, in those words
— and the right response to that is to cut scope, not to raise the number.

**The dependency on v1 was left out on purpose.** The row this one grew out of is the single-rank
CI work, which is finished. Writing that edge down would add a blocker that can never block
anything, and every such edge makes the graph a little less worth reading. The prose says it
instead.

**`prs` stays empty until something merges.** There is a branch and there are two comparison runs,
and neither of those is a pull request. Related work elsewhere in the repository is named in prose
further down. Promoting any of it into the field would make this record claim credit for somebody
else's merge.

**`assigned_on` is the betting-table date**, 2026-05-26 — the day the room agreed to this, which is
also the day the shaping note was written. It is not the day anybody started typing, and nothing
here pretends that it is.

---

## Shaping document: the distributed driver

Written on the day of the betting table and last touched on 2026-06-03, after the first week of
work had already changed what the Progress section said. The four sections below are the shaping
argument as it was put to the room, unedited since.

### Problem

1. The (standalone) driver is not bit-identical between single- and multi-rank runs on any of the
   backends.
2. @Oxpeckerly seems to have found a bug at the drum seam when running with 2 GPUs for a seven-day
   roast. A screenshot went round; reproducing it properly is the first task.

### Appetite

> Appetite (FTEs, weeks): possibly whole cycle
>
> Up to the whole cycle.

Cycle 36 is four weeks long: its betting table on 26.05.2026 and its review meeting on 23.06.2026
are exactly four weeks apart. Hence `person_weeks: 4.0`. The source phrases this as an upper bound
— "up to" — so treat four as a ceiling.

### Solution

- Find bug(s), if any.
- Set up bit-identical tests for code validation.

### Rabbit holes / No-gos

Neither section was filled in when this pitch was shaped.

### Progress (as of 2026-06-03)

The five open items on this pitch were pulled out into `task-53a9f0`, `task-5c1d84`, `task-5f062b`,
`task-5a4e39` and `task-58d7c6`. They are the shaper's own coarse-grained list, not an invention.

---

## Related work

None of the following replaces the shaping document above, and none of it is a dependency.

- **The single-rank CI work this one is the distributed version of.** Finished. Its solution list
  ends on a truncated bullet — "Perform multinode data test when t" — which is, more or less
  literally, where this row starts.
- **The cycle-35 whole_roast hub** listed "Merge at least a hearth_gpu distributed CI pipeline" and
  "Distributed GPU standalone driver test" among its open tasks, months before either had a shaping
  note of its own. This row is those two, grown up.
- **The cycle-37 continuation** is where the GPU half goes. `kilnlab/kiln4py#2298` added a seven-day
  standalone driver validation test expecting bit-identical results between 1 and 4 ranks, enabled
  only for CPU backends and only with `CXXFLAGS=-ffp-contract=off`; `kilnlab/kiln4py#2415` later
  turned on bit-identical checks for the driver and for most static fields. What is left there is
  the GPU backends, which is precisely where this pitch keeps failing. Its appetite is contradictory
  across sources — one says "1-2 weeks", the note body says "one cycle" — which is one reason it was
  not used as this row's appetite.
- **A duplicate that was deliberately not made a record.** Somebody opened a second note the same
  day, same developers, same subject, and never filled in the template. It is referenced once from
  the cycle-36 roster and never again.
- **Explicitly not this row: the distributed unit-test work.** It contains no standalone-driver
  content at all — it is about `test_distributed_*` and `test_parallel_*` — and an earlier reading
  of the board attached it here by mistake. Written down so that the mistake is not made twice.

## Not created

No parent project record. This row's group exists only as a gap between rows on the board; there is
no heading text to name a project after.
