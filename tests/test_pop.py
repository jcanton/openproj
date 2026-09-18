"""The right-click menu, in the three views that draw it.

`design/context-menus.md` is the argument; this covers all five of its cuts — the
box, the host contract and the reader's three items, then the three one-field
writes that turned the menu from something you read into something that changes
the plan, then the form that answers the question the whole design started from,
and finally the one gesture on this menu that cannot be undone from the page.

The judgement jcanton makes on cut 2 is menu-versus-hover, so the questions that
mattered most there are not about the items at all. They are about the two
floating boxes getting out of each other's way, and about what a key means when
two things on the page both want it. Cut 3's are about what went on the wire:
which record, how many times, against which base, and what the box does with an
answer it did not want. Cut 4's are about a box somebody has typed into — what
it opens holding, what it sends, what it refuses to send, and the five signals
that take a menu away and must leave a half-filled form exactly where it is.
Cut 5's are one question asked from both ends: what did the page put on the wire,
and what did it show somebody before it did — because what goes out is a commit
that removes files, and the page's own words over the button are "can only be
undone with git revert".

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
and a `file://` page has nowhere to send it. The stub answers every route a menu
write touches — two until cut 4 added the create — and keeps them consistent
with each other, which is not a detail: a re-read that handed back the rows from
before the write would let a host that never re-read anything pass, and one that
said `unpushed: 0` about a commit it had just called unpushed clears the row
mark it had just earned. A create is the one that most needs it: what the
receipt says depends on whether the host can find the record afterwards.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pytest
from browser import PRESSES, _devtools, _evaluated, chrome, measured_in, pressed_in

from openproj.index import Index, build_index
from openproj.model import KINDS, RUNG, load_repo, parse_text
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

# Through the module and not the facade: `render/__init__.py` re-exports what
# pages are built from, and these two are the route's own reading of the plan —
# `web.py` reaches them the same way, as `render.detail._cascade_facts`.
from openproj.render.detail import _cascade_facts, _titles_for
from openproj.render.tokens import (
    HUMAN,
    LABELS,
    PRIORITIES,
    PRIORITY_GLYPH,
    STATUS_GLYPH,
    SUGGESTS,
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
# Late on purpose, so their position does not move when somebody signs in.
READER_ITEMS = ["open", "open-tab", "copy-link"]
# And the one item that comes after even those, on a writer's menu alone. Cut 5
# put `Delete…` there rather than beside the other five writes, and the reason is
# the gesture: a destructive item between `Take out of "X"` and `Focus subtree`
# is one slip of the wrist away from the two harmless items either side of it.
# `popItems` lifts it out of `popWriteItems`' return by its slug to get it there.
DELETE_ITEM = "delete"
# What a writer's menu ends with, then, and a reader's does not. Spelled as one
# list because three assertions below ask about the tail and a literal `-4:` in
# each of them is three places to edit when a seventh item arrives.
WRITERS_TAIL = [*READER_ITEMS, DELETE_ITEM]
# And the six that write, first, which is the other end of that same ordering.
# Between them is the slot each view splices its own items into —
# `focus-subtree` on the table and the graph, `add-dependency` on the graph, and
# nothing at all on the timeline, which registers no `extras` because it cannot
# write. Those slugs are the HOST's and are deliberately not written down here.
#
# The ORDER is the design's table read down: what makes a record, what changes
# this one, where it is filed, then what this view can do. Cut 4 put three in
# front of cut 3's three rather than after them, which is why every assertion
# below slices `len(WRITE_ITEMS)` rather than a literal — a seventh item is one
# edit here and none anywhere else. `priority` is the seventh, added 2026-09-18
# where jcanton asked for it: "just below status".
WRITE_ITEMS = ["new-child", "edit", "status", "priority", "owner", "parent", "take-out"]


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
    assert got["kinds"][: len(WRITE_ITEMS)] == WRITE_ITEMS, got["kinds"]
    assert got["kinds"][-4:] == WRITERS_TAIL, got["kinds"]
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
  refused: [...POP.children].filter(item => item.hasAttribute('aria-disabled'))
    .map(item => ({kind: item.dataset.kind, why: item.dataset.why || ''})),
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
        # The three that only look are the END of a reader's menu and the last
        # three but one of a writer's, because `Delete…` goes under even them.
        tail = WRITERS_TAIL if who == "writer" else READER_ITEMS
        assert seen["kinds"][-len(tail) :] == tail, (
            f"the {who} was offered {seen['kinds']}, which does not end in {tail}"
        )
        assert seen["refused"] == [], (
            f"the {who} was offered a refused item on a row that is inside something, "
            f"holds records and has a ladder: {seen['refused']}"
        )
        assert seen["role"] == "menu"
        assert seen["roles"] == ["menuitem"] * len(seen["kinds"]), seen["roles"]
        # A button, a link, a button. The link is the one that must not be a
        # button: an `href` is what makes middle-click and the browser's own
        # menu work on it. Read off the three slugs rather than off the end of
        # the list, because what is at the end of a writer's list is `Delete…`.
        assert [seen["tags"][seen["kinds"].index(kind)] for kind in READER_ITEMS] == [
            "BUTTON",
            "A",
            "BUTTON",
        ], seen["tags"]
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

    assert got["writer"]["kinds"][: len(WRITE_ITEMS)] == WRITE_ITEMS, got["writer"]["kinds"]
    for writes in (*WRITE_ITEMS, DELETE_ITEM, "no-schema"):
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
    assert got["kinds"][: len(WRITE_ITEMS)] == WRITE_ITEMS, got["kinds"]
    assert got["kinds"][-4:] == WRITERS_TAIL, got["kinds"]
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
# nowhere to send it. All three routes a menu write touches are answered: the
# PATCH itself, cut 4's POST, and the `/api/table.json` re-read the table's
# `wrote()` does behind both.
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
// And what it has MINTED, which the re-read then answers with beside the plan's
// own rows. Without it the host cannot find a record the create route has just
// made, so `popLanded` answers `reload to see it` about every create — the third
// of its three sentences, drawn for the wrong reason, and the receipt the form
// is judged by in two tests below.
const MADE = {};
// And what it has TAKEN OUT of the plan, which is the delete's half of the same
// bargain: the re-read has to answer without the record and without everything
// that went with it, or `DATA.rows` still holds the row a test is about to
// assert has gone — and it would go on holding it under a page that deleted
// nothing at all.
const DELETED = new Set();
let MINTED = 0;
// The id the server would answer with, spelled the way this plan spells one. The
// prefix is READ off a record of that kind rather than written down: `PREFIX` is
// the model's map and a project's ids begin `proj-`, not `project-`, so a
// harness that guessed would mint an id no page can resolve.
const nextId = kind => {
  const like = Object.values(DATA.rows).find(one => one.kind === kind);
  return (like ? like.id.split('-')[0] : kind) + '-' + String(++MINTED).padStart(6, 'a');
};
// The row the next re-read carries for it: a real row of the same kind with the
// sent fields written over it. Built from the payload alone it would be missing
// the thirty keys `_row` carries and `draw()` reads, which surfaces as a
// TypeError inside the page rather than as an answer about the menu — and
// `search`/`name` are replaced rather than inherited so the row is not findable
// under the title of whichever record stood in for its shape.
const recordMade = (id, fields) => {
  const like = Object.values(DATA.rows).find(one => one.kind === fields.kind);
  const named = String(fields.title || '').toLowerCase();
  MADE[id] = Object.assign({}, like, fields,
    {id: id, off_plan_parent: false, search: named, name: named});
};
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
//
// Two verbs and two answers, because the create route's is not the save route's:
// it is a 201 and it carries the `id` the server minted, which is the whole of
// what `popCreate` has to go on — `about(answer)` and the receipt both read it.
let ANSWER = seen => seen.method === 'POST'
  ? {status: 201, body: {id: nextId(seen.body.fields.kind), outcome: 'committed',
                         commit: 'c0ffee' + (++COMMITS), pushed: true}}
  : {status: 200,
     body: {outcome: 'committed', commit: 'c0ffee' + (++COMMITS), pushed: true}};
// What `GET /api/cascade/{id}` answers, and **it is `_cascade_facts` itself** —
// `REACH` is that function run over this very index and handed to the page as
// JSON (see `_reaches`). A stub that assembled those sentences here would be a
// second derivation of the thing the whole route exists to have exactly one of,
// and the tests below would then be asserting that the page agrees with the
// harness rather than with the plan.
//
// 404 for an id the plan has not got, which is the route's own answer and not a
// nicety: a panel that drew an empty cascade for a typo and an empty cascade for
// a leaf record cannot say which it is, and the second is a delete somebody is
// about to authorise.
let CASCADE = id => REACH[id]
  ? {status: 200, body: REACH[id]}
  : {status: 404, body: {detail: 'no such record'}};
window.fetch = async (url, options) => {
  const asked = options || {};
  const seen = {url: String(url), method: asked.method || 'GET',
                body: asked.body ? JSON.parse(asked.body) : null};
  SENT.push(seen);
  if (seen.url.includes('/api/table.json')) {
    const rows = {};
    for (const [id, row] of Object.entries(DATA.rows))
      if (!DELETED.has(id)) rows[id] = Object.assign({}, row, WRITTEN[id] || {});
    // The records this stub has minted, as the real route would be answering
    // with by now. After the plan's own rows, so a create followed by a save on
    // the new record reads back as one row and not two.
    for (const [id, row] of Object.entries(MADE))
      if (!DELETED.has(id)) rows[id] = Object.assign({}, row, WRITTEN[id] || {});
    return new Response(
      JSON.stringify({rows: rows, problems: [], parked: [], unpushed: UNPUSHED}),
      {status: 200, headers: {'content-type': 'application/json'}});
  }
  if (seen.url.includes('/api/cascade/')) {
    const asking = decodeURIComponent(seen.url.split('/api/cascade/')[1] || '');
    const answer = await CASCADE(asking);
    return new Response(JSON.stringify(answer.body),
                        {status: answer.status, headers: {'content-type': 'application/json'}});
  }
  // The create door, which has no id in its path because the record does not
  // exist yet — that is what the answer's `id` is for.
  if (seen.method === 'POST') {
    const made = await ANSWER(seen);
    if (made.status === 201) {
      recordMade(made.body.id, seen.body.fields);
      if (made.body.pushed === false) UNPUSHED += 1;
    }
    return new Response(JSON.stringify(made.body),
                        {status: made.status, headers: {'content-type': 'application/json'}});
  }
  const about = decodeURIComponent((seen.url.split('/api/record/')[1] || ''));
  // The delete door. One request takes the record and everything filed under it,
  // which is what makes the assertion "one DELETE" worth making at all — the
  // route commits the whole subtree at once, so a page sending one request per
  // doomed record would be a page writing a history that says four things that
  // are not true.
  //
  // What goes out of the plan is `REACH`'s own `deletes` and never the `also` the
  // page sent: `also` is the compare-and-swap, and a stub that deleted whatever
  // it was handed could not tell a panel that listed the consequences honestly
  // from one that made them up.
  if (seen.method === 'DELETE') {
    const answer = await ANSWER(seen);
    if (answer.status === 200) {
      for (const id of [about, ...((REACH[about] || {}).deletes || [])]) DELETED.add(id);
      if (answer.body.pushed === false) UNPUSHED += 1;
    }
    return new Response(JSON.stringify(answer.body),
                        {status: answer.status, headers: {'content-type': 'application/json'}});
  }
  const answer = await ANSWER(seen);
  if (answer.status === 200) {
    WRITTEN[about] = Object.assign({}, WRITTEN[about] || {}, seen.body.fields);
    if (answer.body.pushed === false) UNPUSHED += 1;
  }
  return new Response(JSON.stringify(answer.body),
                      {status: answer.status, headers: {'content-type': 'application/json'}});
};
const patches = () => SENT.filter(one => one.method === 'PATCH');
const posts = () => SENT.filter(one => one.method === 'POST');
const deletions = () => SENT.filter(one => one.method === 'DELETE');
const cascades = () => SENT.filter(one => one.url.includes('/api/cascade/'));

// The pair the shell counts against each other. One `openproj:wrote` for every
// `openproj:writing` — including on a refusal, or one held-back event stops the
// moved-banner for ever — and its `detail` is the sha, or null when nothing was
// committed.
const beats = {writing: 0, wrote: []};
addEventListener('openproj:writing', () => { beats.writing += 1; });
addEventListener('openproj:wrote', event => { beats.wrote.push(event.detail || null); });
const beatsNow = () => ({writing: beats.writing, wrote: beats.wrote.slice()});

// And the beat a DELETE makes instead of those two. `openproj:ours` is the
// shell's own event for a commit that is this page's, and a delete is the one
// write here that sends it — see `popDelete`. Collected beside `beats` rather
// than inside it so a test that asserts `beats` is silent is asserting exactly
// that, and a test that wants the compensation has it to name.
const ours = [];
addEventListener('openproj:ours', event => { ours.push(event.detail || null); });
const oursNow = () => ours.slice();

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


def _reaches(index: Index) -> dict[str, dict]:
    """What `GET /api/cascade/{id}` would answer for every record on the plan.

    **Derived by running the route's own function, and that is the point.** The
    sentences a reader decides on are `_cascade_facts`' (`render/detail.py`), and
    a harness that wrote them out again would be a second derivation of the one
    thing the route exists to have exactly one of — so every assertion below
    would be asking whether the page agrees with this file rather than with the
    plan. The route adds the record's own title beside the facts and this does
    the same, in the same words, through the same fallback.

    Every planned record and not the one a test presses on: which record has
    children, or is depended on, is a fact about `seed/`, and the tests choose by
    shape.
    """
    return {
        record_id: {
            "id": record_id,
            "title": _titles_for(index, [record_id])[0],
            **_cascade_facts(index, record_id),
        }
        for record_id in index.plan
    }


def _served(index: Index) -> str:
    """The plan's cascades, handed to the page as the stub's own answers."""
    return f"const REACH = {json.dumps(_reaches(index))};\n"


def _at_the_table(index: Index, where: Path, script: str, patience: int = 3000) -> dict:
    """One writer's table in Chrome, asked one question about the menu's writes."""
    return measured_in(
        chrome(),
        a_writers_table(index),
        where,
        1280,
        _OPENING + _READERS + _served(index) + _WRITING + script,
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


# **Cut 3's gated-status refusal is gone from here on purpose.** It drew every
# status whose `required_at` names a field the record has not got as a refusal,
# because there was no form to open; cut 4 opens one on exactly those fields with
# the new status already in its box, and
# `test_a_gated_status_opens_the_form_on_what_it_needs_and_saves_both` below is
# that same question asked of the behaviour that replaced it. What survives of
# the old branch is a missing field the form has no box for, and it is
# unreachable in this corpus: every field `required_at` names for every kind is
# in `POP_SCHEMA.fields` for that kind, measured 2026-09-18, so there is no row
# to press. `popNeeds` keeps its test in the assertion that the two maps still
# agree, at the top of the cut-4 section.


# --------------------------------------------------------------------------- #
# Priority
# --------------------------------------------------------------------------- #


_THE_RUNGS = """
const row = rowWhere(one => one.kind === 'task' && one.priority);
if (!row) return {error: 'the corpus holds no task with a priority'};
const other = POP_SCHEMA.priorities.find(one => one !== row.priority);
openOn(row.id);
const top = popKinds();
itemIn('priority').click();
const inside = popControls().map(one => ({
  kind: one.dataset.kind, role: one.getAttribute('role'), word: wordIn(one),
  glyph: partIn(one, 'popglyph'), mark: partIn(one, 'popmark'),
  checked: one.getAttribute('aria-checked')}));
const landed = document.activeElement.dataset.kind;
itemIn('priority-' + other).click();
await rest(700);
// And the rung it already has writes nothing at all.
openOn(row.id);
itemIn('priority').click();
itemIn('priority-' + other).click();
await rest(400);
// The rung a product does not read, which is the same refusal the owner item
// draws on one.
const product = rowWhere(one => one.kind === 'product');
let refused = null;
if (product) {
  openOn(product.id);
  const item = itemIn('priority');
  refused = {disabled: item.getAttribute('aria-disabled'), why: item.dataset.why || '',
             opens: item.getAttribute('aria-haspopup')};
}
return {id: row.id, title: row.title, was: row.priority, other, top, inside, landed,
        ladder: POP_SCHEMA.priorities, sent: patches(), said: said(),
        now: DATA.rows[row.id].priority, refused};
"""


def test_the_priority_submenu_is_the_one_ladder_and_picking_a_rung_writes_it(
    index: Index, tmp_path: Path
):
    """jcanton, 2026-09-18: *"in the right-click menu add priority just below
    status please, I didn't notice we didn't have it there"*.

    It is the status item's twin and the differences are the ladder's, not this
    menu's. `PRIORITIES` is one list for every kind, so there is nothing per-rung
    to look up; what varies is whether the kind reads the field at all, which is
    `unread_fields` — `priority` is in `_WORK_FIELDS`, so a product holds none
    and the item says so rather than disappearing. And no status demands a
    priority, so there is no gate and no form: every rung is writable on every
    record that reads the field.

    Asserted where he asked for it — **directly below Status** — because "add it
    to the menu" and "add it under the status" are two different asks and only
    one of them was made. The glyph is the rising block the chips and the graph's
    nodes draw, off the shell's own map, so a menu with a private ladder of marks
    fails here.

    And picking the rung it is already on writes nothing: the server would take
    it, but a commit is a line in somebody's history.
    """
    got = _at_the_table(index, tmp_path / "rungs.html", _THE_RUNGS, patience=5000)

    assert not got.get("error"), got
    assert got["ladder"] == list(PRIORITIES), got["ladder"]
    assert got["top"].index("priority") == got["top"].index("status") + 1, (
        f"priority is not the item under the status: {got['top']}"
    )
    inside = {one["kind"]: one for one in got["inside"]}
    assert [one["kind"] for one in got["inside"]] == ["back"] + [
        f"priority-{rung}" for rung in PRIORITIES
    ], got["inside"]
    for rung in PRIORITIES:
        one = inside[f"priority-{rung}"]
        assert one["word"] == HUMAN[rung], f"{rung} is drawn as {one['word']!r}"
        assert one["glyph"] == PRIORITY_GLYPH[rung], (
            f"{rung} carries {one['glyph']!r} and its mark on this plan is "
            f"{PRIORITY_GLYPH[rung]!r}"
        )
        assert one["role"] == "menuitemradio", (
            f"{rung} is a plain menuitem, where `aria-checked` is ignored"
        )
        current = rung == got["was"]
        assert one["checked"] == ("true" if current else "false"), one
        assert one["mark"] == ("•" if current else ""), one
    assert got["landed"] == f"priority-{got['was']}", (
        f"the keyboard landed on {got['landed']} rather than on the rung the record is on"
    )
    assert [one["body"]["fields"] for one in got["sent"]] == [{"priority": got["other"]}], (
        f"picking a rung and then picking it again sent {got['sent']}"
    )
    assert got["said"] == f"{got['title']} is already {HUMAN[got['other']]} priority", got["said"]
    assert got["now"] == got["other"], (
        "the row still reads the old priority, so the host was never told"
    )
    assert got["refused"], "the corpus draws no product, so the unread arm is untested"
    assert got["refused"]["disabled"] == "true", (
        f"a product's priority item is offered: {got['refused']}"
    )
    assert "product" in got["refused"]["why"], got["refused"]["why"]


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
# A second menu, opened while the first one's answer is still in the air
# --------------------------------------------------------------------------- #


_A_SECOND_MENU = """
const first = rowWhere(one => one.kind === 'task' && one.status === 'ready');
if (!first) return {error: 'the corpus holds no ready task to move'};
const otherRow = menuRows().find(tr => tr.dataset.id !== first.id);
if (!otherRow) return {error: 'the table drew only one row, so there is no second record'};
const second = {id: otherRow.dataset.id, title: DATA.rows[otherRow.dataset.id].title};
// A rule's own sentence, raised before anything is written — the same 409 shape
// `test_a_refusal_leaves_the_menu_up_saying_what_the_server_said` asks about.
const RULE = 'a project cannot be filed under a project and proj-000002 is under prod-0f0002';

// The answer HELD, which is the whole of the window this guard is about: a write
// here is a commit and a push against a repository on GitHub, so it is seconds,
// and this box stays up for all of them.
let release = null;
const holding = answer => {
  release = null;
  ANSWER = () => new Promise(done => { release = () => done(answer); });
};

// Dismissed the way a reader dismisses it — a press outside — and then a press
// on a DIFFERENT row. That is the ordinary way to open a second menu and it is
// the order a trusted right press produces: pointerdown, then contextmenu.
const moveToTheOtherRecord = () => {
  document.body.dispatchEvent(
    new PointerEvent('pointerdown', {bubbles: true, clientX: 5, clientY: 5}));
  openOn(second.id);
  return {open: popIsOpen(), about: popAbout(), kinds: popKinds(),
          label: POP.getAttribute('aria-label')};
};

const pressShapingOn = id => {
  openOn(id);
  itemIn('status').click();
  itemIn('status-shaping').click();
};

// --- a refusal, which DRAWS its sentence and takes the keyboard -------------
holding({status: 409, body: {detail: RULE}});
pressShapingOn(first.id);
await rest(150);
if (!release) return {error: 'the first press sent no PATCH, so nothing is in the air'};
const moved = moveToTheOtherRecord();
release();
await rest(700);
const refused = {open: popIsOpen(), about: popAbout(), kinds: popKinds(),
                 label: POP.getAttribute('aria-label'),
                 focused: document.activeElement.dataset.kind,
                 drawn: popControls().map(wordIn), said: said()};

