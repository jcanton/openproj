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

import base64
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
status: in_progress
effort_weeks: 1.5          # measured on daint, not guessed

id: task-c00001
parent: pitch-b20000
owner: ann                 # ann has the DWD contacts
reviewers: [bo, cy]
assigned_on: 2026-07-06
priority: medium
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
    # Present so that a server which fails to read it is caught. It was not, and
    # the roster check was off in the browser for as long as this file was absent.
    "config/people.yaml": "known_people: [ann, bo, cy]\n",
    f"projects/{PROJECT}.md": (
        "---\n"
        "id: proj-a10000\n"
        "kind: project\n"
        "title: Distributed driver\n"
        "status: in_progress\n"
        "owner: ann\n"
        "reviewers: [bo]\n"
        "assigned_on: 2026-07-01\n"
        "priority: high\n"
        "---\n"
        "\nThe standalone driver, on more than one rank.\n"
    ),
    f"pitches/{PITCH}.md": (
        "---\n"
        "id: pitch-b20000\n"
        "kind: pitch\n"
        "title: Verify the tracer advection port\n"
        "parent: proj-a10000\n"
        "status: ready\n"
        "owner: ann\n"
        "reviewers: [bo]\n"
        "appetite_weeks: 3\n"
        "priority: high\n"
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
        "status: ready\n"
        "owner: bo\n"
        "reviewers: [ann]\n"
        "effort_weeks: 0.5\n"
        "priority: low\n"
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
    # Scoped to the article: other entities legitimately appear elsewhere on the
    # page now, in the autocomplete list for parent and depends_on. What must not
    # happen is a second entity being *served*.
    article = body.split("<article", 1)[1].split("</article>")[0]
    assert "Downgrade numpy for global sums" not in article
    assert body.count("<article") == 1


def test_an_entity_that_does_not_exist_is_a_404_and_not_an_empty_page(client: TestClient):
    assert client.get("/detail/task-ffffff").status_code == 404


@pytest.mark.parametrize(
    "route", ["/", f"/detail/{TASK}", "/detail", "/graph", "/timeline", "/people",
              "/cycles", "/new?kind=task"]
)
def test_no_page_declares_one_name_twice(client: TestClient, route: str):
    """Several `<script>` blocks, one global scope between them.

    The graph called the node you picked first `source` and the shell calls the
    event stream `source`; a second top-level declaration of a name is a
    SyntaxError that throws away the *whole* later script, so the plan-changed
    banner was dead on that one page and nowhere else. Nothing in the page says
    so — it fails silently, in the console, on one route.
    """
    from openproj.render import _static_dir

    # Only the scripts this app writes. The vendored bundles declare their own
    # names at column 0 inside their own module wrappers — cytoscape-dagre has
    # two `defaults` in two webpack modules — and they are not ours to police.
    # Matched by content rather than by size: the smallest of them is 12 KB.
    vendored = {
        (_static_dir() / name).read_text()
        for name in ("cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js")
    }
    ours = "\n".join(
        block
        for block in re.findall(r"<script[^>]*>(.*?)</script>", client.get(route).text, re.S)
        if block not in vendored
    )
    names = re.findall(r"^(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)", ours, re.M)
    twice = sorted({name for name in names if names.count(name) > 1})

    assert not twice, f"{route} declares {twice} more than once"


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

    save(client, TASK, {"priority": "high"})
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
    assert payload["entities"][TASK]["status"] == "in_progress"

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
    response = save(client, TASK, {"priority": "high"}, base=base)

    assert response.status_code == 200
    assert response.json()["outcome"] == "committed"
    assert response.json()["conflict"] is None

    commit = response.json()["commit"]
    assert git_head(repo_path) == commit
    assert str(commit_at(repo_path, commit).parents[0].id) == base
    assert index_of(client)["entities"][TASK]["priority"] == "high"


def test_the_commit_author_is_the_signed_in_user(client: TestClient, repo_path: Path):
    """`git log --format='%an'` is the audit trail, and the author/committer split
    is what keeps a future push credential a bot no human's departure invalidates.
    The message names the entity so the log reads as a plan, not as a diff."""
    commit = save(client, TASK, {"priority": "high"}).json()["commit"]

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
        json={"base_commit": head(client), "fields": {"priority": "high"}, "body": None},
        headers={"X-Author": "mallory"},
    )

    assert response.status_code == 200
    assert commit_at(repo_path, response.json()["commit"]).author.name == "ann"


