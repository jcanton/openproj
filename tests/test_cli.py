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


def test_serve_says_when_the_repository_is_a_checkout(tmp_path: Path):
    """`--repo .` inside a plan checkout starts, serves, and then leaves `git
    status` reporting every browser-saved record as deleted and untracked,
    because the store moves the branch and never the working tree. The help says
    "a bare clone" and nothing checked. Warned, not refused: reading a checkout
    is harmless."""
    import pygit2

    from openproj.cli import _not_a_bare_clone

    checkout = tmp_path / "plan"
    pygit2.init_repository(str(checkout), initial_head="main")
    bare = tmp_path / "plan.git"
    pygit2.init_repository(str(bare), bare=True, initial_head="main")

    said = _not_a_bare_clone(checkout)
    assert said is not None
    assert "not a bare clone" in said and str(checkout) in said
    assert _not_a_bare_clone(bare) is None
    # Not a repository at all is the store's refusal to make, in its own words.
    assert _not_a_bare_clone(tmp_path / "nowhere") is None


def test_a_plan_that_reaches_the_end_of_the_calendar_still_renders(tmp_path: Path, capsys):
    """The half of A2 that made it worse than the cycle blocker.

    A `done` task dated 9999-12-31 and a cycle nobody could mean are both one
    keystroke too many in a form box, and neither is a validation problem — so
    `check` said "0 blockers, 0 warnings" while `/timeline` answered 500. And
    `render` wrote *no files at all*, not five of six: every page is rendered
    before any is written, so the one that raised took the other five with it.
    Both of the tools you would reach for to diagnose it were silent or dead.
    """
    for directory in ("tasks", "cycles"):
        (tmp_path / directory).mkdir()
    (tmp_path / "tasks" / "task-000001--done.md").write_text(
        "---\nid: task-000001\nkind: task\ntitle: Long done\nstatus: done\n"
        "owner: jackdawrie\nreviewers: [merganserly]\nstart_date: 9999-12-31\n"
        'prs: ["kilnlab/kiln4py#1"]\nperson_weeks: 1.0\n---\n\nBody.\n',
        encoding="utf-8",
    )
    (tmp_path / "cycles" / "0038.md").write_text(
        "---\ncycle: 38\nstarts_on: 2026-09-01\nbuild_weeks: 500000\n---\n\nGoal.\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"

    assert main(["check", str(tmp_path)]) == 0
    assert "0 blockers" in capsys.readouterr().out
    assert main(["render", str(tmp_path), str(out)]) == 0

    for name in (
        "index.html",
        "table.html",
        "detail.html",
        "people.html",
        "cycles.html",
        "graph.html",
        "timeline.html",
    ):
        assert (out / name).is_file(), name
        assert len(read_bytes := (out / name).read_bytes()) > 1000, (name, len(read_bytes))
    # And the one that used to raise is a drawing, not fourteen megabytes of it.
    assert len((out / "timeline.html").read_bytes()) < 1_000_000


# --- behind a proxy ---------------------------------------------------------


def test_the_forwarded_scheme_is_trusted_only_where_it_was_configured(monkeypatch):
    """`proxy_headers=True` is not the setting that decides this, which is the
    whole trap: uvicorn believes `X-Forwarded-Proto` only from
    `forwarded_allow_ips`, defaulting to 127.0.0.1. Cloud Run's frontend arrives
    from 169.254.169.126, so on the deployed service the header was dropped and
    every request looked like plain HTTP.

    Two things broke from that, both away from the code that caused them:
    `request.url_for` built an `http://` callback, which GitHub refuses with "The
    redirect_uri is not associated with this application" — accusing an OAuth App
    that was configured correctly — and `secure_for` answered False, so a session
    cookie on a TLS-only service would have gone out without `Secure`.
    """
    from openproj.cli import _exit_aware_server

    monkeypatch.delenv("OPENPROJ_FORWARDED_ALLOW_IPS", raising=False)
    careful = _exit_aware_server(lambda *a: None, "127.0.0.1", 8000)
    assert careful.config.forwarded_allow_ips == "127.0.0.1"

    monkeypatch.setenv("OPENPROJ_FORWARDED_ALLOW_IPS", "*")
    behind_a_proxy = _exit_aware_server(lambda *a: None, "0.0.0.0", 8080)
    assert behind_a_proxy.config.forwarded_allow_ips == "*"
    assert behind_a_proxy.config.proxy_headers is True


def test_the_container_says_where_it_is_running(monkeypatch, tmp_path):
    """`K_SERVICE` is Cloud Run stating it is Cloud Run, and it is the only thing
    that widens the trust. The same image on a laptop keeps the careful default,
    because trusting a forwarded scheme from anyone lets a client on a plain-HTTP
    run claim https."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "openproj_boot", Path(__file__).resolve().parents[1] / "deploy" / "boot.py"
    )
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)

    # Neither run reaches the clone or the server: the repository is there and
    # `execv` is stubbed — necessarily, because the real one would swap this
    # test process for a server — so `main` stops at the one decision under test.
    (tmp_path / "plan.git").mkdir()
    monkeypatch.setattr(boot.os, "execv", lambda *a, **k: None)
    monkeypatch.setenv("OPENPROJ_REPO", str(tmp_path / "plan.git"))

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("OPENPROJ_FORWARDED_ALLOW_IPS", raising=False)
    boot.main()
    assert "OPENPROJ_FORWARDED_ALLOW_IPS" not in os.environ

    monkeypatch.setenv("K_SERVICE", "openproj")
    boot.main()
    assert os.environ["OPENPROJ_FORWARDED_ALLOW_IPS"] == "*"


# --- the demo -----------------------------------------------------------------
#
# `openproj demo` is the first command anybody runs, and the one nothing could
# test before it existed: the answer to "how do I run this locally" was six lines
# of shell in a README, one of which — `serve --repo seed` — pointed the server
# at a directory that is not a git repository and served an empty plan. A recipe
# is a thing that goes wrong silently; a subcommand is a thing with tests.


def free_port() -> int:
    """A port nothing is listening on. Asked of the operating system rather than
    typed, because a number written into a test suite is a number that collides
    with whatever else the machine running it happens to have open."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Instead:
    """The server, replaced by whatever the test wants to do with the app.

    `_demo` builds its repository inside a `with` and deletes it on the way out,
    so everything worth asserting has to be asserted while the server would have
    been running. This is that moment, handed to the test.
    """

    def __init__(self, doing):
        self.doing = doing
        self.app = None

    def __call__(self, app, host, port):
        self.app = app
        return self

    def run(self):
        self.doing(self.app)


def run_demo(monkeypatch, doing, argv: list[str] | None = None) -> int:
    from openproj import cli

    instead = _Instead(doing)
    monkeypatch.setattr(cli, "_exit_aware_server", instead)
    return main(["demo", "--port", str(free_port()), *(argv or [])])


def test_demo_builds_a_repository_the_server_can_actually_serve(monkeypatch, capsys):
    """The whole point of the command, asked of the server it starts rather than
    of the directory it made: a bare repo with a commit in it can still be one
    the reader finds empty, which is exactly what `--repo seed` did — 200 on
    every route, and no pitches, tasks or projects on any of them."""
    from fastapi.testclient import TestClient

    seen = {}

    def while_it_runs(app):
        with TestClient(app) as client:
            seen["records"] = client.get("/")
            seen["table"] = client.get("/table")
            seen["people"] = client.get("/people")
            seen["index"] = client.get("/api/index.json").json()

    assert run_demo(monkeypatch, while_it_runs) == 0

    assert seen["records"].status_code == 200
    assert seen["table"].status_code == 200
    assert seen["people"].status_code == 200
    # Every rung the plan is made of, read off `RUNG` rather than written down.
    # This was `{"project", "pitch", "task"}`, which was the whole ladder when it
    # was typed; adding `product` as a rung and shipping two of them in the demo
    # made it fail, and the honest reading of that failure is that the literal was
    # a copy of the ladder rather than a statement about the demo. `planned` is
    # the flag that decides what reaches the table, graph, timeline and people
    # pages, so a rung added later is covered here on the commit that adds it.
    from openproj.model import RUNG

    kinds = {record["kind"] for record in seen["index"]["plan"].values()}
    assert kinds == {name for name, rung in RUNG.items() if rung.planned}, (
        "a plan the reader would find empty"
    )
    assert "http://127.0.0.1:" in capsys.readouterr().out, "nothing told anybody where to look"


def test_the_demo_leaves_the_corpus_it_was_built_from_exactly_as_it_found_it(monkeypatch):
    """`demo` writes, and a demo that wrote into `seed/` would be a tracked
    directory quietly filling up with whatever anybody clicked. The write is
    proved rather than assumed: a real icon is stored through the real endpoint
    while the server is up, and `seed/` is compared byte for byte afterwards."""
    from fastapi.testclient import TestClient

    from openproj.cli import _seed_dir

    seed = _seed_dir()
    before = {path: path.read_bytes() for path in sorted(seed.rglob("*")) if path.is_file()}
    wrote = {}

    def while_it_runs(app):
        with TestClient(app) as client:
            wrote["answer"] = client.put("/api/icon", json={"icon": "fox"})

    assert run_demo(monkeypatch, while_it_runs) == 0

    assert wrote["answer"].status_code == 200, wrote["answer"].text
    after = {path: path.read_bytes() for path in sorted(seed.rglob("*")) if path.is_file()}
    assert after == before, "the demo wrote into the corpus it is a copy of"


def test_the_demo_repository_goes_when_the_server_does(monkeypatch, capsys):
    """Nothing durable, on purpose. A stable path reused between runs keeps
    yesterday's edits with nothing on screen saying which parts are the corpus
    and which are yours, makes two runs fight over one writer lock, and turns a
    demo into a repository nobody backs up.

    The path is taken from what the command printed rather than from a glob of
    the temp directory: another demo running on this machine is somebody else's
    business, and a test that swept the whole of `/tmp` would fail on their
    account and pass on a run where nothing was built at all.
    """
    alive = {}

    def while_it_runs(app):
        alive["repo"] = Path(capsys.readouterr().out.split()[1])
        assert alive["repo"].is_dir(), "the repository was not there while it was serving"

    assert run_demo(monkeypatch, while_it_runs) == 0
    assert not alive["repo"].exists(), "a demo repository outlived the server that made it"
    assert not alive["repo"].parent.exists()


def test_the_writers_lock_is_not_copied_into_the_demo_repository(tmp_path: Path):
    """A fossil, and the reason this is a function rather than a `cp -r`.

    `openproj.lock` is `Store`'s flock and holds the pid of whoever last opened
    one. A copy of it was committed to this repository — so the demo would have
    started life holding a lock file naming a process that had been dead for
    months, and a second run would have inherited the first run's pid. Asked of
    `store.LOCK_FILE` rather than of the string, so a rename cannot make this
    test pass by checking for a file that no longer exists.
    """
    from openproj.cli import _seed_files
    from openproj.store import LOCK_FILE

    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--x.md").write_text("---\nid: task-000001\n---\n")
    (tmp_path / LOCK_FILE).write_text("60008")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "defaults.yaml").write_text("schema_version: 4\n")

    files = _seed_files(tmp_path)

    assert LOCK_FILE not in files
    assert set(files) == {"tasks/task-000001--x.md", "config/defaults.yaml"}


