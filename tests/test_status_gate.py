"""Moving a row to a status that demands something it has not got.

`in_progress` requires `start_date`. The table does not carry that column — it
already draws two derived dates, and a third that somebody types beside them is
the kind of thing a reader has to be told apart — so changing the status from the
table used to be a refusal naming a field the table does not show, with the way
out being to open the record and come back.

It is a question now, asked before the write, so the answer travels in the same
PATCH: a row that goes `in_progress` and then has a date added is two commits,
and for the length of the first one the plan holds a record the validator refuses.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import Config, Task, required_at
from openproj.render import ROUTES, render_table

HEAD = "0123456789abcdef0123456789abcdef01234567"


# A corpus of three, hand-built rather than the demo's: every record in `seed/`
# carries a `start_date`, which is what a plan somebody has been keeping looks
# like — and the whole question here is about a record that does not. The third
# has nobody on it at all, so the question it opens has the two people lists in
# it and not only the date.
WITHOUT = "task-000001"
WITH = "task-000002"
BARE = "task-000003"


@pytest.fixture
def index() -> Index:
    records = [
        Task(
            id=WITHOUT,
            kind="task",
            title="No date on it",
            status="ready",
            owner="ann",
            assignees=["ann"],
            reviewers=["bo"],
            person_weeks=2,
        ),
        Task(
            id=WITH,
            kind="task",
            title="Dated already",
            status="ready",
            owner="ann",
            assignees=["ann"],
            reviewers=["bo"],
            person_weeks=2,
            start_date=date(2026, 8, 10),
        ),
        Task(
            id=BARE,
            kind="task",
            title="Nobody on it",
            status="ready",
            owner="ann",
            person_weeks=2,
        ),
    ]
    return build_index(records, Config(), date(2026, 8, 17))


@pytest.fixture
def page(index: Index) -> str:
    return render_table(index, ROUTES, base_commit=HEAD, may_write=True)


_ASKS = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
const row = [...document.querySelectorAll('tbody tr[data-id]')]
  .find(one => one.dataset.id === %s);
const cell = row.querySelector('td[data-col="status"]');
saveCell(cell, 'in_progress');
const panel = document.getElementById('askfor');
const asked = {shown: !panel.hidden, wrote: window.__wrote.length,
               fields: [...panel.querySelectorAll('input')].map(box => box.dataset.field),
               prefilled: panel.querySelector('input').value,
               type: panel.querySelector('input').type};
panel.querySelector('#asked').click();
return {asked, wrote: window.__wrote};
"""


def test_a_status_that_needs_a_date_asks_for_it(index: Index, page: str, tmp_path: Path):
    """One question, one write. The date is prefilled with today because that is
    what "I have started this" means nine times in ten, and it is a real date
    input rather than a text box, so the answer cannot be `next tuesday`."""
    record_id = WITHOUT
    got = measured_in(
        chrome(),
        page,
        tmp_path / "asks.html",
        1400,
        _ASKS % json.dumps(record_id),
        height=900,
    )

    assert got["asked"]["shown"], "the status was changed and nothing was asked"
    assert got["asked"]["wrote"] == 0, "it wrote first and asked afterwards"
    assert got["asked"]["fields"] == ["start_date"]
    assert got["asked"]["type"] == "date"
    assert got["asked"]["prefilled"], "the date was not prefilled"

    assert [call["url"] for call in got["wrote"]] == [f"/api/record/{record_id}"]
    sent = got["wrote"][0]["body"]["fields"]
    assert sent["status"] == "in_progress"
    assert sent["start_date"] == got["asked"]["prefilled"], (
        "the answer and the status went in two different commits"
    )


_CANCELS = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
const row = [...document.querySelectorAll('tbody tr[data-id]')]
  .find(one => one.dataset.id === %s);
const cell = row.querySelector('td[data-col="status"]');
saveCell(cell, 'in_progress');
document.getElementById('askfor').querySelector('#unasked').click();
return {wrote: window.__wrote, hidden: document.getElementById('askfor').hidden,
        status: DATA.rows[%s].status};
