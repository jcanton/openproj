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
#
# Enforce is the operative word, and it is why there are two names. The browser
# does not accept the prefix over plain HTTP at all, so a local run — where the
# whole team will meet this tool first — uses the bare one. Spelled out here
# rather than imported for the same reason as always: a test that imports the
# name it is checking agrees with the code by construction.
SESSION_COOKIE = "__Host-openproj_session"
SESSION_COOKIE_INSECURE = "openproj_session"
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
person_weeks: 1.5          # measured on daint, not guessed

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
        "person_weeks: 3\n"
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
        "person_weeks: 0.5\n"
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
        "person_weeks: 0.5\n"
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


def bet_rows(page: str) -> list[tuple[str, str, str]]:
    """(id, kind, status) per row of the betting table.

    Read off the chips rather than off bare cells: a chip is markup, and the
    regex that read `<td>ready</td>` did not fail when the cell grew one — it
    matched nothing and left three assertions passing over an empty list.
    """
    return re.findall(
        r'<tr data-id="([^"]+)"[^>]*>.*?<span class="chip kind-(\w+)">'
        r'.*?<span class="chip st-(\w+)">',
        page,
        re.S,
    )


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


def test_every_route_says_which_nav_item_it_is(client: TestClient):
    """Every route that serves a page, asked of the server and not of `_page`.

    Two of them are why this is a test about routes rather than about a template.
    `/cycle/37` and `/detail/task-c00001` are pages a reader reaches from the nav,
    and neither is the href of the link that got them there — an implementation
    that lit the item whose `href` matched the current URL would leave both of
    them dark, which is the state every page on this app was in before this round.

    `/new` marks nothing, on purpose: it is not one of the six, and pressing Table
    from it abandons the form rather than staying put. `render_new`'s docstring is
    where that is argued; this is where it is held.
    """
    from pages import lit

    for route, item in (
        ("/", "Table"),
        ("/graph", "Graph"),
        ("/timeline", "Timeline"),
        ("/cycles", "Cycles"),
        ("/cycle/37", "Cycles"),
        ("/people", "People"),
        ("/detail", "Detail"),
        (f"/detail/{TASK}", "Detail"),
    ):
        assert lit(client.get(route).text) == [item], route

    assert lit(client.get("/new?kind=task").text) == []


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


@pytest.mark.parametrize(
    "route", ["/", f"/detail/{TASK}", "/graph", "/cycles", "/cycle/1", "/new?kind=task"]
)
def test_every_write_a_page_makes_is_announced_before_and_after_it(
    client: TestClient, route: str
):
    """Otherwise the server's own news comes back as somebody else's.

    Every commit is broadcast to every tab including the one that made it, and the
    shell can only suppress its own by being told a write is in the air *before*
    it starts — the server announces to the stream before it answers the request.
    Two of five write paths did this; the other three, and the asset upload, did
    not, so pasting an image popped "The plan changed." over your own paste and
    nothing ever hid it again.

    Counted rather than spot-checked: the defect was a path nobody had thought
    about, so the assertion is about all of them at once.
    """
    body = client.get(route).text
    scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", body, re.S))

    # A write is a POST, PATCH or PUT. `/api/preview` renders markdown and commits
    # nothing, and `/api/index.json` is a GET.
    writes = [
        url
        for url, _ in re.findall(
            r"fetch\(\s*(`[^`]*`|'[^']*')[^)]*?method: '(POST|PATCH|PUT)'", scripts, re.S
        )
        if "/api/preview" not in url
    ]
    assert writes, route

    assert scripts.count("dispatchEvent(new Event('openproj:writing'));") == len(writes), (
        f"{route}: {writes}"
    )
    assert scripts.count("dispatchEvent(new CustomEvent('openproj:wrote'") == len(writes), (
        f"{route}: {writes}"
    )
    # In a `finally`, or one refusal holds every later event back forever and the
    # banner never appears again.
    assert scripts.count("} finally {") >= len(writes), route


def test_the_detail_page_says_which_entity_it_is_looking_at(client: TestClient):
    """The shell falls back to the last segment of the URL. That is the id on
    /detail/<id> and the word "detail" on the index view and on the static export,
    which holds every entity in one file — so a write to any of them read as a
    write to nothing and the banner said "The plan changed" about the very page
    in front of you."""
    one = client.get(f"/detail/{TASK}").text
    assert f'window.SHOWING = ["{TASK}"];' in one

    every = client.get("/detail").text
    showing = json.loads(re.search(r"window\.SHOWING = (\[.*?\]);", every).group(1))
    assert set(showing) == {PROJECT, PITCH, TASK, OTHER, DONE}


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


