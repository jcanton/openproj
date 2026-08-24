---
id: pitch-3c9a41
kind: pitch
title: Throughflow 1D CPU single node
parent: null
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: 4.0
assignees:
  - yellowhammer7
assigned_on: null      # was fabricated during migration; unknown
cycle: 28
priority: high
depends_on: []
tags:
  - griddle
  - throughflow
  - f2py
  - fortran-module
  - kiln4py
prs: []
---

# Throughflow 1D CPU single node

This is the first half of getting AIRFLOW out of Fortran: make the 1D throughflow module callable
from Python on CPU, and check it against recorded tap points before anything is rewritten in
hearth. The module itself already exists — the 1D throughflow was isolated out of KILN in an
earlier cycle, given a stateless interface modelled on the drying module that went first, and
built with CMake. What it does not have is a way in from Python. Everything below is about the
binding layer and the verification, and nothing about porting the physics; that comes later and is
a much larger piece of work. The GPU and multi-node continuation is shaped separately, because the
pointer handling `f2py` needs on the device is a different problem from the one solved here.

## Shaping doc header

- Shaped by: Yellowhammer, Kittiwake, Oxpecker
- Appetite (FTEs, weeks): *left blank when this was shaped*
- Developers: Yellowhammer, Kittiwake

## Problem

We would like to call the 1D throughflow module from KILN in kiln4py with Python bindings, and
verify the throughflow scheme against tap data.

## Solution

1. **Generate Python bindings with `f2py`** — create wrappers for `bedstep_setup_config` and
   `bedstep_run`, since `f2py` does not directly support `pointer` or `target` attributes.
2. **Compile the wrapper with `f2py` to generate the `bedstep_f2py` module** — this module can be
   imported directly into `kiln4py`.
3. **Verify the throughflow scheme in `kiln4py` using recorded test data.**
4. **Create the interface for running throughflow in `kiln4py`.**

### Details

1. **Generate Python bindings with `f2py`**
   - Direct usage of `f2py` on the original module routines (`bedstep_setup_config` and
     `bedstep_run`) is not feasible because they use `pointer` and `target` attributes, which are
     not directly supported by `f2py`. To work around this, the pointer arguments are exposed as
     regular NumPy arrays in the wrapper interface. These arrays can then be converted to hearth
     fields and internally associated with Fortran pointers within the wrapper.
   - Combine the wrapper for `bedstep_setup_config` and `bedstep_run` into one wrapper.
2. **Build the Python module using `f2py`**
   - With the wrapper Fortran code in place, use `f2py` to compile and generate a Python extension
     module (e.g. `bedstep_f2py`), importable as `import bedstep_f2py as bs`.
   - The module provides Python-callable interfaces to the Fortran logic and handles NumPy↔Fortran
     array conversion under the hood.
3. **Verify functionality with recorded data in `kiln4py`**
   - The tap data does not need to be regenerated; it already exists from the Fortran verification.
   - Read the data under tap point `airflow-verify-entry` as input, and compare the output against
     tap point `airflow-verify-bedstep-exit`.
4. **Expose the interface for use in `kiln4py`** *(if time permits)*
   - Port the `bedstep` interface.

The appetite, rabbit-hole and no-go sections of this pitch were never filled in, and its progress
list was left as the unedited template. What actually happened is written on the four tasks
underneath it instead, which is the better place for it.

## Context

- **Upstream (Fortran side).** The 1D throughflow of KILN was extracted into a standalone Fortran
  module two cycles earlier: entrypoint `bed_transfer.f90`, stateless interface aligned with the
  drying module that went first, CMake build, `openacc` directives left in place but never
  exercised. That work ran across two cycles and produced the branch this pitch builds on. It was
  never a board row of its own, which is why nothing here links to a record for it.
- **What the hub says about it.** "1D throughflow in Fortran has been isolated and has generated
  Python bindings using `f2py`. The module version has `openacc` directives, and the functionality
  needs to be tested. The Python bindings need to be adjusted in order to pass GPU pointers to the
  Fortran component. `f2py` maybe (or not) supports this." The second half of that paragraph is the
  GPU row, not this one.
- **Downstream.** "Throughflow 1D GPU multi node" declares a dependency on this pitch and is shaped
  around compiling Python wrappers against `openacc` Fortran. The kiln4py-side integration — step 4
  above — was picked up later, first as part of the whole_roast module integration and then as its
  own cycle-37 pitch.
- **Adjacent.** "Throughflow decisions" (1D or 3D? 1D multi-GPU) is the decision that precedes this
  pitch, but nothing declares a dependency between them, so none is recorded here.

## Open questions

**Does `f2py` survive contact with the GPU?** Everything here is CPU. The module carries `openacc`
directives and the GPU row assumes the same wrapper can be taught to pass device pointers through.
Nobody has established that it can. If it cannot, the binding layer is rewritten with `ctypes` or
`cffi` against an explicit C interface, and roughly none of the wrapper code below survives. That
is the largest single piece of risk in the throughflow line of work, and this pitch carries it
rather than resolving it.

**Where does the wrapper live?** Right now it sits beside the Fortran, on the module branch, which
means kiln4py builds it from a source tree it does not own. The alternative is vendoring the
wrapper into kiln4py and pinning the Fortran by commit. Neither is obviously right: the first makes
the wrapper drift with the physics, which is what you want; the second makes the build
reproducible, which is what CI wants.

**What happens when `bed_transfer.f90` changes?** The module was cut from KILN at a point in time.
KILN keeps moving. Nothing currently notices when the two diverge — no test compares them, and the
tap data is regenerated by hand. A stale module that still passes its own tap points is the failure
mode nobody would see.

**How long was this, really?** The appetite was never written down, and the pitch was bet as a full
cycle because that was the unit available, not because anybody had estimated it. The four tasks
underneath are what the cycle actually contained; whether they add up to a cycle is a question
worth asking of the next one of these before it is bet, rather than after.
