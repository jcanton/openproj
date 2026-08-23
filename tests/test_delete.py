"""Taking a record out of the plan.

The server half is in `test_web.py`, beside the other writes, because a delete is
one: a compare-and-swap against a base commit that either lands or refuses. What
is here is the control — where it is, who is offered it, and the fact that it
asks before it acts.

Two properties are worth more than the rest and are checked in a real browser
rather than asserted about the source. A destructive control has to be resolved
to the record it is under, on a page that can hold more than one; and it has to
be impossible to fire in one press.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index, cascade_of
from openproj.model import load_repo
from openproj.render import ROUTES, STATIC, render_detail

HEAD = "0123456789abcdef0123456789abcdef01234567"

# The control itself, and the panel it opens. Markup and not a bare word: the
# stylesheet is inlined into every copy of this page, a reader's included, so a
# substring test on the class name passes on the CSS alone.
BUTTON = '<button type="button" class="delete">Delete</button>'
MARKUP = '<div class="confirming"'


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def one_task(index: Index) -> str:
    return sorted(e for e, record in index.plan.items() if record.kind == "task")[0]


def test_only_somebody_the_server_would_take_a_write_from_is_offered_the_button(
    index: Index,
):
    """Three pages, one question asked three ways.

    `editable` is not the gate. It means "there is a server to talk to", and a
    reader gets a served page with it on — so gating Delete on `editable` alone
    puts a control on a stranger's page whose only possible answer is 401. The
    editor above it has lived with that; a button that removes a record from the
    plan should not, because the way you find out is by pressing it.
    """
    record_id = one_task(index)
    writer = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    reader = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=False)
    exported = render_detail(index, STATIC, only=record_id)

    # The markup and not the word: the stylesheet is inlined into every copy of
    # this page whatever the reader may do, so a plain substring test passes on a
    # reader's page for the CSS alone and proves nothing about the control.
    assert BUTTON in writer and MARKUP in writer
    assert BUTTON not in reader, "a reader was offered a delete they cannot make"
    assert BUTTON not in exported, "a file on a memory stick offered to delete a record"


def test_the_question_names_the_record_it_is_about(index: Index):
    """"Are you sure?" over a record you cannot see is a question nobody can
    answer. This page is as long as a shaping document and the control is at the
    foot of it, so the title can easily be a screen and a half away."""
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)

    asking = page[page.index(MARKUP) :]
    assert index.plan[record_id].title in asking
    assert record_id in asking
    # And it says what "delete" means here, which is not what the word usually
    # promises: the file leaves the plan and stays in the history.
    assert "git revert" in asking


def test_delete_stands_beside_edit_and_wears_what_edit_wears(index: Index):
    """Both ways of changing a record on one line — jcanton, 2026-08-20.

    It was at the foot of the page, past the shaping document, on the argument
    that a destructive control should be far from the ones pressed all day. The
    answer to that is the confirmation, not the distance: a way out you have to
    scroll to find is one nobody finds, which is the same reason Edit moved up
    here in the first place.

    And it carries no font, padding or border of its own, so the two buttons match
    by construction rather than by two rules somebody has to keep in step. Only
    the colour it turns on hover is its own.
    """
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)

    bar = page[page.index('<p class="editbar">') :]
    bar = bar[: bar.index("</p>")]
    assert "class=\"delete\"" in bar and 'id="views"' in bar, bar

    # No size or face of its own anywhere in the stylesheet — only the hover.
    for rule in re.findall(r"\.editbar button\.delete[^{]*\{([^}]*)\}", page):
        assert "font" not in rule and "padding" not in rule, rule


def test_the_control_is_only_on_the_record_page(index: Index):
    """Asked of the other editable pages, because "only in the details view" was
    the requirement and every one of these can also write."""
    from openproj.render import render_graph, render_table

    for name, page in (
        ("table", render_table(index, ROUTES, base_commit=HEAD)),
        ("graph", render_graph(index, ROUTES, base_commit=HEAD)),
    ):
        assert BUTTON not in page, f"the {name} offers a delete"


def test_the_panel_says_what_the_delete_will_take_with_it(index: Index):
    """A cascade nobody was shown is a cascade nobody agreed to.

    The two consequences are drawn as two sentences because they are two different
    things happening to two different sets of files: records filed under this one
    are deleted, and records that merely depend on it keep their file and lose the
    dependency. Both lists come from `cascade_of`, which is what the route itself
    asks — a panel built from a second derivation of that is a panel that can be
    wrong about the commit it is authorising.
    """
    parent = next(
        record_id
        for record_id in sorted(index.plan)
        if cascade_of(index, record_id)[0]
    )
    doomed, _ = cascade_of(index, parent)
    page = render_detail(index, ROUTES, only=parent, base_commit=HEAD, may_write=True)
    asking = page[page.index(MARKUP) :]

    assert "also deletes" in asking
    for child in doomed:
        assert child in asking, f"{child} would be deleted and is not named"
    # And the same ids go back with the press, so what was answered is what the
    # server acts on.
    shown = re.search(r'data-also="([^"]*)"', asking).group(1).split()
    assert sorted(shown) == sorted(doomed + cascade_of(index, parent)[1])


def test_a_leaf_record_asks_a_plain_question(index: Index):
    """Nothing under it and nothing waiting on it, so no cascade sentence at all.
    A panel that says "this also deletes 0 records" teaches people to skim the
    line that matters."""
    leaf = next(
        record_id
        for record_id in sorted(index.plan)
        if cascade_of(index, record_id) == ([], [])
    )
    page = render_detail(index, ROUTES, only=leaf, base_commit=HEAD, may_write=True)
    asking = page[page.index(MARKUP) :]

    assert "also deletes" not in asking
    assert "depending on it" not in asking


# The request is recorded and never answered, the way `test_edges.py` stubs a
# save: the successful path ends in a navigation, which cannot be stubbed and
# would take the page and the report with it.
_PRESSES = """
window.__sent = [];
window.fetch = (url, options) => {
  window.__sent.push({url, method: options.method, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
const one = document.querySelector('article.record');
const open = one.querySelector('.editbar button.delete');
const panel = one.querySelector('.confirming');
const before = {asked: !panel.hidden, sent: window.__sent.length};

open.click();
const opened = {asked: !panel.hidden, sent: window.__sent.length,
                offered: !open.hidden};

panel.querySelector('button.keep').click();
const backedOut = {asked: !panel.hidden, sent: window.__sent.length};

open.click();
panel.querySelector('button.really').click();
return {before, opened, backedOut, sent: window.__sent};
"""


def test_it_takes_two_presses_and_the_first_one_writes_nothing(
    index: Index, tmp_path: Path
):
    """The whole point of the control. Everything up to the second press is a
    question, and a question that has already deleted the record is not one."""
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)

    got = measured_in(chrome(), page, tmp_path / "delete.html", 1200, _PRESSES)

    assert got["before"] == {"asked": False, "sent": 0}, "the page opened already asking"
    assert got["opened"]["asked"] is True, "the button did not ask anything"
    assert got["opened"]["sent"] == 0, "the first press deleted the record"
    assert got["opened"]["offered"] is False, "Delete and Delete it were both live"
    assert got["backedOut"] == {"asked": False, "sent": 0}, "Keep it did not back out"

    assert len(got["sent"]) == 1, got["sent"]
    sent = got["sent"][0]
    assert sent["method"] == "DELETE"
    assert sent["url"] == f"/api/record/{record_id}"
    # The base commit the page was drawn against, so the server can refuse a
    # delete of something somebody has edited since. Without it this would be the
    # one write in the app that cannot say what it thought it was removing.
    # `also` is the list the panel showed — empty for a leaf task with nothing
    # under it and nothing waiting on it, and sent anyway, because the server
    # tells "the page showed nothing" from "the page is too old to have been
    # asked" by whether the key is there at all.
    assert sent["body"] == {"base_commit": HEAD, "also": []}


_WRONG_ONE = """
window.__sent = [];
window.fetch = (url, options) => {
  window.__sent.push({url});
  return new Promise(() => {});
};
const bars = [...document.querySelectorAll('article.record')]
  .filter(one => one.querySelector('.editbar button.delete'));
const last = bars[bars.length - 1];
last.querySelector('.editbar button.delete').click();
last.querySelector('.confirming button.really').click();
return {bars: bars.length, sent: window.__sent.map(one => one.url)};
"""


def test_the_delete_under_a_record_is_the_delete_of_that_record(
    index: Index, tmp_path: Path
):
    """The page can hold every record in the plan — `/detail` serves them all on
    one route. Every other control here is found with `getElementById`, which on
    that page answers with the first element of the name whatever you pressed;
    for the editor the worst case is typing into the wrong box, in front of you,
    undone by not saving. This one commits, so it is found through the article it
    is in and this is the test that says so.
    """
    page = render_detail(index, ROUTES, base_commit=HEAD, may_write=True)
    got = measured_in(chrome(), page, tmp_path / "many.html", 1200, _WRONG_ONE)

    assert got["bars"] > 1, "the page held one record, so nothing was proved"
    last = sorted(index.plan)[-1]
    assert got["sent"] == [f"/api/record/{last}"], (
        f"the last record's Delete asked the server about {got['sent']}"
    )


# The one answer here that arrives a microtask late. `measured_in` stringifies
# what the script returns, synchronously, so `await` cannot be spelled inside it
# — but `--dump-dom` reads the page at the END of its virtual time budget, so a
# continuation that writes `data-report` again overwrites the placeholder and is
# what the harness brings back. Said out loud because a reader who does not know
# it will read the `return` below as the answer.
_REFUSED = """
window.fetch = () => Promise.resolve({
  ok: false, status: 409,
  json: () => Promise.resolve({detail: %s}),
});
const one = document.querySelector('article.record');
const panel = one.querySelector('.confirming');
one.querySelector('.editbar button.delete').click();
panel.querySelector('button.really').click();
setTimeout(() => {
  const why = panel.querySelector('.why');
  document.body.dataset.report = JSON.stringify({
    shown: !why.hidden,
    said: why.textContent,
    canRetry: !panel.querySelector('.acts').hidden,
  });
}, 100);
return {shown: null};
"""


def test_a_refusal_is_shown_where_the_question_was_asked(index: Index, tmp_path: Path):
    """The server refuses a delete that would orphan children and names them. That
    sentence is the useful half of the feature — "delete those three first" — and
    it must not go to the console."""
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    reason = "pitch-x cannot be deleted while task-a and task-b are filed under it."

    got = measured_in(
        chrome(), page, tmp_path / "refused.html", 1200, _REFUSED % json.dumps(reason)
    )

    assert got["shown"] is not None, "the continuation never ran, so nothing was measured"
    assert got["shown"], "the record survived and the page said nothing"
    assert got["said"] == reason
    assert got["canRetry"], "the buttons stayed gone, so there was no way to try again"


_QUIET_BAR = """
const bar = document.getElementById('commitbar');
const before = {shown: bar.offsetParent !== null, said: bar.textContent.trim()};
flipEditing();
const editing = {shown: bar.offsetParent !== null};
document.getElementById('cancel').click();
return {before, editing, after: {shown: bar.offsetParent !== null}};
"""


def test_the_commit_bar_is_not_on_screen_when_there_is_nothing_to_commit(
    index: Index, tmp_path: Path
):
    """It is sticky, so it was on screen the whole time somebody was READING a
    record, saying "Nothing to save" about a form they had not opened — a
    permanent answer to a question nobody had asked, at the foot of every page.

    Measured rather than asked of the attribute: `.commitbar` sets `display:
    flex`, which beats `[hidden]`'s `display: none` because one is an author rule
    and the other is the browser's. Every menu on the table page opened on load
    the day that was forgotten.
    """
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)

    got = measured_in(chrome(), page, tmp_path / "bar.html", 1200, _QUIET_BAR)

    assert got["before"]["shown"] is False, (
        f"the bar was on screen over a record nobody was editing, saying "
        f"{got['before']['said']!r}"
    )
    assert got["editing"]["shown"] is True, "and then it was not there when it was needed"
    assert got["after"]["shown"] is False, "Cancel left it behind"


_WHILE_EDITING = """
const one = document.querySelector('article.record');
const remove = one.querySelector('.editbar button.delete');
const before = !remove.hidden;
flipEditing();
const editing = !remove.hidden;
document.getElementById('cancel').click();
return {before, editing, after: !remove.hidden};
"""


def test_delete_leaves_while_an_edit_is_open(index: Index, tmp_path: Path):
    """Two answers to "I am done with this record" on one line is one too many.

    Delete now sits beside Edit, which is where it belongs — and the moment Edit
    becomes Save and Cancel, the button that throws the record away is a slip of
    the hand from the two that keep it. It comes back when the edit ends, by
    either door.
    """
    record_id = one_task(index)
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)

    got = measured_in(chrome(), page, tmp_path / "editing.html", 1200, _WHILE_EDITING)

    assert got["before"] is True, "there was no Delete to begin with"
    assert got["editing"] is False, "Delete stayed out while the record was being edited"
    assert got["after"] is True, "and it never came back"