"""


def test_giving_up_on_the_question_changes_nothing(index: Index, page: str, tmp_path: Path):
    """Cancel is not "save it without the date": the status is what was refused,
    so leaving the question unanswered leaves the row where it was."""
    record_id = WITHOUT
    got = measured_in(
        chrome(),
        page,
        tmp_path / "cancels.html",
        1400,
        _CANCELS % (json.dumps(record_id), json.dumps(record_id)),
        height=900,
    )

    assert got["wrote"] == []
    assert got["hidden"] is True
    assert got["status"] != "in_progress"


_NO_QUESTION = """
const row = [...document.querySelectorAll('tbody tr[data-id]')]
  .find(one => one.dataset.id === %s);
const cell = row.querySelector('td[data-col="status"]');
return {missing: missingFor(DATA.rows[cell.dataset.record], 'in_progress')};
"""


def test_a_row_that_has_what_the_status_wants_is_not_asked(index: Index, page: str, tmp_path: Path):
    """The question is only worth asking when there is something to ask for."""
    got = measured_in(
        chrome(),
        page,
        tmp_path / "quiet.html",
        1400,
        _NO_QUESTION % json.dumps(WITH),
        height=900,
    )

    assert got["missing"] == []


def test_the_gate_the_table_asks_from_is_the_gate_the_server_enforces(page: str):
    """`required_at()` is derived by running the rules over a blank record of each
    kind at each status, so the map the table asks from cannot drift from the one
    the server refuses with. Shipped, and not written down twice."""
    block = page.split('id="payload" type="application/json">')[1]
    payload = json.loads(block.split("</script>")[0])

    for kind in ("project", "pitch", "task"):
        assert payload["required"][kind] == {
            field: list(at) for field, at in required_at(kind).items()
        }
    # Per kind, because a row is one kind: merged, the map demands `person_weeks`
    # of a project at `ready`, and a project has no such field.
    assert "in_progress" in payload["required"]["task"]["start_date"]
    assert "person_weeks" not in payload["required"]["project"]
    # And the foot of the ladder demands nothing, on the page as well as in the
    # gate. `thinking` is where a record opens, so this is the map every row
    # created from this table is judged against first: one field marked required
    # here and the editor asks for something before it will let a half-formed
    # record exist at all, which is the one thing the word is for.
    for kind in ("project", "pitch", "task"):
        asked = [field for field, at in payload["required"][kind].items() if "thinking" in at]
        assert asked == [], kind


_SUGGESTING = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
const row = [...document.querySelectorAll('tbody tr[data-id]')]
  .find(one => one.dataset.id === %s);
saveCell(row.querySelector('td[data-col="status"]'), 'in_progress');
const panel = document.getElementById('askfor');
const box = panel.querySelector('input[data-field="assignees"]');
const key = name => box.dispatchEvent(
  new KeyboardEvent('keydown', {key: name, bubbles: true, cancelable: true}));
// One name already held, so picking a second can tell "complete the last token"
// from "replace the whole value" — which is what `data-type` decides.
box.focus();
box.value = 'ann, b';
box.dispatchEvent(new Event('input', {bubbles: true}));
const list = document.getElementById(box.getAttribute('aria-controls'));
const item = list.querySelector('li');
const at = item.getBoundingClientRect();
const hit = document.elementFromPoint(at.left + 4, at.top + 4);
const opened = {
  fields: [...panel.querySelectorAll('input')].map(one => one.dataset.field),
  role: box.getAttribute('role'), type: box.dataset.type,
  expanded: box.getAttribute('aria-expanded'),
  offered: [...list.querySelectorAll('li')].map(one => one.dataset.value),
  under: Math.abs(list.getBoundingClientRect().top - box.getBoundingClientRect().bottom) < 2,
  onTop: !!(hit && hit.closest('ul.suggest') === list),
};
key('Enter');
const picked = {value: box.value, panelShown: !panel.hidden,
                listShut: list.hidden, wrote: window.__wrote.length};
panel.querySelector('input[data-field="reviewers"]').value = 'ann';
key('Enter');
return {opened, picked, wrote: window.__wrote,
        panelAfterSave: document.getElementById('askfor').hidden};
"""