def test_a_saved_body_replaces_the_body_and_nothing_else(client: TestClient, repo_path: Path):
    response = save(client, TASK, {}, body="Reproduced on daint with two ranks.\n")

    assert response.json()["outcome"] == "committed"
    stored = file_at(repo_path, response.json()["commit"], PATH)
    assert stored.endswith("Reproduced on daint with two ranks.\n")
    assert "priority: medium" in stored  # the frontmatter is untouched by a body edit


def test_a_stale_base_whose_file_nobody_touched_is_retried_silently(
    client: TestClient, repo_path: Path
):
    """Two people editing two different entities is ~95% of collisions, and it is
    the case that has to be invisible. A person who held a tab open while somebody
    else saved a different task must not be shown anything at all."""
    stale = head(client)
    theirs = save(client, OTHER, {"priority": "high"}).json()["commit"]

    response = save(client, TASK, {"priority": "high"}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "retried"
    assert response.json()["conflict"] is None
    assert str(commit_at(repo_path, response.json()["commit"]).parents[0].id) == theirs
    assert index_of(client)["entities"][OTHER]["priority"] == "high"  # not clobbered
    assert index_of(client)["entities"][TASK]["priority"] == "high"


def test_two_people_changing_different_fields_of_one_entity_are_merged(client: TestClient):
    """Field-level, not file-level: they set the status while I set the priority is
    not a disagreement, and refusing it teaches people to keep their editors shut."""
    stale = head(client)
    save(client, TASK, {"owner": "bo"})

    response = save(client, TASK, {"priority": "high"}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "merged"
    entity = index_of(client)["entities"][TASK]
    assert (entity["owner"], entity["priority"]) == ("bo", "high")


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
    response = save(client, "task-ffffff", {"priority": "high"}, base=base)

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

    commit = save(client, TASK, {"priority": "high"}, base=base).json()["commit"]
    after = file_at(repo_path, commit, PATH)

    assert len(after.splitlines()) == len(before.splitlines())
    assert [
        (was, now)
        for was, now in zip(before.splitlines(), after.splitlines(), strict=True)
        if was != now
    ] == [("priority: medium", "priority: high")]


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
    "status": "ready",
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
    response = create(client, {"kind": "task", "title": "A half-formed idea", "status": "ready"})

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
            "status": "ready",
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

    assert save(secure_client, TASK, {"priority": "high"}).status_code == 401
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

    assert save(secure_client, TASK, {"priority": "high"}).status_code == 403
    assert create(secure_client, VALID_TASK).status_code == 403
    assert git_head(repo_path) == base
    assert secure_client.get("/").status_code == 200  # still a reader


def test_a_member_writes_as_themselves(secure_client: TestClient, repo_path: Path):
    """The gate has to open, too — a check nobody can pass is indistinguishable
    from a check that is broken, and this is what tells the two apart."""
    secure_client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))

    response = save(secure_client, TASK, {"priority": "high"})

    assert response.status_code == 200
    assert commit_at(repo_path, response.json()["commit"]).author.name == "ann"


def test_a_cookie_this_server_did_not_sign_is_nobody(secure_client: TestClient):
    """Anyone can put anything in a cookie jar. A forged or stale session is a
    clean logged-out state — a 401, never a 500, and never a member."""
    forged = sign_session(User(login="mallory", member=True), "some-other-secret")
    secure_client.cookies.set(SESSION_COOKIE, forged)

    assert save(secure_client, TASK, {"priority": "high"}).status_code == 401
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
    assert save(secure_client, TASK, {"priority": "high"}).status_code == 200

    response = secure_client.post("/logout", follow_redirects=False)
    assert response.status_code in (200, 204, 303)
    cleared = response.headers["set-cookie"]
    assert cleared.startswith(f'{SESSION_COOKIE}=""')
    assert "Max-Age=0" in cleared
    assert "Path=/" in cleared

    secure_client.cookies.clear()
    assert save(secure_client, TASK, {"priority": "high"}).status_code == 401


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
    assert save(secure_client, TASK, {"priority": "high"}).status_code == 401


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

        commit = save(writer, TASK, {"priority": "high"}).json()["commit"]

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

    response = save(client, "task-d40000", {"priority": "high"})

    assert response.status_code == 200
    assert response.json()["outcome"] == "committed"
    assert "priority: high" in file_at(repo_path, response.json()["commit"], slugged)


