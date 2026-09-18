"""The right-click menu, in the three views that draw it.

`design/context-menus.md` is the argument; this covers its first three cuts —
the box, the host contract and the reader's three items, and then the three
one-field writes that turned the menu from something you read into something
that changes the plan.

The judgement jcanton makes on cut 2 is menu-versus-hover, so the questions that
mattered most there are not about the items at all. They are about the two
floating boxes getting out of each other's way, and about what a key means when
two things on the page both want it. Cut 3's are about what went on the wire:
which record, how many times, against which base, and what the box does with an
answer it did not want.

Nearly all of these are asked of Chrome; `chrome()` skips when there is none,
because a suite that is green for want of a binary is green for the wrong
reason. Three need none of it and are asked of the rendered page and the
stylesheet it ships.

What a headless run cannot see is written into the tests that depend on it:
there is no native context menu to photograph in this browser, and the only
thing a page controls about one is `preventDefault()`. So that is what is
measured, off a press the browser itself synthesised — a `MouseEvent` a script
constructs runs no default action, so under it `preventDefault()` suppresses a
menu that was never going to appear and the assertion passes either way.

**The server the write tests answer to is a stub at `fetch`** — see `_WRITING`.
What is being asked is what the page SENT and what it did with what came back,
and a `file://` page has nowhere to send it. The stub answers both routes one
menu write touches and keeps them consistent with each other, which is not a
detail: a re-read that handed back the rows from before the write would let a
host that never re-read anything pass, and one that said `unpushed: 0` about a
commit it had just called unpushed clears the row mark it had just earned.
"""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

import pytest
from browser import PRESSES, _devtools, _evaluated, chrome, measured_in, pressed_in

from openproj.index import Index, build_index
from openproj.model import KINDS, load_repo, parse_text
from openproj.render import (
    _POP_STYLE,
    ROUTES,
    STATIC,
    _payload,
    _pop_js,
    render_detail,
    render_graph,
    render_help,
    render_table,
    render_timeline,
)
from openproj.render.tokens import HUMAN, STATUS_GLYPH

HEAD = "0123456789abcdef0123456789abcdef01234567"

# What `placeFloat` (`shell.py`) puts between the pointer and the box it opens.
# Written here as a number because these tests assert *where* the menu landed,
# and "somewhere near the pointer" is a claim that a box in the top-left corner
# also satisfies on a small enough window.
GUTTER = 14


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def a_writers_table(index: Index) -> str:
    return render_table(index, ROUTES, base_commit=HEAD, may_write=True)


# The rungs a plan can hold and a plan view may not draw — issue and note today.
# Read off the ladder rather than named, which is `tests/test_exclusion.py`'s
# rule: a seventh unplanned kind needs no edit in either file.
_UNPLANNED = tuple(rung for rung in KINDS if not rung.planned)


@pytest.fixture
def index_holding_an_off_plan_parent(demo_root: Path) -> Index:
    """The demo corpus, plus one record off the plan and one planned task filed
    under it by hand.

    This is the third of `Take out of "X"`'s three sentences, and the corpus is
    the whole of what makes it askable: `_row` (`rows.py`) nulls a parent that is
    not in `index.plan` and sets `off_plan_parent` beside it, so without a record
    in this shape the refused branch is unreachable and a test of it would be a
    test of nothing.

    `tests/test_exclusion.py` builds the same pair — through a bare repository
    and a served client, because what it asks is what the payload carries over
    the wire. What is asked here is what one menu item SAYS, so the index is
    built in process and the page rendered from it.
    """
    if not _UNPLANNED:  # pragma: no cover - depends on the ladder, not on the code
        pytest.skip(
            "no rung with planned=False, so no record can have a parent the plan "
            "holds and this view cannot draw"
        )
    rung = _UNPLANNED[0]
    holder = f"{rung.prefix}-0ff002"
    front = [f"id: {holder}", f"kind: {rung.name}", "title: Something the plan will not draw"]
    if rung.statuses:
        front.append(f"status: {rung.statuses[0]}")
    records, config, _ = load_repo(demo_root)
    records.append(
        parse_text(
            "---\n" + "\n".join(front) + "\n---\n\nHeld off the plan.\n",
            f"{rung.directory}/{holder}.md",
        )
    )
    # Every field the gate at `ready` asks of a task, so the record this test
    # presses on is refused for exactly one reason and not for two.
    records.append(
        parse_text(
            "---\nid: task-0ff001\nkind: task\ntitle: Filed off the plan\nstatus: ready\n"
            "owner: jackdawrie\nassignees: [jackdawrie]\nreviewers: [mudlarkish]\n"
            f"person_weeks: 1\nparent: {holder}\n---\n\nA hand-written parent.\n",
            "tasks/task-0ff001.md",
        )
    )
    return build_index(records, config, date(2026, 8, 17))


# --------------------------------------------------------------------------- #
# What the rendered page says on its own
# --------------------------------------------------------------------------- #


def test_the_menu_ships_on_the_three_views_that_want_it_and_not_on_the_rest(index: Index):
    """`pop.py` and not `shell.py`, and this is the assertion that holds the line.

    The shell ships on all twelve pages, including `/help` and `/people`; this
    menu is wanted by three. So the module is imported by the views that want
    it, and a later "it would be simpler in the shell" shows up here as two
    pages that grew a menu nobody asked them for.

    Both halves are asked of each host, because they fail differently and only
    one of them is visible. A page that ships the script and never calls
    `popServes` has `POP_HOST` null, so `popMenu` returns false on every press
    and the page looks exactly like a page with no menu at all.
    """
    hosts = {
        "table": a_writers_table(index),
        "graph": render_graph(index, ROUTES, base_commit=HEAD, may_write=True),
        "timeline": render_timeline(index, ROUTES),
    }
    for name, page in hosts.items():
        assert "function popServes(" in page, f"{name} does not carry the menu's script"
        assert "popServes({" in page, (
            f"{name} carries the menu but registers no host, so `popMenu` answers "
            "false on every press and the page draws nothing"
        )
        assert "#pop .popitem" in page, f"{name} carries the menu with no stylesheet for it"

    elsewhere = {
        "the record page": render_detail(index, ROUTES, base_commit=HEAD, may_write=True),
        "help": render_help(index, ROUTES),
    }
    for name, page in elsewhere.items():
        assert "function popServes(" not in page, (
            f"{name} ships the right-click menu, which is the shell's failure mode "
            "arriving by another route"
        )


def test_the_menus_sheet_defines_no_colour_and_takes_no_focus_ring_away():
    """Two rules this sheet has to meet, and it meets them by having nothing for
    them to bite on.

    Colours are tokens defined in three blocks — bare `:root`, the toggle and the
    media query — because most readers never touch the toggle and match the media
    query alone. A sheet that defines one token in one place is right for some
    readers and wrong for the rest. This one only *uses* tokens, so there is no
    third copy to forget.

    And the ring: `.drawmenu` switches it off and fills the item with the accent
    instead, which this sheet may not copy, because
    `test_every_page_can_draw_a_problem_and_a_focus_ring` forbids that declaration
    anywhere in `table.html` and this sheet is inlined into exactly that page.

    **The way that one fails is by being mentioned, not by being written.** A
    stylesheet's comments ship in the page's bytes, so a rule this sheet explains
    it is NOT using puts the forbidden characters on the served page just as
    surely as using it would — the same substring, on the same page, failing the
    same assertion. Two tests have already found their answer in a CSS comment
    rather than in a control (`tests/pages.py`). So the comment says what this
    sheet does instead, and never spells the declaration it is declining.
    """
    assert ":root" not in _POP_STYLE, "the menu's sheet opens a `:root` block of its own"
    defined = re.search(r"--[a-z0-9-]+\s*:", _POP_STYLE)
    assert not defined, (
        f"the menu's sheet defines {defined.group(0) if defined else ''} — a token defined "
        "in one block is wrong for every reader who matches another"
    )
    assert "outline: none" not in _POP_STYLE, (
        "the menu's sheet carries `outline: none` — as a rule or, just as fatally, "
        "inside a comment explaining that it does not use one. It is inlined into "
        "table.html, where test_every_page_can_draw_a_problem_and_a_focus_ring "
        "forbids that string outright"
    )
    assert "outline-offset" in _POP_STYLE, (
        "nothing moves the focus ring inside the item, so the box's own "
        "`overflow-y: auto` clips it"
    )


def test_the_script_knows_where_a_record_lives_in_both_modes():
    """`_pop_js` is a function and `_POP_STYLE` a constant, and the difference is
    this one value: `/detail/` from the server, `detail.html#` in an export.

    The failure it guards is quiet. `_page` takes a template as finished markup,
    so a `{{ }}` left unrendered in a constant is literal text that does nothing
    at all — which is how one rule in `_GRAPH_STYLE` first shipped as a no-op.
    """
    served = str(_pop_js(ROUTES))
    exported = str(_pop_js(STATIC))

    assert 'const POP_RECORD = "/detail/"' in served
    assert 'const POP_RECORD = "detail.html#"' in exported
    for mode, js in (("served", served), ("exported", exported)):
        assert "{{" not in js, f"the {mode} script still carries an unrendered template hole"


# --------------------------------------------------------------------------- #
# The press itself, which only a browser can make
# --------------------------------------------------------------------------- #


# Everything the table's scripts need to be asked about the menu, in the words
# the page itself uses. `bubbles: true` on a cell rather than a dispatch straight
# at the listener: which element carries the view's `contextmenu` handler is the
# view's business — the tbody today — and a test aimed at the handler stops being
# a test of the wiring the moment the wiring moves.
_OPENING = """
const menuRows = () => [...document.querySelectorAll('tbody tr[data-id]')]
  .filter(tr => !tr.classList.contains('draft'));
const rightOn = (row, x, y) => {
  const cell = row.querySelector('td[data-col="title"]');
  const event = new MouseEvent('contextmenu',
    {bubbles: true, cancelable: true, button: 2, buttons: 2, clientX: x, clientY: y});
  cell.dispatchEvent(event);
  return event;
};
const kindsInTheMenu = () => [...POP.children].map(item => item.dataset.kind);
const tabsInTheMenu = () => [...POP.children].map(item => item.tabIndex);
const pressKey = key => document.activeElement.dispatchEvent(
  new KeyboardEvent('keydown', {key: key, bubbles: true, cancelable: true}));
const rest = ms => new Promise(done => setTimeout(done, ms));
"""

# The three items that only LOOK, in this order, and they are the whole of what a
# reader gets from `popItems` itself. `data-kind` and never the visible text: the
# slug is the handle and the words are copy.
#
# Last on purpose, so their position does not move when somebody signs in.
READER_ITEMS = ["open", "open-tab", "copy-link"]
# And the three that write, first, which is the other end of that same ordering.
# Between them is the slot each view splices its own items into —
# `focus-subtree` on the table and the graph, `add-dependency` on the graph, and
# nothing at all on the timeline, which registers no `extras` because it cannot
# write. Those slugs are the HOST's and are deliberately not written down here.
WRITE_ITEMS = ["status", "owner", "take-out"]


# Read before the press: which row is going to be pressed, which two rows are its
# neighbours, and a listener that records what the browser's own `contextmenu`
# event looked like by the time it had finished bubbling. On `window`, which is
# the last stop on the way up, so `defaultPrevented` there is the page's final
# answer whichever element the view bound its handler to.
_BEFORE_THE_PRESS = """
(() => {
  const rows = [...document.querySelectorAll('tbody tr[data-id]')]
    .filter(tr => !tr.classList.contains('draft'));
  if (rows.length < 3) throw new Error('fewer than three rows were drawn');
  const row = rows[1];
  row.scrollIntoView({block: 'center'});
  window.__cell = row.querySelector('td[data-col="title"]');
  window.__rows = {pressed: row.dataset.id, above: rows[0].dataset.id,
                   below: rows[2].dataset.id};
  window.__title = DATA.rows[row.dataset.id].title;
  addEventListener('contextmenu', event => {
    window.__native = {prevented: event.defaultPrevented, shift: event.shiftKey};
  });
  return true;
})()
"""

# Asked after `setup`, so it measures the layout the press will actually meet.
# The point is kept as well as answered: what the menu has to be beside is the
# place the pointer was, and that number exists nowhere else afterwards.
_WHERE_TO_PRESS = """
(() => {
  const box = window.__cell.getBoundingClientRect();
  window.__at = [Math.round(box.left + box.width / 2), Math.round(box.top + box.height / 2)];
  return window.__at;
})()
"""

_WHAT_HAPPENED = """
(() => {
  const box = POP.getBoundingClientRect();
  return {open: popIsOpen(), about: popAbout(), rows: window.__rows, at: window.__at,
          title: window.__title, label: POP.getAttribute('aria-label'),
          kinds: [...POP.children].map(item => item.dataset.kind),
          left: box.left, top: box.top, native: window.__native};
})()
"""