def test_the_question_offers_the_suggestions_a_cell_editor_offers(
    index: Index, page: str, tmp_path: Path
):
    """The gate's boxes are the same fields as the cells beneath them, and they
    had no autocomplete at all: `attachSuggest` runs over the page once at load,
    and this panel is built at runtime.

    Three claims beyond "a list appears". The box keeps the combobox contract the
    widget writes. The pick completes the last comma-separated token rather than
    replacing the value — that is `data-type`, which the panel did not carry. And
    the list is painted on top of the panel and where the box is, asked of real
    pixels with `elementFromPoint`: `.suggest` is z-index 20 against the panel's
    fixed 6, both body children, and a list drawn behind the panel would keep
    every other assertion here green.

    Enter on an open list picks and must not also save: this listener is on the
    input and the panel's is on the way up, so before `defaultPrevented` was
    honoured one press did both.
    """
    got = measured_in(
        chrome(),
        page,
        tmp_path / "suggesting.html",
        1400,
        _SUGGESTING % json.dumps(BARE),
        height=900,
    )

    assert got["opened"]["fields"] == ["assignees", "reviewers", "start_date"]
    assert got["opened"]["role"] == "combobox"
    assert got["opened"]["type"] == "list"
    assert got["opened"]["expanded"] == "true"
    # `ann` is already held, so it is not offered again; `bo` matches the `b`.
    assert got["opened"]["offered"] == ["bo"]
    assert got["opened"]["under"], "the list is not hanging under the box it completes"
    assert got["opened"]["onTop"], "the list is painted behind the gate panel"

    assert got["picked"]["value"] == "ann, bo, ", "the pick replaced the value instead"
    assert got["picked"]["listShut"] is True
    assert got["picked"]["panelShown"] is True, "picking a name saved the half-answered panel"
    assert got["picked"]["wrote"] == 0

    # The second Enter met no open list, so it is the panel's: one write, with
    # the picked names coerced as lists and the prefilled date beside them.
    assert got["panelAfterSave"] is True
    assert [call["url"] for call in got["wrote"]] == [f"/api/record/{BARE}"]
    sent = got["wrote"][0]["body"]["fields"]
    assert sent["status"] == "in_progress"
    assert sent["assignees"] == ["ann", "bo"]
    assert sent["reviewers"] == ["ann"]


_ONE_ESCAPE = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
const row = [...document.querySelectorAll('tbody tr[data-id]')]
  .find(one => one.dataset.id === %s);
saveCell(row.querySelector('td[data-col="status"]'), 'in_progress');
const panel = document.getElementById('askfor');
const box = panel.querySelector('input[data-field="assignees"]');
const key = name => box.dispatchEvent(
  new KeyboardEvent('keydown', {key: name, bubbles: true, cancelable: true}));
box.focus();
box.value = 'b';
box.dispatchEvent(new Event('input', {bubbles: true}));
const list = document.getElementById(box.getAttribute('aria-controls'));
const wasOpen = !list.hidden;
key('Escape');
const first = {listShut: list.hidden, panelShown: !panel.hidden, value: box.value};
key('Escape');
return {wasOpen, first, panelShut: panel.hidden,
        wrote: window.__wrote.length, status: DATA.rows[%s].status};
"""


def test_one_escape_dismisses_one_thing(index: Index, page: str, tmp_path: Path):
    """Escape with the list open closes the list; the question stands, with what
    was typed still in the box. Before the widget marked the Escape it consumed,
    the same press also cancelled the whole panel — the answer half-given, gone.

    The second Escape meets no list and is the panel's: cancelled, unwritten.
    """
    got = measured_in(
        chrome(),
        page,
        tmp_path / "one-escape.html",
        1400,
        _ONE_ESCAPE % (json.dumps(BARE), json.dumps(BARE)),
        height=900,
    )

    assert got["wasOpen"], "the list never opened, so nothing here was asked"
    assert got["first"]["listShut"] is True
    assert got["first"]["panelShown"] is True, "one Escape dismissed the list AND the panel"
    assert got["first"]["value"] == "b", "closing the list took the typing with it"
    assert got["panelShut"] is True
    assert got["wrote"] == 0
    assert got["status"] != "in_progress"
