from pathlib import Path

import openproj


def test_package_exposes_its_version():
    assert openproj.__version__ == "0.1.0"


def test_seed_corpus_has_seventeen_entity_files(seed_root: Path):
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