def test_the_app_exposes_the_flag_that_ends_its_event_streams(repo_path: Path):
    """The runner sets this from uvicorn's own exit hook.

    uvicorn waits for in-flight requests and only then runs lifespan shutdown, so
    an event stream — a request that never ends by design — held Ctrl-C until the
    graceful timeout expired and the process died to a forced cancel. A signal
    handler installed by the app does not help either: uvicorn installs its own
    afterwards and replaces it. This flag is the seam, and a rename here without a
    matching one in `cli._serve` would quietly bring the hang back.
    """
    app = create_app(repo_path, auth="dev", secret=SECRET)

    assert hasattr(app.state, "closing")
    assert not app.state.closing.is_set()


def test_the_runner_sets_that_flag_when_it_is_told_to_exit(repo_path: Path):
    from openproj import cli

    app = create_app(repo_path, auth="dev", secret=SECRET)
    server = cli._exit_aware_server(app, host="127.0.0.1", port=0)
    server.handle_exit(15, None)

    assert app.state.closing.is_set()


# --- the timeline window is a URL -------------------------------------------


def test_a_timeline_view_is_a_link(client: TestClient):
    """Window and zoom live in the query string, so a view can be sent to somebody."""
    page = client.get("/timeline?from=2026-09-01&to=2026-09-30&zoom=14").text

    assert 'value="2026-09-01"' in page
    assert 'value="2026-09-30"' in page
    assert '<option value="14" selected>' in page


def test_a_nonsense_window_falls_back_instead_of_failing(client: TestClient):
    """These are typed as easily as picked, and a bookmark that 422s is a bug
    report about a URL somebody edited by hand."""
    for query in ("from=yesterday", "to=2026-13-01", "zoom=lots", "zoom=0", "from=x&to=y&zoom=z"):
        response = client.get(f"/timeline?{query}")
        assert response.status_code == 200, query
        assert "<svg" in response.text, query


def test_a_backwards_window_does_not_invert_the_drawing(client: TestClient):
    response = client.get("/timeline?from=2026-10-01&to=2026-01-01")

    assert response.status_code == 200
    assert 'width="-' not in response.text


def test_the_server_reads_the_same_config_the_cli_does(repo_path: Path):
    """The list was hardcoded here and had drifted: `people.yaml` was missing, so
    `known_people` was empty under `serve` and the roster check that rejects an
    unknown login was silently off in the browser while on in CI. Both now read
    `model.CONFIG_FILES`, so a fifth file cannot reach one and not the other."""
    from openproj import model
    from openproj.store import Store
    from openproj.web import _config_at

    store = Store(repo_path)
    served = _config_at(store, store.head())

    assert set(model.CONFIG_FILES) == {"defaults.yaml", "cycles.yaml",
                                       "holidays.yaml", "people.yaml"}
    assert served.known_people == ["ann", "bo", "cy"]


# --- cycle records ----------------------------------------------------------


def test_a_cycle_is_created_and_then_updated_in_place(client: TestClient, repo_path: Path):
    """PUT, not PATCH: a roster is written in one sitting, and a name that is
    missing means somebody was taken off rather than left alone."""
    base = git_head(repo_path)
    made = client.put(
        "/api/cycle/37",
        json={"base_commit": base, "fields": {
            "starts_on": "2026-08-17", "build_weeks": 4, "cooldown_weeks": 2,
            "availability": {"ann": 0.5, "bo": 1.0}}, "body": "## Goal\n\nShip it.\n"},
    )
    assert made.status_code == 200

    stored = file_at(repo_path, made.json()["commit"], "cycles/0037.md")
    assert "cycle: 37" in stored
    assert "ann: 0.5" in stored
    assert "Ship it." in stored

    smaller = client.put(
        "/api/cycle/37",
        json={"base_commit": made.json()["commit"],
              "fields": {"availability": {"ann": 0.5}}, "body": None},
    )
    assert smaller.status_code == 200
    assert "bo" not in file_at(repo_path, smaller.json()["commit"], "cycles/0037.md")


def test_a_cycle_the_server_could_not_read_back_is_never_committed(
    client: TestClient, repo_path: Path
):
    """Parsed before writing. A roster that fails to load would take every date on
    every page with it, and the file would already be in git."""
    before = git_head(repo_path)
    refused = client.put(
        "/api/cycle/37",
        json={"base_commit": before,
              "fields": {"starts_on": "2026-08-17", "availability": {"ann": "half"}},
              "body": None},
    )

    assert refused.status_code == 422
    assert "availability of ann" in refused.json()["detail"]
    assert git_head(repo_path) == before


