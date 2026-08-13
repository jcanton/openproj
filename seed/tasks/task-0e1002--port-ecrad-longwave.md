---
id: task-0e1002
kind: task
title: Port ecRad longwave
parent: pitch-0e0001
status: todo
owner: yiluchen1066
assignees: [yiluchen1066]
reviewers: [kotsaloscv, halungge]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 2
depends_on: [task-0e1001]
tags: [radiation, longwave, no-scatter-solver, planck-source, gt4py]
prs: []
created_schema_version: 2
effort_weeks: 2.5
---

# Port ecRad longwave

## Problem

Longwave is what actually cools the atmosphere, so without it the radiation granule produces a
one-sided heating rate and the `Radheating` tendency cannot be compared against
`radheating-exit` at all. ICON's AES configuration uses the cheapest solver in the library:
`1scl`, no scattering, one angle with diffusivity D = 1.66. The physics is simpler than
shortwave; the work is the Planck source machinery and the two-sweep transport.

## Appetite

2.5 weeks. It rides on the k-distribution reader, the chunked `(Cell, Gpt, K)` domain handling
and the host-side g-point reduction that `task-0e1001` lands, which is why it is chained behind
it rather than run in parallel — duplicating that infrastructure and merging it later costs more
than the serialisation does.

## Solution

1. **LW gas optics.** Same `kdist.py` interpolation as shortwave, minus Rayleigh, plus the
   major/minor absorber contributions that the LW k-distribution actually uses.
2. **Planck sources.** `lay_source`, `lev_source` at both interfaces, and `sfc_source` from the
   surface temperature and emissivity, all via the `totplnk` table interpolated in temperature
   and expanded to g-points. Band-to-g-point expansion stays host-side (`np.take`), as decided
   in M1.
3. **No-scattering solver.** `tau_loc = D * tau`, transmittance `exp(-tau_loc)`, and the source
   function with the small-tau expansion — the Padé/Taylor branch around `tau -> 0` must be
   ported as a `where` on a computed field, not as a Python-level `if`, or the definedness
   analysis rejects it. Then the downward sweep from TOA and the upward sweep from the surface,
   written as the scan pair proven in M1 (boolean-flag carry, rtol 1e-8 against numpy).
4. **Assembly.** Sum g-points host-side into broadband up/down fluxes, hand them to
   `Radheating`, and compare against `radheating-entry`/`radheating-exit` — the tendency is the
   delta across the pair, and `tend_ta_rad`, `rsw`, `rlw`, `q_rad` are now serialized (they
   became allocatable only once the output namelist was added on `serialize_rrtmgp`).

## Rabbit holes

- **Sign and level conventions.** RRTMGP indexes levels top-down and ICON's interface flips
  some of them; `mo_rte_rrtmgp_interface.f90` on icon-nwp master is the authority, not the
  library's own test driver. Budget a day for getting `lev_source_inc`/`lev_source_dec`
  the right way round — the symptom is a heating rate correct in magnitude and wrong in sign
  near the tropopause.
- **Emissivity.** APE gives a uniform surface; the land-albedo/emissivity paths APE skips get
  stencil-level tests with synthetic inputs instead.
- Do not compare a bare LW flux against the Fortran and call it validated while the archive is
  the dry one — check the savepoint is not all-zero first (`inspect-savepoints stats`).

## No-gos

- No LW scattering (`2str` / `nstr` paths). AES uses `1scl` and nothing in the warm-bubble
  configuration selects otherwise.
- No McICA sampling, no reduced grid, no restructuring of the shortwave code landed in
  `task-0e1001` beyond what sharing genuinely requires.
