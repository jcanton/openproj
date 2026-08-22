"""The issue rung: off the plan by data, not by type.

An issue used to be kept off the table, the graph, the timeline and the people
page by being a separate type. It is now an `Entity` on a rung with
`planned=False`, and the exclusion is enforced once — in `build_index`, backed
by the Index validator and the KINDS-derived exclusion sweep, which stops being
vacuous in the commit that adds this rung. What is left for this file is what
is true of issues and of nothing else: the vocabulary, the derived state, the
server's stamping at creation, and the redirects from the retired routes.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, file_at, git_head

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import (
    ISSUE_STATUS,
    RUNG,
    Config,
    Entity,
    Issue,
    Task,
    load_repo,
    unread_fields,
    validate_all,
)
from openproj.web import ID_PATTERN, SESSION_COOKIE, create_app


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


def opened(client: TestClient, title: str, base: str, body: str = "", **fields) -> str:
    """An issue through the one door every record uses now."""
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "issue", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def entities(**by_id: str) -> dict[str, Task]:
    return {
        i: Task(id=i, kind="task", title=i, status=status) for i, status in by_id.items()
    }


# --------------------------------------------------------------------------- #
# The rung
# --------------------------------------------------------------------------- #


def test_an_issue_is_a_rung_of_the_ladder():
    """The properties the old separate type carried longhand, now data on the
    one ladder every derivation reads."""
    rung = RUNG["issue"]

    assert issubclass(Issue, Entity)
    assert rung.model is Issue
    assert (rung.prefix, rung.directory) == ("issue", "issues")
    assert rung.planned is False, "off every plan view, enforced in build_index"
    assert rung.statuses == ISSUE_STATUS
    assert not rung.schedules and not rung.depends and not rung.sized and not rung.carded
    for commitment in ("owner", "cycle", "priority", "depends_on", "person_weeks"):
        assert commitment in unread_fields("issue"), commitment
    assert "status" not in unread_fields("issue"), "an issue reads its status"


def test_an_issue_has_no_shaping():
    """A shaped issue is a pitch. Shaping happens in the record an issue is
    promoted into, never in the issue itself — and with the vocabulary on the
    rung, `shaping` is now refused on an issue instead of silently legal."""
    assert ISSUE_STATUS == ("ready", "in_progress", "done", "shelved")


# --------------------------------------------------------------------------- #
# What a link means
# --------------------------------------------------------------------------- #


def test_pitching_an_issue_is_what_closes_it():
    """Derived, never copied. Writing the state into the file as well would be
    a second copy of a fact the link already carries, and the two disagree the
    moment somebody closes the pitch."""
    world = entities(**{"task-aa0001": "done", "task-bb0001": "in_progress"})
    unlinked = Issue(id="issue-000001", kind="issue", title="x")
    picked = Issue(id="issue-000002", kind="issue", title="x", pitched_into=["task-bb0001"])
    finished = Issue(id="issue-000003", kind="issue", title="x", pitched_into=["task-aa0001"])
    partly = Issue(id="issue-000004", kind="issue", title="x",
                   pitched_into=["task-aa0001", "task-bb0001"])

    assert unlinked.state(world) == "ready"
    assert picked.state(world) == "in_progress"
    assert finished.state(world) == "done"
    assert partly.state(world) == "in_progress"


def test_shelved_is_a_decision_a_link_does_not_reverse():
    world = entities(**{"task-aa0001": "done"})
    wont_fix = Issue(id="issue-000001", kind="issue", title="x", status="shelved",
                     pitched_into=["task-aa0001"])

    assert wont_fix.state(world) == "shelved"


def test_a_link_to_something_that_is_gone_leaves_the_stored_state_alone():
    """An issue outlives the pitch it fed. A deleted target is a warning from
    the one validator every record goes through now — `issue_problems` is gone,
    and the rule survives in `_problems_for` keyed by the link field."""
    issue = Issue(id="issue-000001", kind="issue", title="x", pitched_into=["task-zzzzzz"])

    assert issue.state({}) == "ready"
    assert [(p.severity, p.field) for p in validate_all([issue], Config())] == [
        ("warning", "pitched_into")
    ]


# --------------------------------------------------------------------------- #
# Writing — the lost route defaults (spec test 10)
# --------------------------------------------------------------------------- #


def test_creating_an_issue_stamps_the_lost_route_defaults(
    client: TestClient, repo_path: Path
):
    """POST /api/issue is deleted. The generic create stamps what it stamped:
    a minted id (never the browser's), the signed-in reporter, the server's
    date, and the opening status."""
    issue_id = opened(client, "openproj check is slow", git_head(repo_path))
    stored = file_at(repo_path, git_head(repo_path), f"issues/{issue_id}.md")

    assert re.fullmatch(r"issue-[0-9a-f]{6}", issue_id)
    assert "title: openproj check is slow" in stored
    assert "status: ready" in stored
    assert f"reported_by: {ANN.login}" in stored
    assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", stored)


def test_the_reporter_is_a_default_and_the_date_is_not(
    client: TestClient, repo_path: Path
):
    """The session knows who is writing, and that is right almost every time —
    not when somebody files what a colleague mentioned in a corridor, so the
    form can say otherwise. `opened_on` stays the server's: when the record was
    made is not an opinion."""
    theirs = opened(client, "y", git_head(repo_path), reported_by="halungge")
    stamped = opened(client, "z", git_head(repo_path), opened_on="1999-01-01")

    assert "reported_by: halungge" in file_at(
        repo_path, git_head(repo_path), f"issues/{theirs}.md"
    )
    dated = file_at(repo_path, git_head(repo_path), f"issues/{stamped}.md")
    assert "1999" not in dated, "a client-sent creation date is overruled"
    assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", dated)


def test_an_issue_still_needs_a_title(client: TestClient, repo_path: Path):
    before = git_head(repo_path)
    refused = client.post(
        "/api/entity",
        json={"base_commit": before, "fields": {"kind": "issue", "title": "  "}},
    )

    assert refused.status_code == 422
    assert git_head(repo_path) == before, "a refusal writes nothing"


def test_a_word_off_the_issue_ladder_is_refused_at_both_doors(
    client: TestClient, repo_path: Path
):
    """Spec test 4, armed for the rung it was written for: the bespoke gates
    are gone and the generic one must hold the same line, before anything is
    committed."""
    issue_id = opened(client, "x", git_head(repo_path))
    before = git_head(repo_path)

    created = client.post(
        "/api/entity",
        json={"base_commit": before,
              "fields": {"kind": "issue", "title": "y", "status": "shaping"}},
    )
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": before, "fields": {"status": "shaping"}, "body": None},
    )

    assert created.status_code == 422
    assert saved.status_code == 422
    assert "an issue" in created.text, "the refusal reads like the model's own prose"
    assert git_head(repo_path) == before, "a refusal writes nothing"


def test_an_issue_id_is_an_entity_id_now(client: TestClient, repo_path: Path):
    """The pattern is derived from KINDS, so the rung brought its prefix on the
    commit that added it — and the whole entity write surface with it."""
    issue_id = opened(client, "x", git_head(repo_path))

    assert ID_PATTERN.match(issue_id)
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": git_head(repo_path), "fields": {"tags": ["halo"]},
              "body": None},
    )
    assert saved.status_code == 200, saved.text
    assert "- halo" in file_at(repo_path, git_head(repo_path), f"issues/{issue_id}.md")


# --------------------------------------------------------------------------- #
# The hand-written edge, in both directions (the two latent KeyErrors)
# --------------------------------------------------------------------------- #


def test_a_hand_written_edge_to_an_issue_does_not_500_the_table(
    tmp_path: Path,
):
    """`blocked_by` is total over records, so a planned task whose hand-written
    `depends_on` names an issue keeps that edge — and the table's blocker count
    looked the blocker up in the PLAN, which was a KeyError and a 500 on
    /table over one hand-edited file. The count still counts it; the id stays
    off the page, which is a plan view."""
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, {
        **SEED,
        "issues/issue-9a9a9a.md": (
            "---\nid: issue-9a9a9a\ntitle: hand-written blocker\nstatus: ready\n---\n\nx\n"
        ),
        "tasks/task-9b9b9b.md": (
            "---\nid: task-9b9b9b\nkind: task\ntitle: waits on an inbox record\n"
            "status: ready\nowner: ann\nassignees: [ann]\nreviewers: [bo]\n"
            "person_weeks: 1\ndepends_on: [issue-9a9a9a]\n---\n\nx\n"
        ),
    }, "seed a hand-written edge")
    with TestClient(create_app(path, auth="dev", secret=SECRET)) as client:
        table = client.get("/table")
        graph = client.get("/graph")

    assert table.status_code == 200
    assert "issue-9a9a9a" not in table.text, "an inbox id leaked onto a plan page"
    assert graph.status_code == 200
    assert "issue-9a9a9a" not in graph.text, "an inbox id leaked into the graph"


def test_deleting_what_a_hand_written_issue_waits_on_edits_the_issue(
    tmp_path: Path,
):
    """The other direction: `cascade_of` iterates records, so a hand-written
    `depends_on` on an ISSUE puts the issue in `edited` when its target is
    deleted — and the plan-only lookup in the DELETE handler KeyErrored and
    500ed. The delete lands, and the issue loses the dependency like any other
    dependent record."""
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, {
        **SEED,
        "issues/issue-8c8c8c.md": (
            "---\nid: issue-8c8c8c\ntitle: waits by hand\nstatus: ready\n"
            "depends_on: [task-c00002]\n---\n\nx\n"
        ),
    }, "seed a dependent issue")
    with TestClient(create_app(path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        removed = client.request(
            "DELETE", "/api/entity/task-c00002",
            json={"base_commit": git_head(path), "also": ["issue-8c8c8c"]},
        )

    assert removed.status_code == 200, removed.text
    survives = file_at(path, git_head(path), "issues/issue-8c8c8c.md")
    assert "task-c00002" not in survives, "the freed issue still names the deleted task"


# --------------------------------------------------------------------------- #
# The shared page, and the retired routes
# --------------------------------------------------------------------------- #


def test_the_retired_issue_routes_redirect_to_the_shared_ones(
    client: TestClient, repo_path: Path
):
    issue_id = opened(client, "x", git_head(repo_path))

    for old, new in (
        ("/issues", "/"),
        ("/issue/new", "/new?kind=issue"),
        (f"/issue/{issue_id}", f"/detail/{issue_id}"),
    ):
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 301, old
        assert moved.headers["location"] == new, old


def test_an_issue_renders_on_the_shared_record_page(
    client: TestClient, repo_path: Path
):
    issue_id = opened(client, "Halo exchange drops a rank", git_head(repo_path))
    page = client.get(f"/detail/{issue_id}").text

    assert "Halo exchange drops a rank" in page
    assert 'id="promote-go"' in page, "the promote panel moved here with the record"
    hovered = client.get(f"/api/body/{issue_id}")
    assert hovered.status_code == 200, "the hover card reads records, not the plan"
    # The commitbar arrives with the shared page. Cancel now means what it
    # means everywhere on this page — the text stays in the box and the stored
    # draft is forgotten — a DELIBERATE change from the old restore-the-body.
    assert 'id="save"' in page and 'id="cancel"' in page


def test_the_create_form_offers_an_issue_no_plan_status(client: TestClient):
    """The one status control on /new is the plan ladder, and `shaping` on an
    issue is a word the server refuses — offering it would be the form and the
    validator disagreeing in the most annoying possible order. The row is not
    offered to the inbox kinds; the server stamps the opening status, and the
    record page's own per-kind hill is one save away."""
    page = client.get("/new?kind=issue").text

    status_row = re.search(r'data-kinds="([^"]*)"(?:(?!data-kinds).)*?name="status"',
                           page, re.S)
    assert status_row, "the create form must still carry the plan kinds' status row"
    assert "issue" not in status_row.group(1).split()
    assert "note" not in status_row.group(1).split()
    reported = re.search(r'data-kinds="([^"]*)"(?:(?!data-kinds).)*?id="new-reported_by"',
                         page, re.S)
    assert reported and reported.group(1).split() == ["issue"], (
        "an issue's own field is offered to issues and to nothing else"
    )


def test_a_derived_state_reads_on_the_page_and_locks_the_control(
    client: TestClient, repo_path: Path
):
    """Two ways to say one thing disagree the moment one of them is used, so an
    issue whose links decide its state shows the derived word and a control
    that says why it is off."""
    issue_id = opened(client, "x", git_head(repo_path))
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": git_head(repo_path),
              "fields": {"pitched_into": ["task-c00001"]}, "body": None},
    )
    assert saved.status_code == 200, saved.text

    assert "from the work it was pitched into" in client.get(f"/detail/{issue_id}").text


