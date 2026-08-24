"""The table as a writing surface: the contract, written before it is one.

Phase 1's table could be read, sorted and filtered, and that was all. Every field
that actually changes during a week — a status, an owner, a reviewer, a priority —
had to be changed one record at a time on a detail page, and there was no way to
bring a new record into existence from the UI at all. A plan that costs a page
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
import shutil
import subprocess
from datetime import date
from html import unescape
from pathlib import Path

import pygit2
import pytest
from browser import chrome, measured_in, pressed_in, screenshot
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import (
    ANN,
    OTHER,
    PATH,
    PITCH,
    PROJECT,
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
from openproj.model import (
    KIND_NAMES,
    PARENT_KINDS,
    RUNG,
    Config,
    Pitch,
    Project,
    Task,
    load_repo,
    unread_fields,
)
from openproj.render import (
    _TABLE_COLUMNS,
    EDITABLE,
    HUMAN,
    LABELS,
    PRIORITIES,
    STATUSES,
    _new_row_fields,
    render_static,
    render_table,
)
from openproj.web import SESSION_COOKIE, create_app

# The columns the table draws that nobody may type into. Kept as an expectation
# rather than computed silently, so that adding a derived column and forgetting to
# make it read-only fails here instead of in the corpus.
DERIVED = {"size", "start", "end", "blocked_by", "progress"}


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
    return client.get("/table").text


@pytest.fixture
def demo_page(demo_root: Path) -> str:
    """The shipped demo, rendered: a whole plan, with more than one name in a list
    on almost every row.

    The corpus above is four records and answers everything about markup, but a
    control that expands a whole column has almost nothing to say on a plan where
    a single cell hides anything — and the height this deliberately costs is a
    fact about a plan of that size. It is also the corpus `MEASURED` was read
    from, so the widths these tests squeeze the header to are the widths the fit
    works with.

    Nothing here assumes what is in it: the counts and the words are read back off
    the cells, and the one test that needs the row count takes `demo_plan_size`
    rather than writing the number down. It said "seventeen" for as long as the
    demo had seventeen rows in it, which was until somebody grew the demo.
    `seed/` is free to be rewritten, unlike the frozen corpus the scheduler's
    goldens are derived from.
    """
    from openproj.render import render_table

    records, config, _ = load_repo(demo_root)
    return render_table(build_index(records, config, date(2026, 8, 17)))


@pytest.fixture
def demo_plan_size(demo_root: Path) -> int:
    """How many rows the demo's table draws — read off the plan, never typed.

    The table body draws one row per record in `index.plan`, which is every rung
    the plan schedules and not `index.records` (issues and notes are off the
    plan and get their own pages).
    """
    records, config, _ = load_repo(demo_root)
    return len(build_index(records, config, date(2026, 8, 17)).plan)


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
    creating a record a different-shaped act from editing one; it is now the same
    layout as a detail page in edit mode."""
    return client.get("/new?kind=pitch").text


