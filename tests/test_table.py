"""The table as a writing surface: the contract, written before it is one.

Phase 1's table could be read, sorted and filtered, and that was all. Every field
that actually changes during a week — a status, an owner, a reviewer, a priority —
had to be changed one entity at a time on a detail page, and there was no way to
bring a new entity into existence from the UI at all. A plan that costs a page
load per field is a plan that goes stale between meetings, and a plan you cannot
add to from the view you live in is a plan that gets kept somewhere else instead.

Five decisions shape almost every assertion below.

* **Derived columns have no control at all — structurally, not by being
  disabled.** `start`, `end`, `size` and the blocker count are the scheduler's
  output. A disabled input is one attribute away from being editable and the next
  contributor will not know why it was disabled; a control that does not exist
  cannot be wired up by accident. This is the same rule the detail page follows
  (`test_editor.test_no_derived_value_has_an_input_at_all`), and the two surfaces
  agreeing is the point: a person who learns the model from one page must not be
  taught something else by the other.
* **One edit is one PATCH is one commit, carrying only that field.** Field-level
  merge in `store.py` only works if the client sends field-level changes. A cell
  that posts the whole row turns every concurrent edit into a conflict, and a cell
  that posts a body turns a priority change into a rewrite of somebody's shaping
  document.
* **The server mints the id and the path; the client names neither.** An id chosen
  by a browser is a path chosen by a browser the moment it becomes `tasks/<id>.md`,
  and the writable surface stops being a closed set.
* **The client check is a courtesy; the server's answer is the truth.** The create
  form refuses to post a `todo` task with no owner because a four-request
  conversation to create one task teaches people to pick the status with the
  fewest rules. But the rules live in `model.validate_all`, the form's copy is a
  simplification of them, and the two will disagree eventually — so the page must
  render what the server said rather than swallowing it.
* **A save is compared against the commit the page was rendered at.** Re-reading
  HEAD at save time and posting *that* turns a real conflict into a silent
  overwrite of whoever committed in between, which is precisely the thing scoped
  compare-and-swap exists to catch.

What is assertable here is narrower than what a browser would check, and
deliberately so: the rows are drawn by the page's own JavaScript, so the markup
this file sees carries an empty `<tbody>`. Three things are still assertable
server-side, and they happen to be the three that decide whether work gets lost —
the markup the page is delivered as (the create form is all of it), the data the
script is built from, and the API behaviour the script depends on. Where an
assertion stands in for something only a browser can decide, its docstring says so
rather than dressing a string search up as coverage.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import (
    ANN,
    OTHER,
    PATH,
    PITCH,
    SECRET,
    SEED,
    TASK,
    commit_at,
    create,
    file_at,
    git_head,
    head,
    index_of,
    save,
)

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import load_repo
from openproj.render import EDITABLE, STATUSES, render_static
from openproj.web import SESSION_COOKIE, create_app

# The columns the table draws that nobody may type into. Kept as an expectation
# rather than computed silently, so that adding a derived column and forgetting to
# make it read-only fails here instead of in the corpus.
DERIVED = {"size", "start", "end", "blocked_by"}


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    """A bare plan repository, seeded the way every other suite seeds one.

    In production this is a different repository from the source tree; the server
    only ever knows a path to it.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


@pytest.fixture
def page(client: TestClient) -> str:
    return client.get("/").text


# --------------------------------------------------------------------------- #
# Reading the page
# --------------------------------------------------------------------------- #


def script(html: str) -> str:
    """Every line of JavaScript on the page, with the JSON data blocks left out.

    The separation matters for the greps below: a field name that appears only in
    the payload is data the script may or may not act on, while a field name in
    the script is a decision somebody wrote down.
    """
    return "\n".join(
        block
        for attributes, block in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S)
        if "application/json" not in attributes
    )


def payload(html: str) -> dict:
    return json.loads(re.search(r'<script id="payload"[^>]*>(.*?)</script>', html, re.S).group(1))


