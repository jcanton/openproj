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


def test_seed_corpus_has_seventeen_record_files(seed_root: Path):
    files = [
        path
        for directory in ("projects", "pitches", "tasks")
        for path in (seed_root / directory).glob("*.md")
    ]
    assert len(files) == 17


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