def create_form(html: str) -> str:
    match = re.search(r'<form[^>]*id="create".*?</form>', html, re.S)
    assert match, "the table must carry a form for creating a record"
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
    what the column shows is `person_weeks` *or an assumed default*, so a control
    on it would let somebody commit the assumption without meaning to.
    """
    assert set(columns(page)) - set(EDITABLE) - {"id"} <= DERIVED, (
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
    is the only way to retire a record.
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


def test_the_table_offers_a_way_to_create_a_record(page: str, client: TestClient):
    """Records are overwhelmingly born in the UI, so the UI has to be able to bear
    them. Without this the only supported way to add a task is to write a file by
    hand, which is the workflow this tool exists to replace."""
    assert re.search(r'href="/new"', page), "the table needs a way to reach the create page"
    assert client.get("/new").status_code == 200


def test_the_create_form_writes_only_fields_a_person_owns(new_page: str):
    """`kind` picks the directory and `body` is the shaping document; everything
    else on this form has to be a field `EDITABLE` names. A create that can set a
    field the detail page refuses to show is a back door into the schema."""
    # `hill-*` is a widget's grouping name and not a field: five radios need one
    # shared `name` to be one radio group to the browser, and none of them carries
    # `data-type`, which is what the form actually collects and sends. That is
    # asserted below rather than assumed, because the guard this test exists to be
    # is "nothing reaches the server that is not a field a person owns".
    named = controls(new_page) - {"base_commit"}
    grouping = {name for name in named if name.startswith("hill-")}
    for name in grouping:
        for tag in re.findall(rf'<input[^>]*\bname="{re.escape(name)}"[^>]*>', new_page):
            assert "data-type" not in tag, f"{name} is collected and sent, and is not a field"
    named -= grouping

    assert named - {"body"} <= set(EDITABLE)
    for field in ("title", "status", "owner", "reviewers", "review_waived", "parent"):
        assert field in named, field
    # Every kind's fields are on the page; which of them apply is `data-kinds`,
    # checked by test_a_field_only_one_kind_has_is_absent_from_the_others.
    for field in ("person_weeks", "shaped_by", "person_weeks"):
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


def test_the_kind_picker_offers_every_rung_and_only_rungs(new_page: str):
    """Derived on both sides: `KINDS` draws the options and the route refuses
    the rest, so a rung added to the ladder is creatable the day it lands
    rather than the day somebody remembers this select."""
    pick = re.search(r'<select id="kind">.*?</select>', new_page, re.S)
    assert pick, "the create page must carry the kind picker"
    assert options(pick.group(0)) == set(KIND_NAMES)


def test_the_create_page_is_the_record_page_in_a_mode(client: TestClient):
    """One template, one script, two verbs. The create form was forked markup
    once (`_NEW`), and a fork is what the issue and note pages proved a fork
    does — the note got the hill and the issue did not, in one commit. Which
    verb runs is data (`CREATING`), never a second page."""
    import openproj.render as render

    new = client.get("/new?kind=task").text
    detail = client.get(f"/detail/{TASK}").text

    assert not hasattr(render, "_NEW"), "the forked template is gone"
    assert not hasattr(render, "render_new"), "and so is its renderer"
    for html in (new, detail):
        assert "if (CREATING) { await createRecord(); return; }" in html
        assert "async function createRecord()" in html
    assert 'const CREATING = "task";' in new
    assert "const CREATING = null;" in detail, "a stored record's page creates nothing"


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_record_created_from_the_merged_page_round_trips(client: TestClient, kind: str):
    """The whole create flow per kind, through the page's own base commit: the
    page renders, the POST lands, and the record comes back as a page. The
    read-back is the record's own page, never /api/index.json — that map is
    plan-only by design and cannot answer for an unplanned rung. Parametrized
    over the ladder, so the rungs Task 8 adds walk through this door on the
    day they exist — if their server stamping is missing, this is the test
    that says so."""
    page = client.get(f"/new?kind={kind}")
    assert page.status_code == 200
    base = re.search(r'name="base_commit" value="([0-9a-f]{40})"', page.text).group(1)

    made = client.post(
        "/api/record",
        json={"base_commit": base,
              "fields": {"kind": kind, "title": f"Round trip {kind}"},
              "body": "A record made from the merged page.\n"},
    )
    assert made.status_code == 201, made.json()
    new_id = made.json()["id"]
    own = client.get(f"/detail/{new_id}")
    assert own.status_code == 200
    assert f"Round trip {kind}" in own.text, (
        "the record's own page is the read-back for every kind — "
        "/api/index.json is plan-only by design and cannot answer for an "
        "unplanned rung"
    )


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
        # Status is not a dropdown any more: it is the hill, and its stops carry
        # the same pairing — `value` is what git holds and the screen-reader text
        # beside it is what a person reads. Asked here rather than dropped,
        # because the pairing is the point of the test and not the `<select>`.
        stops = re.findall(
            r'<input type="radio"[^>]*value="([^"]+)"[^>]*data-word="([^"]+)"', page
        )
        assert [value for value, _ in stops] == list(STATUSES), "status"
        for value, word in stops:
            assert word != value, f"status: {value} is offered as its own identifier"

        for name, values in (("priority", PRIORITIES),):
            select = re.search(rf'<select name="{name}".*?</select>', page, re.S).group(0)
            offered = re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)</option>', select)
            assert [value for value, _ in offered] == list(values), name
            for value, word in offered:
                # The mark leads and the word follows, on both ladders. It is a
                # string and not markup because an `<option>` is a string, which
                # is also why the priority mark is a character rather than the
                # five-element meter it used to be.
                mark, _, said = word.strip().partition(" ")
                assert mark and mark not in said, (
                    f"{name}: {value} is offered as {word!r} with no mark in "
                    "front of it"
                )
                assert said == LABELS.get(value, HUMAN[value]), (name, value)
                assert value not in word, f"{value} is its own identifier, not a word"


def test_the_status_gate_is_written_on_the_controls_themselves(new_page: str):
    """The requiredness rules, carried by the form so it can check before posting.

    Requiredness is status-gated: permissive when an idea is captured, strict once
    work starts. An HTML `required` attribute cannot say that, because what is
    required depends on the status chosen in the same form a moment ago.

    Every status that demands the field, not the first one — the rules are a chain
    of `elif` and not a stack. Read cumulatively, `done` demanded an owner the
    validator forgives it, so the form refused to create exactly the record the
    server would have accepted.

    Putting the gates on each control keeps the second copy honest: it is a
    declaration next to the field it governs rather than a branch buried in a
    script, and it is visible in the delivered page. That the copy is only a copy
    is the point of `test_the_server_refusal_is_shown_and_not_swallowed`.
    """
    for field, gates in (
        ("owner", "ready"),
        ("reviewers", "ready in_progress"),
        ("person_weeks", "ready"),
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
    record of each kind at each status.

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
    """Asking every kind for every field makes the form a schema dump rather than
    a question. `shaped_by` is the pitch's alone — shaping is what a pitch gets,
    and a task blocked on a missing `shaped_by` would be nonsense — while a size
    belongs to a pitch and a task alike and a project has none, being a container.

    The page carries every kind and hides what does not apply, so that
    switching kind does not throw away a title somebody just typed. Each row says
    which kinds own it, and the server refuses the rest — the guarantee is on the
    side that writes the file, not in whichever controls a script left visible."""
    page = client.get("/new?kind=pitch").text
    found = re.findall(r'<dd data-kinds="([^"]*)">\s*<[^>]*name="([^"]+)"', page)
    owners = {field: kinds.split() for kinds, field in found}

    assert owners["person_weeks"] == ["pitch", "task"]
    assert owners["shaped_by"] == ["pitch"]
    # Every kind that reads a status AND is offered one here, in ladder order
    # and off the ladder. The container rung reads no status at all; the two
    # inbox kinds read one and are deliberately NOT offered it on this form —
    # the single status control is the plan ladder, `shaping` on an issue is a
    # word the server refuses, and a fresh inbox record opens at the server's
    # stamp (`web.opens_at`) instead. That absence is pinned from the other side
    # by `test_the_create_form_offers_an_issue_no_plan_status`. Derived rather
    # than listed, or this is one more copy of the ladder that goes stale the
    # day a rung is added — and spelled out once beneath, so the derivation
    # cannot drift along with the code it derives from.
    assert owners["status"] == [
        kind for kind in KIND_NAMES
        if "status" not in unread_fields(kind) and RUNG[kind].planned
    ]
    assert owners["status"] == ["project", "pitch", "task"]
    # And a field the top rung does not read is not offered on it: a product has
    # no owner and — since jcanton asked, 2026-08-20 — no status and no PRs
    # either, so each of those rows names the other three kinds.
    for field in ("owner", "status", "prs"):
        assert "product" not in owners[field], field


def test_the_server_refuses_a_field_the_kind_does_not_have(client: TestClient):
    """The page hides them; this is what stops them.

    `patch_text` writes every field into the frontmatter before the model parses
    it, so a `shaped_by` on a task would sit in the file unread — present in git,
    invisible to the tool, and wrong the day somebody greps for it.
    """
    response = client.post(
        "/api/record",
        json={"fields": {"kind": "task", "title": "x", "shaped_by": ["ann"]}, "body": ""},
    )

    assert response.status_code == 422
    assert "shaped_by" in response.json()["detail"]


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
    records, config, _ = load_repo(seed_root)
    render_static(build_index(records, config, date(2026, 8, 17)), tmp_path)
    exported = (tmp_path / "table.html").read_text(encoding="utf-8")

    assert not controls(exported)
    assert "base_commit" not in exported
    assert "/api/record" not in exported


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


def test_a_row_says_which_record_it_is_and_a_cell_says_which_field(page: str):
    """A PATCH needs both, and reading them off the DOM is what lets one listener
    serve every cell instead of a closure per cell. Proxy for a browser checking
    that the attributes are actually on the elements."""
    assert re.search(r"<tr[^>]*data-id=", script(page)), "a row must carry its record id"
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
    whether a rule applies to a record that does not exist yet. When the server
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
    beside the row instead, and as text: the report quotes record fields, so
    `innerHTML` would render whatever somebody happened to type into a title.

    Proxy for a browser checking which element it lands in; what is assertable here
    is that it never lands in a control's value.
    """
    body = script(page)

    assert not re.search(r"\.value\s*=[^;\n]*conflict", body, re.I)
    # `refusal(answer, 409)` as well as `answer.conflict`: the report is read out
    # of the answer by the shell's one helper now, because three other write
    # paths were reading a `detail` key a 409 does not carry.
    assert re.search(r"(textContent|innerText)\s*=[^;\n]*(conflict|refusal)", body, re.I), (
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
    page: two people change two records and neither is told anything. If this were
    a conflict, a table would be unusable with more than one person in it."""
    stale = head(client)
    save(client, OTHER, {"priority": "high"})

    response = save(client, TASK, {"priority": "high"}, base=stale)

    assert response.status_code == 200
    assert response.json()["outcome"] == "retried"
    assert response.json()["conflict"] is None
    assert index_of(client)["plan"][OTHER]["priority"] == "high"  # not clobbered


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


# A create that breaks no rule. `assignees` is here for the reason `owner` and
# `reviewers` are: a `ready` record is refused without it, and a create fixture
# that trips a gate makes every test using it a test about that gate.
NEW_TASK = {
    "kind": "task",
    "title": "Per-field delta tolerances",
    "parent": PITCH,
    "status": "ready",
    "owner": "ann",
    "assignees": ["ann"],
    "reviewers": ["bo"],
    "person_weeks": 1.0,
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
    assert index_of(client)["plan"][new_id]["title"] == NEW_TASK["title"]


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
        "person_weeks",
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
            "title": "Read the 2014 stable-summation paper",
            "parent": PITCH,
            "status": "ready",
            "owner": "cy",
            "assignees": ["cy"],
            "review_waived": True,
            "person_weeks": 0.5,
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
    assert index_of(client)["plan"][TASK]["priority"] == "high"  # not rolled back


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
    """One search box beside nine dropdowns reads as the first dropdown.

    It is on a line of its own above them — a line it now shares with whatever the
    view has to say about itself, which is the far end of the same row and not the
    next dropdown along.
    """
    assert re.search(r'<div class="searching">\s*<input id="q"[^>]*>', page)
    assert re.search(r'</div>\s*<div class="facets">', page)


def test_the_table_sizes_itself_to_its_contents_and_the_window(page: str):
    """Measured on one line, so a column is as wide as its widest value needs.

    The arithmetic that turns those measurements into widths is checked by
    running it, in `test_the_default_fit_never_needs_a_horizontal_scrollbar`
    below. This one pins the things around it: the measuring pass, the identity a
    width is stored against, and that a width somebody dragged is never overruled
    by a fit.
    """
    assert ".measuring th, .measuring td { white-space: nowrap; }" in page
    assert "const keyOf = th => th.dataset.col;" in page, (
        "a width belongs to a column — not to a position in the row, and not to "
        "the word printed above it"
    )
    assert re.search(r"function refit\(\) \{\s*if \(automatic\) fitWidths\(\);", page), (
        "a width somebody dragged must survive the automatic fit"
    )
    assert re.search(r"remembered\.set\(WIDTH_KEY[^\n]*\n\s*automatic = false;", page), (
        "and letting go of a grip is what ends the automatic one"
    )


def test_the_table_draws_its_rows_in_a_browser_that_refuses_storage(page: str):
    """A browser with storage denied does not answer null — it throws.

    Private windows, blocked cookies, a page inside a third-party frame and a
    handful of enterprise policies all raise on `localStorage` itself, before
    any method is called. The read that remembers dragged column widths was the
    second statement of the script that draws every row, so on those browsers
    the page everybody lives in was a heading and "17 of 17 shown" over an empty
    body — the whole plan invisible, with nothing said about why.

    Run, not grepped, and run twice. "It still drew something" is also what a
    fallback that quietly loses half the columns does, so the rows a denied
    browser draws have to be the same markup as the rows a working one draws,
    and every record has to be in them.
    """
    from test_injection import run_js

    working = run_js(page)
    denied = run_js(page, storage="denied")

    drawn = [written for written in denied["written"] if "<tr" in written]
    assert drawn, f"storage denied and the table drew nothing: {denied['errors']}"
    assert drawn == [written for written in working["written"] if "<tr" in written], (
        "a browser that refuses storage draws different rows from one that allows it"
    )
    for record_id in payload(page)["rows"]:
        assert record_id in drawn[0], f"{record_id} is missing from the denied browser's table"
    # And it got exactly as far: the widths it could not read are simply the
    # ones nobody dragged. Both runs stop at the same place, which is the shim's
    # own gap rather than anything storage did.
    assert denied["errors"] == working["errors"], (
        "the denied browser's script stopped somewhere the allowed one did not"
    )


def test_the_fit_is_measured_again_once_the_real_typeface_has_landed(page: str):
    """A first load and a reload must produce the same columns.

    The face is a `data:` URI with `font-display: swap`, so the layout the widths
    are measured from can still be the fallback's metrics — and then the first
    paint fits to numbers the second one does not reproduce, which is what
    "broken until I reloaded" looked like. `document.fonts.ready` is the moment
    the metrics stop moving.

    A browser is the only thing that can prove the two loads agree; what is
    assertable here is that the second measurement is asked for at all, and that
    it is skipped once the columns stop being the fit's to decide.
    """
    assert "document.fonts.ready.then(refit);" in page
    assert "addEventListener('resize', refit);" in page, (
        "a new window has to get a new fit, whoever decided the columns"
    )


# What each column needs with its widest cell on one line, read out of Chrome by
# `naturalWidths()` itself on the demo corpus. Numbers a browser produced, so
# they are written down rather than derived — but the *columns* are the code's,
# so a column added without a measurement fails here rather than being quietly
# left out of the arithmetic.
#
# Re-read once the clamped columns stopped being able to overflow their badge:
# `assignees` and `reviewers` are one login and a `+N` now, not a whole list, and
# `prs` is `#2211` rather than `kilnlab/kiln4py#2211` — three columns that were
# written down here at 198, 161 and 172 and had not needed that much for two
# rounds.
#
# Re-read again when the four clamped headers grew the column's own `+`: the
# control is out of flow and the room for it is `padding-right` on the header, so
# `reviewers` went from 111 to 116 — the first of the four whose header, not its
# widest cell, is what the column needs.
MEASURED = {
    "id": 110, "title": 304, "priority": 79, "status": 107, "owner": 100,
    "assignees": 124, "reviewers": 116, "cycle": 63, "size": 81, "start": 101,
    "end": 101, "blocked_by": 87, "progress": 96, "prs": 80, "tags": 128,
}
# The window the owner reported the sideways scroll from: a 1460px scroll
# container inside it.
WINDOW = 1460


def _arithmetic(page: str, expression: str, args: list) -> object:
    """Run the served page's own fit over one set of measurements.

    Lifted out of the page rather than copied into this file: a second copy of
    the arithmetic is a test that goes on passing after the page stops agreeing
    with it. Everything the functions need is a handful of top-level
    declarations, so the extraction is exact and fails loudly if the shape
    changes.
    """
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the machine, not on the code
        pytest.skip("no node on this machine, so the fit's arithmetic cannot be run here")
    parts = [
        re.search(r"^const SPARE_COLUMN = .*?;$", page, re.M),
        re.search(r"^const SQUEEZABLE = new Set\(\[[^\]]*\]\);$", page, re.M),
        re.search(r"^const SHED = \[[^\]]*\];$", page, re.M),
        re.search(r"^const FLOOR = \d+;", page, re.M),
        re.search(r"^const TITLE_FLOOR = \d+;$", page, re.M),
        re.search(r"^const PROGRESS_FLOOR = \d+;$", page, re.M),
        re.search(r"^const CLAMP_FLOOR = \d+;", page, re.M),
        re.search(r"^const CLAMPED = new Set\(\[[^\]]*\]\);$", page, re.M),
        # The floors are per column now — a sentence and a login cannot share one
        # — so the lookup that decides which comes with them.
        re.search(r"^const floorFor = key =>.*?Infinity;$", page, re.S | re.M),
        re.search(r"^function minimumWidth\(natural, keys\) \{.*?^\}$", page, re.S | re.M),
        re.search(r"^function drawnColumns\(natural, keys, room\) \{.*?^\}$", page, re.S | re.M),
        re.search(r"^function fitted\(natural, keys, room\) \{.*?^\}$", page, re.S | re.M),
    ]
    assert all(parts), "the fit is no longer the declarations this lifts out"
    source = "\n".join(found.group(0) for found in parts)
    source += "\nconst ARGS = JSON.parse(process.argv[1]);"
    source += f"\nconsole.log(JSON.stringify({expression}));"
    done = subprocess.run(
        [node, "-e", source, json.dumps(args)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(done.stdout)


def _fit(page: str, natural: list[int], keys: list[str], room: int) -> list[int]:
    return _arithmetic(page, "fitted(ARGS[0], ARGS[1], ARGS[2])", [natural, keys, room])


def _minimum(page: str, keys: list[str]) -> int:
    """The narrowest these columns can be drawn, by the page's own reckoning."""
    return _arithmetic(
        page, "minimumWidth(ARGS[0], ARGS[1])", [[MEASURED[key] for key in keys], keys]
    )


def _drawn(page: str, keys: list[str], room: int) -> list[str]:
    """The columns the page would draw in this much room, in order."""
    pairs = _arithmetic(
        page,
        "drawnColumns(ARGS[0], ARGS[1], ARGS[2])",
        [[MEASURED[key] for key in keys], keys, room],
    )
    return [key for key, _ in pairs]


def _floor(page: str, key: str) -> int:
    """The narrowest this column may be drawn, by the page's own reckoning."""
    return _arithmetic(page, "floorFor(ARGS[0])", [key])


def _shed(page: str) -> list[str]:
    """What the table gives up when it runs out of room, in that order."""
    return (re.search(r"const SHED = \[([^\]]*)\]", page).group(1)
            .replace("'", "").replace(" ", "").split(","))


def test_the_default_fit_never_needs_a_horizontal_scrollbar(page: str):
    """The table arrived scrolling sideways: 1792px of columns in a 1460px window
    on a plan of seventeen rows, so the first thing anybody did on the page they
    live in was drag it back into view.

    Most of that was a 10% cushion — `Math.ceil(w * 1.1)` on twelve columns that
    never wrap — which is why the first assertion here is the one that would have
    caught it: given exactly as much room as the columns measured, every column
    gets exactly what it measured and not a pixel more.
    """
    keys = [column for column, _ in _TABLE_COLUMNS]
    assert set(MEASURED) == set(keys), "a column with no measurement is a column not fitted"
    natural = [MEASURED[key] for key in keys]
    squeezable = set(re.search(r"const SQUEEZABLE = new Set\(\[([^\]]*)\]\)", page).group(1)
                     .replace("'", "").replace(" ", "").split(","))
    clamp_floor = int(re.search(r"const CLAMP_FLOOR = (\d+);", page).group(1))
    clamped = set(re.search(r"const CLAMPED = new Set\(\[([^\]]*)\]\)", page).group(1)
                  .replace("'", "").replace(" ", "").split(","))

    # No cushion. This is the whole of the reported defect.
    assert _fit(page, natural, keys, sum(natural)) == natural

    # At the reported window the table can no longer hold every column, so the
    # page sheds the first of the lookups and fits what is left — which is the
    # promise itself: no sideways scroll, whichever columns survive the window.
    #
    # Which one goes first is `SHED`'s business and not this test's. It was
    # `progress`, back when that column was a bar AND the count beside it and was
    # the widest thing on the row; the count is on the hover card now and the bar
    # narrows to a floor instead, so the first lookup to go is `reviewers`.
    drawn = _drawn(page, keys, WINDOW)
    assert _shed(page)[0] not in drawn, "the first lookup in SHED is the first thing to go"
    assert len(drawn) < len(keys), "nothing was shed at a window that cannot hold every column"
    width = dict(
        zip(drawn, _fit(page, [MEASURED[key] for key in drawn], drawn, WINDOW), strict=True)
    )
    assert sum(width.values()) <= WINDOW, width
    assert sum(width.values()) == WINDOW, "and it fills the window rather than stopping short"

    # The shed column has no width to check, and every other one still has to be
    # what it measured or narrower for a stated reason.
    for key in drawn:
        if key in clamped:
            # Clamped: already one item and a `+N`, so a narrower one hides an
            # item behind a badge that is right there and says how many.
            assert width[key] == MEASURED[key] or width[key] >= clamp_floor, key
        elif key in squeezable:
            # Squeezed, but never past the width at which a column stops being
            # readable — below the floor it scrolls instead, which is honest.
            # Each squeezable column has its own floor: a sentence and a login
            # cannot share one, and the bar is narrower than either.
            assert width[key] == MEASURED[key] or width[key] >= _floor(page, key), key
        else:
            # A date, a count and a cycle number have exactly one right width and
            # no graceful way to be narrower.
            assert width[key] == MEASURED[key], key

    # The groups pay in order, and that order is the whole point of there being
    # two of them. Every list column clamps, so its overflow already has somewhere
    # to go — a badge that says how many — and it gives up width before a sentence
    # does. The other way round, this window put `title` on its 110px floor, the
    # one column on the page anybody reads, while `prs` kept every pixel of a
    # reference the row also links to.
    # The two that are wider than the clamp floor here are the two that pay;
    # `prs` and `reviewers` are already under it and have nothing to give.
    assert width["tags"] < MEASURED["tags"], "a clamped column pays"
    assert width["assignees"] < MEASURED["assignees"], "and so does a list of logins"
    # The sentence pays only what is left after they are spent — so if `title` gave
    # anything up, every clamped column must already be as narrow as it is allowed
    # to be. On a window this tight it does pay; on a real one it keeps its width.
    if width["title"] < MEASURED["title"]:
        # Only the ones still drawn: a column the fit shed has no width to be on
        # its floor. `reviewers` is the first thing `SHED` gives up now.
        for key in clamped & set(drawn):
            assert width[key] == min(MEASURED[key], clamp_floor), key
    assert width["title"] >= _floor(page, "title"), (
        "and never past the width at which it stops being readable"
    )

    # Worst-first inside the clamped group: the widest list pays before the
    # narrowest one does, rather than every column losing the same proportion.
    # Asked of two columns that are both still drawn — at this window the fit
    # sheds `reviewers` and `prs`, and a column that is gone has paid everything.
    paying = [key for key in ("assignees", "reviewers", "prs", "tags") if key in width]
    assert len(paying) >= 2, f"too few clamped columns left to compare: {paying}"
    widest = max(paying, key=lambda k: MEASURED[k])
    narrowest = min(paying, key=lambda k: MEASURED[k])
    assert (MEASURED[widest] - width[widest]) >= (MEASURED[narrowest] - width[narrowest])


def test_a_window_wider_than_the_plan_gives_the_slack_to_tags(page: str):
    """Tags is the one column that can be handed space, or refused it, without
    changing what any row says: it clamps to one line and hides the rest behind
    the `+N`. Every other column would just be padded."""
    keys = [column for column, _ in _TABLE_COLUMNS]
    natural = [MEASURED[key] for key in keys]
    room = sum(natural) + 300

    width = dict(zip(keys, _fit(page, natural, keys, room), strict=True))

    assert sum(width.values()) == room
    assert width["tags"] == MEASURED["tags"] + 300
    for key in keys:
        if key != "tags":
            assert width[key] == MEASURED[key], key


def test_the_frozen_edge_is_painted_from_the_scroll_position(page: str):
    """Never at `scrollLeft === 0`. Which rules draw it is
    `test_cascade.test_the_frozen_edge_is_drawn_only_while_the_table_is_scrolled`;
    this is the half that decides when the class is on, including on arrival —
    a reload restores `scrollLeft` before any of this runs, so a handler that
    only reacts to the event starts out wrong."""
    assert "scroller.classList.toggle('scrolled', scroller.scrollLeft > 0)" in page
    assert re.search(r"scroller\.addEventListener\('scroll', frozenEdge\);\nfrozenEdge\(\);", page)


# `tests/browser.py` holds these now. They were written here, where the table's
# pixel tests could reach them and the graph's could not — and the graph, the
# timeline and the table now answer one question about geometry the same way.


# What a clamped cell promises, measured in the three states it is kept or broken
# in. `overhang` is how far the badge reaches past its cell's right padding edge,
# so anything above zero is a badge with a piece missing; `cut` counts the values
# that had to give up width, which is what is supposed to happen instead.
#
# The second and third states are put there on purpose. The corpus this page is
# built from has short logins and a wide window, so nothing in it is under
# pressure — and the defect is entirely about what happens when something is. The
# fit's own floor, applied through the page's own `applyWidths`, is the state a
# real plan puts these columns in.
_BADGES = """
const cells = [...document.querySelectorAll('td.clamp')]
  .filter(td => td.offsetParent && td.querySelector('.more'));
const at = () => ({
  overhang: Math.max(-999, ...cells.map(td => {
    const box = td.getBoundingClientRect();
    const badge = td.querySelector('.more').getBoundingClientRect();
    return Math.round(badge.right - (box.right - Number.parseFloat(
      getComputedStyle(td).paddingRight)));
  })),
  cut: cells.filter(td => {
    const first = td.querySelector('.first');
    return first.scrollWidth > first.clientWidth + 1;
  }).length,
  // The other way to lose a badge: not pushed out of the cell but squeezed
  // inside it, until `+12` is drawn in the width of `+1`.
  squashed: cells.filter(td => {
    const badge = td.querySelector('.more');
    return badge.scrollWidth > badge.clientWidth + 1;
  }).length,
});
const asDrawn = at();
for (const key of CLAMPED) WIDTHS[key] = CLAMP_FLOOR;
applyWidths();
const onFloor = at();
for (const td of cells) td.querySelector('.first').textContent = 'a'.repeat(60);
return {badges: cells.length, asDrawn, onFloor, long: at()};
"""


def test_the_badge_is_never_the_part_of_a_clamped_cell_that_gets_cut(
    page: str, tmp_path: Path
):
    """`+2` is the whole promise the clamp makes — it says how much of the value
    is hidden, and it is the button that shows it. It was the part being cut: a
    third of it gone wherever a clamped column fell under about 128px, and 368px
    of it outside the cell on a sixty-character login, which reads as the table
    clipping rather than as a column that clamps.

    Geometry from a browser rather than a string search for the rule that is
    meant to produce it: this is a claim about where a box ends up, and a
    stylesheet saying `flex: none` somewhere is not that claim.
    """
    got = measured_in(chrome(), page, tmp_path / "clamped.html", 1280, _BADGES)
    assert got["badges"], "no clamped cell on the page had a badge to check"

    for state, where in (
        ("asDrawn", "as the fit drew it"),
        ("onFloor", "with every clamped column on its floor"),
        ("long", "with a sixty-character value in a column fitted for a short one"),
    ):
        assert got[state]["overhang"] <= 0, (
            f"{where}, a badge reaches {got[state]['overhang']}px past the right edge "
            f"of its own cell"
        )
        assert got[state]["squashed"] == 0, (
            f"{where}, {got[state]['squashed']} badges are drawn narrower than the "
            f"count inside them"
        )
    # And the value is what gave way instead — with an ellipsis, so a cut value
    # says it was cut rather than simply stopping mid-word.
    assert got["long"]["cut"] == got["badges"], (
        "sixty characters fit in a column on its floor, which cannot be true"
    )


# Both controls, driven, in the browser they are drawn in. None of this exists in
# the rendered file: the cells are built by the page's own script and the column
# control is created from `CLAMPED` at load, so a string search can say what the
# code says and nothing about what a click does.
#
# `state()` is deliberately read from the DOM rather than from a variable the
# script keeps, because there is no such variable — one `open` class on the cell
# is the whole state, which is the property being tested.
_TOGGLES = """
const key = 'reviewers';
const th = headers.find(h => keyOf(h) === key);
const control = th.querySelector('.expand');
const cells = () => [...tbody.querySelectorAll(`td[data-col="${key}"]`)]
  .filter(td => td.querySelector('.more'));
const badge = () => cells()[0].querySelector('.more');
const sign = el => getComputedStyle(el, '::before').content.replace(/"/g, '');
const stored = () => {
  // `localStorage` throws on the property itself where it is denied, which would
  // take the whole report with it — and a run that cannot see storage has to say
  // so rather than reporting an empty one.
  try { return JSON.stringify(Object.entries(localStorage).sort()); }
  catch (error) { return 'denied'; }
};
const state = () => ({
  open: cells().filter(td => td.classList.contains('open')).length,
  of: cells().length,
  controlName: control.getAttribute('aria-label'),
  controlSign: sign(control),
  badgeName: badge().getAttribute('aria-label'),
  badgeSign: sign(badge()),
  // The count the badge draws, so the name it carries can be checked against the
  // number it is about rather than against a number this file assumes.
  badgeCount: Number(badge().textContent),
  stored: stored(),
  query: location.search,
  height: Math.round(table.getBoundingClientRect().height),
});
// The naming rule at both counts, asked of the function that writes the badge
// rather than of whichever counts this corpus happens to hold: a plan where
// every list is one name over is a plan that never says "people" out loud.
const naming = [1, 2].map(hidden => {
  const html = clamped(Array.from({length: hidden + 1}, (_, i) => 'name' + i),
                       'person', 'people');
  return [/aria-label="([^"]*)"/.exec(html)[1], /data-collapse="([^"]*)"/.exec(html)[1]];
});
const report = {control: control.outerHTML,
                inSortButton: !!th.querySelector('button:not(.expand) .expand'),
                naming,
                at: [['loaded', state()]]};
const step = (what, act) => { act(); report.at.push([what, state()]); };
step('the badge clicked once', () => badge().click());
step('the badge clicked again', () => badge().click());
step('the column opened', () => control.click());
step('one cell closed by hand', () => badge().click());
step('the column opened again', () => control.click());
step('the column closed', () => control.click());
step('a redraw', () => { control.click(); draw(); });
// The header itself still sorts — otherwise "the control did not sort" is a
// claim about a table that cannot be sorted at all.
step('the header itself clicked', () => th.click());
// And a write this page really does make, through the same storage, so that
// "nothing was written" is an observation and not an unreachable API.
step('a width remembered', () =>
  th.querySelector('.grip').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})));
return report;
"""


def test_a_revealed_cell_can_be_put_back(demo_page: str, tmp_path: Path):
    """`classList.add('open')` was the whole of the reveal and nothing anywhere
    took the class off, so an expanded cell could only be collapsed by reloading
    the page. Nobody reported it because expanding one cell is cheap — and then
    the column control made one click expand seventeen, which turns a nuisance
    into a trap.

    Driven in Chrome rather than read: the badge is written by the page's own
    script and the reveal is a class a click puts on a cell, so what is assertable
    in the rendered file is the code and not the behaviour.
    """
    # 1700 and not 1460: the title column has a floor of its own now — a sentence
    # and a login cannot share one — and at 1460 the fit pays for it by shedding
    # two lookup columns, `reviewers` among them. A test of a control on a column
    # that is not drawn is a test of nothing, and which columns a given window
    # holds is `test_the_default_fit_never_needs_a_horizontal_scrollbar`'s
    # business rather than this one's.
    got = measured_in(chrome(), demo_page, tmp_path / "toggles.html", 1700, _TOGGLES)
    at = dict(got["at"])
    assert at["loaded"]["of"] >= 2, "no cell in this column had anything hidden to reveal"

    assert at["loaded"]["open"] == 0
    assert at["the badge clicked once"]["open"] == 1, "the badge reveals"
    assert at["the badge clicked again"]["open"] == 0, "and puts it back"

    # And it says which of the two it will do next, in its name and in its sign —
    # icon-only, so the name is the whole of what a screen reader is given. The
    # count comes off the badge and the word follows from it, because "+1" is as
    # ordinary as "+4" and the name used to reach a screen reader as "1 more
    # persons".
    hidden = at["loaded"]["badgeCount"]
    people = "person" if hidden == 1 else "people"
    assert at["loaded"]["badgeName"] == f"Show {hidden} more {people}"
    assert at["loaded"]["badgeSign"] == "+"
    assert at["the badge clicked once"]["badgeName"] == f"Show {hidden} fewer {people}"
    assert at["the badge clicked once"]["badgeSign"] == "−"

    # Both counts, from the function that writes the name, because a corpus whose
    # lists are all one name over never exercises the plural at all.
    assert got["naming"] == [
        ["Show 1 more person", "Show 1 fewer person"],
        ["Show 2 more people", "Show 2 fewer people"],
    ]


def test_the_column_control_opens_the_column_and_closes_it(demo_page: str, tmp_path: Path):
    """One click opens every clamped cell in the column, one more puts them all
    back, and what it offers is what the column is not already doing.

    The mis-click it is designed against is the one that sorts the table when
    somebody meant to expand it: the control sits in a 116px header beside a sort
    button and a drag grip. So the click has to stop at the control — asserted
    against a header that demonstrably does sort when it is the thing clicked,
    or the assertion is about a table with no sorting in it.
    """
    # 1700 and not 1460: the title column has a floor of its own now — a sentence
    # and a login cannot share one — and at 1460 the fit pays for it by shedding
    # two lookup columns, `reviewers` among them. A test of a control on a column
    # that is not drawn is a test of nothing, and which columns a given window
    # holds is `test_the_default_fit_never_needs_a_horizontal_scrollbar`'s
    # business rather than this one's.
    got = measured_in(chrome(), demo_page, tmp_path / "toggles.html", 1700, _TOGGLES)
    at = dict(got["at"])
    every = at["loaded"]["of"]
    assert every >= 2, "no cell in this column had anything hidden to reveal"

    assert at["the column opened"]["open"] == every, "one click opens the column"
    assert at["the column opened"]["controlName"] == "Show fewer reviewers"
    assert at["the column opened"]["controlSign"] == "−"
    # It reflects the column rather than firing blindly: close one cell by hand and
    # the column is no longer open, so what it offers is to open that one.
    assert at["one cell closed by hand"]["open"] == every - 1
    assert at["one cell closed by hand"]["controlName"] == "Show all reviewers"
    assert at["one cell closed by hand"]["controlSign"] == "+"
    assert at["the column opened again"]["open"] == every
    # Closing the column closes the cells inside it.
    assert at["the column closed"]["open"] == 0
    # What it costs, and that the cost is entirely refundable: expanding a column
    # is the plan not fitting on one screen any more, and one click has to put the
    # table back exactly as it was rather than nearly.
    assert at["the column opened"]["height"] > at["loaded"]["height"], (
        "opening a column of lists cost no height at all, which cannot be true"
    )
    assert at["the column closed"]["height"] == at["loaded"]["height"], (
        "closing the column did not put the table back where it started"
    )

    # It is in the `<th>` and not in the sort button, and its click stops there.
    assert not got["inSortButton"], "a control inside the sort button sorts on its way"
    assert 'type="button"' in got["control"], "or it submits something"
    for step in ("the column opened", "the column closed"):
        assert at[step]["query"] == at["loaded"]["query"], (
            f"{step} re-sorted the table: the click reached the header"
        )
    assert at["the header itself clicked"]["query"] != at["loaded"]["query"], (
        "the header no longer sorts at all, so nothing above was tested"
    )


def test_an_expanded_column_is_a_way_of_reading_and_not_a_setting(
    demo_page: str, tmp_path: Path
):
    """It costs height — seventeen rows of every list at full length — and that is
    fine because it was asked for and one click puts it back. What would not be
    fine is arriving that way tomorrow.

    So nothing is written down: a redraw replaces every cell and the state goes
    with it, and `localStorage` is untouched by any of it. The remembered width is
    the only thing this table keeps, and it is kept because somebody dragged it.
    """
    # 1700 and not 1460: the title column has a floor of its own now — a sentence
    # and a login cannot share one — and at 1460 the fit pays for it by shedding
    # two lookup columns, `reviewers` among them. A test of a control on a column
    # that is not drawn is a test of nothing, and which columns a given window
    # holds is `test_the_default_fit_never_needs_a_horizontal_scrollbar`'s
    # business rather than this one's.
    got = measured_in(chrome(), demo_page, tmp_path / "toggles.html", 1700, _TOGGLES)
    at = dict(got["at"])

    assert at["a redraw"]["open"] == 0, "a sort or a save reopens nothing"
    assert at["a redraw"]["controlName"] == "Show all reviewers", (
        "and the control says so, rather than offering to close a column that a "
        "redraw already closed"
    )
    assert at["loaded"]["stored"] != "denied", (
        "this run cannot see localStorage at all, so it cannot say nothing was "
        "written to it"
    )
    for step, seen in got["at"]:
        if step == "a width remembered":
            continue
        assert seen["stored"] == at["loaded"]["stored"], f"{step} wrote to localStorage"
    # The width is the one thing this table does keep, and it is kept because
    # somebody asked for it by dragging. It is here so that every assertion above
    # is known to be watching a storage that writes.
    assert at["a width remembered"]["stored"] != at["loaded"]["stored"], (
        "a remembered width did not reach localStorage either, so nothing above "
        "was observed"
    )


# The header at the two widths it is ever drawn at: what the fit gave it with
# room to spare, and the floor it is squeezed to when there is none. Four
# columns, two shapes — `assignees` and `reviewers` sort and hold a button,
# `prs` and `tags` are bare text — and all four carry the control and the grip.
#
# Both widths, because they fail for different reasons. The control is out of
# flow, so at the floor it is the floor that has to be big enough — and at any
# width above it, it is the header's own `padding-right`, which is what puts the
# control into a measurement it is not otherwise part of. On this corpus every
# clamped column is sized by its widest cell rather than by its header, so taking
# the reservation away overlaps nothing here; it is a plan of two-letter logins
# that draws the `+` over REVIEWERS. So the reservation is asserted as what it is
# — room that is at least as wide as the thing standing in it — rather than
# waited for as an overlap this corpus cannot produce.
#
# `labelBox` measures the label whichever shape it is, through a Range for the
# bare text, so a wrap shows up as a box two lines tall.
_HEADROOM = """
function labelBox(th) {
  const button = th.querySelector('button:not(.expand)');
  if (button) return button.getBoundingClientRect();
  const nodes = [...th.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
  const range = document.createRange();
  range.setStart(nodes[0], 0);
  range.setEnd(nodes[nodes.length - 1], nodes[nodes.length - 1].textContent.length);
  return range.getBoundingClientRect();
}
const clamped = headers.filter(th => CLAMPED.has(keyOf(th)));
const line = Math.round(labelBox(clamped[0]).height);
const measure = () => clamped.map(th => {
  const box = th.getBoundingClientRect();
  const label = labelBox(th);
  const control = th.querySelector('.expand').getBoundingClientRect();
  const grip = th.querySelector('.grip').getBoundingClientRect();
  return {
    column: keyOf(th),
    width: Math.round(box.width),
    wrapped: Math.round(label.height) > line + 1,
    overLabel: Math.round(label.right - control.left),
    overGrip: Math.round(control.right - grip.left),
    // What the header sets aside for the control, against what the control and
    // the gap to the grip actually take up.
    reserved: Math.round(Number.parseFloat(getComputedStyle(th).paddingRight)),
    needs: Math.round(control.width + (box.right - control.right)),
  };
});
const at = width => {
  for (const key of CLAMPED) WIDTHS[key] = width;
  automatic = false;
  applyWidths();
  return measure();
};
// The fit's own answer first, before anything here has touched a width.
const asFitted = measure();
return {floor: CLAMP_FLOOR, asFitted, atFloor: at(CLAMP_FLOOR), below: at(CLAMP_FLOOR - 8)};
"""


def test_the_header_fits_at_the_width_the_fit_may_squeeze_it_to(
    demo_page: str, tmp_path: Path
):
    """Measured in Chrome at the two widths these columns are drawn at: the one
    the fit chose with room to spare, and `CLAMP_FLOOR`, the narrowest it is
    allowed to squeeze them to. Every one of the four now holds a label, a sort
    glyph, the column's `+` and a drag grip.

    At 112 — the floor before the control existed — `ASSIGNEES` and `REVIEWERS`
    wrap over two lines, which is a narrower column and a taller header: exactly
    what the clamp was for, undone. The floor went up to 116 to pay for the
    control rather than the control shrinking to fit under the old one.

    The fitted width is the other half and fails differently. The control is
    positioned, so it is in no measurement of its own accord: what puts it into
    one is the room the header sets aside for it, and a header that sets aside
    none is measured as though the control were not there and then handed exactly
    that many pixels by a fit with 300 to spare. Every clamped column in this
    corpus is sized by its widest cell rather than by its header, so that failure
    draws no overlap here — it needs a plan of two-letter logins. The reservation
    is therefore asserted as what it is: room at least as wide as what stands in
    it.

    The last assertion is this test checking itself. Eight pixels below the floor
    the same measurement must report a failure — if it cannot see a header that
    does not fit, its silence above means nothing.
    """
    got = measured_in(chrome(), demo_page, tmp_path / "headroom.html", 1460, _HEADROOM)

    assert len(got["atFloor"]) == 4, "the four clamped columns are the four with a control"
    for where, columns in (("as the fit drew it", got["asFitted"]),
                           (f"at the {got['floor']}px floor", got["atFloor"])):
        for column in columns:
            assert not column["wrapped"], (
                f"{where}, the {column['column']} header wraps over two lines in "
                f"{column['width']}px"
            )
            assert column["overLabel"] <= 0, (
                f"{where}, the {column['column']} label runs {column['overLabel']}px "
                f"under the control in {column['width']}px"
            )
            assert column["overGrip"] <= 0, (
                f"{where}, the {column['column']} control runs {column['overGrip']}px "
                f"into the grip"
            )
            assert column["reserved"] >= column["needs"], (
                f"{where}, the {column['column']} header sets aside "
                f"{column['reserved']}px for a control that takes {column['needs']}px, "
                f"so the column can be measured and fitted as if it were not there"
            )

    assert any(column["wrapped"] or column["overLabel"] > 0 for column in got["below"]), (
        f"{got['floor'] - 8}px fits four headers, a label, a glyph, a control and a "
        f"grip — so this measurement cannot tell a header that fits from one that "
        f"does not, and the floor above is unproven"
    )


# Seventeen rows with every clamped column open, in a window narrow enough that
# the table really is scrolled both ways — which is the only state in which the
# sticky header and the frozen pair are doing anything at all.
#
# `at()` asks what is painted at a point rather than what a stylesheet resolved
# to. A frozen cell that has lost its layer keeps every value the tests assert
# and is drawn under the rows passing beneath it, which is the whole of the
# defect and is invisible to `getComputedStyle`.
#
# The header measured is `status` and deliberately not `title`: the title header
# is sticky twice over — `[data-col="title"]` freezes it sideways at (0,1,0) and
# outranks `thead th` — so it goes on holding the top of the scroller after
# `thead th { position: sticky }` has been taken away entirely. It is the one
# header that cannot answer this question.
_TALL = """
for (const th of headers) {
  const control = th.querySelector('.expand');
  if (control && th.offsetParent !== null) control.click();
}
const rows = [...tbody.rows];
const height = rows.map(tr => Math.round(tr.getBoundingClientRect().height));
scroller.scrollTop = Math.round(scroller.scrollHeight / 3);
scroller.scrollLeft = 200;
scroller.dispatchEvent(new Event('scroll'));
const box = scroller.getBoundingClientRect();
const head = table.querySelector('thead th[data-col="status"]').getBoundingClientRect();
const id = table.querySelector('tbody td[data-col="id"]').getBoundingClientRect();
const title = table.querySelector('tbody td[data-col="title"]').getBoundingClientRect();
const at = (x, y) => {
  const found = document.elementFromPoint(x, y);
  const cell = found && found.closest ? found.closest('td,th') : null;
  return cell ? `${cell.tagName}:${cell.dataset.col}` : 'nothing';
};
// A header to probe that is not itself frozen and is not hidden behind the pair
// that is: scrolled sideways, the columns to the left of the viewport are under
// the frozen pair, and asking what is painted there answers a question about the
// frozen pair rather than about the header row.
const clear = headers
  .filter(th => th.offsetParent !== null && !['id', 'title'].includes(keyOf(th)))
  .map(th => [keyOf(th), th.getBoundingClientRect()])
  .find(([, seen]) => seen.left > title.right + 8);
return {
  headerProbed: clear[0],
  rows: rows.length,
  open: tbody.querySelectorAll('td.clamp.open').length,
  tallest: Math.max(...height),
  shortest: Math.min(...height),
  scrolls: {down: scroller.scrollHeight > scroller.clientHeight + 1,
            sideways: scroller.scrollWidth > scroller.clientWidth + 1},
  scrolled: scroller.classList.contains('scrolled'),
  headerAtTop: Math.round(head.top - box.top),
  idAtLeft: Math.round(id.left - box.left),
  titleAfterId: Math.round(title.left - id.right),
  painted: {
    header: at(clear[1].left + 4, head.top + 4),
    frozenHeader: at(id.right + 20, head.top + 4),
    idColumn: at(box.left + 4, box.top + box.height / 2),
    titleColumn: at(id.right + 20, box.top + box.height / 2),
    beyond: at(box.right - 20, box.top + box.height / 2),
  },
};
"""


def test_the_header_and_the_frozen_pair_hold_when_the_rows_are_tall(
    demo_page: str, demo_plan_size: int, tmp_path: Path
):
    """What expanding a column deliberately costs: every row of lists at full
    length, and a plan that no longer fits on one screen. That is the whole point
    of it being asked for rather than being the default — but it is also the state
    in which the two things that keep a scrolled table readable have the most work
    to do, and neither was ever seen doing it against a 150px row.

    So the table is scrolled down into the middle of the plan and sideways past
    the frozen pair, and what is *painted* at four points is what is asked. A
    frozen cell that has lost its layer resolves to every value a stylesheet test
    asserts and is drawn under the rows passing beneath it.

    The row count is read off the plan rather than written down. It was `== 17`,
    which was the demo's size on the day it was typed, and growing the demo made
    it wrong — silently, in a test whose subject is scrolling and not counting.
    """
    got = measured_in(chrome(), demo_page, tmp_path / "tall.html", 700, _TALL, height=600)

    assert got["rows"] == demo_plan_size
    assert got["open"], "no column opened, so nothing here is about tall rows"
    assert got["tallest"] > got["shortest"], "the rows did not grow"
    assert got["scrolls"]["down"] and got["scrolls"]["sideways"], (
        "the table fits its window, so neither the sticky header nor the frozen "
        "columns are holding anything back"
    )

    assert got["headerAtTop"] == 0, "the header did not stay at the top of the scroller"
    assert got["idAtLeft"] == 0, "the id column did not stay at the left"
    assert got["titleAfterId"] == 0, "the title column no longer begins where id ends"
    assert got["scrolled"], "the frozen edge is not drawn, with columns passing under it"

    assert got["painted"]["header"] == f"TH:{got['headerProbed']}", (
        "a tall row is painted over the header"
    )
    assert got["painted"]["frozenHeader"] == "TH:title", "and over the frozen header"
    assert got["painted"]["idColumn"] == "TD:id", "a passing cell is painted over the id"
    assert got["painted"]["titleColumn"] == "TD:title", "and over the title"
    assert got["painted"]["beyond"] not in ("TD:id", "TD:title"), (
        "the frozen pair is drawn across the whole table, so nothing is scrolling"
    )


def test_the_frozen_edge_is_a_pixel_a_browser_draws(page: str, tmp_path: Path):
    """The edge shipped dead for two rounds and every test of it passed.

    It was `box-shadow: 1px 0 0 var(--line)` on a `<td>` in a
    `border-collapse: collapse` table, and Chrome paints no *outset* box-shadow
    on a collapsed cell at all. The class was toggled correctly, the stylesheet
    resolved to exactly the value asserted, the cascade engine agreed — and there
    was no pixel in either state, so the frozen pair had no edge when scrolled and
    the `+N` badges beside it looked like a clipping bug.

    What no test of a stylesheet can answer is whether anything was drawn, so this
    one asks the browser and compares what came back. Four screenshots of the same
    page: at rest and scrolled sideways, each with the edge and with the edge
    suppressed by a rule appended after it.

    Byte comparison, deliberately: the question is "did this declaration change
    what is on the screen", and equal PNGs are the answer "no". That the resting
    pair comes back byte-identical from two separate runs of Chrome over two
    different files is what says the comparison means anything at all — if this
    renderer were not reproducible, that assertion is the one that fails first,
    and it fails before any conclusion is drawn from an inequality below.

    The two declarations are suppressed one at a time and never together. Both at
    once passes on either one of them alone: the header would carry the whole
    proof while every row under it drew nothing, which is most of the defect.
    """
    browser = chrome()

    # Sideways, by the page's own scroll handler rather than by adding the class:
    # scrolling is what is supposed to produce the edge, so scrolling is what the
    # test does.
    scroll = "<script>document.querySelector('.table-scroll').scrollLeft = 10000;</script>"
    # The same weight as the rules that draw the edge, appended after them, so
    # each is the last declaration standing for its own cell. The header keeps its
    # bottom rule, which is a different line for a different reason.
    no_rows = '<style>.scrolled td[data-col="title"] { box-shadow: none; }</style>'
    no_header = ('<style>.scrolled thead th[data-col="title"] '
                 "{ box-shadow: inset 0 -1px 0 var(--line); }</style>")

    def shot(name: str, extra: str) -> bytes:
        html = tmp_path / f"{name}.html"
        html.write_text(page.replace("</body>", extra + "</body>"))
        return screenshot(browser, html, tmp_path / f"{name}.png")

    rest, rest_without = shot("rest", ""), shot("rest_without", no_rows + no_header)
    assert rest == rest_without, (
        "either the edge is painted at scrollLeft 0 — the whole of what the owner "
        "asked to be rid of — or this browser does not render the same page the "
        "same way twice, and nothing below can be concluded"
    )

    scrolled = shot("scrolled", scroll)
    assert scrolled != rest, "the table did not scroll, so there was no edge to draw either way"

    dead = ("changes no pixel: the declaration is dead. An outset box-shadow on a cell "
            "in a `border-collapse: collapse` table is not painted by Chrome — on these "
            "cells it has to be `inset`")
    assert scrolled != shot("scrolled_rows", scroll + no_rows), f"the edge down the rows {dead}"
    assert scrolled != shot("scrolled_head", scroll + no_header), f"the edge on the header {dead}"


def test_creating_is_the_detail_page_with_nothing_in_it(new_page: str, client: TestClient):
    """Same markup, same controls, same stylesheet.

    A second, differently-shaped form for creating is what made the tool feel like
    two tools: the facts list here has to be the facts list there, or the layout
    moves under you between reading a record and making one.
    """
    detail = client.get(f"/detail/{TASK}").text

    for shape in ('<dl id="facts">', 'class="field title-field"', 'class="field bodybar"',
                  'class="field body-field"', 'id="preview"'):
        assert shape in new_page, shape
        assert shape in detail, shape
    assert "<label>" not in new_page, "the old flat list of labelled controls is gone"

    # And they agree about where the control that commits the form is — jcanton,
    # 2026-08-20, "consistency!". The two pages had it at opposite ends of the
    # same markup for a day, which is the layout moving under you between reading
    # a record and making one, in the one place it matters most.
    #
    # Ordering here, pixels in `test_the_create_button_is_reachable_from_anywhere_
    # in_the_form`. What this asks is that the two pages put the bar in the SAME
    # place, which is a comparison rather than a coordinate — and a comparison of
    # two markup orders is a thing a string can answer.
    for page, which in ((new_page, "create"), (detail, "detail")):
        assert page.index('id="commitbar"') < page.index('<dl id="facts">'), which
        assert page.index('id="commitbar"') < page.index('class="field body-field"'), which


def test_the_kind_is_a_dropdown_and_switching_keeps_what_was_typed(new_page: str):
    """It was three links, and following one was a fresh page — so a title typed
    before realising it should be a pitch was a title typed twice."""
    assert '<select id="kind">' in new_page
    assert "make a" not in new_page, "the links this replaced"
    assert re.search(r"KIND\.onchange = \(\) => \{\s*showKind\(\);", new_page)
    assert "location.href" not in re.search(r"function showKind.*?\n\}", new_page, re.S).group(0)


def test_a_new_pitch_starts_from_the_teams_own_shaping_template(new_page: str):
    """The five ingredients plus the progress list, which is the template the team
    already writes pitches against. Its three header lines — shaped by, appetite,
    developers — are fields here, and a heading restating a field is the two
    copies of one fact this tool exists to end."""
    from openproj.render import TEMPLATES

    pitch = TEMPLATES["pitch"]
    # The five ingredients and the deferred-scope list. `## Progress` is the one
    # heading of the HackMD original this leaves out: a pitch's progress is its
    # tasks, and `test_the_pitch_template_leaves_progress_to_its_tasks` says so.
    for heading in ("## Problem", "## Appetite", "## Solution", "## Rabbit holes",
                    "## No-gos", "## For later"):
        assert heading in pitch, heading
    assert "Shaped by:" not in pitch and "Developers:" not in pitch
    # The guidance rides in HTML comments, exactly as it does in HackMD, and the
    # renderer drops them rather than printing them at the reader.
    assert "<!--" in pitch

    assert '<select id="template">' in new_page
    assert "const TEMPLATES = " in new_page
    # Through `|tojson`, so the `<` opening every comment reaches the script block
    # as `\\u003c` rather than as markup the page's own tokeniser can read.
    assert "\\u003c!-- The raw idea" in new_page
    assert "<!-- The raw idea" not in new_page


def test_a_template_never_overwrites_something_somebody_typed(new_page: str):
    """Switching kind switches template, because picking "pitch" and getting a
    task's headings is the wrong default in the one place the tool can teach the
    shape of a pitch. Once the box holds anything but a template, it is theirs."""
    apply_fn = re.search(r"function applyTemplate\(name\) \{.*?\n\}", new_page, re.S).group(0)
    assert "if (!untouched())" in apply_fn
    assert "the body has been edited" in apply_fn
    untouched = re.search(r"function untouched\(\) \{.*?\n\}", new_page, re.S).group(0)
    assert "Object.values(TEMPLATES).some" in untouched


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
        ("parent", "records"),
        ("cycle", "cycles"),
        ("depends_on", "records"),
    ):
        assert f'data-suggest="{source}"' in control(new_page, field), field

    # And the widget that reads them is on the page, wired to every one at once.
    assert "for (const input of document.querySelectorAll('[data-suggest]'))" in new_page
    suggestions = json.loads(
        re.search(r'<script id="suggest"[^>]*>(.*?)</script>', new_page, re.S).group(1)
    )
    assert {"people", "records", "cycles"} <= set(suggestions)
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
    assert "article.record:not(.editing) .req { display: none; }" in new_page