def columns(html: str) -> list[str]:
    """The field each column stands for, in order.

    The header labels are abbreviations — `pri`, `blockers` — so the sort key is
    the field name where there is one. This doubles as an assertion that every
    sortable column still declares what it sorts by.
    """
    found = []
    for tag, label in re.findall(r"<th([^>]*)>([^<]*)</th>", html):
        sort = re.search(r'data-sort="([^"]+)"', tag)
        found.append(sort.group(1) if sort else label.strip())
    return found


def controls(html: str) -> set[str]:
    """Every named form control in this fragment."""
    return set(re.findall(r'<(?:input|textarea|select)[^>]*\bname="([^"]+)"', html))


def control(html: str, name: str) -> str:
    """The one tag that owns a field, so its attributes can be read."""
    match = re.search(rf'<(?:input|textarea|select)[^>]*\bname="{name}"[^>]*>', html)
    assert match, f"no control named {name!r}"
    return match.group(0)


@pytest.fixture
def new_page(client: TestClient) -> str:
    """The create page. It used to be a form at the bottom of the table, which made
    creating an entity a different-shaped act from editing one; it is now the same
    layout as a detail page in edit mode."""
    return client.get("/new?kind=pitch").text


def create_form(html: str) -> str:
    match = re.search(r'<form[^>]*id="create".*?</form>', html, re.S)
    assert match, "the table must carry a form for creating an entity"
    return match.group(0)


def options(select_html: str) -> set[str]:
    """What a select would actually post, ignoring an empty placeholder."""
    chosen = set()
    for tag, label in re.findall(r"<option([^>]*)>([^<]*)</option>", select_html):
        value = re.search(r'value="([^"]*)"', tag)
        chosen.add((value.group(1) if value else label).strip())
    return chosen - {""}


# --------------------------------------------------------------------------- #
# 1. Which controls exist, and which must not
# --------------------------------------------------------------------------- #


def test_the_table_declares_which_columns_a_person_owns(page: str):
    """The editable set is `render.EDITABLE`, not a second list typed here.

    Two lists of "what a person may change" drift the first time a field is added,
    and the drift is silent in the direction that matters: a field editable on the
    detail page and inert in the table looks like a bug in the browser rather than
    a missing entry in a dictionary.
    """
    declared = payload(page)["editable"]

    assert set(declared) <= set(EDITABLE), "the table cannot invent fields to edit"
    for field in set(EDITABLE) & set(columns(page)):
        assert declared.get(field) == EDITABLE[field], field


def test_no_derived_column_can_be_edited_at_all(page: str):
    """Structurally absent, exactly as on the detail page.

    A start date typed by hand is a lie the next reschedule contradicts, and the
    contradiction surfaces as "the tool is wrong" rather than as "somebody typed
    over a forecast". `size` belongs here too and is the least obvious of the four:
    what the column shows is `effort_weeks` *or an assumed default*, so a control
    on it would let somebody commit the assumption without meaning to.
    """
    assert set(columns(page)) - set(EDITABLE) - {"id"} == DERIVED, (
        "a new column is neither editable nor known-derived"
    )
    declared = payload(page)["editable"]
    for field in DERIVED:
        assert field not in declared, f"{field} is computed and must not be editable"
        assert field not in controls(page), field


def test_the_id_is_shown_and_is_never_a_control(page: str):
    """The id is authoritative and the filename's slug drifts around it. Editing it
    would orphan the file from every reference to it in one keystroke — and on a
    table, in one keystroke on the wrong row."""
    assert TASK in page
    assert "id" not in payload(page)["editable"]
    assert "id" not in controls(page)


def test_the_status_control_offers_every_status_and_not_only_the_ones_in_use(new_page: str):
    """The facet dropdown lists the statuses present in the corpus, which is right
    for filtering and wrong for editing: nothing in this corpus is `shelved`, and a
    status control built from the facet could therefore never shelve anything.

    Deletion is `status: shelved` (spec §4.5), so that is not a missing option, it
    is the only way to retire an entity.
    """
    assert "shelved" in new_page
    for status in STATUSES:
        assert status in new_page, status


def test_the_page_carries_the_commit_it_was_rendered_at(page: str):
    """Compare-and-swap needs the base the person actually saw. A page that saves
    against whatever HEAD has become resolves every real conflict by discarding
    whoever committed while the tab sat open."""
    assert re.search(r'name="base_commit"[^>]*value="[0-9a-f]{40}"', page), (
        "the table must know which commit it is editing"
    )