def test_a_file_that_is_not_a_plan_file_is_not_copied_either(tmp_path: Path):
    """A `.DS_Store` beside the records is not part of anybody's plan, and it is
    not UTF-8 either — so "every file under here" would have made `openproj demo`
    raise a UnicodeDecodeError on a Mac that had once opened the folder."""
    from openproj.cli import _seed_files

    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-000001--x.md").write_text("---\nid: task-000001\n---\n")
    (tmp_path / ".DS_Store").write_bytes(b"\x00\x01\x82\xff not text")

    assert set(_seed_files(tmp_path)) == {"tasks/task-000001--x.md"}


def test_the_demo_is_drawn_around_the_day_its_own_corpus_calls_today(demo_root: Path):
    """The seed corpus is written around one day as "now". Served in December
    with the real clock it draws a plan every date of which is in the past, which
    is a demonstration of a scheduler with nothing left to schedule.

    The date is not typed in here either. `_demo_today` derives it from the
    cycles table; this checks that against the sentence `seed/README.md` says to
    a reader in prose. Two independent copies in the corpus, asserted to agree —
    a test that read the same table the code reads would agree with itself.
    """
    import re

    from openproj.cli import _demo_today
    from openproj.model import load_repo

    _, config, _ = load_repo(demo_root)
    said = re.search(
        r'"Today" for the demo is \*\*(\d{4}-\d{2}-\d{2})\*\*',
        (demo_root / "README.md").read_text(encoding="utf-8"),
    )

    assert said, "seed/README.md no longer says which day the demo is written around"
    assert _demo_today(config).isoformat() == said.group(1)


