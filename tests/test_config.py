from datetime import date
from pathlib import Path

from openproj.model import Config, Problem, load_config


def test_problem_carries_the_rule_version_that_introduced_the_rule():
    problem = Problem(
        severity="warning",
        record_id="pitch-1b3f9a",
        field="assignees",
        message="a ready record needs somebody on it",
        rule_version=2,
    )
    assert problem.severity == "warning"
    assert problem.rule_version == 2


def test_config_defaults_stand_alone():
    config = Config()
    assert config.schema_version == 1
    assert config.nominal_availability == 1.0
    assert config.holidays == []
    assert config.cycles == {}


def test_load_config_merges_the_three_seed_files(seed_root: Path):
    config = load_config(seed_root)
    # schema_version 2 is what NEW records are created at; the corpus is still 1.
    assert config.schema_version == 2
    assert config.nominal_availability == 1.0
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


def test_a_cycle_stores_its_two_meetings_and_derives_the_rest():
    """The betting table and the review meeting are dates somebody put in a
    calendar; a length is a prediction of one. Stored the other way round, four
    weeks could not say that the review had moved for a conference, that the team
    left a month between two cycles, or that a cycle over the year-end closure
    holds a fortnight of building."""
    from openproj.model import Config, Cycle

    resolved = (
        Config()
        .with_plans(
            [
                Cycle(cycle=37, starts_on=date(2026, 8, 17), reviews_on=date(2026, 9, 14)),
                Cycle(cycle=38, starts_on=date(2026, 9, 28), reviews_on=date(2026, 10, 26)),
            ]
        )
        .plans
    )

    # Build ends the working day BEFORE the review: you review what was finished
    # before you walked in.
    assert resolved[37].builds_until == date(2026, 9, 11)
    assert resolved[37].build_weeks == 4.0
    # And the cool-down ends where the next cycle's betting table is, which is
    # stored once — on the next cycle.
    assert resolved[37].ends_on == date(2026, 9, 27)
    assert not resolved[37].assumed_end


def test_a_cycle_with_nothing_after_it_assumes_its_cool_down_and_says_so():
    from openproj.model import Config, Cycle

    only = (
        Config()
        .with_plans([Cycle(cycle=37, starts_on=date(2026, 8, 17), reviews_on=date(2026, 9, 14))])
        .plans[37]
    )

    assert only.ends_on == date(2026, 9, 27), "a fortnight, for want of a next cycle"
    assert only.assumed_end
    assert not only.assumed_review


def test_a_cycle_that_names_no_review_meeting_assumes_one_and_says_so():
    """Parse permissively: a record written before the field existed still loads,
    and the page marks the date it invented rather than printing it as a choice
    somebody made."""
    from openproj.model import Config, Cycle

    guessed = Config().with_plans([Cycle(cycle=37, starts_on=date(2026, 8, 17))]).plans[37]

    assert guessed.assumed_review
    assert guessed.build_weeks == 4.0


def test_the_build_is_measured_in_working_weeks_so_a_holiday_shortens_it():
    """Capacity is `availability × build weeks`, so this is the betting table's
    own number. A length in weeks could not know about the year-end closure."""
    from openproj.model import Config, Cycle

    over_christmas = [Cycle(cycle=40, starts_on=date(2026, 12, 14), reviews_on=date(2027, 1, 11))]
    plain = Config().with_plans(over_christmas).plans[40]
    with_closure = (
        Config(
            holidays=[
                date(2026, 12, 24),
                date(2026, 12, 25),
                date(2026, 12, 28),
                date(2026, 12, 29),
                date(2026, 12, 30),
                date(2026, 12, 31),
            ]
        )
        .with_plans(over_christmas)
        .plans[40]
    )

    assert plain.build_weeks == 4.0
    assert with_closure.build_weeks == 2.8, "six working days of closure"


def test_capacity_is_availability_times_the_build_weeks():
    """Not the whole window: cool-down is not build time, so nobody is bet into it."""
    from openproj.model import Config, Cycle

    cycle = (
        Config()
        .with_plans(
            [
                Cycle(
                    cycle=37,
                    starts_on=date(2026, 8, 17),
                    reviews_on=date(2026, 9, 14),
                    availability={"ann": 0.5},
                )
            ]
        )
        .plans[37]
    )

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


def test_a_cycle_dated_at_the_end_of_the_calendar_resolves_rather_than_raising():
    """`build_weeks: 500000` typed into the Cycles form: the record committed, and
    then `ends_on` raised OverflowError while `Config.with_plans` was assembling
    the cycle windows. That is before any rule has looked at the record, so
    `openproj check`, `openproj render` and nine of the ten routes went down
    together, on a branch whose protection means the commit cannot be
    force-pushed away.

    The length is gone, and the same hazard arrives through the date instead: a
    review meeting in the year 9999. The route bounds it now; this is the file
    somebody edited in git, which never passed the route at all — and the
    arithmetic here counts whole weeks, so it is bounded as well as unraising.
    """
    from openproj.model import Config, Cycle

    resolved = (
        Config()
        .with_plans(
            [
                Cycle(cycle=38, starts_on=date(2026, 9, 1), reviews_on=date.max),
            ]
        )
        .plans[38]
    )

    assert resolved.ends_on == date.max
    assert resolved.builds_until < date.max
    assert resolved.build_weeks > 0


def test_a_review_before_its_own_betting_table_costs_that_cycle_and_no_others():
    """Nonsense in one record, and the page it is on says zero rather than a
    negative length or a window that runs backwards."""
    from openproj.model import Config, Cycle

    resolved = (
        Config()
        .with_plans(
            [
                Cycle(cycle=38, starts_on=date(2026, 9, 1), reviews_on=date(2026, 8, 1)),
                Cycle(cycle=39, starts_on=date(2026, 10, 1), reviews_on=date(2026, 10, 29)),
            ]
        )
        .plans
    )

    assert resolved[38].builds_until == date(2026, 9, 1)
    assert resolved[38].build_weeks == 0.2, "the betting table itself, and no more"
    assert resolved[38].ends_on >= resolved[38].builds_until
    assert resolved[39].build_weeks == 4.0, "the cycle beside it is untouched"


def test_the_cool_down_is_the_gap_to_the_next_betting_table_however_long_it_is():
    """The team leaves a month between two cycles for the conference and release
    window. A length in weeks could not say so; two dates need no exception."""
    from openproj.model import Config, Cycle

    resolved = (
        Config()
        .with_plans(
            [
                Cycle(cycle=35, starts_on=date(2026, 3, 30), reviews_on=date(2026, 4, 27)),
                Cycle(cycle=36, starts_on=date(2026, 6, 22), reviews_on=date(2026, 7, 20)),
            ]
        )
        .plans
    )

    assert resolved[35].ends_on == date(2026, 6, 21), "eight weeks of it, and no rule broken"
    assert resolved[35].build_weeks == 4.0, "the build is unchanged by the gap after it"


def test_a_cycle_window_runs_from_the_betting_table_to_the_next_one():
    """`config.cycles` is what every carryover overlap and every timeline band is
    measured against, so the resolved dates have to land in it."""
    from openproj.model import Config, Cycle

    config = Config().with_plans(
        [
            Cycle(cycle=37, starts_on=date(2026, 8, 17), reviews_on=date(2026, 9, 14)),
            Cycle(cycle=38, starts_on=date(2026, 9, 28), reviews_on=date(2026, 10, 26)),
        ]
    )

    assert config.cycles[37] == (date(2026, 8, 17), date(2026, 9, 27))
    assert config.cycles[38][0] == date(2026, 9, 28), "no day belongs to two cycles"