def test_a_right_press_opens_the_menu_at_the_pointer_for_the_row_under_it(
    index: Index, tmp_path: Path
):
    """One trusted press, and four things only a trusted press can be asked.

    `Input.dispatchMouseEvent` and not a `MouseEvent` a script builds: a
    synthetic event runs no default action, so under it there is no browser menu
    to suppress and `preventDefault()` proves nothing. `pressed_in`'s `button`
    parameter exists for exactly this press.

    The row is the middle one of three so that "this record" and "a neighbouring
    record" are different answers — a menu built from the wrong row is a menu
    that deletes the wrong record in cut 5, and it looks perfectly normal.

    **The window is given a size, and that is the whole point of the two
    assertions below.** They are `left == x + 14` and `top == y + 14`, which are
    exactly the two numbers `placeFloat` FLIPS when the box would cross a
    gutter — so this test is asking about placement in a window whose size it
    had better be stating. `pressed_in` took Chrome's own default until
    2026-09-18, which is 756x469 here: the press landed at y=332 and the box is
    about 85px tall, so it fitted with 38 pixels to spare and nothing said so.
    1280x900 is the size the shift test below already asks for.
    """
    where = tmp_path / "pressed.html"
    where.write_text(a_writers_table(index))
    got, _said = pressed_in(
        chrome(),
        where.as_uri(),
        tmp_path / "profile",
        setup=_BEFORE_THE_PRESS,
        at=_WHERE_TO_PRESS,
        then=_WHAT_HAPPENED,
        button="right",
        flags=("--window-size=1280,900",),
    )

    assert got["native"], "no contextmenu event reached the page at all"
    assert got["open"] is True, "a right press on a row opened no menu"
    assert got["about"] == got["rows"]["pressed"], (
        f"the menu is about {got['about']} and the press was on {got['rows']['pressed']}"
    )
    assert got["about"] not in (got["rows"]["above"], got["rows"]["below"]), (
        "the menu is about a neighbouring row"
    )
    assert got["label"] == f"Actions for {got['title']}", (
        f"the box names itself {got['label']!r}, which is not the record that was pressed"
    )
    assert got["kinds"][:3] == WRITE_ITEMS, got["kinds"]
    assert got["kinds"][-3:] == READER_ITEMS, got["kinds"]
    # Beside the pointer, which is `placeFloat`'s 14px on both axes. A row in the
    # middle of the window is neither near enough to a gutter to be flipped nor
    # near enough to the corner for "at the pointer" and "at 0,0" to agree.
    assert abs(got["left"] - (got["at"][0] + GUTTER)) <= 2, (
        f"the box opened at x={got['left']} for a press at x={got['at'][0]}"
    )
    assert abs(got["top"] - (got["at"][1] + GUTTER)) <= 2, (
        f"the box opened at y={got['top']} for a press at y={got['at'][1]}"
    )
    assert got["native"]["prevented"] is True, (
        "the page did not call preventDefault, so the browser's own menu opens "
        "on top of ours"
    )


# The same two presses, watched. `window.__native` is cleared between them so an
# answer left over from the first cannot stand in for the second's.
_ASK_AFTER_A_PRESS = """
(() => ({open: popIsOpen(), about: popAbout(), native: window.__native}))()
"""


def _right_press(call, at: list[int], *, shift: bool) -> None:
    """A trusted right press, with a modifier `pressed_in` has no parameter for.

    `pressed_in` sends `button` and the `buttons` mask and nothing else, and
    shift is the entire question here — so the press is made through the same
    DevTools method it uses, with CDP's modifier mask beside it (Shift is 8).
    The mask for the button itself is imported rather than written out again:
    it is left 1, right 2, middle 4 and *not* `1 << index`, which is the
    arithmetic that looks right and silently swaps middle and right.
    """
    _evaluated(call, "window.__native = null")
    for kind in ("mousePressed", "mouseReleased"):
        call(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": at[0],
                "y": at[1],
                "button": "right",
                "clickCount": 1,
                "buttons": PRESSES["right"] if kind == "mousePressed" else 0,
                "modifiers": 8 if shift else 0,
            },
        )
        time.sleep(0.1)
    time.sleep(0.5)


def test_shift_and_right_together_leave_the_browsers_own_menu_alone(index: Index, tmp_path: Path):
    """Shift+right-click falls through, on every view.

    **What a headless run can and cannot see.** It cannot see the browser's own
    menu: nothing paints one here, and DevTools offers no way to ask whether one
    appeared. What it can see is the only thing a page decides about one —
    whether `preventDefault()` was called on the `contextmenu` event the browser
    synthesised. That is the whole of the mechanism, and it is observable only
    off a *trusted* press: a script-built `MouseEvent` carries no default action,
    so calling `preventDefault()` on it suppresses nothing and a page that
    ignored the shift key entirely would pass.

    The plain press afterwards is the control, and it is not decoration. Without
    it this test passes on a page where the menu was never wired up at all —
    which is precisely the state this branch is in until the views register a
    host.
    """
    where = tmp_path / "shift.html"
    where.write_text(a_writers_table(index))
    with _devtools(
        chrome(), where.as_uri(), tmp_path / "profile", ("--window-size=1280,900",)
    ) as (call, _said):
        time.sleep(2)
        _evaluated(call, _BEFORE_THE_PRESS)
        at = _evaluated(call, _WHERE_TO_PRESS)
        assert isinstance(at, list), at
        _right_press(call, at, shift=True)
        shifted = _evaluated(call, _ASK_AFTER_A_PRESS)
        _right_press(call, at, shift=False)
        plain = _evaluated(call, _ASK_AFTER_A_PRESS)

    assert shifted["native"], "the shifted press produced no contextmenu event at all"
    assert shifted["native"]["shift"] is True, "the shift key did not reach the page"
    assert shifted["open"] is False, "shift+right-click opened our menu"
    assert shifted["native"]["prevented"] is False, (
        "the page suppressed the browser's own menu on a shifted press, which is "
        "the one press that exists to reach it"
    )
    assert plain["open"] is True, (
        "the unmodified press opened nothing either, so this page has no menu and "
        "the assertions above are about nothing"
    )
    assert plain["native"]["prevented"] is True


# --------------------------------------------------------------------------- #
# The card and the menu, which is the rule jcanton asked for by name
# --------------------------------------------------------------------------- #


# > Opening the menu kills the card, and the card does not come back while the
# > menu is up.
#
# Four questions, because that rule is three things and a fourth that is only
# visible afterwards. `CARD_DELAY` is 600ms, so each wait is 900.
_THE_CARD = """
const row = menuRows()[1];
const held = DATA.rows[row.dataset.id];
const title = () => menuRows()[1].querySelector('td[data-col="title"]');
const hover = () => title().dispatchEvent(
  new PointerEvent('pointerover', {bubbles: true, clientX: 300, clientY: 305}));

// One that is already drawn.
showCard(held, 300, 300);
const drawn = !CARD.hidden;
rightOn(row, 300, 300);
const afterOpening = CARD.hidden;

// One queued 400ms ago and not yet drawn, which would otherwise appear on top
// of the box.
popClose();
queueCard(held, 300, 300);
rightOn(row, 310, 310);
await rest(900);
const queued = CARD.hidden;

// And the pointer, which is sitting over the row the box covers.
hover();
await rest(900);
const underneath = CARD.hidden;
const stillUp = popIsOpen();

// Afterwards it is a hover card again. Without this a flag that is set and
// never cleared passes all three questions above and silently costs the page
// its card.
popClose();
hover();
await rest(900);
const afterwards = !CARD.hidden;
return {drawn, afterOpening, queued, underneath, stillUp, afterwards};
"""


def test_the_card_gets_out_of_the_way_while_the_menu_is_up(index: Index, tmp_path: Path):
    """jcanton, 2026-09-18: *"I didn't mean kill the card entirely: kill it / hide
    it if right click is detected, but it should still show up on hover!"*

    Two body-mounted singletons, and what they owe each other is one rule that is
    three mechanisms: the card hidden now rather than after its grace, the
    pending `cardTimer` cancelled, and a flag `queueCard` consults — because the
    pointer never moved, so it is sitting over the row the menu covers and every
    `pointerover` re-arms the card underneath it.

    Asked with a real clock, because all three are about time.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "card.html",
        1200,
        _OPENING + _THE_CARD,
        patience=4200,
    )

    assert got["drawn"] is True, "no card was drawn at all, so nothing here is being dismissed"
    assert got["afterOpening"] is True, "the card was still up under the menu"
    assert got["queued"] is True, (
        "a card queued before the menu opened was drawn 600ms later, on top of it"
    )
    assert got["underneath"] is True, (
        "the pointer sitting over the covered row re-armed the card under the menu"
    )
    assert got["stillUp"] is True, "the menu did not survive its own row being hovered"
    assert got["afterwards"] is True, (
        "the card never came back after the menu closed — the rule is 'not while "
        "the menu is up', not 'not again'"
    )


# The half of the rule the test above cannot reach, because it never puts the
# card in the one state that has its own way out of being hidden.
#
# `cardResizing` is set rather than dragged for. The grip is only appended when
# the card's document overflows its box (`fitCardGrip`, `shell.py`), so whether
# there is a handle to drag at all depends on which row this corpus happens to
# put second — and a real drag is a pointer capture and a `pointermove` stream
# that a script cannot synthesise trustworthily anyway. The flag IS the state:
# it is what `hideCardNow` reads, and it is set on exactly one line of the
# drag's own `pointerdown`.
_MID_DRAG = """
const row = menuRows()[1];
const held = DATA.rows[row.dataset.id];
showCard(held, 300, 300);
const drawn = !CARD.hidden;
cardResizing = true;
rightOn(row, 300, 300);
return {drawn, hidden: CARD.hidden, open: popIsOpen(), resizing: cardResizing};
"""


def test_a_right_press_during_a_grip_drag_still_hides_the_card_and_opens_the_menu(
    index: Index, tmp_path: Path
):
    """The FIRST of the rule's three mechanisms, and the only one with a way out
    of itself: *"`hideCardNow()`, unconditionally — including through the
    `cardResizing` early-return, because a right-click during a grip drag must
    still get its menu."*

    `hideCardNow` returns without doing anything while the card's bottom edge is
    being dragged, which is right for its own callers — a card cannot be
    dismissed by the gesture that is resizing it. It is wrong for this one. So
    `cardYields` (`shell.py`) hides the card itself rather than calling it, and
    the failure that costs is invisible to every other test in this file: written
    as a bare `hideCardNow()` it passes all six assertions above, and leaves a
    card sitting over the menu for the whole of a drag. Driven both ways in
    headless Chrome on 2026-09-18 — with the bare call the card measured
    `hidden: false` under an open menu.

    **`cardResizing` is still true afterwards, and that assertion is the point of
    the third one.** `cardYields` deliberately does not clear it: the drag's own
    `pointerup`/`pointercancel` owns that, and a function that cleared it here
    would be guessing about the end of a gesture it cannot see — a guess whose
    symptom is a card that hides itself out from under a pointer still holding
    its handle.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "middrag.html",
        1200,
        _OPENING + _MID_DRAG,
    )

    assert got["drawn"] is True, "no card was drawn at all, so nothing here is being dismissed"
    assert got["hidden"] is True, (
        "the card stayed up over the menu because it believed it was being "
        "resized — `cardYields` went through `hideCardNow`, whose `cardResizing` "
        "early return is the one thing this half of the rule exists to bypass"
    )
    assert got["open"] is True, (
        "a right press during a grip drag opened no menu, which is the gesture "
        "the bypass is written for"
    )
    assert got["resizing"] is True, (
        "`cardYields` cleared `cardResizing`, so it has decided a drag it cannot "
        "see is over; the drag's own pointerup is what ends it"
    )


# --------------------------------------------------------------------------- #
# Escape, which five things on the table answer to
# --------------------------------------------------------------------------- #


_ESCAPE = """
const editable = document.querySelector('tbody tr[data-id] td.edit[data-record]');
if (!editable) throw new Error('no editable cell: this is not a writer\\'s table');
// The page's own bulk selection, made through the page's own function — `pick`
// ends in `draw()`, so everything is found again after it.
pick(editable, false);
const picked = PICKED.size;
const row = menuRows().find(tr => tr.dataset.id === editable.dataset.record);
const cell = row.querySelector('td[data-col="title"]');
cell.focus();
rightOn(row, 300, 300);
const opened = popIsOpen();
const focused = document.activeElement.dataset.kind;
const kinds = kindsInTheMenu();
pressKey('Escape');
return {picked, opened, focused, kinds, closed: !popIsOpen(), kept: PICKED.size,
        back: document.activeElement === cell};
"""


def test_escape_in_the_menu_does_not_discard_the_bulk_selection(index: Index, tmp_path: Path):
    """**The most important single test in this cut.**

    Escape means five things on the table. Four are routed around structurally —
    they are bound on the tbody, on a cell editor, on the suggestion list inside
    one and on `#askfor`, and a box parked on `document.body` is inside none of
    them. The fifth is `addEventListener('keydown', …)` on the DOCUMENT, and
    everything on the page is below that: an Escape out of the menu bubbled into
    it and dropped the reader's whole selection.

    So the box's own handler ends in `stopPropagation()`, and this is the test
    that says so. It fails if that call goes, and it fails if the box is ever
    mounted inside the tbody and the other four stop being structural.

    The selection is made with no cell editor open on purpose: the document
    handler returns early while one is, so a test that left an editor open would
    pass with the defect in place.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "escape.html",
        1200,
        _OPENING + _ESCAPE,
    )

    assert got["picked"] >= 1, "nothing was selected, so this test cannot see the defect"
    assert got["opened"] is True, "no menu opened, so nothing was escaped out of"
    assert got["focused"] == got["kinds"][0], (
        "the menu did not take the keyboard, so its own Escape handler never sees the key"
    )
    assert got["closed"] is True, "Escape did not close the menu"
    assert got["kept"] == got["picked"], (
        f"Escape out of the menu took the selection with it: {got['picked']} cells "
        f"before, {got['kept']} after"
    )
    assert got["back"] is True, (
        "the keyboard was left on `<body>`, so the next Tab starts from the top of the page"
    )


# --------------------------------------------------------------------------- #
# The six ways it dies
# --------------------------------------------------------------------------- #


_DISMISSAL = """
const open = () => { rightOn(menuRows()[1], 260, 300); return popIsOpen(); };
const seen = {};
seen.opened = open();
// A press INSIDE the box is the press that chooses an item, not a dismissal.
POP.children[0].dispatchEvent(
  new PointerEvent('pointerdown', {bubbles: true, clientX: 262, clientY: 305}));