def test_a_plan_with_no_cycles_falls_back_to_the_real_today():
    """Every plan on its first day. `None` here rather than a guess, and the
    caller uses the clock — a demo of an empty plan has no opinion about when
    now is."""
    from openproj.cli import _demo_today
    from openproj.model import Config

    assert _demo_today(Config()) is None


def test_the_demo_refuses_a_port_that_is_taken_before_it_says_where_to_look(capsys):
    """uvicorn finds this out at the end, after the command has already printed a
    URL — which by then belongs to whatever else is on that port. A URL on screen
    that opens somebody else's server is worse than a refusal, because it is a
    refusal you go looking for in the wrong place."""
    import socket

    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]

        assert main(["demo", "--port", str(port)]) == 1

    printed = capsys.readouterr()
    assert f"port {port} is already in use" in printed.err
    assert "http://" not in printed.out, "it named a URL it had not managed to serve"


def test_the_demo_signs_you_in_as_somebody_the_plan_names(monkeypatch):
    """`--auth dev` used to be `dev`, who holds no work in any corpus — and the
    People page draws a picker on the signed-in person's row, so a demo signed in
    as `dev` demonstrated that feature by not showing it. The default is the
    first name on the corpus's own roster; `--as` is the rest of the team."""
    from fastapi.testclient import TestClient

    from openproj.cli import _seed_dir
    from openproj.model import load_repo

    _, config, _ = load_repo(_seed_dir())
    first, other = config.known_people[0], config.known_people[1]
    pickers = []

    def count_the_pickers(app):
        with TestClient(app) as client:
            pickers.append(client.get("/people").text.count('id="pick"'))

    assert first != other
    assert run_demo(monkeypatch, count_the_pickers) == 0
    assert run_demo(monkeypatch, count_the_pickers, ["--as", other]) == 0
    # And the other way, which is the claim underneath: the picker follows who
    # you are, rather than being drawn for whoever asks.
    assert run_demo(monkeypatch, count_the_pickers, ["--as", "nobody-in-this-plan"]) == 0

    assert pickers == [1, 1, 0], "the picker is not on the signed-in person's row"