// --- and a write that LANDS, which closes -----------------------------------
//
// Read inside the host's own `wrote()`, which is where `popWrite` goes
// immediately after the close it is gated on. The `openproj:wrote` in its
// `finally` carries a sha, and every open menu dies on one — this second box
// included, and rightly, because the tbody under it has just been replaced. So
// the end of the write is the one moment this half cannot be asked about.
let duringWrote = null;
const hostWrote = POP_HOST.wrote;
POP_HOST.wrote = async (answer, id) => {
  duringWrote = {open: popIsOpen(), about: popAbout()};
  return hostWrote(answer, id);
};
popClose();
holding({status: 200,
         body: {outcome: 'committed', commit: 'c0ffee9', pushed: true}});
pressShapingOn(first.id);
await rest(150);
if (!release) return {error: 'the second press sent no PATCH, so nothing is in the air'};
const movedAgain = moveToTheOtherRecord();
release();
await rest(900);
return {first: {id: first.id, title: first.title}, second, RULE,
        moved, refused, movedAgain, duringWrote,
        landed: {said: said(), base: baseNow(), open: popIsOpen()},
        sent: patches().map(one => one.url), beats: beatsNow()};
"""


def test_an_answer_to_one_menus_write_does_not_reach_the_menu_opened_after_it(
    index: Index, tmp_path: Path
):
    """**`POP_GEN`, and the two ways a stale answer lands in a box it is not
    about.**

    A write here is a commit and a push against a repository on GitHub, so it
    takes seconds, and this box stays up for every one of them. In that window a
    reader can dismiss it and right-click a different record — which is not an
    exotic race but the ordinary way to open a second menu, and the `pointerdown`
    listener in `pop.py` documents that exact sequence. `popWrite` therefore
    snapshots `POP_GEN` as `mine` before it sends, and the answer is applied only
    while the box on screen is still that same opening.

    Both halves are asked because they fail differently and neither is visible in
    the other:

    - a REFUSED write goes through `popSaid`, and `popSay` *draws* the sentence
      as the first item of whatever level is up and puts the keyboard on it. Into
      the second record's menu that is a true sentence about one record under the
      title of another, taking focus with it. It must still be announced, because
      a refusal nobody is told about is a write that looks like it worked — so
      the live region is asserted to carry it, which is also what proves the
      answer arrived at all and that the assertions above it are not vacuous.
    - a LANDED write ends in `popDone()`, which closes the box and gives the
      keyboard back. Ungated, that shuts the second record's menu under the
      reader's pointer.

    The landed half is measured inside the host's `wrote()`, and that is the only
    place it can be: `popWrite`'s `finally` dispatches `openproj:wrote` carrying
    the sha, and every open menu dies on one — the second box included, and
    correctly, because the tbody beneath it has just been replaced. `wrote()` is
    what `popWrite` awaits immediately after the close it is gated on, so it is
    the one moment where a box that was closed and a box that was left alone are
    two different answers.

    Driven both ways in headless Chrome on 2026-09-18, with the guards patched
    out of the rendered page as strings: with `popSaid` drawing unconditionally
    the second menu's first item was the refusal and `document.activeElement` was
    on it; with `popDone()` ungated the box measured closed inside `wrote()`.
    """
    got = _at_the_table(index, tmp_path / "second.html", _A_SECOND_MENU, patience=5000)

    assert not got.get("error"), got
    assert got["second"]["id"] != got["first"]["id"], got

    # The control for both halves: the second menu really is a second menu, about
    # the other record. Without this every assertion below is true of a page that
    # opened nothing the second time.
    for which, seen in (("refusal", got["moved"]), ("landed write", got["movedAgain"])):
        assert seen["open"] is True, f"no second menu opened during the {which}"
        assert seen["about"] == got["second"]["id"], (
            f"the second menu of the {which} is about {seen['about']} and it was "
            f"opened on {got['second']['id']}"
        )
        assert seen["label"] == f"Actions for {got['second']['title']}", seen

    assert got["refused"]["said"] == got["RULE"], (
        f"the refusal was not announced at all: the live region says "
        f"{got['refused']['said']!r}. A refusal nobody is told about is a write "
        "that looks like it worked — and if nothing was said, no answer came back "
        "and the assertions below are about nothing"
    )
    assert "said" not in got["refused"]["kinds"], (
        "the first write's refusal was drawn into the menu of a record it is not "
        f"about: {got['refused']['kinds']}"
    )
    assert got["RULE"] not in got["refused"]["drawn"], got["refused"]["drawn"]
    assert got["refused"]["kinds"] == got["moved"]["kinds"], (
        f"the second menu's items changed under an answer about {got['first']['id']}: "
        f"{got['moved']['kinds']} became {got['refused']['kinds']}"
    )
    assert got["refused"]["focused"] != "said", (
        "the first write's refusal took the keyboard inside the second record's menu"
    )
    assert got["refused"]["about"] == got["second"]["id"], got["refused"]
    assert got["refused"]["label"] == f"Actions for {got['second']['title']}", (
        f"the box renamed itself {got['refused']['label']!r} under the answer"
    )
    assert got["refused"]["open"] is True, "the refusal closed the second record's menu"

    assert got["duringWrote"] is not None, (
        "the host's `wrote()` never ran, so the landed half of this test never "
        "reached the moment it is written for"
    )
    assert got["duringWrote"]["open"] is True, (
        "a write that landed closed the menu somebody had opened on a different "
        "record while it was in the air — `popDone()` is gated on `POP_GEN === mine` "
        "for exactly this"
    )
    assert got["duringWrote"]["about"] == got["second"]["id"], got["duringWrote"]
    assert got["landed"]["said"] == f"{got['first']['title']} is now {HUMAN['shaping']}", (
        f"the write that landed announced {got['landed']['said']!r}"
    )
    assert got["landed"]["base"] == "c0ffee9", (
        f"`#base` is still {got['landed']['base']} after a commit"
    )
    assert got["landed"]["open"] is False, (
        "the second menu outlived an `openproj:wrote` carrying a sha, so it is "
        "pointing at a row in a tbody that has been replaced since it opened"
    )
    assert got["sent"] == [f"/api/record/{got['first']['id']}"] * 2, (
        f"the presses did not both write to {got['first']['id']}: {got['sent']}"
    )
    assert got["beats"] == {"writing": 2, "wrote": [None, "c0ffee9"]}, got["beats"]


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
    for refused in (*WRITE_ITEMS, DELETE_ITEM, "no-schema"):
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


# --------------------------------------------------------------------------- #
# Cut 4: the form, which is the answer to the question that started the design
#
# jcanton, 2026-09-18: *"I'd like to be able to right-click a record in table and
# graph view and have the option of creating a child record"*, and then *"can we
# make new-child stay on the same page? ... in both pages a new popup opens: the
# same as the floating menu but with editable fields (with parent pre-filled) and
# a save button that commits the new record?"* — and, of `Edit…`, that it should
# open that same editable card.
#
# The form is a THIRD FACE of `#pop`, not a third box, so half of what has to be
# asked here is about the box rather than about the fields: which face is up,
# what the box announces itself as while each one is, and — the one rule cut 2
# wrote that cut 4 changes — what does NOT take a half-filled form away.
# --------------------------------------------------------------------------- #


# How the form face is read. It is deliberately not how an item is read: a form
# is no `.popitem` at all, `popControls()` is empty while one is up, and every
# handle below is a `data-kind` slug or the `data-field` on a row — both of which
# `pop.py` documents. The visible words are copy and are asserted only where the
# copy is the claim.
_FORMS = """
const formIn = () => POP.querySelector('[data-kind="form"]');
const headingIn = () => {
  const said = POP.querySelector('[data-kind="form-heading"]');
  return said ? said.textContent : '';
};
// **The part of the card this field is drawn on**, which is one of three
// shapes: the title line, a chip on the chip line, or a row of the list. All
// three carry `data-field`, which is `cardHtml`'s own marker and the only thing
// this box finds a field by.
// `:not(input):not(select)`, because an OPEN control carries `data-field` too —
// it is how `document.activeElement.dataset.field` answers which box the
// keyboard is in — and a bare attribute selector would find the control inside
// the part as well as the part.
const PART = '[data-field="%"]:not(input):not(select)';
const fieldIn = name => POP.querySelector(PART.replace('%', name));
// The cell the value lives in: a list row's `<dd>`, and the part itself for the
// title and the chips, which have no inner box.
const cellIn = name => {
  const part = fieldIn(name);
  if (!part) return null;
  return part.matches('.card-fact') ? part.querySelector('dd') : part;
};
// The CONTROL, which exists only while this field is open. A card shows words;
// clicking one puts a box where the word was, and closing it takes the box away
// again — so `boxIn` answering `null` is the normal state and not a failure.
const boxIn = name => {
  const cell = cellIn(name);
  return cell ? cell.querySelector('input, select') : null;
};
// What the card SAYS this field is, as text. The value when nothing is open,
// and the control's own value when something is.
const valueIn = name => {
  const box = boxIn(name);
  if (box) return box.type === 'checkbox' ? String(box.checked) : box.value;
  const cell = cellIn(name);
  if (!cell) return '';
  // A chip's WORD, without the mark beside it. `↘In progress` is the glyph and
  // the word run together as text, and they are two facts with two readers —
  // the mark finds the rung and the word says which it is.
  const word = cell.querySelector('.chipword');
  return word ? word.textContent : cell.textContent;
};
// Click it, the way somebody does. Not `popOpenField(name)`: what is being
// asked is that the thing on screen is a thing you can press.
const openField = name => { fieldIn(name).click(); return boxIn(name); };
const fieldsInForm = () =>
  [...POP.querySelectorAll('[data-field]:not(input):not(select)')].map(one => one.dataset.field);
// Which of them can be opened at all, and which say why not.
const opensInForm = () =>
  [...POP.querySelectorAll('.popopens')].map(one => one.dataset.field);
const lockedInForm = () =>
  [...POP.querySelectorAll('.poplocked')].map(one => one.dataset.field);
// The field's NAME, without the mark the `<dt>` also carries when the status
// demands it. `''` when there is no name at all, which is a real answer and not
// a missing one: the title and the two chips are drawn the way the card draws
// them, with nothing over them, and a helper that threw there would make "this
// field carries no visible name" the one claim these tests could not state.
const nameIn = name => {
  const part = fieldIn(name);
  const term = part && part.matches('.card-fact') ? part.querySelector('dt') : null;
  return term ? [...term.childNodes]
    .filter(one => one.nodeType === 3).map(one => one.textContent).join('') : '';
};
const markIn = name => {
  const part = fieldIn(name);
  const star = part ? part.querySelector('.popreq') : null;
  return star ? star.textContent : '';
};
// Why a field will not open. On the element rather than under it: a card has no
// room for a paragraph per row.
const noteIn = name => {
  const part = fieldIn(name);
  return part ? (part.title || '') : '';
};
const optionsIn = name =>
  [...boxIn(name).options].map(one => ({value: one.value, text: one.textContent}));
const whyLines = () =>
  [...POP.querySelectorAll('[data-kind="form-why-line"]')].map(one => one.textContent);
const saveIn = () => POP.querySelector('[data-kind="form-save"]');
const cancelIn = () => POP.querySelector('[data-kind="form-cancel"]');
// Which fields have a control on them right now. A card's values are words until
// they are pressed, so this is normally empty — what is in it is what the box
// opened on, or what somebody has clicked.
const opensNow = () =>
  [...POP.querySelectorAll('[data-field] input, [data-field] select')]
    .map(one => one.dataset.field);
// **Whether a form is on screen, which is not the same question as whether one
// is in the box.** `popClose` deliberately leaves the children where they are —
// `.drawmenu` cleared its own on close because it had no `[hidden]` rule, and
// this box has one — so `POP.querySelector('[data-kind="form"]')` answers a
// dismissed form exactly as it answers a live one, and every `the form closed`
// assertion written against it would pass with the form still up.
const formUp = () => popIsOpen() && POP.classList.contains('popforming');
// Which face the box is wearing, in the four ways it says so. `items: 0` is the
// one worth having: a box that drew a form and left its menu items underneath is
// a `role="dialog"` full of `menuitem`s, and nothing else here would notice.
const formIsUp = () => ({up: formUp(), role: POP.getAttribute('role'),
                         items: popControls().length, form: !!formIn()});