def test_a_cycle_record_reaches_the_pages_it_is_for(client: TestClient, repo_path: Path):
    """The server loads `cycles/*.md` the same way the CLI does, so a record
    written through the API changes the dates the very next request."""
    base = git_head(repo_path)
    client.put(
        "/api/cycle/41",
        json={"base_commit": base,
              "fields": {"starts_on": "2026-11-02", "build_weeks": 4, "cooldown_weeks": 2},
              "body": None},
    )

    # Asked through the running server rather than by opening a second Store:
    # single-writer is enforced by a lock, so a second handle in the same process
    # is exactly the thing the lock exists to refuse.
    timeline = client.get("/timeline").text

    assert "cycle 41" in timeline


def test_the_cycle_page_shows_load_against_capacity(client: TestClient, repo_path: Path):
    """The number the team's own sheet does not have. Their HackMD records
    availability and staffing and never adds them up."""
    save(client, TASK, {"cycle": 37, "assignees": ["ann"], "effort_weeks": 3.0})
    client.put(
        "/api/cycle/37",
        json={"base_commit": git_head(repo_path), "fields": {
            "starts_on": "2026-08-17", "build_weeks": 4, "cooldown_weeks": 2,
            "availability": {"ann": 0.25}}, "body": None},
    )
    page = client.get("/cycle/37").text

    assert "Cycle 37" in page
    assert "builds until" in page
    assert re.search(r'data-login="ann"', page)
    assert "Over capacity" in page, "ann holds more than a quarter of four weeks"


def test_a_carried_item_cannot_be_re_stamped_from_the_cycle_page(
    client: TestClient, repo_path: Path
):
    """D-C1: `cycle` says where a thing was BET. Re-stamping an in-progress item
    into the current cycle moves the deadline its overrun is measured against and
    silently forgives the slip — at exactly the moment the slip is happening."""
    save(client, TASK, {"cycle": 36, "status": "in_progress",
                        "assigned_on": "2026-07-01"})
    client.put(
        "/api/cycle/40",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2026-10-19", "build_weeks": 4}, "body": None},
    )
    page = client.get("/cycle/40").text
    rows = re.findall(r'<tr data-id="([^"]+)" class="([^"]*)">.*?<input type="checkbox"'
                      r' class="bet"([^>]*)>', page, re.S)
    carried = [(i, attrs) for i, cls, attrs in rows if "carried" in cls]

    assert carried, "the fixture has in-progress work from an earlier cycle"
    for entity_id, attrs in carried:
        assert "disabled" in attrs, entity_id


def test_the_cycle_page_puts_the_forecast_next_to_the_capacity(client: TestClient):
    """A green bar beside a timeline running a month past the cycle is the failure
    that stops a room trusting the tool, and the two come from different
    subsystems. On one row they cannot quietly disagree."""
    page = client.get("/cycle/37").text

    assert "scheduled until" in page
    assert "<th>capacity</th>" in page


def test_only_the_named_are_in_a_cycle(client: TestClient, repo_path: Path):
    """Being on the roster is what being in the cycle means, so a name is added
    deliberately rather than appearing because somebody was assigned something —
    which would make the roster a report instead of a decision."""
    save(client, TASK, {"cycle": 44, "owner": "cy", "assignees": ["cy"],
                        "effort_weeks": 1.0})
    client.put(
        "/api/cycle/44",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2026-12-14", "build_weeks": 4,
                         "availability": {"ann": 1.0}},
              "body": None},
    )
    page = client.get("/cycle/44").text
    roster = re.findall(r'<tr data-login="([^"]+)"', page)

    assert roster == ["ann"], "cy holds work here but was never named"
    strangers = re.search(r'id="strangers">(.*?)</p>', page, re.S).group(1)
    assert "cy" in strangers, "work counted here by somebody the cycle does not name"