# --------------------------------------------------------------------------- #
# The corpus, and the check that finally covers it
# --------------------------------------------------------------------------- #


def test_the_seed_corpus_issues_load_as_records_off_the_plan(demo_root: Path):
    entities_now, config, unreadable = load_repo(demo_root)
    assert not unreadable

    index = build_index(entities_now, config, date(2026, 8, 17))
    issues = {i: r for i, r in index.records.items() if r.kind == "issue"}

    assert issues, "the demo corpus has issues"
    assert not set(issues) & set(index.entities), "and none of them is in the plan"
    assert not [
        p for p in index.problems
        if p.severity == "blocker" and p.entity_id in issues
    ]
    assert {r.state(index.entities) for r in issues.values()} <= set(ISSUE_STATUS)


def test_check_covers_issues_for_the_first_time(tmp_path: Path):
    """`openproj check` runs `validate_all(entities, config)` and nothing else,
    so `issue_problems` was dead to it from the day it was written: an issue
    with a status nobody defined passed check clean while the web banner
    reported it. One reader now — the same walk, the same rules."""
    (tmp_path / "issues").mkdir()
    (tmp_path / "issues" / "issue-bad001.md").write_text(
        "---\nid: issue-bad001\ntitle: an issue\nstatus: open\n---\n\nx\n",
        encoding="utf-8",
    )

    entities_now, config, unreadable = load_repo(tmp_path)

    assert not unreadable
    assert [e.kind for e in entities_now] == ["issue"], "load_repo walks issues/ itself"
    assert [(p.severity, p.field) for p in validate_all(entities_now, config)] == [
        ("blocker", "status")
    ]