seen.inside = popIsOpen();
document.body.dispatchEvent(
  new PointerEvent('pointerdown', {bubbles: true, clientX: 5, clientY: 5}));
seen.outside = popIsOpen();
// Closed, and gone: `[hidden]` loses to `#pop { display: flex }` on cascade
// origin alone.
seen.display = getComputedStyle(POP).display;
seen.height = POP.getBoundingClientRect().height;

open();
// Non-bubbling, on the box the rows scroll inside. A listener on `window`
// without capture never hears this one.
document.querySelector('.table-scroll').dispatchEvent(new Event('scroll'));
seen.scrolled = popIsOpen();
open();
dispatchEvent(new Event('resize'));
seen.resized = popIsOpen();
open();
dispatchEvent(new CustomEvent('openproj:filter'));
seen.filtered = popIsOpen();
open();
// **The sha is the whole of the difference.** That event fires in a `finally` on
// every write path in this app, refusals included, because the shell counts it
// against `openproj:writing` — so a detail of null is a write that did NOT move
// the plan, and this menu's own refusals arrive here.
dispatchEvent(new CustomEvent('openproj:wrote', {detail: null}));
seen.refused = popIsOpen();
dispatchEvent(new CustomEvent('openproj:wrote', {detail: 'c0ffee1'}));
seen.wrote = popIsOpen();
return seen;
"""


def test_the_menu_dies_on_the_five_signals_that_are_not_escape(index: Index, tmp_path: Path):
    """The menu never moves once placed; it only dies. This is why it is never
    anchored to a row: the table's `draw()` replaces the whole tbody, so a box
    anchored to one is a box pointing at nothing a moment later.

    Each signal is sent the way the page produces it. The scroll is dispatched
    on `.table-scroll` and does not bubble — which is the point, because that is
    the box the rows scroll inside and a `window` listener would never hear it.

    And the closed box is measured rather than asked. `.drawmenu` reported
    itself closed at 162x10 for the same reason a box here would: the UA's
    `[hidden] { display: none }` loses to any author rule that sets `display`,
    on origin alone, regardless of specificity. This box keeps its items when it
    closes, so it would not even collapse to its own padding — it would stay the
    whole menu, over the page, eating every press.

    Five of the six, because Escape is the sixth and it has a test of its own
    above — what it has to answer there is not "did the box close" but what else
    on the page heard the key.

    `openproj:wrote` is asked twice, and the two answers are opposite. What it is
    for is the same thing `openproj:filter` is for one line above: a tbody
    replaced under a box that is not anchored to anything in it. But that event
    fires in a `finally` on EVERY write path here, refusals included — it has to,
    because the shell counts it against `openproj:writing` and one held-back
    event stops the moved-banner for ever. Cut 2 bound `popClose` to it bare,
    which was right while nothing in this menu wrote; from cut 3 a bare close
    draws a refusal and wipes it half a tick later. So a sha means the plan moved
    and this box must die, and no sha means nothing moved and the reason it gives
    stays on screen. The refusal's own half of that is
    `test_a_refusal_leaves_the_menu_up_saying_what_the_server_said`.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "dismissal.html",
        1200,
        _OPENING + _DISMISSAL,
    )

    assert got["opened"] is True, "no menu opened, so none of the closes below mean anything"
    assert got["inside"] is True, "a press inside the box closed it before it could choose"
    assert got["outside"] is False, "a press outside the box left it up"
    assert got["display"] == "none", (
        f"a closed menu still computes `display: {got['display']}` and is {got['height']}px "
        "tall, over the page, taking every press"
    )
    assert got["height"] == 0
    assert got["scrolled"] is False, "the menu survived the rows scrolling out from under it"
    assert got["resized"] is False, "the menu survived the window changing size"
    assert got["filtered"] is False, "the menu survived the rows being redrawn under it"
    assert got["refused"] is True, (
        "the menu closed on an `openproj:wrote` carrying no sha — nothing was "
        "committed, and from cut 3 that event is what this menu's own refusals "
        "fire: the box goes down over the reason it has just drawn"
    )
    assert got["wrote"] is False, (
        "the menu survived a write landing, so it is still pointing at a row in a "
        "tbody that has been replaced since it opened"
    )


# --------------------------------------------------------------------------- #
# What is in the box
# --------------------------------------------------------------------------- #


_ITEMS = """
const row = menuRows()[1];
rightOn(row, 300, 300);
const tab = POP.querySelector('[data-kind="open-tab"]');
return {
  open: popIsOpen(),
  id: row.dataset.id,
  title: DATA.rows[row.dataset.id].title,
  kinds: kindsInTheMenu(),
  tabs: tabsInTheMenu(),
  focused: document.activeElement.dataset.kind,
  role: POP.getAttribute('role'),
  label: POP.getAttribute('aria-label'),
  roles: [...POP.children].map(item => item.getAttribute('role')),
  tags: [...POP.children].map(item => item.tagName),
  refused: [...POP.children].filter(item => item.hasAttribute('aria-disabled')).length,
  tab: {href: tab.getAttribute('href'), target: tab.target, rel: tab.rel},
};
"""


def test_a_reader_is_offered_what_only_looks_and_a_writer_the_whole_list(
    index: Index, tmp_path: Path
):
    """Cut 2 asserted these two pages were identical, and said in as many words
    that the first write item would show up as that assertion failing — "which is
    the moment to decide what a signed-out reader sees instead". This is that
    moment, and the decision is drawn here.

    **The write half is behind `may()`, asked on every open and never cached.** A
    page that learns it is signed out does not go on offering writes until
    somebody reloads. So a reader is offered nothing that PATCHes: not a refused
    `Status`, not an `Editing is unavailable here`, nothing. A control that
    disappears usually teaches nothing about why, and the exception is the one
    where the answer is "not with these credentials" — the sign-in is in the nav
    and it is the whole of the news.

    **A view's own items are not behind that gate**, which is deliberate and is
    each host's to decide: `Focus subtree` moves nothing and belongs to a reader
    as much as to a writer, while the graph's `Add dependency from here` exists
    only where there is a commit bar to save it with. That split is asserted from
    the graph's side in
    `test_the_graphs_own_item_puts_the_canvas_into_connecting_mode_at_that_node`.

    The shape is asserted beside the list, because the shape is the contract the
    rest of this cut is built against. `Open in new tab` is a real `<a
    target="_blank">` and not a `run()` — so middle-click works, and so does the
    browser's own menu on it, which is the one right press inside this box that
    is nobody's business but the browser's.
    """
    got = {
        "writer": measured_in(
            chrome(),
            a_writers_table(index),
            tmp_path / "writer.html",
            1200,
            _OPENING + _ITEMS,
        ),
        "reader": measured_in(
            chrome(),
            render_table(index, ROUTES, base_commit=HEAD, may_write=False),
            tmp_path / "reader.html",
            1200,
            _OPENING + _ITEMS,
        ),
    }

    for who, seen in got.items():
        assert seen["open"] is True, f"the {who}'s page opened no menu"
        assert seen["kinds"][-3:] == READER_ITEMS, (
            f"the {who} was offered {seen['kinds']}, which does not end in the three "
            "items that only look"
        )
        assert seen["refused"] == 0, (
            f"the {who} was offered a refused item on a row that is inside something, "
            f"holds records and has a ladder: {seen['kinds']}"
        )
        assert seen["role"] == "menu"
        assert seen["roles"] == ["menuitem"] * len(seen["kinds"]), seen["roles"]
        # A button, a link, a button. The link is the one that must not be a
        # button: an `href` is what makes middle-click and the browser's own
        # menu work on it.
        assert seen["tags"][-3:] == ["BUTTON", "A", "BUTTON"], seen["tags"]
        assert seen["tab"] == {
            "href": f"/detail/{seen['id']}",
            "target": "_blank",
            "rel": "noopener",
        }, seen["tab"]
        assert seen["label"] == f"Actions for {seen['title']}"
        # Exactly one item in the Tab sequence, and it is the one with focus, so
        # Tab leaves the menu and the arrows are what walk it.
        assert seen["tabs"] == [0, *[-1] * (len(seen["kinds"]) - 1)], seen["tabs"]
        assert seen["focused"] == seen["kinds"][0]

    assert got["writer"]["kinds"][:3] == WRITE_ITEMS, got["writer"]["kinds"]
    for writes in (*WRITE_ITEMS, "no-schema"):
        assert writes not in got["reader"]["kinds"], (
            f"a signed-out reader is offered {writes!r}: {got['reader']['kinds']}"
        )
    assert got["reader"]["kinds"] != got["writer"]["kinds"], (
        "a reader and a writer are offered the same menu in a cut where three items "
        "change the plan"
    )


# --------------------------------------------------------------------------- #
# The graph
# --------------------------------------------------------------------------- #


# A node's data IS its row on this view — there is no `DATA` here at all, which
# is how the first version of the graph's card drew nothing whatsoever. The event
# is emitted through cytoscape rather than dispatched at the canvas, which is how
# `test_card.py` asks the graph its questions: the canvas is painted pixels and
# the node is the thing under the pointer.
_A_NODE = """
const node = cy.nodes().filter(one => !one.isParent())[0];
if (!node) return {error: 'the graph drew no leaf node'};
const press = () => ({clientX: 420, clientY: 300, shiftKey: false, preventDefault() {}});
const rightOnTheNode = () =>
  node.emit({type: 'cxttap', position: node.position(), originalEvent: press()});
rightOnTheNode();
const box = POP.getBoundingClientRect();
const opened = {open: popIsOpen(), about: popAbout(), left: box.left, top: box.top,
                label: POP.getAttribute('aria-label'),
                kinds: [...POP.children].map(item => item.dataset.kind)};
// And the same press with an edge half drawn. `connecting` is set the way the
// Edit dependencies button sets it and nothing else reads it on the way in.
popClose();
connecting = true;
rightOnTheNode();
return {...opened, whileConnecting: popIsOpen(), id: node.id(), title: node.data('title')};
"""


def test_a_right_press_on_a_graph_node_opens_the_menu_for_that_node(index: Index, tmp_path: Path):
    """`cxttap` on nodes, which cytoscape fires for a right-click — and, free and
    harmlessly, for a two-finger tap.

    The coordinates are the ones worth watching here. Cytoscape's event carries
    its own canvas position, and the box is `position: fixed` against the
    viewport; a menu placed with the wrong pair of numbers opens somewhere near
    the node on one zoom level and off the canvas on the next.

    **And no menu at all while an edge is being drawn**, which is a decision this
    view made on its own and is therefore the one that can be quietly reverted.
    It is `dbltap`'s guard for `dbltap`'s reason: `Open` navigates, and a canvas
    holding drawn-but-unsaved edges loses them without a word — while the pointer
    is mid-gesture, picking a blocker and then the thing that waits for it, and a
    box opening under it covers the node being aimed at. The hover card already
    declines here for the second half of that.
    """
    got = measured_in(
        chrome(),
        render_graph(index, ROUTES, base_commit=HEAD, may_write=True),
        tmp_path / "graph.html",
        1200,
        _A_NODE,
    )

    assert not got.get("error"), got
    assert got["open"] is True, "a right press on a node opened no menu"
    assert got["about"] == got["id"], (
        f"the menu is about {got['about']} and the press was on {got['id']}"
    )
    assert got["label"] == f"Actions for {got['title']}"
    assert got["kinds"][:3] == WRITE_ITEMS, got["kinds"]
    assert got["kinds"][-3:] == READER_ITEMS, got["kinds"]
    assert abs(got["left"] - (420 + GUTTER)) <= 2 and abs(got["top"] - (300 + GUTTER)) <= 2, (
        f"the box opened at ({got['left']}, {got['top']}) for a press at (420, 300) — "
        "the pointer's own coordinates are the ones a fixed box is placed with"
    )
    assert got["whileConnecting"] is False, (
        "a right press on a node opened the menu while an edge was being drawn: "
        "`Open` navigates away from every unsaved edge on the canvas, and the box "
        "covers the node the pointer was aiming at"
    )


# Two listeners on `#cy`, added after the page's two, which is what makes them
# witnesses rather than participants:
#
#   - the CAPTURE one runs after `pop.py`'s host page's own capture listener on
#     the same element, so it reports what that listener left behind;
#   - the BUBBLE one runs after cytoscape's `registerBinding(container,
#     'contextmenu', e => e.preventDefault())`, so it reports whether the event
#     ever reached the bubble phase at all and what was done to it there.
#
# Each press appends, and the list is emptied between presses, so "never fired"
# is an empty list and not a stale answer from the press before.
_WATCH_THE_CANVAS = """
(() => {
  window.__seen = {capture: [], bubble: []};
  const canvas = document.getElementById('cy');
  const note = where => event => window.__seen[where].push(
    {shift: event.shiftKey, prevented: event.defaultPrevented});
  canvas.addEventListener('contextmenu', note('capture'), true);
  canvas.addEventListener('contextmenu', note('bubble'));
  return cy.nodes().length;
})()
"""

