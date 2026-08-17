from datetime import date
from pathlib import Path

from openproj.model import Config, Problem, load_config


def test_problem_carries_the_rule_version_that_introduced_the_rule():
    problem = Problem(
        severity="warning",
        entity_id="pitch-1b3f9a",
        field="shaped_by",
        message="a pitch must record who shaped it",
        rule_version=2,
    )
    assert problem.severity == "warning"
    assert problem.rule_version == 2


def test_config_defaults_stand_alone():
    config = Config()
    assert config.schema_version == 1
    assert config.nominal_availability == 1.0
    assert config.default_task_effort == 0.5
    assert config.holidays == []
    assert config.cycles == {}


def test_load_config_merges_the_three_seed_files(seed_root: Path):
    config = load_config(seed_root)
    # schema_version 2 is what NEW entities are created at; the corpus is still 1.
    assert config.schema_version == 2
    assert config.nominal_availability == 1.0
    assert config.default_task_effort == 0.5
    assert config.cycles[36] == (date(2026, 6, 22), date(2026, 8, 14))
    assert date(2026, 8, 1) in config.holidays


def test_every_cycle_used_by_the_seed_corpus_has_boundaries(seed_root: Path):
    config = load_config(seed_root)
    for cycle in (28, 34, 35, 36):
        assert cycle in config.cycles, f"cycle {cycle} is used by the corpus but has no dates"
        start, end = config.cycles[cycle]
        assert start < end


def test_load_config_falls_back_to_defaults_with_no_config_directory(tmp_path: Path):
    assert load_config(tmp_path) == Config()


# --- cycle records ----------------------------------------------------------


def test_a_cycle_record_supersedes_the_dates_in_config(tmp_path: Path):
    """Both exist on purpose: the YAML is how dates were kept before there were
    records, so a repository part-way through has some of each."""
    from openproj.model import load_repo

    for directory in ("projects", "pitches", "tasks", "cycles", "config"):
        (tmp_path / directory).mkdir()
    (tmp_path / "config/cycles.yaml").write_text(
        "cycles:\n  36: [2026-06-22, 2026-08-14]\n  37: [2026-08-17, 2026-10-09]\n"
    )
    (tmp_path / "cycles/0037.md").write_text(
        "---\ncycle: 37\nstarts_on: 2026-08-17\nbuild_weeks: 4\ncooldown_weeks: 2\n"
        "availability:\n  ann: 0.5\n---\n## Goal\n\nShip it.\n"
    )

    _, config, _ = load_repo(tmp_path)

    assert config.cycles[36] == (date(2026, 6, 22), date(2026, 8, 14))  # untouched
    assert config.cycles[37] == (date(2026, 8, 17), date(2026, 9, 27))  # from the record
    assert config.plans[37].availability == {"ann": 0.5}
    assert "Ship it." in config.plans[37].body
    assert 36 not in config.plans


def test_a_cycle_derives_its_ends_rather_than_storing_them():
    """An end stored beside a length is a second copy of one fact, and the two
    disagree the first time somebody moves a date."""
    from openproj.model import Cycle

    cycle = Cycle(cycle=37, starts_on=date(2026, 8, 17), build_weeks=4, cooldown_weeks=2)

    assert cycle.builds_until == date(2026, 9, 13)   # four calendar weeks, inclusive
    assert cycle.ends_on == date(2026, 9, 27)        # six
    assert "builds_until" not in Cycle.model_fields
    assert "ends_on" not in Cycle.model_fields


def test_capacity_is_availability_times_the_build_weeks():
    """Not the whole window: cool-down is not build time, so nobody is bet into it."""
    from openproj.model import Cycle

    cycle = Cycle(cycle=37, starts_on=date(2026, 8, 17), build_weeks=4,
                  availability={"ann": 0.5})

    assert cycle.capacity("ann") == 2.0
    assert cycle.capacity("bo") == 4.0, "unlisted means nobody said otherwise"


