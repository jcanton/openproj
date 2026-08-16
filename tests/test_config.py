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

    _, config = load_repo(tmp_path)

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