# A leaf node's own pixels, in the viewport's coordinates: `renderedPosition` is
# relative to the container and `#cy` sits below a nav, a filter row and a commit
# bar. Read immediately before the press, because nothing between the two moves
# the canvas.
_WHERE_A_NODE_IS = """
(() => {
  const node = cy.nodes().filter(one => !one.isParent())[0];
  const spot = node.renderedPosition();
  const box = document.getElementById('cy').getBoundingClientRect();
  return [Math.round(box.left + spot.x), Math.round(box.top + spot.y)];
})()
"""

_WHAT_THE_CANVAS_SAW = "(() => ({seen: window.__seen, open: popIsOpen()}))()"


def test_shift_and_right_together_reach_the_browser_through_the_canvas(
    index: Index, tmp_path: Path
):
    """**Shift+right-click falls through on the graph too, and the graph is the
    only view where that took a mechanism.**

    The table's and the timeline's are one line each — `if (event.shiftKey)
    return;` — and the tests above and below cover them by opening no menu.
    Cytoscape's canvas is different: it binds `registerBinding(e.container,
    'contextmenu', e => e.preventDefault())`, so the browser's own menu is eaten
    before anything of ours is asked. What the page does about that is a single
    capture-phase listener on the same element, and **deleting it leaves every
    other test in this file green** while Inspect, Copy link address and Open in
    new window go from every node on the canvas.

    So the claim is put the only way a headless run can put it. A browser's own
    menu is not in the DOM and cannot be photographed; what a page decides about
    one is whether `preventDefault()` runs, and the listener under test works by
    making sure cytoscape's never does. Two witnesses on the same element say
    that between them:

    - shift held, the capture witness fires and the bubble witness **never runs
      at all** — the bubble phase was cut off, so nothing prevented anything and
      the event reaches the end of its life intact;
    - no shift, the bubble witness fires with `defaultPrevented` true, which is
      cytoscape eating the menu exactly as it has since before any of this.

    The second press is the control and it is not decoration: without it a page
    that stopped every `contextmenu` in capture, shift or no shift, passes the
    first three assertions. Driven with the listener deleted on 2026-09-18 — the
    shifted press then reached the bubble witness carrying `prevented: true`.

    Trusted presses, because `preventDefault()` on a `MouseEvent` a script builds
    suppresses a default action that was never going to run.
    """
    where = tmp_path / "shiftgraph.html"
    where.write_text(render_graph(index, ROUTES, base_commit=HEAD, may_write=True))
    with _devtools(
        chrome(), where.as_uri(), tmp_path / "profile", ("--window-size=1280,900",)
    ) as (call, _said):
        # ELK's layout is asynchronous and `relayout()` ends in `cy.fit()`, so a
        # fixed sleep is either a guess that is too short on CI or a guess that
        # is too long here. The nodes existing is the condition; the second's
        # wait afterwards is the fit settling, which moves what is under the
        # press rather than whether there is anything under it.
        drew = None
        for _ in range(60):
            drew = _evaluated(call, "typeof cy !== 'undefined' && cy.nodes().length > 0", True)
            if drew:
                break
            time.sleep(0.25)
        assert drew, "the graph drew no nodes in fifteen seconds"
        time.sleep(1.5)
        nodes = _evaluated(call, _WATCH_THE_CANVAS)
        at = _evaluated(call, _WHERE_A_NODE_IS)
        assert isinstance(at, list), at

        _evaluated(call, "window.__seen = {capture: [], bubble: []}; popClose(); true")
        _right_press(call, at, shift=True)
        shifted = _evaluated(call, _WHAT_THE_CANVAS_SAW)

        _evaluated(call, "window.__seen = {capture: [], bubble: []}; popClose(); true")
        _right_press(call, at, shift=False)
        plain = _evaluated(call, _WHAT_THE_CANVAS_SAW)

    assert nodes, "the canvas holds no nodes, so nothing here was pressed"
    assert shifted["seen"]["capture"], "the shifted press produced no contextmenu event at all"
    assert shifted["seen"]["capture"][0]["shift"] is True, "the shift key did not reach the page"
    assert shifted["seen"]["capture"][0]["prevented"] is False, (
        "something had already suppressed the browser's own menu before the "
        "capture phase on `#cy` had finished"
    )
    assert shifted["seen"]["bubble"] == [], (
        "a shifted press reached the bubble phase on `#cy`, where cytoscape's own "
        f"listener is: {shifted['seen']['bubble']}. The capture-phase "
        "`stopPropagation` is gone, and with it every browser menu on the canvas"
    )
    assert shifted["open"] is False, "shift+right-click on a node opened our menu"
    assert plain["seen"]["bubble"], (
        "an unmodified press did not reach the bubble phase either, so this page "
        "stops every contextmenu in capture and the assertions above are about nothing"
    )
    assert plain["seen"]["bubble"][0]["prevented"] is True, (
        "the browser's own menu was left to open over the canvas on an unmodified "
        "press, which is the press our menu answers"
    )
    assert plain["open"] is True, (
        "the unmodified press opened no menu of ours, so it did not land on a node "
        "and the contrast above is between two presses on empty ground"
    )


# --------------------------------------------------------------------------- #
# The timeline, which is two halves of one row
# --------------------------------------------------------------------------- #


# A row on this page is a `<rect>` in the plot and a `.row` in the label column
# beside it, and the two are in different subtrees: one is inside the SVG and one
# is not. `.tl` holds both, which is why one listener can answer for them, and
# the label half is the half a table-shaped harness can never reach.
#
# The rect is found by walking rather than by a selector, because an id is
# `pitch-0b0001` in this corpus and a record id is a plan author's string: the
# one thing that must not decide whether this test runs is whether it needs
# `CSS.escape`.
_A_TIMELINE_ROW = """
const labels = [...document.querySelectorAll('.labels .row[data-id]')];
if (labels.length < 2) return {error: 'the chart drew fewer than two rows'};
const barFor = id => [...document.querySelectorAll('rect[data-id]')]
  .find(rect => rect.dataset.id === id);
const pressed = labels[0], neighbour = labels[1];
const bar = barFor(pressed.dataset.id);
if (!bar) return {error: 'the first labelled row has no bar beside it'};
const rest = ms => new Promise(done => setTimeout(done, ms));
const rightOn = (target, x, y, shift) => {
  const event = new MouseEvent('contextmenu', {bubbles: true, cancelable: true,
    button: 2, buttons: 2, clientX: x, clientY: y, shiftKey: !!shift});
  target.dispatchEvent(event);
  return {open: popIsOpen(), about: popAbout(), prevented: event.defaultPrevented};
};
const andAgain = (target, x, y, shift) => {
  const seen = rightOn(target, x, y, shift);
  popClose();
  return seen;
};
const seen = {id: pressed.dataset.id, other: neighbour.dataset.id};
seen.label = andAgain(pressed, 300, 300);
seen.bar = andAgain(bar, 320, 300);
seen.labelShifted = andAgain(pressed, 300, 300, true);
seen.barShifted = andAgain(bar, 320, 300, true);

// The menu up, and the pointer then crossing a DIFFERENT bar — which is the one
// thing a reader's pointer does on this page while a box is open over it.
rightOn(pressed, 300, 300);
barFor(neighbour.dataset.id).dispatchEvent(
  new PointerEvent('pointerover', {bubbles: true, clientX: 340, clientY: 340}));
await rest(900);
seen.hovered = {card: CARD.hidden, menu: popIsOpen()};

// And the keyboard reaching a row, which is this page's own way to a card and
// the one path in the app that draws one without going through `queueCard`.
const link = neighbour.querySelector('a');
link.focus({preventScroll: true});
await rest(50);
seen.focused = {card: CARD.hidden, menu: popIsOpen()};

// The same focus with no menu up. Without this the two answers above are also
// what a page whose label column draws no card at all would report.
popClose();
link.blur();
link.focus({preventScroll: true});
await rest(50);
seen.control = {card: CARD.hidden};
return seen;
"""


def test_the_timelines_menu_opens_off_a_label_as_well_as_a_bar(index: Index, tmp_path: Path):
    """The timeline is the reader's view — `render_timeline` takes neither
    `may_write` nor `base_commit` — and until now it appeared in this file only
    as a substring of a rendered page. Two things ship untested behind that.

    **The label column is outside the SVG.** `plot` is `.tl`, and its listener
    closes on `rect[data-id], .row[data-id]` because a row on this page is drawn
    twice: a bar in the plot and a label beside it. The label half is also the
    whole of the keyboard's route through the chart — the SVG anchors are
    `tabindex="-1"` deliberately — so dropping it costs a keyboard reader the
    menu entirely, and no table-shaped test can see it.

    **And `showTip`'s `popIsOpen()` guard.** `cardStandsDown` (`shell.py`) is
    read by `queueCard` and deliberately not by `showCard`, on the grounds that
    `showCard`'s other caller is a timeout `cardYields` has just cancelled. This
    page is the exception that reasoning names: focus on a label anchor calls
    `showCard` directly, and a label can take focus while the menu is up. So the
    focus is asked twice — once with a menu up and once without — because "the
    card stayed hidden" is also what a page that draws no card on focus reports.

    Both presses are untrusted on purpose and the shifted ones are the reason to
    say so: `defaultPrevented` on a script-built event is only a record of
    whether the page called `preventDefault()`, which is exactly the claim here.
    Whether a native menu then opens is the browser's, and it is the graph's test
    above that has to put that question to a real press.
    """
    got = measured_in(
        chrome(),
        render_timeline(index, ROUTES),
        tmp_path / "timeline.html",
        1280,
        _A_TIMELINE_ROW,
        patience=3000,
    )

    assert not got.get("error"), got
    assert got["id"] != got["other"], got
    for half, seen in (("label", got["label"]), ("bar", got["bar"])):
        assert seen["open"] is True, f"a right press on the {half} opened no menu"
        assert seen["about"] == got["id"], (
            f"the {half} opened a menu about {seen['about']} and it was pressed for {got['id']}"
        )
        assert seen["prevented"] is True, (
            f"the page left the browser's own menu to open over the {half}"
        )
    for half, seen in (("label", got["labelShifted"]), ("bar", got["barShifted"])):
        assert seen["open"] is False, f"shift+right-click on the {half} opened our menu"
        assert seen["prevented"] is False, (
            f"the page suppressed the browser's own menu on a shifted press on the {half}, "
            "which is the one press that exists to reach it"
        )

    assert got["hovered"]["card"] is True, (
        "the pointer crossing another bar drew a hover card while the menu was up"
    )
    assert got["hovered"]["menu"] is True, "the menu did not survive a bar being hovered"
    assert got["focused"]["card"] is True, (
        "focusing a label drew a card over the open menu: `showCard` does not consult "
        "`cardStandsDown`, and `showTip`'s `popIsOpen()` guard is what stands in for it"
    )
    assert got["focused"]["menu"] is True, "the menu did not survive a label taking focus"
    assert got["control"]["card"] is False, (
        "focusing a label with no menu up drew no card either, so the two answers "
        "above are about a page that has no card on this path at all"
    )


# --------------------------------------------------------------------------- #
# The keyboard
# --------------------------------------------------------------------------- #


# `ContextMenu` and Shift+F10 deliver a `contextmenu` event that bubbles like any
# other, so the menu comes free — but the coordinates do not. This is Firefox's
# report, 0,0, which is the shape with nothing in it to place against.
_MENU_KEY = """
const row = menuRows()[1];
const cell = row.querySelector('td[data-col="title"]');
if (!cell.hasAttribute('tabindex')) return {error: 'the title cell is not a keyboard stop'};
cell.focus();
const rect = cell.getBoundingClientRect();
cell.dispatchEvent(new MouseEvent('contextmenu',
  {bubbles: true, cancelable: true, clientX: 0, clientY: 0}));
const box = POP.getBoundingClientRect();
const first = document.activeElement.dataset.kind;
const opening = tabsInTheMenu();
pressKey('ArrowDown');
const second = document.activeElement.dataset.kind;
pressKey('ArrowUp');
pressKey('ArrowUp');
const wrapped = document.activeElement.dataset.kind;
pressKey('End');
const end = document.activeElement.dataset.kind;
pressKey('Home');
const home = document.activeElement.dataset.kind;
return {open: popIsOpen(), kinds: kindsInTheMenu(), first, second, wrapped, end, home,
        opening, roving: tabsInTheMenu(),
        box: {left: box.left, top: box.top},
        cell: {left: rect.left, top: rect.top, bottom: rect.bottom}};
"""


