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
from openproj.render import EDITABLE, HUMAN, LABELS, PRIORITIES, STATUSES, render_static
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

    A label is written for a reader — `blockers`, `PRs`, `appetite` — and is not
    the field name. Where the two differ the column says which field it stands
    for, so this doubles as an assertion that every column declares itself.

    A sortable header now holds a `<button>`, and the two columns that are not
    sortable hold bare text, so the label cannot be matched as "everything up to
    the next tag" any more. Tags inside are stripped rather than forbidden: the
    contents of a header are a design decision and what a column *is* is not.

    `\\s` after the name, or `<thead>` is a `<th>` whose attributes are `ead` —
    it matched, swallowed the first real header, and the count came out right
    anyway because stripping the tags out of what it swallowed left that header's
    own label behind.
    """
    found = []
    for tag, inner in re.findall(r"<th(\s[^>]*)?>(.*?)</th>", html, re.S):
        declared = re.search(r'data-(?:col|sort|field)="([^"]+)"', tag or "")
        found.append(declared.group(1) if declared else re.sub(r"<[^>]*>", "", inner).strip())
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
    # Every kind's fields are on the page; which of them apply is `data-kinds`,
    # checked by test_a_field_only_one_kind_has_is_absent_from_the_others.
    for field in ("appetite_weeks", "shaped_by", "effort_weeks"):
        assert field in named, f"{field} is status-gated at creation and must be fillable"


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


def test_a_dropdown_on_either_form_offers_words_and_stores_identifiers(
    new_page: str, client: TestClient
):
    """The last of F11. `in_progress` is what git holds and the option's `value`
    keeps it, because that is what gets POSTed and PATCHed; the text beside it is
    what a person reads. The two closed sets on these forms — status and priority
    — were rendering the identifier as the option's words, on both the create form
    and the detail page, which is the one surface where somebody chooses a status
    by name rather than recognising a chip.

    Both forms, because they are one template: `_CONTROL` renders every control on
    each of them, and a fix that reaches only one of two pages built from one
    string is a fix that did not happen.
    """
    detail = client.get(f"/detail/{TASK}").text

    for page in (new_page, detail):
        for name, values in (("status", STATUSES), ("priority", PRIORITIES)):
            select = re.search(rf'<select name="{name}".*?</select>', page, re.S).group(0)
            offered = re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)</option>', select)
            assert [value for value, _ in offered] == list(values), name
            for value, word in offered:
                assert word.strip() == LABELS.get(value, HUMAN[value]), (name, value)
                assert value not in word, f"{value} is its own identifier, not a word"


def test_the_status_gate_is_written_on_the_controls_themselves(new_page: str):
    """The requiredness rules, carried by the form so it can check before posting.

    Requiredness is status-gated: permissive when an idea is captured, strict once
    work starts. An HTML `required` attribute cannot say that, because what is
    required depends on the status chosen in the same form a moment ago.

    Every status that demands the field, not the first one — the rules are a chain
    of `elif` and not a stack. Read cumulatively, `done` demanded an owner the
    validator forgives it, so the form refused to create exactly the entity the
    server would have accepted.

    Putting the gates on each control keeps the second copy honest: it is a
    declaration next to the field it governs rather than a branch buried in a
    script, and it is visible in the delivered page. That the copy is only a copy
    is the point of `test_the_server_refusal_is_shown_and_not_swallowed`.
    """
    for field, gates in (
        ("owner", "ready"),
        ("reviewers", "ready in_progress"),
        ("appetite_weeks", "ready"),
        ("shaped_by", "ready"),
        ("assigned_on", "in_progress"),
        ("prs", "done"),
    ):
        assert f'data-required-at="{gates}"' in control(new_page, field), field

    assert "data-required-at" not in control(new_page, "review_waived"), (
        "review_waived is the escape hatch from a rule, not a rule"
    )


def test_the_gates_are_the_validator_s_own_and_not_a_second_copy(new_page: str):
    """A hand-written map drifts the day somebody edits `_status_problems`, and the
    drift shows up as a form that refuses what the server accepts — or worse,
    accepts what it refuses. These are the validator's gates, run over a blank
    entity of each kind at each status.

    The derivation lives in `model` beside the rule it mirrors. `render` used to do
    it here by importing `model._status_problems` across the module boundary at
    import time, which handed the renderer the shape of a problem tuple; it asks
    `model.required_at()` now. A test may still know the private — that is the
    point of a cross-check — but the page may not.
    """
    from openproj.model import Pitch, Task, _status_problems, required_at
    from openproj.render import REQUIRED_AT, STATUSES

    assert REQUIRED_AT == required_at(), "the page prints the model's answer, not its own"

    for model, kind in ((Pitch, "pitch"), (Task, "task")):
        for status in STATUSES:
            blank = model(id=f"{kind}-000000", kind=kind, title="", status=status)
            demanded = {field for _, field, _, _ in _status_problems(blank) if field}
            for field in demanded:
                assert status in REQUIRED_AT[field], (status, field)

    assert "done" not in REQUIRED_AT["owner"], "done forgives the owner ready insists on"
    assert control(new_page, "status"), "and the control that moves the gates is on the page"


def test_a_field_only_one_kind_has_is_absent_from_the_others(client: TestClient):
    """A pitch has an appetite and a task has an effort, and asking for both makes
    the form a schema dump rather than a question. `shaped_by` is a pitch rule too,
    so a task blocked on a missing `shaped_by` would be nonsense.

    The page carries all three kinds and hides what does not apply, so that
    switching kind does not throw away a title somebody just typed. Each row says
    which kinds own it, and the server refuses the rest — the guarantee is on the
    side that writes the file, not in whichever controls a script left visible."""
    page = client.get("/new?kind=pitch").text
    found = re.findall(r'<dd data-kinds="([^"]*)">\s*<[^>]*name="([^"]+)"', page)
    owners = {field: kinds.split() for kinds, field in found}

    assert owners["appetite_weeks"] == ["pitch"]
    assert owners["shaped_by"] == ["pitch"]
    assert owners["effort_weeks"] == ["task"]
    assert owners["status"] == ["project", "pitch", "task"]


def test_the_server_refuses_a_field_the_kind_does_not_have(client: TestClient):
    """The page hides them; this is what stops them.

    `patch_text` writes every field into the frontmatter before the model parses
    it, so an `effort_weeks` on a pitch would sit in the file unread — present in
    git, invisible to the tool, and wrong the day somebody greps for it.
    """
    response = client.post(
        "/api/entity",
        json={"fields": {"kind": "pitch", "title": "x", "effort_weeks": 3}, "body": ""},
    )

    assert response.status_code == 422
    assert "effort_weeks" in response.json()["detail"]


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

    assert re.search(r"required-?[Aa]t", body), "the form must consult its own gate"
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

    commit = save(client, TASK, {"priority": "high"}, base=base).json()["commit"]
    after = file_at(repo_path, commit, PATH)

    assert [
        (was, now)
        for was, now in zip(before.splitlines(), after.splitlines(), strict=True)
        if was != now
    ] == [("priority: medium", "priority: high")]
    assert commit_at(repo_path, commit).author.name == "ann"


def test_editing_another_row_from_the_same_page_is_invisible(client: TestClient):
    """The common case on a table, where every row is edited from one rendered
    page: two people change two entities and neither is told anything. If this were
    a conflict, a table would be unusable with more than one person in it."""
    stale = head(client)
    save(client, OTHER, {"priority": "high"})

    response = save(client, TASK, {"priority": "high"}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "retried"
    assert response.json()["conflict"] is None
    assert index_of(client)["entities"][OTHER]["priority"] == "high"  # not clobbered


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
    assert save(client, TASK, {"priority": "high"}, base=stale).status_code == 200

    assert save(client, TASK, {"priority": "low"}, base=stale).status_code == 409


NEW_TASK = {
    "kind": "task",
    "title": "Per-field delta tolerances",
    "parent": PITCH,
    "status": "ready",
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
    response = create(client, {"kind": "task", "title": "A half-formed idea", "status": "ready"})

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
            "status": "ready",
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
    save(client, TASK, {"priority": "high"})

    response = create(client, NEW_TASK, base=stale)

    assert response.status_code == 201
    assert response.json()["outcome"] in ("committed", "retried")
    assert index_of(client)["entities"][TASK]["priority"] == "high"  # not rolled back


def test_the_bold_column_is_the_one_being_sorted_by(page: str):
    """Bold used to land on `prs` for the accidental reason that it was the one
    column with no sort key, so it fell through to the browser's default `th`
    weight — the one column you cannot sort by looked like the sorted one."""
    assert "th { color: var(--muted); font-weight: 400;" in page
    assert "th.sorted" in page
    # Inside draw(), not once at load: sorting redraws without reloading, so a
    # marker set from the URL at load stays on whatever the page opened with.
    body = re.search(r"function draw\(\) \{.*?\n\}", page, re.S).group(0)
    assert re.search(r"classList\.toggle\('sorted', th\.dataset\.sort === sort\)", body)


def test_the_search_box_is_not_the_tenth_filter(page: str):
    """One search box beside nine dropdowns reads as the first dropdown."""
    assert re.search(r'<input id="q"[^>]*>\s*<div class="facets">', page)


def test_the_table_sizes_itself_to_its_contents_and_the_window(page: str):
    """Measured on one line, so a column is as wide as its widest value needs.

    Only prs and tags may wrap — a row with three PR references on one line is
    wider than the window on its own — and they split whatever is left.
    """
    assert ".measuring th, .measuring td { white-space: nowrap; }" in page
    assert "const WRAPS = new Set(['prs', 'tags']);" in page
    stored = r"if \(Object\.keys\(WIDTHS\)\.length\) applyWidths\(\); else fitWidths\(\);"
    assert "const keyOf = th => th.dataset.col;" in page, (
        "a width belongs to a column — not to a position in the row, and not to "
        "the word printed above it"
    )
    assert re.search(stored, page), "a width somebody dragged must survive the automatic fit"


def test_creating_is_the_detail_page_with_nothing_in_it(new_page: str, client: TestClient):
    """Same markup, same controls, same stylesheet.

    A second, differently-shaped form for creating is what made the tool feel like
    two tools: the facts list here has to be the facts list there, or the layout
    moves under you between reading an entity and making one.
    """
    detail = client.get(f"/detail/{TASK}").text

    for shape in ('<dl id="facts">', 'class="field title-field"', 'class="field bodybar"',
                  'class="field body-field"', 'id="preview"'):
        assert shape in new_page, shape
        assert shape in detail, shape
    assert "<label>" not in new_page, "the old flat list of labelled controls is gone"


def test_the_kind_is_a_dropdown_and_switching_keeps_what_was_typed(new_page: str):
    """It was three links, and following one was a fresh page — so a title typed
    before realising it should be a pitch was a title typed twice."""
    assert '<select id="kind">' in new_page
    assert "make a" not in new_page, "the links this replaced"
    assert re.search(r"KIND\.onchange = showKind", new_page)
    assert "location.href" not in re.search(r"function showKind.*?\n\}", new_page, re.S).group(0)


def test_every_reference_on_the_create_form_is_offered_and_not_remembered(new_page: str):
    """owner, assignees, reviewers, parent, cycle and blocked_by all point at
    something that already exists. Typed from memory a login is a typo, an id is a
    dangling reference the validator rejects after the save rather than before it,
    and a cycle number is off by one as often as it is right.

    The detail page has had the combobox since it had a form; the create page —
    the one place where everything is empty and nothing can be copied off the row
    above — was six free-text boxes."""
    for field, source in (
        ("owner", "people"),
        ("assignees", "people"),
        ("reviewers", "people"),
        ("parent", "entities"),
        ("cycle", "cycles"),
        ("depends_on", "entities"),
    ):
        assert f'data-suggest="{source}"' in control(new_page, field), field

    # And the widget that reads them is on the page, wired to every one at once.
    assert "for (const input of document.querySelectorAll('[data-suggest]'))" in new_page
    suggestions = json.loads(
        re.search(r'<script id="suggest"[^>]*>(.*?)</script>', new_page, re.S).group(1)
    )
    assert {"people", "entities", "cycles"} <= set(suggestions)
    assert [entry["value"] for entry in suggestions["people"]] == ["ann", "bo", "cy"]


def test_the_form_says_which_fields_the_chosen_status_demands(new_page: str):
    """The gates were a dict in `render.py` and nothing on screen said so: the first
    a person heard of a gate was a refusal after pressing Create.

    Marked on the label and re-marked when the status select moves, because what
    is required changes under you the moment it does."""
    facts = re.search(r'<dl id="facts">(.*?)</dl>', new_page, re.S).group(1)
    # The word is inside a `<label for>` now: a `<dt>`/`<dd>` pair is a caption to
    # a reader and two unrelated blocks of text to everything else, so the name a
    # control answers to is the label element and the mark follows it.
    marked = re.findall(
        r"<dt[^>]*><label for=\"[^\"]+\">([^<]+)</label>\s*"
        r"<span class=\"req\" hidden>required</span>",
        facts,
    )

    assert {"Owner", "Reviewers", "Assigned on", "PRs"} <= set(m.strip() for m in marked)
    assert "Tags" not in marked, "a field no status demands carries no mark"
    # Only in the form, and only for the status in force: the mark is toggled, and
    # a mark that could not be taken off would be an asterisk beside every field.
    assert "mark.hidden = !demanded" in new_page
    assert "form.addEventListener('change', () => markRequired(form));" in new_page
    assert "article.entity:not(.editing) .req { display: none; }" in new_page


def test_the_create_button_follows_the_form_it_commits(new_page: str):
    """It sat above the title, so the last thing on screen after filling a form in
    was the body textarea and the action was a scroll back up. The bar is sticky,
    so it is reachable from wherever the form has got to."""
    assert new_page.index('id="commitbar"') > new_page.index('<dl id="facts">')
    assert new_page.index('id="commitbar"') > new_page.index('class="field body-field"')
    assert re.search(r"\.commitbar \{[^}]*position: sticky; bottom: 0", new_page, re.S)
    assert '<p class="editbar">' not in new_page, "the bar it replaced"


def test_the_columns_and_the_cells_agree_on_their_order(page: str):
    """They were two hand-maintained lists, index-parallel, with nothing enforcing
    it: edit one and every cell shifts a column left of where its header says it
    is. Both are emitted from `_TABLE_COLUMNS` now, and this is what says so."""
    from openproj.render import _TABLE_COLUMNS, _TABLE_DERIVED

    headers = columns(page)
    listed = json.loads(re.search(r"const keys = (\[.*?\]);", page, re.S).group(1))

    assert headers == listed == [name for name, _ in _TABLE_COLUMNS]
    # And every column the payload withholds an editor for is one of them: a
    # derived name that is not a drawn column withholds an editor from nothing.
    assert set(_TABLE_DERIVED) <= set(listed)


def test_a_column_header_is_the_label_map_s_word_for_the_field(page: str):
    """The header words were a literal list beside the central map F11 asked
    everything to go through, so `size` was headed `appetite` in one place and
    `Appetite` in the other — same words, two sources, and only one of them moves
    when the word does. Read off the rendered header rather than off the map, or
    the assertion is the map compared with itself."""
    from openproj.render import _TABLE_COLUMNS

    for name, _ in _TABLE_COLUMNS:
        header = re.search(rf'<th data-col="{name}"[^>]*>(.*?)</th>', page, re.S).group(1)
        assert LABELS[name] in re.sub(r"<[^>]*>", "", header), name


def test_assignees_is_a_column_and_a_filter_and_a_value(page: str, client: TestClient):
    """Three sites, and missing any one of them fails quietly rather than loudly:
    a column with no payload key renders blank on every row until somebody edits
    it, and a dropdown missing from the client-side filter changes the URL and
    filters nothing."""
    payload_json = json.loads(re.search(
        r'<script id="payload"[^>]*>(.*?)</script>', page, re.S).group(1))
    row = next(iter(payload_json["rows"].values()))
    offered = re.findall(r'<select data-field="([^"]+)"', page)
    filtered = re.search(r"const FILTERS = \[(.*?)\];", page, re.S).group(1)

    assert "assignees" in columns(page)
    assert "assignees" in row
    assert "assignees" in offered
    assert set(offered) - {"predicate"} <= set(re.findall(r"'([^']+)'", filtered))


def test_a_status_column_sorts_the_way_work_moves(page: str):
    """Sorted as text, `done` heads the column and `shaping` sits second from
    last — the reverse of the order work moves in, for four of the five."""
    assert re.search(r"const rank = DATA\.choices\[sort\];", page)
    payload_json = json.loads(re.search(
        r'<script id="payload"[^>]*>(.*?)</script>', page, re.S).group(1))

    assert payload_json["choices"]["status"] == list(STATUSES)
    assert payload_json["choices"]["priority"] == list(PRIORITIES)


# --------------------------------------------------------------------------- #
# 4. What the table says about itself
#
# The rows are drawn by the page's own JavaScript, so most of what follows reads
# the delivered stylesheet — which IS the design — or the shape of the code that
# builds a cell. Where an assertion stands in for a browser decision its
# docstring says so; every one of these was also driven in a real browser against
# both the seed corpus and the frozen one before it was written down.
# --------------------------------------------------------------------------- #


def test_a_status_is_a_chip_and_a_kind_rides_with_the_id(page: str):
    """The `--st-*` tokens were used by the graph and the timeline only, so the
    one view people live in was the one view with no colour language at all. Kind
    was worse: filterable in the control bar, visible nowhere, and readable only
    by decoding the id's prefix.

    The word is always inside the chip, so the colour is redundant encoding.
    """
    body = script(page)

    assert re.search(r'class="chip st-\$\{esc\(row\.status\)\}"', body), "a status is a chip"
    assert re.search(r'class="chip kind-\$\{esc\(row\.kind\)\}"', body), "so is a kind"
    assert "esc(human(row.status))" in body and "esc(human(row.kind))" in body, (
        "the chip carries the word, not the identifier"
    )
    for rule in (".chip.st-in_progress", ".chip.kind-project", ".chip.kind-task"):
        assert rule in page, rule


def test_every_identifier_a_filter_offers_is_shown_as_a_word(page: str):
    """`in_progress` and `missing_required_fields` are storage, not English, and
    the filter holding the second was labelled STATE — a word from nowhere in the
    domain. The option's value stays the identifier because that is what the
    client-side filter compares against; only the text a person reads changes."""
    assert '<option value="in_progress">In progress</option>' in page
    assert '<option value="missing_required_fields">Has a problem</option>' in page
    assert '<label class="facet">Flags' in page
    assert '<label class="facet">state' not in page

    # Including inside the editor a double-click opens, or picking "In progress"
    # from a cell would write the label back into the corpus.
    assert re.search(r'<option value="\$\{o\}"[^>]*>\$\{human\(o\)\}</option>', script(page))


def test_the_blocking_count_is_a_link_that_pluralises_and_mutes_at_zero(page: str):
    """"1 blocking problems" was not a link, never pluralised, and was drawn in
    the danger colour at zero — a number that cannot be acted on, shouting.

    It links at the predicate that means exactly what it counts, so the rows you
    land on are the rows the number counted.
    """
    assert re.search(r'<a id="blockers" href="\?predicate=has_blocker"', page)
    assert re.search(r'id="blocker-count">\d+<', page), "the count is the element's own text"

    body = script(page)
    assert "blocking problem${BLOCKERS === 1 ? '' : 's'}" in body
    assert "classList.toggle('none', BLOCKERS === 0)" in body
    assert "#blockers.none { color: var(--muted); }" in page
    assert "#blockers { color: var(--sev-blocker);" in page


def test_the_blocking_count_names_the_population_its_link_opens():
    """"5 blocking problems" opening a table of 2 rows is the exact way a count
    stops being trusted, and it is what this said.

    The number counts *problems*; `?predicate=has_blocker` matches *entities*, and
    one entity can carry three of them. So both numbers are on the label and the
    second one is the promise the link has to keep.
    """
    from openproj.model import Config, Task
    from openproj.render import render_table

    # Two entities, five blockers between them: ready needs an owner, a reviewer
    # and an effort, and one of the three is filled in on the second.
    nameless = Task(id="task-000001", kind="task", title="Ready and nameless",
                    status="ready")
    fine = Task(id="task-000002", kind="task", title="Fine", status="ready",
                owner="ann", reviewers=["bo"], effort_weeks=1)
    half = Task(id="task-000003", kind="task", title="Half named", status="ready",
                owner="ann")
    index = build_index([nameless, fine, half], Config(), date(2026, 8, 17))

    problems = [p for p in index.problems if p.severity == "blocker"]
    entities = {p.entity_id for p in problems}
    assert len(problems) == 5 and len(entities) == 2, "the two numbers must differ"

    page = render_table(index)
    payload = json.loads(re.search(r'id="payload"[^>]*>(.*?)</script>', page, re.S).group(1))
    matched = {i for i, row in payload["rows"].items() if "has_blocker" in row["predicates"]}

    assert matched == entities, "the filter is the population the label names"
    assert f'id="blocker-count">{len(problems)}<' in page
    assert f">blocking problems on {len(matched)} entities</span>" in page

    # And the script rebuilds the same sentence after a save, off the same pass
    # that decides the predicate.
    body = script(page)
    assert "BLOCKED = Object.values(TROUBLE).filter(severity => severity === 'blocker').length;" \
        in body
    assert "on ${BLOCKED} ` +" in body


def test_a_title_somebody_typed_never_becomes_markup():
    """`<`, `&` and a quote are ordinary characters in a title, and each of them
    ends something in HTML.

    Every cell is built by string concatenation out of the payload and every field
    went in raw — sitting beside timeline code that escapes exactly the same data,
    which is one plan and two levels of care. Two ways in, so two assertions: the
    block the payload travels in, and the cell the script builds out of it.
    """
    from openproj.model import Config, Task
    from openproj.render import render_table

    hostile = 'Fix <b>&"the" </script><img src=x> equator'
    entity = Task(id="task-000001", kind="task", title=hostile, owner='a"b',
                  effort_weeks=1, tags=["<i>one", "two&three"], prs=["C2SM/icon4py#1"])
    index = build_index([entity], Config(), date(2026, 8, 17))
    page = render_table(index, base_commit="0" * 40)      # the editor is a way in too

    # The payload. `json.dumps` leaves `<` alone, so `</script>` in a title closed
    # the block it was travelling in and everything after it became live markup.
    raw = re.search(r'<script id="payload"[^>]*>(.*?)</script>', page, re.S).group(1)
    assert json.loads(raw)["rows"]["task-000001"]["title"] == hostile, "and reads back whole"
    assert "<" not in raw and ">" not in raw, "escaped as \\u003c, which is still JSON"

    # The cells. Every interpolation of stored text goes through the one helper,
    # which escapes the same four characters the timeline's does.
    body = script(page)
    assert "const esc = value => String(value ?? '').replace(/[&<>\"]/g," in body
    assert "attr(" not in body, "one helper for cells and attributes, not two standards"
    for interpolation in (
        "${esc(row.title)}",            # the title cell, which is also a link
        "${esc(row.id)}",               # and the href it is a link to
        "return esc(stored(row, key));",  # owner, assignees, reviewers, dates
        "${esc(human(row.status))}",
        "${esc(human(row.kind))}",
        "${esc(ref)}",                  # a PR reference, repo and number both
        "${esc(was)}",                  # and the value the editor opens with
    ):
        assert interpolation in body, interpolation
    assert "const tags = (list || []).map(esc);" in body

    # Nothing typed reaches the page as markup by either route.
    assert "<b>&" not in page and "<i>one" not in page


def test_a_problem_marks_the_row_and_the_cell_that_caused_it(page: str):
    """The reason a row is a problem lived in a native `title` on the `<tr>`, and
    a table is not a thing anybody hovers to find out.

    A field the table has no column for — `shaped_by`, `effort_weeks` — still has
    to be findable, so its complaint falls to the id cell. A glyph on a column
    nobody can see is a row that says something is wrong and will not say what.
    """
    body = script(page)

    assert "sev-row-${SEV_CLASS[worst]}" in body, "the row carries its worst severity"
    assert "sev-cell-' + SEV_CLASS[mark.severity]" in body
    glyph = r'class="sev-mark sev-mark-\$\{SEV_CLASS\[mark\.severity\]\}" role="img"'
    assert re.search(glyph, body)
    assert 'aria-label="${esc(note)}"' in body, "the glyph's name is the message"
    assert "const MARK_COLUMN = {effort_weeks: 'size'," in body
    assert "keys.includes(problem.field) ? problem.field : 'id'" in body


def test_an_empty_table_says_which_of_the_three_empties_it_is(page: str):
    """Filtered to nothing, an empty plan and a payload that did not survive the
    trip all rendered as a header row over a void, which reads as a broken app
    whichever one it is — and each wants something different done about it.

    The message goes inside the tbody: an empty table with its explanation
    somewhere else is still a header row over a void.
    """
    body = script(page)

    assert "'No entity matches these filters.'" in body
    assert "'This plan has no entities yet.'" in body
    assert "'The plan could not be loaded.'" in body
    assert re.search(r'<tr class="nothing"><td colspan=', body), "inside the body, not beside it"
    # The load failure is a real state, not a comment: the payload is parsed
    # defensively and the page keeps working with nothing in it.
    assert re.search(r"try \{\s*DATA = JSON\.parse", body)
    assert "const LOADED = DATA !== null;" in body


def test_clearing_the_filters_is_a_button_and_never_a_form_field(page: str):
    """`test_the_static_export_offers_no_editing_at_all` asserts a rendered file
    has no named control at all, so a Clear that posted a `name=` would make the
    export claim to be editable. It is also not a tenth dropdown: it appears only
    where the emptiness it explains is."""
    body = script(page)

    assert 'id="clear-filters"' in body
    bar = re.search(r'<div id="controls">.*?</div>\s*</div>', page, re.S).group(0)
    assert "clear-filters" not in bar
    assert 'name="clear' not in page
    # The sort is not a filter: losing the column you sorted by would be a second
    # surprise on top of the one you were undoing.
    cleared = (r"for \(const field of \[\.\.\.FILTERS, \.\.\.onPage, 'predicate', 'q'\]\)"
               r" params\.delete")
    assert re.search(cleared, body)
    # And every control the page draws, not only the entity fields: the people
    # page filters by role, which is not a field of an entity and was left set.
    assert "document.querySelectorAll('select[data-field]')]\n    .map(select" in body


def test_a_sortable_header_is_a_button_that_says_which_way_it_sorts(page: str):
    """`th` had no role, no `aria-sort` and nothing to tab to, so sorting was
    mouse-only and the direction was invisible — the same column looked identical
    sorted either way.

    The listener stays on the header so a click anywhere in the cell still sorts;
    the button's Enter and Space arrive there by bubbling. Proxy for a browser
    pressing Enter on a focused header.
    """
    headers = re.findall(r"<th(\s[^>]*)?>(.*?)</th>", page, re.S)
    sortable = [(tag, inner) for tag, inner in headers if "data-sort" in (tag or "")]

    assert len(sortable) == 12, "every column but prs and tags sorts"
    for tag, inner in sortable:
        assert 'aria-sort="none"' in tag, tag
        assert "<button type=" in inner, inner
        assert 'class="dir"' in inner, "somewhere to draw the direction"

    body = script(page)
    announced = "th.setAttribute('aria-sort', here ? (descending ? 'descending' : 'ascending')"
    assert announced in body
    assert re.search(r"\.dir'\)\.textContent = here \? \(descending \? '▾' : '▴'\) : ''", body)


def test_the_header_and_the_two_identity_columns_stay_put(page: str):
    """A ~1670px table scrolled right is fourteen columns of values belonging to
    nobody, and scrolled down it is fourteen columns with no names.

    Both need a ground of their own and a layer above the cells passing under
    them, and the header needs a bounded container to be sticky inside at all —
    a container the height of its own content gives `top: 0` nothing to hold
    against.
    """
    # Named, not a bare number: 15rem is a measurement of the stack above the rows
    # — nav, heading, edit bar, summary, facets — and it has already been wrong
    # once, when the page gained a heading and the box ran off the bottom.
    assert "--above-rows: 15rem;" in page
    assert "max-height: calc(100vh - var(--above-rows))" in page, (
        "the body scrolls in the container"
    )
    assert "thead th {\n  position: sticky; top: 0; z-index: 3; background: var(--surface);" in page
    assert '[data-col="id"] { position: sticky; left: 0; z-index: 1;' in page
    assert '[data-col="title"] { position: sticky; left: var(--sticky-1, 0px); z-index: 1;' in page
    assert "thead [data-col=\"id\"], thead [data-col=\"title\"] { z-index: 4; }" in page
    # A collapsed border is not painted on a sticky cell; the row scrolls over it.
    assert "box-shadow: inset 0 -1px 0 var(--line);" in page

    body = script(page)
    assert "table.style.setProperty('--sticky-1'" in body, (
        "the second column begins where the first ends, and that width is dragged"
    )


def test_the_narrow_layout_drops_the_columns_that_are_lookups(page: str):
    """The only media query in the app was `prefers-color-scheme`. Fourteen
    columns below 1100px means fourteen columns too narrow to read; the three
    that go are reachable on the detail page and still filterable above."""
    narrow = re.search(r"@media \(max-width: 1100px\) \{(.*?)\n\}", page, re.S).group(1)

    for column in ("reviewers", "prs", "tags"):
        assert f'[data-col="{column}"]' in narrow, column
    assert "display: none" in narrow
    # Every cell declares its column, or the rule above would have to count them.
    assert 'return `<td data-col="${key}"' in script(page)
    # A dropped column is not part of the table's width, or the table is set
    # wider than the columns it draws.
    assert "if (th.offsetParent === null) { th.style.width = ''; return; }" in script(page)


def test_the_tags_cell_is_one_line_with_the_rest_behind_a_count(page: str):
    """Five tags wrapped to five lines and every row on screen grew to match, so
    the column with the least in it set the height of the table.

    The count is exact rather than "however many did not fit": one tag is shown
    and `+N` is the number you cannot see. No row padding changes anywhere — this
    is about removing height, not adding it.
    """
    assert "td.tags { white-space: nowrap; overflow: hidden; }" in page
    assert "td.tags .rest { display: none; }" in page
    assert "td.tags.open .rest { display: inline; }" in page
    assert "td.tags.open .more { display: none; }" in page
    assert "padding: .3rem .5rem" in page, "the row keeps the padding it had"

    body = script(page)
    assert re.search(r'aria-label="Show \$\{rest\.length\} more tag', body), (
        "the reveal has a name, not only a plus sign"
    )
    assert "more.closest('td').classList.add('open')" in body
    # It is a control inside an editable cell, so it must not also open the editor.
    assert "event.target.closest('button.more')) return;" in body


def test_an_editable_cell_shows_it_and_a_derived_one_says_why_not(page: str):
    """Editable and computed cells were identical, and the only affordance on the
    page was a 12px hint at the top of it. A derived cell that silently swallows a
    double-click is indistinguishable from a cell that is broken."""
    assert "td.edit { cursor: cell; }" in page
    assert "td.edit:hover { background: var(--surface-2);" in page

    body = script(page)
    assert "'Double-click to edit ' + named" in body, "and a description, not only a colour"
    # Shipped from `_TABLE_WHY`, whose keys ARE `_TABLE_DERIVED`. Written out again
    # in the script, a fifth derived column would arrive with no class and refuse
    # with `undefined` — a cell that will not be edited and will not say why.
    from openproj.render import _TABLE_DERIVED

    why = json.loads(re.search(r"const WHY = (\{.*?\});", body, re.S).group(1))
    assert set(why) == set(_TABLE_DERIVED)
    assert all(sentence.strip() for sentence in why.values())
    assert "data-why=\"${esc(WHY[key])}\"" in body
    # Through `announce`, so the refusal reaches somebody who cannot see the bar
    # it is drawn in — and from Enter as well as from a double-click.
    assert "function refuse(cell) {\n  announce(cell.dataset.why);" in body
    assert "if (computed) refuse(computed);" in body


def test_the_page_never_reports_its_own_write_to_itself(page: str, client: TestClient):
    """`mine` was decided by the entity in the URL, which the table has none of,
    so every save from this page came back as "The plan changed" one keystroke
    after making it — and a banner that fires on your own typing is wallpaper.

    The commit is the handshake: the sha the PATCH returned is the sha announced.
    The write is declared *before* it is sent because the server announces to the
    stream before it answers the request, so the news can arrive first.
    """
    body = script(page)

    assert "dispatchEvent(new Event('openproj:writing'));" in body
    assert "dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));" in body
    assert "committed = answer.commit;" in body
    # Announced even when refused, or one 409 holds every later event forever.
    assert re.search(r"\} finally \{.*?openproj:wrote", body, re.S)

    assert "window.SHOWING = Object.keys(DATA.rows);" in body, (
        "the table has no id in its URL, so it says what it is looking at"
    )

    shell = script(client.get(f"/detail/{TASK}").text)
    assert "if (movedOurs.has(commit)) return;" in shell
    assert "if (movedWriting) movedHeld.push(message); else showMoved(message);" in shell
    # The shell's *reader*, which passed while nothing on the detail page ever set
    # it. The writer is asserted where it lives, in test_web.
    assert "const showing = window.SHOWING || (here ? [here] : []);" in shell


def test_a_write_refreshes_the_count_and_the_markers_in_place(page: str):
    """The validator runs on the server, so what a save did to the problems is not
    something the page can work out — it left the count and the row markers stale
    until somebody reloaded, which is exactly when a count stops being read.

    Only the problems are re-read. Dates are a forecast, and re-forecasting under
    somebody who is mid-edit is worse than being one reload behind.
    """
    body = script(page)

    assert "await fetch('/api/index.json')" in body
    assert "regroup((await response.json()).problems);" in body
    assert re.search(r"await refreshProblems\(\);\s*\n\s*draw\(\);", body)
    assert "/healthz" not in body, "re-reading HEAD before a save discards the collision"


def test_the_grouping_of_problems_is_written_once(page: str):
    """The payload carries the flat list the validator produced, not a copy
    stapled to every row. Grouped on the server as well, the table would have had
    two aggregations — one rendered into the rows and one rebuilt after each save
    — and only the first would ever have been tested."""
    carried = payload(page)

    assert isinstance(carried["problems"], list)
    assert {"severity", "entity_id", "field", "message"} <= set(carried["problems"][0])
    assert "problems" not in next(iter(carried["rows"].values())), (
        "one list, not one per row"
    )
    # The two predicates that read the problem list are recomputed with it.
    assert "row.predicates.push('missing_required_fields');" in script(page)
    assert "row.predicates.push('has_blocker');" in script(page)


# --------------------------------------------------------------------------- #
# Reaching the grid without a mouse
# --------------------------------------------------------------------------- #


def test_a_cell_can_be_edited_without_a_mouse(page: str):
    """The app's primary editing surface was double-click-only, so half the room
    could not change a single field on it.

    One tab stop for the whole grid and the arrows moving inside it, because
    fourteen columns times forty rows is 560 stops if every cell takes one —
    which is not a keyboard path, it is a maze.
    """
    body = script(page)

    assert '<table id="rows" role="grid">' in page, "the arrows belong to the page in a grid"
    assert "const reachable = EDITABLE && (editable || key in WHY);" in body
    assert "${reachable ? ' tabindex=\"-1\"' : ''}" in body
    assert "for (const td of all) td.tabIndex = td === at ? 0 : -1;" in body

    keys = re.search(r"tbody\.addEventListener\('keydown'.*?\n  \}\);", body, re.S).group(0)
    assert "event.key === 'Enter' || event.key === 'F2'" in keys, "both, because both are tried"
    assert "openEditor(cell)" in keys
    assert "ArrowLeft" in keys and "ArrowRight" in keys
    assert "ArrowUp" in keys and "ArrowDown" in keys
    # The mouse path is untouched: it opens the same editor.
    mouse = re.search(r"tbody\.addEventListener\('dblclick'.*?\n  \}\);", body, re.S).group(0)
    assert "event.target.closest('td.edit')" in mouse and "openEditor(cell)" in mouse


def test_the_editor_discards_on_escape_and_commits_on_tab(page: str):
    """Escape is discard and Tab is commit-and-move, the way every grid behaves.

    Both have to survive the redraw a save causes: `saveCell` rebuilds every row,
    so the cell that had focus no longer exists by the time the keyboard needs to
    go back to it.
    """
    body = script(page)
    editor = re.search(r"input\.onkeydown = e => \{.*?\n  \};", body, re.S).group(0)

    assert "if (e.key === 'Enter') { RETURN = true; input.blur(); }" in editor
    assert "abandoned = true;" in editor, "Escape discards rather than saving the partial value"
    assert "if (e.key === 'Tab')" in editor and "e.preventDefault();" in editor
    assert "e.shiftKey ? -1 : 1" in editor, "and backwards"
    # The place is a row id and a column, not an element: the element is gone.
    assert re.search(r"AT = \{id: cell\.parentNode\.dataset\.id,\s*\n\s*col:", editor)
    assert "const held = EDITABLE && (RETURN || !!focused);" in body
    assert "if (focused && !RETURN) rove(focused);" in body, "back to where it is, not where it was"
    assert "if (EDITABLE) { rove(null, held); RETURN = false; }" in body


def test_the_editor_a_cell_opens_says_what_it_is_editing(page: str):
    """A box conjured inside a cell inherits nothing from the header above it. It
    was an unnamed input on top of the one thing that said which column it was."""
    body = script(page)

    assert "const named = esc(FIELD_LABELS[field] || field);" in body
    assert '<select data-type="text" aria-label="${named}">' in body
    assert 'data-type="${EDITABLE[field]}" aria-label="${named}"' in body


def test_the_suggestion_popup_announces_itself(page: str):
    """The keyboard already worked — arrows moved a highlight, Enter picked it —
    and none of it reached a screen reader: a highlight drawn with a class is a
    highlight only a sighted reader can follow, and the popup was a bare `<ul>`
    nobody was told had opened."""
    body = script(page)

    assert "input.setAttribute('role', 'combobox');" in body
    assert "input.setAttribute('aria-autocomplete', 'list');" in body
    assert "input.setAttribute('aria-controls', id);" in body
    assert "list.setAttribute('role', 'listbox');" in body
    assert '<li id="${id}-${i}" role="option"' in body
    # Open and shut, said out loud both ways.
    assert "input.setAttribute('aria-expanded', String(!list.hidden));" in body
    assert "input.setAttribute('aria-expanded', 'false');" in body

    # Which option is current, without moving focus off the box being typed in.
    highlight = re.search(r"function highlight\(\) \{.*?\n  \}", body, re.S).group(0)
    assert "item.setAttribute('aria-selected', String(i === active));" in highlight
    assert "input.setAttribute('aria-activedescendant', items[active].id);" in highlight
    assert "input.removeAttribute('aria-activedescendant');" in highlight
    # The arrows go through it rather than toggling the class themselves, or the
    # announcement and the highlight are two things that can disagree.
    arrows = re.search(r"if \(event\.key === 'ArrowDown' \|\| event\.key === 'ArrowUp'\).*?\n"
                       r"    \} else", body, re.S).group(0)
    assert "highlight();" in arrows and "classList" not in arrows
    # One counter for the page: `aria-controls` is a reference by id, and the
    # detail form carries a dozen of these.
    assert "let SUGGEST_N = 0;" in body and "'suggest-' + (++SUGGEST_N)" in body


def test_every_control_on_the_create_form_has_a_name(new_page: str):
    """A `<dt>`/`<dd>` pair is a caption to a reader and two unrelated blocks of
    text to everything else, so not one control on this form had a name."""
    facts = re.search(r'<dl id="facts">(.*?)</dl>', new_page, re.S).group(1)
    named = dict(re.findall(r'<label for="([^"]+)">([^<]+)</label>', facts))

    assert named, "the labels are the whole of the fix"
    for control_id, word in named.items():
        # A label points at a control that is on the page, or it is a name the
        # reader is told about and cannot reach.
        assert re.search(rf'<(?:input|select|textarea)[^>]*\bid="{control_id}"', new_page), word
    for field in ("status", "owner", "assignees", "reviewers", "cycle", "priority"):
        assert f"new-{field}" in named, field
        assert named[f"new-{field}"] == LABELS[field]

    # The two boxes that are not facts: the title is the page's own heading and
    # the body is the document, so neither has a `<dt>` to hang a label on.
    assert re.search(r'<input name="title"[^>]*aria-label="Title"', new_page)
    assert re.search(r'<textarea name="body"[^>]*aria-label="Shaping document"', new_page, re.S)
    # And the page says what it is, which it did not: its `<h1>` was an empty
    # input.
    assert "<h1>New entity</h1>" in new_page