def test_the_table_offers_a_way_to_create_an_entity(page: str, client: TestClient):
    """Entities are overwhelmingly born in the UI, so the UI has to be able to bear
    them. Without this the only supported way to add a task is to write a file by
    hand, which is the workflow this tool exists to replace."""
    assert re.search(r'href="/new"', page), "the table needs a way to reach the create page"
    assert client.get("/new").status_code == 200


def test_the_create_form_writes_only_fields_a_person_owns(new_page: str):
    """`kind` picks the directory and `body` is the shaping document; everything
    else on this form has to be a field `EDITABLE` names. A create that can set a
    field the detail page refuses to show is a back door into the schema."""
    named = controls(new_page) - {"base_commit"}

    assert named - {"body"} <= set(EDITABLE)
    for field in ("title", "status", "owner", "reviewers", "review_waived", "parent"):
        assert field in named, field
    # The kind is chosen by the route rather than by a control, so a pitch page
    # offers exactly the fields a pitch has and never the ones it does not.
    for field in ("appetite_weeks", "shaped_by"):
        assert field in named, f"{field} is status-gated at creation and must be fillable"
    assert "effort_weeks" not in named, "a pitch has no effort_weeks"


def test_the_create_form_names_neither_the_id_nor_the_path(new_page: str):
    """The server mints both. An id supplied by a browser becomes a path supplied
    by a browser as soon as it is `tasks/<id>.md`, and the writable surface stops
    being closed by construction — which matters more than usual because branch
    protection means a bad write cannot be force-pushed away afterwards."""
    named = controls(new_page)

    assert "id" not in named
    assert "path" not in named
    for field in DERIVED | {"blocks", "overruns_cycle_weeks", "why"}:
        assert field not in named, f"{field} is derived and must not be typed at creation"


def test_the_create_form_offers_the_three_kinds_and_nothing_else(client: TestClient):
    """`kind` is a closed set of three and it is the only thing that chooses a
    directory. It is now the route rather than a control, which closes the set at
    the door: an unknown kind is refused before a page is built, so `../config`
    never reaches a path."""
    for kind in ("project", "pitch", "task"):
        assert client.get(f"/new?kind={kind}").status_code == 200

    assert client.get("/new?kind=../config").status_code == 422
    assert client.get("/new?kind=milestone").status_code == 422


def test_the_status_gate_is_written_on_the_controls_themselves(new_page: str):
    """The requiredness rules, carried by the form so it can check before posting.

    Requiredness is status-gated and cumulative (spec §5.1): permissive when an
    idea is captured, strict once work starts, strictest when it is claimed done.
    An HTML `required` attribute cannot say that, because what is required depends
    on the status chosen in the same form a moment ago.

    Putting the gate on each control keeps the second copy of the rules honest —
    it is a declaration next to the field it governs rather than a branch buried in
    a script, and it is visible in the delivered page, so a reviewer can see what
    the form believes and compare it with `model.validate_all`. That the copy is
    only a copy is the point of `test_the_server_refusal_is_shown_and_not_swallowed`.
    """
    for field, gate in (
        ("owner", "todo"),
        ("reviewers", "todo"),
        ("appetite_weeks", "todo"),
        ("shaped_by", "todo"),
        ("assigned_on", "wip"),
        ("prs", "done"),
    ):
        assert f'data-required-from="{gate}"' in control(new_page, field), field

    assert "data-required-from" not in control(new_page, "review_waived"), (
        "review_waived is the escape hatch from a rule, not a rule"
    )


def test_a_field_only_one_kind_has_is_absent_from_the_others(client: TestClient):
    """A pitch has an appetite and a task has an effort, and asking for both makes
    the form a schema dump rather than a question. `shaped_by` is a pitch rule too,
    so a task blocked on a missing `shaped_by` would be nonsense.

    Absent rather than hidden: the page is rendered per kind, so the control that
    does not belong is not there to be un-hidden by a stray line of script."""
    pitch = controls(client.get("/new?kind=pitch").text)
    task = controls(client.get("/new?kind=task").text)

    assert {"appetite_weeks", "shaped_by"} <= pitch
    assert "effort_weeks" not in pitch
    assert "effort_weeks" in task
    assert not {"appetite_weeks", "shaped_by"} & task


