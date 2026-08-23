from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seed_root() -> Path:
    """The frozen golden corpus: 30 records — 2 products, 2 projects, 7 pitches,
    15 tasks, 2 issues and 2 notes. 26 of those are the plan; the four unplanned
    ones are why `Index.records` and `Index.plan` are different sizes here.

    Deliberately NOT `seed/`. Every golden in the scheduler and index suites was
    derived from these exact files and hand-checked against the spec's algorithm,
    so this corpus has to stop moving. `seed/` is the demo and is free to be
    rewritten; this is the fixture, and changing it means re-deriving the goldens
    by hand.

    It grew once, on 2026-08-23, and how it grew is the precedent: a new planned
    record introduces NEW people and hangs under a NEW ancestor, so that the
    scheduler property in `test_property_adding_an_item_that_shares_no_worker_
    and_no_ancestor_never_moves_that_items_span` keeps the existing spans still —
    and every span it DOES add is derived by hand before it is written down. See
    the comment over GOLDEN_SPANS in `test_schedule.py`. Regenerating those dates
    from a run turns the only non-tautological assertion in the suite into one
    that passes under every possible bug.
    """
    return REPO_ROOT / "tests" / "fixtures" / "corpus"


@pytest.fixture
def demo_root() -> Path:
    """The shipped demo corpus, which must validate clean."""
    return REPO_ROOT / "seed"