def test_the_menu_key_opens_the_menu_beside_whatever_has_focus(index: Index, tmp_path: Path):
    """Without a fallback the menu key opens the box in the top-left corner — and
    on the table, where a roving-tabindex grid is the whole keyboard story, that
    is the most likely path a keyboard reader takes.

    So the fallback is `document.activeElement.getBoundingClientRect()`, and
    this asks for it with the coordinates Firefox reports: 0,0. The row is
    checked to be well away from the corner first, because "beside the focused
    cell" and "in the corner" are only different answers when the cell is
    somewhere else.

    The walk afterwards is the other half of a keyboard menu: the arrows wrap,
    Home and End go to the ends, and exactly one item is ever in the Tab
    sequence — so Tab leaves the menu instead of walking it.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "menukey.html",
        1200,
        _OPENING + _MENU_KEY,
    )

    assert not got.get("error"), got
    assert got["open"] is True, "the menu key opened nothing"
    assert got["cell"]["top"] > 40 and got["cell"]["left"] > 20, (
        f"the focused cell is at {got['cell']}, which is near enough to the corner "
        "that this test cannot tell the fallback from its absence"
    )
    assert abs(got["box"]["left"] - (got["cell"]["left"] + GUTTER)) <= 2, (
        f"the box opened at x={got['box']['left']} for a cell at "
        f"x={got['cell']['left']} — 0,0 was taken at face value"
    )
    assert abs(got["box"]["top"] - (got["cell"]["bottom"] + GUTTER)) <= 2, (
        f"the box opened at y={got['box']['top']} rather than under the cell's "
        f"bottom edge at y={got['cell']['bottom']}"
    )
    assert got["first"] == got["kinds"][0], "the menu opened without taking the keyboard"
    assert got["opening"] == [0, *[-1] * (len(got["kinds"]) - 1)], got["opening"]
    assert got["second"] == got["kinds"][1], "ArrowDown did not move"
    assert got["wrapped"] == got["kinds"][-1], (
        "ArrowUp off the top did not wrap round to the last item"
    )
    assert got["end"] == got["kinds"][-1] and got["home"] == got["kinds"][0]
    assert got["roving"] == [0, *[-1] * (len(got["kinds"]) - 1)], (
        f"the roving tabindex is {got['roving']}: more than one item is in the Tab sequence"
    )


# --------------------------------------------------------------------------- #
# Copy link, which has to answer even when the clipboard does not
# --------------------------------------------------------------------------- #


_COPY = """
const row = menuRows()[1];
rightOn(row, 300, 300);
POP.querySelector('[data-kind="copy-link"]').click();
// 600ms is the backstop the announcement cannot outlive; 800 is that and a
// margin.
await rest(800);
const where = document.getElementById('state') || document.getElementById('announce');
return {said: where.textContent, id: row.dataset.id, closed: !popIsOpen()};
"""


def test_copy_link_says_what_it_did_either_way(index: Index, tmp_path: Path):
    """Measured on 2026-09-18, and it is the opposite of what the design assumed:
    on a `file://` page in headless Chrome `isSecureContext` is TRUE and
    `navigator.clipboard.writeText` exists, so a feature test passes — and the
    promise then neither resolves nor rejects. A `.catch()` fallback never runs
    and "announce either way" quietly becomes announce neither way. The first
    version of this item genuinely announced nothing.

    That is the defect this test is written for, so the assertion is on the live
    region and not on the clipboard: what is being asked is whether a reader who
    pressed the item is told anything at all. Either sentence is a pass, and both
    carry the link — a refusal that says only "could not copy" has taken the
    answer away as well as the clipboard.
    """
    got = measured_in(
        chrome(),
        a_writers_table(index),
        tmp_path / "copy.html",
        1200,
        _OPENING + _COPY,
        patience=2500,
    )

    assert got["said"], (
        "pressing Copy link announced nothing at all: the clipboard promise never "
        "settled and nothing was waiting behind it"
    )
    assert got["id"] in got["said"], (
        f"the announcement is {got['said']!r}, which does not carry the link the "
        "reader asked for"
    )
    assert got["closed"] is True, "a pressed item left the menu up"


# A guard on the harness above rather than on the app: these scripts all name the
# row they press by index, and an empty table would make every assertion in this
# file true of nothing. Asked of the payload the page actually ships.
def test_the_table_under_test_has_rows_to_press(index: Index):
    """`menuRows()[1]` is the middle of three, and a corpus that drew one row
    would answer `undefined` there — which surfaces as "the page reported
    nothing", the same words a page that failed to lay out produces.

    Asked of `_payload`, which is what the page ships its rows as, rather than of
    the plan: a row dropped between the index and the payload is a row that is
    not on the table, and that is the thing being pressed.
    """
    rows = _payload(index)["rows"]
    assert len(rows) >= 3, (
        f"the demo corpus draws {len(rows)} rows, and every browser test here presses the second"
    )


# --------------------------------------------------------------------------- #
# Cut 3: the menu writes
#
# Everything below drives the shipped script in a real browser, because every
# claim here is about what the page SENT and what it did with the answer — and
# both of those live in a listener, a promise and a `replaceChildren` that appear
# in no rendered file.
# --------------------------------------------------------------------------- #


# How an item is read now, and it is not how cut 2 read one. A control is up to
# three spans — `.popglyph`, `.poptext`, `.popmark` — so `control.textContent` is
# `↗Shaping›` and the word is `.poptext` alone.
#
# View-agnostic on purpose: the graph has no `DATA` and no `#base`, and half of
# these questions are asked of it.
_READERS = """
const popKinds = () => popControls().map(one => one.dataset.kind);
const partIn = (one, part) => {
  const found = one.querySelector('.' + part);
  return found ? found.textContent : '';
};
const wordIn = one => partIn(one, 'poptext');
const itemIn = kind => POP.querySelector('.popitem[data-kind="' + kind + '"]');
// An item this VIEW added through `extras`, found by its word. A host's own item
// has no slug in any contract — `data-kind` is stable for the items `pop.py`
// builds — and the wording is what `design/context-menus.md` fixes.
const extraIn = word => popControls().find(one => wordIn(one) === word);
const said = () =>
  (document.getElementById('state') || document.getElementById('announce')).textContent;
"""


# The table with a server behind it, stubbed at `fetch`.
#
# **Stubbed and not served**, because what these tests ask is what the page put
# on the wire and what it did with what came back — and a `file://` page has
# nowhere to send it. Both routes one menu write touches are answered: the PATCH
# itself, and the `/api/table.json` re-read the table's `wrote()` does behind it.
_WRITING = """
// Said here rather than met as `Cannot read properties of null` four lines into
// whichever question asked first. A table whose `_pop_js(links, index)` lost its
// second argument draws one refused item and no write half at all, and the
// harness's own words for that are "the page reported nothing".
if (!POP_SCHEMA)
  return {error: 'this page carries no POP_SCHEMA: `_pop_js(links, index)` is what '
                 + 'bakes it, and without it the menu has no write half to ask about'};
const SENT = [];
// What this stub has taken, per record. The re-read answers the plan AS IT NOW
// IS, the way the real route does: without that a host whose `wrote()` never
// re-read anything would pass every assertion below, because the rows it went on
// showing would be the rows this stub kept handing back.
const WRITTEN = {};
let COMMITS = 0;
// How many of the commits this stub has answered with are only on this
// instance. The re-read has to report the same thing the write did or the two
// halves of the stub contradict each other: `settleMarks` reads `unpushed === 0`
// as "the remote holds everything" and clears the mark the write had just
// earned, which is a stubbed server saying `pushed: false` and `nothing is
// unpushed` about the same commit.
let UNPUSHED = 0;
// A fresh sha per write, so `base_commit` can be asserted to MOVE: the page that
// does not advance `#base` collides with the commit it just made, and one that
// advances it to a constant cannot be told from one that does.
let ANSWER = () => ({status: 200,
                     body: {outcome: 'committed', commit: 'c0ffee' + (++COMMITS), pushed: true}});
window.fetch = async (url, options) => {
  const asked = options || {};
  const seen = {url: String(url), method: asked.method || 'GET',
                body: asked.body ? JSON.parse(asked.body) : null};
  SENT.push(seen);
  if (seen.url.includes('/api/table.json')) {
    const rows = {};
    for (const [id, row] of Object.entries(DATA.rows))
      rows[id] = Object.assign({}, row, WRITTEN[id] || {});
    return new Response(
      JSON.stringify({rows: rows, problems: [], parked: [], unpushed: UNPUSHED}),
      {status: 200, headers: {'content-type': 'application/json'}});
  }
  const about = decodeURIComponent((seen.url.split('/api/record/')[1] || ''));
  const answer = await ANSWER(seen);
  if (answer.status === 200) {
    WRITTEN[about] = Object.assign({}, WRITTEN[about] || {}, seen.body.fields);
    if (answer.body.pushed === false) UNPUSHED += 1;
  }
  return new Response(JSON.stringify(answer.body),
                      {status: answer.status, headers: {'content-type': 'application/json'}});
};
const patches = () => SENT.filter(one => one.method === 'PATCH');

// The pair the shell counts against each other. One `openproj:wrote` for every
// `openproj:writing` — including on a refusal, or one held-back event stops the
// moved-banner for ever — and its `detail` is the sha, or null when nothing was
// committed.
const beats = {writing: 0, wrote: []};
addEventListener('openproj:writing', () => { beats.writing += 1; });
addEventListener('openproj:wrote', event => { beats.wrote.push(event.detail || null); });
const beatsNow = () => ({writing: beats.writing, wrote: beats.wrote.slice()});

const baseNow = () => document.getElementById('base').value;
// A row with the shape a question needs, chosen from the payload rather than
// named. `seed/` is the demo and is free to be rewritten (see `demo_root`), so a
// test that names an id in it is a test a copy edit turns red.
const rowWhere = test => Object.values(DATA.rows).find(test);
const openOn = id => {
  const row = menuRows().find(tr => tr.dataset.id === id);
  if (!row) throw new Error('no row is drawn for ' + id);
  return rightOn(row, 300, 300);
};
"""


def _at_the_table(index: Index, where: Path, script: str, patience: int = 3000) -> dict:
    """One writer's table in Chrome, asked one question about the menu's writes."""
    return measured_in(
        chrome(),
        a_writers_table(index),
        where,
        1280,
        _OPENING + _READERS + _WRITING + script,
        patience=patience,
    )


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


_THE_LADDER = """
const row = rowWhere(one => one.kind === 'task' && one.status === 'ready');
if (!row) return {error: 'the corpus holds no ready task to move'};
openOn(row.id);
const top = popKinds();
itemIn('status').click();
const inside = popControls().map(one => ({
  kind: one.dataset.kind, role: one.getAttribute('role'),
  checked: one.getAttribute('aria-checked'), word: wordIn(one),
  glyph: partIn(one, 'popglyph'), mark: partIn(one, 'popmark'),
  haspopup: one.getAttribute('aria-haspopup')}));
const label = POP.getAttribute('aria-label');
const landed = document.activeElement.dataset.kind;
itemIn('status-shaping').click();
await rest(700);
return {id: row.id, title: row.title, was: row.status, ladder: POP_SCHEMA.statuses[row.kind],
        top, inside, label, landed, sent: patches(), closed: !popIsOpen(), said: said(),
        base: baseNow(), beats: beatsNow(), now: DATA.rows[row.id].status};
"""


def test_the_status_submenu_is_this_kinds_ladder_and_picking_one_writes_it(
    index: Index, tmp_path: Path
):
    """`Status ▸` drills into `RUNG[kind].statuses`, marks the rung the record is
    on, and writes the one that is picked.

    Three things are asserted about the drill that a list of slugs would not
    catch. The ladder is the MODEL's, so a menu that built its own vocabulary —
    the failure `HUMAN` exists to prevent, and which put `in_progress` beside "In
    progress" on one screen — shows up as a word that is not `HUMAN`'s. The
    marks are asserted apart: `•` on the current rung and the status glyph in
    front of every word, because they are drawn in two different spans for two
    different reasons and a menu that drew the tick in the glyph's slot would
    look right in a screenshot and read as two ticks to anybody listening.
    And the keyboard lands on the rung the record is ON, which is where somebody
    reading a ladder is looking.

    The write itself is asserted whole — one PATCH, that body, `#base` moved on
    to the commit that came back, the sentence in the live region, the event pair
    balanced and the row afterwards carrying the new status. A menu that wrote
    twice, wrote the wrong record, left `#base` behind or never told the table is
    each a different line of `popWrite` and each fails here on its own.
    """
    got = _at_the_table(index, tmp_path / "ladder.html", _THE_LADDER)

    assert not got.get("error"), got
    assert "status" in got["top"], got["top"]
    assert got["top"].index("status") < got["top"].index("open"), (
        f"the write half is drawn below the reader's items: {got['top']}"
    )
    inside = {one["kind"]: one for one in got["inside"]}
    assert [one["kind"] for one in got["inside"]] == ["back"] + [
        f"status-{status}" for status in got["ladder"]
    ], got["inside"]
    assert inside["back"]["word"] == "‹ Back"
    for status in got["ladder"]:
        one = inside[f"status-{status}"]
        assert one["word"] == HUMAN[status], f"{status} is drawn as {one['word']!r}"
        assert one["glyph"] == STATUS_GLYPH[status], (
            f"{status} carries {one['glyph']!r} and its mark on this plan is "
            f"{STATUS_GLYPH[status]!r}"
        )
        assert one["role"] == "menuitemradio", (
            f"{status} is a plain menuitem, where `aria-checked` is ignored — so the "
            "dot beside the current rung is a mark only a sighted reader gets"
        )
        current = status == got["was"]
        assert one["checked"] == ("true" if current else "false"), one
        assert one["mark"] == ("•" if current else ""), (
            f"{status} draws {one['mark']!r} behind the word and the record is "
            f"{got['was']}"
        )
    assert got["label"] == "Status", (
        f"the box still names itself {got['label']!r} inside the ladder, so a reader "
        "who arrives in the submenu is told which record it is about and not which "
        "list they are in"
    )
    assert got["landed"] == f"status-{got['was']}", (
        f"the keyboard landed on {got['landed']} rather than on the rung the record is on"
    )
    assert len(got["sent"]) == 1, got["sent"]
    assert got["sent"][0]["url"] == f"/api/record/{got['id']}", got["sent"][0]
    assert got["sent"][0]["body"] == {
        "base_commit": HEAD,
        "fields": {"status": "shaping"},
        "body": None,
    }, got["sent"][0]
    assert got["closed"] is True, "the box stayed up over a write that landed"
    assert got["base"] == "c0ffee1", (
        f"`#base` is still {got['base']} after a commit, so this page's next write "
        "collides with the commit it just made"
    )
    assert got["said"] == f"{got['title']} is now {HUMAN['shaping']}", got["said"]
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]
    assert got["now"] == "shaping", (
        "the row still reads `ready` after its own write: the host's `wrote()` never "
        "re-read the plan, so the table shows the record as it was until a reload"
    )


_THE_GATE = """
const row = rowWhere(one => one.kind === 'task' && one.status !== 'done'
                            && !holds(one, 'prs') && !holds(one, 'end_date'));