def test_the_create_form_has_somewhere_to_put_the_server_refusal(new_page: str):
    """A refusal with nowhere to land is a refusal that gets swallowed, and a
    person who presses Create twice and sees nothing concludes the tool is broken
    rather than that the plan said no."""
    assert re.search(r'id="problems"', new_page)


def test_the_static_export_offers_no_editing_at_all(seed_root: Path, tmp_path: Path):
    """`openproj render` writes files, and a file has no server behind it.

    The detail page already draws this line — it only builds an editor when it is
    handed a base commit — and the table has to draw it in the same place. An
    export that shows a Save button is a page that silently does nothing, which is
    worse than one that never offered.
    """
    entities, config = load_repo(seed_root)
    render_static(build_index(entities, config, date(2026, 8, 17)), tmp_path)
    exported = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert not controls(exported)
    assert "base_commit" not in exported
    assert "/api/entity" not in exported


def test_editing_the_table_pulled_in_no_library(page: str):
    """No npm, no build step, no CDN — asserted on the page that just grew the most
    JavaScript, because that is where the argument for a framework gets made."""
    assert not re.search(r"<script[^>]+src\s*=", page)
    assert "new FormData" not in page, "a serialised form sends fields nobody touched"


# --------------------------------------------------------------------------- #
# 2. What the script is built from
#
# Proxies, every one of them: the rows do not exist until the page's JavaScript
# runs, so what can be checked here is the shape of the code that will build them.
# Each of these stands in for a browser check, and each is here because the
# behaviour it stands in for is one that silently loses work when it is wrong.
# --------------------------------------------------------------------------- #


def test_a_row_says_which_entity_it_is_and_a_cell_says_which_field(page: str):
    """A PATCH needs both, and reading them off the DOM is what lets one listener
    serve every cell instead of a closure per cell. Proxy for a browser checking
    that the attributes are actually on the elements."""
    assert re.search(r"<tr[^>]*data-id=", script(page)), "a row must carry its entity id"
    assert re.search(r"<td[^>]*data-field=", script(page)), "a cell must carry its field"


def test_one_edit_sends_exactly_one_field(page: str):
    """The payload is a single-key object built from the cell's own field name.

    Sending the row would overwrite whatever somebody else changed while this tab
    was open, and would turn two people editing two different columns of the same
    task into a conflict — which is the case field-level merge exists to make
    invisible. Proxy for a browser watching the request body.
    """
    body = script(page)

    assert re.search(r"\{\s*\[[\w.$]+\]\s*:|\w+\[[\w.$]+\]\s*=[^=]", body), (
        "the field name must come from the cell, so that exactly one field travels"
    )
    assert "PATCH" in body


def test_an_inline_edit_can_never_erase_a_shaping_document(page: str):
    """There is no body editor in a table, so a table save has no body to send.

    Sending an empty string instead of null is the accident that matters: the
    server treats a present body as a replacement, so one priority change would
    silently blank the shaping doc it was attached to, and git would record it as
    that person's deliberate edit.
    """
    assert not re.search(r"body:\s*(''|\"\"|``)", script(page)), (
        "an empty body is a replacement, not an omission"
    )


def test_the_save_uses_the_commit_the_page_was_rendered_at(page: str):
    """Never a freshly-read HEAD. Asking the server what HEAD is and then saving
    against the answer is a rebase onto somebody else's work with no read of what
    they wrote — it cannot conflict, which is exactly the problem."""
    body = script(page)

    assert "base_commit" in body
    assert "/healthz" not in body, "re-reading HEAD before a save discards the collision"


def test_a_committed_save_advances_the_page_base_commit(page: str):
    """Otherwise the second edit of a cell conflicts with the first — from the same
    tab, by the same person.

    `test_a_page_that_never_advances_its_base_collides_with_itself` below shows
    that happening through the API, which is the failure this prevents. Proxy for a
    browser making two edits in a row.
    """
    assert re.search(r"base\w*\b[^=\n;]{0,60}=[^;\n]{0,80}\bcommit\b", script(page), re.I), (
        "the page must adopt the commit its own save produced"
    )