# Fill the title, then look at the Create button from three places in the form.
# `top >= 0 && bottom <= innerHeight` is *wholly* on screen, not merely
# intersecting: half a button hanging off an edge is a control somebody scrolls
# to anyway, which is the thing this is about.
_WHERE_CREATE_IS = """
// Out of the session views first, to the create form's surface-off state. A
// session is the ordinary page too since 2026-08-24, so this is belt over
// braces rather than an escape from a full-page surface — kept because the
// claim is about the plainest form there is: several screens tall, and a
// commit bar that stays reachable while you scroll it.
const LIT = ['view-edit', 'view-both', 'preview']
  .map(id => document.getElementById(id))
  .find(seg => seg && seg.getAttribute('aria-pressed') === 'true');
if (LIT) LIT.click();
const SAVE = document.getElementById('save');
const TITLE = document.querySelector('input[name=title]');
TITLE.value = 'A pitch with a shaping document in it';
TITLE.dispatchEvent(new Event('input', {bubbles: true}));
await new Promise(r => setTimeout(r, 200));
const ROOT = document.documentElement;
const out = {screens: ROOT.scrollHeight / innerHeight, at: []};
const end = ROOT.scrollHeight - innerHeight;
// A timer and not `requestAnimationFrame`: a headless Chrome under a virtual
// clock manages two frames in three seconds, so a rAF here is a script that
// never resumes and a harness that reports nothing at all.
for (const y of [0, Math.round(end / 2), end]) {
  scrollTo(0, y);
  await new Promise(r => setTimeout(r, 80));
  const box = SAVE.getBoundingClientRect();
  out.at.push({y: Math.round(scrollY), text: SAVE.textContent.trim(),
               on: box.height > 0 && box.top >= 0 && box.bottom <= innerHeight});
}
return out;
"""


def test_the_create_button_is_reachable_from_anywhere_in_the_form(
    new_page: str, tmp_path: Path
):
    """The control that commits this form is on screen from every part of it — and
    since 2026-08-20 that part of the screen is the top, so that the create page
    and the detail page agree about where a Save lives. jcanton: "move the create
    bar up top too, consistency!"

    The history, because it is what decides how this has to be asked. The bar was
    once STATIC and above the title: the last thing on screen after filling a form
    in was the body box and the action was a scroll back up. The commit that fixed
    that did two things at once — moved the bar to the foot of the form AND made
    it sticky — and only the second delivered the guarantee. A bar that is on
    screen wherever you have scrolled to is as reachable from the head of a form
    as from its foot, so the edge was free and consistency spent it.

    So this asks the guarantee and not the coordinate. It used to assert that the
    bar came after `<dl id="facts">` and after the body field, which is the same
    mistake this test had already corrected once for the class name: markup order
    is how the fix was built, not what it promised.

    And the ordering assertion was actively hiding the defect. `#commitbar { top:
    0; bottom: auto }` was written for the detail page and put in `_DETAIL_STYLE`
    — which this page loads too — so the create bar had already lost `bottom: 0`
    while staying last in the markup, and was stuck to neither edge. Measured in
    Chrome at 1400x900 with the form filled in: 1178px down the page, on screen
    from nowhere near the top of it, under a green suite. Which is why the answer
    now comes from Chrome.
    """
    # Short enough that the form really is several screens: a bar that never
    # leaves a window nothing scrolls in proves nothing at all.
    got = measured_in(chrome(), new_page, tmp_path / "create.html", 1400,
                      _WHERE_CREATE_IS, height=600, patience=2500)

    assert got["screens"] > 1.5, (
        f"the form fits in {got['screens']:.1f} windows, so there is no scroll to "
        "be caught out by and nothing below is evidence"
    )
    assert len({look["y"] for look in got["at"]}) == 3, "the page did not actually scroll"
    for look, place in zip(got["at"], ("the top", "the middle", "the end"), strict=True):
        assert look["text"] == "Create", look
        assert look["on"], f"Create is off screen from {place} of the form: {look}"

    # `.editbar` is on this page again, and this assertion is re-argued rather
    # than deleted. It used to read `'<p class="editbar">' not in new_page`,
    # which pinned the fix by the name of the bar that carried the bug; the bar
    # now holds the view switcher, which is page chrome and belongs in the same
    # place on this page as on the detail page. The argument was never about a
    # class name — it is that the button which commits this form is its own
    # control and not one of the page's — so that is what is asked.
    editbar = re.search(r'<p class="editbar">.*?</p>', new_page, re.S).group(0)
    assert 'id="save"' not in editbar and "Create" not in editbar, "the bar it replaced"


def test_the_columns_and_the_cells_agree_on_their_order(page: str):
    """They were two hand-maintained lists, index-parallel, with nothing enforcing
    it: edit one and every cell shifts a column left of where its header says it
    is. Both are emitted from one list now, and this is what says so.

    Compared with each other rather than with `_TABLE_COLUMNS`, because one column
    is conditional: `progress` is drawn only for a plan whose bodies keep a
    checklist, and this page's does not. The drift this test exists to catch is
    still caught — the two rendered lists must be identical, and every name in
    them must come from the constant in the constant's own order."""
    from openproj.render import _TABLE_COLUMNS, _TABLE_DERIVED

    headers = columns(page)
    listed = json.loads(re.search(r"const keys = (\[.*?\]);", page, re.S).group(1))
    every = [name for name, _ in _TABLE_COLUMNS]

    assert headers == listed
    assert [name for name in every if name in headers] == headers, "and in that order"
    # And every column the payload withholds an editor for is either drawn or not
    # drawn at all: a derived name that is neither withholds an editor from
    # nothing.
    assert set(_TABLE_DERIVED) - set(listed) <= {"progress"}


