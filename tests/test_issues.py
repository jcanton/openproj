"""The issue tracker, which is deliberately not part of the plan.

An entity is a bet: it carries an appetite, takes a place on the timeline and
charges somebody's cycle. An issue is the opposite — most of them will never be
worked on, which is the point of having somewhere to put them. That difference is
the whole design, and these tests are mostly about keeping the two apart.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, git_head

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import Config, Issue, Task, issue_problems, load_repo
from openproj.web import SESSION_COOKIE, create_app

OTHER_PAGES = ("/", "/graph", "/timeline", "/people", "/detail", "/cycles")


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


def opened(client: TestClient, title: str, base: str, **fields) -> str:
    response = client.post(
        "/api/issue", json={"base_commit": base, "title": title, "fields": fields}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


# --------------------------------------------------------------------------- #
# Kept out of the plan
# --------------------------------------------------------------------------- #


def test_an_issue_appears_on_no_page_but_its_own(client: TestClient, repo_path: Path):
    """By construction, not by an exclusion in each view that somebody forgets.
    An issue is not an Entity, so nothing on those pages ever sees one."""
    issue_id = opened(client, "Halo exchange drops a rank", git_head(repo_path))

    assert issue_id in client.get("/issues").text
    for route in OTHER_PAGES:
        assert issue_id not in client.get(route).text, route


def test_an_issue_is_not_an_entity_and_cannot_become_one(client: TestClient, repo_path: Path):
    """The entity id pattern is what keeps `projects|pitches|tasks/<id>.md` the
    whole writable surface for entities. An issue has its own."""
    from openproj.model import _ID_PATTERN, _ISSUE_ID_PATTERN

    issue_id = opened(client, "Something", git_head(repo_path))

    assert not _ID_PATTERN.match(issue_id)
    assert _ISSUE_ID_PATTERN.match(issue_id)
    assert client.patch(f"/api/entity/{issue_id}", json={"base_commit": git_head(repo_path),
                                                         "fields": {}, "body": None}).status_code
    entities, _, _ = load_repo(Path("seed"))
    assert all(not e.id.startswith("issue-") for e in entities)


def test_an_issue_has_no_shaping(client: TestClient):
    """A shaped issue is a pitch. That is the entire lifecycle: somebody reads the
    open issues at the betting table and writes a pitch for what matters."""
    from openproj.model import ISSUE_STATUS

    assert "shaping" not in ISSUE_STATUS
    assert ISSUE_STATUS == ("ready", "in_progress", "done", "shelved")
    assert "shaping" not in re.search(
        r'<select id="state-filter">.*?</select>', client.get("/issues").text, re.S
    ).group(0)


# --------------------------------------------------------------------------- #
# What a link means
# --------------------------------------------------------------------------- #


def entities(**by_id: str) -> dict[str, Task]:
    return {
        i: Task(id=i, kind="task", title=i, status=status) for i, status in by_id.items()
    }


def test_pitching_an_issue_is_what_closes_it():
    """Derived, never copied. Writing the state into the file as well would be a
    second copy of a fact the link already carries, and the two disagree the
    moment somebody closes the pitch."""
    world = entities(**{"task-aa0001": "done", "task-bb0001": "in_progress"})
    unlinked = Issue(id="issue-000001", title="x")
    picked = Issue(id="issue-000002", title="x", pitched_into=["task-bb0001"])
    finished = Issue(id="issue-000003", title="x", pitched_into=["task-aa0001"])
    partly = Issue(id="issue-000004", title="x", pitched_into=["task-aa0001", "task-bb0001"])

    assert unlinked.state(world) == "ready"
    assert picked.state(world) == "in_progress"
    assert finished.state(world) == "done"
    assert partly.state(world) == "in_progress"


def test_shelved_is_a_decision_a_link_does_not_reverse():
    """"We are not doing this" was said by a person. Somebody linking it into a
    pitch afterwards does not un-say it."""
    world = entities(**{"task-aa0001": "done"})
    wont_fix = Issue(id="issue-000001", title="x", status="shelved",
                     pitched_into=["task-aa0001"])

    assert wont_fix.state(world) == "shelved"


def test_a_link_to_something_that_is_gone_leaves_the_stored_state_alone():
    """An issue outlives the pitch it fed. A deleted target is a warning, not a
    state change and not a crash."""
    issue = Issue(id="issue-000001", title="x", pitched_into=["task-zzzzzz"])
    config = Config().with_issues([issue])

    assert issue.state({}) == "ready"
    assert [p.severity for p in issue_problems(config, [])] == ["warning"]


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def test_opening_an_issue_asks_for_a_title_and_nothing_else(
    client: TestClient, repo_path: Path
):
    """Somebody has just noticed something while doing something else. Anything
    asked for beyond a title is a reason not to write it down at all."""
    issue_id = opened(client, "openproj check is slow", git_head(repo_path))
    stored = pygit2.Repository(str(repo_path))[git_head(repo_path)].tree[
        f"issues/{issue_id}.md"
    ].data.decode()

    assert "title: openproj check is slow" in stored
    assert "status: ready" in stored
    assert f"reported_by: {ANN.login}" in stored
    assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", stored)
    assert client.post("/api/issue", json={"base_commit": git_head(repo_path),
                                           "title": "  "}).status_code == 422


def test_an_issue_the_server_could_not_read_back_is_never_committed(
    client: TestClient, repo_path: Path
):
    issue_id = opened(client, "x", git_head(repo_path))
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/issue/{issue_id}",
        json={"base_commit": before, "fields": {"status": "shaping"}, "body": None},
    )

    assert refused.status_code == 422
    assert git_head(repo_path) == before


def test_an_issue_id_that_is_not_one_never_becomes_a_path(client: TestClient, repo_path: Path):
    for hostile in ("../config/defaults", "issue-../../x", "task-c00001", "issue-ZZZZZZ"):
        response = client.patch(
            f"/api/issue/{hostile}",
            json={"base_commit": git_head(repo_path), "fields": {}, "body": None},
        )
        assert response.status_code in (400, 404), hostile
    assert pygit2.Repository(str(repo_path))[git_head(repo_path)].tree["config/defaults.yaml"]


def test_an_issue_cannot_carry_a_field_it_does_not_have(client: TestClient, repo_path: Path):
    issue_id = opened(client, "x", git_head(repo_path))
    refused = client.patch(
        f"/api/issue/{issue_id}",
        json={"base_commit": git_head(repo_path), "fields": {"appetite_weeks": 3}, "body": None},
    )

    assert refused.status_code == 422
    assert "appetite_weeks" in refused.json()["detail"]


def test_the_page_shows_open_issues_until_it_is_asked_for_more(client: TestClient):
    """Open issues are the question the page exists to answer."""
    page = client.get("/issues").text
    script = re.search(r"function apply\(\).*?\n\}", page, re.S).group(0)

    assert "state !== 'done' && state !== 'shelved'" in script
    assert "wanted === '*' ? true" in script


def test_the_list_is_a_table_sorted_the_way_the_other_table_sorts(client: TestClient):
    """Same shape as the table view: columns that sort, click again to reverse,
    and `state` ranked as a sequence rather than as a word."""
    page = client.get("/issues").text
    headers = re.findall(r'<th data-sort="(\w+)"', page)

    assert headers == ["state", "title", "reported_by", "opened", "pitched", "tags"]
    assert "reversed = sorted === key ? !reversed : false;" in page
    assert "RANK.indexOf(row.dataset.state)" in page, "a state is a sequence, not a word"
    # The affordances the entity table grew: a real button, because there is no
    # way to tab to a cell; a direction glyph in a reserved box, so sorting does
    # not shove every header sideways; and aria-sort, which is all a screen
    # reader has to go on.
    assert page.count('aria-sort="none"') == len(headers)
    assert '<button type="button">' in page
    assert '<span class="dir" aria-hidden="true">' in page
    assert "head.setAttribute('aria-sort'" in page
    assert "'\u25be' : '\u25b4'" in page.replace("▾", "\u25be").replace("▴", "\u25b4")


def test_opening_an_issue_is_the_same_view_as_editing_one(client: TestClient, repo_path: Path):
    """A second, differently-shaped form for creating is what made the tool feel
    like two tools the last time. One template, one flag."""
    blank = client.get("/issue/new").text
    issue_id = opened(client, "Something", git_head(repo_path))
    existing = client.get(f"/issue/{issue_id}").text

    for shape in ('<form id="edit"', 'name="title"', 'name="body"', 'id="marks"',
                  'name="pitched_into"', 'id="save"'):
        assert shape in blank, shape
        assert shape in existing, shape
    assert "const CREATING = true;" in blank
    assert "const CREATING = false;" in existing
    assert re.search(r'id="save"[^>]*>\s*Open it\s*</button>', blank)
    assert client.get("/issue/nope").status_code == 404


def test_creating_writes_the_body_and_the_fields_in_one_commit(
    client: TestClient, repo_path: Path
):
    """Opening an issue used to take a title and nothing else, so the body had to
    be found in a list and filled in afterwards — two visits for one thought."""
    before = git_head(repo_path)
    issue_id = opened(client, "Edges cross nodes", before, tags=["graph"])
    after = git_head(repo_path)
    stored = pygit2.Repository(str(repo_path))[after].tree[
        f"issues/{issue_id}.md"
    ].data.decode()

    assert len(list(pygit2.Repository(str(repo_path)).walk(after))) == len(
        list(pygit2.Repository(str(repo_path)).walk(before))
    ) + 1, "one commit, not two"
    assert "- graph" in stored


def test_the_reporter_defaults_to_whoever_is_signed_in(client: TestClient, repo_path: Path):
    """The session knows who is writing — it is the same name that becomes the
    commit's author — and that is right almost every time. It is not right when
    somebody files what a colleague mentioned in a corridor, so the form can say
    otherwise. `opened_on` stays the server's: when the record was made is not an
    opinion."""
    mine = opened(client, "x", git_head(repo_path))
    theirs = opened(client, "y", git_head(repo_path), reported_by="halungge")

    def stored(issue_id: str) -> str:
        return pygit2.Repository(str(repo_path))[git_head(repo_path)].tree[
            f"issues/{issue_id}.md"
        ].data.decode()

    assert f"reported_by: {ANN.login}" in stored(mine)
    assert "reported_by: halungge" in stored(theirs)
    for issue_id in (mine, theirs):
        assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", stored(issue_id))

    refused = client.post(
        "/api/issue",
        json={"base_commit": git_head(repo_path), "title": "z",
              "fields": {"opened_on": "1999-01-01"}},
    )
    assert refused.status_code == 200
    assert "1999" not in stored(refused.json()["id"])


def test_a_derived_state_cannot_also_be_set_by_hand(client: TestClient, repo_path: Path):
    """Two ways to say one thing disagree the moment one of them is used."""
    issue_id = opened(client, "x", git_head(repo_path))
    client.patch(
        f"/api/issue/{issue_id}",
        json={"base_commit": git_head(repo_path),
              "fields": {"pitched_into": ["task-c00001"]}, "body": None},
    )
    page = client.get(f"/issue/{issue_id}").text
    control = re.search(r'<select name="status"[^>]*>', page).group(0)

    assert "disabled" in control
    assert "from the work it was pitched into" in page


def test_the_seed_corpus_carries_issues_that_load(seed_root: Path):
    entities, config, unreadable = load_repo(Path("seed"))

    assert not unreadable
    index = build_index(entities, config, date(2026, 8, 17))

    assert index.issues, "the demo corpus has issues"
    assert not [p for p in index.issue_problems if p.severity == "blocker"]
    assert {i.state(index.entities) for i in index.issues.values()} <= {
        "ready", "in_progress", "done", "shelved"
    }


def test_a_new_issue_has_fields_to_type_in(client: TestClient):
    """Creating IS editing. Without the class its own controls are gated on, the
    page rendered every one of them and then hid all of them, so opening an issue
    was a heading, a Save button and nothing to write in."""
    blank = client.get("/issue/new").text
    creating = re.search(r"const CREATING = true;.*?</script>", blank, re.S).group(0)

    assert "document.body.classList.add('editing');" in creating
    assert "body.editing .field { display: inline-block; }" in blank


def test_the_formatting_bar_sits_above_the_body_not_beside_it(client: TestClient):
    """`.field` on the bar won on specificity over `.bodybar` and turned it
    inline-block, which put the textarea on the same line as the buttons."""
    page = client.get("/issue/new").text
    bar = re.search(r'<p class="([^"]*)bodybar[^"]*">', page).group(1)

    assert "field" not in bar
    assert "body.editing .bodybar { display: flex; }" in page
