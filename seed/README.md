# Seed corpus — this is a DEMO, not a plan

This directory is the demo corpus shipped with `openproj`. It exists so that
`openproj check`, `openproj schedule` and `openproj render` have something to chew on that
looks like real planning data. **It is not the icon4py team's real plan, it is not
anybody's commitment, and no assignment in it has been agreed to by the person named.**

If you arrived here looking for what the team is actually doing, close this and go to
the icon4py repository and its issues.

## Shape

One project, five pitches, eleven tasks.

```
proj-000001  warm_bubble
├── pitch-0a0001  Testing MPI reproducibility     (cycle 37)
├── pitch-0b0001  Porting turbulence              (cycle 36)
├── pitch-0c0001  Porting land                    (cycle 37)  depends on 0b0001
├── pitch-0d0001  Tracer advection convergence    (cycle 36)
└── pitch-0e0001  Radiation port                  (cycle 37)
```

"Today" for the demo is **2026-08-17**, the first working day of cycle 37. Everything
`done` sits in cycles 34–36; everything live sits in 36–37. At least one live chain runs
past the end of its cycle, on purpose — a scheduler that never shows an overrun is not
worth looking at.

## What is grounded in real icon4py work

The technical substance of the bodies. These describe work that genuinely happened or is
genuinely planned, and the specifics in them are real:

- **MPI reproducibility.** `test_standalone_driver_compare_single_multi_rank`, the
  `-ffp-contract=off` narrowing, `LEVELS=validation` versus the hand-fitted
  `atol=1e-13, rtol=1e-14` fallback, and the GPU residual traced to batched
  `cupy.linalg.solve` in the RBF coefficient computation.
- **TMX turbulence.** The atmosphere-first scoping, the prescribed grid-mean surface
  fluxes, the surface sub-project, and the `isrfc_type=1` flux bypass that blocks
  end-to-end ocean validation.
- **JSBACH / land.** The `soil_snow_energy`-first slice, the two-tier oracle, the tmx
  seam that the land model plugs into, and the `Torus_Triangles_20x4_5000m` grid choice.
- **Tracer advection convergence.** The floored `n_time_steps` reference-time bug, the C⁰
  minimum-image Gaussian kink, and the switch to `icon-grid-generator>=0.8.0` with
  `periodic_layout="rectangular"`.
- **Radiation.** The rte_rrtmgp scoping, the cartesian `(Cell, Gpt, K)` approach, and
  host-side g-point reduction.
- **Data hygiene.** The `exclaim_ape_aesPhys_v06` archive collision and the vacuous
  microphysics reference data are both real, and both real reasons this project exists.

The GitHub usernames are all real `C2SM/icon4py` contributors.

## What is invented — do not read any of this as fact

| Field | Status |
|---|---|
| The `warm_bubble` project itself | **Invented.** No such milestone has been declared. |
| Every `owner`, `assignees`, `reviewers`, `shaped_by` | **Invented.** Names are real people; the assignments are not. Nobody agreed to any of this. |
| Every `person_weeks` | **Invented.** Chosen to make the timeline interesting, not measured or estimated by anyone. |
| Every `cycle` and `assigned_on` | **Invented.** The cycle *dates* in `config/cycles.yaml` are a plausible 2026 calendar, not the team's. |
| Every `depends_on` edge | **Invented.** Deliberately sparse so the graph stays readable. |
| Every entry in `prs` | **Invented.** These PR numbers are plausible-looking and should not be dereferenced. |
| Every `id` | Fixed by hand so cross-references resolve. Not how ids are minted in practice. |
| `priority` | **Invented.** |
| The parts of any body that read as decisions or status | Where a body goes beyond what the source notes say, it invents plausibly rather than contradicting them — but it is still invention. |

## Configuration

`config/cycles.yaml`, `config/holidays.yaml` and `config/defaults.yaml` are merged into one
`Config` by `openproj.model.load_config`. The holidays are genuine Zurich cantonal holidays
plus the ETH year-end closure; the cycle calendar is synthetic.

Every entity is `created_schema_version: 2`, so the rules introduced at version 4 —
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
