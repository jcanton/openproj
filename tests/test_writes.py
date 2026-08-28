"""What the pages do when a write does not land.

Every defect here sat under a green suite because the happy path is the only one
anything drove: a save that works is one `fetch` away from a save that comes back
409, 422 or 500, and the three answers were handled by code nobody had ever run.
A conflict report printed as "refused". A blank date box raised a 500, whose
plain-text body then rejected `response.json()` and left Save disabled with the
bar still claiming unsaved changes. A typo in an availability box took somebody
out of the cycle with their capacity and said nothing.

So the assertions below are not about the source of these scripts. The page is
rendered by the real server, its own scripts are run by `tests/js/drive.js`
against the page's own markup, and `fetch` is handed the answers a server really
gives — including a 500 that is not JSON. What is asserted is what a person
would see afterwards: the words in the live region, whether Save came back, the
banner beside the row, and what was actually sent.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from pages import render_paths, render_source
from test_injection import run_js
from test_store import commit_directly
from test_web import (
    ANN,
    DONE,
    DONE_TITLE,
    OTHER,
    OTHER_TITLE,
    PATH,
    PITCH,
    PITCH_TITLE,
    PROJECT,
    PROJECT_TITLE,
    SECRET,
    SEED,
    TASK,
    TASK_TITLE,
)

from openproj.auth import sign_session
from openproj.store import StoreDiverged
from openproj.web import SESSION_COOKIE, _refusal, create_app

# What a 409 carries. `_result` answers with `conflict` and no `detail` at all,
# and this is the sentence three write paths threw away.
REPORT = "cycles/0041.md changed under you\n  starts_on: stored 2026-09-07 · yours 2026-08-17"
CONFLICT = {"outcome": "conflict", "commit": None, "conflict": REPORT, "head": "0" * 40}

# A server fault answers in plain text, so `response.json()` on it rejects. That
# rejection is C1: it took the whole of `flush()` with it.
FAULT = {"status": 500, "text": "Internal Server Error"}


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Every page a member can write from, rendered by the server itself.

    Cycle 41 is set up with two people on the roster and a task bet into it, so
    the roster the scripts read is a real one: `input.rate` has to be somebody's
    availability or the test that refuses `50%` is refusing a box it invented.
    """
    repo = tmp_path_factory.mktemp("writes") / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, SEED, "seed the corpus")
    with TestClient(create_app(repo, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        head = client.get("/healthz").json()["head"]
        bet = client.patch(
            f"/api/record/{TASK}",
            json={"base_commit": head, "fields": {"cycle": 41, "assignees": ["ann"]}, "body": None},
        )
        client.put(
            "/api/cycle/41",
            json={
                "base_commit": bet.json()["commit"],
                "fields": {
                    "starts_on": "2026-08-17",
                    "reviews_on": "2026-09-14",
                    "availability": {"ann": 0.5, "bo": 1.0},
                },
                "body": "## Goal\n\nShip it.\n",
            },
        )
        routes = {
            "cycle": "/cycle/41",
            "table": "/table",
            "detail": f"/detail/{TASK}",
            # The same page with the plain textarea rather than Ace. `drive.js`
            # is a DOM shim and not a browser, and 594 KB of third-party editor
            # is more DOM than it has — so a claim about what SAVE does on this
            # page is asked of the surface the shim can actually run. What is
            # under test is `save()`, which is shared by both editors.
            "detail_plain": f"/detail/{TASK}?editor=plain",
            "graph": "/graph",
            "cycles": "/cycles",
            "new": "/new?kind=task",
            # ann owns a task in this corpus, so she has a row on the People
            # page and the row has her picker on it. A person who holds
            # nothing gets no row and no picker, which is the page's rule
            # and not an accident of this fixture.
            "people": "/people",
            # The two write surfaces that were reading a refusal their own way.
            # The slide editor is a VIEW of the record at the record's own
            # address, and the deck is the rail that saves the slide order; both
            # read `refusal()` now, and both are here so that the sweeps below
            # that say "every page that writes" really mean every one.
            "slide": f"/detail/{TASK}?view=slide",
            "deck": "/deck/41",
        }
        drawn = {}
        for name, route in routes.items():
            answer = client.get(route)
            assert answer.status_code == 200, f"{route}: {answer.status_code}"
            drawn[name] = answer.text
        return drawn


def drive(html: str, expression: str, replies: list[dict] | None = None) -> dict:
    """The page, its own scripts, and the answers a server gives.

    `page` so that `document.querySelectorAll('input.rate')` is the roster the
    server drew rather than an empty list, and the whole answer comes back —
    including `settled`, which is how a write path that hangs reports itself
    instead of just producing nothing.
    """
    answer = run_js(html, expression, page=True, replies=replies or [])
    assert answer["settled"], (
        "the write never settled: something in the chain rejected or hung, which "
        "in a browser is Save disabled for ever with nothing said"
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    return answer


def state(answer: dict) -> str:
    return answer["value"]["state"]


# The words the cycle page says land in `#state`, which is the shell's live
# region on that page; every expression below reports it back.
SAY = "state: document.getElementById('state').textContent"


# --------------------------------------------------------------------------- #
# C1: a refusal the page can survive
# --------------------------------------------------------------------------- #


SAVE_THE_ROSTER = f"""
(async () => {{
  ROSTER_DIRTY = true;
  let threw = null;
  try {{ await flush(false); }} catch (error) {{ threw = String(error); }}
  return {{threw, disabled: SAVE.disabled, unsaved: UNSAVED.textContent, {SAY}}};
}})()
"""


def test_a_server_fault_gives_the_cycle_page_back(pages):
    """A 500 answers in plain text. `response.json()` on it rejects, and the
    rejection went up through `put`, `saveSetup` and `flush` — so Save stayed
    disabled, the bar went on claiming unsaved changes, and nothing was said
    about any of it. The tab was finished, and looked fine."""
    answer = drive(pages["cycle"], SAVE_THE_ROSTER, [FAULT])
    got = answer["value"]

    assert got["threw"] is None, "the refusal came back as an exception nobody catches"
    assert got["disabled"] is False, "Save never came back, so the page cannot be saved again"
    assert got["state"], "a refused save said nothing at all"
    assert got["unsaved"] == "1 unsaved change", "the edit is still there and still unsaved"


def test_the_words_the_server_refused_with_are_the_words_on_the_page(pages):
    """The 422 `_reject_bad_cycle` gives back names the box and the value, which
    is only worth writing if it reaches the person who typed it."""
    detail = "starts_on must be a date like 2026-09-01, not ''"
    answer = drive(pages["cycle"], SAVE_THE_ROSTER, [{"status": 422, "json": {"detail": detail}}])

    assert state(answer) == detail


TYPE_A_WORD_INTO_A_DATE = f"""
(async () => {{
  document.querySelector('#setup [name=reviews_on]').value = 'the 4th';
  ROSTER_DIRTY = true;
  const saved = await flush(false);
  return {{saved, {SAY}}};
}})()
"""


def test_a_word_typed_into_a_date_box_reaches_the_server_as_the_word(pages):
    """`Number('six')` was NaN and `JSON.stringify` sent NaN as null: the typo was
    thrown away on the way out, so the best refusal the server could give was
    about something blank — beside a box with the word still in it.

    The lengths are dates now and the hazard is the same shape, so the boxes still
    send what was typed and the refusal still quotes it."""
    detail = "reviews_on must be a date like 2026-09-01, not 'the 4th'"
    answer = drive(
        pages["cycle"], TYPE_A_WORD_INTO_A_DATE, [{"status": 422, "json": {"detail": detail}}]
    )

    assert json.loads(answer["calls"][0]["body"])["fields"]["reviews_on"] == "the 4th"
    assert state(answer) == detail
    assert answer["value"]["saved"] is False


# --------------------------------------------------------------------------- #
# C2: the one answer that means somebody else moved the plan
# --------------------------------------------------------------------------- #


def test_a_conflict_saving_the_setup_says_what_moved(pages):
    """`_result` has no `detail` on a 409 — it has `conflict`, the report naming
    the file and every field that disagreed — so this printed "refused"."""
    answer = drive(pages["cycle"], SAVE_THE_ROSTER, [{"status": 409, "json": CONFLICT}])

    assert state(answer) != "refused"
    assert REPORT in state(answer)


BET_ON_SOMETHING = f"""
(async () => {{
  const row = document.querySelector('#bets tbody tr');
  pend(row.dataset.id, 'cycle', 41);
  let threw = null;
  try {{ await flush(false); }} catch (error) {{ threw = String(error); }}
  return {{threw, id: row.dataset.id, named: named(row.dataset.id),
           disabled: SAVE.disabled, {SAY}}};
}})()
"""


def test_a_conflict_on_a_bet_says_what_moved(pages):
    """The bets table writes one record per commit through its own fetch, and it
    read `answer.detail` too."""
    answer = drive(pages["cycle"], BET_ON_SOMETHING, [{"status": 409, "json": CONFLICT}])

    assert REPORT in state(answer)
    named = answer["value"]["named"]
    assert named != answer["value"]["id"], "the fixture's row has a title to be named by"
    assert named in state(answer), "which row was refused, by the name the table draws"
    assert answer["value"]["id"] not in state(answer), "and not by an id nobody is reading"
    assert answer["value"]["disabled"] is False, "the edit is still unsaved, so Save is still live"


def test_a_conflict_creating_a_record_is_not_printed_as_refused(pages):
    """The create form lists what the server said under the fields it names. A
    conflict has no `problems` and no `detail`, so the list said "refused"."""
    answer = drive(
        pages["new"],
        f"({{lines: refusals({json.dumps(CONFLICT)}, 409),"
        f" typed: refusals({{detail: 'a task has no reported_by'}}, 422)}})",
    )

    assert answer["value"]["lines"] == [REPORT]
    assert answer["value"]["typed"] == ["a task has no reported_by"]


@pytest.mark.parametrize("page", ["cycle", "table", "detail", "graph", "cycles", "new"])
def test_every_page_that_writes_reads_a_conflict_the_same_way(pages, page):
    """One helper, in the shell, in scope on every page that can write.

    The graph's dependency save is the third path that read `answer.detail`, and
    it is the one page this shim cannot drive end to end — cytoscape wants a
    canvas. What can be asserted is that the helper it now calls is on the page
    and answers correctly, which is the whole of the fix.

    `drawn` and not `message` in the fourth answer: a Problem carries the same
    sentence in both forms — ISO for the terminal and `/api/index.json`, day-first
    for a page — and a banner is a page, so this is the key the fold reads.
    """
    answer = drive(
        pages[page],
        f"({{conflict: refusal({json.dumps(CONFLICT)}, 409),"
        " typed: refusal({detail: 'cycle must be a number'}, 422),"
        " nothing: refusal({}, 500),"
        " problems: refusal({problems: [{drawn: 'an owner is needed'}]}, 422)})",
    )
    got = answer["value"]

    assert got["conflict"] == REPORT
    assert got["typed"] == "cycle must be a number"
    assert got["nothing"] == "refused", "an answer with nothing in it still says something"
    assert got["problems"] == "an owner is needed"


# Every way a line of the shipped scripts can read a body's `detail`, each
# written so that group 1 is the RECEIVER — the name the key is read off — so
# that the one legitimate receiver can be let through by name.
#
# Three patterns and not one, because the receiver is not always on the same side
# of the key. `answer.detail` and `answer['detail']` read left to right;
# `const {detail} = answer` reads right to left and is the same access.
#
# The narrowing this replaces matched `\w+\.detail` alone, which is one of five
# spellings JavaScript has for the same read — and its own docstring already
# argued that a list of spellings is never finished. It is not finished now
# either. What it is instead is a list whose every member is mutation-tested
# below, so the next one that slips is added there in the same edit.
_READS_DETAIL_FORMS = (
    # `answer.detail`, and `answer?.detail` — the same read with a guard on it,
    # which is what a call site written today looks like.
    #
    # Tight against the dot on purpose, and not `\s*\.`: the text being swept is
    # the render package's own Python, where `from .detail import render_detail`
    # is on four lines. A pattern that allowed a space before the dot read the
    # word `from` as a receiver on every one of them.
    re.compile(r"\b(\w+)\??\.detail\b"),
    # `answer['detail']`, `answer["detail"]` and `answer?.['detail']`. No dot to
    # match at all, which is why the pattern above cannot be widened into this
    # one.
    re.compile(r"\b(\w+)(?:\?\.)?\[\s*['\"]detail['\"]\s*\]"),
    # `const {detail} = answer`, and `const {detail: why} = answer`. The
    # destructured name is written once and used everywhere after, so a sweep
    # that misses this line misses every use of it.
    re.compile(r"\{[^{}]*\bdetail\b[^{}]*\}\s*=\s*(\w+)"),
)


def _reads_detail(line: str) -> list[str]:
    """Every receiver `detail` is read off, on one line of script."""
    return [name for form in _READS_DETAIL_FORMS for name in form.findall(line)]

# The one receiver that is not a refusal at all: `CustomEvent`'s payload. Every
# `openproj:wrote` on every page carries its sha as `event.detail`, and those are
# not answers from a server. An ALLOWLIST of one name, not a list of the
# spellings a refusal might arrive under — there is no such list that is ever
# finished, which is the rule this repository has paid for more than once.
_NOT_AN_ANSWER = {"event"}

# A Jinja expression is server-side data drawn into markup before the page is
# ever served — `{{ t.blank.detail }}` on the timeline is a Python attribute, not
# a browser reading a fetch answer. Cut STRUCTURALLY, by the delimiters, and not
# by allowing the name `blank`: a list of names is the denylist-of-spellings this
# repository has been bitten by, and the next such field will have another name.
_JINJA = re.compile(r"\{\{.*?\}\}", re.S)


def test_no_write_path_reads_a_key_a_conflict_does_not_carry():
    """The fold, stated once. Reading the body's `detail` at a call site is the
    shape of the bug: it is a page deciding what the answer holds without knowing
    that the status could be 409, and that a 409 has two shapes.

    **Widened, because the narrow version was slipped twice.** It matched the
    literal string `answer.detail`, so it saw nothing at all in
    `result.detail || 'That could not be saved.'` on the slide editor or in
    `said.detail || said.conflict` on the record page's delete — two call sites
    doing exactly what this test exists to forbid, under a green suite, for as
    long as they were spelled with a different variable name. What is matched now
    is the KEY, off any receiver, with one name allowed through.
    """
    stray = []
    for raw in render_source().splitlines():
        if raw.lstrip().startswith("//"):
            continue
        line = _JINJA.sub(" ", raw)
        for receiver in _reads_detail(line):
            if receiver in _NOT_AN_ANSWER:
                continue
            # `refusal` itself is the one place that may read it, and the asset
            # uploader posts to an endpoint that cannot conflict — an image is
            # named by the hash of its own bytes, so there is nothing to
            # disagree about.
            if line.strip().startswith(("return answer.detail", "return answer.conflict")):
                continue
            if "upload" in line:
                continue
            stray.append(line.strip())

    assert not stray, stray


def test_the_sweep_above_would_see_the_two_that_slipped_it():
    """Mutation-testing the checker, because this one has already passed
    vacuously for the length of two defects.

    The first three lines are the ones that really shipped: the slide editor's
    `result.detail` and the record page's `said.detail`. If a future narrowing of
    `_READS_DETAIL_FORMS` stops matching them, this fails where the sweep would
    go quiet.

    The four after them never shipped and are the point of this being a list
    rather than an assertion about one line. Each is the same read written the
    way a contributor who has never seen this test would write it, and the
    previous version of the sweep — a single `\\w+\\.detail` — returned NOTHING
    for every one: a call site could go on deciding for itself what a 409 holds
    as long as it reached the key through a bracket, a `?.`, or a destructure.
    """
    slipped = [
        "said(result.detail || 'That could not be saved.');",
        "why.textContent = said.detail || said.conflict ||",
        "if (!response.ok) { announce(answer.detail); return; }",
        # Bracket access, which is the same read with no dot in it.
        "announce(answer['detail'] || 'refused');",
        'announce(answer["detail"]);',
        # Optional chaining, which is how a line written today guards itself.
        "announce(answer?.detail || 'refused');",
        # And the destructure, which spells the key once and then hides every
        # later use of it behind a bare local name.
        "const {detail} = answer; announce(detail);",
        "const {detail: why} = await response.json(); announce(why);",
    ]

    for line in slipped:
        found = [r for r in _reads_detail(_JINJA.sub(" ", line)) if r not in _NOT_AN_ANSWER]
        assert found, f"the sweep no longer sees {line!r}"

    # And the one server-side read it must go on cutting, or the timeline's
    # empty-state hint trips a sweep that is about JavaScript.
    assert not _reads_detail(_JINJA.sub(" ", '<p class="hint">{{ t.blank.detail }}</p>'))

    # And the shapes it must go on ignoring, or every write path in the app trips
    # it: the sha a page hands its own banner, in every spelling the pages use.
    for allowed in (
        "dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));",
        "if (event.detail) movedOurs.add(event.detail);",
        "addEventListener('openproj:wrote', event => seen.add(event.detail));",
    ):
        assert not [r for r in _reads_detail(allowed) if r not in _NOT_AN_ANSWER], allowed


# --------------------------------------------------------------------------- #
# C3: the banner that never went away
# --------------------------------------------------------------------------- #


SAVE_A_CELL_TWICE = """
(async () => {
  const cell = document.querySelector('#rows tbody td.edit');
  const box = document.getElementById('row-conflict');
  await saveCell(cell, 'ann');
  const refused = {hidden: box.hidden, text: box.textContent};
  await saveCell(cell, 'bo');
  return {field: cell.dataset.field, refused,
          landed: {hidden: box.hidden, text: box.textContent}};
})()
"""


def test_the_tables_conflict_banner_goes_when_the_next_save_lands(pages):
    """The table redraws rather than reloading, so nothing else ever took the
    banner down: one 409 left "somebody changed this before you" standing over
    every save that landed afterwards, which is a page lying about the
    repository."""
    answer = drive(
        pages["table"],
        SAVE_A_CELL_TWICE,
        [
            {"status": 409, "json": CONFLICT},  # the cell, refused
            {"status": 200, "json": {"commit": "a" * 40, "outcome": "written"}},
            {"status": 200, "json": {"problems": []}},
        ],  # the problems it re-reads after
    )
    got = answer["value"]

    assert got["refused"]["hidden"] is False, "a conflict has to be visible"
    assert REPORT in got["refused"]["text"]
    assert got["landed"]["hidden"] is True, "the banner outlived the save that disproved it"
    assert got["landed"]["text"] == ""


# --------------------------------------------------------------------------- #
# C4: a typo that takes somebody out of the cycle
# --------------------------------------------------------------------------- #


def typed_into_a_rate(value: str) -> str:
    return f"""
(async () => {{
  const box = document.querySelector('input.rate');
  box.value = {json.dumps(value)};
  const saved = await saveSetup();
  return {{saved, who: box.dataset.login, {SAY}}};
}})()
"""


@pytest.mark.parametrize("typed", ["", "  ", "0", "50%", "half"])
def test_an_availability_that_is_not_a_number_is_refused_rather_than_dropped(pages, typed):
    """A PUT is the whole roster, and a missing name means somebody was taken out
    of the cycle with their capacity. `if (rate > 0)` made every one of these a
    removal nobody asked for and nothing reported — while the bets table one
    screen away already refused a bad number by name."""
    answer = drive(pages["cycle"], typed_into_a_rate(typed))
    got = answer["value"]

    assert got["saved"] is False, "the roster was written with somebody quietly missing"
    assert answer["calls"] == [], "nothing may be sent until the number is a number"
    assert got["who"] in got["state"], "the refusal must name whose box it is"
    assert f'not "{typed}"' in got["state"], "and quote what is in it"


def test_a_roster_that_is_all_numbers_is_sent_whole(pages):
    """The other half of the same rule: every name on the page goes into the PUT,
    because the ones that do not are the ones being removed."""
    answer = drive(pages["cycle"], typed_into_a_rate("0.25"), [{"status": 200, "json": {}}])

    assert answer["value"]["saved"] is not False
    sent = json.loads(answer["calls"][0]["body"])
    assert sent["fields"]["availability"] == {"ann": 0.25, "bo": 1.0}


# --------------------------------------------------------------------------- #
# C5: the receipt a staged edit wiped
# --------------------------------------------------------------------------- #


STAGE_TWO_EDITS_THEN_SAY = f"""
(() => {{
  const rows = [...document.querySelectorAll('#bets tbody tr')];
  pend(rows[0].dataset.id, 'cycle', 41);
  pend(rows[0].dataset.id, 'person_weeks', 2);
  announce('Saved 2 changes');
  const said = document.getElementById('state').textContent;
  const ran = __tick();
  return {{said, ran, {SAY}}};
}})()
"""


def test_a_receipt_is_not_blanked_by_an_edit_made_before_it(pages):
    """`say('')` on every staged edit repeated the empty message, and a repeat is
    cleared and re-set on a 0ms timer — so two staged edits left two timers each
    holding an empty string, and both fired after the receipt. `#state` went to
    "Saved 2 changes" and then to nothing, which is the whole of what a save
    says."""
    answer = drive(pages["cycle"], STAGE_TWO_EDITS_THEN_SAY)
    got = answer["value"]

    assert got["said"] == "Saved 2 changes"
    assert got["state"] == "Saved 2 changes", "a pending timer wiped the receipt"


REPEAT_A_REFUSAL = """
(() => {
  const where = document.getElementById('state');
  announce('person_weeks must be a number, not "two"');
  announce('person_weeks must be a number, not "two"');
  const between = where.textContent;
  __tick();
  return {between, state: where.textContent};
})()
"""


def test_the_same_refusal_twice_is_still_read_out(pages):
    """The clearing is not the bug and must survive the fix: a live region speaks
    when its contents change, so refusing the same cell twice with the same
    sentence would otherwise be announced once."""
    answer = drive(pages["cycle"], REPEAT_A_REFUSAL)

    assert answer["value"]["between"] == "", "the region has to change to be read again"
    assert answer["value"]["state"] == 'person_weeks must be a number, not "two"'


# --------------------------------------------------------------------------- #
# Where a write goes
# --------------------------------------------------------------------------- #

# An id the pattern does not match is a *reported* blocker and not a refusal —
# the record loads, every page draws it, and the table offers to edit it — so an
# id with a `#` in it does reach the browser. Raw in a path, the `#` starts a
# fragment and the `?` a query, so the save somebody pressed on this row went to
# `/api/record/task-c0` and wrote to a different record or to none.
BROKEN_ID = "task-c0#001?x"
BROKEN_ID_URL = "/api/record/task-c0%23001%3Fx"

BROKEN_ID_PLAN = {
    "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
    "tasks/one.md": (
        f"---\nid: '{BROKEN_ID}'\nkind: task\ntitle: A task whose id never validated\n"
        "status: ready\nowner: ann\nreviewers: [bo]\nperson_weeks: 1\npriority: medium\n"
        "---\n\nA shaping document.\n"
    ),
}

SAVE_A_CELL = """
(async () => {
  const id = Object.keys(DATA.rows)[0];
  const cell = document.createElement('td');
  cell.className = 'edit';
  cell.dataset.record = id;
  cell.dataset.field = 'owner';
  await saveCell(cell, 'bo');
  return id;
})()
"""


@pytest.fixture(scope="module")
def broken_id_table(tmp_path_factory: pytest.TempPathFactory) -> str:
    repo = tmp_path_factory.mktemp("broken-id") / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, BROKEN_ID_PLAN, "a plan with an id nobody validated")
    with TestClient(create_app(repo, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        answer = client.get("/table")
        assert answer.status_code == 200
        return answer.text


def test_a_save_addresses_the_row_it_was_pressed_on(broken_id_table):
    """Encoded, the whole id reaches the endpoint and the endpoint refuses it —
    an id that is not an id never becomes a path, which `test_web` holds it to.
    Raw, the URL was `/api/record/task-c0` and the save landed on whatever record
    that turned out to be, with a 200 and a receipt saying it had worked."""
    # Two answers: the save, and the re-read of the problems the save triggers.
    answer = drive(
        broken_id_table,
        SAVE_A_CELL,
        [{"status": 200, "json": {"commit": "a" * 40}}, {"status": 200, "json": {"problems": []}}],
    )

    assert answer["value"] == BROKEN_ID, "the table drew a different row from the one saved"
    writes = [call for call in answer["calls"] if call["method"] == "PATCH"]
    assert [call["url"] for call in writes] == [BROKEN_ID_URL]


# --------------------------------------------------------------------------- #
# C7: the icon listbox, which is a popup nothing in a rendered file shows open
# --------------------------------------------------------------------------- #
#
# The rows exist in the markup, but which one the keyboard is on, whether the
# list is open and what happens when the server refuses are all things a script
# decides at runtime — the same blind spot the combobox and the roster were in,
# and the reason `drive.js` exists. The picker before this one was twelve buttons
# and Escape; the assertions below are the contract the listbox took on when it
# grew names, twenty-five rows and a scroll box.


def picker_of(page: str) -> str:
    """Fails loudly rather than testing nothing.

    A People page drawn for somebody who may not write, or who holds no work, has
    no picker in it at all — and every expression below would then run against a
    `null` and come back as an error the assertions do not read.
    """
    assert 'id="picker"' in page and 'id="pick"' in page, "this page has no picker to drive"
    return page


# The listbox keys, in one run: open, down twice, up once, then Escape. Read back
# through `aria-activedescendant`, because that attribute IS how this control
# tells a screen reader where the keyboard is — a test that asserted on the `.on`
# class would pass on a widget only a sighted reader can follow.
WORK_THE_KEYS = """
(() => {
  const pick = document.getElementById('pick');
  const picker = document.getElementById('picker');
  const shut = {hidden: picker.hidden, expanded: pick.getAttribute('aria-expanded')};
  pick.dispatchEvent(new Event('click'));
  const opened = {hidden: picker.hidden, expanded: pick.getAttribute('aria-expanded'),
                  at: picker.getAttribute('aria-activedescendant')};
  const press = key => picker.dispatchEvent(new CustomEvent('keydown', {key}));
  press('ArrowDown'); press('ArrowDown');
  const down = picker.getAttribute('aria-activedescendant');
  press('ArrowUp');
  const up = picker.getAttribute('aria-activedescendant');
  press('End');
  const end = picker.getAttribute('aria-activedescendant');
  press('Home');
  const home = picker.getAttribute('aria-activedescendant');
  press('Escape');
  const closed = {hidden: picker.hidden, expanded: pick.getAttribute('aria-expanded')};
  return {shut, opened, down, up, end, home, closed,
          rows: [...picker.querySelectorAll('[role="option"]')].map(row => row.dataset.icon)};
})()
"""


def test_the_listbox_opens_moves_under_the_arrows_and_closes_on_escape(pages):
    """Escape is the one that has to work: a popup you can only close by finding
    the button that opened it — now under a panel of twenty-five rows — is a trap
    for exactly the reader this widget was rebuilt for."""
    from openproj.render import ICONS

    answer = drive(picker_of(pages["people"]), WORK_THE_KEYS)
    seen = answer["value"]

    assert seen["shut"] == {"hidden": True, "expanded": "false"}
    assert seen["opened"]["hidden"] is False
    assert seen["opened"]["expanded"] == "true"
    # Opened on the row that is stored, which for somebody with no icon is the
    # one that says so — and it is first, so Home and "no icon" are the same key.
    assert seen["opened"]["at"] == "pick-none"
    assert seen["down"] == f"pick-{ICONS[1]}", "two downs from the top is the second icon"
    assert seen["up"] == f"pick-{ICONS[0]}"
    assert seen["end"] == f"pick-{ICONS[-1]}"
    assert seen["home"] == "pick-none"
    assert seen["closed"] == {"hidden": True, "expanded": "false"}
    # The vocabulary, in the vocabulary's own order, with the way out at the top.
    assert seen["rows"] == ["", *ICONS]


# Down to the second icon and Enter, then let the write settle. The microtask
# loop and not a timer: `drive.js` queues timers rather than running them, on
# purpose, so a page's autosave cannot fire against an answer nobody scripted —
# and every promise in this chain is already resolved, so draining the microtask
# queue is the whole of the wait.
CHOOSE_WITH_THE_KEYBOARD = """
(async () => {
  const pick = document.getElementById('pick');
  const picker = document.getElementById('picker');
  pick.dispatchEvent(new Event('click'));
  const press = key => picker.dispatchEvent(new CustomEvent('keydown', {key}));
  press('ArrowDown'); press('ArrowDown');
  const chosen = picker.getAttribute('aria-activedescendant');
  press('Enter');
  for (let i = 0; i < 50 && !picker.hidden; i++) await Promise.resolve();
  return {chosen, hidden: picker.hidden, expanded: pick.getAttribute('aria-expanded'),
          mark: !!pick.querySelector('svg'), unset: pick.classList.contains('unset'),
          selected: [...picker.querySelectorAll('[role="option"]')]
            .filter(row => row.getAttribute('aria-selected') === 'true')
            .map(row => row.dataset.icon),
          state: document.getElementById('state').textContent};
})()
"""


def test_a_pick_made_with_the_keyboard_is_sent_stored_and_shown(pages):
    """The whole path, without a mouse anywhere in it: the name that goes to the
    server, the drawing that lands in the button, and the row that is marked as
    yours afterwards — which is what decides where the list opens next time."""
    from openproj.render import ICONS

    answer = drive(
        picker_of(pages["people"]),
        CHOOSE_WITH_THE_KEYBOARD,
        [{"status": 200, "json": {"commit": "b" * 40}}],
    )
    seen = answer["value"]

    assert seen["chosen"] == f"pick-{ICONS[1]}"
    writes = [call for call in answer["calls"] if call["method"] == "PUT"]
    assert [(c["url"], json.loads(c["body"])) for c in writes] == [
        ("/api/icon", {"icon": ICONS[1]})
    ]
    assert seen["hidden"] is True and seen["expanded"] == "false"
    assert seen["mark"] is True and seen["unset"] is False
    assert seen["selected"] == [ICONS[1]], "the stored row moved with the pick"
    assert seen["state"] == f"Your icon is now {ICONS[1]}."


REFUSED = CHOOSE_WITH_THE_KEYBOARD


def test_a_refused_pick_leaves_the_list_open_with_the_reason_beside_it(pages):
    """A picker that closed on a refusal would leave a page identical to one where
    nothing was pressed — which is the state this feature shipped in once, and the
    reason `#state` exists at all. The refusal is a 422 because that is the one
    this endpoint really gives: `render.ICONS` is closed at the door."""
    answer = drive(
        picker_of(pages["people"]),
        REFUSED,
        [{"status": 422, "json": {"detail": "'dragon' is not an icon"}}],
    )
    seen = answer["value"]

    assert seen["hidden"] is False, "the list closed over the only account of what happened"
    assert seen["expanded"] == "true"
    assert seen["mark"] is False, "the button took a mark the server refused to store"
    # Still the row it was drawn with. ann has no icon, so "No icon" is what is
    # stored and what the list must go on saying is stored — a refusal that
    # moved the mark would be the page agreeing with a write that never landed.
    assert seen["selected"] == [""], "a refused pick moved the row marked as stored"
    assert seen["state"] == "'dragon' is not an icon"


# --------------------------------------------------------------------------- #
# C8: the plan has forked, and every page has to be able to say so
#
# The one refusal that is not about this request. `Store._absorb_remote` raises
# `StoreDiverged` when local and remote have both moved and neither contains the
# other, and refuses to guess which commits to discard; until `_refusal` was
# written the seven HTTP write routes answered that with Starlette's default 500
# — `Internal Server Error`, twenty-one bytes of `text/plain`, which `answerOf`
# turns into `{}` and every page then prints as the bare word "refused". The
# concurrency audit counted 26 of them in a row while `GET /` answered 200.
#
# So the server-side half is in `test_web.py` and this is the other half: what a
# person is actually looking at when the answer arrives. The answer is built by
# calling `_refusal` rather than typed out here, because a test that restates the
# copy it is checking is a test that agrees with itself — and because the code
# and the wording are exactly what is under test.
# --------------------------------------------------------------------------- #


# The two shas are what makes the sentence actionable, and `_absorb_remote`'s own
# wording is what carries them.
_FORK = StoreDiverged(
    "local abc1234 and remote def5678 have both moved; refusing to guess which commits to discard"
)
WEDGED = {"detail": _refusal(_FORK).detail}
WEDGED_STATUS = _refusal(_FORK).status_code


def test_a_forked_plan_gives_the_page_back_and_says_why(pages):
    """C1's assertions, against the answer that used to be the 500 in them.

    A refused write has to leave a page somebody can still use: Save back, the
    edit still there and still counted, and the reason where the reader is
    looking. This is the same shape as the plain-text 500 that took `flush()`
    down with it, and the difference is that there is now something to read.
    """
    answer = drive(pages["cycle"], SAVE_THE_ROSTER, [{"status": WEDGED_STATUS, "json": WEDGED}])
    got = answer["value"]

    assert got["threw"] is None, "the refusal came back as an exception nobody catches"
    assert got["disabled"] is False, "Save never came back, so the page cannot be saved again"
    assert got["unsaved"] == "1 unsaved change", "the edit is still there and still unsaved"
    assert got["state"] == WEDGED["detail"], (
        "the sentence that names the two shas is the whole of what a person can "
        f"act on, and the page said: {got['state']!r}"
    )


@pytest.mark.parametrize("page", ["cycle", "table", "detail", "graph", "cycles", "new"])
def test_every_page_that_writes_says_the_whole_sentence_a_forked_plan_answers(pages, page):
    """One helper, in the shell, on every page that can write — and the status
    code chosen for a divergence has to fall through it to `answer.detail`.

    409 is the code that reads right and is the one that must not be used:
    `refusal` special-cases it to mean "somebody else changed this first" and
    paints the conflict box from `answer.conflict`, which a divergence does not
    carry. That is asserted here from the browser's side — whatever `_refusal`
    picks, this page has to print the sentence and not the empty-report wording.
    """
    answer = drive(pages[page], f"refusal({json.dumps(WEDGED)}, {WEDGED_STATUS})")

    assert answer["value"] == WEDGED["detail"]
    assert "somebody else changed this first" not in answer["value"], (
        "a divergence drawn as an ordinary edit collision: a reload fixes one of "
        "those and nothing a person can do here fixes this one"
    )
    assert answer["value"] != "refused"


def test_the_two_list_forms_say_it_too(pages):
    """`refusals()` on the create form and `refusalLines()` on the table are the
    two readings that are not `refusal()` itself. Both fall back to it when the
    answer carries no `problems`, and a divergence carries none — it is not about
    a field, or a record, or this request at all."""
    created = drive(pages["new"], f"refusals({json.dumps(WEDGED)}, {WEDGED_STATUS})")
    tabled = drive(pages["table"], f"refusalLines({json.dumps(WEDGED)}, {WEDGED_STATUS})")

    assert created["value"] == [WEDGED["detail"]]
    assert tabled["value"] == [WEDGED["detail"]]


# --------------------------------------------------------------------------- #
# §4: the record page asks for the end date too
#
# One rule and not one per surface. The gate that makes the table's panel pop is
# `required_at()`, derived from the validator's own status gates, and it reaches
# this page as `data-required-at` on the controls — so Save asks the same
# question the panel does, in the medium this page already has: the control is on
# screen, so the answer is offered in it rather than in a box over it.
# --------------------------------------------------------------------------- #

FINISHING = """
(async () => {{
  const status = FORM.querySelector('[name=status]');
  status.value = 'done';
  status.dataset.word = 'Done';
  {extra}
  await save();
  const box = FORM.querySelector('[name=end_date]');
  return {{filled: box.value, {SAY}, unsaved: UNSAVED.textContent}};
}})()
"""


def test_pressing_save_on_a_finished_record_offers_the_day_it_ended(pages):
    """The ask, and the reason it stops the save rather than committing what it
    guessed.

    Marking a record done demands the day it ended and that day is almost always
    today, so the answer is written into the box it belongs in — and then nothing
    is sent, because a value the page wrote is a value nobody has read yet. A
    second press commits it, and somebody who finished on Friday changes four
    characters instead of being told what they have not done.

    The seeded task cites no pull request either, which `done` also demands and
    which no form may invent — so this asserts both halves at once: the date is
    offered, the PR is named, and the write does not go.
    """
    answer = drive(pages["detail_plain"], FINISHING.format(extra="", SAY=SAY))

    assert answer["value"]["filled"] == date.today().isoformat()
    said = answer["value"]["state"]
    assert "set to today — check it and press Save again" in said, said
    assert "still needed at Done: " in said, said
    # "Done" and not `done`: the word comes off `data-word`, which the hill keeps
    # current on the hidden input precisely so a refusal says what the reader is
    # looking at rather than what git holds.
    assert "at Done:" in said, said
    # The FIELD names are `labelOf`'s job and this harness cannot answer it:
    # `drive.js` returns null from every `previousElementSibling`, so `labelOf`
    # falls back to `control.name` here where a browser answers "End date" and
    # "PRs". What is asserted instead is that the page really does draw those two
    # words beside those two controls, which is the half that lives in markup.
    assert "end_date" in said and "prs" in said, said
    drawn = pages["detail_plain"]
    assert ">End date<" in drawn and ">PRs<" in drawn
    # The counter has to move with it, or the bar claims one change over a form
    # holding two and Reset puts back a date nobody could see had been added.
    assert answer["value"]["unsaved"] == "2 unsaved changes", answer["value"]["unsaved"]
    assert not answer["calls"], "nothing was sent"


def test_the_second_press_sends_the_date_the_page_offered(pages):
    """The ask is one press, not a dialogue: what the first press put in the box
    is what the second one commits, in the same PATCH as the status.

    A record that goes `done` and then has a date added is two commits, and for
    the length of the first one the plan holds a record the validator refuses —
    which is the same argument the table's panel is built on.
    """
    answer = drive(
        pages["detail_plain"],
        FINISHING.format(
            extra="FORM.querySelector('[name=prs]').value = 'kilnlab/kiln4py#1'; await save();",
            SAY=SAY,
        ),
        replies=[{"status": 200, "json": {"outcome": "committed", "commit": "c" * 40}}],
    )

    assert len(answer["calls"]) == 1, answer["calls"]
    sent = json.loads(answer["calls"][0]["body"])["fields"]
    assert sent["status"] == "done"
    assert sent["end_date"] == date.today().isoformat()
    assert sent["prs"] == ["kilnlab/kiln4py#1"]


def test_a_save_that_does_not_move_the_status_is_not_asked_anything(pages):
    """The guard on the two above, and the delta the ask is scoped to.

    A record can already be standing at a status whose gate it fails — a plan in
    git is a fact, and `in_progress` with nobody assigned is a shape the fixture
    corpus carries on purpose. Asked of the STATE rather than of the write, this
    check would stand in front of every press on such a record: a retitle, a tag,
    a paragraph of the shaping document, each answered with the name of a field
    nobody was editing. That is the state-versus-delta failure `web.py`'s
    past-date refusal learned the expensive way, and this is the same rule the
    table has — `saveCell` asks when the cell being written is the status cell.

    The form is put into that state rather than a second page being rendered for
    it: the assignee box is emptied AND its baseline moved with it, so `changed()`
    reports one edit — the title — over a record that fails its own gate.
    """
    answer = drive(
        pages["detail_plain"],
        f"""
        (async () => {{
          const box = FORM.querySelector('[name=assignees]');
          box.value = '';
          ORIGINAL[box.name] = JSON.stringify(read(box));
          TITLED.value = 'Reproduce the seam artefact again';
          await save();
          return {{{SAY}}};
        }})()
        """,
        replies=[{"status": 200, "json": {"outcome": "committed", "commit": "d" * 40}}],
    )

    assert len(answer["calls"]) == 1, answer["calls"]
    assert json.loads(answer["calls"][0]["body"])["fields"] == {
        "title": "Reproduce the seam artefact again"
    }


# --------------------------------------------------------------------------- #
# C9: a 409 that is not a conflict
#
# `409` in this app carries two different bodies, and until this section nothing
# in the suite knew that.
#
#   The STORE's compare-and-swap report comes back through `_result` as
#   `{outcome, commit, conflict, head, pushed}` — no `detail` anywhere in it.
#   That is C2, above, and it is the only 409 that means somebody else moved the
#   plan.
#
#   A RULE's refusal is a FastAPI `HTTPException`, so it is `{"detail": …}` with
#   no `conflict`. `web.py` answers one at thirteen places and not one of them is
#   a concurrent write: two files claiming an id, a dependency loop, a cascade
#   whose shape moved while the panel sat open, and the whole of the rekind
#   ladder.
#
# `refusal()` read `answer.conflict` alone on a 409, so every rule refusal was
# printed as the concurrency sentence and its own words were thrown away. The
# gesture that reported it: change a pitch that is filed under a project into a
# project. The server refuses BEFORE any write with "a project cannot be filed
# under a project and Verify the aroma transport port (pitch-b20000) is under
# Distributed driver (proj-a10000). Move it first, or take its parent off"; the
# page said "somebody else changed this first", which sent somebody reloading
# against a plan nobody had touched.
#
# Both records are named twice over — title, then id — and that came later, with
# the sweep that took the bare ids out of everything a gesture or a refusal says.
# "Move it first" is an instruction to open one of those two files: the title is
# how a reader knows which piece of work is meant, the id is what the file is
# called in git.
#
# There was no test to break: this whole failure sat under a green suite because
# every 409 the suite had ever driven was C2's, hand-typed.
# --------------------------------------------------------------------------- #


# What `refusal()` falls back to when a 409 gives it nothing else. Every test in
# this section exists to keep it OFF a rule's refusal: it describes something a
# reload fixes, and a rule refusal is never that.
CONCURRENCY = "somebody else changed this first"

# A record with no parent and nothing filed under it. It is the only shape that
# reaches the rekind route's `drops` question — every other record in `SEED` is
# refused by the containment ladder first, so the two `drops` exits are
# unreachable without one.
LONE = "task-c00009"
LONE_TITLE = "A chore nobody pitched"
LONE_RECORD = (
    "---\n"
    "id: task-c00009\n"
    "kind: task\n"
    "title: A chore nobody pitched\n"
    "status: ready\n"
    "owner: ann\n"
    "reviewers: [bo]\n"
    "person_weeks: 1\n"
    "priority: low\n"
    "---\n"
    "\nA chore.\n"
)


def head_of(client) -> str:
    return client.get("/healthz").json()["head"]


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory):
    """A signed-in member over a plan of your choosing, one server per plan.

    Three plans are needed and not one, because two of the refusals below are
    about a plan that is already broken in a way no route can be asked to create:
    an id claimed by two files. The two spellings of that are different 409s from
    different lines — two files in one directory is `_path_for` refusing to pick,
    and one file in each of two directories is the INDEX noticing while
    `_path_for` sees nothing wrong — so they are two plans.

    Nothing here writes: every gesture is refused before a commit, which is the
    property under test. The bodies are what the routes really answer, because a
    test that types out the sentence it is checking is a test that agrees with
    itself.
    """
    made: dict[str, TestClient] = {}
    open_clients: list[TestClient] = []

    def serve(name: str, plan: dict[str, str]) -> TestClient:
        if name not in made:
            repo = tmp_path_factory.mktemp(name) / "plan.git"
            pygit2.init_repository(str(repo), bare=True, initial_head="main")
            commit_directly(repo, plan, "seed the corpus")
            client = TestClient(create_app(repo, auth="dev", secret=SECRET))
            client.__enter__()
            client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
            open_clients.append(client)
            made[name] = client
        return made[name]

    yield serve
    for client in open_clients:
        client.__exit__(None, None, None)


@pytest.fixture(scope="module")
def rule_refusals(served) -> dict[str, dict]:
    """Every 409 a write route gives that a browser can actually provoke, keyed
    by the gesture, holding the body the server really sent.

    Four exits are missing and they are named rather than quietly absent: the two
    `… could not be found` arms in `rekind` and `remove`, and `rekind`'s own loop
    check. Each needs a plan where a record names a file that is not there while
    the index still holds the record — a state `_path_for` and `build_index`
    disagree about, which nothing reachable through the API produces. They are
    covered instead by the syntax sweep below, which reads every 409 in `web.py`
    whether a gesture can reach it or not.
    """
    plain = served("plain", {**SEED, f"tasks/{LONE}.md": LONE_RECORD})
    # Two files in one directory: `task-c00001--notes` starts with the id, which
    # is a folder somebody made to keep notes in.
    twice = served("twice", {**SEED, f"tasks/{TASK}--notes.md": SEED[PATH]})
    # One file in each of two directories. `_path_for` only ever searches the
    # directory the id's prefix names, so it finds exactly one and is happy; the
    # index walks the whole tree and is not.
    across = served("across", {**SEED, f"notes/{TASK}.md": SEED[PATH]})

    gestures = {
        # `_rekind_plan`, the parent rung. This is the reported gesture.
        "a project filed under a project": (
            plain, "POST", "/api/rekind",
            lambda head: {"id": PITCH, "kind": "project", "base_commit": head},
        ),
        # `_rekind_plan`, the other half: what is filed UNDER it.
        "records stranded under a task": (
            plain, "POST", "/api/rekind",
            lambda head: {"id": PITCH, "kind": "task", "base_commit": head},
        ),
        # The `drops` question, which is a `JSONResponse` and not an
        # `HTTPException` so that the list travels beside the sentence — and so
        # the one 409 in `web.py` whose body is written out by hand.
        "a change that would drop fields": (
            plain, "POST", "/api/rekind",
            lambda head: {"id": LONE, "kind": "note", "base_commit": head},
        ),
        # The compare-and-swap on the SHAPE of that change.
        "a drop list that no longer matches": (
            plain, "POST", "/api/rekind",
            lambda head: {
                "id": LONE, "kind": "note", "base_commit": head, "drops": ["nonsense"],
            },
        ),
        "a record left waiting for itself": (
            plain, "PATCH", f"/api/record/{OTHER}",
            lambda head: {
                "base_commit": head, "fields": {"depends_on": [OTHER]}, "body": None,
            },
        ),
        "a batch that would make a loop": (
            plain, "PATCH", "/api/records",
            lambda head: {
                "base_commit": head, "ids": [OTHER], "fields": {"depends_on": [OTHER]},
            },
        ),
        "a cascade whose shape moved": (
            plain, "DELETE", f"/api/record/{PITCH}",
            lambda head: {"base_commit": head, "also": ["nope"]},
        ),
        "two files claiming one id": (
            twice, "PATCH", f"/api/record/{TASK}",
            lambda head: {
                "base_commit": head, "fields": {"priority": "low"}, "body": None,
            },
        ),
        "an id contested across directories": (
            across, "PATCH", f"/api/record/{TASK}",
            lambda head: {
                "base_commit": head, "fields": {"priority": "low"}, "body": None,
            },
        ),
        "a batch touching a contested id": (
            across, "PATCH", "/api/records",
            lambda head: {"base_commit": head, "ids": [TASK], "fields": {"priority": "low"}},
        ),
    }

    bodies = {}
    for name, (client, method, url, body_for) in gestures.items():
        answer = client.request(method, url, json=body_for(head_of(client)))
        assert answer.status_code == 409, f"{name}: {answer.status_code} {answer.text}"
        bodies[name] = answer.json()
    return bodies


def test_the_reported_gesture_reaches_the_server_as_a_409_carrying_its_own_sentence(
    rule_refusals,
):
    """The half of the report that is about the server, before any page reads it.

    The route refused correctly and before any write, and it said the useful
    thing. Nothing below is worth asserting if this stops being true — the bug
    was never that the server was wrong.
    """
    said = rule_refusals["a project filed under a project"]

    assert said == {
        "detail": (
            f"a project cannot be filed under a project and {PITCH_TITLE} ({PITCH}) "
            f"is under {PROJECT_TITLE} ({PROJECT}). Move it first, or take its parent off"
        )
    }
    assert "conflict" not in said, "a rule refusal is not the store's report"


@pytest.mark.parametrize(
    "page", ["cycle", "table", "detail", "graph", "cycles", "new", "slide", "deck"]
)
def test_the_reported_gesture_is_not_printed_as_a_conflict_on_any_page(
    pages, rule_refusals, page
):
    """The body the server really sent, driven through the SHIPPED `refusal()` on
    every page that reads one.

    Not a hand-typed 409: this is the exact JSON `POST /api/rekind` answered the
    reported gesture with, handed to the page's own script by `drive.js`. What a
    person saw was the concurrency sentence — advice to reload, about a plan
    nobody had touched — over a sentence that named both records and said what to
    do instead.

    `slide` and `deck` are here at this level and no deeper, for the reason the
    graph already is: neither `save()` is reachable from this shim. The slide
    editor's script stops at an Ace surface `drive.js` has not got and the deck's
    at an `IntersectionObserver`, so what can be asserted of those two is that
    the helper they now call is on the page and answers correctly — which is the
    whole of what changed in them.
    """
    said = rule_refusals["a project filed under a project"]
    answer = drive(pages[page], f"refusal({json.dumps(said)}, 409)")

    assert answer["value"] == said["detail"]
    assert CONCURRENCY not in answer["value"], (
        "a rule refusal drawn as an edit collision: a reload fixes one of those "
        "and there is nothing to reload for this one"
    )


# Which records each refusal has to name, and by BOTH halves — the title a
# person reads and the id the file is called in git.
#
# `named()` writes every record it mentions as `Title (id)`, and each half does a
# job the other cannot: every one of these sentences ends in an instruction to go
# and open one of the records it names ("Move it first", "read it again and
# decide", "take them out of the selection"), so the title is how a reader picks
# which one and the id is what `git show` is given. Written out here because the
# assertion below is otherwise a comparison of the answer to itself.
NAMED_TWICE = {
    "a project filed under a project": ((PITCH, PITCH_TITLE), (PROJECT, PROJECT_TITLE)),
    "records stranded under a task": (
        (PITCH, PITCH_TITLE), (TASK, TASK_TITLE), (OTHER, OTHER_TITLE), (DONE, DONE_TITLE),
    ),
    "a change that would drop fields": ((LONE, LONE_TITLE),),
    "a drop list that no longer matches": ((LONE, LONE_TITLE),),
    "a record left waiting for itself": ((OTHER, OTHER_TITLE),),
    "a batch that would make a loop": ((OTHER, OTHER_TITLE),),
    "a cascade whose shape moved": (
        (PITCH, PITCH_TITLE), (TASK, TASK_TITLE), (OTHER, OTHER_TITLE), (DONE, DONE_TITLE),
    ),
}

# And the three that name no title at all, on purpose.
#
# These are the refusals about a plan git is already holding wrong — one id, two
# files — where WHICH record the id means is exactly what is in dispute. There is
# no title to print that would not be a guess at which of the two files was
# meant, so these name the paths and the id instead, and the remedy they give is
# a git one. A sweep that demanded a title of every refusal would have pushed a
# guess into the one sentence that must not make one.
NAMED_IN_GIT = {
    "two files claiming one id": (f"tasks/{TASK}--notes.md", f"tasks/{TASK}.md", TASK),
    "an id contested across directories": (f"tasks/{TASK}.md",),
    "a batch touching a contested id": (TASK,),
}


def test_every_409_a_write_route_gives_reaches_the_page_as_its_own_sentence(
    pages, rule_refusals
):
    """The table, driven in one run of the page's own script.

    Ten gestures, ten real bodies, one `refusal()` — the point being that not one
    of them is the store's report and every one of them has something to say. The
    generic sentence is asserted against twice on purpose: it must not be what is
    printed, and it must not merely be a PREFIX of what is printed either, which
    is how a "somebody else changed this first — <reason>" fix would pass a
    lazier assertion while still telling somebody to reload.

    **`sentence == body["detail"]` is not an assertion about content.** It says
    the helper handed back what it was given, which is worth having and is all it
    is: nine of these ten gestures would have gone on passing it while the server
    answered them with the empty string. What each sentence must actually HOLD is
    written out above and checked here, so that a refusal quietly going back to
    bare ids — the thing this branch went through the app to undo — fails on the
    gesture that reported it rather than on nothing.
    """
    expression = "({" + ",".join(
        f"{json.dumps(name)}: refusal({json.dumps(said)}, 409)"
        for name, said in sorted(rule_refusals.items())
    ) + "})"
    printed = drive(pages["detail"], expression)["value"]

    assert set(printed) == set(rule_refusals), "a gesture went missing between the two"
    # Every gesture is classified, so a new one cannot be added to the fixture
    # and left unread by everything below.
    assert set(NAMED_TWICE) | set(NAMED_IN_GIT) == set(rule_refusals), (
        "a gesture the fixture drives that nothing here says what it must name"
    )

    for name, sentence in sorted(printed.items()):
        assert sentence == rule_refusals[name]["detail"], name
        assert CONCURRENCY not in sentence, name
        assert sentence != "refused", name

    for name, records in sorted(NAMED_TWICE.items()):
        for record_id, title in records:
            assert f"{title} ({record_id})" in printed[name], (
                f"{name}: {record_id} is named without the half a reader needs — "
                f"{printed[name]!r}"
            )

    for name, wanted in sorted(NAMED_IN_GIT.items()):
        for half in wanted:
            assert half in printed[name], f"{name}: {half} is not in {printed[name]!r}"


def test_a_real_conflict_still_prints_the_stores_own_report(pages, served):
    """The other shape, and the one that must not regress.

    Provoked rather than typed: a save that lands, then a second save from the
    same page against the base commit it was rendered at. `_result` answers that
    with `conflict` and NO `detail`, which is C2's whole premise — a fix that
    made `refusal()` prefer `detail` would have printed nothing useful here.
    """
    client = served("swapping", dict(SEED))
    stale = head_of(client)
    landed = client.patch(
        f"/api/record/{TASK}",
        json={"base_commit": stale, "fields": {"priority": "low"}, "body": None},
    )
    assert landed.status_code == 200, landed.text

    refused = client.patch(
        f"/api/record/{TASK}",
        json={"base_commit": stale, "fields": {"priority": "very_high"}, "body": None},
    )
    said = refused.json()

    assert refused.status_code == 409
    assert said.get("detail") is None, "the store's report does not carry a detail"
    printed = drive(pages["detail"], f"refusal({json.dumps(said)}, 409)")["value"]
    assert printed == said["conflict"]
    assert "somebody changed this before you" in printed


# --------------------------------------------------------------------------- #
# The guard with teeth
#
# The tests above drive the ten exits a gesture can reach. This one reads all of
# them out of `web.py` as syntax, including the four no gesture reaches, and
# states the rule the next `HTTPException(409, …)` has to meet — because the
# whole defect was one call site being written without anybody knowing that 409
# already meant something.
# --------------------------------------------------------------------------- #


def _called(node: ast.Call) -> str:
    """The name being called, whether it was imported or reached through the
    module it lives in.

    `fastapi.HTTPException(409)` and `HTTPException(409)` are the same exit, and
    a sweep that reads only `ast.Name` sees one of them. `web.py` imports the
    bare name today; the next file to answer a 409 need not, and this sweep is
    written for the call site that does not exist yet.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _argument(node: ast.Call, position: int, name: str) -> ast.expr | None:
    """One argument of a call, however it was written.

    Both constructors below take every argument either way round —
    `HTTPException(409, why)` and `HTTPException(status_code=409, detail=why)`
    are the same call, and the second spelling is the one FastAPI's own
    documentation uses. Reading only the positional form is how a sweep comes to
    return nothing at all over the exact line it was written for.
    """
    if len(node.args) > position and not isinstance(node.args[position], ast.Starred):
        return node.args[position]
    return next((keyword.value for keyword in node.keywords if keyword.arg == name), None)


def _four_oh_nines(source: str) -> list[tuple[int, str]]:
    """Every place `web.py` answers 409, as (line, shape).

    `"report"` is the store's compare-and-swap answer, which `refusal()` reads
    out of `conflict`; `"sentence"` is a rule's own words in `detail`; `"empty"`
    is a 409 with neither, which is the one shape that must not exist — a page
    reading it has nothing to print but the concurrency wording.

    Read as syntax and not as text, for the reason
    `test_no_page_is_assembled_by_substitution` is: `409` appears in prose in
    this file more often than it appears in code, and a grep counts the comments
    arguing about it.

    **Widened once already.** The first version read the status out of the first
    positional argument only, matched the callee as a bare name only, and counted
    the mere PRESENCE of a `detail` keyword as a sentence — so
    `HTTPException(status_code=409)`, `JSONResponse(payload, 409)`,
    `fastapi.HTTPException(409)` and `HTTPException(409, detail=None)` were each
    either invisible or misread, and the first two of those are the spellings
    FastAPI's own documentation teaches. A guard that returns nothing over the
    shape it forbids is not a narrow guard, it is an absent one.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = _called(node)
        if called == "HTTPException":
            # `HTTPException(status_code, detail=None, headers=None)`.
            status = _argument(node, 0, "status_code")
            detail = _argument(node, 1, "detail")
        elif called == "JSONResponse":
            # `JSONResponse(content, status_code=200, …)` — the status is the
            # SECOND argument here and the first one there, which is the other
            # half of why a single positional rule could not read both.
            status = _argument(node, 1, "status_code")
            body = _argument(node, 0, "content")
            detail = None
            if isinstance(body, ast.Dict):
                detail = next(
                    (
                        value
                        for key, value in zip(body.keys, body.values, strict=True)
                        if isinstance(key, ast.Constant) and key.value == "detail"
                    ),
                    None,
                )
        else:
            continue

        if isinstance(status, ast.IfExp):
            # `_result`: `status_code=409 if written.outcome == "conflict"
            # else 200`. The one 409 in this file that IS a concurrent write,
            # and the one that may carry no `detail`.
            #
            # One of the two branches has to BE 409. `GET /api/health`
            # answers `200 if detail is None else 503` out of a payload whose
            # first key is called `detail`, and a sweep that read "a
            # conditional status" as "the store's report" counted it — which
            # would have let a real empty 409 hide behind a route that is not
            # a write at all.
            branches = [
                part.value
                for part in (status.body, status.orelse)
                if isinstance(part, ast.Constant)
            ]
            if 409 in branches:
                found.append((node.lineno, "report"))
            continue

        if not (isinstance(status, ast.Constant) and status.value == 409):
            continue
        # A `detail` that is written out as `None` is not a sentence, and the
        # first version of this counted it as one because it asked whether the
        # keyword was THERE. `HTTPException(409, detail=None)` is the constructor
        # default said out loud: it reaches a page as `{"detail": null}`, which
        # `refusal()` falls through exactly as it falls through a body with no
        # `detail` in it at all.
        said = detail is not None and not (
            isinstance(detail, ast.Constant) and detail.value is None
        )
        found.append((node.lineno, "sentence" if said else "empty"))
    return found


def test_no_route_answers_409_with_a_body_a_page_would_read_as_a_conflict():
    """The rule, stated where the next call site will be written.

    A 409 carrying neither `conflict` nor `detail` prints as "somebody else
    changed this first" on every page that reads it, whatever it was actually
    about — which is the defect this section is named for, in its worst form:
    not a sentence thrown away but a sentence that was never written.

    `_result` is the one exemption and it is recognised by SHAPE rather than by
    line or by name: its status is a conditional, because it is the same function
    for the answer that succeeded.
    """
    web_py = Path(sys.modules[create_app.__module__].__file__)
    exits = _four_oh_nines(web_py.read_text(encoding="utf-8"))

    assert len(exits) >= 13, f"the sweep found {len(exits)} 409s, so it proved almost nothing"
    assert [line for line, shape in exits if shape == "report"], (
        "no compare-and-swap answer found at all, so this sweep is reading the "
        "wrong file or the wrong shape"
    )
    empty = [line for line, shape in exits if shape == "empty"]
    assert not empty, (
        f"{web_py.name} answers 409 with no sentence in it at line(s) {empty}: every "
        "page that reads one will print 'somebody else changed this first' over "
        "whatever that refusal was really about"
    )


def test_the_sweep_above_can_tell_the_two_shapes_apart():
    """Mutation-testing the checker. Two of the harnesses in this repository have
    already passed vacuously, and a sweep that classified everything as
    `"sentence"` would be green over the exact defect it is written for."""
    empty = _four_oh_nines('raise HTTPException(409)')
    said = _four_oh_nines('raise HTTPException(409, "two files claim this id")')
    bare = _four_oh_nines('return JSONResponse({"drops": drops}, status_code=409)')
    carried = _four_oh_nines('return JSONResponse({"detail": why, "drops": d}, status_code=409)')
    swap = _four_oh_nines(
        'return JSONResponse(payload, status_code=409 if written.outcome == "c" else 200)'
    )

    assert [s for _, s in empty] == ["empty"]
    assert [s for _, s in said] == ["sentence"]
    assert [s for _, s in bare] == ["empty"], "a 409 whose body has no detail slipped through"
    assert [s for _, s in carried] == ["sentence"]
    assert [s for _, s in swap] == ["report"]
    # And a 422 is not counted at all, or the sweep is about nothing in
    # particular.
    assert _four_oh_nines('raise HTTPException(422, "not a kind")') == []
    # Nor is a conditional status that never reaches 409. `GET /api/health`
    # really answers `200 if detail is None else 503` from a payload with a key
    # called `detail` in it, and counting that as the store's report would let a
    # genuinely empty 409 hide behind a route that does not write at all.
    assert _four_oh_nines(
        'return JSONResponse(payload, status_code=200 if detail is None else 503)'
    ) == []


def test_the_sweep_above_reads_every_spelling_of_the_same_refusal():
    """The half the first version of `_four_oh_nines` could not see at all.

    Each line here is a legal way to write a 409 that the narrow sweep returned
    NOTHING for — not "sentence" over an empty one, which would at least have
    been a wrong answer, but no row at all, which reads on the calling test as a
    file with fewer 409s in it than it has. Three of the four are the spellings
    FastAPI's own documentation uses, so this is not a hypothetical shape: it is
    the one the next contributor is likeliest to type.

    Kept as a list of concrete lines and not as a generated matrix, because what
    is being pinned is that these exact strings are read — a matrix would drift
    with the reader it is testing.
    """
    unreadable = {
        # The documented keyword form, and the shape the sweep must call `empty`.
        'raise HTTPException(status_code=409)': "empty",
        'raise HTTPException(status_code=409, detail="two files claim this id")': "sentence",
        # A positional status on the response, which is `JSONResponse`'s second
        # argument and was read as though it were the first.
        'return JSONResponse({"drops": drops}, 409)': "empty",
        'return JSONResponse({"detail": why}, 409)': "sentence",
        # Reached through its module rather than imported by name.
        'raise fastapi.HTTPException(409)': "empty",
        'raise fastapi.HTTPException(409, "two files claim this id")': "sentence",
        # The constructor default written out. It is a 409 with no sentence in
        # it, however carefully the keyword is spelled.
        'raise HTTPException(409, detail=None)': "empty",
        # And the store's own report, in the keyword-free spelling.
        'return JSONResponse(payload, 409 if written.outcome == "c" else 200)': "report",
    }

    for line, shape in unreadable.items():
        assert [s for _, s in _four_oh_nines(line)] == [shape], line

    # The 422s beside them are still not this sweep's business in any spelling,
    # or every refusal in `web.py` lands in a list about concurrency.
    for line in (
        'raise HTTPException(status_code=422, detail="not a kind")',
        'raise fastapi.HTTPException(422)',
        'return JSONResponse({"detail": why}, 422)',
    ):
        assert _four_oh_nines(line) == [], line


# --------------------------------------------------------------------------- #
# C10: a write that fails in silence
#
# A dropped connection is `fetch` REJECTING — a `TypeError`, never a status — so
# nothing about it can be reached through the `!response.ok` arm, and eleven
# write paths had `try`/`finally` with no `catch` at all under a green suite for
# exactly that reason. What a person got was the gesture vanishing: the live
# region still reading "saving…", Save still disabled over a bar still counting
# the edits, and nothing anywhere to say whether the work had landed.
#
# `drive.js` grew `{reject: "…"}` for this. A scripted 500 proves nothing here:
# it is answered, and the whole failure is the answer that never comes.
# --------------------------------------------------------------------------- #


DROPPED = {"reject": "Failed to fetch"}


def test_a_dropped_connection_saving_the_cycle_setup_says_so(pages):
    """C1's assertions, against the failure that has no status at all.

    Same three things a refused save owes: Save back, the edit still there and
    still counted, and a sentence where the reader is looking. Without the
    `catch` the rejection escaped through `put`, `saveSetup` and `flush`, which
    `drive()` reports as the write never settling.
    """
    answer = drive(pages["cycle"], SAVE_THE_ROSTER, [DROPPED])
    got = answer["value"]

    assert got["threw"] is None, "the rejection came back as an exception nobody catches"
    assert got["disabled"] is False, "Save never came back, so the page cannot be saved again"
    assert got["unsaved"] == "1 unsaved change", "the edit is still there and still unsaved"
    assert "Failed to fetch" in got["state"], got["state"]
    # It must not claim what reached the server. A fetch rejects when the ANSWER
    # is lost as readily as when the request never left, so "nothing was sent" is
    # a guess — and the wrong one exactly when the write did land.
    assert "nothing was sent" not in got["state"].lower(), got["state"]
    assert "Press Save again" in got["state"], got["state"]


def test_a_dropped_connection_on_a_bet_names_the_row_it_stopped_on(pages):
    """The bets table writes one record per commit, so a rejection mid-batch is
    the one place where "nothing happened" and "some of it happened" look the
    same on screen. The row it stopped on has to be named."""
    answer = drive(pages["cycle"], BET_ON_SOMETHING, [DROPPED])
    got = answer["value"]

    assert got["threw"] is None
    assert got["disabled"] is False, "the edit is still unsaved, so Save is still live"
    # By the name the row is drawn with. The bets table draws `<a>{{ row.title }}</a>`
    # in its name cell, and this sentence used to answer with `task-0a1001`.
    assert got["named"] != got["id"], "the fixture's row has a title to be named by"
    assert got["named"] in got["state"], "which row the batch stopped on"
    assert got["id"] not in got["state"], "and not by an id nobody is reading"
    assert "Failed to fetch" in got["state"], got["state"]


DROP_A_CELL_SAVE = """
(async () => {
  const cell = document.querySelector('#rows tbody td.edit');
  const box = document.getElementById('row-conflict');
  await saveCell(cell, 'ann');
  return {record: cell.dataset.record, field: cell.dataset.field,
          conflict: {hidden: box.hidden, text: box.textContent},
          state: document.getElementById('state').textContent};
})()
"""


def test_a_dropped_connection_saving_a_cell_says_so_beside_the_table(pages):
    """The table's single-cell save. `reparent`, one screen down in the same
    file, already had this `catch`; `saveCell` did not, so the rejection escaped
    unhandled and the cell simply went back to the value the page holds — which
    is exactly what a save that LANDED also looks like here. Nothing on the
    screen could tell the two apart.
    """
    answer = drive(pages["table"], DROP_A_CELL_SAVE, [DROPPED])
    got = answer["value"]

    assert got["field"], "the driver never reached an editable cell"
    # Which row, said the way the table draws it. The first editable cell in this
    # corpus is the project's own title, and it is pinned rather than looked up
    # so that the expected sentence below is written out and not derived from the
    # page that is under test.
    assert (got["record"], got["field"]) == (PROJECT, "title"), got
    assert got["state"].startswith(f"{PROJECT_TITLE}: title not saved — Failed to fetch."), (
        "which row was not saved, by the name it is drawn under"
    )
    assert PROJECT not in got["state"], (
        f"the row's filename is not what this sentence is about: {got['state']!r}"
    )
    # Not into the conflict box. That box means the store refused a swap and
    # names what moved; a dropped connection knows neither, and a page that put
    # it there would be inventing a report.
    assert got["conflict"]["hidden"] is True
    assert got["conflict"]["text"] == ""


def test_the_harness_can_really_make_a_fetch_reject(pages):
    """Mutation-testing the new option. `{reject: …}` is the whole medium these
    four tests live in, and a shim that quietly answered 200 instead would make
    every one of them pass over a page with no `catch` in it."""
    answer = drive(
        pages["cycle"],
        "(async () => { let threw = null;"
        " try { await fetch('/api/health-not-really', {method: 'POST'}); }"
        " catch (error) { threw = String(error); }"
        " return threw; })()",
        [DROPPED],
    )

    assert answer["value"] == "TypeError: Failed to fetch"
    # And the request is recorded, because it really was made: a rejected write
    # that vanished from `calls` would be indistinguishable from one never sent.
    assert [call["url"] for call in answer["calls"]] == ["/api/health-not-really"]


# --------------------------------------------------------------------------- #
# C11: the rail nobody drove
#
# The deck's `save()` is the write path with the fewest ways in: no Save button,
# no form, no cell — the only way to send anything is to move a slide, and the
# order that goes is whatever the rail is holding when the gesture ends. Both of
# this branch's changes to it (the server's own words on a refusal, and a `catch`
# at all) shipped with nothing driving them: adding `deck` to the parametrised
# list above proves that `refusal` is ON the page, which is true of every page,
# and says nothing about whether this one calls it.
#
# It could not be driven, and the reason was in `drive.js` rather than in the
# page: `new IntersectionObserver` is near the top of the deck's one script, so
# the whole IIFE stopped there and not one of the rail's listeners was ever
# registered. Two stubs later — the observer, and `insertBefore` with the
# `nextSibling` a reorder inserts before — the gesture runs end to end.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def deck_page(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A deck with slides on its rail, which is a different plan from `pages`.

    `_deck_view` draws LEAVES bet into the cycle. `pages` bets a task and a task
    has no children, so that deck is the title slide and the empty-state
    placeholder — a rail with nothing orderable on it, from which the reorder
    cannot be driven at all. Betting the PITCH puts its three tasks on the rail,
    and doing that to `pages` would have put a pitch and three tasks into the
    bets table that every cycle test in this file drives.
    """
    repo = tmp_path_factory.mktemp("deck") / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, SEED, "seed the corpus")
    with TestClient(create_app(repo, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        bet = client.patch(
            f"/api/record/{PITCH}",
            json={"base_commit": head_of(client), "fields": {"cycle": 41}, "body": None},
        )
        assert bet.status_code == 200, bet.text
        client.put(
            "/api/cycle/41",
            json={
                "base_commit": bet.json()["commit"],
                "fields": {"starts_on": "2026-08-17", "reviews_on": "2026-09-14"},
                "body": "## Goal\n\nShip it.\n",
            },
        )
        drawn = client.get("/deck/41")
        assert drawn.status_code == 200, drawn.status_code
        return drawn.text


# Alt+ArrowDown on the first orderable thumbnail: the keyboard half of the rail's
# reorder, ending in the same `save()` a drag ends in.
#
# Driven as the gesture and not by calling `save()`, which is not reachable: the
# deck's script is one IIFE, so a test that could call it would be a test written
# against a page that does not exist. The live region is the shell's `#announce`
# — this page has no `#state`, which is what `announce` prefers where there is
# one — and the microtask flush is `test_table`'s `SETTLE`, because the shim's
# `setTimeout` fires only when a test asks it to.
REORDER_THE_DECK = """
(async () => {
  const thumbs = document.getElementById('thumbs');
  const rows = [...thumbs.children];
  const press = new Event('keydown');
  press.key = 'ArrowDown';
  press.altKey = true;
  press.target = rows[1];
  thumbs.dispatchEvent(press);
  for (let i = 0; i < 50; i++) await Promise.resolve();
  return {order: [...thumbs.children].map(item => item.dataset.id),
          said: document.getElementById('announce').textContent};
})()
"""


def test_the_rail_really_reorders_and_really_writes(deck_page):
    """The medium, before either refusal below is worth anything.

    Four thumbnails with three of them orderable, one Alt+ArrowDown, one PUT
    carrying the new order — and a rail that has actually moved. Every assertion
    in the two tests after this one is about what `save()` SAYS, and all three
    would pass over a page whose keydown handler was never registered and whose
    live region simply stayed empty.
    """
    answer = drive(
        deck_page,
        REORDER_THE_DECK,
        [{"status": 200, "json": {"outcome": "committed", "commit": "c" * 40, "conflict": None}}],
    )

    assert answer["value"]["order"] == ["title", OTHER, TASK, DONE], (
        "the held slide moved down one, and not to the end of the rail"
    )
    calls = [call for call in answer["calls"] if call["method"] == "PUT"]
    assert len(calls) == 1, "one gesture, one write"
    assert calls[0]["url"] == "/api/cycle/41"
    sent = json.loads(calls[0]["body"])
    assert sent["fields"] == {"deck_order": [OTHER, TASK, DONE]}, sent
    assert sent["base_commit"], "compared against the commit the deck was drawn at"
    assert answer["value"]["said"] == "Slide order saved, 3 slides."


def test_a_refused_reorder_says_what_the_server_said(deck_page, rule_refusals):
    """The deck's half of C9, driven through the gesture.

    This said "That order could not be saved. Reload and try again." for every
    answer it ever got — which is wrong for a rule refusal (there is nothing to
    reload for), wrong for a 422 (the field is named and reloading loses the
    order), and wrong for a 503 (the plan's history has forked and trying again
    will never clear it). The body handed over is a real one: the exact JSON the
    rekind route answered the reported gesture with.
    """
    said = rule_refusals["a project filed under a project"]
    answer = drive(deck_page, REORDER_THE_DECK, [{"status": 409, "json": said}])

    assert answer["value"]["said"] == said["detail"]
    assert CONCURRENCY not in answer["value"]["said"]
    assert "Reload and try again" not in answer["value"]["said"], (
        "one sentence over four different answers, and the wrong advice for three"
    )


def test_a_reorder_on_a_dead_connection_does_not_claim_the_rail_is_wrong(deck_page):
    """The `catch` this page had none of, and the one sentence on it that had to
    be got right rather than merely written.

    A rejection here is the only failure on this page a presenter meets in front
    of a room, and there are two of them under one symptom: the PUT never left,
    and the PUT committed while its answer was lost. In the first the rail is
    ahead of the plan; in the second the rail is exactly the plan. So the
    sentence may not say which, and it may not say "move a slide again" either —
    a second move builds a DIFFERENT order against a `BASE` that never advances,
    which is the one shape `_merge_frontmatter` refuses.
    """
    answer = drive(deck_page, REORDER_THE_DECK, [DROPPED])
    said = answer["value"]["said"]

    assert answer["value"]["order"] == ["title", OTHER, TASK, DONE], (
        "the rail is left where the gesture put it: nothing here knows to undo it"
    )
    assert said.startswith("That order was not confirmed — Failed to fetch."), said
    assert "reload this deck" in said, said
    # The three claims it must not make. Each is a sentence somebody would
    # reasonably have written and each is false on one of the two failures under
    # this one symptom.
    assert "move a slide again" not in said.lower(), (
        "the retry it advises is the conflict it would cause"
    )
    assert "does not hold" not in said, (
        "a PUT that committed and lost its answer leaves the rail showing exactly "
        "what the plan holds"
    )
    assert "nothing was sent" not in said.lower(), said


# --------------------------------------------------------------------------- #
# The guard the last section is missing
#
# Eleven write paths had `try`/`finally` with no `catch`, and every one of them
# was under a green suite: a test drives one gesture and there is no gesture for
# "the wifi went". The tests above drive six of the branch's twelve catches that
# closed them, which leaves eight standing on nothing but having been typed.
#
# So the rule is stated as syntax, over the whole render package, where the next
# write path will be written.
# --------------------------------------------------------------------------- #


def _blank_whole_line_comments(text: str) -> str:
    """The file with its whole-line `//` comments blanked out.

    Blanked and not removed, so the line numbers below are still the file's own.
    Whole-line only: the sweep that follows counts braces and these modules argue
    in prose that contains them.
    """
    return "\n".join("" if line.lstrip().startswith("//") else line for line in text.split("\n"))


def _guarded_by_a_catch(text: str, at: int) -> bool:
    """Whether the `await fetch(` at `at` sits in a `try` that has a `catch`.

    Walked backwards over braces to the nearest ENCLOSING `try {`, then forwards
    from that brace to its partner to see what follows it. Two things had to be
    read rather than grepped: an enclosing block is not the nearest `try` in the
    file — the write paths here are `try` inside `if` inside a function — and a
    `try` is not a guard, because `try`/`finally` is exactly what shipped.

    The nearest enclosing `try` decides, so a `finally`-only inner `try` inside a
    caught outer one reads as unguarded. That is the honest answer for what this
    is about: the rejection stops at the inner block's `finally` and unwinds, and
    the sentence that never got written is the inner one's.
    """
    depth = 0
    index = at
    while index > 0:
        index -= 1
        if text[index] == "}":
            depth += 1
        elif text[index] == "{":
            if depth:
                depth -= 1
                continue
            if not re.search(r"\btry\s*$", text[max(0, index - 40) : index]):
                continue
            closing = index
            level = 0
            while closing < len(text):
                if text[closing] == "{":
                    level += 1
                elif text[closing] == "}":
                    level -= 1
                    if not level:
                        break
                closing += 1
            return bool(re.match(r"\s*catch\b", text[closing + 1 : closing + 30]))
    return False


# The one non-GET fetch in the package that changes nothing.
#
# A URL and not a rule, and it is named here rather than pattern-matched because
# every structural way of telling it from the twenty writes beside it is a guess:
# `base_commit` is absent from four real writes too (`/api/asset`,
# `/api/drawing`, `/api/icon`, `/api/rekind`), so keying on that would exempt
# those instead. It is a POST because a slide's whole state is too big for a
# query string, and the route renders markdown and returns HTML — the reason it
# is asked of the server at all is written above the call.
#
# One entry, and the test asserts it is one: a second exemption has to be argued
# here, in front of the list, rather than added to it.
A_POST_THAT_READS = "/api/slide/preview"


def _write_fetches() -> list[tuple[str, int, str, bool]]:
    """Every `await fetch(` in the render package that is not a GET."""
    found = []
    for path in render_paths():
        text = _blank_whole_line_comments(path.read_text(encoding="utf-8"))
        for call in re.finditer(r"await fetch\(", text):
            window = text[call.start() : call.start() + 500]
            method = re.search(r"method:\s*'(\w+)'", window)
            if not method or method.group(1) == "GET":
                continue
            found.append(
                (
                    path.name,
                    text[: call.start()].count("\n") + 1,
                    window,
                    _guarded_by_a_catch(text, call.start()),
                )
            )
    return found


def test_every_write_a_page_makes_is_inside_a_try_with_a_catch():
    """The rule, where the next write path will be written.

    A dropped connection is `fetch` REJECTING — a `TypeError`, never a status —
    so it cannot be reached through `!response.ok`, which is the arm every one of
    these already had. What a page without a `catch` does is lose the gesture in
    silence: the live region still saying "saving…", Save still disabled, and
    nothing anywhere to say whether the work is in git.

    This is the guard the four driven catches above cannot be: there are twelve
    of them and four gestures, and the next write path will be the thirteenth.
    """
    fetches = _write_fetches()

    assert len(fetches) >= 20, (
        f"the sweep found {len(fetches)} writes in the render package, so it read "
        "the wrong files or the wrong shape"
    )
    exempt = [one for one in fetches if A_POST_THAT_READS in one[2]]
    assert len(exempt) == 1, f"the one exemption names {len(exempt)} calls: {exempt}"

    bare = [
        (name, line)
        for name, line, window, guarded in fetches
        if not guarded and A_POST_THAT_READS not in window
    ]
    assert not bare, (
        f"a write with no `catch` around it at {bare}: a dropped connection there "
        "is the gesture vanishing — the sentence still saying it is happening, the "
        "control still disabled, and nothing to say whether it landed"
    )


def test_the_sweep_above_knows_a_try_from_a_guard():
    """Mutation-testing the checker, and the second case is the one that matters:
    `try`/`finally` with no `catch` is not a mistake anybody makes once. It is
    what all eleven of these were."""
    caught = "async function save() { try { await fetch('/a', {method: 'PATCH'}); } catch (e) {} }"
    finalised = (
        "async function save() { try { await fetch('/a', {method: 'PATCH'}); } finally {} }"
    )
    bare = "async function save() { await fetch('/a', {method: 'PATCH'}); }"
    nested = (
        "async function save() { try { if (x) { await fetch('/a', {method: 'PATCH'}); } }"
        " catch (e) {} }"
    )

    for source, guarded in ((caught, True), (finalised, False), (bare, False), (nested, True)):
        at = source.index("await fetch(")
        assert _guarded_by_a_catch(source, at) is guarded, source

    # And a whole-line comment is not code. These modules argue about braces in
    # prose, and a sweep that counted those would report the file it is written
    # about as unparseable rather than as unguarded.
    commented = "// try {\nasync function save() { await fetch('/a', {method: 'PATCH'}); }"
    blanked = _blank_whole_line_comments(commented)
    assert _guarded_by_a_catch(blanked, blanked.index("await fetch(")) is False
