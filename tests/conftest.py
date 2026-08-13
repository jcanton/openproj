from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seed_root() -> Path:
    """The frozen golden corpus: 1 project, 5 pitches, 11 tasks.

    Deliberately NOT `seed/`. Every golden in the scheduler and index suites was
    derived from these exact files and hand-checked against the spec's algorithm,
    so this corpus has to stop moving. `seed/` is the demo and is free to be
    rewritten; this is the fixture, and changing it means re-deriving the goldens
    by hand.
    """
    return REPO_ROOT / "tests" / "fixtures" / "corpus"


@pytest.fixture
def demo_root() -> Path:
    """The shipped demo corpus, which must validate clean."""
    return REPO_ROOT / "seed"