def test_the_create_checks_the_status_gate_before_it_posts(new_page: str):
    """A round trip to be told the owner is missing is a round trip that teaches
    people to pick `shelved`. The check reads the gate off the controls, so the
    rules are declared once in the markup rather than re-typed per field."""
    body = script(new_page)

    assert re.search(r"required-?[Ff]rom", body), "the form must consult its own gate"
    assert "review_waived" in body, (
        "a waiver is how work with nothing to review gets created; a reviewers check "
        "that does not honour it makes the honest answer a fake reviewer"
    )


def test_the_server_refusal_is_shown_and_not_swallowed(page: str):
    """The form's copy of the rules is a simplification and will disagree with
    `validate_all` eventually — grandfathering alone means the form cannot know
    whether a rule applies to an entity that does not exist yet. When the server
    says no anyway, the page has to say what it said."""
    body = script(page)

    assert "problems" in body
    assert re.search(r"\b422\b|response\.ok|response\.status", body), (
        "a refused create must be distinguished from an accepted one"
    )


def test_a_conflict_is_never_written_into_an_editable_cell(page: str):
    """Text placed into an editing surface is text somebody saves back.

    A conflict report names both values, so pasting it into the cell it came from
    would commit `stored 'bo' · yours 'cy'` as the owner on the next save. It goes
    beside the row instead, and as text: the report quotes entity fields, so
    `innerHTML` would render whatever somebody happened to type into a title.

    Proxy for a browser checking which element it lands in; what is assertable here
    is that it never lands in a control's value.
    """
    body = script(page)

    assert not re.search(r"\.value\s*=[^;\n]*conflict", body, re.I)
    assert re.search(r"(textContent|innerText)\s*=[^;\n]*conflict", body, re.I), (
        "the report must be shown as text, beside the row it belongs to"
    )
    assert re.search(r"[.#]conflict\b", page), (
        "the report needs styling of its own, or it reads as another row of data"
    )


# --------------------------------------------------------------------------- #
# 3. The API the table rests on
#
# End-to-end, against git, because the page is only as correct as what these
# calls do. Asserted from the table's point of view: one cell, one commit.
# --------------------------------------------------------------------------- #


def test_one_cell_edit_is_one_commit_of_one_line(client: TestClient, repo_path: Path):
    """The whole file, line for line, because "edit it in git if you prefer" stops
    being true the first time a table cell reformats somebody's frontmatter — and
    the git history is the audit trail, so an unreadable diff costs twice."""
    base = head(client)
    before = file_at(repo_path, base, PATH)

    commit = save(client, TASK, {"priority": 1}, base=base).json()["commit"]
    after = file_at(repo_path, commit, PATH)

    assert [
        (was, now)
        for was, now in zip(before.splitlines(), after.splitlines(), strict=True)
        if was != now
    ] == [("priority: 2", "priority: 1")]
    assert commit_at(repo_path, commit).author.name == "ann"


