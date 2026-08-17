---
id: pitch-3c9a41
kind: pitch
title: Turbulence 1D CPU single node
parent: null
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: 4.0
shaped_by: null        # REQUIRED from schema_version 2; not in source
assignees:
  - yiluchen1066
assigned_on: null      # was fabricated during migration; unknown
cycle: 28
priority: high
depends_on: []
tags:
  - greenline
  - turbulence
  - f2py
  - fortran-granule
  - icon4py
prs: []
---

# Turbulence 1D CPU single node

> **Provenance.** Task-table row 22 (`[Greenline] Open projects TABLE`, https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg).
> Row verbatim: *Nr 22 | Turbulence 1D CPU single node | Priority High | Status Done | Who "Y" | Depends on: (empty) | PR: (empty) | Shape doc: (empty) | Notes: "Implement ICON4Py granule, code is in [Turbulence icon-exclaim]"*, where `[Turbulence icon-exclaim]` = https://github.com/C2SM/icon-exclaim/tree/turbulence_1d.
> The row leaves the *Shape doc* column empty. The shaping document below was located in the GridTools HackMD space: **`[Greenline] Python bindings on Turbulence granule`**, cycle 28 (04/25), https://hackmd.io/@gridtools/S1airZWAJx. It is the pitch that makes the 1D turbulence granule callable from Python **on CPU**, which is exactly this row's scope — the cycle-34 successor pitch states plainly that "The 1D Turbulence granule currently only runs on CPU via `f2py`", and the GPU/multi-node continuation is table row 23.

## Shaping doc header (as written)

- Shaped by: Yilu Chen, Christos Kotsalos, Chia Rui
- Appetite (FTEs, weeks): *left blank in the note itself*
- Developers: Yilu, Christos

## Problem

We would like to call the 1D turbulence granule from icon-exclaim in icon4py with Python binding and verify the turbulence scheme with serialize data.

## Solution

1. **Generate Python bindings with `f2py`** — create wrappers for `turbdiff_setup_config` and `turbdiff_run`, since `f2py` does not directly support `pointer` or `target` attributes.
2. **Compile the wrapper with `f2py` to generate the `turbdiff_f2py` module** — this module can be imported directly into `icon4py`.
3. **Verify turbulence scheme in `icon4py` using serialized test data.**
4. **Create the interface for running the turbulence in `icon4py`.**

### Details

1. **Generate Python bindings with `f2py`**
   - Direct usage of `f2py` on the original granule routines (`turbdiff_setup_config` and `turbdiff_run`) is not feasible because they use `pointer` and `target` attributes, which are not directly supported by `f2py`. To work around this, the pointer arguments are exposed as regular NumPy arrays in the wrapper interface. These arrays can then be converted to GT4Py fields and internally associated with Fortran pointers within the wrapper.
   - Combine the wrapper for `turbdiff_setup_config` and `turbdiff_run` into one wrapper.
2. **Build the Python module using `f2py`**
   - With the wrapper Fortran code in place, use `f2py` to compile and generate a Python extension module (e.g. `turbdiff_f2py`), importable as `import turbdiff_f2py as td`.
   - The module provides Python-callable interfaces to the Fortran logic and handles NumPy↔Fortran array conversion under the hood.
3. **Verify functionality with serialized data in `icon4py`**
   - The serialized data does not need to be regenerated; it already exists from the Fortran verification.
   - Read the data under savepoint `icon-turbulence-verify-entry` as input, and compare the output against savepoint `icon-turbulence-verify-turbdiff-exit`.
4. **Expose the interface for use in `icon4py`** *(if time permits)*
   - Port the `turbdiff` interface.

The note links supporting material at https://drive.google.com/file/d/1_fR4SM-_vduKMKAwOygPCtMhWn6dPhIK/view?usp=sharing (Google Drive; not fetched during migration).

The *Appetite*, *Rabbit holes* and *No-gos* sections of the note are present but empty, and the *Progress* checklist was left as the unedited template — no per-task status was recorded there.

## Context around this row