def test_a_column_header_is_the_label_map_s_word_for_the_field(page: str):
    """The header words were a literal list beside the central map F11 asked
    everything to go through, so `size` was headed `appetite` in one place and
    `Appetite` in the other — same words, two sources, and only one of them moves
    when the word does. Read off the rendered header rather than off the map, or
    the assertion is the map compared with itself."""
    from openproj.render import _TABLE_COLUMNS

    # Every column the table can draw has a word, including the conditional one
    # this page does not happen to be drawing.
    assert {name for name, _ in _TABLE_COLUMNS} <= set(LABELS)
    for name in columns(page):
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
    offered = re.findall(r'<div class="facet" data-field="([^"]+)"', page)
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


def test_a_status_is_a_chip_and_the_id_cell_holds_only_the_id(page: str):
    """The `--st-*` tokens were used by the graph and the timeline only, so the
    one view people live in was the one view with no colour language at all.

    Kind is not a chip in this table. `pitch-0c0001` already says pitch, in a
    prefix the model guarantees agrees with the kind, so the chip in the id cell
    was restating the first word of the cell it sat in — seventeen times, in the
    narrowest column on the row. The id is not boxed in its place either: it is
    monospace, which is already what marks it as a token to be cited, and a
    border round every id is the same noise wearing a different hat.

    Kind stays a facet, which is where "show me only tasks" is actually asked,
    and stays a chip on the pages where there is no id to carry it.

    One thing did join the cell since: the grip a row is dragged by. It is a
    handle and not a label — it says what can be done to the row rather than
    repeating what the row is — and it is drawn only where the row has somewhere
    to go, which is why it is asserted here rather than merely tolerated.
    """
    body = script(page)

    # Through `stClass`, which is `_status_class` in the other language: a class
    # attribute names a rule the stylesheet has, so a status nobody has heard of
    # gets the ready rung rather than putting its own text in the attribute.
    assert re.search(r'class="chip \$\{stClass\(row\.status\)\}"', body), "a status is a chip"
    assert "esc(human(row.status))" in body, "the chip carries the word, not the identifier"
    assert ".chip.st-in_progress" in page

    # The shell's hover card builds one — a card is not a cell, and on the graph
    # and the timeline the kind chip is the only thing saying which kind a node
    # is. So the claim is about the table's own script, which is the thing that
    # draws the cells.
    table_only = body.split("// --- the hover card")[0] + body.split("function hideCard()")[-1]
    assert "chip kind-" not in table_only, "no kind chip is built for any cell of this table"
    assert re.search(
        r"""if \(key === 'id'\)\s*\n\s*return \(EDITABLE && movable\(row\) \? GRIP : ''\)"""
        r"""\s*\+ `<span class="eid">\$\{esc\(row\.id\)\}""", body
    ), "and nothing is boxed in its place but the handle it is moved by"
    assert '<span class="facetname">Kind' in page, "and kind is still asked for in the facet bar"


def test_no_kind_is_given_a_rule_of_its_own(page: str):
    """One rule per kind and every one of them the same rule, so none can drift.
    What it resolves to on each chip is
    `test_cascade.test_every_kind_chip_is_the_same_shape`.

    It was one selector naming three kinds, which is the same claim while the
    ladder has three rungs and a chip with no border at all the moment it has
    four — `product` arrived as exactly that. The rules are written by a loop
    over the ladder now, so the claim is that they are identical rather than that
    there is one of them.
    """
    from openproj.model import KIND_NAMES

    rules = re.findall(r"\.chip\.kind-(\w+) \{([^}]*)\}", page)
    assert [kind for kind, _ in rules] == list(KIND_NAMES), rules
    assert len({body.strip() for _, body in rules}) == 1, (
        f"the kinds are drawn {len({b.strip() for _, b in rules})} different ways: {rules}"
    )


def test_every_identifier_a_filter_offers_is_shown_as_a_word(page: str):
    """`in_progress` and `missing_required_fields` are storage, not English, and
    the filter holding the second was labelled STATE — a word from nowhere in the
    domain. The option's value stays the identifier because that is what the
    client-side filter compares against; only the text a person reads changes."""
    # The facet's values are checkboxes now, each labelled with the word rather
    # than the identifier — the claim is about `in_progress` never reaching a
    # reader, not about the tag it is drawn in.
    assert '<input type="checkbox" value="in_progress">In progress</label>' in page
    assert (
        '<input type="checkbox" value="missing_required_fields">Has a problem</label>' in page
    )
    assert '<span class="facetname">Flags' in page
    assert '<span class="facetname">state' not in page

    # Including inside the editor a double-click opens, or picking "In progress"
    # from a cell would write the label back into the corpus. Both go through
    # `esc` — the closed set is a closed set today, and a rule with an exception
    # in it is a rule nobody applies to the next line.
    assert re.search(
        r'<option value="\$\{esc\(o\)\}"[^>]*>`\s*\+\s*'
        r'`\$\{esc\(markFor\(field, o\)\)\}\$\{esc\(human\(o\)\)\}</option>',
        script(page),
    )


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

    The number counts *problems*; `?predicate=has_blocker` matches *records*, and
    one record can carry three of them. So both numbers are on the label and the
    second one is the promise the link has to keep.
    """
    from openproj.model import Config, Task
    from openproj.render import render_table

    # Two records, five blockers between them: ready needs an owner, a reviewer
    # and an effort, and one of the three is filled in on the second.
    nameless = Task(id="task-000001", kind="task", title="Ready and nameless",
                    status="ready")
    fine = Task(id="task-000002", kind="task", title="Fine", status="ready",
                owner="ann", reviewers=["bo"], person_weeks=1)
    half = Task(id="task-000003", kind="task", title="Half named", status="ready",
                owner="ann")
    index = build_index([nameless, fine, half], Config(), date(2026, 8, 17))

    problems = [p for p in index.problems if p.severity == "blocker"]
    records = {p.record_id for p in problems}
    assert len(problems) == 5 and len(records) == 2, "the two numbers must differ"

    page = render_table(index)
    payload = json.loads(re.search(r'id="payload"[^>]*>(.*?)</script>', page, re.S).group(1))
    matched = {i for i, row in payload["rows"].items() if "has_blocker" in row["predicates"]}

    assert matched == records, "the filter is the population the label names"
    assert f'id="blocker-count">{len(problems)}<' in page
    assert f">blocking problems on {len(matched)} records</span>" in page

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

    hostile = 'Fix <b>&"the" </script><img src=x> seam'
    record = Task(id="task-000001", kind="task", title=hostile, owner='a"b',
                  person_weeks=1, tags=["<i>one", "two&three"], prs=["kilnlab/kiln4py#1"])
    index = build_index([record], Config(), date(2026, 8, 17))
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
        "${esc(human(row.status))}",    # the kind is no longer drawn in any cell
        "${esc(ref)}",                  # a PR reference, repo and number both
        "${esc(was)}",                  # and the value the editor opens with
    ):
        assert interpolation in body, interpolation
    assert "clamped((value || []).map(esc), 'tag', 'tags')" in body

    # Nothing typed reaches the page as markup by either route.
    assert "<b>&" not in page and "<i>one" not in page


def test_a_problem_marks_the_row_and_the_cell_that_caused_it(page: str):
    """The reason a row is a problem lived in a native `title` on the `<tr>`, and
    a table is not a thing anybody hovers to find out.

    A field the table has no column for — `shaped_by`, `person_weeks` — still has
    to be findable, so its complaint falls to the id cell. A glyph on a column
    nobody can see is a row that says something is wrong and will not say what.
    """
    body = script(page)

    assert "'sev-row-' + SEV_CLASS[worst]" in body, "the row carries its worst severity"
    assert "sev-cell-' + SEV_CLASS[mark.severity]" in body
    glyph = r'class="sev-mark sev-mark-\$\{SEV_CLASS\[mark\.severity\]\}" role="img"'
    assert re.search(glyph, body)
    assert 'aria-label="${esc(note)}"' in body, "the glyph's name is the message"
    assert "const MARK_COLUMN = {person_weeks: 'size'," in body
    assert "keys.includes(problem.field) ? problem.field : 'id'" in body


def test_an_empty_table_says_which_of_the_three_empties_it_is(page: str):
    """Filtered to nothing, an empty plan and a payload that did not survive the
    trip all rendered as a header row over a void, which reads as a broken app
    whichever one it is — and each wants something different done about it.

    The message goes inside the tbody: an empty table with its explanation
    somewhere else is still a header row over a void.
    """
    body = script(page)

    assert "'No record matches these filters.'" in body
    assert "'This plan has no records yet.'" in body
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
    # And every control the page draws, not only the record fields: the people
    # page filters by role, which is not a field of a record and was left set.
    assert "document.querySelectorAll('.facet[data-field]')]\n    .map(facet" in body


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

    # Thirteen: the fixture's pitch has tasks under it, so it has progress to
    # report and the column is drawn. A plan with neither tasks nor a checklist
    # anywhere would have twelve — see `_columns_for`.
    assert len(sortable) == 13, "every column but prs and tags sorts"
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
    # The container is bounded by the room the window has left, which the shell
    # measures. It used to be `100vh - 15rem`, a hand-count of the stack above the
    # rows written down as a constant — and the count had already been wrong once,
    # when the page gained a heading and the box ran off the bottom of the window.
    # What that bound actually produces is checked in a browser, by
    # `test_render.test_the_box_each_view_fills_stops_where_the_window_does`.
    assert "max-height: var(--room)" in page, "the body scrolls in the container"
    assert '<div class="table-scroll" data-fills>' in page, (
        "and the shell is told which box that is"
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
    """Fourteen columns below the width the fit needs means fourteen columns too
    narrow to read; the three that go are reachable on the detail page and still
    filterable above.

    *Which* width that is is not written in the stylesheet any more. It was
    `@media (max-width: 1100px)` while the floors below put the fourteen-column
    minimum at 1354px, so every window from 1101 to 1393 kept all fourteen
    columns and scrolled sideways — 293px of it at the low end. Two numbers that
    have to agree, one in CSS and one in JavaScript. Now the fit measures it.
    """
    # The served stylesheet with its comments taken out — the comments say what
    # the breakpoint was and why it went, and a search that reads them is a search
    # that cannot tell a rule from an explanation of one.
    styles = re.sub(r"/\*.*?\*/", "", "".join(re.findall(r"<style>(.*?)</style>", page, re.S)),
                    flags=re.S)
    # **Not "no `@media (max-width` anywhere on this page", which is what this
    # asked before.** That was a proxy that happened to hold, and it broke the
    # day a rule about something else needed one: the sheet carrying the suggest
    # list also carries the editor toolbar, and the toolbar has a narrow-window
    # rule for a bar this page never draws. The claim is about the TABLE — that
    # nothing decides its layout from a width written in CSS — so it is asked
    # about the table's own selectors, inside every at-rule on the page.
    # Brace-matched through `cascade._blocks`, because a non-greedy regex for a
    # media block stops at the first rule inside it and would miss the second.
    from cascade import _blocks

    for prelude, body in _blocks(styles):
        if not prelude.startswith("@media"):
            continue
        assert not re.search(r"\.shed-|data-col|--sticky|\btable\b|\bt[hd]\b", body), (
            f"the breakpoint that drifted is back, inside `{prelude}`: {body.strip()[:160]}"
        )
    rule = re.search(r"\n(\.shed-.*?) \{ display: none; \}", styles, re.S).group(1)
    for column in _shed(page):
        assert f'.shed-{column} [data-col="{column}"]' in rule, column

    body = script(page)
    assert "SHED.forEach(key => table.classList.toggle(shedClass(key), !kept.has(key)));" in body
    assert "const drawn = drawnColumns(natural, keys, room);" in body, (
        "the fit decides it, from the same floors it fits by"
    )
    # Every cell declares its column, or the rule above would have to count them.
    assert 'return `<td data-col="${key}"' in body
    # A dropped column is not part of the table's width, or the table is set
    # wider than the columns it draws.
    assert "if (th.offsetParent === null) { th.style.width = ''; return; }" in body
    # A shed column measures zero, and what it *would* need is how the fit
    # decides whether to draw it again — so it is measured with the classes off.
    assert "table.classList.remove(...SHED.map(shedClass));" in body


# Every window the audit walked, plus the two edges of the drift it found: 1101
# was 293px of sideways scroll and 1393 was one pixel of it.
@pytest.mark.parametrize(
    "room", [900, 1050, 1091, 1100, 1101, 1280, 1353, 1354, 1366, 1393, 1440, 1500,
             1600, 1920, 2560],
)
def test_no_window_leaves_the_table_scrolling_sideways_by_choice(page: str, room: int):
    """The fit and the shedding are one number now, so this is the check that the
    number is right at every window rather than at the one it was written for.

    Below the minimum of the last layout there is nothing left to shed and the
    table scrolls, which is honest — but it may only scroll by exactly the
    shortfall, never by a column it could have dropped.
    """
    keys = [column for column, _ in _TABLE_COLUMNS]
    last = [key for key in keys if key not in _shed(page)]
    minimum, reduced = _minimum(page, keys), _minimum(page, last)
    assert reduced < minimum, "shedding a column has to buy room"

    drawn = _drawn(page, keys, room)
    total = sum(_fit(page, [MEASURED[key] for key in drawn], drawn, room))

    if room >= reduced:
        assert total <= room, (
            f"{room}px draws {len(drawn)} columns in {total}px: {total - room}px of "
            f"sideways scroll, with a full minimum of {minimum} and a shed-down "
            f"minimum of {reduced}"
        )
    else:
        assert drawn == last, "and everything that can go has gone"
        assert total == reduced, "and at its narrowest it is exactly its own minimum"


def test_a_column_goes_only_when_the_one_before_it_was_not_enough(page: str):
    """The three do not go together. At 1354px the table would give up a fifth of
    what it says to buy 300px it needs 112 of — and every window in that band
    kept all fourteen columns and scrolled before this was measured at all.

    So each of them goes at its own width, in the stated order, and each of those
    widths is the width at which the layout above it stopped fitting.
    """
    keys = [column for column, _ in _TABLE_COLUMNS]
    order = _shed(page)

    kept = list(keys)
    for column in order:
        # One pixel below what this layout needs is where the next column goes.
        edge = _minimum(page, kept)
        assert _drawn(page, keys, edge) == kept, f"{column} goes too early"
        kept = [key for key in kept if key != column]
        assert _drawn(page, keys, edge - 1) == kept, f"{column} goes too late"

    # And nothing goes below that: what is left is what the table always draws.
    assert _drawn(page, keys, 320) == kept


def test_the_tags_cell_is_one_line_with_the_rest_behind_a_count(page: str):
    """Five tags wrapped to five lines and every row on screen grew to match, so
    the column with the least in it set the height of the table.

    The count is exact rather than "however many did not fit": one tag is shown
    and `+N` is the number you cannot see. No row padding changes anywhere — this
    is about removing height, not adding it.
    """
    assert "td.clamp { white-space: nowrap; overflow: hidden; }" in page
    assert "td.clamp .rest { display: none; }" in page
    assert "td.clamp.open .rest { display: inline; }" in page
    assert "padding: .3rem .5rem" in page, "the row keeps the padding it had"
    # The badge is still there when the cell is open, because it is what closes it
    # again. `td.clamp.open .more { display: none; }` is what made the reveal
    # one-way: there was nothing left to click.
    assert 'td.clamp .more::before { content: "+"; }' in page
    assert 'td.clamp.open .more::before { content: "−"; }' in page
    assert "td.clamp.open .more { display: none; }" not in page

    body = script(page)
    assert 'const expand = `Show ${rest.length} more ${word}`;' in body, (
        "the reveal has a name, not only a plus sign"
    )
    assert 'data-collapse="Show ${rest.length} fewer ${word}"' in body, (
        "and the name changes with the state, because a control says what it will do"
    )
    # Both list columns, because fixing tags alone only moved the problem one
    # column left: a task with three merged PRs stood 128px tall beside a 50px row.
    assert "clamped((value || []).map(esc), 'tag', 'tags')" in body
    assert "clamped((value || []).map(prLink), 'pull request', 'pull requests')" in body
    # Every list column, not three of four: assignees and reviewers were the last
    # that wrapped, and they were most of the height left in the table.
    assert "clamped((value || []).map(esc), 'person', 'people')" in body
    assert "CLAMPED.has(key) ? 'clamp' : ''" in body
    # `toggle`, not `add`, and one function both controls go through.
    assert "td.classList.toggle('open', open);" in body
    assert "more.closest('td').classList.add('open')" not in body
    # It is a control inside an editable cell, so it must not also open the editor.
    assert "event.target.closest('button.more')) return;" in body


# One cell, drawn by the page's own `cell()` against a row the test hands it, with
# the title attribute read back off the markup it produced.
#
# The tooltip is assembled from three sources — a validation problem, the hidden
# values, the editor's instruction — and only the last of them is a literal
# anywhere in the file. Greping for a string would say nothing about what the
# other two do to it, or about which order they come out in, which is the whole of
# what was asked for.
_TIP = """
(() => {
  const rows = ROWS;
  MARKS = MARKED;
  return rows.map(row => {
    const html = cell(row, KEY);
    const found = /title="([^"]*)"/.exec(html);
    return found ? found[1] : null;
  });
})()
"""


def _tips(page: str, rows: list[dict], key: str, marks: dict | None = None) -> list[str]:
    from test_injection import run_js

    answer = run_js(
        page,
        _TIP.replace("ROWS", json.dumps(rows))
        .replace("MARKED", json.dumps(marks or {}))
        .replace("KEY", json.dumps(key)),
    )
    # The shim is not a browser and some of the page's script does not survive it,
    # so `errors` is never empty and asserting on it would be asserting on the
    # shim. What is checked instead is that `cell()` itself ran to the end for
    # every row: an expression that threw comes back with no value at all, and a
    # test reading tooltips out of `None` is a test that cannot fail.
    assert isinstance(answer["value"], list) and len(answer["value"]) == len(rows), answer
    # The `title` came out of markup, so it is escaped: it is compared here as the
    # browser would read it, which is also the only way `&amp;` in a tag is
    # distinguishable from a tooltip that escaped twice.
    return [None if tip is None else unescape(tip) for tip in answer["value"]]


def test_a_clamped_cell_says_what_it_is_hiding_before_it_says_how_to_edit_it(page: str):
    """Four columns draw one value and a `+N`, and the only way to read the rest
    was to click the badge — while hovering the cell answered a question nobody
    had asked: "Double-click to edit assignees".

    So the hidden values go first and the instruction under them, and a cell that
    is hiding nothing gets no extra line at all — every tooltip in the table
    growing a redundant sentence is how a tooltip stops being read.
    """
    one, two, none = _tips(
        page,
        [{"id": "task-000001", "assignees": ["merganserly", "nightjarelli"]},
         {"id": "task-000002", "assignees": ["Oxpeckerly", "nightjarelli", "jackdawrie"]},
         {"id": "task-000003", "assignees": ["sanderlingly"]}],
        "assignees",
    )
    assert one == "+1 more: nightjarelli\nDouble-click to edit assignees"
    assert two == "+2 more: nightjarelli, jackdawrie\nDouble-click to edit assignees"
    assert none == "Double-click to edit assignees", "nothing is hidden, so nothing is revealed"

    # A `title` takes newlines and this is two lines, not a run-on sentence: the
    # answer and the instruction are different kinds of thing.
    assert one.count("\n") == 1

    # Every clamped column, not the one it was reported on. `prs` reveals the whole
    # reference and not the `#2211` the cell draws — the cell drops the repository
    # because it never varies, and a tooltip has room to say which one it is.
    tags, prs, reviewers = (
        _tips(page, [{"id": "task-000001", "tags": ["ci", "hearth", "port"]}], "tags")[0],
        _tips(page, [{"id": "task-000001", "prs": ["kilnlab/kiln4py#1", "kilnlab/kiln4py#2"]}],
         "prs")[0],
        _tips(page, [{"id": "task-000001", "reviewers": ["a", "b"]}], "reviewers")[0],
    )
    assert tags.startswith("+2 more: hearth, port\n")
    assert prs.startswith("+1 more: kilnlab/kiln4py#2\n")
    assert reviewers.startswith("+1 more: b\n")

    # And a column that clamps nothing is untouched, or the change is not "reveal
    # what is hidden", it is "put a sentence on every cell".
    plain = _tips(page, [{"id": "task-000001", "owner": "jackdawrie"}], "owner")[0]
    assert plain == "Double-click to edit owner"


def test_a_problem_still_comes_first_and_a_long_list_is_capped(page: str):
    """Two things the reveal line must not break.

    A validation problem is the most important thing a cell can say, so it stays
    first — but it no longer *replaces* what is under it, which used to leave a
    cell carrying both a blocker and a `+2` answering neither "who are the other
    two" nor "how do I fix this". The fix for most of these is to edit the cell the
    sentence is sitting on.

    And a native tooltip has no scrollbar. Sixty tags in one is a wall of text with
    the instruction lost at the bottom of it, so the line is capped at what reads
    as a line and says how many it did not print.
    """
    marks = {"task-000001": {"assignees": {"severity": "blocker",
                                           "messages": ["nobody is on this"]}}}
    tip = _tips(page, [{"id": "task-000001", "assignees": ["a", "b"]}], "assignees", marks)[0]
    assert tip == "nobody is on this\n+1 more: b\nDouble-click to edit assignees"

    many = [f"tag-{n:02d}" for n in range(60)]
    capped = _tips(page, [{"id": "task-000001", "tags": many}], "tags")[0]
    reveal = capped.split("\n")[0]
    assert reveal.startswith("+59 more: tag-01, tag-02, "), reveal
    assert len(reveal) < 220, f"{len(reveal)} characters is a paragraph, not a line: {reveal}"
    # The count is of everything hidden and the tail is of what would not fit, so
    # the two together account for every value: 59 hidden, 22 printed, 37 not.
    printed = reveal.split(": ", 1)[1].split(" … and ")[0].split(", ")
    assert reveal.endswith(f"… and {59 - len(printed)} not shown"), reveal
    # One value, however long, always prints: a lone sixty-character login coming
    # back as "+1 more: … and 1 not shown" would be a cell hiding its own answer.
    single = _tips(page, [{"id": "task-000001", "tags": ["x", "y" * 400]}], "tags")[0]
    assert single.startswith("+1 more: " + "y" * 400 + "\n")


def test_the_reveal_line_cannot_smuggle_markup_into_the_cell(page: str):
    """The tooltip is a second seam over stored text — a tag, a login and a PR
    reference are all sentences somebody typed — and it is built by string
    concatenation into an attribute. `"` ends the attribute it sits in.
    """
    from test_injection import assert_clean, run_js

    hostile = ["ok", '" onmouseover="alert(1)', "<img src=x onerror=alert(1)>"]
    written = run_js(
        page, f"cell({{id: 'task-000001', tags: {json.dumps(hostile)}}}, 'tags')"
    )["value"]
    # The raw markup, judged by the same census every other seam on the page gets:
    # what matters is what a browser parses, not what the string looks like here.
    assert_clean(written, f"the clamped cell's tooltip: {written[:200]}")
    # And the values are in there rather than dropped. Escaping that lost them
    # would pass the census above while answering nothing — which is the failure
    # mode a census cannot see.
    assert unescape(re.search(r'title="([^"]*)"', written).group(1)) == (
        '+2 more: " onmouseover="alert(1), <img src=x onerror=alert(1)>\n'
        "Double-click to edit tags"
    )


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
    # it is drawn in — and from Enter as well as from a double-click. The
    # sentence is a parameter now, because a row refusing to hold another one is
    # the same event with a sentence that belongs to the pair rather than the
    # cell; a cell asked without one still answers with its own.
    assert "function refuse(cell, why) {\n  announce(why || cell.dataset.why);" in body
    assert "if (computed) refuse(computed);" in body


def test_the_page_never_reports_its_own_write_to_itself(page: str, client: TestClient):
    """`mine` was decided by the record in the URL, which the table has none of,
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
    assert {"severity", "record_id", "field", "message"} <= set(carried["problems"][0])
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
    # The id cell joined them, and it is not editable: it is where a move is
    # started without a mouse, and a gesture only a mouse can make is a gesture
    # half the room does not have.
    assert "const reachable = EDITABLE && (editable || key in WHY || key === 'id');" in body
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
    after = re.search(r"if \(EDITABLE\) \{\n(.*?)\n  \}", body, re.S).group(1)
    for put_back in ("rove(null, held);", "RETURN = false;", "sayDraft();", "markTargets();"):
        assert put_back in after, put_back


