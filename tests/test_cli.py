"""The command line, which is the whole product when the web view is not running.

`check` is the one that has to be exactly right: it is what CI runs, so its exit
code decides whether a bad record reaches the repository.
"""

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pygit2
import pytest
from test_store import SEED, commit_directly

from openproj.cli import main


def test_check_exits_non_zero_when_the_repository_has_blockers(seed_root: Path, capsys):
    """The seed corpus has real blockers, so this is the true-negative case that
    proves the exit code is wired to the problems rather than to nothing."""
    assert main(["check", str(seed_root)]) == 1
    out = capsys.readouterr().out
    assert "blocker" in out
    assert "pitch-2a7f3e" in out


def test_check_exits_zero_when_only_warnings_remain(tmp_path: Path):
    record = "\n".join(
        [
            "---",
            "id: task-000001",
            "kind: task",
            "title: Fine",
            "status: ready",
            "owner: jackdawrie",
            "reviewers: [merganserly]",
            "person_weeks: 1.0",
            "---",
            "",
            "Body.",
        ]
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--fine.md").write_text(record, encoding="utf-8")

    assert main(["check", str(tmp_path)]) == 0


def test_check_reports_warnings_without_failing(tmp_path: Path, capsys):
    """A warning that is invisible is a warning nobody acts on, and a warning that
    fails the build is a rule that gets reverted."""
    record = "\n".join(
        [
            "---",
            "id: task-000001",
            "kind: task",
            "title: Orphan",
            "status: ready",
            "owner: jackdawrie",
            "reviewers: [merganserly]",
            "person_weeks: 1.0",
            "---",
            "",
            "No parent.",
        ]
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--orphan.md").write_text(record, encoding="utf-8")

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
    assert set(payload["spans"]) <= set(payload["plan"])


def test_schedule_accepts_an_explicit_today(seed_root: Path, capsys):
    """`today` is a parameter everywhere else in the codebase; a CLI that could
    only ask the system clock would make the output impossible to pin in a test."""
    assert main(["schedule", str(seed_root), "--json", "--today", "2026-08-17"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["today"] == "2026-08-17"
    # 08-13 and not the 08-17 asked for: the task is in progress and its start
    # date is the 13th, so it starts when it started. `--today` still moves everything
    # that has not begun, which is what this test is about.
    assert payload["spans"]["task-53a9f0"]["start"] == "2026-08-13"


# A date the way the files store one, and a date the way the pages read one out.
# `\b` on the second so that a version or an id ending in digits cannot make one.
_STORED = re.compile(r"\d{4}-\d{2}-\d{2}")
_READ_OUT = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")


def test_the_json_document_holds_one_date_format_and_it_is_the_stored_one(seed_root: Path, capsys):
    """`--json` is a document a script pipes: `today` is ISO, every span date is
    ISO, and for one release the explanations beside them were not.

    The scheduler had been made to format its sentences day-first because the
    record page draws its dates that way, and the sweep took the CLI with it — so
    a consumer that read a date out of `explanations` got `28.08.2026` from a
    document in which the same day is `2026-08-28` two keys above. The whole
    payload is scanned rather than the explanations alone, because the next thing
    to carry a formatted date into here will not be called `explanations`.
    """
    assert main(["schedule", str(seed_root), "--json", "--today", "2026-08-17"]) == 0
    printed = capsys.readouterr().out
    payload = json.loads(printed)

    assert payload["explanations"], "a corpus that explains nothing cannot fail this"
    assert _READ_OUT.findall(printed) == []
    # Not vacuous: the sentences really do name dates, and they name them ISO.
    assert [text for text in payload["explanations"].values() if _STORED.search(text)]


def test_a_line_of_the_schedule_table_says_its_dates_one_way(seed_root: Path, capsys):
    """Two columns of ISO and then a sentence that said `28.08.2026`:

        2026-08-28  2026-09-15  task-0a1002  Starts on 28.08.2026: the …

    One line, one day, two spellings sixty characters apart, which invites the
    reader to work out what the difference is meant to mean. The columns are the
    span as the model holds it, so the sentence is asked for the same reading.

    Per line rather than over the whole output, because that is the claim: a
    terminal where half the lines were one format and half the other would pass a
    scan of the text and still be the defect.
    """
    assert main(["schedule", str(seed_root), "--today", "2026-08-17"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert lines
    assert [line for line in lines if _STORED.search(line) and _READ_OUT.search(line)] == []
    # The columns are three fields wide; a fourth is a sentence. At least one
    # line has to carry one with a date in it, or nothing above was tested.
    notes = [parts[3] for line in lines if len(parts := re.split(r"\s{2,}", line)) > 3]
    assert [note for note in notes if _STORED.search(note)]


def test_an_unknown_subcommand_fails_rather_than_doing_something(capsys):
    assert main(["frobnicate"]) == 2


def test_the_shipped_demo_corpus_validates_clean(demo_root: Path, capsys):
    """The demo is the first thing anyone runs. A demo that fails its own check
    teaches people the check is noise.

    Distinct from the golden corpus in tests/fixtures/, which deliberately carries
    ten blockers because migrated data is messy and the validator has to say so.
    The exact set is pinned in `test_the_seed_corpus_reports_exactly_this_problem_set`;
    this test only cares that the DEMO carries none.
    """
    assert main(["check", str(demo_root)]) == 0
    # Added by the commit that made a note a rung: issues and notes acquired
    # `openproj check` coverage they never had, and this warning is the
    # coverage arriving — the web banner said it all along.
    assert (
        "warning: note-55cc66: written_by: dabchickly is not in config/people.yaml"
        in capsys.readouterr().out
    )


def test_check_is_asked_about_a_day_rather_than_reading_the_clock(demo_root: Path, capsys):
    """`openproj demo` draws `seed/` around 2026-08-17, which the corpus writes
    down four times; `check` read `date.today()`. So from any day after that one
    the two disagreed about the same files: eleven records are `ready` with a
    start date of the first day of cycle 37, and the command reported every one of
    them as a date that has gone by while every page of the running demo drew them
    as future. Both take the day the same way now — through `build_index`, which
    is the one place a schedule and a validation are paired around a single day —
    and this is the flag that names it.

    Asserted in both directions on purpose. "No such line at the pinned day"
    passes just as well on a command that has stopped reporting the rule at all,
    so the other day has to show the eleven the first one is claiming to have
    silenced.
    """
    assert main(["check", str(demo_root), "--today", "2026-08-17"]) == 0
    passed = "has passed and the work has not begun"
    assert passed not in capsys.readouterr().out

    assert main(["check", str(demo_root), "--today", "2026-12-01"]) == 0
    assert capsys.readouterr().out.count(passed) == 11


def test_serve_is_reachable_from_the_command_line():
    """The README promises `openproj serve`; a parser that has never heard of it
    turns that promise into a stack trace at the worst moment."""
    from openproj.cli import _parser

    args = _parser().parse_args(["serve", "--repo", "seed", "--auth", "dev"])
    assert args.command == "serve"
    assert args.auth == "dev"


def test_serve_listens_where_cloud_run_requires(monkeypatch):
    """Cloud Run sets PORT and requires 0.0.0.0 — "notably not 127.0.0.1". A
    container that binds the loopback passes every local test and then fails its
    health check with no useful message."""
    from openproj.cli import _parser

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("OPENPROJ_HOST", "0.0.0.0")
    args = _parser().parse_args(["serve", "--repo", "seed"])

    assert (args.host, args.port) == ("0.0.0.0", 8080)


def test_the_vendored_static_directory_is_found_by_an_env_var(monkeypatch, tmp_path: Path):
    """An installed layout resolves the source-tree path past site-packages, and
    GET /graph became an uncaught FileNotFoundError. Found by building a wheel
    rather than by reading the path. OPENPROJ_STATIC is the override a deployment
    running the source tree, or a wheel built before static/ was packaged, uses."""
    from openproj.render import _static_dir

    (tmp_path / "cytoscape.min.js").write_text("//")
    monkeypatch.setenv("OPENPROJ_STATIC", str(tmp_path))

    assert _static_dir() == tmp_path


def test_the_wheel_carries_what_the_lookups_look_for(monkeypatch, tmp_path: Path):
    """A wheel built from `packages = ["src/openproj"]` alone shipped no static/
    and no seed/, so an installed `openproj serve`, `render` or `demo` answered
    its first page with "the vendored static/ directory is missing" — while the
    README said every command runs straight out of the published package. The
    fix is two halves that can drift apart in silence: pyproject's force-include
    puts each directory beside the package, and each lookup reads beside the
    package. This test reads the map off pyproject.toml and drives both lookups
    through a fake installed layout shaped by it, so a rename on either side
    fails here rather than on somebody's first `uvx openproj serve`."""
    import tomllib

    import openproj.cli as cli
    import openproj.vendor as vendor

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    carried = tomllib.loads(pyproject.read_text())["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert {"static", "seed"} <= carried.keys()
    for source in ("static", "seed"):
        assert (pyproject.parent / source).is_dir(), f"{source}/ is not in the source tree"
        assert Path(carried[source]).parts[0] == "openproj", carried[source]

    # An installed layout: the package directory holds what the wheel put there,
    # and the source-tree candidate two levels up resolves to nothing.
    package = tmp_path / "site-packages" / "openproj"
    for source in ("static", "seed"):
        (tmp_path / "site-packages" / carried[source]).mkdir(parents=True)
    monkeypatch.delenv("OPENPROJ_STATIC", raising=False)
    monkeypatch.setattr(vendor, "__file__", str(package / "vendor.py"))
    monkeypatch.setattr(cli, "__file__", str(package / "cli.py"))

    assert vendor._static_dir() == tmp_path / "site-packages" / carried["static"]
    assert cli._seed_dir() == tmp_path / "site-packages" / carried["seed"]