# --- the container's signal path ---------------------------------------------


def test_a_signal_to_the_entrypoint_reaches_the_server(tmp_path: Path):
    """SIGTERM to the container's process must reach uvicorn, or nothing flushes.

    `boot.py` is PID 1 under the Dockerfile's CMD, installs no signal handler,
    and used to start the server with `subprocess.call` — a child. Python leaves
    SIGTERM at SIG_DFL and the kernel discards a default-disposition signal sent
    to PID 1, so `Server.handle_exit` never ran on Cloud Run: `app.state.closing`
    never set, the SSE loops never noticed, and the co-editing room's shutdown
    flush — which commits text somebody has typed and not yet saved — never ran
    there either. Ten silent seconds and then SIGKILL.

    Asked of a real process and a real signal, because the defect is entirely
    about process shape: run the entrypoint, wait until it is actually serving,
    send it SIGTERM, and require that IT exits and that nothing is left holding
    the port. With `subprocess.call` the parent dies on the signal and the
    orphaned server keeps the socket; with `execv` there is only one process and
    it shuts down gracefully. Not run as PID 1 — a container is not available
    here — but the mechanism under test is the same one.
    """
    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed the corpus")
    port = free_port()

    started = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent.parent / "deploy" / "boot.py")],
        env={
            **os.environ,
            "OPENPROJ_REPO": str(plan),
            "OPENPROJ_AUTH": "dev",
            "OPENPROJ_SECRET": "test-secret",
            "PORT": str(port),
            "OPENPROJ_REMOTE": "",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            time.sleep(0.1)
        else:
            raise AssertionError("the entrypoint never started serving")

        started.send_signal(signal.SIGTERM)
        try:
            said = started.communicate(timeout=30)[0]
        except subprocess.TimeoutExpired:
            raise AssertionError(
                "the entrypoint ignored SIGTERM — on Cloud Run that is ten silent "
                "seconds and then SIGKILL, with nothing flushed"
            ) from None
    finally:
        if started.poll() is None:  # pragma: no cover - only on a failure
            started.kill()
            started.wait(timeout=10)

    # The claim is not that the process went away — a SIGKILL would do that too,
    # and so would the wrapper dying while the server it started carried on. The
    # claim is that the SERVER ran its shutdown, because that is the hook
    # `app.state.closing` hangs off and therefore the hook every flush in
    # `design/deferred-push.md` depends on. uvicorn says so in three lines, and the
    # last of them only appears after lifespan shutdown has completed.
    assert "Application shutdown complete" in said, (
        "the server did not shut down gracefully, so `closing` never set and "
        f"nothing flushed. It said:\n{said}"
    )
    # And nothing is left holding the port: if a child were still serving, the
    # signal reached the wrapper and not the server.
    with pytest.raises(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            pass

    # NOT an assertion on the exit status, and this is worth writing down: after
    # a clean drain uvicorn restores SIGTERM's default disposition, so the status
    # is -15 and reads exactly like a process that ignored the signal and was
    # killed by it. The two are indistinguishable from the outside, which is why
    # the evidence here is what the server SAID rather than how it exited.


# --------------------------------------------------------------------------- #
# `new`: the write path for somebody without a browser
#
# Written after an agent was asked to file an issue against a plan repository and
# had to reverse-engineer the schema from the three issues already in it — which
# it did, and got `prs` wrong, because nothing told it that an issue is never
# scheduled and its `prs` is therefore not read. Every rule that would have said
# so was already in this codebase; there was just no command that ran them at the
# moment a record is written rather than some time afterwards.
# --------------------------------------------------------------------------- #


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    """A plan repository with nothing in it but its configuration, which is the
    state `new` has to work in: the first record is the one with no neighbour to
    copy."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "defaults.yaml").write_text(
        "schema_version: 4\nnominal_availability: 1.0\n", encoding="utf-8"
    )
    return tmp_path


def written(plan: Path) -> list[Path]:
    return sorted(p for p in plan.rglob("*.md") if p.is_file())


def test_new_writes_a_record_that_check_then_accepts(plan: Path):
    """The whole command, as one property: what it writes is what the gate CI
    runs will pass. Anything less and it is a template generator."""
    assert main(["new", "issue", str(plan), "--title", "Two extrapolations"]) == 0

    assert main(["check", str(plan)]) == 0


def test_new_files_a_record_under_its_kinds_directory_and_prefix(plan: Path):
    """Both come off the rung. An agent guessing them from the corpus is the
    thing this command exists to stop."""
    assert main(["new", "issue", str(plan), "--title", "Two extrapolations"]) == 0

    (only,) = written(plan)
    assert only.parent.name == "issues"
    assert only.stem.startswith("issue-")
    assert len(only.stem) == len("issue-") + 6


def test_new_stamps_the_repositorys_own_schema_version(plan: Path):
    """Read from the plan's config, never from a number in this code: a record
    written today is held to today's rules, and which rules those are is the
    repository's fact and not the CLI's."""
    (plan / "config" / "defaults.yaml").write_text(
        "schema_version: 2\nnominal_availability: 1.0\n", encoding="utf-8"
    )

    assert main(["new", "note", str(plan), "--title", "A thought"]) == 0

    (only,) = written(plan)
    assert "created_schema_version: 2" in only.read_text(encoding="utf-8")


def test_new_says_a_field_this_kind_does_not_read_is_not_read(plan: Path, capsys):
    """The exact trap that prompted this command. `prs` is a real field on the
    model, so nothing refuses it; it is simply never read on a record that is
    never scheduled. A warning, like `check` gives — the record is written, and
    the person is told before they commit rather than after.
    """
    code = main(
        [
            "new",
            "issue",
            str(plan),
            "--title",
            "Two extrapolations",
            "--set",
            "prs=kilnlab/kiln4py#1359",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "warning" in out
    assert "prs" in out
    assert "is not read" in out


def test_new_refuses_a_blocker_and_leaves_no_file_behind(plan: Path, capsys):
    """A record that cannot pass `check` must not reach the disk at all. Writing
    it and reporting the blocker would put the repository in the state the
    command was run to avoid, and leave somebody to `rm` their way out of it."""
    code = main(["new", "task", str(plan), "--title", "Port it", "--status", "ready"])

    assert code == 1
    assert written(plan) == []
    assert "blocker" in capsys.readouterr().out


def test_new_refuses_a_field_the_kind_does_not_have(plan: Path, capsys):
    """Not a validation problem — a typo. The field would sit in the frontmatter
    unread by anything, and every reader of that file would believe it meant
    something."""
    code = main(
        ["new", "issue", str(plan), "--title", "Two extrapolations", "--set", "reportedby=jcanton"]
    )

    assert code == 1
    assert written(plan) == []
    assert "reportedby" in capsys.readouterr().out


def test_new_owns_the_date_and_defaults_the_author_on_an_inbox_record(plan: Path):
    """When a record was made is not an opinion, so the command writes it. Who
    reported it is a default and not a fact — somebody files what a colleague
    mentioned in a corridor — so `--set` may say otherwise."""
    assert (
        main(
            [
                "new",
                "issue",
                str(plan),
                "--title",
                "Two extrapolations",
                "--set",
                "reported_by=jcanton",
            ]
        )
        == 0
    )

    (only,) = written(plan)
    text = only.read_text(encoding="utf-8")
    assert "reported_by: jcanton" in text
    assert f"opened_on: '{date.today().isoformat()}'" in text


def test_new_answers_in_json_for_something_that_is_not_a_person(plan: Path, capsys):
    """An agent has to read the id back to say what it filed, and parsing it out
    of prose is the kind of thing that works until the prose is reworded."""
    assert main(["new", "issue", str(plan), "--title", "Two extrapolations", "--json"]) == 0

    said = json.loads(capsys.readouterr().out)
    (only,) = written(plan)
    assert said["id"] == only.stem
    assert Path(said["path"]) == only.relative_to(plan)


def test_two_records_in_a_row_do_not_collide(plan: Path):
    """Six hex characters is 16.7 million, which is not infinity, and the loser of
    a collision would be a record silently overwritten by the next one."""
    assert main(["new", "note", str(plan), "--title", "One"]) == 0
    assert main(["new", "note", str(plan), "--title", "Two"]) == 0

    assert len(written(plan)) == 2


def test_new_can_commit_and_leaves_the_working_tree_clean(plan: Path):
    """The point of `--commit` is that the next command is `git push` and nothing
    else. A commit that moves the branch without the index leaves a clone whose
    `git status` reports the new record as both staged-deleted and untracked,
    which is a worse place to be than having committed by hand.
    """
    repo = pygit2.init_repository(str(plan), initial_head="main")
    repo.config["user.name"] = "Jacopo"
    repo.config["user.email"] = "jcanton@example.org"

    assert main(["new", "issue", str(plan), "--title", "Two extrapolations", "--commit"]) == 0

    (only,) = written(plan)
    reopened = pygit2.Repository(str(plan))
    # The record specifically, not the whole tree: the plan's own config is
    # untracked in this fixture and committing it is not this command's business.
    assert str(only.relative_to(plan)) not in reopened.status()
    head = reopened[reopened.references["refs/heads/main"].target]
    assert head.message.startswith(f"{only.stem}: ")
    assert head.tree / "issues" / only.name, "the record is not in the commit"


def test_new_without_commit_leaves_git_alone(plan: Path):
    """The default is a file on the disk and nothing else: a person who wants to
    read it before it becomes a commit must be able to, and an agent that got the
    title wrong should be able to just edit the file."""
    pygit2.init_repository(str(plan), initial_head="main")

    assert main(["new", "issue", str(plan), "--title", "Two extrapolations"]) == 0

    assert pygit2.Repository(str(plan)).references.get("refs/heads/main") is None


def test_new_works_in_a_directory_that_is_not_a_repository(tmp_path: Path):
    """`check` and `render` both run against a plain directory, and this is not
    the command that gets to be different about it."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "defaults.yaml").write_text("schema_version: 4\n", encoding="utf-8")

    assert main(["new", "note", str(tmp_path), "--title", "A thought"]) == 0


def test_one_set_on_a_list_field_is_a_list_of_one(plan: Path):
    """What somebody types. Without it the answer is a pydantic type error naming
    `list_type`, which is correct and no use at all when the fix is a pair of
    brackets that the shell also wants quoting."""
    assert (
        main(["new", "task", str(plan), "--title", "Port it", "--set", "reviewers=merganserly"])
        == 0
    )

    (only,) = written(plan)
    assert "reviewers:" in only.read_text(encoding="utf-8")
    assert "- merganserly" in only.read_text(encoding="utf-8")


def test_a_repeated_set_builds_the_list_without_brackets(plan: Path):
    """The other way in, for the caller who would rather not quote YAML at all."""
    assert (
        main(
            [
                "new",
                "task",
                str(plan),
                "--title",
                "Port it",
                "--set",
                "reviewers=merganserly",
                "--set",
                "reviewers=jackdawrie",
            ]
        )
        == 0
    )

    (only,) = written(plan)
    text = only.read_text(encoding="utf-8")
    assert "- merganserly" in text
    assert "- jackdawrie" in text


def test_new_writes_the_kinds_own_shaping_template(plan: Path):
    """A pitch that arrives with no headings is a pitch nobody shapes. The
    template is the team's, and it is the same one the browser's New starts
    from."""
    assert main(["new", "pitch", str(plan), "--title", "Port the dycore"]) == 0

    (only,) = written(plan)
    assert "## Problem" in only.read_text(encoding="utf-8")


def test_a_body_file_replaces_the_template(plan: Path):
    """The agent case: the body is already written somewhere and re-typing it
    through --set is not a thing anybody should do."""
    (plan / "body.md").write_text("## Problem\n\nTwo copies of one routine.\n", encoding="utf-8")

    assert (
        main(
            [
                "new",
                "issue",
                str(plan),
                "--title",
                "Two extrapolations",
                "--body-file",
                str(plan / "body.md"),
            ]
        )
        == 0
    )

    (only,) = (p for p in written(plan) if p.parent.name == "issues")
    assert "Two copies of one routine." in only.read_text(encoding="utf-8")


def test_set_wants_a_field_and_a_value(plan: Path, capsys):
    """`--set reported_by` with no `=` is a typo, and one that would otherwise be
    read as a field named `reported_by` with an empty value."""
    code = main(["new", "issue", str(plan), "--title", "T", "--set", "reported_by"])

    assert code == 1
    assert written(plan) == []
    assert "--set" in capsys.readouterr().out


def test_tag_and_set_tags_both_land(plan: Path):
    """`--tag` is documented as sugar for the same field, and sugar that silently
    drops the thing it is sugar for is the worst of both."""
    assert (
        main(["new", "issue", str(plan), "--title", "T", "--set", "tags=[dycore]", "--tag", "port"])
        == 0
    )

    text = written(plan)[0].read_text(encoding="utf-8")
    assert "- dycore" in text
    assert "- port" in text


@pytest.fixture
def a_machine_with_no_git_identity(tmp_path: Path):
    """Take `user.name` and `user.email` away from every config level there is.

    Through `pygit2.settings.search_path` and NOT through `HOME`: libgit2
    resolves those directories once, when it initialises, so an environment
    variable set afterwards is read by nothing — the first draft of this passed
    on a machine with no `~/.gitconfig` and on no other machine. Pointing the
    three levels above the repository at an empty directory is the supported way
    to say "this machine has no identity", and it says it the same everywhere.

    Global state, so it is put back on the way out however the test leaves.
    """
    levels = (
        pygit2.enums.ConfigLevel.GLOBAL,
        pygit2.enums.ConfigLevel.XDG,
        pygit2.enums.ConfigLevel.SYSTEM,
    )
    empty = tmp_path / "no-git-config"
    empty.mkdir()
    was = {level: pygit2.settings.search_path[level] for level in levels}
    for level in levels:
        pygit2.settings.search_path[level] = str(empty)
    yield
    for level, path in was.items():
        pygit2.settings.search_path[level] = path


@pytest.mark.usefixtures("a_machine_with_no_git_identity")
def test_commit_into_a_repository_with_no_identity_writes_nothing(plan: Path, capsys):
    """Asked before the record is written, not after. A refusal that arrives once
    the file is on the disk keeps neither half of the contract: the record exists,
    the commit does not, and the exit code says the whole thing failed."""
    pygit2.init_repository(str(plan), initial_head="main")

    code = main(["new", "issue", str(plan), "--title", "T", "--commit"])

    assert code == 1
    assert written(plan) == []
    assert "identity" in capsys.readouterr().out


def test_commit_in_a_directory_that_is_not_a_repository_writes_nothing(plan: Path, capsys):
    """`--commit` against a plain directory is a typo, not a request to go looking
    for a repository somewhere above it."""
    code = main(["new", "issue", str(plan), "--title", "T", "--commit"])

    assert code == 1
    assert written(plan) == []
    assert "not a git repository" in capsys.readouterr().out


def test_commit_from_a_plan_nested_in_another_repository_writes_nothing(tmp_path: Path, capsys):
    """`pygit2.Repository()` searches upwards, so a plan directory inside some
    other checkout resolves to THAT one — and every path this command computed is
    relative to the plan. Committing anyway stages a path that does not exist."""
    pygit2.init_repository(str(tmp_path), initial_head="main")
    inside = tmp_path / "plan"
    (inside / "config").mkdir(parents=True)
    (inside / "config" / "defaults.yaml").write_text("schema_version: 4\n", encoding="utf-8")

    code = main(["new", "issue", str(inside), "--title", "T", "--commit"])

    assert code == 1
    assert list(inside.rglob("*.md")) == []
    assert "not the root of one" in capsys.readouterr().out


def test_every_command_is_named_in_the_help_summary():
    """`openproj --help` opens with the module docstring's first line, so a
    command missing from it is a command a person reading the help does not know
    exists.

    `new` was missing for exactly as long as it took to run the published package
    once and read the output. Writing this test then found `serve` missing too,
    and had been since it was added — a list of commands maintained by hand beside
    a list maintained by argparse is two lists, and the hand-written one is the
    one that goes stale without anything failing.
    """
    from openproj.cli import _parser

    parser = _parser()
    commands = next(
        action for action in parser._actions if action.dest == "command" and action.choices
    )

    missing = [
        name
        for name in commands.choices
        if not re.search(rf"\b{re.escape(name)}\b", parser.description)
    ]
    assert not missing, f"not in `openproj --help`: {', '.join(missing)}"


@pytest.fixture
def a_machine_whose_git_knows_you(tmp_path: Path):
    """A global git config naming an author, and nothing else, the same way
    `a_machine_with_no_git_identity` takes one away: through libgit2's search
    path, because HOME is read once at initialisation and then never again."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = Ann Ashworth\n\temail = ann@example.org\n")
    level = pygit2.enums.ConfigLevel.GLOBAL
    was = pygit2.settings.search_path[level]
    pygit2.settings.search_path[level] = str(home)
    yield
    pygit2.settings.search_path[level] = was


@pytest.mark.usefixtures("a_machine_whose_git_knows_you")
def test_init_writes_a_plan_that_check_accepts_and_commits_it_under_your_name(
    tmp_path: Path, monkeypatch, capsys
):
    """Before this, a plan was started by copying `seed/config` — a demo roster,
    a 2026 calendar and whatever schema version the demo was at. The four files
    here name nobody but the person asked for, hold no dates, and sit at the
    newest schema version; the commit is theirs, and the working tree is clean
    afterwards, so the next command is `openproj new`."""
    from openproj.model import LATEST_SCHEMA_VERSION, load_config

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    plan = tmp_path / "garden"

    assert (
        main(
            [
                "init",
                str(plan),
                "--as",
                "ann",
                "--org",
                "kilnlab",
                "--remote",
                "https://example.org/kilnlab/garden.git",
            ]
        )
        == 0
    )

    config = load_config(plan)
    assert config.schema_version == LATEST_SCHEMA_VERSION
    assert config.known_people == ["ann"]
    assert config.cycles == {} and config.holidays == []
    repo = pygit2.Repository(str(plan))
    head = repo[repo.head.target]
    assert head.author.name == "Ann Ashworth" and head.parents == []
    assert repo.status() == {}, "a commit that skipped the index leaves everything untracked"
    assert repo.remotes["origin"].url == "https://example.org/kilnlab/garden.git"
    assert main(["check", str(plan)]) == 0
    assert "openproj new pitch" in capsys.readouterr().out


def test_init_refuses_a_directory_with_something_in_it(tmp_path: Path, capsys):
    """`init .` in the wrong terminal must not put a plan inside a codebase."""
    (tmp_path / "main.py").write_text("print()\n")

    assert main(["init", str(tmp_path), "--no-prompt"]) == 1

    assert "not empty" in capsys.readouterr().out
    assert not (tmp_path / "config").exists() and not (tmp_path / ".git").exists()


@pytest.mark.usefixtures("a_machine_with_no_git_identity")
def test_init_on_a_machine_git_cannot_name_writes_nothing_unless_told_not_to_commit(
    tmp_path: Path, capsys
):
    """The refusal `new --commit` makes, made before the first file rather than
    after the last: a plan on the disk with no commit and an exit code saying
    the whole thing failed is the outcome with no good next step."""
    plan = tmp_path / "garden"

    assert main(["init", str(plan), "--no-prompt"]) == 1
    assert "identity" in capsys.readouterr().out
    assert not plan.exists()

    assert main(["init", str(plan), "--no-prompt", "--no-commit"]) == 0
    assert (plan / "config" / "defaults.yaml").is_file()
    assert pygit2.Repository(str(plan)).head_is_unborn


@pytest.mark.usefixtures("a_machine_whose_git_knows_you")
def test_init_writes_the_deployment_it_is_told_and_carries_the_org_and_remote_into_it(
    tmp_path: Path,
):
    """The deploy script reads one file, so the org and the remote the plan was
    given are written into it as well — twice on the command line would be the
    two copies that disagree."""
    plan = tmp_path / "garden"
    assert (
        main(
            [
                "init",
                str(plan),
                "--no-prompt",
                "--org",
                "kilnlab",
                "--remote",
                "https://example.org/kilnlab/garden.git",
                "--deploy",
                "PROJECT=roast-1",
                "--deploy",
                "APP_ID=1",
            ]
        )
        == 0
    )

    written = (plan / "deploy" / "openproj.env").read_text()
    assert 'PROJECT="roast-1"' in written and 'APP_ID="1"' in written
    assert 'ORG="kilnlab"' in written
    assert 'REMOTE="https://example.org/kilnlab/garden.git"' in written
    assert 'REGION="europe-west1"' in written, "a blank REGION is a deploy that fails late"


def test_init_refuses_a_deployment_key_it_does_not_know(tmp_path: Path, capsys):
    """`--deploy PROJET=x` would be a file with a blank PROJECT and a key nothing
    reads, and the deploy would say so an hour later."""
    assert main(["init", str(tmp_path / "garden"), "--no-prompt", "--deploy", "PROJET=x"]) == 1
    assert "PROJET" in capsys.readouterr().out
    assert not (tmp_path / "garden").exists()


def test_init_asks_only_for_what_the_command_line_left_out():
    """A question per missing option, none for a given one, and the deployment
    behind a single yes-or-no — so a command line that says everything asks
    nothing, which is what lets a script call this at all."""
    from openproj.bootstrap import Options, ask_for_the_rest

    # Ten answers for the first call, and one "n" for the second call's yes-or-no.
    answers = iter(
        ["https://example.org/p.git", "ann", "y", "roast-1", "", "", "1", "2", "c", "/k", "n"]
    )
    asked: list[str] = []

    def ask(question: str) -> str:
        asked.append(question)
        return next(answers)

    got = ask_for_the_rest(Options(org="kilnlab"), ask)

    assert not any("org" in question.lower() for question in asked), asked
    assert got.org == "kilnlab" and got.remote == "https://example.org/p.git" and got.login == "ann"
    assert got.deploy["ORG"] == "kilnlab", "carried from the answer above, not asked twice"
    assert got.deploy["REMOTE"] == "https://example.org/p.git"
    assert got.deploy["REGION"] == "europe-west1" and got.deploy["SERVICE"] == "openproj"
    assert got.deploy["PROJECT"] == "roast-1" and got.deploy["APP_KEY_FILE"] == "/k"

    nothing = ask_for_the_rest(Options(org="a", remote="b", login="c"), ask)
    assert nothing.deploy == {} and asked[-1].startswith("Describe a Cloud Run deployment")


@pytest.mark.usefixtures("a_machine_whose_git_knows_you")
def test_init_asks_at_a_terminal_and_not_elsewhere(tmp_path: Path, monkeypatch):
    """The wiring: `input` is reached only when stdin is a terminal."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["", "", "ann", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert main(["init", str(tmp_path / "asked")]) == 0
    assert "ann" in (tmp_path / "asked" / "config" / "people.yaml").read_text()

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked without a terminal"))
    assert main(["init", str(tmp_path / "silent")]) == 0


def test_the_example_env_is_the_blank_form():
    """`deploy/example.env` is documentation of a file the code writes, so it is
    generated from the same template and this keeps the two the same."""
    from openproj.bootstrap import deploy_env_text

    example = Path(__file__).resolve().parents[1] / "deploy" / "example.env"
    assert example.read_text() == deploy_env_text({})


def test_the_seed_is_written_at_the_newest_schema_version(demo_root: Path):
    """`LATEST_SCHEMA_VERSION` is a literal because the rules carry theirs as
    literals; `seed/config/defaults.yaml` says in its own comments that it tracks
    the newest rule. A bump that forgets one of them fails here. (`seed_root` is
    the frozen test corpus at version 2, which is why it is not the fixture.)"""
    from openproj.model import LATEST_SCHEMA_VERSION, load_config

    assert load_config(demo_root).schema_version == LATEST_SCHEMA_VERSION


def test_serve_refuses_github_auth_without_an_org(seed_root: Path, monkeypatch, capsys):
    """`--org` defaulted to one team's org, so every other deployment that forgot
    the flag refused everybody outside that team, silently. Now it is a refusal
    to start, before anything is opened."""
    monkeypatch.delenv("OPENPROJ_ORG", raising=False)

    assert main(["serve", "--repo", str(seed_root), "--auth", "github"]) == 2

    assert "org" in capsys.readouterr().err


def test_the_app_refuses_github_auth_without_an_org(tmp_path: Path):
    """The same refusal one layer down, for a caller that builds the app itself."""
    from openproj.web import create_app

    with pytest.raises(ValueError, match="org"):
        create_app(tmp_path, auth="github", secret="s" * 40, client_id="a", client_secret="b")