def test_the_editor_a_cell_opens_says_what_it_is_editing(page: str):
    """A box conjured inside a cell inherits nothing from the header above it. It
    was an unnamed input on top of the one thing that said which column it was."""
    body = script(page)

    assert "const named = esc(FIELD_LABELS[field] || field);" in body
    assert '<select data-type="text" aria-label="${named}">' in body
    assert 'data-type="${esc(EDITABLE[field])}" aria-label="${named}"' in body


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


def test_the_popup_a_cell_opens_hangs_off_the_body_and_not_off_the_cell(page: str):
    """A popup is cut off by `overflow` on any ancestor, and this table's rows
    scroll inside `.table-scroll`.

    The list used to be the input's own next sibling, so on a low row it was
    clipped against the bottom of the scroll box — and nine of the fourteen
    columns carry a suggestion list, which makes that the normal case rather than
    an edge. In the title column it was worse: a frozen cell is `position: sticky`
    with a z-index, which is a stacking context, so the list was painted under the
    sticky header too. Driven rather than grepped, because both the cell and the
    list exist only after the editor has run.
    """
    from test_injection import run_js

    answer = run_js(
        page,
        "(() => {"
        "  const id = Object.keys(DATA.rows)[0];"
        "  const row = document.createElement('tr'); row.dataset.id = id;"
        "  const cell = document.createElement('td');"
        "  cell.className = 'edit'; cell.dataset.col = 'owner';"
        "  cell.dataset.record = id; cell.dataset.field = 'owner';"
        "  row.append(cell);"
        "  openEditor(cell);"
        "  const parked = document.body.querySelectorAll('ul.suggest');"
        "  return [parked.length, parked.map(one => one.parentNode.tagName)];"
        "})()",
    )
    count, parents = answer["value"]

    assert count == 1, f"the editor opened no suggestion list at all: {answer['errors']}"
    assert parents == ["BODY"], parents


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
    for field in ("owner", "assignees", "reviewers", "cycle", "priority"):
        assert f"new-{field}" in named, field
        assert named[f"new-{field}"] == LABELS[field]

    # Status has no `<label for>`, and must not: its control is a group of radios
    # and a label names one element. The group names itself. See the same note in
    # `test_every_control_on_the_form_has_a_name`.
    assert "new-status" not in named
    assert 'role="radiogroup" aria-label="Status"' in new_page

    # The two boxes that are not facts: the title is the page's own heading and
    # the body is the document, so neither has a `<dt>` to hang a label on.
    assert re.search(r'<input name="title"[^>]*aria-label="Title"', new_page)
    assert re.search(r'<textarea name="body"[^>]*aria-label="Shaping document"', new_page, re.S)
    # And the page says what it is, which it did not: its `<h1>` was an empty
    # input.
    assert "<h1>New record</h1>" in new_page


# --------------------------------------------------------------------------- #
# 8. A row you type into
#
# Creating a record meant leaving the table for `/new`, which is the right page
# for writing a pitch properly and the wrong one for "and a task for the docs".
# The `+` row is the same act at the scale of a row: pick the kind, fill in the
# columns that kind has, press Create — through the same `POST /api/record`,
# because two ways to create a record is two sets of rules about what a new
# record must carry, and they disagree by Thursday.
#
# The rows are drawn by the page's own script, so most of what is asserted below
# is asserted by running that script against the page's own markup and handing
# `fetch` the answers a server really gives.
# --------------------------------------------------------------------------- #


# Enough turns of the microtask queue for a write path to run to its end. The
# driver queues timers rather than firing them, so nothing here can be waited for
# with a clock — and a `fetch` that resolves immediately still takes one turn per
# `await`, of which a create has half a dozen.
SETTLE = "for (let i = 0; i < 50; i++) await Promise.resolve();"


def drive_table(page: str, expression: str, replies: list[dict] | None = None) -> dict:
    """The table's own script, run against the table's own markup.

    `page=True` because every claim below is about what the script does to the
    page it is on — which row it drew, which one it refused, what it put in the
    live region — and a shim that answers those from a phantom is a shim
    agreeing with itself.
    """
    from test_injection import run_js

    answer = run_js(page, expression, page=True, replies=replies or [])
    assert answer["settled"], (
        "the expression never settled: something in the write path hung, which in "
        "a browser is a row that stays half-created with nothing said"
    )
    assert not [error for error in answer["errors"] if error.startswith("expression:")], (
        answer["errors"]
    )
    return answer


def test_the_table_ends_in_a_row_that_makes_one(page: str):
    """The `+` is the last row of the table and not a button above it.

    Where a plan grows is where a plan ends, and a control that lives outside the
    rows is a control that has to be found. It is drawn after whatever the
    filters left — including after all three empty states, because a plan with
    nothing in it is exactly when the way to put something in it has to be on
    screen — and it is never filtered, because a row that does not exist yet
    cannot match a filter.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  const rows = [...tbody.querySelectorAll('tr')];"
        "  const last = rows[rows.length - 1];"
        "  return {adders: tbody.querySelectorAll('tr.adder').length,"
        "          lastIsAdder: last.classList.contains('adder'),"
        "          control: !!last.querySelector('button')};"
        "})()",
    )

    assert answer["value"] == {"adders": 1, "lastIsAdder": True, "control": True}


def test_an_empty_plan_still_offers_the_row_that_would_end_it(client: TestClient):
    """Empty must not look like broken, and an empty table that also has no way to
    add anything looks like a tool that has not finished loading.

    The sentence stays what it was — this plan has no records yet — and the
    control sits directly under it, which is what turns a statement into an
    invitation.
    """
    from openproj.model import Config
    from openproj.render import render_table

    page = render_table(build_index([], Config(), date(2026, 8, 17)), base_commit="deadbee")
    answer = drive_table(
        page,
        "(() => ({empty: !!tbody.querySelector('tr.nothing'),"
        "         adder: !!tbody.querySelector('tr.adder'),"
        "         order: [...tbody.querySelectorAll('tr')]"
        "           .map(tr => tr.getAttribute('class'))}))()",
    )

    assert answer["value"]["empty"], "the empty sentence is still drawn"
    assert answer["value"]["adder"], "and the way out of it is drawn under it"
    assert answer["value"]["order"] == ["nothing", "adder"]


def test_a_rendered_file_offers_no_row_to_type_into(seed_root: Path, tmp_path: Path):
    """`openproj render` writes files, and a file has no server to create with.

    The whole of the draft lives inside the editable branch, so an export does
    not carry the code at all rather than carrying it and refusing — the same
    line the rest of this page already draws.
    """
    records, config, _ = load_repo(seed_root)
    render_static(build_index(records, config, date(2026, 8, 17)), tmp_path)
    exported = script((tmp_path / "table.html").read_text(encoding="utf-8"))

    assert "function adderHtml" not in exported
    assert "+ New row" not in exported
    assert "/api/record" not in exported


def test_the_new_row_offers_the_fields_that_kind_has_and_no_others():
    """A project has no appetite of its own and a pitch is the kind that is
    shaped, and the row knows that because the models do.

    Derived from `_new_row_fields`, which is derived in turn from `EDITABLE` and
    the models' own fields — so this cannot pass by agreeing with a list somebody
    typed twice. `size` is the one column that is not simply its own field: on a
    stored row it shows an appetite or an assumed default and refuses to be
    typed into, and on a row that does not exist yet there is no assumption
    standing in for a decision.
    """
    fields = _new_row_fields()

    assert fields["pitch"]["size"] == "person_weeks"
    assert fields["task"]["size"] == "person_weeks"
    assert "size" not in fields["project"], "a project has no size of its own"
    for kind, columns in fields.items():
        assert "id" not in columns, f"the server mints the id, not the browser ({kind})"
        for derived in ("start", "end", "blocked_by", "progress"):
            assert derived not in columns, f"{derived} is the scheduler's ({kind})"
        for column, field in columns.items():
            assert field in EDITABLE, f"{column} writes to a field nobody owns"


def test_the_row_says_which_columns_it_cannot_be_typed_into_and_why(page: str):
    """Two different reasons a cell takes nothing, and a blank cell says neither.

    A project has no Appetite; nobody has a Start, because the scheduler works it
    out. Both are drawn as cells that cannot be filled in, and each carries the
    sentence that belongs to it — asked of the map rather than listed in the
    page, so a column that becomes kind-only later explains itself without this
    line changing.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  openDraft(); chooseKind('project');"
        "  const tip = column => {"
        "    const td = tbody.querySelector(`tr.draft td[data-col=\"${column}\"]`);"
        "    return [td.getAttribute('class'), td.getAttribute('title')];"
        "  };"
        "  return {size: tip('size'), start: tip('start'), title: tip('title')};"
        "})()",
    )
    got = answer["value"]

    assert got["size"][0] == "draft-none"
    assert got["size"][1] == "A project has no appetite"
    assert got["start"][0] == "draft-none"
    assert "Derived from" in got["start"][1], "the scheduler's own sentence, not a new one"
    assert "edit" in got["title"][0], "and the column it does have is a control"


def test_the_kind_is_chosen_first_and_the_row_follows_from_it(page: str):
    """"First choose the kind, then set the fields" — because until the kind is
    chosen there is no answer to which fields the row even has.

    Switching it afterwards keeps what has been typed, which is the lesson the
    create form already paid for: a title typed before switching used to be a
    title typed again. What does not survive is a value the new kind has no
    column for — a size typed while the row was a task is not a project's to
    carry, and posting it is a 422 quoting a field that is no longer on screen.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  openDraft();"
        "  const before = !!tbody.querySelector('tr.draft');"
        "  chooseKind('task');"
        "  stage('title', 'A chore nobody pitched');"
        "  stage('person_weeks', '2');"
        "  const asTask = JSON.stringify(DRAFT.fields);"
        "  chooseKind('project');"
        "  return {before, after: !!tbody.querySelector('tr.draft'),"
        "          asTask, asProject: JSON.stringify(DRAFT.fields)};"
        "})()",
    )
    got = answer["value"]

    assert got["before"] is False, "no row before there is a kind to draw it from"
    assert got["after"] is True
    assert json.loads(got["asTask"])["person_weeks"] == 2
    kept = json.loads(got["asProject"])
    assert kept["title"] == "A chore nobody pitched", "the typing survives the switch"
    assert "person_weeks" not in kept, "a project has no appetite to carry"
    # The two a record is created with, shown rather than left blank: a cell that
    # silently becomes `thinking` on save is the row lying about what it will
    # write. Both are read off the model in `table.py`, so this moved on its own
    # when the ladder gained a rung at its foot — which is what the word here is
    # asserting: that the row shows the default rather than a copy of it.
    assert kept["status"] == "thinking" and kept["priority"] == "medium"


def test_a_row_created_inline_goes_through_the_one_create_route(page: str):
    """One POST, to the route the create form uses, carrying no id and no path.

    An id chosen by a browser is a path chosen by a browser the moment it becomes
    `tasks/<id>.md`. The body is the kind's own template — the same map `/new`
    offers — because a pitch made here has to be the same document as a pitch
    made there; a plan where a shaping template depends on which page somebody
    happened to use is a plan with two kinds of pitch in it.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('task');"
        "  stage('title', 'Write the migration note');"
        f" await createDraft(); {SETTLE}"
        "  return document.getElementById('state').textContent;"
        "})()",
        replies=[
            {"status": 201, "json": {"id": "task-a1b2c3", "outcome": "committed",
                                     "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {}, "problems": []}},
        ],
    )
    posts = [call for call in answer["calls"] if call["method"] == "POST"]

    assert len(posts) == 1 and posts[0]["url"] == "/api/record"
    sent = json.loads(posts[0]["body"])
    assert sent["fields"]["kind"] == "task"
    assert sent["fields"]["title"] == "Write the migration note"
    assert "id" not in sent["fields"], "the server mints it"
    assert sent["base_commit"], "a create is compared against the commit the page was drawn at"
    assert "## Progress" in sent["body"], "the kind's own template, as `/new` would have given it"
    assert "task-a1b2c3" in answer["value"], "and the reader is told what was made"


def test_the_created_row_is_re_read_rather_than_invented(page: str):
    """A new row's dates, its size, what it blocks and which project it counts
    against are the server's arithmetic.

    Drawn from what was posted, the row would arrive with every scheduler column
    empty and would fill in on the next reload — which is the same defect as a
    stale table, one row wide. So the page re-reads the payload it was built
    from, and the page moves forward with the repository: the commit the create
    returned becomes the base the next save is compared against.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('task'); stage('title', 'A new row');"
        f" await createDraft(); {SETTLE}"
        "  return {base: BASE.value, rows: Object.keys(DATA.rows).length, draft: DRAFT};"
        "})()",
        replies=[
            {"status": 201, "json": {"id": "task-a1b2c3", "outcome": "committed",
                                     "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {"task-a1b2c3": {"id": "task-a1b2c3",
                                                              "predicates": []}},
                                     "problems": []}},
        ],
    )

    assert [call["url"] for call in answer["calls"]] == ["/api/record", "/api/table.json"]
    assert answer["value"]["base"] == "c0ffee"
    assert answer["value"]["rows"] == 1, "the table is the plan as it is now, not as it was"
    assert answer["value"]["draft"] is None, "and the row that was typed is a record now"


def test_a_row_with_no_title_is_never_sent(page: str):
    """A title at minimum, refused here rather than by the server.

    The server refuses a titleless row too — what it would commit does not read
    back as a record — but it refuses it as YAML, and the reason a row needs a title is not
    about YAML: it is that a row with none is a row nobody can find again, in a
    table whose first column is a mint-fresh id nobody has ever seen. Everything
    else a status demands is left to `validate_all`, which is the only thing that
    knows the rules and which of them a record is old enough to be held to.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('pitch');"
        "  stage('owner', 'ann');"
        f" await createDraft(); {SETTLE}"
        "  return {said: [...document.getElementById('draft-problems').children]"
        "            .map(li => li.textContent),"
        "          hidden: document.getElementById('draft-problems').hidden,"
        "          kept: JSON.stringify(DRAFT.fields)};"
        "})()",
    )
    got = answer["value"]

    assert answer["calls"] == [], "nothing was sent"
    assert got["hidden"] is False
    assert got["said"] == ["A row needs a title — it is how anybody finds it again."]
    assert json.loads(got["kept"])["owner"] == "ann", "and nothing typed was thrown away"


def test_what_the_server_refuses_a_row_with_is_shown_beside_it(page: str):
    """The client's check is a courtesy and the server's answer is the truth.

    A create is refused with every blocker at once, and each one is a sentence
    about a field. They land in the bar under the row — a create has no row to
    sit beside, and `#row-conflict` is for a save that collided — as text nodes,
    because a Problem quotes whatever the plan holds.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('pitch'); stage('title', 'A bet'); stage('status', 'ready');"
        f" await createDraft(); {SETTLE}"
        "  return {said: [...document.getElementById('draft-problems').children]"
        "            .map(li => li.textContent),"
        "          draft: !!DRAFT};"
        "})()",
        replies=[{"status": 422, "json": {"problems": [
            {"severity": "blocker", "record_id": "pitch-000000", "field": "owner",
             "message": "a ready record needs an owner"},
            {"severity": "blocker", "record_id": "pitch-000000", "field": "shaped_by",
             "message": "a ready pitch needs to say who shaped it"},
        ]}}],
    )
    got = answer["value"]

    assert got["said"] == ["a ready record needs an owner",
                           "a ready pitch needs to say who shaped it"]
    assert got["draft"] is True, "the row is still there, with everything typed into it"


def test_a_half_filled_row_is_not_remembered_anywhere(page: str):
    """A reload loses it, and that is the decision rather than the oversight.

    A draft kept in `localStorage` is a record of the plan that is not in git,
    that nobody can review and that no base commit covers — the one draft this
    app does keep, on the detail page, has to carry the commit it was drafted
    against precisely so that it can say it has gone stale. That is worth paying
    for a shaping document somebody spent an hour on. It is not worth paying for
    four short fields with Create sitting under them.

    What the draft does survive is a redraw: it lives in one variable and
    `draw()` builds every row from state, so sorting the table with a row half
    typed does not cost the typing.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  openDraft(); chooseKind('task'); stage('title', 'Half a thought');"
        "  draw();"
        "  const cell = tbody.querySelector('tr.draft td[data-field=\"title\"]');"
        "  return cell.textContent;"
        "})()",
    )

    assert answer["value"] == "Half a thought", "a redraw keeps it"
    assert answer["stored"] == {}, "and nothing outlives the page"


def test_a_row_created_inline_lands_as_a_commit_with_the_right_kind_and_author(
    client: TestClient, repo_path: Path
):
    """The end of it, in git: the file, its kind, its directory, and who gets the
    credit.

    The author is the session and only the session — it is the team's only audit
    trail and it is worth exactly what the guarantee that nobody can name
    themselves in a request body is worth. This posts what the row posts: a kind,
    a title, the status and priority the row showed, and the kind's template as
    the body.
    """
    made = create(
        client,
        {"kind": "task", "title": "Write the migration note", "status": "shaping",
         "priority": "medium"},
        body="## Problem\n\n## Progress\n\n- [ ]\n",
    )

    assert made.status_code == 201
    new_id = made.json()["id"]
    assert new_id.startswith("task-")
    stored = file_at(repo_path, made.json()["commit"], f"tasks/{new_id}.md")
    assert "kind: task" in stored and "title: Write the migration note" in stored
    assert "## Progress" in stored, "the shaping document is the record"
    commit = commit_at(repo_path, made.json()["commit"])
    assert commit.author.name == ANN.login
    assert new_id in commit.message
    # And it is in the plan the moment it is committed, which is what the row
    # re-reads to draw itself.
    assert new_id in client.get("/api/table.json").json()["rows"]


# --------------------------------------------------------------------------- #
# 9. A row you move
#
# Dropping A on B makes B the parent of A. The rule about which kind may hold
# which is `model.PARENT_KINDS` and is shipped to the page, because a drop that
# would break it has to be refused while the mouse is still down — a rule that
# only answers after the request is a rule somebody meets as a 422.
#
# The two drags on this page do not overlap by construction: a grab in `thead` is
# a column being resized (a `pointerdown` on a `<th>`), a grab in `tbody` is a
# row being moved (a native drag that starts on a handle inside a `<td>`), and no
# element carries both.
# --------------------------------------------------------------------------- #


