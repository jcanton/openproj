"""Build a synthetic plan repository of a given size, for load measurement.

Not a fixture and not a test: `tests/load/` is a measuring instrument. It writes
into a temporary directory the caller names and never touches `seed/` or any
plan of anybody's.

The shape is the shape of the real corpus — one project, pitches under it, tasks
under those, plus notes and issues, plus the four config files copied verbatim
from `seed/config/` so the scheduler has cycles, holidays and a roster to work
with. Bodies are padded to roughly the length of a real shaping document,
because `build_index` walks `sections()` and `checklist()` over every one of
them and a corpus of one-line bodies measures the wrong thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from openproj.store import build_plan_repository  # noqa: E402

PEOPLE = ["jcanton", "nfarabullini", "msimberg", "iomaganaris", "halungge", "edopao"]

BODY = """## Problem

{title} is not doing the one thing it was built for, and the reason is buried in
a configuration file that three other jobs also read. The 7-day validation test
asserts bitwise-identical output between one and four ranks, but only on CPU
backends and only with contraction disabled.

## Appetite

{weeks} weeks, carried over from the previous cycle.

## Solution

Reproduce or formally retire the artefact, running the driver on main and on the
branch with two and four ranks. Promote the repro flags out of the validation
level so the asserting flag set runs on merges.

## Rabbit holes

- **Per-rank build caches.** The cache key ignores the compiler flags, so a
  shared cache root silently reuses binaries built the other way.
- **The halo exchange.** Not in scope; it has its own pitch.

## Progress

- [x] reproduce on two ranks
- [x] find the flag that hides it
- [ ] promote the flag set
- [ ] drop the print-instead-of-fail escape

## For later

- the four-rank GPU case
- the torus convergence study
"""


def files(pitches: int, tasks_each: int, notes: int, issues: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("cycles.yaml", "defaults.yaml", "holidays.yaml", "people.yaml"):
        out[f"config/{name}"] = (ROOT / "seed" / "config" / name).read_text()
    out["cycles/0037.md"] = (ROOT / "seed" / "cycles" / "0037.md").read_text()

    out["projects/proj-000001--warm-bubble.md"] = _record(
        "proj-000001", "project", "Warm bubble", None, "in_progress", 0, 3.0
    )
    n = 0
    for p in range(pitches):
        pid = f"pitch-{p:06x}"
        out[f"pitches/{pid}--pitch-{p}.md"] = _record(
            pid, "pitch", f"Pitch number {p}", "proj-000001", "todo", p, 4.0
        )
        for t in range(tasks_each):
            tid = f"task-{n:06x}"
            n += 1
            out[f"tasks/{tid}--task-{n}.md"] = _record(
                tid, "task", f"Task number {n}", pid, "in_progress", n, 1.5
            )
    for i in range(notes):
        nid = f"note-{i:06x}"
        out[f"notes/{nid}.md"] = _unplanned(nid, "note", f"Note number {i}", i)
    for i in range(issues):
        iid = f"issue-{i:06x}"
        out[f"issues/{iid}.md"] = _unplanned(iid, "issue", f"Issue number {i}", i)
    return out


def _record(rid, kind, title, parent, status, seed, weeks):
    owner = PEOPLE[seed % len(PEOPLE)]
    other = PEOPLE[(seed + 1) % len(PEOPLE)]
    reviewer = PEOPLE[(seed + 2) % len(PEOPLE)]
    lines = [
        "---",
        f"id: {rid}",
        f"kind: {kind}",
        f"title: {title}",
    ]
    if parent:
        lines.append(f"parent: {parent}")
    lines += [
        f"status: {status}",
        f"owner: {owner}",
        f"assignees: [{owner}, {other}]",
        f"reviewers: [{reviewer}]",
        "review_waived: false",
        "assigned_on: 2026-08-17",
        "priority: high",
        "depends_on: []",
        "tags: [icon4py, load]",
        'prs: ["C2SM/icon4py#1223"]',
        "created_schema_version: 2",
        f"person_weeks: {weeks}",
        "shaped_by: jcanton",
        "cycle: 37",
        "---",
        "",
        BODY.format(title=title, weeks=weeks),
    ]
    return "\n".join(lines)


def _unplanned(rid, kind, title, seed):
    who = PEOPLE[seed % len(PEOPLE)]
    key = "raised_by" if kind == "issue" else "noted_by"
    dated = "raised_on" if kind == "issue" else "noted_on"
    return "\n".join(
        [
            "---",
            f"id: {rid}",
            f"kind: {kind}",
            f"title: {title}",
            f"{key}: {who}",
            f"{dated}: 2026-08-17",
            "tags: [load]",
            "created_schema_version: 2",
            "---",
            "",
            BODY.format(title=title, weeks=1),
        ]
    )


def build(path: Path, pitches=40, tasks_each=10, notes=60, issues=60) -> str:
    return build_plan_repository(path, files(pitches, tasks_each, notes, issues), "load corpus")


if __name__ == "__main__":
    import shutil

    where = Path(sys.argv[1])
    if where.exists():
        shutil.rmtree(where)
    counts = [int(x) for x in sys.argv[2:6]] if len(sys.argv) > 5 else [40, 10, 60, 60]
    sha = build(where, *counts)
    print(sha, sum(1 for _ in where.rglob("*")))
