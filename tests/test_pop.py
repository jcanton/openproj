"""The right-click menu, in the three views that draw it.

`design/context-menus.md` is the argument; this is the second cut of it — the
box, the host contract and the reader's three items, with nothing that writes.
The judgement jcanton makes on this cut is menu-versus-hover, so the questions
that matter most here are not about the items at all. They are about the two
floating boxes getting out of each other's way, and about what a key means when
two things on the page both want it.

Nine of these need a **trusted** press, a real clock or a painted box, and are
asked of Chrome; `chrome()` skips when there is none, because a suite that is
green for want of a binary is green for the wrong reason. Four need none of
that and are asked of the rendered page and the stylesheet it ships.

What a headless run cannot see is written into the tests that depend on it:
there is no native context menu to photograph in this browser, and the only
thing a page controls about one is `preventDefault()`. So that is what is
measured, off a press the browser itself synthesised — a `MouseEvent` a script
constructs runs no default action, so under it `preventDefault()` suppresses a
menu that was never going to appear and the assertion passes either way.
"""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

import pytest
from browser import PRESSES, _devtools, _evaluated, chrome, measured_in, pressed_in

from openproj.index import Index, build_index
from openproj.model import load_repo
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

# The three items a reader gets in this cut, in this order. `data-kind` and never
# the visible text: the slug is the handle and the words are copy.
READER_ITEMS = ["open", "open-tab", "copy-link"]


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
    assert got["kinds"] == READER_ITEMS, got["kinds"]
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
pressKey('Escape');
return {picked, opened, focused, closed: !popIsOpen(), kept: PICKED.size,
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
    assert got["focused"] == READER_ITEMS[0], (
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
dispatchEvent(new CustomEvent('openproj:wrote'));
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

    `openproj:wrote` is the one that has nothing to switch on yet and is asked
    anyway. From cut 3 this menu's own writes dispatch it, and what it is for is
    the same thing `openproj:filter` is for one line above: a tbody replaced
    under a box that is not anchored to anything in it. A menu left up over rows
    that have just been rebuilt is a menu about a row that no longer exists, and
    the item that acts on it in cut 5 is `Delete…`.
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


def test_a_reader_and_a_writer_are_offered_the_same_three_items(index: Index, tmp_path: Path):
    """Cut 2 is reader-only on purpose, so that the menu-versus-hover judgement is
    made before any of it can change the plan. The two pages are therefore
    identical here, and saying so now is what makes cut 3 visible: the first
    write item shows up as this assertion failing, which is the moment to decide
    what a signed-out reader sees instead.

    The shape is asserted beside the list, because the shape is the contract cut
    3 builds against. `Open in new tab` is a real `<a target="_blank">` and not a
    `run()` — so middle-click works, and so does the browser's own menu on it,
    which is the one right press inside this box that is nobody's business but
    the browser's.
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
        assert seen["kinds"] == READER_ITEMS, f"the {who} was offered {seen['kinds']}"
        assert seen["refused"] == 0, (
            f"the {who} was offered a refused item, and nothing in this cut produces one"
        )
        assert seen["role"] == "menu"
        assert seen["roles"] == ["menuitem"] * 3, seen["roles"]
        # A button, a link, a button. The link is the one that must not be a
        # button: an `href` is what makes middle-click and the browser's own
        # menu work on it.
        assert seen["tags"] == ["BUTTON", "A", "BUTTON"], seen["tags"]
        assert seen["tab"] == {
            "href": f"/detail/{seen['id']}",
            "target": "_blank",
            "rel": "noopener",
        }, seen["tab"]
        assert seen["label"] == f"Actions for {seen['title']}"
        # Exactly one item in the Tab sequence, and it is the one with focus, so
        # Tab leaves the menu and the arrows are what walk it.
        assert seen["tabs"] == [0, -1, -1], seen["tabs"]
        assert seen["focused"] == READER_ITEMS[0]

    assert got["reader"]["kinds"] == got["writer"]["kinds"], (
        "a reader and a writer are offered different menus in a cut where nothing writes"
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
    assert got["kinds"] == READER_ITEMS, got["kinds"]
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
    assert got["opening"] == [0, -1, -1], got["opening"]
    assert got["second"] == got["kinds"][1], "ArrowDown did not move"
    assert got["wrapped"] == got["kinds"][-1], (
        "ArrowUp off the top did not wrap round to the last item"
    )
    assert got["end"] == got["kinds"][-1] and got["home"] == got["kinds"][0]
    assert got["roving"] == [0, -1, -1], (
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