# Picking a row up by its grip, exactly as a browser does it.
PICK_UP = """
  const grip = tbody.querySelector('tr[data-id="%(id)s"] .rowgrip');
  const start = new Event('dragstart');
  start.target = grip;
  tbody.dispatchEvent(start);
"""

# Dragging over a row, and what it answered. `defaultPrevented` is the answer:
# calling it is the whole of "you may drop here", and a row refuses by not.
OVER = """
  const over = new Event('dragover');
  over.target = tbody.querySelector('%(where)s');
  tbody.dispatchEvent(over);
"""


def test_the_rule_the_page_refuses_with_is_the_model_s(page: str):
    """Not three lines of JavaScript saying the same thing.

    This map was widened yesterday — a task may now hang straight off a project —
    and a page still refusing that would be the tool arguing with its own
    validator, in the one direction where the page wins: the drop never happens,
    so nothing is ever refused loudly enough to notice.
    """
    carried = payload(page)["parent_kinds"]

    assert carried == {kind: list(kinds) for kind, kinds in PARENT_KINDS.items()}
    assert "PARENT_KINDS[child.kind]" in script(page), "and it is what the refusal reads"


def test_a_drop_that_breaks_containment_is_refused_before_it_is_sent(page: str):
    """A task cannot hold a task, and the row that cannot take it says so from the
    moment the other one is picked up — not after a save comes back 422.

    Two channels, because one of them is the browser's: the row is drawn refusing
    it, and `dragover` never calls `preventDefault` on it, which is what makes
    the browser draw its own no-drop cursor and — the part that matters — what
    stops `drop` from firing at all. The refusal is structural rather than a
    check at the other end that somebody has to remember to write.
    """
    answer = drive_table(
        page,
        "(() => {"
        + PICK_UP % {"id": TASK}
        + OVER % {"where": f'tr[data-id="{OTHER}"] td'}
        # The mark this gesture adds, not the whole class list: a row also
        # carries how deep in the tree it is drawn, and reading the attribute
        # made this test fail on a row moving one level in.
        + f'  const target = tbody.querySelector(\'tr[data-id="{OTHER}"]\');'
        + "  const drawn = ['can-hold', 'no-hold']"
        + "    .filter(one => target.classList.contains(one)).join(' ');"
        + "  const drop = new Event('drop');"
        + f'  drop.target = tbody.querySelector(\'tr[data-id="{OTHER}"] td\');'
        + "  tbody.dispatchEvent(drop);"
        "  return {allowed: over.defaultPrevented, drawn, moving: MOVING};"
        "})()",
    )
    got = answer["value"]

    assert got["allowed"] is False, "the drop was never permitted"
    assert got["drawn"] == "no-hold", "and the row it would have landed on shows it"
    assert "table.moving tr.no-hold > td" in page, "which is a rule that paints something"
    # A browser would not have delivered the drop at all, having refused it above.
    # Delivered by hand anyway, nothing is written: a refusal that only holds
    # while the browser is co-operating is not a refusal.
    assert answer["calls"] == [], "and no request was made even so"


def test_a_row_that_may_hold_it_says_so_before_the_mouse_arrives(page: str):
    """The other half of the same claim, and the one that makes it a design rather
    than a refusal: every row is marked the moment a row is picked up, so where a
    move can land is visible without hunting for it.

    On the cells and not on the `<tr>`, because the two frozen columns paint a
    background of their own and a row-level colour is drawn underneath them —
    the id and the title would have been the two cells that did not answer.
    """
    answer = drive_table(
        page,
        "(() => {"
        + PICK_UP % {"id": TASK}
        + "  const seen = {};"
        "  for (const tr of tbody.querySelectorAll('tr[data-id]'))"
        # A row may already carry the stripe that says something on it is wrong,
        # so what is read here is the mark this gesture adds, not the class list.
        "    seen[tr.dataset.id] = ['can-hold', 'no-hold']"
        "      .filter(one => tr.classList.contains(one)).join(' ');"
        "  return {seen, table: table.classList.contains('moving')};"
        "})()",
    )
    seen = answer["value"]["seen"]

    assert answer["value"]["table"] is True
    assert seen[PROJECT] == "can-hold", "a task may hang straight off a project"
    assert seen[PITCH] == "no-hold", "and it is already in that one"
    assert seen[OTHER] == "no-hold", "and a task holds nothing"
    assert seen[TASK] == "", "the row in your hand is not a target"
    assert "table.moving tr.can-hold > td" in page