if (!row) return {error: 'the corpus holds no task short of the gate at done'};
openOn(row.id);
itemIn('status').click();
const before = popKinds();
const gated = itemIn('status-done');
const seen = {disabled: gated.getAttribute('aria-disabled'), why: gated.dataset.why || '',
              role: gated.getAttribute('role'), word: wordIn(gated)};
gated.click();
await rest(400);
return {id: row.id, title: row.title, seen, before,
        // The table's OWN answer to the same question, asked of the same row
        // through the machinery `askFor` is built on.
        missing: missingFor(row, 'done'),
        labels: missingFor(row, 'done').map(field => FIELD_LABELS[field] || field),
        word: human('done'),
        sent: patches().length, open: popIsOpen(), kinds: popKinds(), said: said(),
        base: baseNow(), beats: beatsNow()};
"""


def test_a_gated_status_is_refused_in_the_gates_own_words_and_writes_nothing(
    index: Index, tmp_path: Path
):
    """**The one most likely to be got wrong quietly**, so both halves are
    asserted: the item is refused, AND no request was made.

    An item that is drawn `aria-disabled` and sends its PATCH anyway looks
    exactly right in a screenshot and in the DOM; what it does is let the server
    answer 422 for a rule the page had already worked out. So `patches()` is
    asked as well, and so is `#base`, and so is the event pair — a write that
    went out and was refused leaves all three moved.

    The sentence is asserted against the TABLE's own machinery rather than
    against a literal: `missingFor`, `FIELD_LABELS` and `human` are the page's,
    and the claim is that the menu names the same fields in the same words. A
    second wording for one rule is how a control and the server come to describe
    the same refusal two ways, which is the failure `HUMAN` was written for.

    One deliberate difference is not asserted as equality and is why the labels
    are checked by containment: `missingFor` drops any field the table cannot
    edit, because the panel it feeds has to offer a box per field it names, and
    the menu offers no boxes at all — so a field the table could not write is
    still a reason the server would refuse and the menu still names it.
    """
    got = _at_the_table(index, tmp_path / "gate.html", _THE_GATE)

    assert not got.get("error"), got
    assert got["missing"], (
        "the table's own gate finds nothing missing at `done` on this row, so the "
        "menu has nothing to refuse and this test is about nothing"
    )
    assert got["seen"]["disabled"] == "true", (
        "a status the record cannot be given is offered as though it could be"
    )
    assert got["seen"]["role"] == "menuitemradio", got["seen"]
    assert got["seen"]["word"] == HUMAN["done"]
    for label in got["labels"]:
        assert label in got["seen"]["why"], (
            f"the refusal does not name {label!r}, which the table's own gate says "
            f"is missing: {got['seen']['why']!r}"
        )
    assert got["seen"]["why"].startswith(f"{got['word']} needs "), got["seen"]["why"]
    assert got["title"] in got["seen"]["why"], (
        f"the refusal does not name the record it is about: {got['seen']['why']!r}"
    )
    assert "own page" in got["seen"]["why"], (
        "the refusal says what is missing and not where to put it — an error says "
        f"how to fix it: {got['seen']['why']!r}"
    )
    assert got["sent"] == 0, (
        "the refused item sent a PATCH anyway, so the page knew the gate would "
        "refuse it and asked the server to say so"
    )
    assert got["beats"] == {"writing": 0, "wrote": []}, got["beats"]
    assert got["base"] == HEAD, "`#base` moved on a write that never happened"
    assert got["open"] is True, "a refused item dismissed the menu"
    assert got["kinds"] == got["before"], (
        f"the ladder changed under a refusal: {got['before']} became {got['kinds']}"
    )
    assert got["said"] == got["seen"]["why"], (
        f"pressing the refused item announced {got['said']!r} rather than its reason"
    )


# --------------------------------------------------------------------------- #
# Owner
# --------------------------------------------------------------------------- #


_THE_PEOPLE = """
const row = rowWhere(one => one.kind === 'task' && one.owner);
if (!row) return {error: 'the corpus holds no owned task'};
const somebody = POP_SCHEMA.people.find(login => login !== row.owner);
if (!somebody) return {error: 'the corpus knows only one person'};
openOn(row.id);
itemIn('owner').click();
const kinds = popKinds();
const inside = popControls().map(one => ({kind: one.dataset.kind, word: wordIn(one),
  role: one.getAttribute('role'), checked: one.getAttribute('aria-checked')}));
const landed = document.activeElement.dataset.kind;
itemIn('owner-' + somebody).click();
await rest(700);
const first = {closed: !popIsOpen(), said: said(), base: baseNow(), sent: patches().length};
// And "nobody", off a fresh open — the submenu is built from the row as it is
// now, so this one is drawn against an owner the write above has just changed.
openOn(row.id);
itemIn('owner').click();
const second = {checked: popControls().filter(one => one.getAttribute('aria-checked') === 'true')
                          .map(one => one.dataset.kind)};
itemIn('owner-nobody').click();
await rest(700);
return {id: row.id, title: row.title, was: row.owner, somebody, kinds, inside, landed, first,
        second, people: POP_SCHEMA.people, sent: patches(), said: said(),
        now: DATA.rows[row.id].owner, base: baseNow(), beats: beatsNow()};
"""


def test_the_owner_submenu_writes_a_person_and_nobody_clears_it(index: Index, tmp_path: Path):
    """`Owner ▸` is the page's own people plus one value that is not a person.

    The list is asserted against `POP_SCHEMA.people`, which is `_suggestions`
    (`controls.py`) — the same source the table's suggestion box completes from.
    A second reading of "who is on this plan" would disagree with the box beside
    it the first time somebody joined, and it would disagree silently.

    **`— nobody —` is a value in the list and not a verb**, and what it writes is
    `null` and not `''`. Those are two different writes and only one of them is
    the shape every other unset field in this corpus has: `patch_text`
    round-trips, so `owner: ''` is a field that is present and empty. The
    assertion is on the body that went out, because nothing on the page can tell
    the two apart afterwards.

    The second write is made off a FRESH open so that the submenu is built from
    the row as it then is — `items` is a function for exactly this reason — and
    the check mark it draws is asserted to have moved to the person the first
    write set. A submenu stored at its parent's draw would still be marking the
    owner the record had a commit ago.
    """
    got = _at_the_table(index, tmp_path / "people.html", _THE_PEOPLE, patience=4000)

    assert not got.get("error"), got
    assert got["kinds"] == ["back", *[f"owner-{login}" for login in got["people"]], "owner-nobody"]
    inside = {one["kind"]: one for one in got["inside"]}
    assert inside["owner-nobody"]["word"] == "— nobody —", (
        f"the value that is not a person is drawn as {inside['owner-nobody']['word']!r}"
    )
    assert inside[f"owner-{got['was']}"]["checked"] == "true", (
        f"the record is owned by {got['was']} and nothing in the list is marked as current"
    )
    assert inside[f"owner-{got['was']}"]["role"] == "menuitemradio"
    assert got["landed"] == f"owner-{got['was']}", (
        f"the keyboard landed on {got['landed']} rather than on the current owner"
    )
    assert got["first"]["sent"] == 1, "picking a person did not write, or wrote twice"
    assert got["first"]["closed"] is True
    assert got["first"]["said"] == f"{got['title']} is now owned by {got['somebody']}"
    assert got["second"]["checked"] == [f"owner-{got['somebody']}"], (
        f"the second open still marks {got['second']['checked']} as the owner, so the "
        "submenu was built once and kept rather than rebuilt from the row"
    )
    assert [one["body"]["fields"] for one in got["sent"]] == [
        {"owner": got["somebody"]},
        {"owner": None},
    ], got["sent"]
    assert [one["body"]["base_commit"] for one in got["sent"]] == [HEAD, "c0ffee1"], (
        "the second write did not go out against the commit the first one made — "
        "this page would be picking a conflict with itself: "
        f"{[one['body']['base_commit'] for one in got['sent']]}"
    )
    assert got["said"] == f"{got['title']} has no owner", got["said"]
    assert got["now"] is None, "clearing the owner left the row still owned"
    assert got["beats"] == {"writing": 2, "wrote": ["c0ffee1", "c0ffee2"]}, got["beats"]


# --------------------------------------------------------------------------- #
# Take out of "X", which is three sentences and a fourth
# --------------------------------------------------------------------------- #


_TAKING_OUT = """
const inside = rowWhere(one => one.parent && !one.off_plan_parent);
const off = rowWhere(one => one.off_plan_parent);
const loose = rowWhere(one => !one.parent && !one.off_plan_parent
                              && (POP_SCHEMA.parent_kinds[one.kind] || []).length);
const top = rowWhere(one => !(POP_SCHEMA.parent_kinds[one.kind] || []).length);
if (!inside || !off || !loose || !top)
  return {error: 'the corpus does not hold all four shapes',
          have: {inside: !!inside, off: !!off, loose: !!loose, top: !!top}};
// Each refusal is opened, read and PRESSED, because "drawn dim" and "does
// nothing" are two claims and only the second one is about the plan.
const readItem = id => {
  openOn(id);
  const one = itemIn('take-out');
  const seen = {word: wordIn(one), why: one.dataset.why || '',
                disabled: one.getAttribute('aria-disabled'), said: ''};
  one.click();
  seen.said = said();
  popClose();
  return seen;
};
const refused = {off: readItem(off.id), loose: readItem(loose.id), top: readItem(top.id)};
const quiet = {sent: patches().length, base: baseNow(), beats: beatsNow()};
// The one that acts, last, so the count above cannot be confused with this one.
openOn(inside.id);
const acting = {word: wordIn(itemIn('take-out')),
                disabled: itemIn('take-out').getAttribute('aria-disabled')};
itemIn('take-out').click();
await rest(700);
return {refused, quiet, acting,
        inside: {id: inside.id, title: inside.title,
                 parentTitle: DATA.rows[inside.parent].title},
        off: {id: off.id, title: off.title}, loose: {id: loose.id, title: loose.title},
        top: {id: top.id, title: top.title, kind: top.kind},
        sent: patches(), said: said(), closed: !popIsOpen(),
        now: DATA.rows[inside.id].parent, beats: beatsNow()};
"""


def test_take_out_acts_on_a_parent_and_refuses_the_three_ways_there_is_not_one(
    index_holding_an_off_plan_parent: Index, tmp_path: Path
):
    """**Three sentences, not two** — and a fourth that the ladder makes true.

    `_row` (`rows.py`) nulls a parent that is not in `index.plan` and sets
    `off_plan_parent` beside it, so `row.parent` being empty means one of two
    completely different things. Telling a record that IS inside something this
    view cannot draw that it "is not inside anything" is the bug
    `tests/test_exclusion.py` was written for seen from the other side, and
    acting on it would overwrite a line the page never showed anybody.

    The fourth is the ladder's: a product can hold nothing above it, so "is not
    inside anything" implies a fix that does not exist. That distinction is
    `moveTip`'s (`table.py`) for the drag gesture, and it is the same records.

    Every refusal is PRESSED and the wire is then read. An item drawn dim that
    sends its PATCH anyway would pass a test that only looked at the markup, and
    on the off-plan row that PATCH is the data loss: `{parent: null}` over a
    stored parent nothing on this page ever drew, which the server cannot tell
    from the record page legitimately refiling it.
    """
    got = _at_the_table(
        index_holding_an_off_plan_parent, tmp_path / "takeout.html", _TAKING_OUT, patience=4000
    )

    assert not got.get("error"), got
    wanted = {
        "off": (
            f"{got['off']['title']} is filed under something this view cannot show "
            "— where it belongs is edited on its own page."
        ),
        "loose": f"{got['loose']['title']} is not inside anything.",
        "top": (
            f"A {got['top']['kind']} belongs to nothing, so there is nothing to "
            "take it out of."
        ),
    }
    for which, sentence in wanted.items():
        seen = got["refused"][which]
        assert seen["disabled"] == "true", f"the {which} row's Take out is offered as an action"
        assert seen["word"] == "Take out", (
            f"the {which} row's refused item names a parent it has not got: {seen['word']!r}"
        )
        assert seen["why"] == sentence, f"{which}: {seen['why']!r}"
        assert seen["said"] == sentence, (
            f"pressing the {which} row's refused item announced {seen['said']!r}"
        )
    assert got["quiet"]["sent"] == 0, (
        "a refused Take out sent a PATCH: on the off-plan row that write blanks a "
        "parent nothing on this page ever drew"
    )
    assert got["quiet"]["base"] == HEAD
    assert got["quiet"]["beats"] == {"writing": 0, "wrote": []}, got["quiet"]["beats"]

    assert got["acting"]["disabled"] is None, "the row that IS inside something was refused"
    assert got["acting"]["word"] == f'Take out of "{got["inside"]["parentTitle"]}"', (
        f"the item names {got['acting']['word']!r} and the parent is "
        f"{got['inside']['parentTitle']!r}"
    )
    assert len(got["sent"]) == 1, got["sent"]
    assert got["sent"][0]["url"] == f"/api/record/{got['inside']['id']}"
    assert got["sent"][0]["body"]["fields"] == {"parent": None}, (
        "`parent: ''` and `parent: null` are not the same write — `patch_text` "
        f"round-trips a value: {got['sent'][0]['body']['fields']}"
    )
    assert got["closed"] is True
    assert got["said"] == f"{got['inside']['title']} is no longer inside anything"
    assert got["now"] is None, "the row is still filed under its parent after the write"
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


# --------------------------------------------------------------------------- #
# The keyboard, one level down
# --------------------------------------------------------------------------- #


_KEYS_AT_DEPTH = """
const target = rowWhere(one => one.kind === 'task' && one.status);
if (!target) return {error: 'the corpus holds no task with a status'};
const editable = menuRows().find(tr => tr.dataset.id === target.id)
  .querySelector('td.edit[data-record]');