def test_editing_another_row_from_the_same_page_is_invisible(client: TestClient):
    """The common case on a table, where every row is edited from one rendered
    page: two people change two entities and neither is told anything. If this were
    a conflict, a table would be unusable with more than one person in it."""
    stale = head(client)
    save(client, OTHER, {"priority": 1})

    response = save(client, TASK, {"priority": 1}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "retried"
    assert response.json()["conflict"] is None
    assert index_of(client)["entities"][OTHER]["priority"] == 1  # not clobbered


def test_two_tabs_editing_one_cell_is_a_409_that_writes_nothing(
    client: TestClient, repo_path: Path
):
    """The only disagreement a person is allowed to be interrupted by. Nothing is
    committed, HEAD does not move, and the report names both values so the row can
    offer keep-mine or keep-theirs without another round trip."""
    stale = head(client)
    theirs = save(client, TASK, {"owner": "bo"}).json()["commit"]

    response = save(client, TASK, {"owner": "cy"}, base=stale)

    assert response.status_code == 409
    assert response.json()["commit"] is None
    assert "bo" in response.json()["conflict"] and "cy" in response.json()["conflict"]
    assert git_head(repo_path) == theirs
    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marker not in response.text


def test_a_page_that_never_advances_its_base_collides_with_itself(client: TestClient):
    """Why `test_a_committed_save_advances_the_page_base_commit` exists.

    Two edits to one cell from one tab, both sent against the commit the page was
    rendered at: the second is compared with the first and refused. Nobody else is
    involved, so a person would see a conflict with themselves and reasonably
    conclude the tool cannot be trusted.
    """
    stale = head(client)
    assert save(client, TASK, {"priority": 1}, base=stale).status_code == 200

    assert save(client, TASK, {"priority": 3}, base=stale).status_code == 409


NEW_TASK = {
    "kind": "task",
    "title": "Per-field delta tolerances",
    "parent": PITCH,
    "status": "todo",
    "owner": "ann",
    "reviewers": ["bo"],
    "effort_weeks": 1.0,
}


def test_the_new_control_creates_through_the_api_and_the_server_mints_the_id(
    client: TestClient, repo_path: Path
):
    """Minting server-side also means the id is unique without asking first, which
    is what lets the form post once rather than reserve-then-write."""
    response = create(client, NEW_TASK, body="Compare per field, not per file.\n")

    assert response.status_code == 201
    new_id = response.json()["id"]
    assert re.fullmatch(r"task-[0-9a-f]{6}", new_id)

    stored = file_at(repo_path, response.json()["commit"], f"tasks/{new_id}.md")
    assert f"id: {new_id}" in stored
    assert index_of(client)["entities"][new_id]["title"] == NEW_TASK["title"]


def test_an_id_sent_by_the_client_is_ignored_rather_than_honoured(
    client: TestClient, repo_path: Path
):
    """The form has no id control, but the absence of a control is not a guarantee —
    the guarantee is that a supplied id changes nothing about where the file
    lands."""
    response = create(client, {**NEW_TASK, "id": "task-ffffff"})

    assert response.status_code == 201
    assert response.json()["id"] != "task-ffffff"
    tasks = pygit2.Repository(str(repo_path))[response.json()["commit"]].tree["tasks"]
    assert "task-ffffff.md" not in [entry.name for entry in tasks]


def test_a_create_missing_its_gated_fields_comes_back_as_problems(
    client: TestClient, repo_path: Path
):
    """Every blocker at once, in the shape the form renders. One field per refusal
    would make creating a task a four-request conversation, and only blockers
    travel: a warning listed beside the reasons is indistinguishable from one, and
    a person who fixes it and is refused again learns the messages are noise."""
    base = git_head(repo_path)
    response = create(client, {"kind": "task", "title": "A half-formed idea", "status": "todo"})

    assert response.status_code == 422
    assert {p["field"] for p in response.json()["problems"]} >= {
        "owner",
        "reviewers",
        "effort_weeks",
    }
    assert {p["severity"] for p in response.json()["problems"]} == {"blocker"}
    assert git_head(repo_path) == base


def test_a_create_that_waives_review_is_accepted(client: TestClient):
    """The form's reviewers check has to agree with this one. Some work has nothing
    to review — reading a paper, a spike — and if the waiver did not pass here the
    honest answer for those would be to name a reviewer who is not one."""
    response = create(
        client,
        {
            "kind": "task",
            "title": "Read the IPDPS 2014 paper",
            "parent": PITCH,
            "status": "todo",
            "owner": "cy",
            "review_waived": True,
            "effort_weeks": 0.5,
        },
    )

    assert response.status_code == 201


def test_a_create_racing_another_write_is_still_one_commit(client: TestClient):
    """A create posts the page's base commit like every other write. The new file is
    at a path nobody else can have touched, so a stale base is retried rather than
    refused — but it is still compared, not assumed."""
    stale = head(client)
    save(client, TASK, {"priority": 1})

    response = create(client, NEW_TASK, base=stale)

    assert response.status_code == 201
    assert response.json()["outcome"] in ("committed", "retried")
    assert index_of(client)["entities"][TASK]["priority"] == 1  # not rolled back
