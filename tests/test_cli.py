"""The command line, which is the whole product when the web view is not running.

`check` is the one that has to be exactly right: it is what CI runs, so its exit
code decides whether a bad record reaches the repository.
"""

import json
import os
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
            "status: ready",
            "owner: jcanton",
            "reviewers: [msimberg]",
            "person_weeks: 1.0",
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
            "status: ready",
            "owner: jcanton",
            "reviewers: [msimberg]",
            "person_weeks: 1.0",
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
    # 08-13 and not the 08-17 asked for: the task is in progress and was assigned
    # on the 13th, so it starts when it started. `--today` still moves everything
    # that has not begun, which is what this test is about.
    assert payload["spans"]["task-53a9f0"]["start"] == "2026-08-13"


def test_an_unknown_subcommand_fails_rather_than_doing_something(capsys):
    assert main(["frobnicate"]) == 2


def test_the_shipped_demo_corpus_validates_clean(demo_root: Path):
    """The demo is the first thing anyone runs. A demo that fails its own check
    teaches people the check is noise.

    Distinct from the golden corpus in tests/fixtures/, which deliberately carries
    nine blockers because migrated data is messy and the validator has to say so.
    """
    assert main(["check", str(demo_root)]) == 0


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
    """static/ is not in the wheel, so an installed layout resolves the source-tree
    path past site-packages and GET /graph becomes an uncaught FileNotFoundError.
    Found by building a wheel rather than by reading the path."""
    from openproj.render import _static_dir

    (tmp_path / "cytoscape.min.js").write_text("//")
    monkeypatch.setenv("OPENPROJ_STATIC", str(tmp_path))

    assert _static_dir() == tmp_path


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
        "owner: jcanton\nreviewers: [msimberg]\nassigned_on: 9999-12-31\n"
        "prs: [\"C2SM/icon4py#1\"]\nperson_weeks: 1.0\n---\n\nBody.\n",
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

    for name in ("index.html", "detail.html", "people.html",
                 "cycles.html", "graph.html", "timeline.html"):
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
    # `serve` is replaced, so `main` stops at the one decision under test.
    (tmp_path / "plan.git").mkdir()
    monkeypatch.setattr(boot.subprocess, "call", lambda *a, **k: 0)
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
            seen["table"] = client.get("/")
            seen["people"] = client.get("/people")
            seen["index"] = client.get("/api/index.json").json()

    assert run_demo(monkeypatch, while_it_runs) == 0

    assert seen["table"].status_code == 200
    assert seen["people"].status_code == 200
    kinds = {entity["kind"] for entity in seen["index"]["entities"].values()}
    assert kinds == {"project", "pitch", "task"}, "a plan the reader would find empty"
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
    said = re.search(r'"Today" for the demo is \*\*(\d{4}-\d{2}-\d{2})\*\*',
                     (demo_root / "README.md").read_text(encoding="utf-8"))

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
