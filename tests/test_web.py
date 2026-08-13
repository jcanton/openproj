"""The server's contract, written before the server exists.

Phase 1 shipped four pages that could only be read. This is what changes when a
browser can write, and almost every assertion below is about one of five
decisions:

* **Reads are public, writes are not.** The content is public by decision, so
  every GET answers an anonymous browser. The gate lives on the two write
  endpoints and is checked *per request* from the signed session, never at login
  alone: a server that only asks about membership at `/auth/callback` and then
  issues a cookie to whoever authenticated has handed write access to every
  GitHub user on earth. `test_a_signed_in_non_member_is_refused_at_the_write`
  is the one that would catch that, and it is why the non-member in these tests
  holds a *valid* session.
* **The author is the session, and only the session.** The author/committer split
  in `store.py` is the team's only audit trail, and it is worth precisely as much
  as the guarantee that the author string was not client-supplied. Hence a header
  and a query parameter that both try to be somebody else.
* **The writable surface is a closed set by construction.** The path is derived
  from an id that has to match `^(proj|pitch|task)-[0-9a-f]{6}$` first, and the
  kind comes from the id prefix — not from the body, and never from string
  concatenation. Branch protection (spec §13) means a bad write cannot be
  force-pushed away, so the bound has to be at the door.
* **A save preserves the file.** `PATCH` sends only the touched fields, and what
  lands in git differs from what was there by exactly the lines that changed —
  comments, key order, list style and body intact. "Edit it in git if you prefer"
  stops being true the first time a save reformats somebody's file, and nobody
  comes back after that.
* **A refusal writes nothing.** A 409 leaves HEAD where it was and carries a
  rendered conflict with no `<<<<<<<` in it, because a conflict marker that
  reaches the client reaches a textarea.

Everything git-shaped is asserted against the repository with pygit2 rather than
against the API's own answer, since the API reporting success is exactly the
thing under test. The bare repo is seeded with `test_store`'s `commit_directly`
so that both suites agree on what a plan repository looks like.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pygit2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from test_store import commit_directly

from openproj.auth import User, sign_session
from openproj.web import create_app

ORG = "C2SM"
SECRET = "a-real-signing-secret-for-tests"
CLIENT_ID = "Iv1.0123456789abcdef"
CLIENT_SECRET = "s3cr3t-client-secret"

# Named exactly, because the `__Host-` prefix is load-bearing: it makes cookie
# fixation from a sibling subdomain structurally impossible and forces the
# browser to enforce Secure, Path=/ and no Domain on our behalf.
SESSION_COOKIE = "__Host-openproj_session"
STATE_COOKIE = "op_state"

ANN = User(login="ann", member=True)
MALLORY = User(login="mallory", member=False)

TASK = "task-c00001"
OTHER = "task-c00002"
DONE = "task-c00003"
PITCH = "pitch-b20000"
PROJECT = "proj-a10000"

PATH = f"tasks/{TASK}.md"


# --------------------------------------------------------------------------- #
# The corpus
#
# Small, valid but for one deliberate blocker, and one file hand-formatted the
# way a person writes one — a leading comment, a blank line inside the
# frontmatter, key order that is nobody's business but theirs, an inline comment
# and two flow-style lists. That file is the round-trip promise made concrete.
# --------------------------------------------------------------------------- #

HAND_FORMATTED = """---
# Two GPUs, and only on the equator. The note at the bottom belongs with the file.
title: Reproduce the 2-GPU equator artefact
kind: task
status: wip
effort_weeks: 1.5          # measured on daint, not guessed

id: task-c00001
parent: pitch-b20000
owner: ann                 # ann has the DWD contacts
reviewers: [bo, cy]
assigned_on: 2026-07-06
priority: 2
tags: [gpu, verification]
prs: []
---