if (!editable) throw new Error('no editable cell on that row: this is not a writer\\'s table');
// The page's own bulk selection, made through the page's own function — `pick`
// ends in `draw()`, so everything is found again after it. With no cell editor
// open: the document handler returns early while one is, and a test that left
// one open would pass with the defect in place.
pick(editable, false);
const picked = PICKED.size;
const row = menuRows().find(tr => tr.dataset.id === target.id);
row.querySelector('td[data-col="title"]').focus();
rightOn(row, 300, 300);
const opened = popKinds();
itemIn('status').focus();
pressKey('ArrowRight');
const drilled = {kinds: popKinds(), focused: document.activeElement.dataset.kind};
pressKey('ArrowLeft');
const popped = {kinds: popKinds(), focused: document.activeElement.dataset.kind,
                open: popIsOpen()};
pressKey('ArrowRight');
const again = popKinds();
pressKey('Escape');
const escaped = {open: popIsOpen(), kinds: popKinds(), kept: PICKED.size,
                 focused: document.activeElement.dataset.kind};
pressKey('Escape');
const closed = {open: popIsOpen(), kept: PICKED.size};
return {picked, opened, drilled, popped, again, escaped, closed,
        ladder: POP_SCHEMA.statuses[target.kind], was: target.status};
"""


def test_the_arrows_walk_into_a_submenu_and_escape_pops_before_it_closes(
    index: Index, tmp_path: Path
):
    """Five claims, and the fifth is the one that costs somebody work.

    ArrowRight drills, ArrowLeft pops, Escape at depth pops rather than closing,
    Escape at the top closes — and **Escape at depth still does not reach the
    table's document-level handler**, which drops the whole bulk selection. That
    handler is `addEventListener('keydown', …)` on the DOCUMENT and everything on
    the page is below it, so the box's `stopPropagation()` has to be ABOVE the
    branch that decides whether to pop or to close. Written the other way round
    — inside the close arm — every assertion but the last one here still passes,
    and a key that did not even shut the menu takes the reader's selection with
    it.

    ArrowLeft and Escape are both asserted because they are two spellings of one
    thing, and cut 3 found the mouse path through `‹ Back` closing the menu while
    both key paths popped correctly. Two ways to do one thing, one of them wrong.
    """
    got = _at_the_table(index, tmp_path / "keys.html", _KEYS_AT_DEPTH)

    assert not got.get("error"), got
    assert got["picked"] >= 1, "nothing was selected, so this test cannot see the defect"
    assert "status" in got["opened"], got["opened"]
    wanted = ["back", *[f"status-{status}" for status in got["ladder"]]]
    assert got["drilled"]["kinds"] == wanted, (
        f"ArrowRight on the status item drew {got['drilled']['kinds']}"
    )
    assert got["drilled"]["focused"] == f"status-{got['was']}", got["drilled"]
    assert got["popped"]["open"] is True, "ArrowLeft closed the menu instead of popping a level"
    assert got["popped"]["kinds"] == got["opened"], got["popped"]
    assert got["popped"]["focused"] == "status", (
        "ArrowLeft put the keyboard on "
        f"{got['popped']['focused']} rather than back on the item it came out of"
    )
    assert got["again"] == wanted, "the second drill did not go back in"
    assert got["escaped"]["open"] is True, (
        "Escape inside the submenu closed the whole menu: one press, one level"
    )
    assert got["escaped"]["kinds"] == got["opened"], got["escaped"]
    assert got["escaped"]["focused"] == "status", got["escaped"]
    assert got["escaped"]["kept"] == got["picked"], (
        f"an Escape that merely backed out of a submenu took the bulk selection with "
        f"it: {got['picked']} cells before, {got['escaped']['kept']} after"
    )
    assert got["closed"]["open"] is False, "Escape at the top level left the menu up"
    assert got["closed"]["kept"] == got["picked"], (
        "the Escape that closed the menu dropped the bulk selection on the way out"
    )


# --------------------------------------------------------------------------- #
# A refusal, which is the answer this box has to stay up for
# --------------------------------------------------------------------------- #


_REFUSED = """
const row = rowWhere(one => one.kind === 'task' && one.status === 'ready');
if (!row) return {error: 'the corpus holds no ready task to move'};
// A RULE's own sentence: `web.py` raises thirteen of these as an
// HTTPException(409) BEFORE anything is written, and not one of them is a
// concurrent write.
const RULE = 'a project cannot be filed under a project and proj-000002 is under prod-0f0002';
// And the store's compare-and-swap report, which is the other 409 and the only
// one that means somebody else moved the plan.
const REPORT = 'main is at deadbee, and this page was rendered from c0ffee';
ANSWER = () => ({status: 409, body: {detail: RULE}});
openOn(row.id);
const top = popKinds();
itemIn('status').click();
const ladder = popKinds();
itemIn('status-shaping').click();
await rest(700);
const first = popControls()[0];
const rule = {open: popIsOpen(), kinds: popKinds(), said: said(), base: baseNow(),
              drawn: first ? wordIn(first) : '', kind: first ? first.dataset.kind : '',
              disabled: first ? first.getAttribute('aria-disabled') : '',
              focused: document.activeElement.dataset.kind, beats: beatsNow(),
              rows: DATA.rows[row.id].status};
// Still usable: every item the level had is under the refusal, and `‹ Back` is
// one of them and still gets out of the list.
itemIn('back').click();
const after = {kinds: popKinds(), open: popIsOpen()};
ANSWER = () => ({status: 409, body: {conflict: REPORT}});
itemIn('status').click();
itemIn('status-shaping').click();
await rest(700);
const second = popControls()[0];
const conflict = {open: popIsOpen(), said: said(), base: baseNow(),
                  drawn: second ? wordIn(second) : ''};
return {id: row.id, RULE, REPORT, top, ladder, rule, after, conflict,
        sent: patches().length};
"""


def test_a_refusal_leaves_the_menu_up_saying_what_the_server_said(index: Index, tmp_path: Path):
    """**Both 409 shapes, and the one that has been got wrong five times.**

    A 409 from this server carries either the store's `conflict` report or a
    rule's own `detail` sentence, and every page that decided for itself which
    key the body holds has printed "somebody else changed this first" over a
    sentence that told the reader exactly what to do. So the rule's sentence is
    asserted to arrive verbatim, and the stock line is asserted NOT to. That is
    also the sweep in `tests/test_writes.py` seen from the outside: a reader
    spelled `said.detail || said.conflict` reads the two in the wrong order and
    fails there — this says what it costs a person.

    The box stays up, which is what makes the answer readable at all: the menu is
    over the row, the live region on this page is a strip most readers will not
    be looking at, and a box that closed under an answer that had not arrived
    makes a refused write look exactly like one that landed. So the refusal is
    drawn as an item, the keyboard is put on it, and the level under it is
    untouched — every item it had is still there and `‹ Back` still gets out.

    And nothing moved: `#base` is where it was, the row is unchanged, and the
    event pair still balances. `openproj:wrote` fires on a refusal too — it has
    to, or the shell's count never comes back down — which is precisely why the
    listener that closes this box on that event reads the sha first.
    """
    got = _at_the_table(index, tmp_path / "refused.html", _REFUSED, patience=4500)

    assert not got.get("error"), got
    assert got["rule"]["open"] is True, (
        "the menu closed under a refusal, so the reason was drawn and taken off the "
        "screen half a tick later"
    )
    assert got["rule"]["said"] == got["RULE"], (
        f"the live region says {got['rule']['said']!r} and the server said "
        f"{got['RULE']!r}"
    )
    assert got["rule"]["said"] != "somebody else changed this first", (
        "a rule's own sentence was read as the store's conflict report: the reader "
        "is sent to reload against a plan nobody touched"
    )
    assert got["rule"]["kind"] == "said", (
        f"the refusal was announced and not drawn — the first item is "
        f"{got['rule']['kind']!r}"
    )
    assert got["rule"]["drawn"] == got["RULE"], got["rule"]["drawn"]
    assert got["rule"]["disabled"] == "true", "the drawn refusal is an item you can press"
    assert got["rule"]["focused"] == "said", (
        f"the keyboard is on {got['rule']['focused']!r} rather than on the reason, "
        "and `replaceChildren` has just thrown away whatever it was on"
    )
    assert got["rule"]["kinds"] == ["said", *got["ladder"]], (
        f"the refusal replaced the level instead of standing over it: {got['rule']['kinds']}"
    )
    assert got["rule"]["base"] == HEAD, "`#base` moved on a write the server refused"
    assert got["rule"]["rows"] == "ready", "the row was changed by a write that did not happen"
    assert got["rule"]["beats"] == {"writing": 1, "wrote": [None]}, (
        f"the event pair does not balance over a refusal: {got['rule']['beats']} — one "
        "held-back `openproj:wrote` stops the moved-banner for ever"
    )
    assert got["after"]["open"] is True and got["after"]["kinds"] == got["top"], (
        f"`‹ Back` under a refusal drew {got['after']}, and the level it pops to is "
        f"{got['top']}"
    )
    assert got["conflict"]["said"] == got["REPORT"], (
        f"the store's own report came out as {got['conflict']['said']!r}"
    )
    assert got["conflict"]["drawn"] == got["REPORT"]
    assert got["conflict"]["open"] is True
    assert got["conflict"]["base"] == HEAD
    assert got["sent"] == 2, f"two presses, two PATCHes, and the page sent {got['sent']}"


# --------------------------------------------------------------------------- #
# Two presses
# --------------------------------------------------------------------------- #


_TWICE = """
const row = rowWhere(one => one.kind === 'task' && one.status === 'ready');
if (!row) return {error: 'the corpus holds no ready task to move'};
// The answer is held, which is the whole state this guard is about: the box
// stays up under a write, the item is under the pointer, and it is easier to
// press twice than the button that minted two records on the deployed service.
let release = null;
ANSWER = () => new Promise(done => {
  release = () => done({status: 200, body: {outcome: 'committed', commit: 'c0ffee1',
                                            pushed: true}});
});
openOn(row.id);
itemIn('status').click();
const item = itemIn('status-shaping');
item.click();
item.click();
await rest(150);
const during = {sent: patches().length, said: said(), open: popIsOpen(),
                writing: beats.writing};
release();
await rest(700);
return {id: row.id, during, sent: patches(), said: said(), closed: !popIsOpen(),
        base: baseNow(), beats: beatsNow()};
"""


def test_two_presses_with_no_gap_send_one_patch(index: Index, tmp_path: Path):
    """`CREATING` (`table.py`) exists because two presses 0.9s apart minted two
    records on the deployed service, and a status item is easier to press twice
    than that button was: it sits under the pointer and the box stays up until
    the answer comes back.

    Two PATCHes against one base is a page picking a conflict with itself — the
    second would answer 409 and the reader would be told somebody else had
    changed it. So the second press is refused before the `openproj:writing`
    event, and that ordering is asserted as well: an early return after the
    event leaves the shell's count held one too high, and the moved-banner never
    appears again.

    The answer is held rather than raced. A test that clicked twice against an
    answer that came back immediately would be asking nothing at all — the guard
    is only ever true while a write is in the air.
    """
    got = _at_the_table(index, tmp_path / "twice.html", _TWICE)

    assert not got.get("error"), got
    assert got["during"]["sent"] == 1, (
        f"{got['during']['sent']} PATCHes went out for two presses, against one base"
    )
    assert got["during"]["writing"] == 1, (
        "the second press dispatched `openproj:writing` before it was refused, so "
        "the shell's count is held one too high for the rest of the page's life"
    )
    assert got["during"]["open"] is True, "the box went down before the answer arrived"
    assert got["during"]["said"], "the second press was refused in silence"
    assert "already" in got["during"]["said"], (
        f"the second press announced {got['during']['said']!r}, which does not say "
        "that a save is already going out"
    )
    assert len(got["sent"]) == 1, got["sent"]
    assert got["closed"] is True and got["base"] == "c0ffee1"
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


# --------------------------------------------------------------------------- #
# What each view adds of its own
# --------------------------------------------------------------------------- #


# The two words the design fixes for the graph's own items. Found by word and
# not by slug: `data-kind` is stable for the items `pop.py` builds, and a host's
# own item has no slug in any contract.
_ADD_EDGE = "Add dependency from here"
_FOCUS = "Focus subtree"

_THE_GRAPHS_OWN = """
const node = cy.nodes().filter(one => !one.isParent())[0];
if (!node) return {error: 'the graph drew no leaf node'};
const rightOnTheNode = () => node.emit({type: 'cxttap', position: node.position(),
  originalEvent: {clientX: 420, clientY: 300, shiftKey: false, preventDefault() {}}});
// The page's own words for its own mode, read off its own button rather than
// written down here: what the item has to leave behind is the state pressing
// that button leaves behind.
CONNECT.click();
const inMode = {text: CONNECT.textContent, connecting: connecting};
CONNECT.click();
const outMode = {text: CONNECT.textContent, connecting: connecting};
rightOnTheNode();
const words = popControls().map(wordIn);
const add = extraIn(ADD_EDGE);
if (!add) return {error: 'the graph offers no such item', words: words};
add.click();
// The graph's harness is `_READERS` alone — `rest` belongs to `_OPENING`, which
// is the table's — and one tick is all this waits for: the run is synchronous
// and what follows it is the canvas settling.
await new Promise(done => setTimeout(done, 300));
return {id: node.id(), words, inMode, outMode, open: popIsOpen(),
        after: {connecting: connecting, text: CONNECT.textContent,
                blocker: blocker ? blocker.id() : null,
                picked: cy.getElementById(node.id()).hasClass('picked'),
                pending: cy.edges('.pending').length}};
"""

_THE_GRAPH_A_READER_GETS = """
const node = cy.nodes().filter(one => !one.isParent())[0];
if (!node) return {error: 'the graph drew no leaf node'};
node.emit({type: 'cxttap', position: node.position(),
  originalEvent: {clientX: 420, clientY: 300, shiftKey: false, preventDefault() {}}});
return {connect: !!document.getElementById('connect'), open: popIsOpen(),
        words: popControls().map(wordIn), kinds: popKinds()};
"""


def test_the_graphs_own_item_puts_the_canvas_into_connecting_mode_at_that_node(
    index: Index, tmp_path: Path
):
    """Drawing a dependency takes two clicks on the canvas, and the first of them
    is "which record must finish first". This item is that first click made from
    the record you are already pointing at — so what it has to leave behind is
    exactly the state the canvas is in one tap into the gesture: the mode on, the
    node held as the blocker, and the node drawn `picked` so the reader can see
    which end they have.

    **The button's own word is asserted too, and it is read off the button
    rather than written here.** A mode turned on by setting `connecting = true`
    and nothing else leaves the control that turns it off still saying "Edit
    dependencies" — a reader in a mode with no visible way out, and a canvas that
    discards their half-drawn edge when they press what looks like the way in.

    And nothing is drawn yet: one end is not an edge. A `pending` edge here would
    be a dependency on nothing, which the Save button would then try to commit.

    The reader's page is asked the same question, and it is the control this test
    needs: `extras` is spliced in whole, OUTSIDE the `may()` gate that holds the
    write half back, so a host that forgets to ask offers a signed-out reader a
    gesture that ends in a PATCH.
    """
    got = measured_in(
        chrome(),
        render_graph(index, ROUTES, base_commit=HEAD, may_write=True),
        tmp_path / "graphmine.html",
        1280,
        _READERS + f"const ADD_EDGE = {_ADD_EDGE!r};\n" + _THE_GRAPHS_OWN,
        patience=3000,
    )

    assert not got.get("error"), got
    assert _FOCUS in got["words"], (
        f"the graph's menu offers {got['words']}, with no {_FOCUS!r} among them"
    )
    assert got["inMode"]["connecting"] is True and got["outMode"]["connecting"] is False, got
    assert got["after"]["connecting"] is True, (
        "the item did not put the canvas into connecting mode, so the click that "
        "follows it lands on a canvas that is not drawing anything"
    )
    assert got["after"]["blocker"] == got["id"], (
        f"the canvas is holding {got['after']['blocker']} as the record that must "
        f"finish first, and the menu was opened on {got['id']}"
    )
    assert got["after"]["picked"] is True, (
        "the node is not drawn picked, so nothing on the canvas says which end of "
        "the dependency is already chosen"
    )
    assert got["after"]["text"] == got["inMode"]["text"], (
        f"the button still says {got['after']['text']!r} while the canvas is "
        f"connecting: it says {got['inMode']['text']!r} when the button itself turns "
        "the mode on, and a reader whose only way out is a control that lies about "
        "what it does will press it to leave and discard their edge instead"
    )
    assert got["after"]["pending"] == 0, (
        "the item drew an edge from one end, which Save would then commit as a "
        "dependency on nothing"
    )
    assert got["open"] is False, "the box stayed up over the canvas it just put into a mode"

    reader = measured_in(
        chrome(),
        render_graph(index, ROUTES, base_commit=HEAD, may_write=False),
        tmp_path / "graphreader.html",
        1280,
        _READERS + _THE_GRAPH_A_READER_GETS,
        patience=3000,
    )
    assert not reader.get("error"), reader
    assert reader["connect"] is False, (
        "the reader's graph draws the Edit dependencies button, so this half is not "
        "about a reader at all"
    )
    assert reader["open"] is True, "the reader's graph opened no menu, so its list is empty"
    assert _ADD_EDGE not in reader["words"], (
        f"a signed-out reader is offered {_ADD_EDGE!r}: `extras` is spliced in outside "
        "the `may()` gate, so a host that does not ask gets no gate at all"
    )
    for refused in ("status", "owner", "take-out", "no-schema"):
        assert refused not in reader["kinds"], (
            f"the reader's graph draws {refused!r}: {reader['kinds']}"
        )


_FOCUSING = """
const kin = {};
for (const one of Object.values(DATA.rows))
  if (one.parent) (kin[one.parent] = kin[one.parent] || []).push(one.id);
// A pitch and not the first record that holds two: the products at the top of
// this corpus hold nearly all of it, and "fewer rows than before" is a claim a
// filter that dropped one row also satisfies.
const target = rowWhere(one => one.kind === 'pitch' && (kin[one.id] || []).length >= 2);
if (!target) return {error: 'no pitch in the corpus holds two records'};
const family = new Set([target.id]);
const walk = id => (kin[id] || []).forEach(child => { family.add(child); walk(child); });
walk(target.id);
// The ancestors are allowed either way — a subtree drawn with the line down to
// it is a defensible reading — so the row this asks about is one that is in
// neither direction from the target.
const above = new Set();
for (let up = target.parent; up; up = (DATA.rows[up] || {}).parent) above.add(up);
const stranger = rowWhere(one => !family.has(one.id) && !above.has(one.id));
if (!stranger) return {error: 'every row in the corpus is in one family'};
const before = menuRows().map(tr => tr.dataset.id);
openOn(target.id);
const focus = extraIn(FOCUS);
if (!focus) return {error: 'the table offers no such item',
                    words: popControls().map(wordIn)};
focus.click();
await rest(600);
const out = document.getElementById('unfilter');
const narrowed = {shown: menuRows().map(tr => tr.dataset.id), open: popIsOpen(),
                  said: said(), offered: !out.hidden};
if (narrowed.offered) out.click();
await rest(600);
return {id: target.id, family: [...family], stranger: stranger.id, before, narrowed,
        back: menuRows().map(tr => tr.dataset.id), sent: patches().length};
"""


def test_focus_subtree_narrows_the_table_to_one_family_and_says_how_to_get_out(
    index: Index, tmp_path: Path
):
    """A read gesture, and the two halves of it are one rule this repository has
    already written down: *empty must not look like broken*, and a filter you
    cannot see is a filter you cannot leave.

    So the rows are asserted in both directions — the family is there and a
    record in neither direction from it is gone — and then the way out is
    asserted to be the way out this bar already has. `#unfilter` ("Clear
    filters") is drawn only while something is actually set, which makes it the
    honest witness: a focus that narrowed the table without going through the
    page's own filter state would leave that button hidden, and a reader who had
    just hidden four fifths of their plan with a menu item would have nothing on
    screen offering it back.

    Nothing is written. A gesture that only decides which rows are drawn has no
    business touching the plan, and that is asserted rather than assumed because
    the item sits in the same list as three that do.
    """
    got = _at_the_table(index, tmp_path / "focus.html", f"const FOCUS = {_FOCUS!r};\n" + _FOCUSING)

    assert not got.get("error"), got
    assert len(got["family"]) >= 3, got["family"]
    assert len(got["narrowed"]["shown"]) < len(got["before"]), (
        f"the table still draws {len(got['narrowed']['shown'])} rows of "
        f"{len(got['before'])}, so nothing was narrowed"
    )
    for one in got["family"]:
        assert one in got["narrowed"]["shown"], (
            f"{one} is inside {got['id']} and was filtered out of its own subtree"
        )
    assert got["stranger"] not in got["narrowed"]["shown"], (
        f"{got['stranger']} is in neither direction from {got['id']} and is still drawn"
    )
    assert got["narrowed"]["offered"] is True, (
        "the table narrowed itself with `Clear filters` still hidden, so the reader "
        "has no control on screen that gives the rest of the plan back"
    )
    assert sorted(got["back"]) == sorted(got["before"]), (
        f"Clear filters brought back {len(got['back'])} rows of {len(got['before'])}"
    )
    assert got["narrowed"]["open"] is False, "the box stayed up over the rows it just replaced"
    assert got["sent"] == 0, "focusing a subtree wrote to the plan"


# --------------------------------------------------------------------------- #
# What the host owes a write that landed
# --------------------------------------------------------------------------- #


_AFTERWARDS = """
const row = rowWhere(one => one.kind === 'task' && one.status === 'ready');
if (!row) return {error: 'the corpus holds no ready task to move'};
// A commit the server itself says is not on GitHub yet, which is the one answer
// `markSaved` acts on.
ANSWER = () => ({status: 200,
                 body: {outcome: 'committed', commit: 'c0ffee1', pushed: false}});
const tr = menuRows().find(one => one.dataset.id === row.id);
const cell = tr.querySelector('td[data-col="title"]');
if (!cell.hasAttribute('tabindex')) return {error: 'the title cell is not a keyboard stop'};
cell.focus();
rightOn(tr, 300, 300);
itemIn('status').click();
itemIn('status-shaping').click();
await rest(900);
const drawn = menuRows().find(one => one.dataset.id === row.id);
const where = document.activeElement;
return {id: row.id, held: UNLANDED.get('c0ffee1') || null,
        mark: !!(drawn && drawn.querySelector('.unlanded')),
        status: DATA.rows[row.id].status,
        focus: {body: where === document.body, tag: where.tagName,
                row: where.closest && where.closest('tr') ? where.closest('tr').dataset.id : null}};
"""


def test_a_menu_write_leaves_the_row_marked_and_the_keyboard_somewhere(
    index: Index, tmp_path: Path
):
    """Three things the HOST owes a write the menu made, and each of them is a
    feature the table already has by another route.

    **The mark.** `markSaved` remembers a commit the server reported as `pushed:
    false` and marks that row until a later read confirms it landed. A `wrote()`
    that ignores the answer takes that mark off the one gesture with no other way
    to earn it, and the row then claims to be on GitHub when it is not.

    **The redraw.** `refreshRows()` replaces `DATA.rows` and does not draw; every
    other caller on the page pairs the two. Without the draw the menu's write is
    invisible until something else happens to redraw, which on a quiet page is a
    reload.

    **The keyboard.** `popWrite` gives focus back to the element the menu was
    opened from BEFORE calling `wrote()`, precisely so that element still exists
    — and then the table's own `draw()` throws the whole tbody away, cell
    included. `rove` is what this table hands focus with everywhere else and it
    survives that redraw. Left out, focus falls to `<body>` and the next Tab
    starts from the top of the page.
    """
    got = _at_the_table(index, tmp_path / "afterwards.html", _AFTERWARDS, patience=4000)

    assert not got.get("error"), got
    assert got["held"] == got["id"], (
        "the answer never reached `markSaved`, so a commit the server said is not "
        "on GitHub yet is remembered against no row at all"
    )
    assert got["status"] == "shaping", "the host never re-read the plan after its own write"
    assert got["mark"] is True, (
        "the row carries no `not pushed yet` mark: `markSaved` ran and nothing drew "
        "again, so the mark exists only in a Map"
    )
    assert got["focus"]["body"] is False, (
        "the keyboard was left on `<body>`: `popWrite` gave it back to the cell the "
        "menu was opened from and `draw()` then replaced that cell — `rove` is what "
        "puts it somewhere that survives"
    )
    assert got["focus"]["row"] == got["id"], (
        f"the keyboard landed on a {got['focus']['tag']} in row {got['focus']['row']}, "
        f"and the write was on {got['id']}"
    )
