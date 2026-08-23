# Seed corpus — this is a DEMO, not a plan

This directory is the demo corpus shipped with `openproj`. It exists so that
`openproj check`, `openproj schedule` and `openproj render` have something to chew on that
looks like real planning data. **It is not anybody's real plan, it is not anybody's
commitment, and nobody named in it has agreed to anything.**

## Shape

One project, five pitches, eleven tasks.

```
proj-000001  whole_roast
├── pitch-0a0001  Testing rank reproducibility   (cycle 37)
├── pitch-0b0001  Porting throughflow            (cycle 36)
├── pitch-0c0001  Porting the bed                (cycle 37)  depends on 0b0001
├── pitch-0d0001  Aroma transport convergence    (cycle 36)
└── pitch-0e0001  Burner radiation port          (cycle 37)
```

Beside them: three issues and three notes. Two of the notes are still ideas — one is
being turned over, one was thought about and dropped — and the third was promoted into
`pitch-0e0001`, which says so in its own shaping document. That is the whole shape of a
note's life, in three files.

"Today" for the demo is **2026-08-17**, the first working day of cycle 37. Everything
`done` sits in cycles 34–36; everything live sits in 36–37. At least one live chain runs
past the end of its cycle, on purpose — a scheduler that never shows an overrun is not
worth looking at.

## Everything here is invented

The domain, the people, the pull requests and the calendar are all made up. There is no
`KILN`, no `kiln4py`, no `hearth`, no Griddle programme and no Kettleworth Institute; the
handles are not anybody's handles; `kilnlab/kiln4py#2318` is not a pull request and should
not be dereferenced.

It is written the way a real plan is written, because that is the point of a demo corpus —
a body that reads as filler teaches a reader nothing about what a shaping document is for.
The engineering in it is meant to hang together: a legacy Fortran simulator of a
coffee-roasting plant is being re-implemented in Python subsystem by subsystem, nothing may
replace it until it reproduces it bit-for-bit, and the records argue about how to get there.
None of it happened.

## What is invented — do not read any of this as fact

| Field | Status |
|---|---|
| The `whole_roast` project itself | **Invented.** No such milestone has been declared. |
| Every `owner`, `assignees`, `reviewers`, `shaped_by` | **Invented.** The handles are invented too, and nobody agreed to any of this. |
| Every `person_weeks` | **Invented.** Chosen to make the timeline interesting, not measured or estimated by anyone. |
| Every `cycle` and `assigned_on` | **Invented.** The cycle *dates* in `config/cycles.yaml` are a plausible 2026 calendar, not anybody's. |
| Every `depends_on` edge | **Invented.** Deliberately sparse so the graph stays readable. |
| Every entry in `prs` | **Invented.** These PR numbers are plausible-looking and should not be dereferenced. |
| Every `id` | Fixed by hand so cross-references resolve. Not how ids are minted in practice. |
| `priority` | **Invented.** |
| The technical substance of every body | **Invented.** It is meant to be self-consistent, not true. |

## Configuration

`config/cycles.yaml`, `config/holidays.yaml` and `config/defaults.yaml` are merged into one
`Config` by `openproj.model.load_config`. The holidays are an ordinary European public-holiday
year plus a plant shutdown between Christmas and New Year; the cycle calendar is synthetic.

Every record is `created_schema_version: 2`, so the rules introduced at version 4 —
containment, where a `cycle` may live, and tasks adding up to more than the bet they sit
inside — report as warnings here rather than as blockers.

The corpus is expected to pass `uv run openproj check seed` with **zero blockers and exactly
one warning**: `pitch-0d0001` is bet at six weeks and its three tasks propose seven and a
half. That one is left in on purpose. It is the only check on this list whose output is a
conversation rather than a correction, and a demo where nothing ever exceeds its appetite
teaches that the number cannot be exceeded.

Only what is bet carries a `cycle:` — the five pitches. Their tasks take the cycle of the
pitch they belong to, and the project has none at all.

## If you fork this

Replace every row of the invented table above with something a human has agreed to, and
delete this file's warnings once they are no longer true. A demo fixture that quietly
graduates into a plan is how a tracker starts lying.