def test_a_row_that_belongs_to_nothing_is_never_offered_a_move(page: str):
    """The top of the ladder has no handle at all.

    A control that is drawn and then refuses is a control that has to be tried;
    the missing grip says the same thing without a sentence — and the cell still
    carries one for the reader who asks, because an absence explains nothing on
    its own.

    Which kinds belong to nothing is asked of the page's own `PARENT_KINDS`
    rather than named here. It was `project` until a `product` was added above
    it, and this test passed for the wrong reason the whole way: a project now
    has somewhere to go, and the row with nowhere to go is a kind this corpus
    does not contain. Since the flip the set holds three — the product because
    it is the top of the tree, the two inbox kinds because an issue belongs to
    nothing (`under=()` on their rungs) — and the page's `movable` must refuse
    all of them, the inbox pair even though, being unplanned, they never have
    a row on this table to grow a grip in the first place: the payload ships
    every kind, and a gesture must refuse even a row that should not exist.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  const grip = id => !!tbody.querySelector(`tr[data-id=\"${id}\"] .rowgrip`);"
        "  const top = Object.keys(PARENT_KINDS)"
        "    .filter(k => !(PARENT_KINDS[k] || []).length);"
        + f"  return {{project: grip('{PROJECT}'), task: grip('{TASK}'),"
        + "           top: top, movable: top.map(k => movable({kind: k})),"
        + "           said: moveTip({kind: top[0]})};"
        + "})()",
    )
    got = answer["value"]

    tops = [kind for kind in KIND_NAMES if not PARENT_KINDS[kind]]
    assert got["top"] == tops, got["top"]
    assert set(tops) == {"product", "issue", "note"}, (
        "spelled out once so the derivation above cannot drift with the code"
    )
    assert got["movable"] == [False] * len(tops)
    assert got["said"] == "A product belongs to nothing, so there is nothing to file it under"
    # And the two kinds this corpus does hold both have somewhere to go now.
    assert got["project"] is True and got["task"] is True


def test_a_drop_is_one_patch_of_one_field_through_the_save_path(page: str):
    """A parent is a field like any other: the same PATCH, the same base commit,
    the same one-key body, the same 409.

    The gesture is new; the save path is not. A drop that posted the row would
    overwrite whatever somebody else changed while this tab was open, and a drop
    that carried a body would rewrite the shaping document it was dragged by.
    """
    answer = drive_table(
        page,
        "(async () => {"
        + PICK_UP % {"id": TASK}
        + OVER % {"where": f'tr[data-id="{PROJECT}"] td'}
        + "  const drop = new Event('drop');"
        "  drop.target = tbody.querySelector('tr[data-id=\"%s\"] td');"
        "  tbody.dispatchEvent(drop);"
        f" {SETTLE}"
        "  return {moving: MOVING, said: document.getElementById('state').textContent};"
        "})()" % PROJECT,
        replies=[
            {"status": 200, "json": {"outcome": "committed", "commit": "c0ffee",
                                     "conflict": None}},
            {"status": 200, "json": {"rows": {}, "problems": []}},
        ],
    )
    patches = [call for call in answer["calls"] if call["method"] == "PATCH"]

    assert len(patches) == 1, "one drop, one commit"
    assert patches[0]["url"] == f"/api/record/{TASK}"
    sent = json.loads(patches[0]["body"])
    assert sent["fields"] == {"parent": PROJECT}, "one field travels, and it is the parent"
    assert sent["body"] is None, "an empty body is a replacement, not an omission"
    assert sent["base_commit"], "compared against the commit the page was drawn at"
    assert answer["value"]["moving"] is None, "and the table is not still holding it"
    assert PROJECT in answer["value"]["said"], "the move is announced, not only drawn"


def test_a_row_can_be_taken_out_of_what_holds_it(page: str):
    """Unparenting is a drop like any other, onto the one row that is not a
    record: the `+` row at the bottom.

    It is the same idea said the same way — under everything, outside the tree —
    and it is the only target that is always on screen, because that row is
    sticky against the bottom of the scroll box. It offers itself only while
    something is being moved, and only when there is something to take it out of;
    a row that belongs to nothing is not offered a way to belong to less.
    """
    answer = drive_table(
        page,
        "(async () => {"
        + PICK_UP % {"id": TASK}
        + "  const out = document.getElementById('unparent');"
        "  const offered = {hidden: out.hidden, said: out.textContent};"
        + OVER % {"where": "tr.adder"}
        + "  const drop = new Event('drop');"
        "  drop.target = tbody.querySelector('tr.adder td');"
        "  tbody.dispatchEvent(drop);"
        f" {SETTLE}"
        "  return {offered, allowed: over.defaultPrevented,"
        "          said: document.getElementById('state').textContent};"
        "})()",
        replies=[
            {"status": 200, "json": {"outcome": "committed", "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {}, "problems": []}},
        ],
    )
    got = answer["value"]

    assert got["offered"]["hidden"] is False
    assert got["offered"]["said"] == f"Take {TASK} out of {PITCH}"
    assert got["allowed"] is True
    sent = json.loads(answer["calls"][0]["body"])
    assert sent["fields"] == {"parent": None}, "null, which is what no parent is stored as"
    assert "no longer" in got["said"]


def test_a_reparent_leaves_no_derived_column_stale(client: TestClient, page: str):
    """A drop changes what the scheduler draws, and on rows nobody dragged.

    Moving a task out of a pitch changes that pitch's start, its progress and the
    project's rollup — three derived columns on two other rows. The rule one
    screen up in the source, that a save re-reads the problems and never the
    forecast, is about not moving dates under somebody who is mid-edit; a drop is
    a gesture that is over, and a table that does not move after one looks like a
    drop that did nothing.

    Both halves are asserted with the server's own answer: what the payload says
    after the write, and what the page draws when it is handed exactly that.
    """
    before = client.get("/api/table.json").json()
    moved = save(client, TASK, {"parent": PROJECT})
    after = client.get("/api/table.json").json()

    assert moved.status_code == 200
    assert before["rows"][TASK]["parent"] == PITCH
    assert after["rows"][TASK]["parent"] == PROJECT
    # The rows that were not touched and moved anyway.
    assert after["rows"][PITCH]["progress_text"] != before["rows"][PITCH]["progress_text"]
    assert after["rows"][PITCH]["start"] != before["rows"][PITCH]["start"]

    answer = drive_table(
        page,
        "(async () => {"
        + PICK_UP % {"id": TASK}
        + OVER % {"where": f'tr[data-id="{PROJECT}"] td'}
        + "  const drop = new Event('drop');"
        "  drop.target = tbody.querySelector('tr[data-id=\"%s\"] td');"
        "  tbody.dispatchEvent(drop);"
        f" {SETTLE}"
        # The progress column is a bar now and carries its count in the bar's own
        # tooltip; the date columns are drawn short. Both are read where they are
        # drawn rather than where they used to be.
        "  const cell = column => tbody.querySelector("
        "    `tr[data-id=\"%s\"] td[data-col=\"${column}\"]`);"
        "  const meter = cell('progress').querySelector('.meter');"
        # `getAttribute` and not `.title`: the driver's DOM reflects attributes,
        # not every property a browser mirrors them onto.
        "  return {progress: meter ? (meter.getAttribute('title') || '') : '',"
        "          start: cell('start').textContent.trim()};"
        "})()" % (PROJECT, PITCH),
        replies=[
            {"status": 200, "json": moved.json()},
            {"status": 200, "json": after},
        ],
    )
    got = answer["value"]

    assert after["rows"][PITCH]["progress_text"] in got["progress"], (
        "the pitch's progress is what the plan says now, not what it said before the drop"
    )
    # `2026-07-14` is drawn `26.07.14`: two date columns of ten characters each
    # were what made every row on a laptop two lines tall. The row still carries
    # the ISO string, which is what the sort reads and what this compares against.
    year, month, day = after["rows"][PITCH]["start"].split("-")
    # Day first — `14.07` — with the two-digit year trailing in its own element,
    # which the column drops when it tightens. `startswith`, because the driver's
    # DOM does not gather a nested span's text into its parent's `textContent`
    # the way a browser does, so the year may or may not be in what comes back.
    assert got["start"].startswith(f"{day}.{month}"), got["start"]
    assert year[:2] not in got["start"], "the century is still being drawn"


def test_a_column_is_dragged_in_the_header_and_a_row_in_the_body(page: str):
    """The one invariant that keeps the two gestures apart: a grab that starts in
    `thead` resizes a column and a grab that starts in `tbody` moves a row, and
    neither may fire the other.

    They are different mechanisms as well as different regions — the column grip
    is a `pointerdown` handler on a `<th>`, the row grip is a native drag on a
    handle inside a `<td>` — so there is no element that carries both and no
    ordering between them to get right. The narrower rule, that a row is picked
    up by its grip rather than anywhere in its body, is the same rule said more
    strictly: it is what keeps a cell's text selectable and the editor a cell
    opens usable.
    """
    body = script(page)
    # The header's grip, and everything the header does with a grab.
    column = re.search(
        r"headers\.forEach\(\(th, i\) => \{\n.*?\n\}\);", body, re.S
    ).group(0)

    assert "grip.onpointerdown = event => {" in column and "th.append(grip);" in column
    # `dragging` is the column resize's own flag and says nothing about a native
    # drag; what would make a header start one is either of these, and neither is
    # anywhere in it.
    assert "draggable" not in column and "dragstart" not in column
    # The body's, and it only starts on the handle.
    for gesture in ("dragstart", "dragover", "drop", "dragend"):
        assert f"tbody.addEventListener('{gesture}'" in body, gesture
    assert "tbody.addEventListener('pointerdown'" not in body, (
        "nothing in the rows listens for the gesture that resizes a column"
    )
    row = re.search(r"tbody\.addEventListener\('dragstart'.*?\n  \}\);", body, re.S).group(0)
    assert "event.target.closest('.rowgrip')" in row, "a row is picked up by its grip"
    assert "event.preventDefault();" in row, "and a selection dragged out of a cell is not a move"
    assert "th" not in re.sub(r"[a-zA-Z]th|th[a-zA-Z]", "", row), "the header is not in reach"
    # And the handle itself is only ever drawn into a cell of the id column.
    assert 'class="rowgrip" draggable="true"' in body
    assert not re.search(r"<th[^>]*draggable", page), "no header is draggable"


def test_a_row_can_be_moved_without_a_mouse(page: str):
    """Dragging is a mouse gesture, and this page has a skip link because somebody
    will arrive without one.

    So the move has a keyboard equal rather than a documented gap, and it is the
    same move: Enter on the id cell — the cell that is the row's own name, and
    where the grip is drawn — picks the row up, the arrows that already walk the
    grid carry it, Enter on a row files it there and Escape leaves it where it
    was. The same rows are lit, the same rows refuse, and the same PATCH is sent.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  const press = (id, column, key) => {"
        "    const event = new Event('keydown');"
        "    event.key = key;"
        "    event.target = tbody.querySelector("
        "      `tr[data-id=\"${id}\"] td[data-col=\"${column}\"]`);"
        "    tbody.dispatchEvent(event);"
        "    return event.defaultPrevented;"
        "  };"
        "  const took = press('%(task)s', 'id', 'Enter');"
        "  const picked = MOVING;"
        "  press('%(other)s', 'title', 'Enter');"
        "  const refused = document.getElementById('state').textContent;"
        "  press('%(project)s', 'title', 'Enter');"
        f" {SETTLE}"
        "  return {took, picked, refused, moving: MOVING};"
        "})()" % {"task": TASK, "other": OTHER, "project": PROJECT},
        replies=[
            {"status": 200, "json": {"outcome": "committed", "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {}, "problems": []}},
        ],
    )
    got = answer["value"]

    assert got["took"] is True, "Enter on the id cell is the move, not the editor"
    assert got["picked"] == TASK
    assert got["refused"] == "a task belongs to a pitch or a project, not to a task", (
        "a refused target says why, out loud — the drawn refusal is the half a "
        "keyboard reader does not get"
    )
    assert got["moving"] is None
    patches = [call for call in answer["calls"] if call["method"] == "PATCH"]
    assert len(patches) == 1, "the illegal one was refused and the legal one was sent"
    assert json.loads(patches[0]["body"])["fields"] == {"parent": PROJECT}


def test_escape_leaves_the_row_where_it_was(page: str):
    """The way out of a move that was started by accident, and it writes nothing.

    A move in the air owns Enter and Escape until it lands, so the cell editor
    cannot open underneath it — and the moment it is cancelled the grid's own
    keys are the grid's again.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  const press = (id, column, key) => {"
        "    const event = new Event('keydown');"
        "    event.key = key;"
        "    event.target = tbody.querySelector("
        "      `tr[data-id=\"${id}\"] td[data-col=\"${column}\"]`);"
        "    tbody.dispatchEvent(event);"
        "  };"
        + f"  press('{TASK}', 'id', 'Enter');"
        + f"  press('{TASK}', 'id', 'Escape');"
        + "  return {moving: MOVING, marked: table.classList.contains('moving'),"
        "          said: document.getElementById('state').textContent,"
        "          rows: [...tbody.querySelectorAll('tr.can-hold, tr.no-hold')].length};"
        "})()",
    )
    got = answer["value"]

    assert answer["calls"] == [], "nothing was written"
    assert got["moving"] is None and got["marked"] is False
    assert got["rows"] == 0, "and every row is a row again"
    assert TASK in got["said"]


def test_the_route_the_table_re_reads_is_the_payload_it_was_drawn_from(
    client: TestClient, page: str
):
    """One shape, so a table that has just written something is built exactly like
    a table that has just been opened.

    The alternative was to re-read `/api/index.json`, which answers with the plan
    and spans — and turning those into rows means `_row` written a second time in
    JavaScript: a progress fraction counted out of a body, a blocker count, a
    project walked up the tree. A copy that only runs after a save is a copy
    nobody would ever look at again.
    """
    fresh = client.get("/api/table.json")

    assert fresh.status_code == 200
    assert fresh.json() == payload(page)


def test_the_count_says_how_many_rows_there_are_to_be_shown_of(page: str, client: TestClient):
    """"18 of 17 shown", live on the page, the first time a row was created from
    the table.

    The first number was the script's and the second was the template's, which
    was true for as long as the only way to change how many rows the plan has was
    to reload. Both are the script's now, written by the same function, on the
    same pass: a count that contradicts itself inside one sentence is the whole
    of what a count is for.
    """
    assert '<span id="shown" class="num">' in page and 'id="total"' in page
    assert "document.getElementById('total').textContent" in script(page)

    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('task'); stage('title', 'One more');"
        f" await createDraft(); {SETTLE}"
        "  return [document.getElementById('shown').textContent,"
        "          document.getElementById('total').textContent];"
        "})()",
        replies=[
            {"status": 201, "json": {"id": "task-a1b2c3", "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {
                "task-a1b2c3": {"id": "task-a1b2c3", "predicates": []},
                "task-d4e5f6": {"id": "task-d4e5f6", "predicates": []},
            }, "problems": []}},
        ],
    )

    # As strings, because a live region holds text and the shim holds what it was
    # handed: what is asserted is the two numbers agreeing, not their type.
    assert [str(one) for one in answer["value"]] == ["2", "2"], (
        "one plan, one number of rows in it"
    )


def test_a_redraw_in_the_middle_of_a_move_leaves_the_last_row_saying_what_it_says(page: str):
    """The sticky bar at the bottom of the plan went blank in the middle of a move.

    `startMoving` set the way-out button's words and its `hidden` on the element,
    and `draw()` rebuilds the whole tbody: `adderHtml` emits the button hidden
    and wordless, `moving` is still on the table so `+ New row` stays hidden, and
    `#unparent:not([hidden])` stops matching the button that was just re-hidden.
    Typing one character into the search box did it, as did any facet and any
    sort — and the keyboard move redraws by design. What was on screen was an
    empty strip, while the live region went on saying "The row at the bottom
    takes it out of pitch-b20000".

    Both states are checked, because the row that has nowhere to go out of is the
    other way to end up with nothing drawn there — and it is the commoner one: a
    row is usually dragged INTO something, which means it was in nothing.
    """
    answer = drive_table(
        page,
        "(() => {"
        "  const bar = () => {"
        "    const out = document.getElementById('unparent');"
        "    const rootless = document.getElementById('rootless');"
        "    return {said: out.hidden ? '' : out.textContent,"
        "            rootless: rootless.hidden ? '' : rootless.textContent};"
        "  };"
        + PICK_UP % {"id": TASK}
        + "  const held = bar();"
        "  draw();"
        "  const redrawn = bar();"
        # The other state, on the same row: one nothing holds. There is no such
        # row in this corpus that may also be moved — every task is in the pitch
        # — so it is made by taking this one out, which is what the page itself
        # does the moment an unparent lands.
        f" DATA.rows['{TASK}'].parent = null;"
        + f"  startMoving('{TASK}');"
        + "  const loose = bar();"
        "  draw();"
        "  return {held, redrawn, loose, looseRedrawn: bar()};"
        "})()",
    )
    got = answer["value"]

    assert got["held"]["said"] == f"Take {TASK} out of {PITCH}"
    assert got["redrawn"] == got["held"], "a redraw mid-move does not change what it offers"
    assert got["loose"]["rootless"] == f"{TASK} is not inside anything"
    assert got["looseRedrawn"] == got["loose"]
    for state in got.values():
        assert state["said"] or state["rootless"], "and it is never an empty strip"


def test_the_row_a_drop_would_land_in_is_named_beside_the_cursor(page: str):
    """A drop names its target rather than asking about it.

    No modal: a dialog on every drag is a toll on a gesture that is already
    deliberate — pick the row up, carry it, let go on the right one — and a
    reparent is one field and one commit that dragging back undoes. So the answer
    is drawn where the hand already is, before the drop rather than after it, and
    it is the row's title, because the ground under the cursor already says which
    row it is.

    A row that cannot hold this one is named nowhere: `dragover` refuses it
    before the label is written, which is the same refusal that stops the drop.
    """
    answer = drive_table(
        page,
        "(() => {"
        + PICK_UP % {"id": TASK}
        # Each drag-over in a block of its own: the snippet names the event, and
        # three of them in one scope is a redeclaration rather than three moves.
        + "{" + OVER % {"where": f'tr[data-id="{PROJECT}"] td'} + "}"
        # Parked on the body, so that is where it is asked for — the same place
        # the cells' suggestion popups are found, and for the same reason.
        + "  const into = document.body.querySelector('#into');"
        "  const onto = {said: into.textContent, hidden: into.hidden};"
        + "{" + OVER % {"where": f'tr[data-id="{OTHER}"] td'} + "}"
        + "  const refused = {said: into.textContent, hidden: into.hidden};"
        + "{" + OVER % {"where": "tr.adder"} + "}"
        + "  const out = {said: into.textContent, hidden: into.hidden};"
        "  stopMoving();"
        "  return {onto, refused, out, after: into.hidden};"
        "})()",
    )
    got = answer["value"]

    assert got["onto"] == {"said": "→ into Distributed driver", "hidden": False}, (
        "the title, which is the answer to 'is that the right row'"
    )
    assert got["refused"] == {"said": "", "hidden": True}, (
        "a task holds nothing, so it is not named as anywhere this could land"
    )
    assert got["out"]["said"] == "→ out of Verify the aroma transport port"
    assert got["after"] is True, "and the label goes when the move does"
    assert "#into {" in page and "position: fixed" in page
    assert "table.moving tr.over > td {\n  background: var(--drop);" in page, (
        "the would-be parent's row is the green one"
    )


# --------------------------------------------------------------------------- #
# 10. A plan is a tree, and the table draws one
#
# A project holds pitches, a pitch holds tasks, and a task can hang straight off
# a project. The table drew that as a flat list sorted by id — the tree's own
# order with the shape rubbed off it — so the one view that shows every field of
# every record was the one view that did not show how they are arranged.
#
# Three decisions, and each is narrower than it looks:
#
# * **Depth first, and only in the id sort.** A tree ordered by owner is not a
#   tree: the parent is wherever its owner's name falls and its children are
#   three screens away. Every other column sorts flat, and draws no connectors,
#   because there is nothing there for a connector to be true about.
# * **Filtering keeps the whole tree.** A record that would be filtered out but
#   holds something that matched stays, dimmed — a filtered table is still a plan
#   and not a list of orphans — and it must not be counted, because the count is
#   of answers.
# * **The connectors are computed from what is drawn.** A sibling the filter
#   removed would otherwise leave a `└─` lying about which row ends the branch.
# --------------------------------------------------------------------------- #


# Two projects, so that depth-first order and id order are not the same list:
# flat, `pitch-b10000` sorts above every project, and in the tree it is the last
# thing on the table. `task-c90000` hangs straight off its project, which is the
# depth the map allows and the corpus in `test_web` has no example of.
#
# The owners are the filter this corpus exists to be filtered by: under
# `owner=ann` the pitch survives only as context, one project survives only as
# context, one pitch goes entirely, and the last task drawn under the pitch is
# NOT the last one in the plan — which is the only arrangement that can tell a
# connector computed from the rows apart from one computed from the records.
TREE = [
    Project(id="proj-a10000", kind="project", title="Porting the bed", owner="ann"),
    Pitch(id="pitch-b90000", kind="pitch", title="Aroma transport", parent="proj-a10000",
          owner="bo", person_weeks=3),
    Task(id="task-c10000", kind="task", title="Blend weights", parent="pitch-b90000", owner="ann"),
    Task(id="task-c20000", kind="task", title="Tap-point reference", parent="pitch-b90000",
         owner="ann"),
    Task(id="task-c30000", kind="task", title="Seam artefact", parent="pitch-b90000",
         owner="bo"),
    Project(id="proj-a90000", kind="project", title="Distributed driver", owner="bo"),
    Pitch(id="pitch-b10000", kind="pitch", title="Halo exchange", parent="proj-a90000",
          owner="bo", person_weeks=2),
    Task(id="task-c90000", kind="task", title="One rank", parent="proj-a90000", owner="ann"),
]

# What each row of the table is: its id, how deep it is drawn, whether it is
# there only as context, and the connector it draws at each level. Read off the
# drawn rows and never off the payload, because every claim in this section is
# about the drawing.
DRAWN = """
  const rungs = tr => [...tr.querySelectorAll('.rung')]
    .map(one => one.className.split(' ').filter(w => w !== 'rung').join(''));
  const drawn = () => [...tbody.querySelectorAll('tr[data-id]')].map(tr => ({
    id: tr.dataset.id,
    depth: ['d1', 'd2', 'd3'].findIndex(one => tr.classList.contains(one)) + 1,
    context: tr.classList.contains('context'),
    rungs: rungs(tr),
  }));
"""


@pytest.fixture
def tree_page() -> str:
    """The table over `TREE`, editable, rendered by the real renderer."""
    return render_table(build_index(TREE, Config(), date(2026, 8, 17)), base_commit="deadbee")


def test_the_id_sort_draws_the_plan_depth_first(tree_page: str):
    """Roots in id order, children in id order under each root.

    Not a second ordering on top of that one: a childless project sits exactly
    where its id puts it, rather than being grouped after the projects that have
    children. One rule, and it is the rule the ids were already sorted by.

    The corpus is arranged so that this cannot pass by accident — flat, the two
    pitches sort above both projects and every task below them, which is not this
    list in any order.
    """
    answer = drive_table(tree_page, "(() => {" + DRAWN + "  return drawn();})()")
    rows = answer["value"]

    assert [one["id"] for one in rows] == [
        "proj-a10000",
        "pitch-b90000",
        "task-c10000",
        "task-c20000",
        "task-c30000",
        "proj-a90000",
        "pitch-b10000",
        "task-c90000",
    ]
    assert [one["depth"] for one in rows] == [0, 1, 2, 2, 2, 0, 1, 1], (
        "a task hanging off a project is one level in, not two"
    )
    assert sorted(one["id"] for one in rows) != [one["id"] for one in rows], (
        "which is not the flat order, or this test proves nothing"
    )


def test_every_other_column_sorts_flat(tree_page: str):
    """A tree ordered by owner is not a tree.

    The parent is wherever its owner's name falls and its children are three
    screens away, so an indent would point at the row above it and mean nothing,
    and a connector between two unrelated rows is a claim about the plan that is
    simply false. Those columns sort the way they always did, and they keep no
    ancestors for a context they cannot provide.
    """
    answer = drive_table(
        tree_page,
        "(() => {" + DRAWN + "  params.set('sort', 'owner'); draw(); return drawn();})()",
    )
    rows = answer["value"]

    assert {one["depth"] for one in rows} == {0}, "nothing is indented"
    assert not any(one["rungs"] for one in rows), "and nothing draws a connector"
    assert len(rows) == len(TREE), "every row is there, in one flat list"


def test_a_filtered_table_keeps_the_tree_and_counts_only_the_answers(tree_page: str):
    """An ancestor of a match stays, dimmed, and is not counted.

    Filtering to `owner=ann` and getting three tasks with no pitch over them is a
    list of tasks, not a plan: the row that says which pitch they are part of is
    the one a person is about to want. It stays a record while it is there — it
    opens, it edits, a drop lands on it — it simply is not an answer to what was
    asked, which is what the dimming says and what the count has to agree with.

    "4 of 8 shown" over six rows, and both numbers are right: the first is how
    many matched, and it is the number the sentence promises.
    """
    answer = drive_table(
        tree_page,
        "(() => {" + DRAWN + "  params.set('owner', 'ann'); draw();"
        "  return {rows: drawn(),"
        "          shown: document.getElementById('shown').textContent,"
        "          total: document.getElementById('total').textContent};})()",
    )
    got = answer["value"]
    rows = got["rows"]

    assert [one["id"] for one in rows] == [
        "proj-a10000",
        "pitch-b90000",
        "task-c10000",
        "task-c20000",
        "proj-a90000",
        "task-c90000",
    ], "the matches, and every ancestor that holds one"
    assert [one["id"] for one in rows if one["context"]] == ["pitch-b90000", "proj-a90000"], (
        "the two that are there for what is under them"
    )
    assert "pitch-b10000" not in [one["id"] for one in rows], (
        "a pitch that neither matched nor holds a match is gone"
    )
    assert [str(got["shown"]), str(got["total"])] == ["4", "8"], (
        "the count is of answers, and a row kept as context is not one"
    )
    assert "tr.context > td { background: var(--surface-2); color: var(--muted); }" in tree_page


def test_the_connector_that_ends_a_branch_is_the_last_row_drawn(tree_page: str):
    """Not the last record, which is a different row the moment anything is filtered.

    In the plan, `task-c30000` is the last task under the pitch. Under
    `owner=ann` it is filtered out, and the row that ends the branch on screen is
    `task-c20000` — so `task-c20000` draws the `└` and `task-c10000` keeps its
    `├`. Computed from the records instead, `task-c20000` would draw a `├`
    promising a sibling under a row that ends the branch, and the drawing would
    be describing a table nobody is looking at.

    The connectors are class names on empty spans and the shapes are borders. Box
    drawing characters line up only in a monospace face — this column is
    proportional — and a screen reader announces "box drawings light up and
    right" before every child's title, which is why the wrapper is `aria-hidden`.
    """
    answer = drive_table(
        tree_page,
        "(() => {" + DRAWN + "  const whole = drawn();"
        "  params.set('owner', 'ann'); draw();"
        "  return {whole, filtered: drawn(),"
        "          hidden: tbody.querySelector('.tree').getAttribute('aria-hidden')};})()",
    )
    got = answer["value"]
    whole = {one["id"]: one["rungs"] for one in got["whole"]}
    filtered = {one["id"]: one["rungs"] for one in got["filtered"]}

    assert whole["proj-a10000"] == [], "a root has no connector to draw"
    assert whole["pitch-b90000"] == ["end"], "the only pitch its project holds"
    assert whole["task-c10000"] == ["blank", "tee"]
    assert whole["task-c30000"] == ["blank", "end"], "the last task, unfiltered"
    assert whole["pitch-b10000"] == ["tee"] and whole["task-c90000"] == ["end"]

    assert filtered["task-c10000"] == ["blank", "tee"], "still a sibling to come"
    assert filtered["task-c20000"] == ["blank", "end"], (
        "and the row that ends the branch on screen is the one that says so"
    )
    assert got["hidden"] == "true", "there is nothing here to read out"
    # The markup the script actually wrote, and not the page: the stylesheet's
    # own comment says which glyphs these rungs stand for, in prose, which is
    # where a box-drawing character is a fine thing to be.
    drawn = "".join(answer["written"])
    assert "class=\"rung " in drawn, "or the next line is asserting about nothing"
    assert not set(drawn) & set("├└│─"), "drawn as borders, never typed"


def test_the_indent_never_takes_the_drop_target_with_it(tree_page: str):
    """Small, capped, and paid for out of the cell's padding.

    `PARENT_KINDS` bounds the real depth at two, so three is a cap on a
    hand-edited file rather than a design for four levels — a row deeper than
    that is drawn at that depth, because the indent is a hint about where a row
    sits and it is not worth the title column's width to be exact about a shape
    the validator is already complaining about.

    The drawing is taken out of flow and the indent is padding on the cell, which
    is what keeps the row's own box the whole width of the table: a drop lands on
    the row, and a target that shrinks as it goes deeper into the tree would make
    the rows that are hardest to reach the hardest to hit.
    """
    assert "const TREE_DEPTH = 3;" in script(tree_page)
    assert "tr.d3 > td[data-col=\"title\"] { padding-left: calc(.5rem + 42px); }" in tree_page
    assert "tr.d4" not in tree_page, "capped, and the cap is drawn as well as computed"
    assert ".tree { position: absolute;" in tree_page, "so it costs the words nothing"

    answer = drive_table(
        tree_page,
        "(() => {" + DRAWN + "  return {"
        "    cells: [...tbody.querySelectorAll('tr[data-id]')]"
        "      .map(tr => tr.querySelectorAll('td').length),"
        "    tree: [...tbody.querySelectorAll('tr[data-id]')]"
        "      .map(tr => (tr.querySelector('td[data-col=\\'title\\'] .tree') ? 1 : 0)),"
        "  };})()",
    )
    got = answer["value"]

    assert len(set(got["cells"])) == 1, "every row is the same number of cells deep or shallow"
    assert got["tree"] == [0, 1, 1, 1, 1, 0, 1, 1], "and the drawing is in the title column"


def test_a_row_kept_for_context_is_still_a_record(tree_page: str):
    """Dimmed is not disabled.

    It is a row of the plan that is on screen: its title opens it, its cells
    still edit, and a drop still lands on it — which is the whole reason the
    ancestor is worth keeping, since filing something under the pitch you can now
    see is exactly what a person does next.
    """
    answer = drive_table(
        tree_page,
        "(() => {  params.set('owner', 'ann'); draw();"
        "  const pitch = tbody.querySelector('tr[data-id=\"pitch-b90000\"]');"
        "  startMoving('task-c90000');"
        "  return {editable: !!pitch.querySelector('td[data-col=\"status\"].edit'),"
        "          opens: !!pitch.querySelector('td[data-col=\"title\"] a'),"
        "          holds: pitch.classList.contains('can-hold'),"
        "          refused: refuses('task-c90000', 'pitch-b90000')};})()",
    )
    got = answer["value"]

    assert got["editable"] is True and got["opens"] is True
    assert got["refused"] == "" and got["holds"] is True, "and a task may still be filed under it"


@pytest.mark.parametrize("route", ["/", "/graph", "/timeline", "/cycles", "/people", "/new"])
def test_no_template_comment_reaches_the_page(client: TestClient, route: str):
    """A Jinja comment ends at the first `#` `}`, including one inside the prose.

    Found by writing one: a comment explaining why the two delimiters around it
    were the whitespace-preserving spelling quoted the other spelling, ended
    there, and printed the rest of itself into the bar between the blocker count
    and the row count. The comments in this file are long and full of quoted
    source, so this is a mistake that will be made again — and it is invisible in
    a diff and obvious on the page.
    """
    served = client.get(route).text

    assert served.count("{#") == 0, "a comment that reached the page never opened one"
    assert "#}" not in served, f"a template comment leaked into {route}"

# The draft row's controls, in the browser that has to draw them. The row does
# not exist in the rendered file — it is built by the page's own script when the
# kind is chosen — and neither of its two controls contains a character, so the
# only question worth asking about them is how big the drawing inside each one
# came out.
_DRAFT_MARKS = """
document.getElementById('add-row').click();
const picker = document.getElementById('draft-kind');
picker.value = 'project';
picker.dispatchEvent(new Event('change', {bubbles: true}));
const box = node => {
  const r = node.getBoundingClientRect();
  return {w: Math.round(r.width), h: Math.round(r.height),
          top: Math.round(r.top), right: Math.round(r.right)};
};
const cell = tbody.querySelector('tr.draft td.draft-id');
const rows = [...tbody.querySelectorAll('tr:not(.draft):not(.adder)')];
// What the picker would need to draw the kind it is showing, which is not what
// it would need to draw the whole list: a `<select>` is as wide as its widest
// option, and the one that decides that — `choose a kind…` — is only ever read
// in the bar. So the probe holds the chosen option and nothing else.
const picked = cell.querySelector('select');
const probe = picked.cloneNode(false);
probe.removeAttribute('id');
probe.appendChild(picked.selectedOptions[0].cloneNode(true));
probe.style.cssText =
  'position:absolute;visibility:hidden;width:auto;min-width:auto;flex:none';
picked.parentNode.appendChild(probe);
const needed = Math.ceil(probe.getBoundingClientRect().width);
probe.remove();
return {
  cell: box(cell),
  marks: [...cell.querySelectorAll('button.draft-do')].map(button => ({
    id: button.id,
    button: box(button),
    drawing: box(button.querySelector('svg')),
  })),
  picker: box(picked),
  pickerNeeds: needed,
  draftHeight: Math.round(
    tbody.querySelector('tr.draft').getBoundingClientRect().height),
  shortestRow: Math.min(...rows.map(
    row => Math.round(row.getBoundingClientRect().height))),
};
"""


def test_the_draft_rows_marks_are_drawn(demo_root: Path, tmp_path: Path):
    """Both controls on the row nobody has created yet, measured in Chrome.

    They shipped as two empty boxes. `_ICON_SVG` carries a `viewBox` and no
    `width` or `height`, every earlier use of one sat in a box that sized it, and
    an SVG that nothing sizes lays out at 0x0 — so the check and the cross the
    row is created and abandoned with were nothing at all, under a suite that
    was green because it only ever asked whether the markup was emitted.

    A resolved value would not have settled it either way round: there was no
    rule to resolve. The question is how many pixels the drawing came out, and
    this is where that answer lives.
    """
    # The demo corpus and not the four-record one, because the id column is as
    # wide as the fit made it and the fit was measured against this plan: on
    # seventeen rows the column is 121px, which is the width the picker has to
    # say `Project` in.
    records, config, _ = load_repo(demo_root)
    page = render_table(
        build_index(records, config, date(2026, 8, 17)), base_commit="deadbee"
    )
    got = measured_in(chrome(), page, tmp_path / "draft.html", 1460, _DRAFT_MARKS)

    assert [mark["id"] for mark in got["marks"]] == ["draft-create", "draft-cancel"]
    for mark in got["marks"]:
        assert mark["drawing"]["w"] >= 8 and mark["drawing"]["h"] >= 8, (
            f"{mark['id']} is drawn {mark['drawing']['w']}x{mark['drawing']['h']}, "
            f"which is a button with nothing in it"
        )
        assert mark["button"]["w"] >= mark["drawing"]["w"], (
            f"{mark['id']}'s drawing is wider than the button around it"
        )

    # One line, and the row the same height as an ordinary one: the marks are
    # marks rather than the words `Create` and `Cancel` precisely so that the
    # three of them and the id column fit each other.
    tops = {mark["button"]["top"] for mark in got["marks"]} | {got["picker"]["top"]}
    assert max(tops) - min(tops) <= 4, (
        f"the draft row's controls stand on more than one line: {sorted(tops)}"
    )
    assert got["draftHeight"] <= got["shortestRow"] + 2, (
        f"the draft row is {got['draftHeight']}px against {got['shortestRow']}px "
        f"for an ordinary row, so it reads as a different kind of thing"
    )
    # And the picker gave way rather than the cell: a flex item's `min-width` is
    # `auto`, which is how the longest thing in the list decided the width of the
    # narrowest column on the table.
    assert got["picker"]["right"] <= got["cell"]["right"], (
        "the kind picker reaches past the right edge of the id cell"
    )
    # Shrinking is not the same as cutting. The cell says what the row is about
    # to be, and a picker squeezed to `Projec` says it slightly wrong.
    assert got["picker"]["w"] + 1 >= got["pickerNeeds"], (
        f"the picker is {got['picker']['w']}px where the kind it is showing "
        f"needs {got['pickerNeeds']}px, so the word is cut"
    )


# --------------------------------------------------------------------------- #
# Reviewers a row did not name itself
# --------------------------------------------------------------------------- #


_INHERITED = """
const rows = [...tbody.querySelectorAll('tr[data-id]')];
const found = rows.map(row => {
  const cell = row.querySelector('td[data-col="reviewers"]');
  return {
    id: row.dataset.id,
    own: (DATA.rows[row.dataset.id].reviewers || []).length,
    from: (DATA.rows[row.dataset.id].reviewers_from || []).length,
    text: cell.textContent.trim(),
    inherited: cell.classList.contains('inherited'),
    ground: getComputedStyle(cell).backgroundColor,
  };
});
return {
  borrowing: found.filter(one => !one.own && one.from),
  owning: found.filter(one => one.own),
};
"""


def test_a_row_that_names_no_reviewer_shows_the_ones_under_it(tmp_path: Path):
    """A pitch whose tasks are reviewed is reviewed — the validator stopped asking
    it for a reviewer of its own, so the column stopped being empty for a reason
    nothing on the page could see.

    The ground says the value came from underneath rather than from this record's
    file, which is the difference between "these are the reviewers" and "these are
    the reviewers, and changing them means changing the tasks".
    """
    # A corpus of three, hand-built: every pitch in `seed/` names its own
    # reviewers, which is what a plan somebody has been keeping looks like — and
    # the whole question here is about one that does not.
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Held up by its tasks",
              status="ready", owner="ann", reviewers=[], person_weeks=4,
              shaped_by=["ann"], assigned_on=date(2026, 8, 10)),
        Task(id="task-000001", kind="task", title="One", parent="pitch-000001",
             status="ready", owner="ann", reviewers=["bo"], person_weeks=2,
             assigned_on=date(2026, 8, 10)),
        Task(id="task-000002", kind="task", title="Two", parent="pitch-000001",
             status="ready", owner="bo", reviewers=["cy"], person_weeks=2,
             assigned_on=date(2026, 8, 10)),
    ]
    page = render_table(build_index(records, Config(), date(2026, 8, 17)))
    got = measured_in(chrome(), page, tmp_path / "inherited.html", 1460, _INHERITED)

    assert got["borrowing"], "no row in this corpus takes its reviewers from below"
    for row in got["borrowing"]:
        assert row["text"], f"{row['id']} shows nothing where it has {row['from']} below it"
        assert row["inherited"], f"{row['id']} does not say the names are not its own"
        assert row["ground"] not in ("rgba(0, 0, 0, 0)", "transparent"), row["id"]

    # And a row with its own reviewers is drawn the way it always was.
    for row in got["owning"]:
        assert not row["inherited"], f"{row['id']} names its own and is drawn as borrowing"


_DROP_ON_A_DEAD_CONNECTION = r"""
const loose = [];
addEventListener('unhandledrejection', event => {
  loose.push(String(event.reason));
  event.preventDefault();
});
let paired = 0;
addEventListener('openproj:writing', () => { paired++; });
addEventListener('openproj:wrote', () => { paired--; });
const region = document.getElementById('state');
region.textContent = '';
window.fetch = async () => { throw new TypeError('Failed to fetch'); };
let threw = null;
try { await reparent(CHILD, PARENT); } catch (error) { threw = String(error); }
await new Promise(go => setTimeout(go, 120));
const row = tbody.querySelector(`tr[data-id="${CHILD}"]`);
return {
  loose, threw, paired,
  said: region.textContent,
  // The row stopped waiting, which the `finally` has always done, and it is
  // still drawn where it started, because nothing re-read the plan.
  waiting: WRITING,
  dimmed: row ? row.classList.contains('writing') : null,
  parent: (DATA.rows[CHILD] || {}).parent || null,
};
"""


def test_a_drop_on_a_dead_connection_takes_its_own_sentence_back_down(
    page: str, tmp_path: Path
):
    """`reparent` announces `moving task-3 into project-a…` before the request and
    takes it back only when an answer arrives — and it was `try`/`finally` with no
    `catch`.

    A rejection runs the `finally` and carries on unwinding. So the row undimmed,
    the paired `openproj:wrote` fired, and the live region went on saying the move
    was happening, for ever, over a row still drawn where it started. `e82ce55`
    fixed this exact shape on the editing surface and said in its message that the
    uploader and Save were the only two sites with a sentence left behind them;
    this is a third, on a gesture that is one drag rather than a paste some people
    never make.

    The sentence does not guess. A fetch rejects when the answer is lost as
    readily as when the request never left, so it says what to do — drag it again,
    and the compare-and-swap refuses the second one with the conflict report if
    the first one landed.
    """
    got = measured_in(
        chrome(), page, tmp_path / "drop-dropped.html", 1460,
        _DROP_ON_A_DEAD_CONNECTION.replace("CHILD", json.dumps(TASK))
        .replace("PARENT", json.dumps(PROJECT)),
        patience=4800,
    )

    assert got["loose"] == [], f"the rejection still escapes: {got['loose']}"
    assert got["threw"] is None, f"and it reaches the gesture that called it: {got['threw']}"
    assert got["paired"] == 0, (
        "an `openproj:writing` was left unpaired, which holds every later banner "
        "on this page for ever"
    )
    assert "…" not in got["said"], (
        f"the page is still saying the move is happening: {got['said']!r}"
    )
    assert TASK in got["said"] and "was not moved" in got["said"], got["said"]
    assert "Drag it again" in got["said"], (
        f"and it does not say what to do about it: {got['said']!r}"
    )
    assert got["waiting"] is None and got["dimmed"] is False, (
        "the row is still drawn as though the write were in the air"
    )
    assert got["parent"] == PITCH, (
        f"the row moved on a write that never landed: {got['parent']!r}"
    )


# Drag a column wider, which is what ends the automatic fit, then resize the
# window both ways and see whether the table still fits it. `dispatchEvent` and
# not a real window resize: headless Chrome is one size for the life of the run,
# and what is under test is the handler, not the browser's own reflow.
_REFIT = """
const scroller = document.getElementById('rows').parentElement;
const table = document.getElementById('rows');
const grip = document.querySelector('th .grip') || document.querySelector('th [class*=grip]');
if (!grip) return {error: 'no grip to drag'};

const down = new PointerEvent('pointerdown', {clientX: 400, bubbles: true});
grip.dispatchEvent(down);
dispatchEvent(new PointerEvent('pointermove', {clientX: 700, bubbles: true}));
dispatchEvent(new PointerEvent('pointerup', {clientX: 700, bubbles: true}));

const measure = () => ({
  room: scroller.clientWidth,
  table: Math.round(table.getBoundingClientRect().width),
});
const dragged = measure();

// Narrower, then wider, then back — each time through the handler the window
// resize would call.
scroller.style.width = '700px';
dispatchEvent(new Event('resize'));
const narrow = measure();

scroller.style.width = '1600px';
dispatchEvent(new Event('resize'));
const wide = measure();

return {dragged, narrow, wide, columns: [...table.querySelectorAll('th')].length};
"""


def test_a_dragged_table_still_fits_the_window_it_is_looked_at_in(
    page: str, tmp_path: Path
):
    """Reported by jcanton, 2026-08-20: "the table keeps its width, which means it
    can be smaller than the page when enlarging and (worse) larger than the page
    when reducing the size of the browser".

    Both halves are the same defect. Dragging a column ended the automatic fit for
    good, and every resize after that re-applied the stored pixels — so the table
    stayed the width of whatever window it was dragged in.

    A dragged width is a decision about PROPORTION, not about pixels: it says this
    column deserves twice the room of that one. So it is scaled to the window
    rather than replayed into it, and the columns keep their relative sizes while
    the table keeps fitting the page.
    """
    got = measured_in(chrome(), page, tmp_path / "refit.html", 1460, _REFIT)

    assert not got.get("error"), got
    for name in ("narrow", "wide"):
        room, drawn = got[name]["room"], got[name]["table"]
        # A pixel of slack for the collapsed border the fit measures separately.
        assert drawn <= room + 2, f"{name}: {drawn}px of table hanging out of {room}px"
        assert drawn >= room - 40, f"{name}: {room - drawn}px of empty page beside the table"
    # And nothing was shed to achieve it: a dragged layout keeps its columns.
    assert got["columns"] > 5


def test_a_blocker_that_is_done_is_not_a_blocker(client: TestClient, repo_path: Path):
    """jcanton, 2026-08-20: "make sure the counter gets updated if blocking tasks
    are marked as done".

    The column is headed Blockers and counted every entry in `depends_on`, whether
    or not the thing it named had finished — so a record whose one dependency
    landed last week still read 1, for ever. A count that is wrong in the
    reassuring direction is a count people stop reading.

    `depends_on` itself is untouched. That this waited for that is history worth
    keeping, and it is what the graph draws.
    """
    from test_web import DONE, OTHER, TASK, save

    assert save(client, TASK, {"depends_on": [OTHER, DONE]}).status_code == 200

    def blockers_of(record_id: str) -> int:
        # Off the table's own payload, which is what the column is drawn from —
        # `/api/index.json` is the flat index and answers a different question.
        page = client.get("/table").text
        rows = json.loads(
            re.search(r'<script id="payload" type="application/json">(.*?)</script>', page, re.S)
            .group(1)
        )["rows"]
        return rows[record_id]["blocked_by"]

    # `DONE` is already done, so only the open one counts.
    assert blockers_of(TASK) == 1, "a finished dependency is still being counted"

    assert save(client, OTHER, {"status": "done"}).status_code == 200
    assert blockers_of(TASK) == 0, "the count did not move when the blocker finished"

    # And shelved work stops counting too: parked is not something anybody is
    # waiting on either.
    assert save(client, OTHER, {"status": "ready"}).status_code == 200
    assert blockers_of(TASK) == 1
    assert save(client, OTHER, {"status": "shelved"}).status_code == 200
    assert blockers_of(TASK) == 0


def test_only_a_cell_with_something_in_the_way_is_tinted(page: str):
    """A column tinted on every row says nothing. The tint is written beside the
    number by the same function, so it cannot outlive the count it is about."""
    assert "key === 'blocked_by' && row.blocked_by > 0 ? 'waiting' : ''" in page
    assert 'td[data-col="blocked_by"].waiting { background: var(--waiting); }' in page
    # Its own colour, and not the one a validation blocker wears. Those are two
    # different facts, and one tint for both teaches a reader that the plan is
    # broken whenever somebody is waiting for a colleague.
    assert "--waiting:" in page
    assert re.search(r"--waiting: (#[0-9a-f]{6})", page).group(1) != re.search(
        r"--sev-blocker-soft: (#[0-9a-f]{6})", page
    ).group(1)


# Drag a column, then squeeze the window hard, which is how jcanton hit this: the
# automatic fit protects these columns, and a dragged layout is scaled to whatever
# window it is looked at in and can go below what a chip needs.
_TIGHT = """
const table = document.getElementById('rows');
const scroller = table.parentElement;
// Before anything is dragged or squeezed: a window with room in it, where both
// columns are meant to read as a mark AND a word.
const untouched = {
  priwords: [...document.querySelectorAll('td[data-col="priority"] .chipword')]
    .filter(one => one.offsetParent !== null).length,
  words: [...document.querySelectorAll('td[data-col="status"] .chipword')]
    .filter(one => one.offsetParent !== null).length,
};
const grip = document.querySelector('th .grip') || document.querySelector('th [class*=grip]');
if (!grip) return {error: 'no grip to drag'};
grip.dispatchEvent(new PointerEvent('pointerdown', {clientX: 400, bubbles: true}));
dispatchEvent(new PointerEvent('pointermove', {clientX: 760, bubbles: true}));
dispatchEvent(new PointerEvent('pointerup', {clientX: 760, bubbles: true}));

const spilling = () => {
  const out = [];
  for (const key of ['status', 'priority'])
    for (const cell of document.querySelectorAll(`td[data-col="${key}"]`)) {
      const box = cell.getBoundingClientRect();
      for (const inner of cell.children) {
        const edge = inner.getBoundingClientRect().right;
        if (edge > box.right + 1) out.push(`${key} ${Math.round(edge - box.right)}px past`);
      }
    }
  return out;
};
const marks = () => [...document.querySelectorAll('td[data-col="status"] .chipmark')]
  .filter(one => one.offsetParent !== null).length;
const words = () => [...document.querySelectorAll('td[data-col="status"] .chipword')]
  .filter(one => one.offsetParent !== null).length;
// A wrapped cell does not spill sideways, it grows downwards — so the shape of
// this defect is a height, not an overhang. Reported as the tallest priority
// cell against the tallest status cell, which is the same chip at the same font
// and is therefore the height one line of chip is.
const stacking = () => {
  // The MARK's own box, not the cell's: a row is as tall as its tallest cell,
  // and on this corpus that is a list of tags several lines high — so asking the
  // cell measured the row and reported the two columns identical however either
  // of them was drawn.
  const tall = key => Math.max(...[...document.querySelectorAll(`td[data-col="${key}"] > span`)]
    .map(one => one.getBoundingClientRect().height), 0);
  return {priority: Math.round(tall('priority')), status: Math.round(tall('status'))};
};
const priwords = () => [...document.querySelectorAll('td[data-col="priority"] .chipword')]
  .filter(one => one.offsetParent !== null).length;
const pribars = () => [...document.querySelectorAll('td[data-col="priority"] .chipmark')]
  .filter(one => one.offsetParent !== null).length;

scroller.style.width = '620px';
dispatchEvent(new Event('resize'));
const tight = {spilling: spilling(), marks: marks(), words: words(),
               stacking: stacking(), priwords: priwords(), pribars: pribars()};

scroller.style.width = '1800px';
dispatchEvent(new Event('resize'));
const roomy = {spilling: spilling(), marks: marks(), priwords: priwords()};

return {untouched, tight, roomy};
"""


def test_a_column_too_narrow_for_its_word_keeps_its_mark(page: str, tmp_path: Path):
    """jcanton, 2026-08-20, with a screenshot of a narrowed window: the status chip
    ran straight through the Owner column — `» IN PROGRESSjcanton`.

    `.chip` is `white-space: nowrap`, which is right: "IN PROGRESS" broken over
    two lines is not a chip. What was missing is anywhere for the overflow to go —
    `status` is in neither `CLAMPED` nor `SQUEEZABLE`, so the fit hands it a width
    and nothing clips what does not fit. Priority was in neither either, and got
    away with it only because plain text wraps, which is the `Medi um` in the same
    screenshot.

    The decision was to drop to the mark rather than clip with an ellipsis:
    `IN PROG…` teaches nothing, while `»` and the five bars are already taught by
    the graph's legend, and the timeline already drops its own glyph below
    `_GLYPH_MIN_PX`. A narrow column falls back to a notation the reader has been
    shown rather than to a word cut in half.
    """
    got = measured_in(chrome(), page, tmp_path / "tight.html", 1900, _TIGHT)

    assert not got.get("error"), got
    assert got["tight"]["spilling"] == [], got["tight"]["spilling"][:4]
    assert got["tight"]["words"] == 0, "the word stayed and is what was spilling"
    assert got["tight"]["marks"] > 0, (
        "the mark went with the word, so a squeezed column now says nothing at all"
    )
    # And the words come back. Otherwise the first narrow window a reader ever
    # opens costs them the words for good.
    assert got["roomy"]["marks"] > 0
    assert got["roomy"]["spilling"] == [], got["roomy"]["spilling"][:4]

    # Priority, which was the same defect wearing the other failure mode: its
    # word wrapped instead of overflowing, so the cell never reported itself over
    # and the column tightened only once "Medium" had become six lines of one
    # letter. jcanton, 2026-08-20, with a screenshot of a `M e d i u m` column
    # beside a status chip that had already dropped to its glyph.
    #
    # Measured as a height and not as an overhang, because a wrapped cell does
    # not hang out of anything. One line of chip is what the status column is at
    # the same width, and the two are the same chip at the same font.
    tall = got["tight"]["stacking"]
    assert tall["priority"] <= tall["status"] + 2, (
        f"the priority column is {tall['priority']}px tall against status at "
        f"{tall['status']}px, so its word is still stacking a letter at a time"
    )
    assert got["tight"]["priwords"] == 0 and got["tight"]["pribars"] > 0, (
        "a narrow priority column should read as its mark alone, the way status "
        f"reads as its glyph alone: {got['tight']}"
    )
    # Both words are there before anything is dragged. Not after: this probe
    # drags 360px into the id column and the fit honours it, so the two columns
    # are legitimately still narrow in a window twice the width — which is the
    # whole point of dropping to the mark rather than clipping.
    assert got["untouched"]["priwords"] > 0 and got["untouched"]["words"] > 0, (
        f"a table with room in it is not showing its words: {got['untouched']}"
    )


# --------------------------------------------------------------------------- #
# The press that creates a row: that it lands, and that it lands once.
# --------------------------------------------------------------------------- #


def test_a_second_press_while_the_create_is_in_flight_makes_no_second_record(page: str):
    """One press, one record, however many times the check is pressed.

    A create is a commit and a push to GitHub, which from Cloud Run is 1.5 to 2
    seconds, and for all of it the row used to sit there looking exactly as it
    had before the press — `openproj:writing` is *counted* by the shell to hold
    its banner back and draws nothing. So somebody pressed again, and the second
    press posted a second record: two 201s 0.9 seconds apart in the deployed
    service's log on 2026-08-24, two rows, one of them deleted by hand a minute
    later.

    Pressed through the delegated listener rather than by calling `createDraft`
    twice, because the guard has to hold for the gesture and not only for the
    function. What this cannot prove is the other half — that the check is drawn
    `disabled` and a mouse therefore cannot reach it at all — because this shim
    has no notion of a disabled control; that half is asked of Chrome below.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('task');"
        "  stage('title', 'Pressed twice in a hurry');"
        "  const press = () => {"
        "    const event = new Event('click');"
        "    event.target = tbody.querySelector('#draft-create');"
        "    tbody.dispatchEvent(event);"
        "  };"
        "  press();"
        "  const held = CREATING;"
        "  press();"
        f" {SETTLE}"
        "  return {held, after: CREATING, draft: DRAFT};"
        "})()",
        replies=[
            {"status": 201, "json": {"id": "task-a1b2c3", "outcome": "committed",
                                     "commit": "c0ffee"}},
            {"status": 200, "json": {"rows": {}, "problems": []}},
        ],
    )
    posts = [call for call in answer["calls"] if call["method"] == "POST"]

    assert len(posts) == 1, (
        f"the check was pressed twice and posted {len(posts)} records: {posts}"
    )
    assert answer["value"]["held"] is True, "the row does not say it is working"
    assert answer["value"]["after"] is False, "the flag outlived its own request"
    assert answer["value"]["draft"] is None, "the row that was typed is a record now"


def test_a_refused_create_gives_the_check_back(page: str):
    """A guard that never releases is worse than the double press it prevents.

    This is the cycle page's defect through a different door: a 500 there left
    Save disabled for ever, and a row whose check never comes back cannot be
    corrected and retried — the typing is only in the page, so the way out is a
    reload that throws it away. So `createDraft` clears the flag in a `finally`
    and redraws after it, on every way out including the ones that threw.
    """
    answer = drive_table(
        page,
        "(async () => {"
        "  openDraft(); chooseKind('task'); stage('title', 'Refused once');"
        f" await createDraft(); {SETTLE}"
        "  return {creating: CREATING,"
        "          disabled: tbody.querySelector('#draft-create').hasAttribute('disabled'),"
        "          title: DRAFT && DRAFT.fields.title,"
        "          said: [...document.getElementById('draft-problems').children]"
        "                  .map(item => item.textContent)};"
        "})()",
        replies=[{"status": 422, "json": {"problems": [
            {"record_id": "task-a1b2c3", "severity": "blocker",
             "message": "a task needs an owner before it can be ready"},
        ]}}],
    )

    assert answer["value"]["creating"] is False, "the flag survived a refusal"
    assert answer["value"]["disabled"] is False, "the check never came back"
    assert answer["value"]["title"] == "Refused once", "the typing was thrown away"
    assert answer["value"]["said"] == ["a task needs an owner before it can be ready"], (
        "and the refusal is still on screen after the redraw that gave the check back"
    )


# The page, put where the press has to find it: a draft row with a kind chosen,
# a title half-typed, and the editor for it STILL OPEN — which is the state the
# defect needs and the state a person is actually in when they reach for the
# check. `fetch` is replaced before anything is pressed, so the create answers
# without a server; the recorded calls are the evidence.
_PRESS_SETUP = """
window.__sent = [];
window.fetch = (url, options) => {
  const asked = String(url);
  window.__sent.push({url: asked, method: (options || {}).method || 'GET',
                      body: (options || {}).body || ''});
  const table = asked.endsWith('/api/table.json');
  return Promise.resolve(new Response(
    JSON.stringify(table ? {rows: {}, problems: []}
                         : {id: 'task-a1b2c3', outcome: 'committed', commit: 'c0ffee'}),
    {status: table ? 200 : 201, headers: {'content-type': 'application/json'}}));
};
openDraft();
chooseKind('task');
tbody.querySelector('tr.draft td[data-field="title"] input').value = 'Typed, then pressed';
tbody.querySelector('tr.adder').scrollIntoView({block: 'center'});
'ready'
"""

_PRESS_AT = """
(() => {
  const box = document.getElementById('draft-create').getBoundingClientRect();
  return [box.x + box.width / 2, box.y + box.height / 2];
})()
"""

_PRESS_OUTCOME = """
({
  posts: window.__sent.filter(one => one.method === 'POST').map(one => one.url),
  title: (window.__sent.filter(one => one.method === 'POST')[0] || {}).body || '',
  draft: DRAFT === null,
})
"""


def test_the_check_creates_the_row_on_one_press_with_the_editor_still_open(
    page: str, tmp_path: Path
):
    """**The press that did nothing.** Pressed with the title editor open, the
    check created no row, said nothing, and left the draft exactly as it was.

    The mechanism is not in this page's logic at all, which is why every cheaper
    harness passes with the defect in place. `mousedown` on a button moves the
    focus to it; that blurs the open cell editor; this page's blur handler stages
    the value and redraws, and `draw()` replaces the whole `tbody` through
    `innerHTML`. So the button that took the `mousedown` is detached before the
    `mouseup`, the two land on elements with no common ancestor left in the
    document, and the browser therefore synthesises **no click at all**. The
    delegated listener never runs. Nothing failed, so nothing was reported: from
    the outside the check is simply dead until you press it a second time.

    `drive.js` cannot see this — it has no focus model, no bubbling, and no click
    synthesis, so a press lands there by construction. Neither can a script
    inside the page: `element.click()` and a dispatched `MouseEvent` are
    `isTrusted: false`, run no default action, move no focus, and are dispatched
    rather than synthesised, so they answer a question nobody asked. The only
    harness that can is a real browser sent real input, which is what
    `pressed_in` is.

    The title matters as much as the row: holding the focus is what keeps the
    press, and the check has to take what is in the open box with it, or the fix
    would trade a lost press for a lost field.
    """
    where = tmp_path / "press.html"
    where.write_text(page)
    got, said = pressed_in(
        chrome(), where.as_uri(), tmp_path / "profile",
        setup=_PRESS_SETUP, at=_PRESS_AT, then=_PRESS_OUTCOME,
    )

    assert got["posts"] == ["/api/record"], (
        f"one press of the check sent {got['posts']}; the console said {said}"
    )
    assert "Typed, then pressed" in got["title"], (
        "the press landed but left behind what was still in the open editor"
    )
    assert got["draft"], "the row was created and the draft is gone"