- **Upstream (Fortran side).** `[Greenline] 1D turbulence Fortran granule`, cycle 24 (https://hackmd.io/@gridtools/BykLyZb9A), extracted the 1D turbulence of ICON into a standalone Fortran granule (entrypoint `src/atm_phy_schemes/turb_diffusion.f90`, ICON-NWP as base, CMake build, stateless interface aligned with the muphys granule). The cycle-25 overview records "Yilu will continue her work with Turbulence", so the granule work ran across cycles 24–25; the code the row points at (`C2SM/icon-exclaim`, branch `turbulence_1d`) comes from that effort. That pitch is not itself a task-table row.
- **Greenline hub, §C.3 Turbulence** (https://hackmd.io/@gridtools/HyygMYpGbx#3-Turbulence): "1d turbulence in Fortran has been 'isolated' by Yilu and it has generated python bindings using `F2Py`. The granule version has `openacc` directives, and the functionality needs to be tested. The Python bindings need to be adjusted in order to pass GPU pointers to the Fortran component. `F2Py` maybe (or not) support this." — the second half of that paragraph is row 23, not this row.
- **Downstream.** Row 23 "Turbulence 1D GPU multi node" declares `Depends on: 22` and is shaped by `[Greenline] Investigate compiling Python wrappers with F2Py and OpenACC Fortran Turbulence granule` (cycle 34, https://hackmd.io/@gridtools/ByqAXcMSbg). The icon4py-side integration (step 4 above) was picked up later by `[Greenline] Warm Bubble: Turbulence granule integration` (cycle 34, https://hackmd.io/@gridtools/HkHMquJUbl) and `[ICON4Py] plug in turbulence` (cycle 37, https://hackmd.io/@gridtools/H1y7pmbXze).
- Row 21 "Turbulence decisions" (Done, Who `A+Y`, "1D or 3D turbulence? 1D multi GPU") is topically the decision that precedes this row, but **the table declares no dependency between 21 and 22**, so none is recorded here.

## Migration notes

- **Who.** The row's raw `Who` string is `Y`. Resolved to **Yilu Chen → `yiluchen1066`**: she is a contributor to `C2SM/icon4py`, her GitHub profile reads *ychen, ETH Zurich (CSCS)*, she is the author of the head commit of `C2SM/icon-exclaim@turbulence_1d` (2025-12-18) — the exact branch this row links — and the cycle-28 overview names her as the developer of this pitch. Christos Kotsalos is listed as *support* in the overview (and as a co-developer in the pitch header), but the row's `Who` is `Y` alone, so he is not in `assignees`.
- **Appetite.** The note's own Appetite section is blank. The cycle-28 overview (https://hackmd.io/@gridtools/H1Up0S-Ake) lists this exact pitch with appetite **"full cycle"**. Cycle 28 ran from betting table **2025-04-08** to review meeting **2025-05-06** = **28 days = 4.0 elapsed weeks**; a full cycle is described elsewhere in the corpus as a "Full 4 week cycle". Hence `person_weeks: 4.0` (elapsed, not person-weeks).
- **assigned_on.** `2025-04-08`, the cycle-28 betting-table date typed in the overview — the meeting at which this pitch was bet and Yilu named as its developer. No other date is stated anywhere for this row.
- **PRs.** The row's PR column is empty and neither the shaping doc nor the cycle-28 overview cites a PR, so `prs` is empty. (The cycle-34 successor pitch cites `C2SM/icon-exclaim#437`, but that belongs to the later integration work, not this row.)
- **Dependencies.** The row's *Depends on* cell is empty — `depends_on: []`. Inbound references from rows 23 and 99 are recorded on those rows, per the depends_on-only invariant.
- **Parent.** No project entity: the row's group (rows 21–24, turbulence) is a blank-row group with **no heading in the source** — the grouping label was inferred by an earlier pass, so nothing in the table names a project.
- **Priority mapping used:** table `High+` → 0, `High` → 1, `Medium` → 2, `Low` → 3. Row 22 is `High` → `priority: high`.