# --------------------------------------------------------------------------- #
# The end of the calendar
# --------------------------------------------------------------------------- #


def test_a_date_stops_at_the_end_of_the_calendar_rather_than_raising():
    """`days_after` is the one place a date moves, and this is why it exists.

    `date` covers years 1 to 9999 and `timedelta` raises the moment arithmetic
    leaves that range — which, out of a property read while the config is being
    assembled, is every page 500 at once. Saturating is the answer because
    `date.max` is not a date anybody plans against.
    """
    from openproj.model import days_after

    assert days_after(date(2026, 8, 17), 1) == date(2026, 8, 18)
    assert days_after(date(2026, 8, 17), -1) == date(2026, 8, 16)
    assert days_after(date.max, 1) == date.max
    assert days_after(date.min, -1) == date.min
    assert days_after(date(2026, 8, 17), 5_000_000) == date.max
    assert days_after(date(2026, 8, 17), -5_000_000) == date.min


def test_a_length_that_is_not_a_number_saturates_instead_of_raising():
    """`round()` and `math.ceil()` both raise on infinity, and a length in weeks
    is a float a hand-edited file may write as `.inf`. NaN arrives from
    `inf - inf` one addition later and rounds no better, so it lands on the
    forward edge rather than on an exception."""
    from openproj.model import CALENDAR_DAYS, days_after, within_the_calendar

    assert within_the_calendar(3.0) == 3.0
    # The constant first in the `min`, because NaN loses every comparison: the
    # other order returns the NaN and the caller rounds it.
    assert within_the_calendar(float("inf")) == CALENDAR_DAYS
    assert within_the_calendar(float("nan")) == CALENDAR_DAYS
    assert days_after(date(2026, 8, 17), float("inf")) == date.max
    assert days_after(date(2026, 8, 17), float("nan")) == date.max
    assert days_after(date(2026, 8, 17), float("-inf")) == date.min


def test_a_cycle_longer_than_the_calendar_ends_at_the_end_of_it():
    """`build_weeks: 500000` typed into the Cycles form: the record committed, and
    then `ends_on` raised OverflowError while `Config.with_plans` was assembling
    the cycle windows. That is before any rule has looked at the record, so
    `openproj check`, `openproj render` and nine of the ten routes went down
    together, on a branch whose protection means the commit cannot be
    force-pushed away.

    The route refuses that number now. This is the file somebody edited in git,
    which never passed the route at all.
    """
    from openproj.model import Cycle

    absurd = Cycle(cycle=38, starts_on=date(2026, 9, 1), build_weeks=500_000.0)
    infinite = Cycle(
        cycle=39, starts_on=date(2026, 9, 1),
        build_weeks=float("inf"), cooldown_weeks=float("-inf"),
    )

    assert absurd.builds_until == date.max
    assert absurd.ends_on == date.max
    assert infinite.builds_until == date.max
    assert infinite.ends_on == date.max, "inf + -inf is NaN, which rounds no better"


def test_the_clamp_does_not_move_a_length_the_calendar_can_hold():
    """A guard that changes an ordinary answer is a bug with a docstring.

    Half weeks are the ones at risk: the length is `round(weeks * 7)` days and
    the last day is one before it, so 4.5 weeks is 32 days and ends on the 31st
    — not `round(4.5 * 7 - 1)`, which is 30.
    """
    from openproj.model import Cycle

    start = date(2026, 8, 17)
    for weeks, cooldown, builds, ends in (
        (4.5, 2.0, date(2026, 9, 17), date(2026, 10, 1)),
        (0.5, 0.5, date(2026, 8, 20), date(2026, 8, 23)),
        (1.2, 0.3, date(2026, 8, 24), date(2026, 8, 26)),
        (3.7, 1.1, date(2026, 9, 11), date(2026, 9, 19)),
    ):
        cycle = Cycle(cycle=1, starts_on=start, build_weeks=weeks, cooldown_weeks=cooldown)
        assert (cycle.builds_until, cycle.ends_on) == (builds, ends), weeks