The artefact shows up on the equator only, and only with two ranks.
It is not visible in the serialbox reference data.
"""

SEED = {
    "config/defaults.yaml": (
        "schema_version: 2\nnominal_availability: 1.0\ndefault_task_effort: 0.5\n"
    ),
    f"projects/{PROJECT}.md": (
        "---\n"
        "id: proj-a10000\n"
        "kind: project\n"
        "title: Distributed driver\n"
        "status: wip\n"
        "owner: ann\n"
        "reviewers: [bo]\n"
        "assigned_on: 2026-07-01\n"
        "priority: 1\n"
        "---\n"
        "\nThe standalone driver, on more than one rank.\n"
    ),
    f"pitches/{PITCH}.md": (
        "---\n"
        "id: pitch-b20000\n"
        "kind: pitch\n"
        "title: Verify the tracer advection port\n"
        "parent: proj-a10000\n"
        "status: todo\n"
        "owner: ann\n"
        "reviewers: [bo]\n"
        "appetite_weeks: 3\n"
        "priority: 1\n"
        "---\n"
        "\nPort the least-squares coefficients and check them against serialbox.\n"
    ),
    PATH: HAND_FORMATTED,
    f"tasks/{OTHER}.md": (
        "---\n"
        "id: task-c00002\n"
        "kind: task\n"
        "title: Downgrade numpy for global sums\n"
        "parent: pitch-b20000\n"
        "status: todo\n"
        "owner: bo\n"
        "reviewers: [ann]\n"
        "effort_weeks: 0.5\n"
        "priority: 3\n"
        "---\n"
        "\nGlobal sums stopped being reproducible at numpy 2.1.\n"
    ),
    # The one deliberate blocker in the corpus: done, with nothing to show for it.
    f"tasks/{DONE}.md": (
        "---\n"
        "id: task-c00003\n"
        "kind: task\n"
        "title: Read the IPDPS 2014 paper\n"
        "parent: pitch-b20000\n"
        "status: done\n"
        "owner: cy\n"
        "review_waived: true\n"
        "effort_weeks: 0.5\n"
        "---\n"
        "\nAnurag's paper on halo exchange.\n"
    ),
}


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    """A bare repository, seeded the way `test_store` seeds one.

    In production the data repository is a different repository from this one, so
    the server is only ever pointed at a path — never at its own checkout.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    """A signed-in member, in the mode the team runs locally.

    The session cookie is set even in `auth="dev"` because the author of a commit
    comes from the session in both modes; dev decides who may write, never who
    gets the credit.
    """
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


@pytest.fixture
def secure_client(repo_path: Path):
    """The production configuration, with nobody signed in."""
    app = create_app(
        repo_path,
        auth="github",
        org=ORG,
        secret=SECRET,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    with TestClient(app) as client:
        yield client


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


# `TestClient` is an `httpx.Client`, so the helpers below work unchanged against
# the live server the events test needs.


def head(client: httpx.Client) -> str:
    return client.get("/healthz").json()["head"]


def git_head(repo_path: Path) -> str:
    return str(pygit2.Repository(str(repo_path)).references["refs/heads/main"].target)


def file_at(repo_path: Path, commit: str, path: str) -> str:
    return pygit2.Repository(str(repo_path))[commit].tree[path].data.decode("utf-8")


def commit_at(repo_path: Path, commit: str) -> pygit2.Commit:
    return pygit2.Repository(str(repo_path))[commit]


def save(client: httpx.Client, entity_id: str, fields: dict, *, base=None, body=None):
    """One Save is one PATCH is one commit. Only the touched fields travel."""
    return client.patch(
        f"/api/entity/{entity_id}",
        json={"base_commit": base or head(client), "fields": fields, "body": body},
    )


def create(client: httpx.Client, fields: dict, *, base=None, body=None):
    return client.post(
        "/api/entity",
        json={"base_commit": base or head(client), "fields": fields, "body": body},
    )


def index_of(client: httpx.Client) -> dict:
    return client.get("/api/index.json").json()


# --------------------------------------------------------------------------- #
# 1. Reads, which need no login and are the same pages Phase 1 shipped
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "route", ["/", f"/detail/{TASK}", "/detail", "/graph", "/timeline"]
)
def test_every_view_is_served_as_a_page(client: TestClient, route: str):
    response = client.get(route)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lstrip().startswith("<!doctype html>")


def test_the_table_renders_the_repository_as_it_is_right_now(client: TestClient):
    """Served from the live index, not from a `derived/` directory checked in
    yesterday: the one blocker in the corpus has to be counted here."""
    body = client.get("/").text

    assert "Reproduce the 2-GPU equator artefact" in body
    assert "Downgrade numpy for global sums" in body
    assert '<table id="rows"' in body
    assert 'id="blocker-count">1<' in body  # task-c00003 is done with no PRs


def test_a_served_page_navigates_by_route_and_not_by_filename(client: TestClient):
    """The static build links `graph.html`; a served page must link `/graph`.

    Left alone this is the failure where every link in the header 404s, which is
    both the first thing anybody clicks and the kind of bug that survives a demo
    because the author always lands on the page they were working on. The `.html`
    check covers the links the page's JavaScript builds as well, which is where
    the detail links live.
    """
    for route in ("/", "/detail", "/graph", "/timeline"):
        body = client.get(route).text
        assert not re.search(r'href="[^"]*\.html', body), route
        assert 'href="/graph"' in body, route


