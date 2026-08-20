"""A plan of any size, built rather than stored.

The real corpus is 31 records and the views have to hold up on a plan that is
not. This makes one: `projects x pitches x tasks` of containment, chains of
dependencies inside each group, and edges across groups — which is the shape
that matters, because a flat plan of five hundred records exercises none of the
things that go wrong.

A generator and not a second repository of markdown, which was the alternative
jcanton offered. Sixty deterministic lines beside the code that reads them beat a
few thousand generated files somewhere else: any size is available on demand, the
seed makes two runs identical, and there is no second thing to keep in step when
the record format changes.

    uv run python tests/plans.py /tmp/big-plan 14 6 5     # 518 records

Used by `test_graph_layout.py` at a size the suite can afford. For the sizes it
cannot, run it by hand — the numbers measured on 2026-08-20 at 1900x820 are in
the `LAYOUT` comment in `render.py`.
"""
import pathlib
import random
import shutil
import sys


def build(root: pathlib.Path, projects: int, pitches: int, tasks: int, seed: int = 7) -> int:
    """Write a plan and return how many records it holds.

    Seeded, so the same arguments give the same plan: a layout test whose corpus
    moved between runs would report a layout that did not.
    """
    rng = random.Random(seed)
    if root.exists():
        shutil.rmtree(root)
    DIRS = {"project": "projects", "pitch": "pitches", "task": "tasks"}
    for d in (*DIRS.values(), "config"):
        (root / d).mkdir(parents=True)
    people = [f"dev{n}" for n in range(8)]
    (root / "config/people.yaml").write_text(f"known_people: [{', '.join(people)}]\n")
    (root / "config/defaults.yaml").write_text(
        "schema_version: 2\nnominal_availability: 1.0\ndefault_task_effort: 0.5\n")

    made, ids = [], {"project": [], "pitch": [], "task": []}
    def write(kind, num, parent, extra=""):
        eid = f"{kind[:4]}-{num:06d}"
        ids[kind].append(eid)
        made.append(eid)
        front = [f"id: {eid}", f"kind: {kind}", f"title: {kind} {num}",
                 "status: ready", f"owner: {rng.choice(people)}",
                 f"reviewers: [{rng.choice(people)}]"]
        if parent:
            front.append(f"parent: {parent}")
        if kind != "project":
            front.append(f"person_weeks: {rng.choice([0.5, 1, 2, 3])}")
        if extra:
            front.append(extra)
        (root / DIRS[kind] / f"{eid}.md").write_text(
            "---\n" + "\n".join(front) + "\n---\n\nSynthetic.\n")
        return eid

    n = 0
    for _ in range(projects):
        n += 1
        p = write("project", n, None)
        for _ in range(pitches):
            n += 1
            q = write("pitch", n, p)
            for _ in range(tasks):
                n += 1
                write("task", n, q)

    # Dependencies: chains inside a group, and edges across groups — the shape
    # the audit says root `layered` cannot rank without help.
    deps = {}
    for kind in ("pitch", "task"):
        pool = ids[kind]
        for i in range(0, len(pool) - 1, 3):
            deps.setdefault(pool[i + 1], []).append(pool[i])
    for _ in range(max(4, len(ids["pitch"]) // 4)):
        a, b = rng.sample(ids["pitch"], 2)
        deps.setdefault(a, []).append(b)

    DIRS = {"project": "projects", "pitch": "pitches", "task": "tasks"}
    for eid, on in deps.items():
        kind = "pitch" if eid.startswith("pitc") else "task"
        path = root / DIRS[kind] / f"{eid}.md"
        text = path.read_text().replace("---\n\nSynthetic",
            f"depends_on: [{', '.join(sorted(set(on)))}]\n---\n\nSynthetic", 1)
        path.write_text(text)
    return len(made)

if __name__ == "__main__":
    where = pathlib.Path(sys.argv[1])
    count = build(where, int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    print(f"{count} records in {where}")
