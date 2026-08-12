from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seed_root() -> Path:
    """The committed seed corpus: 1 project, 5 pitches, 11 tasks."""
    return REPO_ROOT / "seed"