def test_a_detail_route_serves_one_entity_and_not_the_whole_corpus(client: TestClient):
    """A shareable per-entity URL is the point of the route existing at all; a
    page that ships every entity and hides all but one with JavaScript is the
    static build, and it is what this route replaces."""
    body = client.get(f"/detail/{TASK}").text

    assert "Reproduce the 2-GPU equator artefact" in body
    assert "the serialbox reference data" in body  # the shaping doc, rendered
    assert "Downgrade numpy for global sums" not in body


def test_an_entity_that_does_not_exist_is_a_404_and_not_an_empty_page(client: TestClient):
    assert client.get("/detail/task-ffffff").status_code == 404


def test_the_graph_still_carries_its_libraries_inline(client: TestClient):
    """Serving the pages must not turn them back into pages that fetch from a CDN.

    The libraries are vendored under `static/` precisely so the tool works on a
    train and cannot be broken by somebody else's outage; a `<script src=...>`
    reintroduced here would be invisible until the day it mattered.
    """
    body = client.get("/graph").text

    assert "cytoscape" in body
    assert not re.search(r"<script[^>]+src\s*=", body)


def test_healthz_reports_the_commit_being_served(client: TestClient, repo_path: Path):
    """`head` is what a deploy check and a stale-tab check both read. It has to be
    the commit on disk, not a value the process cached at startup — somebody will
    push to this repository from a terminal in week one."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "head": git_head(repo_path)}

    save(client, TASK, {"priority": 1})
    assert head(client) == git_head(repo_path)


def test_the_index_json_carries_the_entities_the_spans_and_the_problems(client: TestClient):
    """The whole snapshot, so a client can render a view without a second request.

    Spans and problems are both derived and neither is stored, so this is also the
    assertion that the server is running the scheduler and the validator rather
    than echoing the files back.
    """
    payload = index_of(client)

    assert set(payload["entities"]) == {PROJECT, PITCH, TASK, OTHER, DONE}
    assert payload["entities"][TASK]["title"] == "Reproduce the 2-GPU equator artefact"
    assert payload["entities"][TASK]["status"] == "wip"

    span = payload["spans"][TASK]
    assert span["start"] <= span["end"]

    problems = payload["problems"]
    assert {"severity": "blocker", "entity_id": DONE, "field": "prs"} in [
        {k: p[k] for k in ("severity", "entity_id", "field")} for p in problems
    ]


def test_the_index_json_keeps_the_fields_only_a_pitch_or_a_task_has(client: TestClient):
    """A size that is `null` on every row is the whole timeline, silently gone.

    `Index.entities` is annotated `dict[str, Entity]`, and pydantic serialises by
    the declared type, so a plain `model_dump` drops `appetite_weeks` and
    `effort_weeks` — it warns rather than raises, which is the worst of both. The
    payload has to carry the subclasses as they actually are.
    """
    entities = index_of(client)["entities"]

    assert entities[TASK]["effort_weeks"] == 1.5
    assert entities[PITCH]["appetite_weeks"] == 3


def test_a_rule_newer_than_the_entity_reaches_the_client_as_a_warning(client: TestClient):
    """Grandfathering has to survive the trip through JSON, or the web view
    re-invents the rule that made adding a required field invalidate the whole
    repository at once. The pitch predates the `shaped_by` rule, so it warns."""
    problems = index_of(client)["problems"]
    shaped_by = [p for p in problems if p["entity_id"] == PITCH and p["field"] == "shaped_by"]

    assert [p["severity"] for p in shaped_by] == ["warning"]


# --------------------------------------------------------------------------- #
# 2. The write path
# --------------------------------------------------------------------------- #


def test_a_save_against_the_current_head_is_committed(client: TestClient, repo_path: Path):
    base = head(client)
    response = save(client, TASK, {"priority": 1}, base=base)

    assert response.status_code == 200
    assert response.json()["outcome"] == "committed"
    assert response.json()["conflict"] is None

    commit = response.json()["commit"]
    assert git_head(repo_path) == commit
    assert str(commit_at(repo_path, commit).parents[0].id) == base
    assert index_of(client)["entities"][TASK]["priority"] == 1


def test_the_commit_author_is_the_signed_in_user(client: TestClient, repo_path: Path):
    """`git log --format='%an'` is the audit trail, and the author/committer split
    is what keeps a future push credential a bot no human's departure invalidates.
    The message names the entity so the log reads as a plan, not as a diff."""
    commit = save(client, TASK, {"priority": 1}).json()["commit"]

    written = commit_at(repo_path, commit)
    assert written.author.name == "ann"
    assert written.committer.name == "openproj-bot"
    assert written.message.startswith(f"{TASK}: ")


def test_the_author_can_never_be_supplied_by_the_client(client: TestClient, repo_path: Path):
    """The audit trail is worth exactly as much as this. A header, a query
    parameter or a body field claiming to be somebody else has to change nothing
    at all — the session is the only source of the name."""
    response = client.patch(
        f"/api/entity/{TASK}?author=mallory",
        json={"base_commit": head(client), "fields": {"priority": 1}, "body": None},
        headers={"X-Author": "mallory"},
    )

    assert response.status_code == 200
    assert commit_at(repo_path, response.json()["commit"]).author.name == "ann"


def test_a_saved_body_replaces_the_body_and_nothing_else(client: TestClient, repo_path: Path):
    response = save(client, TASK, {}, body="Reproduced on daint with two ranks.\n")

    assert response.json()["outcome"] == "committed"
    stored = file_at(repo_path, response.json()["commit"], PATH)
    assert stored.endswith("Reproduced on daint with two ranks.\n")
    assert "priority: 2" in stored  # the frontmatter is untouched by a body edit


def test_a_stale_base_whose_file_nobody_touched_is_retried_silently(
    client: TestClient, repo_path: Path
):
    """Two people editing two different entities is ~95% of collisions, and it is
    the case that has to be invisible. A person who held a tab open while somebody
    else saved a different task must not be shown anything at all."""
    stale = head(client)
    theirs = save(client, OTHER, {"priority": 1}).json()["commit"]

    response = save(client, TASK, {"priority": 1}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "retried"
    assert response.json()["conflict"] is None
    assert str(commit_at(repo_path, response.json()["commit"]).parents[0].id) == theirs
    assert index_of(client)["entities"][OTHER]["priority"] == 1  # not clobbered
    assert index_of(client)["entities"][TASK]["priority"] == 1


def test_two_people_changing_different_fields_of_one_entity_are_merged(client: TestClient):
    """Field-level, not file-level: they set the status while I set the priority is
    not a disagreement, and refusing it teaches people to keep their editors shut."""
    stale = head(client)
    save(client, TASK, {"owner": "bo"})

    response = save(client, TASK, {"priority": 1}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "merged"
    entity = index_of(client)["entities"][TASK]
    assert (entity["owner"], entity["priority"]) == ("bo", 1)


def test_a_genuine_collision_is_a_409_that_writes_nothing(client: TestClient, repo_path: Path):
    """The real disagreement, and the only one the person is allowed to be
    interrupted by. Nothing is committed, HEAD does not move, and the refusal
    carries a rendered conflict naming both values so the client can offer keep
    mine / keep theirs without going back to the server to find out what theirs is.

    The 409 body is still a WriteResult. A client that has to parse one shape on
    success and another on refusal grows a branch, and the branch is where the
    conflict gets dropped on the floor.
    """
    stale = head(client)
    theirs = save(client, TASK, {"owner": "bo"}).json()["commit"]

    response = save(client, TASK, {"owner": "cy"}, base=stale)

    assert response.status_code == 409
    assert response.json()["outcome"] == "conflict"
    assert response.json()["commit"] is None

    conflict = response.json()["conflict"]
    assert "bo" in conflict and "cy" in conflict
    assert git_head(repo_path) == theirs
    assert index_of(client)["entities"][TASK]["owner"] == "bo"


def test_no_conflict_marker_ever_reaches_the_browser(client: TestClient):
    """A `<<<<<<<` in the response is a `<<<<<<<` in a textarea, and then somebody
    presses Save and the markers are in the corpus for good."""
    stale = head(client)
    save(client, TASK, {"owner": "bo"}, body="Their line.\n")

    response = save(client, TASK, {"owner": "cy"}, base=stale, body="My line.\n")

    assert response.status_code == 409
    assert not [m for m in ("<<<<<<<", "=======", ">>>>>>>") if m in response.text]


def test_saving_an_entity_that_does_not_exist_is_a_404(client: TestClient, repo_path: Path):
    """A well-formed id for a file that is not there. `PATCH` edits; it does not
    quietly create, or a typo in a URL becomes an entity nobody meant to make."""
    base = git_head(repo_path)
    response = save(client, "task-ffffff", {"priority": 1}, base=base)

    assert response.status_code == 404
    assert git_head(repo_path) == base


# --------------------------------------------------------------------------- #
# 3. The round trip
# --------------------------------------------------------------------------- #


def test_a_partial_save_changes_only_the_lines_it_was_asked_to(
    client: TestClient, repo_path: Path
):
    """The round-trip promise, asserted line by line against what git stores.

    A save that reorders keys, drops a comment, restyles a list or reflows the
    body makes "edit it in git if you prefer" a lie after the first web edit, and
    it also makes every subsequent diff unreadable — which is the same failure
    twice, because the git history *is* the audit trail.

    Comparing the whole file line-for-line rather than spot-checking is deliberate:
    it pins the leading comment, the blank line inside the frontmatter, the
    hand-chosen key order, the inline comment, both flow-style lists and the body
    in one assertion, and it fails loudly rather than partially.
    """
    base = head(client)
    before = file_at(repo_path, base, PATH)
    assert before == HAND_FORMATTED  # the seed is what a person wrote

    commit = save(client, TASK, {"priority": 1}, base=base).json()["commit"]
    after = file_at(repo_path, commit, PATH)

    assert len(after.splitlines()) == len(before.splitlines())
    assert [
        (was, now)
        for was, now in zip(before.splitlines(), after.splitlines(), strict=True)
        if was != now
    ] == [("priority: 2", "priority: 1")]


def test_a_field_the_client_did_not_send_is_not_rewritten(client: TestClient, repo_path: Path):
    """Only the touched fields travel, which is what makes field-level merge
    possible at all. A client that round-trips the whole entity turns every save
    into a whole-file compare-and-swap and every concurrent edit into a conflict."""
    commit = save(client, TASK, {"status": "done", "prs": ["C2SM/icon4py#412"]}).json()["commit"]
    stored = file_at(repo_path, commit, PATH)

    assert "effort_weeks: 1.5          # measured on daint, not guessed" in stored
    assert "owner: ann                 # ann has the DWD contacts" in stored
    assert "reviewers: [bo, cy]" in stored  # still one line, still flow style
    assert "assignees" not in stored  # an untouched default is not materialised


# --------------------------------------------------------------------------- #
# 4. Creation, where the required fields actually bite
#
# Roughly every entity is born here, so this is the enforcement point that
# decides whether the corpus is worth reading. CI and the index gate catch what
# gets past it; nothing catches what this lets through.
# --------------------------------------------------------------------------- #


VALID_TASK = {
    "kind": "task",
    "title": "Per-field delta tolerances",
    "parent": PITCH,
    "status": "todo",
    "owner": "ann",
    "reviewers": ["bo"],
    "effort_weeks": 1.0,
}


def test_a_create_mints_the_id_and_files_it_by_kind(client: TestClient, repo_path: Path):
    """The client never chooses the path, and never chooses the id.

    An id supplied by the browser is a path supplied by the browser once it has
    been turned into `tasks/<id>.md`, and the writable surface of the repository
    stops being a closed set. Minting it server-side also means the id is unique
    without a round trip to ask.
    """
    response = create(client, VALID_TASK, body="Compare per field, not per file.\n")

    assert response.status_code == 201
    assert response.json()["outcome"] == "committed"

    new_id = response.json()["id"]
    assert re.fullmatch(r"task-[0-9a-f]{6}", new_id)

    stored = file_at(repo_path, response.json()["commit"], f"tasks/{new_id}.md")
    assert f"id: {new_id}" in stored
    assert stored.endswith("Compare per field, not per file.\n")
    assert index_of(client)["entities"][new_id]["title"] == "Per-field delta tolerances"


def test_a_create_missing_its_status_gated_fields_is_refused(
    client: TestClient, repo_path: Path
):
    """Every blocker for the status being asked for, in one answer.

    Refusing on the first missing field would make creating one task a
    four-request conversation, which is how a form teaches people to pick the
    status with the fewest rules. 422 rather than 400: the request was understood
    perfectly, and it is the plan that says no.

    Only blockers travel in a refusal. This create also earns the unparented-task
    warning, and a warning listed beside the reasons is indistinguishable from one
    — the person fixes it, resubmits, and learns the messages are noise.
    """
    base = head(client)
    response = create(client, {"kind": "task", "title": "A half-formed idea", "status": "todo"})

    assert response.status_code == 422
    assert {p["field"] for p in response.json()["problems"]} >= {
        "owner",
        "reviewers",
        "effort_weeks",
    }
    assert {p["severity"] for p in response.json()["problems"]} == {"blocker"}
    assert git_head(repo_path) == base  # nothing was written


def test_a_create_is_not_refused_over_a_warning(client: TestClient):
    """An unparented task is a warning, not a blocker: the first real chore we
    tried to record belonged to no pitch, and inventing a parent to satisfy the
    validator is falsifying the plan to please the tool."""
    response = create(client, {**VALID_TASK, "parent": None})

    assert response.status_code == 201
    new_id = response.json()["id"]
    warnings = [p for p in index_of(client)["problems"] if p["entity_id"] == new_id]
    assert [(p["severity"], p["field"]) for p in warnings] == [("warning", "parent")]


def test_a_new_entity_is_held_to_the_current_rules(client: TestClient, repo_path: Path):
    """Grandfathering protects the corpus that already exists, not the entity being
    created right now. The seeded pitch only warns about `shaped_by`; a pitch
    created today is created at the repository's `schema_version` and is blocked
    without it. This is the mechanism working end to end rather than in a unit
    test, and it is the reason a required field can ever be added at all."""
    base = head(client)
    response = create(
        client,
        {
            "kind": "pitch",
            "title": "Turbulence on one node",
            "status": "todo",
            "owner": "ann",
            "reviewers": ["bo"],
            "appetite_weeks": 6,
        },
    )

    assert response.status_code == 422
    assert [p["field"] for p in response.json()["problems"]] == ["shaped_by"]
    assert git_head(repo_path) == base


def test_a_create_records_its_author_like_any_other_write(client: TestClient, repo_path: Path):
    response = create(client, VALID_TASK)

    assert commit_at(repo_path, response.json()["commit"]).author.name == "ann"


# --------------------------------------------------------------------------- #
# 5. Writes are gated, reads are not
#
# The two checks are different checks and both are required: the one at
# /auth/callback decides what to put in the cookie, the one here decides whether
# to act on it. A server holding only the first is open to every GitHub user
# alive, and it looks completely correct while it is.
# --------------------------------------------------------------------------- #


def test_the_content_stays_public_when_nobody_is_signed_in(secure_client: TestClient):
    """Reads need no login, by decision. Putting the plan behind the org would
    make it unlinkable from an issue, which is where most people meet it."""
    for route in ("/", "/detail", "/graph", "/timeline", "/api/index.json", "/healthz"):
        assert secure_client.get(route).status_code == 200, route


def test_an_anonymous_visitor_cannot_write(secure_client: TestClient, repo_path: Path):
    base = git_head(repo_path)

    assert save(secure_client, TASK, {"priority": 1}).status_code == 401
    assert create(secure_client, VALID_TASK).status_code == 401
    assert git_head(repo_path) == base


def test_a_signed_in_non_member_is_refused_at_the_write(
    secure_client: TestClient, repo_path: Path
):
    """The one that matters. Mallory authenticated with GitHub perfectly well and
    holds a cookie this server signed itself — the only thing standing between her
    and the corpus is that the write endpoint asks about membership again, from
    the session, on every request.

    401 and 403 are kept apart on purpose: the first means "sign in", the second
    means "signing in again will not help", and a client that shows a login button
    to somebody who is not in the org sends them round a loop forever.
    """
    secure_client.cookies.set(SESSION_COOKIE, sign_session(MALLORY, SECRET))
    base = git_head(repo_path)

    assert save(secure_client, TASK, {"priority": 1}).status_code == 403
    assert create(secure_client, VALID_TASK).status_code == 403
    assert git_head(repo_path) == base
    assert secure_client.get("/").status_code == 200  # still a reader


def test_a_member_writes_as_themselves(secure_client: TestClient, repo_path: Path):
    """The gate has to open, too — a check nobody can pass is indistinguishable
    from a check that is broken, and this is what tells the two apart."""
    secure_client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))

    response = save(secure_client, TASK, {"priority": 1})

    assert response.status_code == 200
    assert commit_at(repo_path, response.json()["commit"]).author.name == "ann"


def test_a_cookie_this_server_did_not_sign_is_nobody(secure_client: TestClient):
    """Anyone can put anything in a cookie jar. A forged or stale session is a
    clean logged-out state — a 401, never a 500, and never a member."""
    forged = sign_session(User(login="mallory", member=True), "some-other-secret")
    secure_client.cookies.set(SESSION_COOKIE, forged)

    assert save(secure_client, TASK, {"priority": 1}).status_code == 401
    assert secure_client.get("/").status_code == 200


def test_logging_out_ends_the_ability_to_write(secure_client: TestClient):
    """Two properties, asserted separately, because the client's cookie jar cannot
    model the third.

    `httpx` keeps a cookie injected with `cookies.set` in a different slot from one
    delivered by `Set-Cookie`, so a correct domain-scoped deletion leaves the
    injected copy behind — an artefact of the jar, not of the server. What the
    server owes is that logout *instructs* the browser to clear the session, and
    that a request arriving without one cannot write. Both are checked here; a real
    browser joins them up.
    """
    secure_client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
    assert save(secure_client, TASK, {"priority": 1}).status_code == 200

    response = secure_client.post("/logout", follow_redirects=False)
    assert response.status_code in (200, 204, 303)
    cleared = response.headers["set-cookie"]
    assert cleared.startswith(f'{SESSION_COOKIE}=""')
    assert "Max-Age=0" in cleared
    assert "Path=/" in cleared

    secure_client.cookies.clear()
    assert save(secure_client, TASK, {"priority": 1}).status_code == 401


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param({}, id="the-default-signing-secret"),
        pytest.param({"secret": SECRET, "client_secret": ""}, id="no-client-secret"),
        pytest.param({"secret": SECRET, "client_id": ""}, id="no-client-id"),
    ],
)
def test_github_mode_refuses_to_start_on_a_development_default(repo_path: Path, settings: dict):
    """The defaults in `create_app` exist so tests can call it with one argument,
    and that is exactly the kind of thing that reaches production quietly. A
    server signing sessions with `dev-secret` is a server anybody can mint a
    member cookie for, so it has to die at startup rather than at the first write.
    """
    with pytest.raises(ValueError):
        create_app(
            repo_path,
            auth="github",
            org=ORG,
            **{"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **settings},
        )


# --------------------------------------------------------------------------- #
# 6. The login handshake
#
# The token exchange itself is `openproj.auth`'s contract and is tested there.
# What only the server can own is the state: generating one, binding it to this
# browser, and refusing a callback that does not carry it back.
# --------------------------------------------------------------------------- #


def test_login_binds_a_fresh_state_to_the_browser(secure_client: TestClient):
    """State in the URL alone is not CSRF protection — it has to be in a cookie
    too, or there is nothing to compare the echo against. SameSite=Lax rather than
    Strict because the callback is a top-level cross-site GET: Strict drops the
    cookie and every single login fails.
    """
    response = secure_client.get("/login", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert query["scope"] == ["read:org"]  # never `repo`, not even once
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"][0].endswith("/auth/callback")
    assert query["state"][0]

    # Lower-cased because cookie attribute values are case-insensitive and
    # Starlette writes `SameSite=lax`; asserting the spelling would fail a
    # correct implementation for no reason.
    cookie = response.headers["set-cookie"].lower()
    assert STATE_COOKIE.lower() in cookie
    assert "httponly" in cookie and "samesite=lax" in cookie

    second = secure_client.get("/login", follow_redirects=False)
    other = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
    assert other != query["state"][0]  # a reused state is not a nonce


def test_a_callback_whose_state_does_not_match_is_abandoned(secure_client: TestClient):
    """GitHub's own words: if the states do not match, a third party created the
    request and the process should be aborted. Aborted means before the exchange —
    the code is never sent anywhere, so this test needs no network to prove it."""
    secure_client.get("/login", follow_redirects=False)

    response = secure_client.get(
        "/auth/callback?code=e72e16c7e42f292c6912&state=not-the-one-we-issued",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert save(secure_client, TASK, {"priority": 1}).status_code == 401


# --------------------------------------------------------------------------- #
# 7. The writable surface is a closed set
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entity_id",
    [
        "../config/defaults",
        "..%2F..%2Fconfig%2Fdefaults",
        "task-c00001%2F..%2F..%2Fconfig%2Fdefaults",
        "tasks%2Ftask-c00001",
        "task-zzzzzz",
        "task-c0001",
        "not-an-id",
        "",
    ],
)
def test_an_id_that_is_not_an_id_never_becomes_a_path(
    client: TestClient, repo_path: Path, entity_id: str
):
    """The id is admitted against `^(proj|pitch|task)-[0-9a-f]{6}$` before anything
    is concatenated, and the kind comes from its prefix rather than from the body.
    That makes `projects|pitches|tasks/<id>.md` the entire writable surface of the
    repository by construction rather than by libgit2's good manners — which
    matters here more than usual, because branch protection means a bad write
    cannot be force-pushed away afterwards.
    """
    base = git_head(repo_path)
    before = file_at(repo_path, base, "config/defaults.yaml")

    response = client.request(
        "PATCH",
        f"/api/entity/{entity_id}",
        json={"base_commit": base, "fields": {"owner": "mallory"}, "body": "pwned\n"},
    )

    assert response.status_code in (400, 404, 405)
    assert git_head(repo_path) == base
    assert file_at(repo_path, base, "config/defaults.yaml") == before


def test_a_create_cannot_choose_its_own_kind_of_directory(client: TestClient, repo_path: Path):
    """`kind` is a closed set of three, and it is the only thing that picks the
    directory. Anything else is a 422 before a path is built."""
    base = git_head(repo_path)
    response = create(client, {**VALID_TASK, "kind": "../config"})

    assert response.status_code == 422
    assert git_head(repo_path) == base


def test_an_oversized_body_is_refused_at_the_door(client: TestClient, repo_path: Path):
    """Starlette does not bound a request body and Cloud Run will carry 32 MB of
    it. A blob committed to git is permanent, and branch protection blocks the
    force-push that would be needed to take it back out, so the only place this
    can be stopped is before the commit."""
    base = git_head(repo_path)
    response = save(client, TASK, {}, base=base, body="x" * 2_000_000)

    assert response.status_code == 413
    assert git_head(repo_path) == base


# --------------------------------------------------------------------------- #
# 8. Events
#
# Server-Sent Events, not WebSockets: the traffic is one-way, it survives a
# proxy, and it reconnects by itself. This is cache invalidation for other
# people's tabs, which is the whole reason a shared plan can be trusted after
# somebody else edits it.
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_server(repo_path: Path):
    """A real uvicorn on a real socket, which this one test needs.

    Starlette's `TestClient` runs the application to completion and buffers the
    whole body before it hands back a response, so `client.stream()` over an
    endless event stream never returns — the test would hang rather than fail.
    Reading the stream over a socket is also the honest test: chunked transfer
    and the absence of buffering are properties of the server, not of the
    generator, and they are exactly what breaks SSE in practice.

    The lock in `store.py` is per-repository, so this owns the whole repository
    for the duration and no other client fixture may be used beside it.
    """
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(repo_path, auth="dev", secret=SECRET),
            host="127.0.0.1",
            port=0,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn never came up"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_write_is_broadcast_to_everybody_watching(live_server: str):
    """The stream is opened before the write, because an event emitted into a
    stream nobody is holding yet is precisely the bug this is here to catch.

    The event names the commit and what changed, so a listener can refresh one
    row rather than reloading the page and throwing away the filter the person
    had set — which is the difference between live data and an interruption.
    """
    cookies = {SESSION_COOKIE: sign_session(ANN, SECRET)}
    seen: queue.Queue[str] = queue.Queue()

    with (
        httpx.Client(base_url=live_server, cookies=cookies, timeout=15) as watcher,
        httpx.Client(base_url=live_server, cookies=cookies, timeout=15) as writer,
    ):

        def listen() -> None:
            with watcher.stream("GET", "/api/events") as response:
                seen.put(response.headers["content-type"])
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        seen.put(line)
                        return

        listener = threading.Thread(target=listen, daemon=True)
        listener.start()
        assert seen.get(timeout=15).startswith("text/event-stream")

        commit = save(writer, TASK, {"priority": 1}).json()["commit"]

        event = json.loads(seen.get(timeout=15).partition(":")[2])
        listener.join(timeout=15)

    assert event["commit"] == commit
    assert event["changed"] == [TASK]


def test_an_entity_whose_filename_carries_a_slug_is_still_found(
    client: TestClient, repo_path: Path
):
    """Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    the path has to be looked up rather than reconstructed. Guessing `<id>.md`
    passes against a corpus nobody has ever renamed and fails against every real
    one — which is exactly how this shipped and then broke on first contact.
    """
    slugged = "tasks/task-d40000--a-title-someone-wrote.md"
    commit_directly(
        repo_path,
        {**SEED, slugged: SEED[PATH].replace(TASK, "task-d40000")},
        "add an entity filed under its slug",
    )

    response = save(client, "task-d40000", {"priority": 1})

    assert response.status_code == 200
    assert response.json()["outcome"] == "committed"
    assert "priority: 1" in file_at(repo_path, response.json()["commit"], slugged)