def test_the_bet_lists_what_to_pick_up_before_what_is_running(
    client: TestClient, repo_path: Path
):
    """Ready first, in progress after, by id inside each. What is already running
    is context at a betting table; what is ready is the question."""
    client.put(
        "/api/cycle/45",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-01-11", "build_weeks": 4}, "body": None},
    )
    page = client.get("/cycle/45").text
    rows = re.findall(r'<tr data-id="([^"]+)"[^>]*>.*?<td>(\w+)</td>\s*<td>(\w+)</td>',
                      page, re.S)
    statuses = [status for _, _, status in rows]

    assert set(statuses) <= {"ready", "in_progress"}
    assert statuses == sorted(statuses, key=["ready", "in_progress"].index)
    for status in ("ready", "in_progress"):
        ids = [i for i, _, s in rows if s == status]
        assert ids == sorted(ids)


# --- images -----------------------------------------------------------------

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M+AFzCOKhhVMKoA"
    "AI5CA/8Ehl9pAAAAAElFTkSuQmCC"
)


def upload(client: TestClient, data: bytes, kind: str = "image/png"):
    return client.post("/api/asset", content=data, headers={"content-type": kind})


def test_an_uploaded_image_is_named_by_its_contents(client: TestClient, repo_path: Path):
    """Content-addressed, so the same file twice is the same path and the second
    upload writes nothing. It is also why an asset needs none of the write path's
    machinery: it is never edited, so no conflict can exist."""
    first = upload(client, PNG)
    before = git_head(repo_path)
    second = upload(client, PNG)

    assert first.status_code == 200
    assert first.json()["fresh"] is True
    assert re.fullmatch(r"assets/[0-9a-f]{16}\.png", first.json()["path"])
    assert second.json()["path"] == first.json()["path"]
    assert second.json()["fresh"] is False
    assert git_head(repo_path) == before, "an identical upload writes nothing"


def test_an_uploaded_image_comes_back_byte_for_byte(client: TestClient):
    path = upload(client, PNG).json()["path"]
    served = client.get(f"/{path}")

    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert "immutable" in served.headers["cache-control"], "the name is the hash"


def test_the_upload_route_takes_images_and_nothing_else(client: TestClient):
    """No SVG in particular: it is a document that can carry script, and these are
    served from the same origin as the editor."""
    assert upload(client, PNG, "image/svg+xml").status_code == 415
    assert upload(client, b"#!/bin/sh\n", "text/x-shellscript").status_code == 415
    assert upload(client, b"", "image/png").status_code == 422
    assert upload(client, b"\x89PNG" + b"x" * (3 * 1024 * 1024)).status_code == 413


def test_an_asset_name_that_is_not_a_hash_never_becomes_a_path(client: TestClient):
    for name in ("../config/defaults.yaml", "..%2Fconfig", "nope.png", "abc.exe"):
        assert client.get(f"/assets/{name}").status_code == 404, name


def test_a_stored_image_is_drawn_and_a_remote_one_is_not(client: TestClient):
    """A remote image would make the page fetch from the network, which is what
    inlining every library was for. One in the repository travels with the clone
    and is served from this origin."""
    path = upload(client, PNG).json()["path"]
    save(client, TASK, {}, body=f"![a]({path})\n\n![b](https://example.com/b.png)\n")
    page = client.get(f"/detail/{TASK}").text

    assert f'<img src="/{path}"' in page
    assert "https://example.com/b.png" in page
    assert '<img src="https://example.com' not in page


def test_the_preview_shows_what_the_page_will_show(client: TestClient):
    """One transform, used by both. Written twice, the preview drew an uploaded
    image against the current URL — so a figure that renders on `/detail/task-x`
    was a broken image in the preview of that same document, which is the one
    place somebody checks it before saving. PR references were missing there too.
    """
    path = upload(client, PNG).json()["path"]
    body = f"![a]({path})\n\n![b](https://example.com/b.png)\n\nSee C2SM/icon4py#1364.\n"

    save(client, TASK, {}, body=body)
    previewed = client.post("/api/preview", json={"body": body}).json()["html"]
    stored = client.get(f"/detail/{TASK}").text

    assert f'<img src="/{path}"' in previewed
    assert f'<img src="/{path}"' in stored
    assert '<a href="https://example.com/b.png">b (external image)</a>' in previewed
    assert "https://github.com/C2SM/icon4py/pull/1364" in previewed


def test_the_preview_still_refuses_html(client: TestClient):
    """The rewrite runs after markdown, on markdown's own output — it must not
    become a way to get a tag past the renderer."""
    smuggled = client.post(
        "/api/preview",
        json={"body": '<script>alert(1)</script>\n\n<img src="assets/deadbeefdeadbeef.png">\n'},
    ).json()["html"]

    assert "<script>" not in smuggled
    assert "<img" not in smuggled