def test_the_health_check_is_reachable_at_a_path_that_is_ours(client: TestClient):
    """`/healthz` is not ours on Cloud Run. Google's frontend answers it with its
    own 404 page and the request never reaches the container — observed on the
    deployed service, where `/healthz` returned Google-branded HTML with no
    access-log line while an unrouted path on the same host returned this app's
    JSON 404. The one URL meant to prove the service is alive was the one that
    could not reach it.

    So the deployment checks `/api/health`, in a namespace this app owns and
    nothing in front of it claims. `/healthz` stays for a run behind anything
    else, and both must keep answering the same thing.
    """
    ours = client.get("/api/health")

    assert ours.status_code == 200
    assert ours.json() == client.get("/healthz").json()


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
    the declared type, so a plain `model_dump` drops `person_weeks` and
    `person_weeks` — it warns rather than raises, which is the worst of both. The
    payload has to carry the subclasses as they actually are.
    """
    entities = index_of(client)["entities"]

    assert entities[TASK]["person_weeks"] == 1.5
    assert entities[PITCH]["person_weeks"] == 3


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


@pytest.mark.parametrize("base", ["0" * 40, "not-a-sha", ""])
def test_a_base_this_repository_never_had_is_refused_rather_than_raised(
    client: TestClient, repo_path: Path, base: str
):
    """Every read here is at an explicit commit, and each one assumed it exists.

    A sha the repository has never seen reached `_tree` as `None.tree` and a
    string that is not hex reached it as a ValueError — a 500, in `text/plain`,
    which is the one answer the page cannot even read back to say what happened.

    It stopped being hypothetical when a restored draft started carrying the
    commit it was drafted against: that base is older than HEAD on purpose, so a
    draft left in a browser across a re-clone of the plan arrives here naming a
    commit nothing has. The draft is still in the browser, and the refusal says
    what to do with it.
    """
    was = git_head(repo_path)

    response = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": base, "fields": {"priority": "high"}, "body": None},
    )

    assert response.status_code == 422, response.text
    assert "copy anything unsaved" in response.json()["detail"]
    assert git_head(repo_path) == was


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

    assert "person_weeks: 1.5          # measured on daint, not guessed" in stored
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
    "person_weeks": 1.0,
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
        "person_weeks",
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
            "person_weeks": 6,
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


def test_a_stranger_is_told_so_without_an_error(secure_client: TestClient):
    """`/api/me` is asked on every page load, and every page here is readable
    signed out — so the signed-out answer is the ordinary one. A 401 would put a
    red line in the console of a page working exactly as designed, which is how a
    real error comes to be ignored.

    The org travels with it because "not a member" is only useful said of what.
    """
    answer = secure_client.get("/api/me")

    assert answer.status_code == 200
    assert answer.json() == {"org": ORG}


def test_the_corner_knows_a_member_from_somebody_who_only_signed_in(
    secure_client: TestClient,
):
    """The nav draws these two differently, and the difference is the whole point:
    Mallory has a valid session and cannot write. Saying so in the corner beats
    finding out at the moment of saving, which reads like the tool is broken."""
    secure_client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
    assert secure_client.get("/api/me").json() == {"login": "ann", "member": True, "org": ORG}

    secure_client.cookies.set(SESSION_COOKIE, sign_session(MALLORY, SECRET))
    answer = secure_client.get("/api/me").json()
    assert answer == {"login": "mallory", "member": False, "org": ORG}


def test_who_you_are_does_not_carry_a_token(secure_client: TestClient):
    """The session holds a login and a membership and nothing else, by design.
    This is the one place that hands the session back to a page, so it is the
    place where a credential added to `User` later would first get out."""
    secure_client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))

    body = secure_client.get("/api/me").text

    assert "token" not in body and "secret" not in body


def test_a_forged_cookie_is_a_stranger_in_the_corner(secure_client: TestClient):
    """The corner reads the same session the write gate does. If a forged cookie
    drew a name here it would say somebody is signed in who cannot write, and the
    tool would look broken rather than the cookie."""
    secure_client.cookies.set(
        SESSION_COOKIE, sign_session(User(login="mallory", member=True), "some-other-secret")
    )

    assert secure_client.get("/api/me").json() == {"org": ORG}


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
    # The name that can be stored on this connection, which over plain HTTP is
    # the bare one. A deletion aimed at the other name clears nothing.
    assert cleared.startswith(f'{SESSION_COOKIE_INSECURE}=""')
    assert "Max-Age=0" in cleared
    assert "Path=/" in cleared

    secure_client.cookies.clear()
    assert save(secure_client, TASK, {"priority": "high"}).status_code == 401


def test_a_session_cookie_is_one_a_browser_will_actually_store(secure_client: TestClient):
    """The bug this pair exists over: `__Host-` is a rule, not a hint.

    A `Set-Cookie` carrying that prefix without `Secure` is dropped by the browser
    with no warning and no error, and the response looks like it worked — so every
    local sign-in ended signed out. Over plain HTTP `Secure` cannot be sent, so
    the prefixed name cannot be used, and this asserts the two never come apart.
    """
    for header in (
        secure_client.get("/login", follow_redirects=False).headers.get("set-cookie", ""),
        secure_client.post("/logout", follow_redirects=False).headers.get("set-cookie", ""),
    ):
        assert "__Host-" not in header or "Secure" in header, header


def test_the_deployment_keeps_the_prefix_and_its_guarantee(repo_path: Path):
    """Over TLS the prefixed name comes back, with `Secure` and `Path=/` — which
    is what makes it a cookie no sibling host and no downgraded connection can
    have set. Losing that quietly is the other way this fix could go wrong."""
    app = create_app(
        repo_path,
        auth="github",
        org=ORG,
        secret=SECRET,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    with TestClient(app, base_url="https://openproj.example") as client:
        cleared = client.post("/logout", follow_redirects=False).headers["set-cookie"]

    assert cleared.startswith(f'{SESSION_COOKIE}=""')
    assert "Secure" in cleared and "Path=/" in cleared


def test_a_session_set_before_tls_is_still_a_session(repo_path: Path):
    """Both names are read. A server that used to be plain HTTP and is now behind
    TLS otherwise signs everybody out on the day it moves, for no reason a reader
    could work out from the page."""
    app = create_app(
        repo_path,
        auth="github",
        org=ORG,
        secret=SECRET,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    with TestClient(app, base_url="https://openproj.example") as client:
        client.cookies.set(SESSION_COOKIE_INSECURE, sign_session(ANN, SECRET))
        assert client.get("/api/me").json()["login"] == "ann"


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


def test_a_sign_in_somebody_cancelled_says_so(secure_client: TestClient):
    """Clicking Cancel on GitHub's authorize page sends the browser back here with
    an error and no code. Falling through to the exchange made that a bare
    "Internal Server Error", which cannot be told apart from a broken tool by the
    one person in a position to say which it was."""
    login = secure_client.get("/login", follow_redirects=False)
    state = login.headers["set-cookie"].split("op_state=")[1].split(";")[0]

    response = secure_client.get(
        f"/auth/callback?error=access_denied&error_description=The+user+has+denied&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


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
    served, unreadable = _config_at(store, store.head())

    assert set(model.CONFIG_FILES) == {"defaults.yaml", "cycles.yaml",
                                       "holidays.yaml", "people.yaml"}
    assert served.known_people == ["ann", "bo", "cy"]
    assert unreadable == []


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


# Every one of these is one gesture away in the browser: clear the date box, or
# type a word into build weeks — `Number('six')` is NaN and `JSON.stringify`
# sends NaN as null. All three reached `parse_cycle_text` and raised an
# unhandled ValidationError, which is a 500 whose body is not even JSON: the
# page could not report it, and its Save never came back.
@pytest.mark.parametrize(
    "fields, says",
    [
        ({"starts_on": "", "reviews_on": "2026-09-14"}, "starts_on"),
        ({"starts_on": "17/08/2026"}, "starts_on"),
        ({"starts_on": None}, "starts_on"),
        ({"starts_on": "2026-08-17", "reviews_on": None}, "reviews_on"),
        ({"starts_on": "2026-08-17", "reviews_on": ""}, "reviews_on"),
        # As the boxes send them: what was typed, so the refusal can quote it.
        ({"starts_on": "2026-08-17", "reviews_on": "the 4th"}, "'the 4th'"),
        # A review meeting before its own betting table is a cycle with no build
        # in it: every bet in it overruns by definition and its capacity is zero.
        ({"starts_on": "2026-08-17", "reviews_on": "2026-08-10"}, "not after"),
        ({"starts_on": "2026-08-17", "availability": {"ann": "nan"}}, "'nan'"),
        # Nothing names the missing field, so the catch-all around the parse is
        # what has to answer: a new cycle written with a roster and no date.
        ({"availability": {"ann": 0.5}}, "starts_on"),
    ],
)
def test_a_cycle_field_the_record_cannot_hold_is_refused_not_raised(
    client: TestClient, repo_path: Path, fields: dict, says: str
):
    before = git_head(repo_path)
    refused = client.put(
        "/api/cycle/62", json={"base_commit": before, "fields": fields, "body": None}
    )

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert says in detail, detail
    # A refusal writes nothing, and a refusal a person can act on says which box.
    assert git_head(repo_path) == before
    assert "\n" not in detail and "pydantic" not in detail, "a sentence, not a stack trace"


# The same eleven a member can send to the endpoint beside the cycle one, which
# had no parse-before-write at all. `_reject_bad_types` names numbers, lists and
# one bool; none of these is any of those, so every one returned 200 and
# committed — after which `/`, `/detail/<id>` and `/api/index.json` all answered
# 500, for everybody, permanently. It is a commit on a protected main, so it
# cannot be force-pushed away, and the only repair is a second crafted PATCH
# against the poisoning commit's sha, which the 500ing pages will not give you.
# Not reachable through the shipped UI, which is not a mitigation: it needs one
# deliberate request from any signed-in member.
@pytest.mark.parametrize(
    "field, value",
    [
        ("owner", {"a": 1}),
        ("owner", ["a", "b"]),
        ("title", {"a": 1}),
        ("title", 5),
        ("assigned_on", ""),
        ("assigned_on", "six"),
        ("assigned_on", 7),
        ("tags", [None]),
        ("tags", [{"a": 1}]),
        ("parent", 3),
        ("created_schema_version", "x"),
    ],
)
def test_an_entity_the_server_could_not_read_back_is_never_committed(
    client: TestClient, repo_path: Path, field: str, value: object
):
    """Parsed before writing, like the cycle beside it, and the pages prove it.

    A fresh repository per case — the fixture gives one — because the whole
    failure is that the bad value is *in git* afterwards, and a case that ran
    second in a poisoned repository could not tell a refusal from a repository
    that was already down.
    """
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": before, "fields": {field: value}, "body": None},
    )

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    # Which field, in the words on the screen: `str(ValidationError)` is four
    # lines and a documentation URL, and a person cannot act on that.
    assert field.split(".")[0] in detail, detail
    assert "\n" not in detail and "pydantic" not in detail, "a sentence, not a stack trace"

    assert git_head(repo_path) == before, "the refusal committed anyway"
    for route in ("/", f"/detail/{TASK}", "/api/index.json", "/graph", "/timeline"):
        assert client.get(route).status_code == 200, route


def test_an_entity_field_the_record_can_hold_is_still_written(
    client: TestClient, repo_path: Path
):
    """The other half: the check must refuse what cannot be read back and nothing
    else. A date, a list of tags and a title all still save."""
    saved = save(client, TASK, {"title": "A title", "assigned_on": "2026-09-01", "tags": ["gpu"]})

    assert saved.status_code == 200, saved.text
    assert index_of(client)["entities"][TASK]["assigned_on"] == "2026-09-01"


def test_a_date_the_record_can_hold_is_written_in_the_spelling_the_corpus_uses(
    client: TestClient, repo_path: Path
):
    """The other half of the same check: what passes is normalised, so a date
    that arrives in the compact ISO spelling is not stored in a second one.
    Quoted, because ruamel quotes what would otherwise load as a date — which is
    how every cycle this API has ever written is stored."""
    made = client.put(
        "/api/cycle/63",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "20260817", "build_weeks": 4}, "body": None},
    )

    assert made.status_code == 200, made.text
    assert "starts_on: '2026-08-17'" in file_at(repo_path, made.json()["commit"], "cycles/0063.md")


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
    save(client, TASK, {"cycle": 37, "assignees": ["ann"], "person_weeks": 3.0})
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
    # On the pitch, because that is where a bet is made: the task under it is
    # part of that bet and takes the cycle from it.
    save(client, PITCH, {"cycle": 36, "status": "in_progress",
                         "assigned_on": "2026-07-01"})
    save(client, TASK, {"status": "in_progress", "assigned_on": "2026-07-01"})
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


def test_the_bet_table_wears_no_class_the_page_cannot_draw(client: TestClient):
    """It carried `class="table-scroll"` against a stylesheet that has never held
    the rule — a class doing nothing, which reads to the next person as a layout
    they must not disturb.

    Wiring it would have been worse than leaving it inert: every appetite,
    assignees and reviewers box in this table opens a suggestion popup that
    `attachSuggest` inserts as the input's own next sibling, so an `overflow` on
    an ancestor cuts the list off against the bottom of the table on the last
    rows. A page that scrolls sideways is a nuisance; an autocomplete cut in half
    looks broken.
    """
    page = client.get("/cycle/37").text

    assert 'class="table-scroll"' not in page
    # The class still exists, on the one table with a sticky header to hold up.
    assert 'class="table-scroll"' in client.get("/").text
    assert re.search(r'<input class="live wide" data-field="assignees"[^>]*data-suggest', page), (
        "and this is the reason: the popups live inside the cells"
    )


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
    save(client, PITCH, {"cycle": 44})
    save(client, TASK, {"owner": "cy", "assignees": ["cy"], "person_weeks": 1.0})
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
    rows = bet_rows(page)
    statuses = [status for _, _, status in rows]

    assert statuses, "the fixture has work to bet"
    assert set(statuses) <= {"ready", "in_progress"}
    assert statuses == sorted(statuses, key=["ready", "in_progress"].index)
    for status in ("ready", "in_progress"):
        ids = [i for i, _, s in rows if s == status]
        assert ids == sorted(ids)


def test_the_bet_table_names_a_status_in_the_colour_every_other_page_uses(
    client: TestClient, repo_path: Path
):
    """One chip everywhere a status is named. The betting table said `in_progress`
    in the same ink as the title beside it, so the one column a room reads down
    was the one column with nothing to read down."""
    client.put(
        "/api/cycle/46",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-02-08", "build_weeks": 4}, "body": None},
    )
    page = client.get("/cycle/46").text
    rows = bet_rows(page)

    assert rows
    for entity_id, kind, status in rows:
        assert f'<span class="chip st-{status}">' in page, entity_id
        assert f'<span class="chip kind-{kind}">' in page, entity_id
    assert "In progress" in page or "in_progress" not in [s for _, _, s in rows]
    assert ">in_progress<" not in page, "the identifier is the class, never the word"


def test_every_cycle_the_plan_names_is_on_the_index(client: TestClient, repo_path: Path):
    """F25. The index listed the cycles with a record, which are the ones somebody
    has already thought about. A cycle holding work and holding no record is the
    one worth finding, and it was the one the page left out."""
    client.put(
        "/api/cycle/47",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-03-08", "build_weeks": 4,
                         "availability": {"ann": 1.0}}, "body": None},
    )
    save(client, PITCH, {"cycle": 48})
    save(client, TASK, {"owner": "bo", "assignees": ["bo"], "person_weeks": 2.0})
    page = client.get("/cycles").text
    cards = re.findall(r'<h2><a href="/cycle/(\d+)">Cycle \d+</a></h2>', page)

    assert cards == ["48", "47"], "newest first, record or not"
    # 2.5: bo's two weeks plus the half-week sibling task under the same pitch.
    # A cycle with no record still says what it is holding, which is the whole
    # reason it is on this list.
    assert re.search(r'>2\.5</b> weeks bet against\s+no roster', page), "48 holds work"


def test_a_cycle_card_says_the_bet_against_the_capacity(client: TestClient, repo_path: Path):
    """F25. `9.2 of 19.8 weeks bet` is the sentence the method turns on, and it
    was a fragment at the end of a bullet. The weeks counted are every week
    charged to the cycle, including work belonging to somebody the roster does
    not name — a cycle must never look emptier than it is."""
    client.put(
        "/api/cycle/49",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-04-05", "build_weeks": 4,
                         "availability": {"ann": 0.5}}, "body": None},
    )
    save(client, PITCH, {"cycle": 49})
    save(client, TASK, {"owner": "cy", "assignees": ["cy"], "person_weeks": 3.0})
    card = re.search(r'<li class="card([^"]*)">\s*<h2><a href="/cycle/49".*?</li>',
                     client.get("/cycles").text, re.S).group(0)

    # 3.5, not 3.0: betting the pitch bets everything under it, so cy's three
    # weeks and bo's half-week sibling task both land in the cycle. That is what
    # "the pitch is the unit of the bet" means for a capacity sum.
    assert "<b class=\"num\">3.5</b> of" in card, "cy is not on the roster and still counts"
    assert "<b class=\"num\">2.0</b> weeks bet" in card, "ann at half of four weeks"
    assert re.search(r'<span class="bar"><span style="width: 100%">', card)
    assert card.startswith('<li class="card over">'), "3.0 bet against 2.0 of capacity"


def test_the_create_form_is_not_another_cycle_in_the_list(client: TestClient):
    """F26. Four inputs and a button that writes a file sat at the same level as
    the list above them, with nothing between the two saying which was which."""
    page = client.get("/cycles").text

    assert '<section id="create">' in page
    assert "<h2>Start a cycle</h2>" in page
    assert "#create { border-top: 1px solid var(--line);" in page
    assert page.index('id="start"') > page.index('id="reviews"'), \
        "F15: the button follows the fields it commits"


def test_the_proposal_ignores_a_cycle_that_only_an_entity_mentions(
    client: TestClient, repo_path: Path
):
    """A cycle number on an entity is not a decision about when the next cycle
    starts, and the listing above this form actively invites betting into one that
    has no record.

    Unioning `entity.cycle` into the proposal made one such bet push the number
    past the last real cycle — and the number it landed on has no dates behind it,
    so the last cycle's end date was thrown away and the form offered "starts
    today". The listing still shows the bet cycle; only the proposal ignores it.
    """
    client.put(
        "/api/cycle/12",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-01-04", "build_weeks": 4,
                         "cooldown_weeks": 2, "availability": {"ann": 1.0}},
              "body": None},
    )
    save(client, TASK, {"cycle": 40})      # bet into a cycle nobody has written down
    page = client.get("/cycles").text

    assert '<input id="number" type="number" value="13"' in page, "after the last real one"
    # 2027-01-04 plus four build weeks and two of cool-down ends 2027-02-14.
    assert '<input id="starts" type="date" value="2027-02-15"' in page, \
        "the day the last recorded cycle ends, not today"

    assert '<a href="/cycle/40">Cycle 40</a>' in page, "the listing still names it"


def test_starting_a_cycle_asks_before_it_writes(client: TestClient):
    """F26. Starting a cycle writes a file and moves every date on every page
    that reads it, off one click beside four inputs somebody was just typing in."""
    page = client.get("/cycles").text
    reveal = re.search(r"START\.onclick = \(\) => \{.*?\n\};", page, re.S).group(0)
    commit = re.search(r"document\.getElementById\('yes'\)\.onclick = async \(\) => \{"
                       r".*?\n\};", page, re.S).group(0)

    assert "fetch(" not in reveal, "the first click asks, it does not write"
    assert "CONFIRM.hidden = false;" in reveal
    assert "confirm-number" in reveal, "the question names the cycle being started"
    assert "fetch(`/api/cycle/${number}`" in commit
    assert "document.getElementById('no').onclick" in page, "and a way to say no"


def test_the_glyph_that_takes_somebody_out_of_a_cycle_says_so_and_asks(
    client: TestClient, repo_path: Path
):
    """F26. An unlabelled bin next to the availability field, one click from
    removing a person and their capacity with them."""
    client.put(
        "/api/cycle/51",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-07-05", "build_weeks": 4,
                         "availability": {"ann": 1.0, "bo": 0.5}}, "body": None},
    )
    page = client.get("/cycle/51").text
    rows = re.findall(r'<tr data-login="([^"]+)"', page)

    assert rows == ["ann", "bo"]
    for login in rows:
        assert f'aria-label="Take {login} out of this cycle"' in page
        assert f'aria-label="{login} availability"' in page
    dropcell = re.search(r'<td class="dropcell">.*?</td>', page, re.S).group(0)
    assert 'class="confirm" hidden>' in dropcell
    assert 'class="yes">yes</button>' in dropcell and 'class="no">no</button>' in dropcell
    # The row the add box builds is a second copy of the same cell, and a copy
    # that drifts is a row whose only destructive control loses its name.
    minted = re.search(r"function dropCell\(login\) \{.*?\n\}", page, re.S).group(0)
    # `${who}` and not `${login}`: the name is escaped once at the top of the
    # function, because a login is typed and this cell is markup.
    assert "const who = esc(login);" in minted
    assert 'aria-label="Take ${who} out of this cycle"' in minted
    assert 'class="confirm" hidden>' in minted


def test_the_save_button_follows_what_it_commits(client: TestClient):
    """F15. Every commit action on this page sat above the form it commits, which
    on a betting table means a screen away from the row being argued about."""
    page = client.get("/cycle/37").text

    assert page.index('id="commitbar"') > page.index('<form id="setup"')
    assert page.index('id="commitbar"') > page.index('<table id="bets"')
    assert "position: sticky; bottom: 0;" in page, "and stays in reach"


def test_the_cycle_page_says_what_is_unsaved_and_that_a_save_landed(client: TestClient):
    """F5. One save model for the page, said out loud: the bar names what is
    unsaved, and the receipt survives the reload that proves it landed."""
    page = client.get("/cycle/37").text
    mark = re.search(r"function mark\(\) \{.*?\n\}", page, re.S).group(0)
    click = re.search(r"SAVE\.onclick = async \(\) => \{.*?\n\};", page, re.S).group(0)

    assert '<span id="unsaved">Nothing to save</span>' in page
    assert 'id="state" role="status"' in page, "a receipt nobody is told about"
    assert "UNSAVED.textContent" in mark and "BAR.classList.toggle('dirty'" in mark
    assert "sessionStorage.setItem(RECEIPT" in click
    assert "sessionStorage.getItem(RECEIPT)" in page
    assert re.search(r"receipt = `\$\{quiet \? 'Autosaved' : 'Saved'\}", page), \
        "the two-minute autosave confirms in the same place as the button"


def test_the_unsaved_count_and_the_receipt_count_the_same_thing(client: TestClient):
    """"2 unsaved changes" and then "Saved 1 change" about the same two edits.

    `mark()` counted fields and `flush()` counted commits, and two fields on one
    row is one commit. F5 is about a save you can believe, and that number is the
    whole of the claim: a receipt you have to reconcile against the counter that
    preceded it is a receipt nobody reads twice.
    """
    page = client.get("/cycle/37").text
    mark = re.search(r"function mark\(\) \{.*?\n\}", page, re.S).group(0)
    flush = re.search(r"async function flush\(quiet\) \{.*?\n\}", page, re.S).group(0)

    # Both sides count one edit per field, the roster as one, and the notes as one.
    # The setup PUT carries the roster and the notes together, so a save that
    # changed both is two edits before it and two after it.
    assert "for (const fields of PENDING.values()) edits += Object.keys(fields).length;" in mark
    assert "saved += Object.keys(fields).length;" in flush
    # Three flags now: the goal became a field of its own, above the betting
    # table, and an unsaved goal has to be counted like an unsaved roster or the
    # bar says "nothing to save" over an edit.
    assert (
        "let edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);"
        in mark
    )
    assert (
        "const edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);"
        in flush
    )
    assert "saved += edits;" in flush
    # The one thing that must never come back: a per-commit tally in the receipt.
    assert "saved += 1;" not in flush, "one write can still be two edits"

    # And the two sentences are built from the same unit either side of the save.
    assert re.search(r"\$\{edits\} unsaved change\$\{edits === 1 \? '' : 's'\}", mark)
    assert re.search(r"\$\{saved\} change\$\{saved === 1 \? '' : 's'\}", flush)


def test_a_cycle_with_no_record_is_a_form_and_says_so(client: TestClient):
    """F25 links here for every cycle the plan names, so a cycle nobody has
    written down yet has to be worth arriving at: the team list seeds the roster,
    because an empty table beside an add box is a form nobody can tell is
    working."""
    page = client.get("/cycle/37").text
    roster = re.findall(r'<tr data-login="([^"]+)"', page)

    assert "No record yet" in page
    assert "the record Save would write" in page
    assert roster == ["ann", "bo", "cy"], "config/people.yaml, sorted"


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

    # The sha comes back to the uploader as well as going out to the stream. The
    # shell's banner suppresses news of a commit this tab made, and it can only do
    # that if the request that made it says which commit that was — an upload that
    # only announced popped "The plan changed." over the paste that caused it.
    assert first.json()["commit"] == git_head(repo_path)


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


# A reference in prose, the same reference already inside a link, and one inside
# a code span. The middle one is the defect: the substitution ran over
# markdown-it's finished HTML with no idea what it was inside, so the reference
# in the `href` was linked again — an anchor nested in an attribute, which a
# tokeniser turns into one anchor wearing junk valueless attributes. The third is
# the same blindness the other way: backticks mean "do not interpret this".
PR_CONTEXTS = (
    "Bare: C2SM/icon4py#1364.\n\n"
    "[a pr link](https://github.com/org/repo#12)\n\n"
    "In code: `org/repo#9`.\n"
)


def test_a_pr_reference_is_linked_in_prose_and_left_alone_everywhere_else(client: TestClient):
    """Broken markup on the detail page, the static export and the preview alike,
    and it broke the benign page as much as the hostile one — which is why a
    hostile-versus-benign census could not see it."""
    save(client, TASK, {}, body=PR_CONTEXTS)
    previewed = client.post("/api/preview", json={"body": PR_CONTEXTS}).json()["html"]
    stored = client.get(f"/detail/{TASK}").text

    for where, html in (("preview", previewed), ("detail", stored)):
        assert '<a href="https://github.com/C2SM/icon4py/pull/1364">C2SM/icon4py#1364</a>' in html
        # Byte for byte: this anchor exists in one piece only if nothing linked
        # the reference sitting inside its own href.
        assert '<a href="https://github.com/org/repo#12">a pr link</a>' in html, where
        assert "<code>org/repo#9</code>" in html, where
    # The whole preview is one body, so its anchors can be counted: two links
    # written by the document, and nothing else.
    assert previewed.count("<a ") == 2, previewed


def test_the_preview_renders_with_the_page_s_own_markdown(client: TestClient):
    """It built a second MarkdownIt, and the second one disagreed with `_MD` about
    both of the things it had been taught: tables were not enabled, so a table
    previewed as a wall of pipes and rendered as a table once saved, and it did
    not drop the leading heading that only restates the title — so the preview
    showed a heading the saved page suppresses. Preview is the one place somebody
    checks a document before committing it; a preview that is wrong about the page
    is worse than no preview.
    """
    body = "# Bubble\n\n| field | weeks |\n|---|---|\n| appetite | 6 |\n"

    previewed = client.post(
        "/api/preview", json={"body": body, "title": "Bubble"}
    ).json()["html"]

    assert "<table>" in previewed, "the same tables the saved page renders"
    assert "<h1>Bubble</h1>" not in previewed, "and the same repeated title dropped"
    # Without a title nothing is dropped: the heading is only a repetition when
    # there is something for it to repeat.
    assert "<h1>Bubble</h1>" in client.post("/api/preview", json={"body": body}).json()["html"]


def test_both_editors_send_the_title_they_are_previewing(client: TestClient):
    """The title that decides whether the document's own first heading is a
    repetition is the one in the box, not the one in the repository — the same
    Save is about to change it."""
    for page in (client.get(f"/detail/{TASK}").text, client.get("/new?kind=pitch").text):
        assert "const TITLED = document.querySelector('.title-field');" in page
        assert "body: JSON.stringify({body: BODY.value, title: TITLED.value})" in page


def test_the_preview_still_refuses_html(client: TestClient):
    """The rewrite runs after markdown, on markdown's own output — it must not
    become a way to get a tag past the renderer."""
    smuggled = client.post(
        "/api/preview",
        json={"body": '<script>alert(1)</script>\n\n<img src="assets/deadbeefdeadbeef.png">\n'},
    ).json()["html"]

    assert "<script>" not in smuggled
    assert "<img" not in smuggled


def test_every_control_on_the_cycle_page_has_a_name(client: TestClient):
    """The three boxes that decide when a cycle runs sat under `<dt>`s, and the
    betting table is four hundred boxes named by a column header a reader who
    lands on one of them never passed through.

    A row's controls are named after the row, not the column: "appetite" without
    "for what" is not a name.
    """
    page = client.get("/cycle/37").text
    setup = re.search(r'<form id="setup".*?</form>', page, re.S).group(0)

    for field, word in (("starts_on", "Starts on"), ("reviews_on", "Review meeting")):
        assert f'<label for="{field}">{word}</label>' in setup, field
        assert re.search(rf'<input[^>]*\bid="{field}"', setup), field
    # And the two dates below them are worked out rather than typed, so they have
    # no control to name — a `<label for>` pointing at nothing is a name a reader
    # is promised and cannot reach.
    for derived in ("Builds until", "Cool-down ends"):
        assert f'<dt class="derived">{derived}</dt>' in setup, derived
    assert "<label" not in setup.split("Builds until")[1]
    assert '<label for="joining"' in page and 'id="joining"' in page

    rows = re.findall(r'<tr data-id="([^"]+)".*?</tr>', page, re.S)
    assert rows, "the corpus offers nothing to bet"
    for row in re.findall(r'<tr data-id="[^"]+".*?</tr>', page, re.S):
        title = re.search(r'<a href="[^"]*">([^<]+)</a>', row).group(1)
        assert f'aria-label="Bet {title} into cycle 37"' in row, title
        assert f'aria-label="{title} appetite in weeks"' in row, title
        assert f'aria-label="{title} assignees"' in row, title
        assert f'aria-label="{title} reviewers"' in row, title

    # Every control on the page is named one way or the other. A checkbox with no
    # label and no aria-label is a checkbox announced as "checkbox". The style and
    # script blocks come out first: both of them talk *about* `<input type=date>`.
    markup = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S)
    for tag in re.findall(r"<(?:input|select|textarea)[^>]*>", markup):
        if 'type="hidden"' in tag:
            continue
        named = "aria-label=" in tag or re.search(r'\bid="([^"]+)"', tag)
        assert named, tag
        if "aria-label=" not in tag:
            control_id = re.search(r'\bid="([^"]+)"', tag).group(1)
            assert f'<label for="{control_id}"' in page, tag


def test_a_receipt_the_cycle_page_draws_is_a_receipt_it_announces(client: TestClient):
    """The bar said "Saved 3 changes" and nothing said it out loud. `say` goes
    through the shell's region, which puts it in `#state` as well — so the
    sentence is drawn in the same place and announced for the first time."""
    page = client.get("/cycle/37").text

    assert "function say(message) { announce(message); }" in page
    assert "STATE.textContent" not in page, "the direct write this replaced"
    assert 'id="state" role="status"' in page


def test_a_committed_parent_that_names_nothing_leaves_every_page_readable(
    client: TestClient, repo_path: Path
):
    """`parent` is a `str`, so a well-formed id nobody wrote a file for parses.

    Which is the whole point: the write path's parse-before-write refusal asks
    whether the *record* reads back, and this record does. What did not read back
    was the *plan* — `build_index` walked the parent chain and indexed a link
    that is not there — so a PATCH any signed-in member can send returned 200,
    committed, and then answered 500 on `/`, `/detail/<id>`, `/graph`,
    `/timeline`, `/people` and `/api/index.json` for everybody, on every read.
    Branch protection means that commit cannot be force-pushed away, and the
    500ing pages will not hand you the sha to craft the repair against.

    A dangling parent is deliberately not a validation problem (see the `task()`
    helper in `test_validate`), so the requirement is not that the write is
    refused — it is that the plan still renders afterwards.
    """
    head = client.get("/healthz").json()["head"]

    saved = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": head, "fields": {"parent": "proj-ffffff"}},
    )
    assert saved.status_code == 200, saved.text

    # In git, not in the answer: the point is that the value really did land.
    written = pygit2.Repository(str(repo_path)).revparse_single(
        f"{saved.json()['commit']}:{PATH}"
    ).data.decode()
    assert "parent: proj-ffffff" in written

    for route in ("/", f"/detail/{TASK}", "/api/index.json", "/graph", "/timeline", "/people"):
        assert client.get(route).status_code == 200, route


def test_a_committed_size_larger_than_the_calendar_leaves_every_page_readable(
    client: TestClient
):
    """The same shape, through the scheduler instead of the index.

    `person_weeks: 1000000` parses, commits, and then `working_days_after` walked
    a day at a time until `timedelta` went past year 9999 and raised. Same blast
    radius as the dangling parent, same permanence, and no rule refuses the value.
    """
    head = client.get("/healthz").json()["head"]

    saved = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": head, "fields": {"person_weeks": 1_000_000.0}},
    )
    assert saved.status_code == 200, saved.text

    for route in ("/", f"/detail/{TASK}", "/api/index.json", "/graph", "/timeline", "/people"):
        assert client.get(route).status_code == 200, route


def test_a_cycle_longer_than_the_calendar_is_refused_and_writes_nothing(
    client: TestClient, repo_path: Path
):
    """`build_weeks: 500000` — three keystrokes into the Cycles form's own box,
    which had no bound at all — committed, and then `Cycle.ends_on` raised
    OverflowError while the config was still being assembled. That is before any
    rule has looked at the record, so nine routes answered 500 and `/healthz`
    alone survived, permanently, on a branch whose protection means the commit
    cannot be force-pushed away.

    The length is a pair of dates now and the same hazard arrives through them, so
    the bound moved with them. Refused where the route already refuses a word for
    a number, and the refusal quotes the value: a 422 that will not say what was
    wrong is a form nobody can correct.
    """
    base = head(client)

    refused = client.put(
        "/api/cycle/38",
        json={"base_commit": base,
              "fields": {"starts_on": "2026-09-01", "reviews_on": "9999-12-31"}},
    )

    assert refused.status_code == 422
    assert "not a cycle" in refused.json()["detail"]
    assert "520" in refused.json()["detail"], "and says what it will hold"
    assert head(client) == base, "a refused write leaves HEAD where it was"
    # In git, not in the answer: a 422 that still wrote the file is the failure.
    tree = pygit2.Repository(str(repo_path)).revparse_single("HEAD^{tree}")
    assert "cycles" not in [entry.name for entry in tree]


def test_a_cycle_record_longer_than_the_calendar_leaves_every_page_readable(
    client: TestClient, repo_path: Path
):
    """The file somebody wrote in git, which never passed the route.

    "Edit it in git if you prefer" is the promise, so the door check cannot be
    the only guard: a hand-written record still has to cost that cycle's dates
    rather than every page.
    """
    record = "---\ncycle: 38\nstarts_on: 2026-09-01\nbuild_weeks: 500000\n---\n"
    commit_directly(repo_path, SEED | {"cycles/0038.md": record}, "a cycle nobody could mean")

    for route in ("/", "/detail", "/api/index.json", "/graph", "/timeline", "/people", "/cycles"):
        assert client.get(route).status_code == 200, route


def test_a_done_date_at_the_end_of_the_calendar_leaves_a_timeline_you_can_open(
    client: TestClient
):
    """`31/12/9999` into the detail page's "Assigned on": committed, and
    `/timeline` answered 500 for good.

    Worse than the cycle above in one way — `openproj check` reported "0
    blockers, 0 warnings" and `openproj render` wrote no files at all, so both
    of the tools you would reach for to diagnose it were silent or dead.

    A 200 is not the whole claim: left to itself the plot draws every day
    between here and the year 9999 and comes out fourteen megabytes wide, which
    is a hung tab rather than a page. So the timeline is measured, not just
    fetched.
    """
    base = head(client)

    saved = client.patch(
        f"/api/entity/{DONE}", json={"base_commit": base, "fields": {"assigned_on": "9999-12-31"}}
    )
    assert saved.status_code == 200, saved.text

    for route in ("/", f"/detail/{DONE}", "/api/index.json", "/graph", "/timeline", "/people"):
        assert client.get(route).status_code == 200, route
    timeline = client.get("/timeline").text
    assert len(timeline) < 1_000_000, f"{len(timeline)} bytes is not a page"
    assert len(re.findall(r'<text class="month-label"', timeline)) < 600


@pytest.mark.parametrize("size", [float("inf"), float("nan")])
def test_a_size_that_is_not_a_number_is_refused_at_both_doors(client: TestClient, size: float):
    """`Infinity` and `NaN` are valid JSON to Python's parser, so they arrive as
    ordinary floats and passed every type check on the way in. `person_weeks:
    Infinity` committed, and then `math.ceil` raised inside the scheduler's own
    end-of-calendar guard — the guard was the thing that fell over.

    Both doors, because `create` had no type check at all: a closed writable
    surface is only closed if both ways in are.
    """
    base = head(client)
    # `content`, not `json`: the standard encoder refuses these two, and the
    # point is that Python's *decoder* accepts them, so this is what a client
    # that is not this test suite can actually put on the wire.
    literal = "Infinity" if size == size else "NaN"
    headers = {"content-type": "application/json"}

    saved = client.patch(
        f"/api/entity/{TASK}",
        content=f'{{"base_commit": "{base}", "fields": {{"person_weeks": {literal}}}}}',
        headers=headers,
    )
    created = client.post(
        "/api/entity",
        content=(
            '{"fields": {"kind": "task", "title": "Big", "owner": "ann", '
            f'"reviewers": ["bo"], "status": "ready", "person_weeks": {literal}}}}}'
        ),
        headers=headers,
    )

    assert saved.status_code == 422, saved.text
    assert "person_weeks" in saved.json()["detail"]
    assert created.status_code == 422, created.text
    assert head(client) == base, "a refused write leaves HEAD where it was"


# --------------------------------------------------------------------------- #
# 12. The envelope
#
# Every check above is about a *value* inside the request. The request itself —
# a JSON object with a `base_commit`, a `fields` map and a `body` string — was
# assumed by all four write routes and checked by none of them, so the first
# unguarded line in each handler turned a malformed body into an AttributeError
# under the router. That is a 500 in `text/plain`, which is the one answer these
# pages cannot read back to say what happened; it is the whole reason the value
# checks exist, and the envelope those checks live inside had none.
#
# Reachable without a browser, which is the point: `/api/preview` answers an
# anonymous visitor, and the other three answer any member with curl. Nothing
# here can corrupt the plan — every fault was before the commit — so what is at
# stake is whether a person is told what was wrong.
# --------------------------------------------------------------------------- #

JSON_HEADERS = {"content-type": "application/json"}
WRITE_ROUTES = (
    ("PATCH", f"/api/entity/{TASK}"),
    ("PUT", "/api/cycle/3"),
    ("POST", "/api/entity"),
    ("POST", "/api/preview"),
)


@pytest.mark.parametrize("method,route", WRITE_ROUTES)
def test_a_request_body_that_is_not_json_is_refused_rather_than_raised(
    client: TestClient, repo_path: Path, method: str, route: str
):
    """A truncated POST is the ordinary way this happens, and it happens to the
    person on the worst connection in the room."""
    was = git_head(repo_path)

    response = client.request(method, route, content=b"{not json", headers=JSON_HEADERS)

    assert response.status_code == 400, response.text
    assert "not JSON" in response.json()["detail"]
    assert git_head(repo_path) == was


@pytest.mark.parametrize("method,route", WRITE_ROUTES)
@pytest.mark.parametrize("payload", ("[]", '"a string"', "5", "null"))
def test_a_request_that_is_not_an_object_is_refused_rather_than_raised(
    client: TestClient, repo_path: Path, method: str, route: str, payload: str
):
    """All four routes read keys off whatever came back. `JSON.stringify` over
    the wrong variable sends a list, and a list has no `.get`."""
    was = git_head(repo_path)

    response = client.request(method, route, content=payload, headers=JSON_HEADERS)

    assert response.status_code == 422, response.text
    assert git_head(repo_path) == was


@pytest.mark.parametrize("method,route", (("PATCH", f"/api/entity/{TASK}"),
                                          ("PUT", "/api/cycle/3")))
@pytest.mark.parametrize(
    "base", ("__MISSING__", "null", '""', "7", '"' + "z" * 40 + '"', '"' + "0" * 40 + '"')
)
def test_a_save_without_a_real_base_commit_is_refused_at_both_doors(
    client: TestClient, repo_path: Path, method: str, route: str, base: str
):
    """The entity save learned this from a restored draft carrying a commit that
    a re-clone of the plan had taken away. The cycle save beside it had the same
    four ways to fault — absent, null, not a string, and a sha nothing has — and
    none of the guard, so the same stale tab was a 500 there.

    Parametrised over both routes rather than written twice, because "the guard
    is on one of the two identical routes" is exactly the shape of the defect.
    """
    was = git_head(repo_path)
    carried = "" if base == "__MISSING__" else f'"base_commit": {base}, '

    response = client.request(
        method, route, content=f'{{{carried}"fields": {{}}}}', headers=JSON_HEADERS
    )

    assert response.status_code == 422, response.text
    assert "copy anything unsaved" in response.json()["detail"]
    assert git_head(repo_path) == was


@pytest.mark.parametrize("method,route", (("PATCH", f"/api/entity/{TASK}"),
                                          ("PUT", "/api/cycle/3"),
                                          ("POST", "/api/entity")))
def test_fields_that_are_not_a_map_are_refused_rather_than_raised(
    client: TestClient, repo_path: Path, method: str, route: str
):
    was = git_head(repo_path)

    response = client.request(
        method, route,
        content=json.dumps({"base_commit": was, "fields": ["priority", "high"]}),
        headers=JSON_HEADERS,
    )

    assert response.status_code == 422, response.text
    assert git_head(repo_path) == was


@pytest.mark.parametrize("method,route", (("PATCH", f"/api/entity/{TASK}"),
                                          ("PUT", "/api/cycle/3"),
                                          ("POST", "/api/entity")))
def test_a_body_that_is_not_text_is_refused_rather_than_raised(
    client: TestClient, repo_path: Path, method: str, route: str
):
    """`len(body.encode(...))` is the size check, and it was also where a body
    that is not text stopped being a save and became an AttributeError."""
    was = git_head(repo_path)

    response = client.request(
        method, route,
        content=json.dumps({"base_commit": was, "fields": {}, "body": 5}),
        headers=JSON_HEADERS,
    )

    assert response.status_code == 422, response.text
    assert "a body is text" in response.json()["detail"]
    assert git_head(repo_path) == was


def test_a_preview_of_something_that_is_not_text_still_answers(client: TestClient):
    """This one renders and does not write, so it shows what was typed rather
    than refusing it. It is also the only write-adjacent route an anonymous
    visitor can reach, and the markdown parser took a number as a TypeError."""
    response = client.post("/api/preview", json={"body": 5, "title": 7})

    assert response.status_code == 200, response.text
    assert "5" in response.json()["html"]


@pytest.mark.parametrize(
    "fields,expected",
    (
        ({"title": 12345}, "title"),
        ({"title": ["a", "b"]}, "title"),
        ({"assigned_on": "not-a-date"}, "assigned_on"),
        ({"reviewers": [1, 2]}, "reviewers"),
        ({"tags": [None]}, "tags"),
        ({"created_schema_version": "two"}, "created_schema_version"),
    ),
)
def test_a_create_the_server_could_not_read_back_says_which_field(
    client: TestClient, repo_path: Path, fields: dict, expected: str
):
    """The save route has parsed before writing since the round that found it.
    The create route beside it called the same `parse_text` with no guard at all,
    so every value `_reject_bad_types` does not name — a title that is a number,
    a date that is a word, a reviewer that is an integer — came out as a bare
    ValidationError, which is a 500 in `text/plain` on a form that has to be able
    to say which box was wrong. Nothing was committed either way; what changes is
    whether the person is told.
    """
    was = git_head(repo_path)

    response = create(client, {**VALID_TASK, **fields})

    assert response.status_code == 422, response.text
    assert "would not read back" in response.json()["detail"]
    assert expected in response.json()["detail"]
    assert git_head(repo_path) == was


@pytest.mark.parametrize("number", (-1, 10000, 99999))
def test_a_cycle_number_no_save_would_accept_is_not_a_page(client: TestClient, number: int):
    """`int` in the path admits every integer; `CYCLE_PATTERN` on the save admits
    0 to 9999. So `/cycle/-1` rendered a whole editable page whose every Save was
    a 422 — the read path and the write path disagreeing about which cycles
    exist, and a dead end a person can only find by filling the form in first."""
    assert client.get(f"/cycle/{number}").status_code == 404
    assert client.get("/cycle/9999").status_code == 200, "a real cycle number still is one"
