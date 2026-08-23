from pathlib import Path

import pytest

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


def test_every_test_file_is_in_exactly_one_ci_shard():
    """CI runs this suite as parallel jobs, each `pytest` over the file list in
    `.github/shards/<name>` — and a hand-written list fails open. A test file in
    no shard is a test CI silently stops running the day it is written, with
    every job green; a file in two shards burns a runner proving the same thing
    twice. Nobody sees either without a census, which is what this is — the
    shape of `test_every_html_get_route_is_in_the_census`, pointed at CI.

    Held against the tree (`tests/test_*.py` off disk) rather than against a
    second hand-written list, so it cannot itself go stale. It skips while
    `.github/shards/` does not exist: before the sharded workflow lands, one
    job runs the whole suite and there is nothing to hold — and if the
    directory is ever deleted while the workflow still reads it, the jobs fail
    loudly on the missing lists, so the skip cannot hide that either. What the
    skip could never catch is this file itself falling out of every shard; the
    cut is "everything else" by construction, so the census rides with it.
    """
    root = Path(__file__).parent.parent
    shards = root / ".github" / "shards"
    if not shards.is_dir():
        pytest.skip("no .github/shards yet: CI is one job and runs the whole suite")

    seen: dict[str, list[str]] = {}
    for shard in sorted(path for path in shards.iterdir() if path.is_file()):
        for line in shard.read_text(encoding="utf-8").splitlines():
            for token in line.split():
                if token.startswith("#"):
                    break  # the rest of the line is commentary, not a path
                named = root / token
                assert named.is_file(), (
                    f"{shard.name} names {token}, which does not exist; entries are "
                    f"paths from the repository root, e.g. tests/test_web.py"
                )
                assert (
                    named.parent == root / "tests"
                    and named.name.startswith("test_")
                    and named.name.endswith(".py")
                ), f"{shard.name} names {token}, which is not a tests/test_*.py file"
                seen.setdefault(named.name, []).append(shard.name)

    every = {path.name for path in (root / "tests").glob("test_*.py")}
    missing = sorted(every - seen.keys())
    assert not missing, f"in no shard, so no CI job ever runs them: {missing}"
    doubled = {name: where for name, where in seen.items() if len(where) > 1}
    assert not doubled, f"in more than one shard, so CI runs them twice: {doubled}"
