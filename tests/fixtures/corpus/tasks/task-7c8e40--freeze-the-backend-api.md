---
id: task-7c8e40
kind: task
title: Freeze the backend API before the shutdown
parent: pitch-7b3e94
status: ready
owner: Whimbrelson
assignees: [Whimbrelson]
reviewers: [redpollard]
review_waived: false
start_date: null
priority: medium
depends_on: []
tags: [hearth, backend, api]
prs: []
created_schema_version: 2
person_weeks: 1.0
---

# Freeze the backend API before the shutdown

## Problem

The surface between the emitter and a backend has moved three times this year and is about to move
a fourth time, when the scan gains its second lowering. Every move edited the model side, and the
model side has no way of telling which of the forty-odd names it imports are meant to be stable.

## Solution

Declare eleven of them supported and make the rest private. The supported list is the emitter
entry points, the lowering-selection hook and the two capability flags; everything else gains a
leading underscore in the same commit, so that the freeze is enforced by the name rather than by a
document somebody has to remember to read.

The document exists as well, because a name says what is stable and not why. It goes in
`hearth/backends/API.md`, one screen long, and it is written in the shape below — quoted here so
that the reviewer knows what is being asked for before the branch appears:

```
## <symbol>

- [ ] one line on what it is for
- since: <release>
- may change: never / with a deprecation cycle
```

Neither of those two lines is a section of this task or a point on its checklist. They are the
template being quoted, and the difference matters to anything that reads this file.

## Progress

- [ ] the eleven, agreed with the model side
- [ ] underscore everything else, one commit
- [ ] `API.md`, one screen
