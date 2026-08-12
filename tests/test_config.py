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