// Typed the way a person types: the value, and then the two events a control
// fires. `change` is the one the form listens to — it re-marks the required
// fields and re-places the box — so a test that assigned `.value` alone would be
// asking about a form nobody had touched.
const typeInto = (name, value) => {
  const box = boxIn(name) || openField(name);
  if (box.type === 'checkbox') box.checked = !!value;
  else box.value = value;
  box.dispatchEvent(new Event('input', {bubbles: true}));
  box.dispatchEvent(new Event('change', {bubbles: true}));
  return box;
};
// Typed, and then finished with. **Blur is what commits**, on a live box as one
// PATCH and on a staged one into what the button will send — the table's own
// bargain, and `Enter` reaches it by blurring. Written as a helper because
// every test that changes a value has to say where the value went.
const answer = (name, value) => { typeInto(name, value); boxIn(name).blur(); };
// And typed, then given up on. Escape must not bubble: `popClose` is listening
// for it on the way up, and a test that dispatched a bubbling one would be
// asking about the box closing rather than about the field reverting.
const giveUp = name => boxIn(name).dispatchEvent(
  new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
// The press, and not a call to `popSave()`. The button is `type="submit"` inside
// a real `<form>`, so what is being asked is that the browser's own submit
// reaches the handler — which is also the whole of the keyboard's path through
// this box, since Enter in any field submits and nothing else here would say so.
const pressSave = () => saveIn().click();
// A record and a status it cannot be given as it stands, SEARCHED rather than
// named: which rung this corpus can ask that about is a fact about `seed/`,
// which is the demo and is free to be rewritten. `popMissing` is the module's
// own reading of `required_at`, which is itself derived by running the gate over
// a blank record — so what comes back is the rule and not a copy of it.
const shortOf = least => {
  for (const status of POP_SCHEMA.statuses.task) {
    const row = rowWhere(one => one.kind === 'task' && one.status !== status
                                && popMissing(one, status).length >= least);
    if (row) return {row: row, gate: status, missing: popMissing(row, status)};
  }
  return null;
};
"""


# What `fieldsInForm()` reads in, given a kind's editable fields.
#
# The form is the hover card, so it draws what the card draws: the title line,
# then the chip line, then the `<dl>`. Three fields therefore come out of the
# schema's order and go to the front in the card's own — kind, priority, status
# is `cardHtml`'s chip order and jcanton's, from 2026-08-21.
def _the_cards_order(schema: list[str]) -> list[str]:
    face = [name for name in ("title", "priority", "status") if name in schema]
    return face + [name for name in schema if name not in face]


def _at_a_form(
    index: Index, where: Path, script: str, patience: int = 3500, tall: int = 900
) -> dict:
    """One writer's table in Chrome, asked one question about the form.

    `tall` is a parameter for the reason `measured_in` has one: `placeFloat`
    flips a box against the bottom gutter, so where a form ends up is a fact
    about the window and one window is the one thing that cannot show it.
    """
    return measured_in(
        chrome(),
        a_writers_table(index),
        where,
        1280,
        _OPENING + _READERS + _served(index) + _WRITING + _FORMS + script,
        height=tall,
        patience=patience,
    )


# --------------------------------------------------------------------------- #
# `New child ▸`, which is the item that was asked for
# --------------------------------------------------------------------------- #


_CHILD_KINDS = """
const seen = {};
// Every rung a plan view draws, asked for its own list. Which kinds those are
// comes off the payload rather than out of a list here, and what each may hold
// comes off `POP_SCHEMA.child_kinds` — the model's own `CHILD_KINDS`. The claim
// is that the MENU offers what the ladder says, not that either agrees with a
// list somebody typed into a test.
const drawn = [...new Set(Object.values(DATA.rows).map(one => one.kind))];
for (const kind of drawn) {
  const row = rowWhere(one => one.kind === kind);
  openOn(row.id);
  const item = itemIn('new-child');
  const at = {word: wordIn(item), mark: partIn(item, 'popmark'),
              haspopup: item.getAttribute('aria-haspopup'),
              disabled: item.getAttribute('aria-disabled'), why: item.dataset.why || ''};
  item.click();
  at.said = said();
  // One level down, or still at the top: a refused item answers and the box
  // stays exactly where it was, which is a different thing from drilling into an
  // empty list and is the difference this reads.
  at.depth = POP_STACK.length;
  at.label = POP.getAttribute('aria-label');
  at.inside = popControls().map(one => ({kind: one.dataset.kind, word: wordIn(one)}));
  seen[kind] = at;
  popClose();
}
// And the two rungs no plan view draws a row for. `issue` and `note` are
// `planned: false`, so there is no row to press on any of the three hosts and
// the item builder itself is the only place the question can be put — which is
// worth doing, because "nothing is filed inside one" is exactly the answer a
// menu that inverted `parent_kinds` in the browser would get wrong for them.
const unplanned = {};
for (const kind of Object.keys(POP_SCHEMA.child_kinds).filter(one => !drawn.includes(one)))
  unplanned[kind] = popNewChildItem({id: kind + '-000001', kind: kind, title: 'Off the plan'});
return {seen, unplanned, drawn, child: POP_SCHEMA.child_kinds,
        sent: patches().length + posts().length};
"""


def test_new_child_offers_exactly_the_kinds_that_rung_may_hold(index: Index, tmp_path: Path):
    """One entry per kind this record may hold, and a sentence where there are
    none.

    The list is `CHILD_KINDS` — the model's own map, read downwards — and not an
    inversion of `parent_kinds` done in the browser. A third spelling of the
    ladder in the one language nothing here tests it in is the drift the whole
    schema exists to stop, and the two maps are already held to being exact
    inverses in `test_the_ladder_reads_the_same_in_both_directions`.

    **A rung that holds nothing is refused and not left out**, and the sentence
    is about the LADDER rather than about this record: nothing is ever filed
    inside a task, so "this one has no children yet" would imply a fix that does
    not exist. That is `moveTip`'s distinction (`table.py`) for the drag gesture,
    made again for the same records.

    A task is the one a plan view can be pressed on. An issue and a note hold
    nothing either and are `planned: false`, so no host draws a row for one — the
    item builder is asked directly, which is the only place that question exists.
    """
    got = _at_a_form(index, tmp_path / "children.html", _CHILD_KINDS)

    assert not got.get("error"), got
    assert len(got["drawn"]) >= 3, (
        f"the table draws only {got['drawn']}, so this asks about one branch of the ladder"
    )
    holding = [kind for kind in got["drawn"] if got["child"][kind]]
    empty = [kind for kind in got["drawn"] if not got["child"][kind]]
    assert holding and empty, (
        f"every rung on this table {'holds' if holding else 'holds nothing'}, so only one "
        f"branch of this test is reachable: {got['child']}"
    )
    for kind in holding:
        at = got["seen"][kind]
        assert at["word"] == "New child", at
        assert at["haspopup"] == "menu", (
            f"a {kind}'s New child is not announced as opening a list: {at}"
        )
        assert at["mark"] == "›", f"a {kind}'s New child draws {at['mark']!r} behind the word"
        assert at["disabled"] is None, f"a {kind} may hold {got['child'][kind]} and was refused"
        assert at["depth"] == 2, f"pressing New child on a {kind} did not drill: {at}"
        assert at["label"] == "New child", at["label"]
        assert [one["kind"] for one in at["inside"]] == [
            "back",
            *[f"new-child-{child}" for child in got["child"][kind]],
        ], at["inside"]
        assert [one["word"] for one in at["inside"][1:]] == [
            HUMAN[child] for child in got["child"][kind]
        ], (
            f"a {kind}'s children are drawn {[one['word'] for one in at['inside'][1:]]} — the "
            "words are `HUMAN`'s, or this menu has a vocabulary of its own"
        )
    for kind in empty:
        at = got["seen"][kind]
        assert at["disabled"] == "true", f"a {kind} holds nothing and its New child acts: {at}"
        assert at["why"] == f"Nothing is filed inside a {kind}.", at["why"]
        assert at["said"] == at["why"], (
            f"pressing a {kind}'s refused New child announced {at['said']!r}"
        )
        assert at["depth"] == 1, (
            f"a refused New child drilled into an empty list on a {kind}: {at}"
        )
    for kind, item in got["unplanned"].items():
        assert got["child"][kind] == [], (
            f"{kind} holds {got['child'][kind]} and no view draws a row for one, so this "
            "half of the test is asking about the wrong rungs"
        )
        assert item["why"] == f"Nothing is filed inside a {kind}.", item
    assert got["sent"] == 0, "opening the New child list wrote to the plan"


_NEW_CHILD_FORM = """
const parent = rowWhere(one => (POP_SCHEMA.child_kinds[one.kind] || []).length);
if (!parent) return {error: 'no row on this table may hold anything'};
const kind = POP_SCHEMA.child_kinds[parent.kind][0];
openOn(parent.id);
itemIn('new-child').click();
itemIn('new-child-' + kind).click();
// Clicked, the way somebody does. A locked field must answer the press by not
// opening — that is the whole of what "locked" means on a card whose values are
// words until you press one.
fieldIn('parent').click();
const first = document.activeElement;
return {parent: {id: parent.id, title: parent.title, kind: parent.kind}, kind,
        up: formIsUp(), heading: headingIn(), label: POP.getAttribute('aria-label'),
        fields: fieldsInForm(), schema: POP_SCHEMA.fields[kind],
        opens: opensInForm(), locked: lockedInForm(),
        parentSays: valueIn('parent'), parentBox: !!boxIn('parent'),
        note: noteIn('parent'),
        status: valueIn('status'), at: POP_SCHEMA.opens[kind],
        title: valueIn('title'),
        verb: saveIn().textContent, cancel: cancelIn().textContent,
        focused: {field: first.dataset.field, tag: first.tagName},
        why: whyLines(), hidden: POP.querySelector('[data-kind="form-why"]').hidden,
        sent: patches().length + posts().length};
"""


def test_new_child_opens_the_form_with_the_parent_filled_and_locked(index: Index, tmp_path: Path):
    """The box's third face: `role="dialog"`, a blank card of this kind, and not
    one `.popitem` left underneath it.

    **A record that does not exist cannot be written one field at a time**, so
    this is the box's staged half: what you answer is held in it and one button
    sends the lot. `POST /api/record` takes the whole record, which is the whole
    of the reason — and the box looks exactly like the live one, because it is
    the same card.

    **The parent is filled and locked, and the lock is drawn rather than
    hidden.** It is not a choice — it is the record the menu was opened on, and
    offering it again is the gesture said twice — so the row is there, saying
    which record, refusing to open, with the sentence on it saying why. A row
    that disappears teaches nothing about why, which is the same rule that draws
    a refused item instead of leaving it out.

    Three things beside it are asserted because each is a lie the box could tell
    instead. The fields are `POP_SCHEMA.fields[kind]` — per kind, off
    `_editable_for`, so it cannot offer a field the validator then complains
    about. The status chip says `opens_at(kind)` rather than nothing, which is
    both a required field answered and the box not lying about what Create will
    write. And the keyboard lands in Title, open and waiting — never the locked
    parent and never `<body>` — because a title is the one thing the record
    cannot be created without.
    """
    got = _at_a_form(index, tmp_path / "newchild.html", _NEW_CHILD_FORM)

    assert not got.get("error"), got
    assert got["up"] == {"up": True, "role": "dialog", "items": 0, "form": True}, got["up"]
    wanted = f'New {HUMAN[got["kind"]].lower()} in "{got["parent"]["title"]}"'
    assert got["heading"] == wanted, got["heading"]
    assert got["label"] == wanted, (
        f"the box announces itself as {got['label']!r} while it is a form — a reader "
        "arriving inside it is told which menu they are in"
    )
    assert got["fields"] == _the_cards_order(got["schema"]), (
        f"the form drew {got['fields']} and this kind's editable fields, in the order the "
        f"card draws them, are {_the_cards_order(got['schema'])}"
    )
    assert got["parentSays"] == got["parent"]["title"], (
        f"the parent row says {got['parentSays']!r} and the menu was opened on "
        f"{got['parent']['title']!r} — `New child` means this record and no other"
    )
    assert "parent" in got["locked"] and "parent" not in got["opens"], (
        f"the parent of a new child can be changed: opens {got['opens']}, locked {got['locked']}"
    )
    assert got["parentBox"] is False, (
        "pressing the locked parent opened a control in it, so the lock is a class and "
        "not a rule"
    )
    assert got["note"] == (
        f'Filed under "{got["parent"]["title"]}", which is what New child means.'
    ), got["note"]
    assert got["status"] == HUMAN[got["at"]], (
        f"the status chip says {got['status']!r} and this kind opens at {got['at']!r} — "
        "nothing there is a required field the reader has to fill before they have said "
        "anything, and a box lying about what Create writes"
    )
    assert got["verb"] == f"Create {HUMAN[got['kind']].lower()}", got["verb"]
    assert got["cancel"] == "Cancel"
    assert got["focused"] == {"field": "title", "tag": "INPUT"}, (
        f"the keyboard landed on {got['focused']}, and the one field a record cannot be "
        "created without is Title — open, because a blank card with nothing to type in is "
        "a card"
    )
    assert got["title"] == "", f"the title of a record nobody has named reads {got['title']!r}"
    assert got["why"] == [] and got["hidden"] is True, (
        "the refusal list is drawn over a form nobody has pressed Save on yet"
    )
    assert got["sent"] == 0, "opening a form wrote to the plan"


_CREATING = """
const parent = rowWhere(one => (POP_SCHEMA.child_kinds[one.kind] || []).length);
if (!parent) return {error: 'no row on this table may hold anything'};
const kind = POP_SCHEMA.child_kinds[parent.kind][0];
const title = 'A child made from the menu';
openOn(parent.id);
itemIn('new-child').click();
itemIn('new-child-' + kind).click();
answer('title', title);
// **A parent staged behind the lock's back**, which is what makes the assertion
// on the POST below a claim about the rule rather than about a row nobody
// touched. The locked row will not open, so this reaches past it and writes the
// answer straight into what the button sends: `popCreated` takes the parent from
// the ROW the menu was opened on and never from there, and that is the whole of
// what `New child` means.
const stray = Object.values(DATA.rows).find(one => one.id !== parent.id
  && (POP_SCHEMA.parent_kinds[kind] || []).includes(one.kind));
if (!stray) return {error: 'the corpus holds no second record that could hold this kind'};
POP_FORM.values.parent = stray.id;
pressSave();
const during = {disabled: saveIn().disabled, said: said(), posts: posts().length};
await rest(1000);
const id = Object.keys(MADE)[0] || null;
return {parent: {id: parent.id, title: parent.title}, kind, title, stray: stray.id, id,
        opens: POP_SCHEMA.opens[kind], during,
        sent: posts(), patched: patches().length,
        said: said(), closed: !popIsOpen(), form: formUp(),
        row: id ? DATA.rows[id] : null,
        drawn: id ? menuRows().some(tr => tr.dataset.id === id) : false,
        made: Object.keys(MADE).length, base: baseNow(), beats: beatsNow()};
"""


def test_saving_the_form_creates_the_record_under_the_record_it_was_opened_on(
    index: Index, tmp_path: Path
):
    """One POST, and every key in it accounted for.

    **Empty is not a value on a create**, which is why the body is asserted whole
    rather than by containment: `opening_fields` (`model.py`) is what decides what
    a new record starts life with, and a form that sent `owner: null` for every
    box nobody filled would write an empty key into the file for each of them, in
    a corpus whose whole premise is that the file is the document. So the payload
    is the kind, the title somebody typed, the status the box was opened holding,
    and the parent — and nothing else, out of fifteen controls.

    **The parent is the row the menu was opened on**, and this test forces the
    box to say otherwise before pressing Save: a different record's id is staged
    behind the lock's back, which is the nearest a card whose locked row will not
    open can be got to tampering. A box that read what it was holding would file
    the record under the stray, and it is the one defect here that no reading of
    the DOM can see afterwards.

    The rest is the receipt. `popLanded` names the title AND the id — the id was
    minted a moment ago and nobody has seen it, the title is the half the person
    who typed it recognises — and with nothing filtered the record is on screen,
    so the sentence makes no claim about where it went. The half that says
    otherwise is `test_a_child_created_under_a_filter_says_where_it_went`.
    """
    got = _at_a_form(index, tmp_path / "creating.html", _CREATING)

    assert not got.get("error"), got
    assert len(got["sent"]) == 1, got["sent"]
    assert got["patched"] == 0, "a create went out as a PATCH as well"
    assert got["sent"][0]["url"] == "/api/record", got["sent"][0]
    assert got["sent"][0]["body"] == {
        "base_commit": HEAD,
        "fields": {
            "kind": got["kind"],
            "title": got["title"],
            "status": got["opens"],
            "parent": got["parent"]["id"],
        },
        "body": None,
    }, got["sent"][0]["body"]
    assert got["sent"][0]["body"]["fields"]["parent"] != got["stray"], (
        "the record was filed under the staged id rather than under the record the menu "
        "was opened on"
    )
    assert got["during"]["posts"] == 1, "the press sent no create at all"
    assert got["during"]["disabled"] is True, (
        "Save is still pressable while the commit is in the air, which is how two "
        "presses 0.9s apart minted two records on the deployed service"
    )
    assert "Creating" in got["during"]["said"], (
        f"nothing was said while the commit was in the air: {got['during']['said']!r} — two "
        "seconds of a box that looks untouched is what taught somebody to press Create twice"
    )
    assert got["made"] == 1 and got["id"], got
    assert got["form"] is False and got["closed"] is True, (
        "the form outlived the commit that landed, over a table that has just been redrawn"
    )
    assert got["row"], "the host never found the record it had just made"
    assert got["row"]["title"] == got["title"], got["row"]
    assert got["row"]["parent"] == got["parent"]["id"], got["row"]
    assert got["row"]["kind"] == got["kind"], got["row"]
    assert got["drawn"] is True, (
        "the new record is in `DATA.rows` and not in the tbody: `wrote()` re-read the "
        "plan and nothing drew from it"
    )
    assert got["said"] == f"Created {got['title']} ({got['id']})", got["said"]
    assert got["base"] == "c0ffee1", (
        f"`#base` is still {got['base']} after a create, so the next write from this page "
        "collides with the commit it just made"
    )
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


_TWICE_ON_SAVE = """
const parent = rowWhere(one => (POP_SCHEMA.child_kinds[one.kind] || []).length);
if (!parent) return {error: 'no row on this table may hold anything'};
const kind = POP_SCHEMA.child_kinds[parent.kind][0];
// The answer HELD, which is the whole of the state this guard is about: a write
// here is a commit and a push against a repository on GitHub, so it is seconds,
// and the form stays up for all of them with Save under the pointer.
let release = null;
ANSWER = seen => new Promise(done => {
  release = () => done({status: 201, body: {id: nextId(seen.body.fields.kind),
    outcome: 'committed', commit: 'c0ffee1', pushed: true}});
});
openOn(parent.id);
itemIn('new-child').click();
itemIn('new-child-' + kind).click();
answer('title', 'Pressed twice');
pressSave();
const held = {disabled: saveIn().disabled, posts: posts().length};
// Twice more, by both routes. The button is how a pointer repeats it; the submit
// is Enter's path and the one that reaches `popSave` PAST a disabled button —
// which is why the rule is a flag and the attribute is only how it is shown.
pressSave();
formIn().dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
await rest(250);
const during = {posts: posts().length, why: whyLines(), form: formUp(),
                open: popIsOpen(), title: valueIn('title'), writing: beats.writing};
if (!release) return {error: 'the first press sent no create, so nothing is in the air'};
release();
await rest(1000);
return {parent: parent.id, kind, held, during, posts: posts(),
        made: Object.keys(MADE), said: said(), closed: !popIsOpen(), beats: beatsNow()};
"""


def test_two_presses_on_save_with_no_gap_create_one_record(index: Index, tmp_path: Path):
    """**`POST /api/record` is not idempotent, and that is the whole difference
    from every other write this menu makes.**

    `CREATING` exists in `table.py` because two presses 0.9s apart minted two
    records on the deployed service. A PATCH repeated is the same write — same
    value, same base, and `_merge_frontmatter` skips a key whose stored value
    already equals the one being sent — so the advice after a lost answer is "try
    it again". A create repeated is a second record, and the advice has to be to
    go and look first.

    So the second press is refused, and it is refused by both routes: the button
    is disabled while the commit is in the air, and `POP_WRITING` catches
    everything that does not go through the button. The submit dispatched here is
    Enter's path, which is exactly that — a form whose only guard was the
    attribute would pass the first assertion and mint a second record from the
    keyboard.

    And the refusal is DRAWN, into the form's own list, rather than only
    announced: the reader is looking at the box, and a refusal only a screen
    reader hears is a Save that looks like it did nothing at all.

    The answer is held rather than raced. Against an answer that came back
    immediately this would be asking nothing, because the guard is only ever true
    while a write is in the air.
    """
    got = _at_a_form(index, tmp_path / "twicesave.html", _TWICE_ON_SAVE, patience=4500)

    assert not got.get("error"), got
    assert got["held"] == {"disabled": True, "posts": 1}, got["held"]
    assert got["during"]["posts"] == 1, (
        f"{got['during']['posts']} creates went out for three presses of one Save"
    )
    assert got["during"]["writing"] == 1, (
        "a refused press dispatched `openproj:writing` before it was refused, so the "
        "shell's count is held one too high for the rest of the page's life"
    )
    assert got["during"]["why"] == ["A save is already going out. Wait for it to answer."], (
        f"the second press was refused in silence, or somewhere else: {got['during']['why']}"
    )
    assert got["during"]["form"] is True, "the box went down before the answer arrived"
    assert got["during"]["title"] == "Pressed twice", (
        "the refusal rebuilt the form and lost what was typed into it"
    )
    assert len(got["posts"]) == 1, got["posts"]
    assert len(got["made"]) == 1, (
        f"the plan holds {len(got['made'])} new records after one person pressed Create: "
        f"{got['made']}"
    )
    assert got["closed"] is True
    assert got["said"].startswith("Created "), got["said"]
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


# --------------------------------------------------------------------------- #
# `Edit…`, which is the same face opened on a record that exists
# --------------------------------------------------------------------------- #


_EDITING = """
const row = rowWhere(one => one.kind === 'task' && one.status && one.title);
if (!row) return {error: 'the corpus draws no task'};
const somebody = POP_SCHEMA.people.find(login => login !== row.owner);
if (!somebody) return {error: 'the corpus knows only one person'};
openOn(row.id);
const item = itemIn('edit');
const word = wordIn(item);
item.click();
const opened = {up: formIsUp(), heading: headingIn(), fields: fieldsInForm(),
                schema: POP_SCHEMA.fields[row.kind],
                opens: opensInForm(), locked: lockedInForm(),
                save: saveIn() ? saveIn().textContent : '',
                cancel: cancelIn() ? cancelIn().textContent : '',
                boxes: POP.querySelectorAll('input, select').length,
                says: {}, held: {}, names: {}};
for (const name of fieldsInForm()) {
  opened.says[name] = valueIn(name);
  opened.names[name] = nameIn(name);
}
opened.note = noteIn('depends_on');
// Every field opened and read back, one at a time, then given up on. The round
// trip is the claim: a value this card renders one way and reads another shows
// up here as a control holding something the record does not.
for (const name of opensInForm()) {
  const box = openField(name);
  opened.held[name] = box.type === 'checkbox' ? box.checked : box.value;
  giveUp(name);
}
const quiet = {sent: patches().length, form: formUp(), boxes: POP.querySelectorAll('input').length};
// Two fields answered in one visit, and nothing sent while they are answered.
// This is the whole of what the button buys: the card that wrote on blur sent a
// PATCH per field and wrote a commit per field with it.
const title = row.title + ' (edited from the menu)';
typeInto('title', title);
typeInto('owner', somebody);
const staged = {sent: patches().length, open: opensNow(), title: valueIn('title')};
pressSave();
await rest(1000);
const landed = {sent: patches(), posted: posts().length, said: said(), open: popIsOpen(),
                form: formUp(), base: baseNow(),
                title: DATA.rows[row.id].title, owner: DATA.rows[row.id].owner};
// And the other way out. Nothing typed into a box that is cancelled reaches the
// plan, which is what the word promises.
openOn(row.id);
itemIn('edit').click();
typeInto('title', 'typed into a box that was cancelled');
cancelIn().click();
await rest(300);
const cancelled = {sent: patches().length, open: popIsOpen(), said: said(),
                   title: DATA.rows[row.id].title};
return {id: row.id, was: row, title, somebody, word, opened, quiet, staged, landed,
        cancelled, beats: beatsNow()};
"""


def test_edit_opens_on_the_record_and_one_save_commits_what_was_answered(
    index: Index, tmp_path: Path
):
    """**`Edit…` opens the hover card, and every value on it is a word until you
    press it.** Then that one word is a box, Escape puts the word back, and
    **Save is what writes** — all of what was answered, in one commit.

    It used to write each field as it was answered, which is `openEditor`'s
    bargain in the table and is what jcanton asked for on 2026-09-18: "it could
    be like the table where you have to click one field to enter edit mode for
    that field?". Later the same day, having met the other box — the one a gated
    status opens, which has always held its answers and had a Save — he asked for
    one bargain rather than two: *"this card has the save/cancel buttons at the
    bottom, while the card that shows up when selecting the edit menu doesn't and
    commits on each field change. I'd like them to be consistent, and I think I'd
    prefer them both to have the save/cancel buttons and save only when clicking
    save, not on every edit as I asked before."*

    So there is **no box on a card nobody has clicked** — that is the assertion
    that tells this apart from the form it replaced, and the way to make it from
    the DOM is to count the controls before anything is pressed — and there IS a
    Save and a Cancel under it, which is the half that changed.

    **One PATCH for the visit, naming only what moved.** `_merge_frontmatter`
    would skip a key whose stored value already equals the one being sent, so a
    whole-card payload would commit the same thing — but the commit MESSAGE names
    the fields, and a line saying fifteen fields were written when two were is a
    line in somebody's history that is not true. `git log --follow` on a record is
    one of the two ways this plan is read.

    Every field is opened and read back here, which makes the round trip a claim
    rather than an accident: a list joined with the wrong separator, a number that
    came back a string, a date box reporting something other than what it was
    given — each is a silent rewrite of a field the reader never looked at, and
    each fails on `held` below.

    **`depends_on` will not open, and that is the single most useful thing the
    per-kind schema produced.** `_row` (`rows.py`) ships `blocked_by` — a COUNT —
    and no `depends_on` at all, while the graph's node data carries the list,
    because `_elements` adds it. A card that opened a box there would show an
    empty list over a record with three dependencies on this view, and anything
    typed REPLACES them. The rule asks `name in row` rather than carrying a list
    of field names, so the same code locks a row on one host and opens it on the
    other.
    """
    got = _at_a_form(index, tmp_path / "editing.html", _EDITING, patience=4500)

    assert not got.get("error"), got
    was = got["was"]
    assert got["word"] == "Edit…", got["word"]
    assert got["opened"]["up"] == {
        "up": True,
        "role": "dialog",
        "items": 0,
        "form": True,
    }, got["opened"]["up"]
    assert got["opened"]["heading"] == f'Edit "{was["title"]}"', got["opened"]["heading"]
    assert got["opened"]["boxes"] == 0, (
        f"the card opened with {got['opened']['boxes']} controls already on it — a card is "
        "words, and a box of controls is the form this replaced"
    )
    assert (got["opened"]["save"], got["opened"]["cancel"]) == ("Save", "Cancel"), (
        f"the box offers {got['opened']['save']!r} and {got['opened']['cancel']!r} — both "
        "cards carry the same pair, which is what was asked for"
    )
    assert got["opened"]["fields"] == _the_cards_order(got["opened"]["schema"]), (
        f"the card drew {got['opened']['fields']} and this kind's editable fields, in the "
        f"order the card draws them, are {_the_cards_order(got['opened']['schema'])}"
    )
    says = got["opened"]["says"]
    assert says["title"] == was["title"], says["title"]
    assert says["status"] == HUMAN[was["status"]], (
        f"the status chip says {says['status']!r} and the record is {was['status']!r} — the "
        "card spells a rung the way every other page does"
    )
    held = got["opened"]["held"]
    # Spelled out per type rather than run through the module's own `popRawOf`,
    # which would be the test agreeing with the code it is asking about.
    assert held["title"] == was["title"], held["title"]
    assert held["status"] == was["status"], held
    assert held["priority"] == (was["priority"] or ""), held
    assert held["owner"] == (was["owner"] or ""), held
    assert held["assignees"] == ", ".join(was["assignees"] or []), held
    assert held["review_waived"] is bool(was["review_waived"]), held
    assert held["start_date"] == (was["start_date"] or ""), held
    assert got["opened"]["names"]["person_weeks"] == LABELS["person_weeks"], (
        "the card names a field by its own key rather than by the one word the whole "
        f"app calls it: {got['opened']['names']['person_weeks']!r}"
    )
    assert got["opened"]["names"]["title"] == "", (
        "the title line carries a name, and on a card it carries none"
    )
    assert "depends_on" in got["opened"]["locked"], (
        "the table carries `blocked_by`, a count, and no `depends_on` — so a box opened "
        "there is drawn empty over a record that has dependencies, and blur deletes them"
    )
    assert "depends_on" not in got["opened"]["opens"], got["opened"]["opens"]
    assert got["opened"]["note"] == (
        "This view does not carry it — edit it on the record's own page."
    ), got["opened"]["note"]
    assert got["quiet"]["sent"] == 0, (
        "opening every field and giving each one up wrote to the plan"
    )
    assert got["quiet"]["boxes"] == 0, "Escape left the control where the value should be"
    assert got["quiet"]["form"] is True, "Escape on a field took the whole box down"
    assert got["staged"]["sent"] == 0, (
        "a field answered went out as a PATCH before Save was pressed, which is the "
        "bargain this box gave up"
    )
    assert sorted(got["staged"]["open"]) == ["owner", "title"], (
        f"the second field was answered and the first closed: {got['staged']['open']}. A "
        "box that shuts a control when the next one opens loses the answer in it"
    )
    assert got["staged"]["title"] == got["title"], got["staged"]["title"]
    assert len(got["landed"]["sent"]) == 1, (
        f"two fields answered in one visit went out as {len(got['landed']['sent'])} "
        "writes, which is as many commits"
    )
    assert got["landed"]["posted"] == 0, "editing a record that exists went out as a create"
    assert got["landed"]["sent"][0]["url"] == f"/api/record/{got['id']}", got["landed"]["sent"][0]
    assert got["landed"]["sent"][0]["body"] == {
        "base_commit": HEAD,
        "fields": {"title": got["title"], "owner": got["somebody"]},
        "body": None,
    }, (
        "the write sent something other than the two fields that were answered — every "
        f"other field on the card is in the commit message: {got['landed']['sent'][0]['body']}"
    )
    assert got["landed"]["said"] == (
        f"{was['title']}: {LABELS['title']} and {LABELS['owner']} saved"
    ), got["landed"]["said"]
    assert got["landed"]["open"] is False and got["landed"]["form"] is False, (
        "the box stayed up after its Save landed — one press is the whole gesture, and "
        "the row it was drawn from has just been replaced"
    )
    assert got["landed"]["base"] == "c0ffee1"
    assert (got["landed"]["title"], got["landed"]["owner"]) == (got["title"], got["somebody"]), (
        "the row still reads the old values after its own write"
    )
    assert got["cancelled"]["sent"] == 1, (
        "Cancel wrote what was typed into the box, which is the whole of what the word "
        "promises not to do"
    )
    assert got["cancelled"]["open"] is False, "Cancel left the box up"
    assert got["cancelled"]["said"] == "nothing was changed", got["cancelled"]["said"]
    assert got["cancelled"]["title"] == got["title"], (
        "a cancelled box changed the record it was opened on"
    )
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


_ENTER_TAKES = """
const row = rowWhere(one => one.kind === 'task' && one.title && one.status);
if (!row) return {error: 'the corpus draws no task'};
const somebody = POP_SCHEMA.people.find(login => login !== row.owner);
if (!somebody) return {error: 'the corpus knows only one person'};
openOn(row.id);
itemIn('edit').click();
const title = row.title + ' (typed, then entered)';
typeInto('title', title);
typeInto('owner', somebody);
// Enter, the way a browser delivers it. The return of `dispatchEvent` is the
// claim that it was answered here: an Enter left alone reaches the `<form>` this
// control sits in, which has a `type="submit"` button in it.
const enter = name => !boxIn(name).dispatchEvent(
  new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
const stopped = enter('title');
const taken = {stopped, sent: patches().length, form: formUp(),
               box: !!boxIn('title'), says: valueIn('title'), open: opensNow(),
               owner: boxIn('owner') ? boxIn('owner').value : null,
               where: document.activeElement.dataset.field || ''};
// The other one, which leaves nothing open — so the keyboard has to land
// somewhere inside the box or the next Escape reaches nothing.
enter('owner');
const both = {sent: patches().length, open: opensNow(), owner: valueIn('owner'),
              where: document.activeElement.dataset.field
                || document.activeElement.dataset.kind || '',
              inside: POP.contains(document.activeElement)};
// A half-written date, which is the one answer Enter may not take: the picker
// reports `value === ''` for `2026-0` exactly as it does for a box somebody
// emptied on purpose. `defineProperty` because `validity` is the browser's and
// headless Chrome will not be given one any other way.
openField('start_date');
const date = boxIn('start_date');
date.value = '';
Object.defineProperty(date, 'validity', {value: {badInput: true}, configurable: true});
enter('start_date');
const half = {open: opensNow(), why: whyLines(), sent: patches().length,
              where: document.activeElement.dataset.field || ''};
// Finished, and then taken.
Object.defineProperty(date, 'validity', {value: {badInput: false}, configurable: true});
date.value = '2026-03-02';
enter('start_date');
const finished = {open: opensNow(), says: valueIn('start_date'), why: whyLines()};
pressSave();
await rest(1000);
const landed = {sent: patches(), said: said(), open: popIsOpen(),
                title: DATA.rows[row.id].title, owner: DATA.rows[row.id].owner,
                start: DATA.rows[row.id].start_date};
return {id: row.id, was: row, title, somebody, taken, both, half, finished, landed};
"""


def test_enter_takes_the_answer_and_closes_the_field_without_writing(
    index: Index, tmp_path: Path
):
    """jcanton, 2026-09-18, on the version where Enter reached the form's own
    submit: *"can we instead have 'enter' only close the field being edited,
    similarly to escape, instead of committing on the floating editing card?"*.

    So Enter and Escape are a pair and neither of them writes. Enter takes what
    is in the box and puts it on the card as a word; Escape puts the old word
    back; Save is the only thing that sends anything, which is what the button
    being there says.

    **Taken is not written.** What Enter stages goes into `form.values`, the card
    is drawn again from it, and the plan has not been touched — the assertion
    that says so is the PATCH count, taken after each of the four presses here.

    **The whole box is drawn again rather than the one slot rewritten**, because
    what a value looks like as a word is `cardHtml`'s answer — a chip with its
    tint and its mark, a list joined the card's way, a dash where there is
    nothing — and a second place that renders one is how two places come to
    disagree. Which is why every OTHER open control is staged first: the redraw
    rebuilds them from the row, and an answer left in one would have been
    rewritten to the record's.

    **A half-written date is the one answer Enter may not take.** A native picker
    answers `value === ''` for `2026-0` exactly as it does for a box somebody
    emptied on purpose, so taking it would stage a deletion nobody asked for —
    the defect `openEditor` (`table.py`) records in as many words. Nothing closes,
    the box says which field it is, and the answer stays on screen to be
    finished.

    And the keyboard stays inside the box. `#pop` is where this box's keydown
    listener is, so a keyboard that fell out of it cannot press Escape to leave —
    and it cannot be given to the word just written, because `.card-fact` is
    `display: contents` and Chrome will not focus an element with no box.
    """
    got = _at_a_form(index, tmp_path / "entertakes.html", _ENTER_TAKES, patience=5000)

    assert not got.get("error"), got
    assert got["taken"]["stopped"] is True, (
        "Enter was left to bubble, so it reached the `<form>` this control is inside and "
        "pressed its submit button — which is the commit this was asked to stop being"
    )
    assert got["taken"]["sent"] == 0, "Enter wrote to the plan"
    assert got["taken"]["form"] is True, "Enter took the whole box down"
    assert got["taken"]["box"] is False, "Enter left the control open"
    assert got["taken"]["says"] == got["title"], (
        f"the card reads {got['taken']['says']!r} after Enter and {got['title']!r} was "
        "typed — a taken answer that is not on the card is one nobody can check"
    )
    assert got["taken"]["open"] == ["owner"], (
        f"the fields still open are {got['taken']['open']} — Enter closes the one field it "
        "was pressed in"
    )
    assert got["taken"]["owner"] == got["somebody"], (
        "the redraw rebuilt the other open control from the record, so the answer typed "
        "into it is gone"
    )
    assert got["taken"]["where"] == "owner", (
        f"the keyboard went to {got['taken']['where']!r} rather than to the control still "
        "open beside it"
    )
    assert got["both"]["sent"] == 0 and got["both"]["open"] == [], got["both"]
    assert got["both"]["owner"] == got["somebody"], got["both"]["owner"]
    assert got["both"]["inside"] is True, (
        f"with nothing open the keyboard is on {got['both']['where']!r}, outside the box. "
        "It has to stay inside `#pop`, which is where this box's keydown listener is — "
        "otherwise Escape reaches nothing and Tab starts again from the top of the page"
    )
    assert got["both"]["where"] == "title", (
        f"the keyboard is on {got['both']['where']!r} rather than on the card's first "
        "field, which is where `popFirstSlot` puts it"
    )
    assert got["half"]["open"] == ["start_date"], (
        "Enter closed a half-written date, which stages a deletion of the date that is "
        "there — and says nothing about it"
    )
    assert got["half"]["sent"] == 0
    assert len(got["half"]["why"]) == 1 and "half-written" in got["half"]["why"][0], (
        f"the box said {got['half']['why']} about a date it refused to take"
    )
    assert got["half"]["where"] == "start_date", (
        "the keyboard is not in the box the refusal is about, which is the one place the "
        "reader has to be to act on it"
    )
    assert got["finished"]["open"] == [] and got["finished"]["why"] == [], got["finished"]
    assert got["finished"]["says"] == "02.03.2026", (
        f"the card reads {got['finished']['says']!r} over a date somebody has just typed. "
        "`cardFact` draws `row.start ?? row.start_date` — the scheduler's span first — so "
        "a staged date has to move the derived twin with it or the card is confidently "
        "wrong about the one thing the reader just did"
    )
    assert len(got["landed"]["sent"]) == 1, (
        f"three fields taken in one visit went out as {len(got['landed']['sent'])} writes"
    )
    assert got["landed"]["sent"][0]["body"]["fields"] == {
        "title": got["title"],
        "owner": got["somebody"],
        "start_date": "2026-03-02",
    }, (
        "Save sent something other than the three answers Enter took: "
        f"{got['landed']['sent'][0]['body']['fields']}"
    )
    assert got["landed"]["open"] is False, "the box stayed up after its Save landed"
    assert (got["landed"]["title"], got["landed"]["owner"], got["landed"]["start"]) == (
        got["title"],
        got["somebody"],
        "2026-03-02",
    ), got["landed"]


# --------------------------------------------------------------------------- #
# The shape of it, which is the card's
# --------------------------------------------------------------------------- #


# What the box adds to the card and the card has no reason to carry: the classes
# that say a value can be pressed, and the two children that are the box's own.
# Everything else must be the same, node for node.
_THE_BOXES_OWN = ['popopens', 'poplocked', 'popediting', 'popcard']
_THE_BOXES_PARTS = ['popheading', 'popwhy', 'popacts']
# And the one element the box adds inside the card's own: the mark on a field the
# status now in the box will make the server refuse the record without. A card is
# read and asks for nothing, so it has none.
_THE_BOXES_MARKS = ['popreq']


_THE_CARDS_SHAPE = """
const row = rowWhere(one => one.kind === 'task' && one.title && one.status && one.priority);
if (!row) return {error: 'the corpus draws no task carrying both ladders'};
const MINE = """ + repr(_THE_BOXES_OWN).replace("'", '"') + """;
const MARKS = ["popreq"];
const PARTS = """ + repr(_THE_BOXES_PARTS).replace("'", '"') + """;
// Every element under this one, as tag plus the classes that are not the box's
// own. Two boxes drawn by one function have the same list; two boxes drawn by
// two functions agree until somebody edits one of them.
const classOf = one => (one.getAttribute('class') || '').trim().split(' ').filter(Boolean);
const boneOf = one => one.tagName
  + classOf(one).filter(c => !MINE.includes(c)).map(c => '.' + c).join('');
const bonesOf = root => [...root.children]
  // The document is fetched and appended to the card and is not in the box, by
  // design — jcanton, 2026-09-18: "as by design, not making the body editable".
  .filter(one => !classOf(one).includes('card-body'))
  .flatMap(one => [one, ...one.querySelectorAll('*')])
  .filter(one => !classOf(one).some(c => MARKS.includes(c)))
  .map(boneOf);
// The words, which is the other half of "the same box": a structure that matches
// while the text does not is two boxes that merely look alike.
const wordsOf = root => [...root.querySelectorAll('dt, dd, .chipword, .card-title')]
  // Without the mark, for the reason the mark is left out of the bones: a card
  // asks for nothing, so `Appetite *` against `Appetite` is the box adding the
  // one thing it is supposed to add.
  .map(one => [...one.childNodes]
    .filter(node => !(node.nodeType === 1 && MARKS.includes(node.className)))
    .map(node => node.textContent).join('').trim());
// The card first, on the same row, so that what the box is compared against is
// the thing itself rather than a description of one. Caught, because the
// document behind a card is fetched and this page is served over `file://` —
// the fields are drawn in the first pass either way.
await showCard(row, 300, 300, []).catch(() => {});
const card = {width: getComputedStyle(CARD).maxWidth, bones: bonesOf(CARD),
              words: wordsOf(CARD), hill: !!CARD.querySelector('.card-hill')};
popClose();
openOn(row.id);
itemIn('edit').click();
const form = formIn();
// The box's own children set aside, and what is left compared with the card.
const mine = [...form.children].filter(one => PARTS.includes(String(one.className).split(' ')[0]));
// `kept` and not `rest`: `_READERS` already declares a `rest`, and a duplicate
// top-level `const` is a SyntaxError for the whole block — which reports as a
// page that said nothing at all rather than as a test that failed.
const kept = document.createElement('div');
for (const one of [...form.children]) if (!mine.includes(one)) kept.append(one.cloneNode(true));
const seen = {
  card: card,
  width: getComputedStyle(POP).maxWidth,
  bones: bonesOf(kept),
  words: wordsOf(kept),
  hill: !!form.querySelector('.card-hill'),
  extra: mine.map(one => String(one.className).split(' ')[0]),
  // No document in the box, and no control on a card nobody has pressed.
  body: !!form.querySelector('.card-body'),
  boxes: form.querySelectorAll('input, select').length,
  named: {title: nameIn('title'), priority: nameIn('priority'), status: nameIn('status')},
};
// The status chip is the status control, so the picture beside it has to be the
// status too — the card draws the same fact twice and so does this.
const before = form.querySelector('.card-chips .hill-ball').dataset.word;
const pick = openField('status');
const other = [...pick.options].map(one => one.value).find(one => one && one !== row.status);
if (other) {
  typeInto('status', other);
  seen.moved = {
    to: other, was: before,
    chip: form.querySelector('.card-chips [data-field="status"]').className,
    ball: form.querySelector('.card-chips .hill-ball')
      ? form.querySelector('.card-chips .hill-ball').dataset.word : '',
  };
}
return {id: row.id, kind: row.kind, was: row.status, seen: seen};
"""


def test_the_box_a_right_click_opens_is_the_hover_card_itself(index: Index, tmp_path: Path):
    """**The box a right-click opens to edit a record is the box a hover opens to
    read one — the same markup, from the same function, under the same
    stylesheet.**

    jcanton, 2026-09-18, after two passes that merely resembled it: *"I meant
    this card"*, *"it should display the editable fields as the edit view, so
    owner, assignees, reviewer, etc etc"*, and — for how a value becomes a
    control without the box turning back into a form — *"it could be like the
    table where you have to click one field to enter edit mode for that field?"*.

    So the claim is asserted structurally, against the live card rather than
    against a description of one: the card is opened on the row, read, dismissed,
    and the box opened in its place. Every element under both is listed as tag
    plus classes, and the two lists must be equal — the only classes allowed to
    differ are the box's own, the ones that say a value can be pressed. The
    visible words are compared beside them, because a structure that matches
    while the text does not is two boxes that merely look alike.

    `cardHtml` (`shell.py`) is what makes that possible and is the whole design:
    one builder, called by the hover and by the box, and `:is(#card, .popcard)`
    in the stylesheet so there is no second copy of the rules either.

    **Nothing on the box is a control until it is pressed.** That is the
    assertion that tells this apart from every earlier cut: a box with fifteen
    outlined controls in it is the form this replaced, and counting them before
    anything is clicked is how the DOM can say which one it is.

    The hill is the last of it. The card draws the status twice — the word in the
    chip and the shape under it — so the picture has to follow the `<select>`,
    and a chip reading `Done` over a ball still on the near slope would be the
    card confidently wrong about the one record it is showing.
    """
    got = _at_a_form(index, tmp_path / "shape.html", _THE_CARDS_SHAPE, patience=4500)

    assert not got.get("error"), got
    seen = got["seen"]
    card = seen["card"]
    # The card itself came up, which everything below is measured against.
    assert len(card["bones"]) > 10 and card["words"], (
        f"the hover card drew almost nothing to compare the box with: {card}"
    )

    assert seen["width"] == card["width"], (
        f"the box is capped at {seen['width']} and the card it stands in for at {card['width']}"
    )
    assert seen["bones"] == card["bones"], (
        "the box and the card are not the same markup. The box drew\n"
        f"  {seen['bones']}\nand the card drew\n  {card['bones']}"
    )
    assert seen["words"] == card["words"], (
        f"the box says {seen['words']} and the card says {card['words']}"
    )
    assert seen["extra"] == ["popheading", "popwhy", "popacts"], (
        f"the box's own children are {seen['extra']} — the heading, the refusal list "
        "and the Save/Cancel pair, which every box on these pages now carries"
    )
    assert seen["boxes"] == 0, (
        f"the box opened with {seen['boxes']} controls already on it — a card is words, "
        "and a box of controls is the form this replaced"
    )
    assert seen["body"] is False, "a document reached the box, which is the detail page's"
    assert seen["hill"] is True and card["hill"] is True, (
        "the card draws a hill beside its status chip and the box does not"
    )
    # The three on the card's face carry no visible name, which is the part that
    # was asked for by name. `aria-label` carries the fact instead.
    assert seen["named"] == {"title": "", "priority": "", "status": ""}, seen["named"]

    moved = seen.get("moved")
    assert moved, "the corpus offers this kind only one status, so the chip cannot be moved"
    assert f"st-{moved['to']}" in moved["chip"], (
        f"the status chip still reads {moved['chip']} after the picker was moved to "
        f"{moved['to']} — a chip in the old rung's tint is confidently wrong"
    )
    assert moved["ball"] and moved["ball"] != moved["was"], (
        f"the hill still says {moved['was']!r} after the status moved to {moved['to']!r}"
    )


_A_SPACE = """
const row = rowWhere(one => one.kind === 'task' && one.title);
if (!row) return {error: 'the corpus draws no task'};
openOn(row.id);
itemIn('edit').click();
const seen = {};
for (const name of ['title', 'assignees']) {
  const box = openField(name);
  box.value = '';
  // A space, typed the way a browser delivers one: the `keydown` first, and then
  // the character — which only arrives if nothing cancelled the key. This is the
  // whole of the bug: the row this box sits in was listening for a space as
  // "open me", and swallowed it on the way past.
  const key = new KeyboardEvent('keydown', {key: ' ', bubbles: true, cancelable: true});
  box.dispatchEvent(key);
  seen[name] = {stopped: key.defaultPrevented};
  if (!key.defaultPrevented) {
    box.value = 'two words';
    box.dispatchEvent(new Event('input', {bubbles: true}));
  }
  seen[name].held = box.value;
  giveUp(name);
}
// And the row itself still answers a space, which is what the handler is for.
const part = fieldIn('title');
part.focus();
const onRow = new KeyboardEvent('keydown', {key: ' ', bubbles: true, cancelable: true});
part.dispatchEvent(onRow);
seen.row = {stopped: onRow.defaultPrevented, opened: !!boxIn('title')};
return {id: row.id, seen};
"""


def test_a_space_typed_into_a_field_reaches_the_field(index: Index, tmp_path: Path):
    """**The control this box opens is a CHILD of the element that opens it**, so
    every key typed into it bubbles up to that element's own handler.

    That handler answers Enter and Space with "open me", and cancels them so a
    space does not scroll the page under an open card. Written without asking
    whose key it was, it cancelled the space somebody was typing into the title:
    jcanton, 2026-09-18, on the released version — "when editing the new card I
    can't add space characters in the fields (tried title and assignees)".

    `event.target !== part` is the fix, and it is asked rather than inferred from
    whether a control is open: a `<select>` inside the same element answers space
    and the arrow keys itself, and this handler has no business with any of them.

    Both halves are asserted, because the fix that only does the first half is
    deleting the handler: a space typed in the box is not cancelled, and a space
    typed on the row still opens it.
    """
    got = _at_a_form(index, tmp_path / "space.html", _A_SPACE)

    assert not got.get("error"), got
    for name in ("title", "assignees"):
        assert got["seen"][name]["stopped"] is False, (
            f"the space typed into {name} was cancelled before the box could have it"
        )
        assert got["seen"][name]["held"] == "two words", got["seen"][name]
    assert got["seen"]["row"]["stopped"] is True, (
        "a space pressed on the row itself is not answered, so the card cannot be opened "
        "from the keyboard — and the page scrolls under it instead"
    )
    assert got["seen"]["row"]["opened"] is True, "the space on the row opened nothing"


_COMPLETING = """
const row = rowWhere(one => one.kind === 'task' && one.title);
if (!row) return {error: 'the corpus draws no task'};
openOn(row.id);
itemIn('edit').click();
const seen = {};
// The fields that OPEN, which is not every field the card draws: this host
// carries a `blocked_by` count and no `depends_on`, and a box drawn empty over a
// value this view has not got would delete it — so that one is locked, with a
// sentence, and locked is the right answer rather than a gap in this test.
for (const name of opensInForm()) {
  if (!POP_SCHEMA.suggests[name]) continue;
  const box = openField(name);
  if (!box) { seen[name] = {error: 'the field would not open'}; continue; }
  const list = box.getAttribute('list') && document.getElementById(box.getAttribute('list'));
  seen[name] = {
    source: POP_SCHEMA.suggests[name],
    tag: box.tagName,
    // A datalist attached to the box AND STILL IN THE DOCUMENT, with something
    // in it: an empty one, or one `replaceChildren` has thrown away, is a
    // control that completes nothing — which is what was reported.
    inPage: !!(list && list.isConnected),
    // `parent` is a `<select>` of the records that may hold this one, and its
    // own options are its completion. Every other completing field is typed
    // into.
    listed: box.tagName === 'SELECT'
      ? [...box.options].map(one => one.value)
      : (list ? [...list.options].map(one => one.value) : null),
  };
  giveUp(name);
}
// And the list fields carry the text already typed through, or a datalist —
// which matches on the WHOLE value — offers nothing the moment there are two
// names in the box.
const many = opensInForm().find(name => POP_SCHEMA.suggests[name]
  && POP_SCHEMA.types[name] === 'list' && POP_SCHEMA.types[name] !== 'select');
let carried = null;
if (many) {
  const box = openField(many);
  const first = POP_SCHEMA.suggests[many] === 'people'
    ? POP_SCHEMA.people[0] : (POP_SCHEMA.lists[POP_SCHEMA.suggests[many]] || [{}])[0].value;
  box.value = first + ',';
  box.dispatchEvent(new Event('input', {bubbles: true}));
  const list = document.getElementById(box.getAttribute('list'));
  carried = {name: many, typed: box.value,
             offers: [...list.options].map(one => one.value).slice(0, 3)};
  giveUp(many);
}
return {id: row.id, seen, carried, lists: Object.keys(POP_SCHEMA.lists || {})};
"""


def test_every_field_that_completes_on_the_record_page_completes_in_the_card(
    index: Index, tmp_path: Path
):
    """jcanton, 2026-09-18: *"autocomplete doesn't work in the forms inside our
    new editable card. can you enable all as in the /detail?"*.

    Two halves were wrong and the second is the one that was noticed. The call
    was gated on `type === 'text'`, and a list field's type is `list` — so
    `assignees`, `reviewers`, `tags`, `depends_on` and `prs`, five of the seven
    fields anybody completes, had no datalist at all. And `tags`, `prs` and
    `cycles` were deliberately kept out of the schema when this box was a form of
    its own, so even the fields that did reach `popComplete` had nothing to offer.

    Asked of `SUGGESTS` rather than of a list here: that map is what the record
    page draws its own `<datalist>`s from, so "all as in the /detail" is the
    claim that every field with a source in it completes here too, and a field
    added to it later fails this test rather than quietly completing nothing.

    The carry-through is the other assertion. A datalist matches against the
    whole value of the box, so on `ann,` the options have to be `ann, bo` and not
    `bo` — otherwise picking one would delete the name already typed.
    """
    got = _at_a_form(index, tmp_path / "completing.html", _COMPLETING)

    assert not got.get("error"), got
    # Every field this record has that the detail page completes. Taken off the
    # form's own rows, so a field the card does not draw is not asked about.
    wanted = {name for name in got["seen"]}
    assert wanted, "no completing field was opened at all, so this measured nothing"
    assert wanted <= set(SUGGESTS), f"the card completes a field the record page does not: {wanted}"
    for name, one in got["seen"].items():
        assert not one.get("error"), (name, one)
        assert one["listed"], (
            f"{name} completes from {one.get('source')} and its box carries "
            f"{one['listed']!r} — a control that completes nothing"
        )
        # The list has to be ON the page. It was appended to the slot and then
        # thrown away by the `replaceChildren` that puts the control there, so
        # every box pointed `list=` at a detached element — a `list` attribute
        # that is present and completes nothing, which is what a test asking only
        # for the attribute would have called a pass.
        if one["tag"] != "SELECT":
            assert one["inPage"], f"{name}'s list is not in the document"
    assert set(got["lists"]) == {"tags", "prs", "cycles"}, (
        f"the three lists that are neither a person nor a record ship as {got['lists']}"
    )
    assert got["carried"], "no list field was found, so the carry-through is untested"
    assert all(one.startswith(got["carried"]["typed"]) for one in got["carried"]["offers"]), (
        f"{got['carried']['name']} was offered {got['carried']['offers']} after "
        f"{got['carried']['typed']!r} was typed — picking one would delete what is there"
    )


# --------------------------------------------------------------------------- #
# A refusal, which is the whole reason the form is a face of this box
# --------------------------------------------------------------------------- #


_REFUSED_FORM = """
const row = rowWhere(one => one.kind === 'task' && one.status && one.title);
if (!row) return {error: 'the corpus draws no task'};
const somebody = POP_SCHEMA.people.find(login => login !== row.owner);
if (!somebody) return {error: 'the corpus knows only one person'};
// A RULE's own sentence, raised as an HTTPException(409) before anything is
// written. Not one of the thirteen is a concurrent write, which is why the box
// has to stay up: this is news somebody can act on.
const RULE = 'a task may not be filed under a task, and this one is';
ANSWER = () => ({status: 409, body: {detail: RULE}});
openOn(row.id);
itemIn('edit').click();
const typed = row.title + ' — typed and not yet saved';
typeInto('title', typed);
// Nothing went out on the typing: this box holds what is in it until Save.
const quiet = patches().length;
pressSave();
await rest(900);
const refused = {quiet, form: formUp(), up: formIsUp(), why: whyLines(),
                 title: valueIn('title'), open: !!boxIn('title'),
                 focused: document.activeElement.dataset.kind || '',
                 sent: patches().length,
                 base: baseNow(), beats: beatsNow(), now: DATA.rows[row.id].title};
// **The five signals that take a MENU away, every one of which would be a silent
// deletion of what somebody has typed.** Each is sent the way the page produces
// it, and the scroll is dispatched on `.table-scroll` and does not bubble —
// which is the point, since that is the box the rows scroll inside.
document.body.dispatchEvent(
  new PointerEvent('pointerdown', {bubbles: true, clientX: 5, clientY: 5}));
document.querySelector('.table-scroll').dispatchEvent(new Event('scroll'));
dispatchEvent(new CustomEvent('openproj:filter'));
dispatchEvent(new CustomEvent('openproj:wrote', {detail: 'c0ffeeff'}));
// And a right press on a DIFFERENT row, which is the one signal that would not
// merely hide the box: it is a `replaceChildren` over everything in it.
const elsewhere = menuRows().find(tr => tr.dataset.id !== row.id);
const stray = rightOn(elsewhere, 420, 420);
const survived = {form: formUp(), title: valueIn('title'),
                  open: popIsOpen(), about: popAbout(), prevented: stray.defaultPrevented,
                  why: whyLines()};
// Answered again, and this time the server takes it. What goes out is what is
// still in the box, which is what proves the answer was KEPT rather than merely
// drawn once.
ANSWER = () => ({status: 200,
                 body: {outcome: 'committed', commit: 'c0ffee2', pushed: true}});
pressSave();
await rest(1000);
const landed = {sent: patches(), said: said(), open: popIsOpen(), form: formUp(),
                base: baseNow(), now: DATA.rows[row.id].title};
// And the two ways a box is left on purpose, which are two decisions and two
// keys: Escape in a control undoes that field, and Escape again leaves the box.
openOn(row.id);
itemIn('edit').click();
typeInto('owner', somebody);
pressKey('Escape');
const undone = {form: formUp(), box: !!boxIn('owner'), owner: valueIn('owner'),
                where: document.activeElement.dataset.kind || ''};
pressKey('Escape');
const escaped = {open: popIsOpen(), form: formUp(), said: said(),
                 sent: patches().length};
return {id: row.id, was: row.title, typed, somebody, RULE,
        wasOwner: row.owner, refused, survived, landed, undone, escaped};
"""


def test_a_refusal_keeps_the_box_open_with_the_answer_still_in_it(
    index: Index, tmp_path: Path
):
    """**This is why the box is a face of `#pop` and not a page**, and it is the
    one rule cut 2 wrote down that cut 4 changed.

    A refusal keeps the box open with the reader's answer in it: `popSay`
    branches on `POP_FORM` and puts the sentence into the box's own list without
    rebuilding anything, and nothing touches the controls, so what was typed is
    still where it was typed. A card that swallowed both would leave somebody
    looking at the old value with no idea why their new one did not take.

    Pressing Save again is what proves it — what goes out the second time is what
    is on screen, and a box that had redrawn itself from the row would send the
    row's.

    And the box is **not dismissed by somebody looking at the page**. Every one
    of the six signals that kill a menu means "the reader is reaching for
    something else", which for a list of words is a reason to get out of the way
    and for a half-answered card is a silent deletion: a click on the row behind
    it, a scroll of the table under it, a filter, a write landing elsewhere, and
    the work is gone with nothing said. Three of the last four audit rounds
    shipped a defect of exactly that shape. `popClose` returns early while
    `POP_FORM` is set unless `POP_SHUTTING`, which only `popDone` sets — so
    Escape and a commit that landed are the ways out, and they are decisions.

    A right press elsewhere is the sixth and the only one that is not a hide:
    `popMenu` answers `true` without touching the box, so the view still calls
    `preventDefault` and the browser's own menu does not open over the top of it.
    That is the contract change — "whether this module answered the press" rather
    than "whether a menu was opened", which is what the call site was always
    really asking.
    """
    got = _at_a_form(index, tmp_path / "refusedform.html", _REFUSED_FORM, patience=6000)

    assert not got.get("error"), got
    assert got["refused"]["quiet"] == 0, (
        "the title was written as it was typed — this box holds what is in it and Save "
        "is the only thing that commits"
    )
    assert got["refused"]["form"] is True, (
        "the refusal closed the box, so the answer is gone and the reason went with it"
    )
    assert got["refused"]["up"]["up"] is True and got["refused"]["up"]["role"] == "dialog"
    assert got["refused"]["why"] == [got["RULE"]], (
        f"the box says {got['refused']['why']} and the server said {got['RULE']!r} — a "
        "rule's own sentence read as the store's conflict report sends the reader to "
        "reload against a plan nobody touched"
    )
    assert got["refused"]["open"] is True, (
        "the control closed on a write that was refused, so the answer is only in the "
        "reader's memory"
    )
    assert got["refused"]["title"] == got["typed"], (
        f"the title box holds {got['refused']['title']!r} after a refusal and "
        f"{got['typed']!r} was typed into it"
    )
    assert got["refused"]["focused"] == "form-why", (
        f"the keyboard is on {got['refused']['focused']!r} rather than on the sentence "
        "that has just appeared. A refusal is put under the keyboard when it arrives — "
        "the same move `popSay` makes in the menu — and Tab out of it lands on Save, "
        "which is the next thing in the document"
    )
    assert got["refused"]["sent"] == 1 and got["refused"]["base"] == HEAD
    assert got["refused"]["now"] == got["was"], "the row changed under a write that was refused"
    assert got["refused"]["beats"] == {"writing": 1, "wrote": [None]}, (
        f"the event pair does not balance over a refusal: {got['refused']['beats']}"
    )
    assert got["survived"]["form"] is True, (
        "a press outside, a scroll, a filter, a write landing elsewhere or a right press "
        "on another row took a half-answered card away"
    )
    assert got["survived"]["title"] == got["typed"], got["survived"]
    assert got["survived"]["why"] == [got["RULE"]], (
        "the reason went off the screen while the box it is about stayed"
    )
    assert got["survived"]["about"] == got["id"], (
        f"the box is now about {got['survived']['about']}, so the right press rebuilt it "
        "over the card"
    )
    assert got["survived"]["prevented"] is True, (
        "the view did not call `preventDefault` on a press this module answered, so the "
        "browser's own menu opens on top of a half-answered card"
    )
    assert len(got["landed"]["sent"]) == 2, got["landed"]["sent"]
    assert got["landed"]["sent"][1]["body"]["fields"] == {"title": got["typed"]}, (
        "the second write sent something other than what was in the box: it was rebuilt "
        f"from the row under the refusal — {got['landed']['sent'][1]['body']}"
    )
    assert got["landed"]["said"] == f"{got['was']}: {LABELS['title']} saved", got["landed"]["said"]
    assert got["landed"]["open"] is False and got["landed"]["form"] is False, (
        "the box stayed up after its Save landed. One press is the whole gesture now, and "
        "the row it was drawn from has just been replaced"
    )
    assert got["landed"]["now"] == got["typed"], (
        f"the row reads {got['landed']['now']!r} after a Save of {got['typed']!r}"
    )
    assert got["landed"]["base"] == "c0ffee2"
    assert got["undone"]["where"] == "form-save", (
        f"after Escape gave up on a field the keyboard is on {got['undone']['where']!r}. "
        "It has to stay inside the box: this box's keydown listener is on `#pop`, so a "
        "keyboard that fell out of it cannot press Escape again to leave"
    )
    assert got["undone"]["form"] is True, (
        "Escape in a control took the whole box down, when what was asked for was to undo "
        "one field"
    )
    assert got["undone"]["box"] is False and got["undone"]["owner"] != got["somebody"], (
        f"Escape left the owner reading {got['undone']['owner']!r}, which is what was "
        "typed rather than what the record holds"
    )
    assert got["escaped"]["open"] is False and got["escaped"]["form"] is False, (
        "Escape did not take the card away, and it is the close that is a decision rather "
        "than somebody looking at the page"
    )
    assert got["escaped"]["said"] == "nothing was changed", got["escaped"]["said"]
    assert got["escaped"]["sent"] == 2, (
        "leaving the box by Escape wrote what was typed into it, which is the whole of "
        "what Cancel and Escape promise not to do"
    )


# --------------------------------------------------------------------------- #
# `Assign parent…`, which is the one field the answer to is another record
# --------------------------------------------------------------------------- #


_THE_PICKER = """
const row = rowWhere(one => one.kind === 'task' && one.parent && !one.off_plan_parent);
if (!row) return {error: 'the corpus draws no task filed under something'};
const allowed = POP_SCHEMA.parent_kinds[row.kind] || [];
// What the picker OUGHT to hold, worked out from the payload this page was
// rendered with rather than from the module being asked about: every row of a
// kind that may hold this one, except this one.
const legal = Object.values(DATA.rows)
  .filter(one => one.id !== row.id && allowed.includes(one.kind))
  .map(one => one.id);
// And a record of a kind that may NOT hold it, which has to be on the plan or
// the assertion that it is absent is about nothing.
const wrongKind = Object.values(DATA.rows).find(one => !allowed.includes(one.kind)
                                                       && one.id !== row.id);
openOn(row.id);
const item = itemIn('parent');
const word = wordIn(item);
item.click();
// **Open already**, which is what `Change parent…` means on a card whose values
// are words until they are pressed: somebody who chose that item has said which
// field they came to change.
const box = boxIn('parent');
const opened = {up: formIsUp(), heading: headingIn(), fields: fieldsInForm(),
                tag: box ? box.tagName : '', disabled: box ? box.disabled : null,
                value: box ? box.value : '',
                // And nothing else opened with it: this is the card, and every
                // other value on it is still a word.
                boxes: POP.querySelectorAll('input, select').length,
                save: !!saveIn(),
                options: optionsIn('parent')};
opened.kinds = opened.options.filter(one => one.value)
  .map(one => (DATA.rows[one.value] || {}).kind || null);
const next = opened.options.map(one => one.value)
  .find(one => one && one !== row.parent);
if (!next) return {error: 'the corpus offers no second legal parent to move to'};
typeInto('parent', next);
// Nothing yet: what is typed into this box is held in it, and Save is what
// commits. The count is taken before the press so that "one PATCH" below is a
// claim about the press and not about the pair.
const quiet = patches().length;
pressSave();
await rest(1000);
const landed = {quiet, sent: patches(), said: said(), open: popIsOpen(),
                now: DATA.rows[row.id].parent, posted: posts().length};
// And the host that cannot list its records at all, which is the timeline and
// the static export. The item refuses with a sentence rather than opening a card
// over a picker with nothing in it.
//
// `popDone()` first, and defensively: a write that lands closes the box, but
// `popClose` refuses to take a box with a form in it down, so a run that somehow
// still had one up would find the card here rather than rebuild the menu.
popDone();
POP_HOST.all = undefined;
openOn(row.id);
const blind = {disabled: itemIn('parent').getAttribute('aria-disabled'),
               why: itemIn('parent').dataset.why || '', word: wordIn(itemIn('parent'))};
return {id: row.id, title: row.title, was: row.parent, word, allowed, legal, next,
        nextTitle: DATA.rows[next] ? DATA.rows[next].title : null,
        wrongKind: wrongKind ? wrongKind.id : null, opened, landed, blind,
        hosted: {all: typeof HOST_ALL === 'function', shows: typeof HOST_SHOWS === 'function'}};
"""

# **The two calls cut 4 adds to the host contract**, read as the page left them
# and then filled in where it left them empty.
#
# `all()` and `shows(id)` are optional to `popServes` like `extras` and `wrote`,
# and `table.py` is not the file that added them, so they may or may not be on the
# page. What each one costs when a host leaves it out is never silence — the
# parent items refuse with a sentence and the create's receipt stops claiming to
# know where the record went — and both of those are branches worth having tested
# on their own. But the picker's CONTENTS are `pop.py`'s and would otherwise be
# untestable on any of the three views until somebody else's one line landed.
#
# So the host's own answer is read first, and asserted on its own at the end of
# each test that needs it; the fallback below is the line `pop.py`'s contract note
# gives the table, installed only where the page has not installed it. A wired
# page is asked through its own wiring and this is a no-op.
_HOST_CALLS = """
const HOST_ALL = POP_HOST.all;
const HOST_SHOWS = POP_HOST.shows;
POP_HOST.all = POP_HOST.all || (() => Object.values(DATA.rows));
POP_HOST.shows = POP_HOST.shows || (id => menuRows().some(tr => tr.dataset.id === id));
"""

# The one line each of the two writing views needs, quoted from `pop.py`'s own
# host-contract note, so a failure here says what to add rather than what is
# missing.
_WIRING = {
    "all": "all: () => Object.values(DATA.rows)",
    "shows": 'shows: id => !!tbody.querySelector(`tr[data-id="${id}"]`)',
}


def test_assign_parent_offers_a_select_of_the_records_that_may_hold_this_one(
    index: Index, tmp_path: Path
):
    """**A `<select>` of records that exist, and never a box to type an id
    into.**

    That control is the only thing that ever stood in front of two holes in the
    server, both measured through the API before cut 4 closed them:
    `_containment_problems` returned early on a parent it could not resolve, so a
    dangling one committed in silence and `openproj check` never mentioned it;
    and PATCH ran `loop_made` and no `validate_all` at all, so a wrong-kind
    parent committed and was reported afterwards. Both doors refuse now, and this
    control is still the right one — a refusal is a worse answer than a list that
    could not express the mistake in the first place.

    So three things are asserted about what is in it, and each is one of those
    mistakes made unsayable: no record of a kind that may not hold this one, not
    the record itself, and nothing at all that is not an id the payload carries.
    The loop is the one case a reader cannot have meant; every other loop is
    still the server's to find, which is why this is not a second copy of
    `loop_made`.

    **And the last assertion is about the HOST rather than the menu.** `rows(id)`
    answers about one record and a parent picker is a question about all of them,
    so cut 4 adds `all()` to the contract. Without it the item refuses with a
    sentence — which is right for the timeline and for a rendered file, and is
    asserted here as its own branch — and wrong for the two views that can write,
    where it means `Assign parent…` never opens at all.
    """
    got = _at_a_form(index, tmp_path / "picker.html", _HOST_CALLS + _THE_PICKER, patience=5000)

    assert not got.get("error"), got
    assert got["word"] == "Change parent…", (
        f"a record that is filed under something offers {got['word']!r}"
    )
    assert got["opened"]["up"]["role"] == "dialog", got["opened"]["up"]
    assert got["opened"]["heading"] == f'Where "{got["title"]}" is filed', got["opened"]["heading"]
    assert "parent" in got["opened"]["fields"] and len(got["opened"]["fields"]) > 1, (
        f"`Change parent…` drew {got['opened']['fields']} — it is the same card as "
        "`Edit…`, because a card of one row is not a card; what the item buys is that the "
        "one field somebody came to change is already open"
    )
    assert got["opened"]["tag"] == "SELECT", (
        f"the parent control is a {got['opened']['tag']}: a box you can type into is the "
        "one control that can name a record that does not exist"
    )
    assert got["opened"]["boxes"] == 1, (
        f"the card opened with {got['opened']['boxes']} controls on it — `Change parent…` "
        "opens the one field somebody came to change and leaves the rest words"
    )
    assert got["opened"]["save"] is True, (
        "the card has no Save, and where a record is filed is written when Save is "
        "pressed like everything else on this box"
    )
    assert got["opened"]["disabled"] is False, "the picker that is the whole point is locked"
    assert got["opened"]["value"] == got["was"], (
        f"the picker opens holding {got['opened']['value']!r} and the record is filed "
        f"under {got['was']!r}"
    )
    assert got["opened"]["options"][0] == {"value": "", "text": "— nothing —"}, (
        f"the first option is {got['opened']['options'][0]} — a parent that is not locked "
        "may be cleared, and that is a state the field can really be in"
    )
    offered = [one["value"] for one in got["opened"]["options"] if one["value"]]
    assert sorted(offered) == sorted(got["legal"]), (
        f"the picker offers {sorted(offered)} and the records that may hold a "
        f"{got['allowed']} are {sorted(got['legal'])}"
    )
    assert got["id"] not in offered, (
        "the picker offers the record itself, which is a loop and the one case a reader "
        "cannot have meant"
    )
    assert set(got["opened"]["kinds"]) <= set(got["allowed"]), (
        f"the picker offers records of kinds {sorted(set(got['opened']['kinds']))} and this "
        f"kind may only be filed under {got['allowed']}"
    )
    assert got["wrongKind"], "every row on this table is of a kind that could hold a task"
    assert got["wrongKind"] not in offered, (
        f"{got['wrongKind']} is of a kind that may not hold this record and is in the list"
    )
    assert got["landed"]["quiet"] == 0, (
        "picking a parent wrote it before Save was pressed, which is the bargain this "
        "box gave up: jcanton asked for save/cancel on both cards and a save only on the "
        "press"
    )
    assert len(got["landed"]["sent"]) == 1 and got["landed"]["posted"] == 0, got["landed"]
    assert got["landed"]["sent"][0]["body"]["fields"] == {"parent": got["next"]}, (
        f"moving a record sent {got['landed']['sent'][0]['body']['fields']}"
    )
    assert got["landed"]["open"] is False, (
        "the box stayed up after its Save landed — one press is the whole gesture, and "
        "the row under it has just been redrawn"
    )
    assert got["landed"]["now"] == got["next"], "the row is still filed where it was"
    assert got["landed"]["said"] == f'{got["title"]} is now inside "{got["nextTitle"]}"', (
        f"the receipt reads {got['landed']['said']!r} — `Take out of \"X\"` says the same "
        "change the same way, and two sentences for one change is how one word came to be "
        "spelled three ways on one screen"
    )
    assert got["blind"]["disabled"] == "true", (
        "a view that cannot list its records opened a card over a picker with nothing in it"
    )
    assert got["blind"]["why"] == (
        "This view cannot list the records here, so there is nothing to pick from — "
        "where a record is filed is edited on its own page."
    ), got["blind"]["why"]
    assert got["hosted"]["all"] is True, (
        "the table registers no `all()`, so `Assign parent…` is refused on every row and "
        "`Edit…` draws its parent control dead. The one line it needs is "
        f"`{_WIRING['all']}`, beside `rows:` in its own `popServes({{…}})`"
    )


# --------------------------------------------------------------------------- #
# The status gate, which cut 3 refused and cut 4 answers
# --------------------------------------------------------------------------- #


_THE_GATE = """
const found = shortOf(2);
if (!found) return {error: 'the corpus holds no task short of two fields at any status'};
const row = found.row, gate = found.gate, missing = found.missing;
openOn(row.id);
itemIn('status').click();
const item = itemIn('status-' + gate);
const seen = {disabled: item.getAttribute('aria-disabled'), why: item.dataset.why || '',
              word: wordIn(item), role: item.getAttribute('role')};
item.click();
// The box the gate opens is STAGED: a `done` and the PRs it demands cannot be
// written one at a time, because the gate refuses whichever arrives first. So
// the fields it names are open, the rest of the card is words, and one button
// sends them together.
const opened = {up: formIsUp(), heading: headingIn(), fields: fieldsInForm(),
                status: valueIn('status'), open: opensNow(), save: !!saveIn(),
                pressable: opensInForm(),
                required: {}, marks: {}};
for (const name of opensNow()) {
  opened.required[name] = boxIn(name).getAttribute('aria-required');
  opened.marks[name] = markIn(name);
}
// Saved with the boxes still empty. The gate is asked HERE, before anything goes
// out, and of the fields this box is about and no others.
pressSave();
await rest(400);
const early = {why: whyLines(), sent: patches().length, form: formUp(),
               focused: document.activeElement.dataset.field};
// One answer per box, chosen by what the field IS rather than by its name: a
// number, a date, a login where the schema says the options are people, an id
// where it says records, and a plain word otherwise.
const answers = {};
for (const name of missing) {
  const type = POP_SCHEMA.types[name];
  const source = POP_SCHEMA.suggests[name];
  answers[name] = type === 'number' ? '2' : type === 'date' ? '2026-09-01'
                  : source === 'people' ? POP_SCHEMA.people[0]
                  : source === 'records' ? row.parent
                  : 'kilnlab/kiln4py#1';
  typeInto(name, answers[name]);
}
pressSave();
await rest(1000);
return {id: row.id, title: row.title, was: row.status, gate, missing, answers, seen, opened,
        early, types: POP_SCHEMA.types, sent: patches(), said: said(),
        closed: !popIsOpen(), now: DATA.rows[row.id].status, beats: beatsNow()};
"""


def test_a_gated_status_opens_the_form_on_what_it_needs_and_saves_both(
    index: Index, tmp_path: Path
):
    """**The gate is answered rather than fought, and this is where cut 3's
    behaviour changed.**

    Cut 3 drew a status whose `required_at` names fields the record has not got
    as a refusal, because there was no form to open. Cut 4 opens one on exactly
    those fields with the new status already in its box, and one Save commits the
    status and the answers together — which is what `askFor` (`table.py`) does
    today, and the reason the gate is worth having at all. Two commits would
    leave the plan holding, for the length of the first one, a record the
    validator refuses.

    So the first assertion is that the item is NOT refused any more, and the last
    is that ONE PATCH carried both halves. Between them is the thing that makes
    the form answerable: the status in the box decides which fields are marked,
    `popMarkRequired` runs on every change rather than on the status control
    alone, and the mark is paired with `aria-required` so it is not half a fact.

    And the gate is asked before the write, of the drawn boxes only. A form of
    one field cannot answer for a status it is not changing, and a refusal naming
    a field the payload does not carry is the failure
    `_reject_a_start_date_this_write_puts_in_the_past` was rewritten to stop
    making — on the server, about exactly this shape of question.
    """
    got = _at_a_form(index, tmp_path / "gateform.html", _THE_GATE, patience=5000)

    assert not got.get("error"), got
    assert len(got["missing"]) >= 2, (
        f"only {got['missing']} is missing at {got['gate']}, so the plural half of this "
        "is about nothing"
    )
    assert got["seen"]["disabled"] is None, (
        f"a status the record is short of is still drawn refused: {got['seen']} — cut 4 "
        "opens a form on what it needs, and the sentence survives only for a field the "
        "form has no box for"
    )
    assert got["seen"]["why"] == "", got["seen"]
    assert got["seen"]["word"] == HUMAN[got["gate"]], got["seen"]
    assert got["opened"]["up"]["role"] == "dialog", (
        "picking a gated status wrote instead of opening a form, or did nothing at all"
    )
    assert got["opened"]["heading"] == (
        f"{HUMAN[got['gate']]} needs {'this' if len(got['missing']) == 1 else 'these'}"
    ), got["opened"]["heading"]
    # The whole card is drawn — it is the card — and what the gate is about is the
    # part of it that can be touched: the fields it names are open, the status it
    # is asking for is on the chip, and every other value is a word nothing wires.
    assert got["opened"]["open"] == got["missing"], (
        f"the box opened on {got['opened']['open']} and the gate names {got['missing']} — "
        "somebody who chose a gated status has already said what they are doing"
    )
    assert sorted(got["opened"]["pressable"]) == sorted(["status", *got["missing"]]), (
        f"{sorted(got['opened']['pressable'])} can be pressed on a box that is about "
        f"{sorted(['status', *got['missing']])} — the rest of the card is a word each"
    )
    assert set(got["opened"]["fields"]) > set(got["opened"]["pressable"]), (
        f"the box drew only {got['opened']['fields']}, so it is a form about a gate rather "
        "than the card with a gate open on it"
    )
    assert got["opened"]["status"] == HUMAN[got["gate"]], (
        f"the status chip says {got['opened']['status']!r}: the rung that was picked is "
        "not on it, so one Save cannot commit the status and the answers together"
    )
    for name in got["missing"]:
        assert got["opened"]["required"][name] == "true", (
            f"{name} is what {got['gate']} demands and the control does not say so"
        )
        assert got["opened"]["marks"][name] == " *", (
            f"{name} carries no mark, so the sighted half of that fact is missing"
        )
    assert got["early"]["why"] == [
        f"{HUMAN[got['gate']]} needs {LABELS[name]}." for name in got["missing"]
    ], got["early"]["why"]
    assert got["early"]["sent"] == 0, (
        "the form sent a PATCH it had already worked out would be refused, and let the "
        "server say so"
    )
    assert got["early"]["form"] is True
    assert got["early"]["focused"] == got["missing"][0], (
        f"the keyboard is on {got['early']['focused']!r} rather than on the first box the "
        "refusal is about"
    )
    wanted = {"status": got["gate"]}
    for name, typed in got["answers"].items():
        kind = got["types"][name]
        wanted[name] = [typed] if kind == "list" else float(typed) if kind == "number" else typed
    assert len(got["sent"]) == 1, (
        f"the status and the fields it demands went out as {len(got['sent'])} commits, and "
        "the plan holds a record the validator refuses for the length of the first"
    )
    assert got["sent"][0]["body"]["fields"] == wanted, got["sent"][0]["body"]["fields"]
    named = [LABELS[name] for name in ("status", *got["missing"])]
    assert got["said"] == (
        f"{got['title']}: {', '.join(named[:-1])} and {named[-1]} saved"
    ), (
        f"the receipt reads {got['said']!r} and this one Save wrote the status and "
        f"{got['missing']} with it"
    )
    assert got["now"] == got["gate"], "the row did not move to the status that was picked"
    assert got["closed"] is True
    assert got["beats"] == {"writing": 1, "wrote": ["c0ffee1"]}, got["beats"]


# --------------------------------------------------------------------------- #
# Where the new record went, when the answer is "nowhere you can see"
# --------------------------------------------------------------------------- #


_UNDER_A_FILTER = """
// A parent whose own status is not the one its children open at, so a filter set
// to it draws the parent and cannot draw the child.
const parent = rowWhere(one => (POP_SCHEMA.child_kinds[one.kind] || []).length && one.status
  && one.status !== POP_SCHEMA.opens[POP_SCHEMA.child_kinds[one.kind][0]]);
if (!parent) return {error: 'no row on this table holds a kind that opens at another status'};
const kind = POP_SCHEMA.child_kinds[parent.kind][0];
// Set through the page's own control rather than by poking `params`: what is
// being asked is what happens under the filter this view really has, and
// `update` is what every facet on the bar calls.
update('status', parent.status);
await rest(400);
const filtered = {shown: menuRows().length, all: Object.keys(DATA.rows).length,
                  drawn: menuRows().some(tr => tr.dataset.id === parent.id)};
openOn(parent.id);
itemIn('new-child').click();
itemIn('new-child-' + kind).click();
const title = 'A child the filter will not draw';
typeInto('title', title);
// The chip's word, because the status of a record nobody has touched is not a
// control on this card — it is staged, and `popForm` put it there.
const opens = POP_FORM.values.status;
pressSave();
await rest(1200);
const id = Object.keys(MADE)[0] || null;
return {parent: {id: parent.id, title: parent.title, status: parent.status}, kind, title,
        opens, id, filtered, said: said(), sent: posts().length,
        known: id ? !!DATA.rows[id] : false,
        drawn: id ? menuRows().some(tr => tr.dataset.id === id) : true,
        hosted: {all: typeof HOST_ALL === 'function', shows: typeof HOST_SHOWS === 'function'}};
"""


def test_a_child_created_under_a_filter_says_where_it_went(index: Index, tmp_path: Path):
    """**A record created under a filter the child does not match lands nowhere
    visible, and the only feedback anybody gets is this sentence.**

    `refreshRows()` replaces `DATA.rows` and `draw()` re-applies `matches()`, so
    a new child that does not answer the filter is not drawn at all. The draft
    row has the same hole today and it has never been felt, because the draft row
    is visible while it is being typed. This form is not, and it closes on
    success — so the receipt has to say where the record went, and say so when
    the answer is "nowhere you can currently see".

    The three sentences `popLanded` has are one per state, and the difference
    between them is a question only the host can answer: whether that id is on
    screen RIGHT NOW, filter and window included. Without `shows` the receipt
    still names the record and makes no claim about visibility, which is honest
    and is not what the design asks for — so the last assertion is about the
    table's own wiring.
    """
    got = _at_a_form(
        index, tmp_path / "underfilter.html", _HOST_CALLS + _UNDER_A_FILTER, patience=5500
    )

    assert not got.get("error"), got
    assert got["opens"] != got["parent"]["status"], (
        f"a new {got['kind']} opens at {got['opens']!r} and the filter is set to "
        f"{got['parent']['status']!r} — the same rung, so the child is drawn and this is "
        "about nothing"
    )
    assert got["filtered"]["drawn"] is True, "the record the menu is opened on is filtered out"
    assert got["filtered"]["shown"] < got["filtered"]["all"], (
        f"the filter left all {got['filtered']['all']} rows on screen, so nothing is hidden"
    )
    assert got["sent"] == 1 and got["id"], got
    assert got["known"] is True, (
        "the host never found the record it had just made, so the receipt below is the "
        "`reload to see it` branch and says nothing about the filter"
    )
    assert got["drawn"] is False, (
        "the new child is on screen after all, so the sentence under test is not the one "
        "this state produces"
    )
    assert got["said"] == (
        f"Created {got['title']} ({got['id']}) — it is not on screen, because the filter "
        "this view has set does not match it"
    ), got["said"]
    assert got["hosted"]["shows"] is True, (
        "the table registers no `shows()`, so a create made under a filter says only that "
        "the record exists and leaves somebody looking for a row that is not there. The "
        f"one line it needs is `{_WIRING['shows']}`, beside `rows:` in its own "
        "`popServes({…})`"
    )


# --------------------------------------------------------------------------- #
# The one thing in this box that moves
# --------------------------------------------------------------------------- #


_REPLACING = """
const found = shortOf(2);
if (!found) return {error: 'the corpus holds no task short of two fields at any status'};
const row = found.row, gate = found.gate, missing = found.missing;
const tr = menuRows().find(one => one.dataset.id === row.id);
// **Opened at the FOOT of the window, which is the only place this question
// exists.** `placeFloat` flips a box that would cross the bottom gutter, so a
// form drawn in the middle of the window has room to grow into and nothing to
// prove; one drawn near the bottom is already flipped above the pointer, and
// every line the refusal adds pushes its own Save button down past the edge of a
// `position: fixed` element there is no way to scroll to.
rightOn(tr, 300, innerHeight - 24);
itemIn('status').click();
itemIn('status-' + gate).click();
const first = POP.getBoundingClientRect();
const before = {top: first.top, bottom: first.bottom, height: first.height};
pressSave();
await rest(400);
const grown = POP.getBoundingClientRect();
const button = saveIn().getBoundingClientRect();
return {id: row.id, gate, missing, before,
        after: {top: grown.top, bottom: grown.bottom, height: grown.height},
        save: {top: button.top, bottom: button.bottom},
        why: whyLines(), window: innerHeight, cap: innerHeight * 0.7,
        sent: patches().length};
"""


def test_the_form_re_places_itself_when_a_refusal_grows_it(index: Index, tmp_path: Path):
    """**The form is the exception to "the menu never moves once placed; it only
    dies", and the reason is concrete rather than aesthetic.**

    A menu's content is fixed the moment it is drawn. A form's is not: a refusal
    list growing under a box already near the foot of the window pushes its own
    Save button off the bottom, and a `position: fixed` element is the one thing
    on a page that cannot be scrolled back into view. So `popFormSays` ends in
    `popPlace()`, which places against `POP_AT` — the pointer the box was opened
    at — and flips or clamps exactly as the first placement would have.

    What the design's rule is really about stays true, and is asserted elsewhere:
    nothing that moves the page UNDER this box re-places it. A scroll, a resize,
    a pan and a filter still kill a menu, and still leave a form alone.

    The arithmetic is asserted in both directions, because only the pair says
    anything. `before.top + after.height` is where the bottom of the box WOULD
    have been had it stayed where it was — asserted to be off the window, or the
    refusal did not grow it enough for this to be asking anything — and
    `after.bottom` is where it actually is.

    Asked at a 600px window rather than the 900 everything else here uses: the
    box caps at `70vh` and scrolls, so a window tall enough makes this form fit
    with its refusals and there is nothing to move.
    """
    got = _at_a_form(index, tmp_path / "replacing.html", _REPLACING, patience=4000, tall=600)

    assert not got.get("error"), got
    assert got["why"] == [
        f"{HUMAN[got['gate']]} needs {LABELS[name]}." for name in got["missing"]
    ], got["why"]
    assert len(got["why"]) >= 2, got["why"]
    assert got["sent"] == 0, "the refusal that grew the box also went out as a PATCH"
    assert got["before"]["height"] < got["cap"] - 1, (
        f"the form was already at its {got['cap']:.0f}px cap before the refusal "
        f"({got['before']['height']:.0f}px), so it could not grow and nothing here moved"
    )
    assert got["after"]["height"] > got["before"]["height"], (
        f"the refusal list did not grow the box: {got['before']['height']:.0f}px before "
        f"and {got['after']['height']:.0f}px after"
    )
    assert got["before"]["top"] + got["after"]["height"] > got["window"] - 8, (
        f"a box left at y={got['before']['top']:.0f} would still have ended at "
        f"{got['before']['top'] + got['after']['height']:.0f} in a {got['window']}px "
        "window, which is on screen — so this test cannot tell a box that re-placed "
        "itself from one that did not"
    )
    assert got["after"]["bottom"] <= got["window"] - 7, (
        f"the box now ends at {got['after']['bottom']:.0f} in a {got['window']}px window: "
        "it grew where it stood, and a `position: fixed` element is the one thing on the "
        "page there is no way to scroll to"
    )
    assert got["after"]["top"] < got["before"]["top"], (
        "the box did not move, so it is only on screen by luck of how much the refusal "
        "happened to add"
    )
    assert 0 <= got["save"]["top"] and got["save"]["bottom"] <= got["window"], (
        f"Save is at {got['save']}, off a {got['window']}px window — which is the whole "
        "of what the re-placement is for"
    )


# --------------------------------------------------------------------------- #
# Cut 5: `Delete…`, which is the one gesture here that cannot be undone from the
# page
#
# The commit takes the record off the tip of the branch and leaves every version
# of it in history, which is the whole of what makes a delete button defensible
# — and is exactly why the questions below are about what somebody was SHOWN
# before they agreed to it, and not only about what went on the wire.
#
# `GET /api/cascade/{id}` is answered by `_cascade_facts` itself (see
# `_reaches`), so what the stub hands the page is what the route would: the ids
# the deletion is compare-and-swapped against, and the sentences that name the
# same records by title.
# --------------------------------------------------------------------------- #


# The title the plan-moved fixture files its late child under. Written down
# because it is the word that proves a redraw: a panel showing it is a panel
# drawn from the answer that came back AFTER the refusal.
LATE_CHILD = "Filed while the panel was open"


def _whose_delete_reaches(index: Index) -> str:
    """A planned record that takes at least two others with it and frees a third.

    Searched by shape rather than named, which is this file's rule everywhere
    else: `seed/` is the demo and is free to be rewritten, so a test that names
    an id in it is a test a copy edit turns red. Two and not one because a count
    of 1 cannot tell `<strong>{{ count }}</strong>` from a hard-coded number, and
    the freed record because the two sentences are drawn differently on purpose
    and a corpus with only one of them cannot say so.
    """
    for record_id in index.plan:
        facts = _cascade_facts(index, record_id)
        if len(facts["deletes"]) >= 2 and facts["frees"]:
            return record_id
    pytest.skip(  # pragma: no cover - a fact about the corpus, not about the code
        "no planned record's deletion takes two records with it and frees a third, "
        "so the two sentences cannot both be drawn"
    )


def _a_leaf(index: Index) -> str:
    """A planned record nothing is filed under and nothing waits on."""
    for record_id in index.plan:
        if not _cascade_facts(index, record_id)["also"]:
            return record_id
    pytest.skip(  # pragma: no cover - a fact about the corpus, not about the code
        "every planned record's deletion reaches another, so the plain question "
        "cannot be asked"
    )


def _as_read(said: dict) -> str:
    """One of `said`'s parts as the panel reads aloud, in one piece.

    `popReach` draws the count in a `<strong>` and each title in a chip of its
    own — parts and not a finished sentence, because a title is held to one rule,
    that it is not blank, so comma-joining three of them offers a reader four
    records and asks them to press Delete on that. What a person reads is still
    one sentence, which is what this rebuilds: every part with one space between,
    exactly as `append` leaves them.
    """
    return " ".join(
        [
            said["lead"],
            *([str(said["count"])] if said["count"] else []),
            *([said["mid"]] if said["mid"] else []),
            *said["names"],
            *([said["tail"]] if said["tail"] else []),
        ]
    )


def _after_a_late_child(demo_root: Path, index: Index, parent_id: str) -> dict:
    """The same record's cascade on a plan that moved while the panel was open.

    Somebody files a task under the pitch somebody else is looking at a delete
    confirmation for. That is the exact sequence the DELETE route's
    compare-and-swap on `also` exists for, and this is the answer the route gives
    the second time it is asked — derived by building the index again with the
    record in it and running `_cascade_facts` over that, so the new sentence is
    the plan's own and not a string this file made up.
    """
    like = RUNG[index.records[_cascade_facts(index, parent_id)["deletes"][0]].kind]
    late = f"{like.prefix}-0ff00d"
    front = [f"id: {late}", f"kind: {like.name}", f"title: {LATE_CHILD}"]
    if like.statuses:
        front.append(f"status: {like.statuses[0]}")
    front.append(f"parent: {parent_id}")
    records, config, _ = load_repo(demo_root)
    records.append(
        parse_text(
            "---\n" + "\n".join(front) + "\n---\n\nFiled late.\n",
            f"{like.directory}/{late}.md",
        )
    )
    moved = build_index(records, config, date(2026, 8, 17))
    return {
        "id": parent_id,
        "title": _titles_for(moved, [parent_id])[0],
        **_cascade_facts(moved, parent_id),
    }


# How the confirmation face is read, and it is neither how an item is read nor
# how the form is. A panel is no `.popitem` at all — `popControls()` is empty
# while one is up, which is itself one of the assertions — and every handle here
# is a `data-kind` slug `pop.py` writes down.
_ASKING = """
const partAsked = kind => {
  const found = POP.querySelector('[data-kind="' + kind + '"]');
  return found ? found.textContent : '';
};
// **Whether a panel is on screen, which is not whether one is in the box.**
// `popClose` deliberately leaves the children where they are, so a
// `querySelector('[data-kind="confirm"]')` answers a dismissed panel exactly as
// it answers a live one — and every `it closed` assertion written against that
// would pass with the panel still up.
const askUp = () => popIsOpen() && POP.classList.contains('popasking');
// The four ways the box says which face it is wearing. `items: 0` is the one
// worth having: a box that drew a panel over its own menu items is a
// `role="dialog"` full of `menuitem`s, and nothing else here would notice.
const panelIs = () => ({up: askUp(), role: POP.getAttribute('role'),
                        label: POP.getAttribute('aria-label'), items: popControls().length});
// The consequences as drawn: the sentence somebody reads, the number they are
// agreeing to, and the titles as SEPARATE elements — which is the half a
// comma-joined string cannot have.
const reachLines = () => [...POP.querySelectorAll(
  '[data-kind="confirm-deletes"], [data-kind="confirm-frees"]')].map(one => ({
    kind: one.dataset.kind, text: one.textContent, mild: one.classList.contains('popmild'),
    strong: [...one.querySelectorAll('strong')].map(many => many.textContent),
    names: [...one.querySelectorAll('.popnamed')].map(chip => chip.textContent)}));
const whyAsked = () => [...POP.querySelectorAll('[data-kind="confirm-why-line"]')]
  .map(one => one.textContent);
const reallyIn = () => POP.querySelector('[data-kind="confirm-delete"]');
const keepIn = () => POP.querySelector('[data-kind="confirm-keep"]');
// What the panel would authorise, read off the panel itself rather than off the
// wire: `also` is the list the DELETE is compare-and-swapped against, and it is
// `null` until the plan has answered.
const askedAbout = () => POP_CONFIRM
  ? {id: POP_CONFIRM.id, title: POP_CONFIRM.title, also: POP_CONFIRM.also,
     deletes: POP_CONFIRM.deletes}
  : null;
const askOn = id => { openOn(id); itemIn('delete').click(); };
// Everything this page put on the wire, less the one request the shell makes on
// its own. `readPile` polls `/api/health` on a minute, and a test that asserted
// over raw `SENT` would be a test that goes red on the day somebody shortens
// that interval — while what is being asked here is about the DELETE.
const asked = () => SENT.filter(one => !one.url.includes('/api/health'))
  .map(one => one.method + ' ' + one.url);
"""


def _at_a_panel(index: Index, where: Path, script: str, patience: int = 4000) -> dict:
    """One writer's table in Chrome, asked one question about the confirmation."""
    return measured_in(
        chrome(),
        a_writers_table(index),
        where,
        1280,
        _OPENING + _READERS + _served(index) + _WRITING + _ASKING + script,
        patience=patience,
    )


# --------------------------------------------------------------------------- #
# What the panel asks, and what it will not offer until the plan has answered
# --------------------------------------------------------------------------- #


_ASKED = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
// **The answer HELD**, which is the only way to read the panel in the state the
// design is most specific about: drawn, holding the question, and with nothing
// pressable on it yet. Against an answer that came back immediately this half
// would be asking nothing at all.
let release = null;
CASCADE = id => new Promise(done => { release = () => done({status: 200, body: REACH[id]}); });
askOn(TARGET);
const asking = Object.assign(panelIs(), {
  heading: partAsked('confirm-heading'), note: partAsked('confirm-note'),
  reach: reachLines(), why: whyAsked(),
  really: {disabled: reallyIn().disabled, text: reallyIn().textContent},
  keep: keepIn().textContent, focused: document.activeElement.dataset.kind,
  panel: askedAbout(), asked: cascades().map(one => one.url), wire: asked()});
// Pressed while it is still a question. There is nothing to authorise yet, and
// this is the press `asking.really.disabled = true` is written for: the box is
// placed at the pointer that opened it, so the destructive control appears under
// a hand that has just pressed something.
reallyIn().click();
await rest(100);
const early = {deletions: deletions().length, up: askUp()};
release();
await rest(500);
const answered = Object.assign(panelIs(), {
  note: partAsked('confirm-note'), reach: reachLines(), why: whyAsked(),
  enabled: !reallyIn().disabled, panel: askedAbout(),
  asked: cascades().map(one => one.url), deletions: deletions().length,
  patched: patches().length, posted: posts().length, base: baseNow(),
  beats: beatsNow(), row: !!DATA.rows[TARGET]});
return {asking, early, answered};
"""


def test_delete_asks_the_plan_what_would_go_and_draws_it_before_offering_anything(
    index: Index, tmp_path: Path
):
    """**`Delete…` never asks a bare question**, and this is the whole of what it
    asks instead.

    The panel opens holding the record's name and nothing else, says it is
    working out what the deletion would take with it, and asks
    `GET /api/cascade/{id}`. What comes back is drawn: the sentences a person
    decides on, with the count in its own element and each title in a chip of its
    own — and the ids, which nobody reads and which are what the DELETE is
    compare-and-swapped against. Both halves are asserted against
    `_cascade_facts` run over this index in Python, because that is what the
    route answers with; a panel that agreed with a sentence written out in this
    file would prove only that two files had been edited together.

    **The destructive control is disabled from the moment it is drawn**, and it
    is pressed here while it is. The record page arranges this structurally — its
    Delete button is hidden and the panel is drawn somewhere else — and this box
    has no somewhere else: it is placed at `POP_AT`, the same pointer, and the
    press that opened the panel was on an item inside the panel's own outline. So
    the guarantee is earned by the round trip instead, and what this test asks is
    that the round trip really is in the way: a press before the plan answers
    sends nothing.

    And the box is wearing one face. `items: 0` is the assertion that says so —
    a panel drawn over the menu items it replaced would be a `role="dialog"` full
    of `menuitem`s, announced to a reader as a menu with no items in it.
    """
    target = _whose_delete_reaches(index)
    facts = _reaches(index)[target]
    got = _at_a_panel(
        index, tmp_path / "asked.html", f"const TARGET = {target!r};\n" + _ASKED
    )

    assert not got.get("error"), got
    asking, early, answered = got["asking"], got["early"], got["answered"]

    assert asking["up"] is True, "`Delete…` drew no confirmation at all"
    assert asking["role"] == "dialog", (
        f"the box is a {asking['role']!r} while it is asking a question with two "
        "buttons on it"
    )
    assert asking["label"] == f'Delete "{facts["title"]}"?', asking["label"]
    assert asking["heading"] == f'Delete "{facts["title"]}"?', asking["heading"]
    assert asking["items"] == 0, (
        "the panel was drawn over the menu's own items, so the box is a dialog "
        "holding a list of menuitems"
    )
    assert asking["note"] == "Working out what this would take with it…", asking["note"]
    assert asking["reach"] == [] and asking["why"] == [], (
        f"the panel drew consequences before the plan had answered: {asking['reach']}"
    )
    assert asking["panel"]["also"] is None, (
        f"the panel already holds {asking['panel']['also']} to send — a list worked "
        "out in the browser is a list that cannot see the records this view does not "
        "draw, and every delete against it would be refused"
    )
    assert asking["really"]["disabled"] is True, (
        "`Delete it` is pressable the instant the panel appears, under a pointer that "
        "has just pressed the item that opened it"
    )
    assert asking["really"]["text"] == "Delete it" and asking["keep"] == "Keep it", asking
    assert asking["focused"] == "confirm-keep", (
        f"the keyboard landed on {asking['focused']!r} — it goes on the way out of a "
        "destructive question, never on the way through it"
    )
    assert asking["asked"] == [f"/api/cascade/{target}"], asking["asked"]
    assert asking["wire"] == [f"GET /api/cascade/{target}"], (
        f"opening the panel put {asking['wire']} on the wire, and asking what a deletion "
        "would take with it is the whole of what it may do"
    )
    assert early["deletions"] == 0, (
        "a press on `Delete it` before the plan had answered deleted the record, and "
        "nobody had been shown what went with it"
    )
    assert early["up"] is True, "that press took the panel away"

    assert answered["enabled"] is True, (
        "the plan answered and `Delete it` is still not pressable, so the panel is a "
        "question with no way to say yes"
    )
    assert answered["note"] == "Commit deletion? Can only be undone with git revert.", (
        answered["note"]
    )
    assert [line["kind"] for line in answered["reach"]] == [
        f"confirm-{said['kind']}" for said in facts["said"]
    ], answered["reach"]
    assert len(answered["reach"]) == 2, (
        f"the panel drew {len(answered['reach'])} sentences and the plan sent "
        f"{len(facts['said'])}"
    )
    for line, said in zip(answered["reach"], facts["said"], strict=True):
        assert line["text"] == _as_read(said), (
            f"the panel reads {line['text']!r} and the plan said {_as_read(said)!r}"
        )
        # One element per title, which is the half a sentence cannot carry: a
        # title is held to one rule, that it is not blank, so three titles joined
        # by commas — one of which has a comma in it — offer a reader four
        # records and ask them to press Delete on that.
        assert line["names"] == said["names"], (
            f"the panel named {line['names']} and the plan named {said['names']}"
        )
        assert line["strong"] == ([str(said["count"])] if said["count"] else []), (
            f"the count is drawn as {line['strong']} — the number somebody is agreeing "
            "to is the one part of that sentence that is not prose"
        )
        # The quiet line is where nothing is destroyed and a field is edited
        # instead. Drawing the two the same way teaches people to skim both.
        assert line["mild"] is (said["kind"] == "frees"), line
    assert answered["panel"]["also"] == facts["also"], (
        f"the panel will authorise {answered['panel']['also']} and the plan's answer "
        f"was {facts['also']}"
    )
    assert answered["panel"]["deletes"] == facts["deletes"], answered["panel"]
    assert answered["asked"] == [f"/api/cascade/{target}"], (
        f"the panel asked the plan {len(answered['asked'])} times for one question"
    )
    assert answered["deletions"] == 0, "drawing the consequences deleted the record"
    assert answered["patched"] == 0 and answered["posted"] == 0, answered
    assert answered["base"] == HEAD and answered["beats"] == {"writing": 0, "wrote": []}, (
        f"opening a question moved the page's commit or its write counters: {answered}"
    )
    assert answered["row"] is True, "the record is out of the plan and nobody pressed anything"


_A_LEAF = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
askOn(TARGET);
await rest(400);
const asking = Object.assign(panelIs(), {
  heading: partAsked('confirm-heading'), note: partAsked('confirm-note'),
  reach: reachLines(), enabled: !reallyIn().disabled, panel: askedAbout(),
  asked: cascades().map(one => one.url)});
reallyIn().click();
await rest(600);
return {asking, sent: deletions(), said: said(), up: askUp(), open: popIsOpen(),
        row: !!DATA.rows[TARGET], drawn: menuRows().some(tr => tr.dataset.id === TARGET)};
"""


def test_a_record_with_nothing_under_it_asks_a_plain_question(index: Index, tmp_path: Path):
    """**Empty must not look like broken**, which is finding F1 pointed at the one
    panel where the two are a deletion apart.

    A record nothing is filed under and nothing waits on has an empty cascade,
    and the panel draws exactly that: the question, the git-revert line, and no
    sentences — because there are none to say. It is a plain question and not a
    missing one, and the thing that makes it readable as plain rather than as
    unfinished is that the note has moved on from "Working out what this would
    take with it…" and the button is live.

    The other half of that pair is the route's 404 for an id the plan has not
    got, which is why it answers one: a panel that drew an empty cascade for a
    typo and an empty cascade for a leaf could not say which it was, and the
    second is a delete somebody is about to authorise.

    And the receipt is the leaf's own. `popDelete` says "with N records that were
    filed under it" when there were some; here there are none, so the sentence
    stops after the title rather than reporting a zero.
    """
    target = _a_leaf(index)
    facts = _reaches(index)[target]
    got = _at_a_panel(index, tmp_path / "leaf.html", f"const TARGET = {target!r};\n" + _A_LEAF)

    assert not got.get("error"), got
    asking = got["asking"]
    assert asking["up"] is True, "`Delete…` drew no confirmation for a record with no children"
    assert asking["heading"] == f'Delete "{facts["title"]}"?', asking["heading"]
    assert asking["asked"] == [f"/api/cascade/{target}"], (
        "the panel did not ask the plan at all about a record it could see had no "
        "children: what this view can see is `index.plan`, and the answer is about "
        "`index.records`"
    )
    assert asking["reach"] == [], (
        f"the panel drew {asking['reach']} for a record whose deletion reaches nothing"
    )
    assert asking["note"] == "Commit deletion? Can only be undone with git revert.", (
        f"the note still reads {asking['note']!r}, so a plain question is indistinguishable "
        "from one still waiting for its answer"
    )
    assert asking["enabled"] is True, "a leaf's deletion cannot be agreed to"
    assert asking["panel"]["also"] == [], asking["panel"]
    assert len(got["sent"]) == 1, got["sent"]
    assert got["sent"][0]["body"] == {"base_commit": HEAD, "also": []}, got["sent"][0]["body"]
    assert got["said"] == f"{facts['title']} is deleted", (
        f"the receipt reads {got['said']!r} — a record that took nothing with it does not "
        "report a count"
    )
    assert got["up"] is False and got["open"] is False, "the panel outlived the deletion"
    assert got["row"] is False and got["drawn"] is False, (
        "the record is still in `DATA.rows` or still drawn, so the host never re-read the "
        "plan after the commit"
    )


# --------------------------------------------------------------------------- #
# Agreeing to it, and the one request that goes out
# --------------------------------------------------------------------------- #


_CONFIRMED = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
askOn(TARGET);
await rest(400);
const panel = askedAbout();
reallyIn().click();
const during = {disabled: reallyIn().disabled, deletions: deletions().length, up: askUp()};
await rest(900);
return {panel, during, sent: deletions(), patched: patches().length, posted: posts().length,
        said: said(), up: askUp(), open: popIsOpen(), base: baseNow(), beats: beatsNow(),
        ours: oursNow(),
        row: !!DATA.rows[TARGET], drawn: menuRows().some(tr => tr.dataset.id === TARGET),
        kids: panel.deletes.filter(id => DATA.rows[id]),
        kidsDrawn: panel.deletes.filter(id => menuRows().some(tr => tr.dataset.id === id)),
        freed: (REACH[TARGET].frees || []).filter(id => DATA.rows[id])};
"""


def test_confirming_sends_one_delete_and_the_record_goes(index: Index, tmp_path: Path):
    """**One request, carrying the ids the panel showed and nothing else.**

    The route commits the record and its whole subtree together, for a reason
    `web.py` writes down: one decision, and a `git log` showing a pitch removed
    and then four tasks removed says four things that are not true. So a page
    that sent one DELETE per doomed record would be writing that history — and it
    would leave the plan in a state a protected branch cannot be talked out of if
    the third of five failed.

    **The body is asserted whole**, which is the half `popSend`'s `sends` change
    is for. A deletion sends `{base_commit, also}` — the ids the reader agreed
    to, compare-and-swapped by the route against its own answer — and no
    `fields`, because a `fields: {}` on a deletion is this page telling the
    server something it does not mean.

    And what the deletion did is read off the plan afterwards rather than assumed:
    the record is gone from `DATA.rows` and out of the tbody, everything filed
    under it went with it, and **the records that merely depended on it are still
    there** — they keep their files and lose a dependency, which is the whole of
    why `cascade_of` answers two lists rather than one.

    The receipt names the reach as well as the record, because by the time it is
    said the panel that listed it is gone, and "deleted" alone is a receipt for
    one file about a commit that removed eight.
    """
    target = _whose_delete_reaches(index)
    facts = _reaches(index)[target]
    got = _at_a_panel(
        index, tmp_path / "confirmed.html", f"const TARGET = {target!r};\n" + _CONFIRMED
    )

    assert not got.get("error"), got
    assert len(got["sent"]) == 1, (
        f"{len(got['sent'])} DELETEs went out for one press, and the route takes the "
        f"whole subtree in one commit: {[one['url'] for one in got['sent']]}"
    )
    assert got["sent"][0]["url"] == f"/api/record/{target}", got["sent"][0]["url"]
    assert got["sent"][0]["body"] == {"base_commit": HEAD, "also": facts["also"]}, (
        got["sent"][0]["body"]
    )
    assert "fields" not in got["sent"][0]["body"], (
        "the deletion sent a `fields` key, which is this page telling the server "
        "something it does not mean"
    )
    assert got["patched"] == 0 and got["posted"] == 0, got
    assert got["during"]["deletions"] == 1, "the press sent nothing at all"
    assert got["during"]["disabled"] is True, (
        "`Delete it` is still pressable while the commit is in the air, and the second "
        "press would be sent against a record that may already be gone"
    )
    assert got["up"] is False and got["open"] is False, (
        "the box outlived the commit, over a table that has just been redrawn"
    )
    assert got["row"] is False and got["drawn"] is False, (
        f"{target} is still in the plan this page is showing after a commit that removed it"
    )
    assert got["kids"] == [] and got["kidsDrawn"] == [], (
        f"{got['kids']} were filed under it and are still on the table: the host re-read "
        "the plan and the rows it drew are from before the deletion"
    )
    assert got["freed"] == facts["frees"], (
        f"the records that merely depended on it are gone as well: {facts['frees']} became "
        f"{got['freed']} — they keep their files and lose a dependency"
    )
    gone = len(facts["deletes"])
    assert got["said"] == (
        f"{facts['title']} is deleted, with {gone} records that were filed under it"
    ), got["said"]
    assert got["base"] == "c0ffee1", (
        f"`#base` is still {got['base']} after a commit, so the next write from this page "
        "collides with the commit it just made"
    )
    # Silent on both, because a DELETE is invisible to the announce census in
    # `tests/test_web.py` and a pair here would count a write it cannot see.
    # `openproj:ours` is what a delete sends instead — the shell's own event for a
    # commit that is this page's, which stops the stream's news arriving as "The
    # plan changed" about the record just removed.
    assert got["beats"] == {"writing": 0, "wrote": []}, got["beats"]
    assert got["ours"] == ["c0ffee1"], f"the commit was not claimed as ours: {got['ours']}"


# --------------------------------------------------------------------------- #
# Not agreeing to it, which has to be silent on the wire
# --------------------------------------------------------------------------- #


_KEPT = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
const ways = [];
const leave = async (how, go) => {
  // **The record is checked for before each way**, and it is not a nicety: a way
  // out that deleted it takes the row with it, `openOn` then throws inside this
  // script, and the harness reports "the page reported nothing" — which is the
  // one failure message that says nothing about the defect it found.
  if (!menuRows().some(tr => tr.dataset.id === TARGET)) {
    ways.push({how: how, gone: true, up: askUp(), open: popIsOpen(), said: said(),
               deletions: deletions().length});
    return;
  }
  askOn(TARGET);
  await rest(300);
  const before = deletions().length;
  go();
  await rest(200);
  ways.push({how: how, gone: false, up: askUp(), open: popIsOpen(), said: said(),
             deletions: deletions().length - before});
};
await leave('keep', () => keepIn().click());
await leave('escape', () => pressKey('Escape'));
// The four signals below `Keep it` and Escape, and the panel deliberately does
// NOT resist them the way the form does: a form holds typed work, this holds a
// question, and a destructive panel that will not go away when you reach past it
// is worse than one that closes easily.
await leave('outside', () => document.body.dispatchEvent(
  new PointerEvent('pointerdown', {bubbles: true, clientX: 5, clientY: 5})));
await leave('scroll', () => document.dispatchEvent(new Event('scroll')));
await leave('filter', () => dispatchEvent(new CustomEvent('openproj:filter')));
return {ways, wire: asked(), base: baseNow(), beats: beatsNow(),
        row: !!DATA.rows[TARGET], drawn: menuRows().some(tr => tr.dataset.id === TARGET)};
"""


def test_keeping_it_sends_nothing_at_all(index: Index, tmp_path: Path):
    """**The wire is asserted silent, and not merely the box shut.**

    A panel that closed and deleted anyway is the failure this test is for, and
    it is invisible from the DOM: the box is gone either way, the table redraws
    either way, and on a protected branch the news arrives as a commit somebody
    else reads. So what is asserted is that no DELETE was sent by any of the five
    ways out, that the only requests on the wire are the five questions the
    panels asked, and that the record is still in the plan afterwards.

    **Five ways, because the confirmation does not inherit the form's dismissal
    exemption.** `popClose` refuses to shut a form, and copying that here would
    have put an un-dismissable destructive panel on the page — so a press
    outside, a scroll and a filter close this one exactly as they close a menu.
    Reaching past a question cancels it, which is the answer anybody reaching
    past it wanted.

    The two that are decisions say so. `Keep it` and Escape both announce
    "nothing was deleted" — the same words, because a control and the key that
    does the same thing may not report it differently, and this app has already
    had one word mean three things on one screen.
    """
    target = _whose_delete_reaches(index)
    got = _at_a_panel(index, tmp_path / "kept.html", f"const TARGET = {target!r};\n" + _KEPT)

    assert not got.get("error"), got
    assert [way["how"] for way in got["ways"]] == [
        "keep",
        "escape",
        "outside",
        "scroll",
        "filter",
    ], got["ways"]
    for way in got["ways"]:
        assert way["gone"] is False, (
            f"the record was already out of the plan by the time {way['how']!r} was "
            "asked, so an earlier way out of this panel deleted it"
        )
        assert way["deletions"] == 0, (
            f"leaving the panel by {way['how']!r} sent a DELETE: the box shuts either "
            "way, so this is a deletion nobody would learn about until the commit"
        )
        assert way["up"] is False and way["open"] is False, (
            f"the panel survived {way['how']!r}, which is a destructive question that "
            "will not go away when somebody reaches past it"
        )
    for decided in got["ways"][:2]:
        assert decided["said"] == "nothing was deleted", (
            f"{decided['how']!r} announced {decided['said']!r} — `Keep it` and Escape do "
            "the same thing and may not report it in two vocabularies"
        )
    assert got["wire"] == [f"GET /api/cascade/{target}"] * len(got["ways"]), (
        f"the wire carried {got['wire']} — five panels asked what a deletion would take "
        "with it, and nothing else should have gone out at all"
    )
    assert got["row"] is True and got["drawn"] is True, (
        f"{target} is out of the plan after five people said no to deleting it"
    )
    assert got["base"] == HEAD, "`#base` moved on a deletion that never happened"
    assert got["beats"] == {"writing": 0, "wrote": []}, (
        f"a cancelled deletion dispatched the shell's write events: {got['beats']}"
    )


# --------------------------------------------------------------------------- #
# The plan moved while the panel was open
# --------------------------------------------------------------------------- #


_STALE = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
// The route's own 409: it refuses a deletion whose `also` is not the list it
// computes itself, which is somebody filing a record under this one while the
// panel sat open. A rule's sentence and not the store's compare-and-swap report
// — two shapes, one reader, and `refusal()` is the only thing that may tell them
// apart.
const STALE = 'the plan changed while that was open: deleting ' + REACH[TARGET].title
  + ' now affects one more record. Nothing was deleted — read it again and decide.';
ANSWER = () => ({status: 409, body: {detail: STALE}});
askOn(TARGET);
await rest(400);
const before = {reach: reachLines(), also: askedAbout().also.slice()};
// And the plan really does move: from here the route answers with the cascade of
// an index that has one more record filed under this one. `MOVED` is
// `_cascade_facts` run over that index, so the second answer is as much the
// plan's own as the first was.
CASCADE = id => ({status: 200, body: id === TARGET ? MOVED : REACH[id]});
reallyIn().click();
const during = {disabled: reallyIn().disabled};
await rest(800);
const after = {up: askUp(), why: whyAsked(), reach: reachLines(), note: partAsked('confirm-note'),
               also: askedAbout() ? askedAbout().also.slice() : null,
               enabled: !reallyIn().disabled, asked: cascades().length,
               deletions: deletions().length, said: said(), base: baseNow(),
               focused: document.activeElement.dataset.kind, kinds: popKinds()};
// The second press, against the list the panel is showing NOW.
ANSWER = () => ({status: 200,
                 body: {outcome: 'committed', commit: 'c0ffee2', pushed: true}});
reallyIn().click();
await rest(900);
return {STALE, before, during, after, sent: deletions(), open: popIsOpen(),
        said: said(), base: baseNow(), beats: beatsNow(), ours: oursNow(),
        row: !!DATA.rows[TARGET]};
"""


def test_a_refusal_re_asks_the_plan_and_redraws_what_would_go(
    index: Index, demo_root: Path, tmp_path: Path
):
    """**A refused deletion re-asks the cascade rather than offering the same
    list again.**

    The refusal a delete gets is almost always that the plan moved under the
    panel — somebody filed a task under this pitch while it sat open — and the
    route says so by refusing a deletion whose `also` is not the list it computes
    itself. What the panel is showing at that moment is therefore a claim about a
    plan that no longer exists, and pressing again against it would be refused by
    the same rule for the same reason, for ever.

    So the sentences are replaced, the `also` that goes on the wire is replaced
    with them, and only then is the button pressable again. The redraw is
    asserted against `_cascade_facts` run over an index that really does have the
    late record in it, and the new title is asserted to be in the sentence: a
    panel that merely re-enabled its button would pass every other assertion
    here.

    **The reason stays.** `popCascade` does not clear the refusal it was sent
    back by, because that sentence is why the panel changed under somebody, and
    it has to still be there when it has. The keyboard is put on it for the same
    reason the form's refusal takes the keyboard.

    And the panel survives at all, which is not free: `popSay` draws a refusal
    into the menu by replacing the level that is up, and doing that here would
    have replaced the question with a list of menu items half a tick after the
    reader pressed Delete it.
    """
    target = _whose_delete_reaches(index)
    facts = _reaches(index)[target]
    moved = _after_a_late_child(demo_root, index, target)
    got = _at_a_panel(
        index,
        tmp_path / "stale.html",
        f"const TARGET = {target!r};\nconst MOVED = {json.dumps(moved)};\n" + _STALE,
        patience=5500,
    )

    assert not got.get("error"), got
    assert moved["also"] != facts["also"], (
        "the plan-moved fixture built the same cascade as the plan itself, so the redraw "
        "below cannot be told from no redraw at all"
    )
    before, after = got["before"], got["after"]
    assert before["also"] == facts["also"], before["also"]
    assert got["during"]["disabled"] is True, (
        "`Delete it` stayed pressable while the deletion was in the air"
    )
    assert after["up"] is True, (
        "the refusal took the panel away and drew the menu back in its place, half a tick "
        f"after the press: the box is showing {after['kinds']}"
    )
    assert after["why"] == [got["STALE"]], (
        f"the panel says {after['why']} and the server said {got['STALE']!r} — a 409 here "
        "has two shapes and only `refusal()` reads them in the right order"
    )
    assert after["focused"] == "confirm-why", (
        f"the keyboard is on {after['focused']!r} rather than on the reason the deletion "
        "did not happen"
    )
    assert after["asked"] == 2, (
        f"the panel asked the plan {after['asked']} times: a refusal is the one moment its "
        "list is known to be wrong, and it is the moment to ask again"
    )
    assert after["deletions"] == 1, (
        "the refusal was answered by sending the deletion again, against the list the "
        "server had just refused"
    )
    assert after["also"] == moved["also"], (
        f"the panel would still authorise {after['also']} and the plan now answers "
        f"{moved['also']}"
    )
    assert [line["text"] for line in after["reach"]] == [
        _as_read(said) for said in moved["said"]
    ], after["reach"]
    assert any(LATE_CHILD in line["names"] for line in after["reach"]), (
        f"the record filed while the panel was open is named nowhere in {after['reach']} — "
        "the panel re-enabled its button over the list the server refused"
    )
    assert after["enabled"] is True, (
        "the panel drew the new consequences and left no way to agree to them"
    )
    assert after["note"] == "Commit deletion? Can only be undone with git revert.", after["note"]
    assert after["base"] == HEAD, "`#base` moved on a deletion the server refused"

    assert len(got["sent"]) == 2, [one["url"] for one in got["sent"]]
    assert got["sent"][0]["body"]["also"] == facts["also"], got["sent"][0]["body"]
    assert got["sent"][1]["body"] == {"base_commit": HEAD, "also": moved["also"]}, (
        f"the second press sent {got['sent'][1]['body']} — what goes on the wire is the "
        "list the panel showed, and the panel is showing the plan as it now is"
    )
    assert got["open"] is False and got["row"] is False, (
        "the deletion that landed left the record in the plan this page is showing"
    )
    assert got["base"] == "c0ffee2", got["base"]
    assert got["beats"] == {"writing": 0, "wrote": []}, (
        f"a deletion dispatched the shell's write pair, which the announce census "
        f"cannot see a DELETE to balance against: {got['beats']}"
    )
    # One `ours`, not two: the refused attempt committed nothing, and this event
    # carries a sha or it is not sent. That asymmetry is why it is asserted here
    # rather than only on the happy path.
    assert got["ours"] == ["c0ffee2"], (
        f"a refused deletion and a landed one claimed {got['ours']}"
    )


# --------------------------------------------------------------------------- #
# Two presses on the destructive control
# --------------------------------------------------------------------------- #


_TWICE_ON_DELETE = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
// The answer HELD, which is the whole of the window this guard is about: a write
// here is a commit and a push against a repository on GitHub, so it is seconds,
// and the panel stays up for all of them with `Delete it` under the pointer.
let release = null;
ANSWER = () => new Promise(done => {
  release = () => done({status: 200,
                        body: {outcome: 'committed', commit: 'c0ffee1', pushed: true}});
});
askOn(TARGET);
await rest(400);
reallyIn().click();
const held = {disabled: reallyIn().disabled, deletions: deletions().length};
// And again, PAST the attribute. `POP_WRITING` is the rule and `disabled` is
// only how it is shown — the form's own twice-pressed test goes past it through
// the submit event, and this panel's second route is a control re-enabled by
// anything at all, which `popCascade` itself does when a refusal re-asks.
reallyIn().disabled = false;
reallyIn().click();
await rest(250);
const during = {deletions: deletions().length, why: whyAsked(), up: askUp(),
                writing: beats.writing};
if (!release) return {error: 'the first press sent no DELETE, so nothing is in the air'};
release();
await rest(900);
return {held, during, sent: deletions(), said: said(), open: popIsOpen(),
        row: !!DATA.rows[TARGET], beats: beatsNow(), ours: oursNow()};
"""


def test_two_presses_on_delete_it_with_no_gap_send_one_delete(index: Index, tmp_path: Path):
    """Two presses 0.9s apart minted two records on the deployed service, which
    is why `CREATING` exists in `table.py`. This is the same gesture aimed the
    other way, and a repeat here is not the harmless thing a repeated PATCH is:
    the second request is a deletion of a record that may already be gone, and
    its answer is a 404 or a 409 about a plan somebody now has to go and read.

    So `POP_WRITING` refuses it, before the `openproj:writing` event — an early
    return after that event leaves the shell's count held one too high and the
    moved-banner never appears again.

    **The second press goes past the disabled attribute on purpose.** `disabled`
    is how the rule is shown and not the rule, and there is a live path through
    it: `popCascade` re-enables this very button whenever a refusal re-asks the
    plan, while the earlier deletion may still be in the air. A panel whose only
    guard was the attribute would pass a test that only clicked twice.

    And the refusal is drawn into the panel rather than only announced. The
    reader is looking at the box, and this is the easiest refusal in the whole
    menu to meet — the control is under the pointer and the box stays up — so it
    is the last one that should be invisible.
    """
    target = _whose_delete_reaches(index)
    facts = _reaches(index)[target]
    got = _at_a_panel(
        index, tmp_path / "twicedelete.html", f"const TARGET = {target!r};\n" + _TWICE_ON_DELETE,
        patience=5000,
    )

    assert not got.get("error"), got
    assert got["held"] == {"disabled": True, "deletions": 1}, got["held"]
    assert got["during"]["deletions"] == 1, (
        f"{got['during']['deletions']} deletions went out for two presses, the second of "
        "them against a record the first may already have removed"
    )
    # **Zero, and not one.** A delete announces no `openproj:writing` at all —
    # the sweep in `tests/test_web.py` counts POST, PATCH and PUT call sites and
    # asserts the page holds exactly that many pairs, and a DELETE matches none
    # of the three, so a pair here would announce a write that census cannot see.
    # The record page's own delete is bracketed by nothing for the same reason.
    # What a delete owes the shell instead is bought in `popDelete`'s `finally`:
    # `openproj:ours` for the commit, and `popClose` for a menu opened elsewhere.
    #
    # So what this asserts is that the refusal is still free: the second press
    # must not leave a count raised that nothing will ever lower.
    assert got["during"]["writing"] == 0, (
        "a delete dispatched `openproj:writing`, which the announce census in "
        "`tests/test_web.py` cannot see a DELETE to balance against"
    )
    assert got["during"]["why"] == ["A save is already going out. Wait for it to answer."], (
        f"the second press was refused in silence, or somewhere else: {got['during']['why']}"
    )
    assert got["during"]["up"] is True, "the panel went down before the answer arrived"
    assert len(got["sent"]) == 1, [one["url"] for one in got["sent"]]
    assert got["said"] == (
        f"{facts['title']} is deleted, with {len(facts['deletes'])} records that were "
        "filed under it"
    ), got["said"]
    assert got["open"] is False and got["row"] is False, got
    # Neither beat, on the landed delete either — same reason as the refusal
    # above. `openproj:ours` is what the shell hears instead, and it is what
    # stops the stream's own news arriving as "The plan changed" about the
    # record this page has just removed.
    assert got["beats"] == {"writing": 0, "wrote": []}, got["beats"]
    assert got["ours"] == ["c0ffee1"], (
        f"the commit was not claimed as ours: {got['ours']}"
    )


# --------------------------------------------------------------------------- #
# What a reader is offered instead
# --------------------------------------------------------------------------- #


_NO_DELETE = """
const row = menuRows()[1];
rightOn(row, 300, 300);
return {open: popIsOpen(), kinds: kindsInTheMenu(), asks: typeof popAsk,
        reads: typeof popCascade, wearing: POP.className,
        panel: !!POP.querySelector('[data-kind="confirm"]')};
"""


def test_a_reader_is_offered_no_delete_and_no_way_to_ask_for_one(index: Index, tmp_path: Path):
    """A signed-out reader is offered nothing that deletes — not a refused
    `Delete…`, not an `Editing is unavailable here`, nothing. The sign-in is in
    the nav and it is the whole of the news; a refused item teaches why a control
    will not act, and "not with these credentials" is the one answer that is
    already on the page.

    **And the machinery is not there either**, which is the half a list of item
    slugs cannot see. `popAsk` and `popCascade` are in `_POP_WRITE_JS`, which
    `_pop_js` emits only when it is given an index — so on a reader's page they
    are not defined at all, and the route they would ask is nowhere in the bytes.

    That last assertion is the one worth keeping when somebody moves a function
    between the halves of that file. `tests/test_table.py` and
    `tests/test_render.py` already sweep a reader's page and every rendered file
    for `/api/record` and `base_commit` as plain substrings, because a rendered
    file is a thing somebody puts on a share; `/api/cascade/` is the third route
    this menu knows and it belongs in exactly the same place. **A comment naming
    it ships in the page's bytes just as surely as the code would** — which has
    already cost this branch two rounds, once in a stylesheet and once in the
    menu's own script.
    """
    reader = measured_in(
        chrome(),
        render_table(index, ROUTES, base_commit=HEAD, may_write=False),
        tmp_path / "nodelete.html",
        1200,
        _OPENING + _NO_DELETE,
    )

    assert reader["open"] is True, "the reader's page opened no menu, so its list is empty"
    assert DELETE_ITEM not in reader["kinds"], (
        f"a signed-out reader is offered `Delete…`: {reader['kinds']}"
    )
    assert reader["kinds"][-3:] == READER_ITEMS, (
        f"the reader's menu ends {reader['kinds'][-3:]} rather than in the three items "
        "that only look"
    )
    assert reader["asks"] == "undefined" and reader["reads"] == "undefined", (
        f"a reader's page carries popAsk={reader['asks']} and popCascade={reader['reads']}: "
        "the confirmation's machinery is in the write half, and a page rendered without "
        "an index has no write half"
    )
    assert reader["panel"] is False and "popasking" not in reader["wearing"], reader

    for name, page in {
        "a signed-out reader's table": render_table(index, ROUTES, base_commit=HEAD),
        "the static export": render_table(index, STATIC),
        "the timeline": render_timeline(index, ROUTES),
    }.items():
        assert "/api/cascade/" not in page, (
            f"{name} carries the cascade route in its bytes — and it carries it whether "
            "the string is code or a comment explaining that this page does not use it"
        )
    for name, page in {
        "a writer's table": a_writers_table(index),
        "a writer's graph": render_graph(index, ROUTES, base_commit=HEAD, may_write=True),
    }.items():
        assert "/api/cascade/" in page, (
            f"{name} cannot ask what a deletion would take with it, so its `Delete…` has "
            "nothing to draw and nothing to compare against"
        )


# --------------------------------------------------------------------------- #
# A second menu, opened while a deletion is still in the air
# --------------------------------------------------------------------------- #


_A_SECOND_MENU_AFTER_A_DELETE = """
if (!DATA.rows[TARGET]) return {error: TARGET + ' is not on this table'};
const otherRow = menuRows().find(tr => tr.dataset.id !== TARGET);
if (!otherRow) return {error: 'the table drew only one row, so there is no second record'};
const second = {id: otherRow.dataset.id, title: DATA.rows[otherRow.dataset.id].title};
const STALE = 'the plan changed while that was open. Nothing was deleted — read it '
  + 'again and decide.';

// The answer HELD, which is the whole of the window this guard is about.
let release = null;
const holding = answer => {
  release = null;
  ANSWER = () => new Promise(done => { release = () => done(answer); });
};
// Dismissed the way a reader dismisses it — a press outside — and then a press
// on a DIFFERENT row. That is the ordinary way to open a second menu and it is
// the order a trusted right press produces: pointerdown, then contextmenu.
const moveToTheOtherRecord = () => {
  document.body.dispatchEvent(
    new PointerEvent('pointerdown', {bubbles: true, clientX: 5, clientY: 5}));
  openOn(second.id);
  return {open: popIsOpen(), about: popAbout(), kinds: popKinds(),
          label: POP.getAttribute('aria-label')};
};
const pressDeleteOn = async id => { askOn(id); await rest(400); reallyIn().click(); };

// --- a refusal, which DRAWS its sentence and takes the keyboard -------------
holding({status: 409, body: {detail: STALE}});
await pressDeleteOn(TARGET);
await rest(150);
if (!release) return {error: 'the first press sent no DELETE, so nothing is in the air'};
const moved = moveToTheOtherRecord();
release();
await rest(800);
const refused = {open: popIsOpen(), about: popAbout(), kinds: popKinds(), up: askUp(),
                 label: POP.getAttribute('aria-label'),
                 focused: document.activeElement.dataset.kind,
                 drawn: popControls().map(wordIn), said: said(),
                 asked: cascades().length};

// --- and a deletion that LANDS, which closes --------------------------------
//
// Read inside the host's own `wrote()`, which is where `popSend` goes
// immediately after the close it is gated on. The `openproj:wrote` in its
// `finally` carries a sha, and every open menu dies on one — this second box
// included, and rightly, because the tbody under it has just been replaced.
let duringWrote = null;
const hostWrote = POP_HOST.wrote;
POP_HOST.wrote = async (answer, id) => {
  duringWrote = {open: popIsOpen(), about: popAbout()};
  return hostWrote(answer, id);
};
popClose();
holding({status: 200, body: {outcome: 'committed', commit: 'c0ffee9', pushed: true}});
await pressDeleteOn(TARGET);
await rest(150);
if (!release) return {error: 'the second press sent no DELETE, so nothing is in the air'};
const movedAgain = moveToTheOtherRecord();
release();
await rest(1000);
return {second, STALE, moved, refused, movedAgain, duringWrote,
        landed: {said: said(), base: baseNow(), open: popIsOpen(), row: !!DATA.rows[TARGET]},
        sent: deletions().map(one => one.url), beats: beatsNow()};
"""


def test_an_answer_to_one_menus_delete_does_not_reach_the_menu_opened_after_it(
    index: Index, tmp_path: Path
):
    """`POP_GEN` again, and the answer that arrives here is about a record that
    may no longer exist.

    A deletion is a commit and a push against a repository on GitHub, so it takes
    seconds, and the box stays up for every one of them. In that window a reader
    can dismiss it and right-click a different record — which is not an exotic
    race but the ordinary way to open a second menu. So both halves are asked, in
    the shape `test_an_answer_to_one_menus_write_does_not_reach_the_menu_opened_
    after_it` established for cut 3's writes, because both fail differently here
    and neither is visible in the other:

    - a REFUSED deletion goes through `popSaid`, and `popSay` draws its sentence
      as the first item of whatever level is up. Into the second record's menu
      that is a sentence about deleting something else, drawn over an item list
      where the last item deletes the record somebody is now looking at.
    - a LANDED one ends in `popDone()`, which would shut that second menu under
      the reader's pointer.

    **And the refusal must not re-ask the cascade**, which is the half that is
    new here. `popReally` re-asks on a refusal because the panel's list is then
    known to be wrong — but only `if (popAsking(asking))`, and this panel is
    gone. Without that guard a dismissed panel would fetch the consequences of a
    deletion nobody is being offered, and draw them into whatever is on screen.

    The live region still carries the refusal either way, because a refusal
    nobody is told about is a write that looks like it worked — and it is also
    what proves the answer arrived at all and that the assertions above it are
    not vacuous.
    """
    target = _whose_delete_reaches(index)
    got = _at_a_panel(
        index,
        tmp_path / "seconddelete.html",
        f"const TARGET = {target!r};\n" + _A_SECOND_MENU_AFTER_A_DELETE,
        patience=6000,
    )

    assert not got.get("error"), got
    assert got["second"]["id"] != target, got

    for which, seen in (("refusal", got["moved"]), ("landed deletion", got["movedAgain"])):
        assert seen["open"] is True, f"no second menu opened during the {which}"
        assert seen["about"] == got["second"]["id"], (
            f"the second menu of the {which} is about {seen['about']} and it was opened "
            f"on {got['second']['id']}"
        )
        assert seen["label"] == f"Actions for {got['second']['title']}", seen

    assert got["refused"]["said"] == got["STALE"], (
        f"the refusal was not announced at all: the live region says "
        f"{got['refused']['said']!r}. A refusal nobody is told about is a deletion that "
        "looks like it worked — and if nothing was said, no answer came back and the "
        "assertions below are about nothing"
    )
    assert got["refused"]["up"] is False, (
        "the first record's confirmation was drawn back over the second record's menu"
    )
    assert "said" not in got["refused"]["kinds"], (
        "the refused deletion's sentence was drawn into the menu of a record it is not "
        f"about: {got['refused']['kinds']}"
    )
    assert got["STALE"] not in got["refused"]["drawn"], got["refused"]["drawn"]
    assert got["refused"]["kinds"] == got["moved"]["kinds"], (
        f"the second menu's items changed under an answer about {target}: "
        f"{got['moved']['kinds']} became {got['refused']['kinds']}"
    )
    assert got["refused"]["focused"] != "said", (
        "the refused deletion took the keyboard inside the second record's menu"
    )
    assert got["refused"]["about"] == got["second"]["id"], got["refused"]
    assert got["refused"]["open"] is True, "the refusal closed the second record's menu"
    assert got["refused"]["asked"] == 1, (
        f"the plan was asked {got['refused']['asked']} times what this deletion would "
        "take with it: the refusal re-asked for a panel that had already been dismissed"
    )

    assert got["duringWrote"] is not None, (
        "the host's `wrote()` never ran, so the landed half of this test never reached "
        "the moment it is written for"
    )
    assert got["duringWrote"]["open"] is True, (
        "a deletion that landed closed the menu somebody had opened on a different record "
        "while it was in the air — `popDone()` is gated on `POP_GEN === mine` for this"
    )
    assert got["duringWrote"]["about"] == got["second"]["id"], got["duringWrote"]
    assert got["landed"]["said"].startswith(f"{_reaches(index)[target]['title']} is deleted"), (
        f"the deletion that landed announced {got['landed']['said']!r}"
    )
    assert got["landed"]["row"] is False, "the record the deletion removed is still in the plan"
    assert got["landed"]["base"] == "c0ffee9", (
        f"`#base` is still {got['landed']['base']} after a commit"
    )
    assert got["landed"]["open"] is False, (
        "the second menu outlived an `openproj:wrote` carrying a sha, so it is pointing at "
        "a row in a tbody that has been replaced since it opened"
    )
    assert got["sent"] == [f"/api/record/{target}"] * 2, (
        f"the presses did not both delete {target}: {got['sent']}"
    )
    # Silent on both beats, for the reason written out above the sibling
    # assertion in `test_two_presses_on_delete_it_with_no_gap_send_one_delete`:
    # a DELETE is invisible to the announce census, so it announces neither.
    # The guarantee the pair used to carry here — that a menu opened on another
    # record dies when this write lands — is asserted three lines up as
    # `landed.open is False`, and it is `popClose` in `popDelete`'s `finally`
    # that keeps it rather than the event.
    assert got["beats"] == {"writing": 0, "wrote": []}, got["beats"]
