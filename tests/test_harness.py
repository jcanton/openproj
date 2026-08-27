import ast
import json
from pathlib import Path

import openproj


def test_the_package_and_the_project_agree_about_the_version():
    """Two files hold this number and they have already disagreed with each other
    and with the newest tag: `pyproject.toml` and `__init__.py` both said 0.1.0
    while `v0.2.0` was the newest tag and 189 commits had landed since it.

    A literal here was the previous version of this test, which pins the number
    to whatever it was on the day it was written and goes stale on the commit
    that bumps it — so it asks the thing that can actually be wrong: whether the
    two files say the same thing. Which of them a wheel believes depends on how
    it was built.
    """
    import tomllib

    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())

    assert openproj.__version__ == pyproject["project"]["version"]


def test_seed_corpus_has_twenty_six_plan_record_files(seed_root: Path):
    """A size sentinel, so growing the corpus is a decision somebody makes.

    24 + 2 = 26, which is `len(index.plan)`. `products/` is counted on its own
    line rather than folded into the glob below: those three directories were the
    whole plan when this was written, and a rung added later has to be named here
    or the sentinel goes on passing while covering less of the corpus each time.
    """
    files = [
        path
        for directory in ("projects", "pitches", "tasks")
        for path in (seed_root / directory).glob("*.md")
    ]
    assert len(files) == 24
    assert len(list((seed_root / "products").glob("*.md"))) == 2


def test_every_test_repository_names_the_branch_the_store_reads():
    """`Store` reads `refs/heads/main` and nothing else, and libgit2 with no user
    config creates `master` — so a fixture that omits `initial_head` passes on a
    laptop configured for `main` and dies on a runner that is not, with
    `KeyError: 'refs/heads/main'` thrown from inside pygit2 with no mention of a
    branch name anywhere in the message.

    That is what the first CI run found: nine tests in `test_headers` and one in
    `test_identity`, machine-dependent since the day they were written, green on
    every machine that had ever run them. Scanned as source rather than asserted
    per fixture, because the next one will be written the same way.
    """
    offenders = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "init_repository(" in line and "initial_head" not in line:
                offenders.append(f"{path.name}:{number}")

    assert not offenders, f"init_repository without initial_head='main': {offenders}"


# How much of the suite the durations table has to know before the split stops
# being a split. Not 1.0: a test written today is not in a table measured
# yesterday, and it must not turn the merge gate red for that — `pytest-split`
# gives an unmeasured test the average and still runs it, in exactly one group,
# so what a stale table costs is BALANCE and never coverage. 0.8 is the point at
# which "a few new tests" has become "nobody has re-measured in months".
_DURATIONS_FLOOR = 0.8


def _test_functions(path: Path) -> set[str]:
    """Every `def test_…` in one file, by name.

    `ast` and not a regex, for `test_the_facade_…`'s reason: a name inside a
    string or a comment is not a test, and this is the kind of census that is
    worse than nothing when it is quietly wrong.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }


def test_the_durations_table_still_knows_what_the_suite_is_made_of():
    """CI cuts the suite into eight groups by recorded duration, and this is the
    alarm on the recording going stale.

    **It is deliberately not the census that stood here.** That one held
    `tests/test_*.py` against the hand-written lists in `.github/shards/`,
    because a file in no shard was a file CI silently stopped running with every
    job green — a gate that fails OPEN, which is the one failure a gate must
    never have. Splitting works off the collected list instead, so that cannot
    happen any more: every test is in exactly one group whether or not anybody
    has measured it. The lists are gone and so is the way they failed.

    What replaces it is the failure the new scheme actually has, which is quieter
    and only costs time. A table that has stopped describing the suite still
    produces eight groups; they are just eight badly unbalanced ones, and the
    gate slows down with nothing anywhere saying why. So this asks two things of
    `.test_durations`: that every test FILE is in it at all — a whole new file
    unmeasured is the biggest single distortion available — and that it knows
    enough of the individual tests to be worth reading.

    Regenerate with one serial run, which is how the file was made:

        uv run pytest --store-durations
    """
    root = Path(__file__).parent.parent
    table = root / ".test_durations"
    assert table.is_file(), (
        ".test_durations is missing, so every test is given the same weight and "
        "the eight CI groups are cut by count rather than by time. Regenerate it "
        "with `uv run pytest --store-durations`."
    )
    recorded = json.loads(table.read_text(encoding="utf-8"))
    assert recorded, ".test_durations is empty"

    # `tests/test_web.py::test_one[param]` -> ("tests/test_web.py", "test_one").
    known: dict[str, set[str]] = {}
    for node_id in recorded:
        path, _, rest = node_id.partition("::")
        known.setdefault(path, set()).add(rest.partition("[")[0])

    files = sorted(path for path in (root / "tests").glob("test_*.py"))
    unmeasured = [path.name for path in files if f"tests/{path.name}" not in known]
    assert not unmeasured, (
        f"never measured, so every test in them is cut in at the average and the "
        f"groups are unbalanced by however long they really take: {unmeasured}. "
        f"Regenerate with `uv run pytest --store-durations`."
    )

    written = {f"tests/{path.name}::{name}" for path in files for name in _test_functions(path)}
    seen = {f"{path}::{name}" for path, names in known.items() for name in names}
    covered = len(written & seen) / len(written)
    assert covered >= _DURATIONS_FLOOR, (
        f".test_durations knows {covered:.0%} of the suite's test functions, under "
        f"the {_DURATIONS_FLOOR:.0%} floor. The split still runs every test — an "
        f"unmeasured one is given the average — but the groups are no longer "
        f"balanced by anything real. Regenerate with `uv run pytest "
        f"--store-durations`."
    )
