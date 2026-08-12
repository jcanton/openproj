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
