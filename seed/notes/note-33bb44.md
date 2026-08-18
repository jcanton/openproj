---
id: note-33bb44
title: A dashboard for validation runs
status: dropped
written_by: ninaburg
written_on: 2026-07-29
tags: [tooling, validation]
became: []
---
The idea was a page showing every validation run, which fields it compared and
whether it passed — something to open after a nightly instead of reading logs.

Talked about it at the cycle 36 review. The runs already write JUnit XML that CI
renders, and the thing people actually want is to know *why* a field diverged,
which no dashboard would have told them. Nobody wanted to own it. Written down
here rather than deleted, because it comes up about twice a year.
