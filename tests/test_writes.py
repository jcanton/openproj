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

import json
from datetime import date

import pygit2
import pytest
from fastapi.testclient import TestClient
from pages import render_source
from test_injection import run_js
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, TASK

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
  return {{threw, id: row.dataset.id, disabled: SAVE.disabled, {SAY}}};
}})()
"""


def test_a_conflict_on_a_bet_says_what_moved(pages):
    """The bets table writes one record per commit through its own fetch, and it
    read `answer.detail` too."""
    answer = drive(pages["cycle"], BET_ON_SOMETHING, [{"status": 409, "json": CONFLICT}])

    assert REPORT in state(answer)
    assert answer["value"]["id"] in state(answer), "which row was refused"
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


def test_no_write_path_reads_a_key_a_conflict_does_not_carry():
    """The fold, stated once. Reading `answer.detail` at a call site is the shape
    of the bug: it is a page deciding what the answer holds without knowing that
    the status could be 409."""
    stray = [
        line.strip()
        for line in render_source().splitlines()
        if "answer.detail" in line
        and not line.lstrip().startswith("//")
        # `refusal` itself is the one place that may read it, and the asset
        # uploader posts to an endpoint that cannot conflict — an image is named
        # by the hash of its own bytes, so there is nothing to disagree about.
        and not line.strip().startswith("return answer.detail")
        and "upload" not in line
    ]

    assert not stray, stray


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
