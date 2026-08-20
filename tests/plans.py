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

# The id prefixes, off the ladder rather than `kind[:4]` — which spells `pitch`
# `pitc` and `product` `prod`, and only one of those is what the parser expects.
PREFIX = {"product": "prod", "project": "proj", "pitch": "pitch", "task": "task"}


def _share(total: int, groups: int, which: int) -> int:
    """`total` projects dealt out over `groups` products, remainder first."""
    if groups <= 1:
        return total
    return total // groups + (1 if which < total % groups else 0)


def build(root: pathlib.Path, projects: int, pitches: int, tasks: int, seed: int = 7,
          products: int = 2) -> int:
    """Write a plan and return how many records it holds.

    Seeded, so the same arguments give the same plan: a layout test whose corpus
    moved between runs would report a layout that did not.
    """
    rng = random.Random(seed)
    if root.exists():
        shutil.rmtree(root)
    DIRS = {"product": "products", "project": "projects",
            "pitch": "pitches", "task": "tasks"}
    for d in (*DIRS.values(), "config"):
        (root / d).mkdir(parents=True)
    people = [f"dev{n}" for n in range(8)]
    (root / "config/people.yaml").write_text(f"known_people: [{', '.join(people)}]\n")
    (root / "config/defaults.yaml").write_text(
        "schema_version: 2\nnominal_availability: 1.0\ndefault_task_effort: 0.5\n")

    made, ids = [], {"product": [], "project": [], "pitch": [], "task": []}
    def write(kind, num, parent, extra=""):
        eid = f"{PREFIX[kind]}-{num:06d}"
        ids[kind].append(eid)
        made.append(eid)
        front = [f"id: {eid}", f"kind: {kind}", f"title: {kind} {num}", "status: ready"]
        # A product carries none of the work fields and is filed under nothing:
        # `unread_fields` in `model.py` is what says so, and a generator that
        # wrote them anyway would make every plan it builds report warnings.
        if kind != "product":
            front += [f"owner: {rng.choice(people)}", f"reviewers: [{rng.choice(people)}]"]
        if parent:
            front.append(f"parent: {parent}")
        if kind not in ("project", "product"):
            front.append(f"person_weeks: {rng.choice([0.5, 1, 2, 3])}")
        if extra:
            front.append(extra)
        (root / DIRS[kind] / f"{eid}.md").write_text(
            "---\n" + "\n".join(front) + "\n---\n\nSynthetic.\n")
        return eid

    n = 0
    for group in range(max(1, products)):
        n += 1
        # Products only if asked for. The rung above project groups the codebases
        # one plan spans, and the layout it produces is a fourth level of nesting
        # — which is the thing worth measuring, since every defect this file was
        # written for got worse the more containment there was.
        top = write("product", n, None) if products else None
        for _ in range(_share(projects, products, group)):
            n += 1
            p = write("project", n, top)
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
    # Across groups, and ACYCLIC by construction: a record only ever waits on one
    # minted before it. Random pairs made rings — measured, a generated plan of
    # 518 records held a genuine blocked-by cycle between two pitches, which
    # `validate_all` reports as a blocker and which the write path now refuses
    # outright. A corpus that cannot exist is a corpus that measures the wrong
    # thing: two of the three backward arrows on this plan were the drawing
    # correctly failing to lay out a ring, not the layout getting anything wrong.
    #
    # Mutual dependencies BETWEEN GROUPS are still generated, and deliberately —
    # two projects each holding work that waits on the other is legal, common,
    # and the one shape no arrangement of two boxes on a line can express.
    pool = ids["pitch"]
    for _ in range(max(4, len(pool) // 4)):
        first, second = sorted(rng.sample(range(len(pool)), 2))
        deps.setdefault(pool[second], []).append(pool[first])

    for eid, on in deps.items():
        kind = "pitch" if eid.startswith("pitch") else "task"
        path = root / DIRS[kind] / f"{eid}.md"
        text = path.read_text().replace("---\n\nSynthetic",
            f"depends_on: [{', '.join(sorted(set(on)))}]\n---\n\nSynthetic", 1)
        path.write_text(text)
    return len(made)

if __name__ == "__main__":
    where = pathlib.Path(sys.argv[1])
    count = build(where, int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]),
                  products=int(sys.argv[5]) if len(sys.argv) > 5 else 2)
    print(f"{count} records in {where}")
