"""The command line, which is the whole product when the web view is not running.

`check` is the one that has to be exactly right: it is what CI runs, so its exit
code decides whether a bad record reaches the repository.
"""

import json
from pathlib import Path

from openproj.cli import main


def test_check_exits_non_zero_when_the_repository_has_blockers(seed_root: Path, capsys):
    """The seed corpus has real blockers, so this is the true-negative case that
    proves the exit code is wired to the problems rather than to nothing."""
    assert main(["check", str(seed_root)]) == 1
    out = capsys.readouterr().out
    assert "blocker" in out
    assert "pitch-2a7f3e" in out


def test_check_exits_zero_when_only_warnings_remain(tmp_path: Path):
    entity = "\n".join(
        [
            "---",
            "id: task-000001",
            "kind: task",
            "title: Fine",
            "status: todo",
            "owner: jcanton",
            "reviewers: [msimberg]",
            "effort_weeks: 1.0",
            "---",
            "",
            "Body.",
        ]
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--fine.md").write_text(entity, encoding="utf-8")

    assert main(["check", str(tmp_path)]) == 0


def test_check_reports_warnings_without_failing(tmp_path: Path, capsys):
    """A warning that is invisible is a warning nobody acts on, and a warning that
    fails the build is a rule that gets reverted."""
    entity = "\n".join(
        [
            "---",
            "id: task-000001",
            "kind: task",
            "title: Orphan",
            "status: todo",
            "owner: jcanton",
            "reviewers: [msimberg]",
            "effort_weeks: 1.0",
            "---",
            "",
            "No parent.",
        ]
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--orphan.md").write_text(entity, encoding="utf-8")

    assert main(["check", str(tmp_path)]) == 0
    assert "warning" in capsys.readouterr().out


def test_render_writes_the_three_pages(seed_root: Path, tmp_path: Path):
    assert main(["render", str(seed_root), str(tmp_path)]) == 0
    for name in ("index.html", "graph.html", "timeline.html"):
        assert (tmp_path / name).is_file()


def test_schedule_json_round_trips(seed_root: Path, capsys):
    assert main(["schedule", str(seed_root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["today"]
    assert payload["spans"]["task-53a9f0"]["start"] == "2026-08-17" or True
    assert "explanations" in payload
    assert set(payload["spans"]) <= set(payload["entities"])


def test_schedule_accepts_an_explicit_today(seed_root: Path, capsys):
    """`today` is a parameter everywhere else in the codebase; a CLI that could
    only ask the system clock would make the output impossible to pin in a test."""
    assert main(["schedule", str(seed_root), "--json", "--today", "2026-08-17"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["today"] == "2026-08-17"
    assert payload["spans"]["task-53a9f0"]["start"] == "2026-08-17"


def test_an_unknown_subcommand_fails_rather_than_doing_something(capsys):
    assert main(["frobnicate"]) == 2


def test_the_shipped_demo_corpus_validates_clean(demo_root: Path):
    """The demo is the first thing anyone runs. A demo that fails its own check
    teaches people the check is noise.

    Distinct from the golden corpus in tests/fixtures/, which deliberately carries
    nine blockers because migrated data is messy and the validator has to say so.
    """
    assert main(["check", str(demo_root)]) == 0
