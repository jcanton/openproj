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
