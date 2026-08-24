"""One ball, on one hill, standing for a status.

Shape Up draws a piece of work as a ball on a hill: uphill is figuring out what
to do, the summit is knowing, downhill is doing it. `status` already carries that
distinction, and a chip cannot say it — `shaping` and `in_progress` are one rung
apart in a list and opposite sides of a hill in the book.

Two things are worth testing here and they are not the same thing. One is the
arithmetic: the curve and the stops come out of one function, and a stop that
does not land on the line it is drawn on is the whole feature broken in the one
way a reader will notice immediately. The other is the pixels — a resolved `left`
is a promise about paint that this repository has already watched a stylesheet
fail to keep.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from functools import cache
from pathlib import Path

import pytest
from browser import chrome, measured_in
from test_injection import run_js

from openproj.index import Index, build_index
from openproj.model import (
    ISSUE_STATUS,
    KINDS,
    NOTE_STATUS,
    RUNG,
    STATUS_ORDER,
    Config,
    Issue,
    Pitch,
    Task,
    load_repo,
)
from openproj.render import (
    _HILL_ALONG,
    _HILL_BOX,
    _HILL_GROUND,
    _HILL_NORMALS,
    _HILL_OFF_THE_PATH,
    _HILL_STOPS,
    _LADDER_OF,
    _STATE_HINT,
    EDITABLE,
    HILL_LADDERS,
    LABELS,
    ROUTES,
    STATUSES,
    SUGGESTS,
    _control_html,
    _editable_for,
    _fact_rows,
    _hill_at,
    _hill_html,
    _hill_path,
    _human,
    hill_geometry,
    render_detail,
    render_table,
)

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def test_every_hill_stop_is_on_the_line() -> None:
    """The one invariant the drawing has.

    Not "close enough": the path is sampled at multiples of 1/48 and every stop
    on the curve is at a quarter, so each stop's coordinates are literally two of
    the numbers in the `d` attribute. A ball floating a few pixels off the line
    it is meant to be on is the first thing anybody would see and the last thing
    a resolved-value test would catch, which is why this asks the path itself.
    """
    path = _hill_path()
    for word, along in _HILL_ALONG.items():
        x, y = _hill_at(along)
        assert (x, y) == _HILL_STOPS[word], f"{word} is not where the curve puts it"
        assert f"{x:g} {y:g}" in path, f"{word} at ({x}, {y}) is not a point on the path"


def test_halfway_up_is_halfway_up() -> None:
    """Why it is a raised cosine and not any other curve through three points.

    `shaping` and `in_progress` are drawn at a quarter and three quarters along,
    and the claim the picture makes about them is *halfway* — up and down. This
    is that claim, as arithmetic: the curve passes through the midpoint between
    the ground and the summit at exactly those two places. Any curve that fails
    this is a curve where the two words no longer mean what the drawing says.
    """
    summit = _hill_at(0.5)[1]
    middle = (_HILL_GROUND + summit) / 2
    assert _hill_at(0.25)[1] == middle
    assert _hill_at(0.75)[1] == middle


def test_every_status_a_record_can_hold_has_a_stop() -> None:
    """Read off the vocabularies rather than restated beside them.

    A word added to `STATUSES` or `NOTE_STATUS` tomorrow fails here rather than
    quietly having nowhere to stand — which on a hill is not a missing row, it is
    a record with no ball at all and no way to tell that from a bug.
    """
    for word in (*STATUSES, *NOTE_STATUS):
        assert word in _HILL_STOPS, f"{word} is a status a file may hold and has no stop"
    assert set(HILL_LADDERS["record"]) == set(STATUSES)
    assert set(HILL_LADDERS["note"]) == set(NOTE_STATUS)


def test_the_two_that_came_off_the_path_stand_under_the_summit() -> None:
    """`shelved` and `dropped` are on the ground, halfway along.

    Not past the finish, which is where they would naturally go and where they
    would read as "after done" — the one thing shelved is not. Under the summit
    is "never got over it", which is what happened.
    """
    summit_x = _HILL_STOPS["ready"][0]
    for word in _HILL_OFF_THE_PATH:
        assert _HILL_STOPS[word] == (summit_x, _HILL_GROUND), f"{word} is not under the summit"


def test_nothing_is_drawn_below_the_ground() -> None:
    """The hill costs its own height and no more.

    It sits in a facts column beside fifteen other rows and above a shaping
    document; a picture that hangs a ball below the line it stands on is a row
    twice as tall as it needs to be for one word.
    """
    for word, (_, y) in _HILL_STOPS.items():
        assert y <= _HILL_GROUND, f"{word} hangs below the ground line"
    assert max(y for _, y in _HILL_STOPS.values()) == _HILL_GROUND


def test_an_unknown_status_gets_no_ball_and_says_its_word() -> None:
    """`status` is permissive, so a hand-edited file reaches here holding anything.

    The chip's answer for those is `_status_class`'s `st-ready`, which is right
    for a chip — the word beside it says what it really is — and wrong for a ball,
    because it would park an unrecognised status on the summit and say something
    false. No ball, a quiet hill, and the word as written.
    """
    drawn = str(_hill_html("banana"))
    assert "hill-ball" not in drawn
    assert "hill-off" in drawn
    assert "banana" in drawn, "the page must still say what the file holds"


def test_a_record_cannot_stand_where_only_a_note_can() -> None:
    """And a note cannot stand where only a record can.

    The stop sets are per record kind, so this is not a rule enforced at the
    moment of a drag — there is no stop there to drag to. `dropped` is a word a
    record's file could hold after a hand edit, and on a pitch's hill it is as
    unrecognisable as `banana`.

    The word here used to be `thinking`, which stopped being note-only on
    2026-08-24 — jcanton asked for it on every kind but an issue, so a record can
    now stand at the foot of the hill and a pitch's ladder offers it. `dropped`
    is what is left that only a note can hold, and it is the same question.
    """
    assert 'value="dropped"' not in str(_hill_html("shaping", live=True))
    assert "hill-ball" not in str(_hill_html("dropped"))
    for word in ("ready", "in_progress", "done"):
        assert f'value="{word}"' not in str(_hill_html("thinking", "note", live=True))


def test_a_promoted_note_stands_where_the_record_it_became_does() -> None:
    """Derived, undraggable, and not nowhere.

    `promoted` comes from `became` and no press can set it, so it has no stop. Left
    at that it drew a hill with no ball on it — empty looking exactly like broken.
    It stands at `shaping` because that is where `promote` creates the record it
    became, hollow because the note is not the thing standing there, and on a hill
    that is not dimmed because that ball is on its way up.
    """
    drawn = str(_hill_html("promoted", "note"))
    assert "hill-ball hill-promoted" in drawn
    assert "hill-off" not in drawn
    stood = re.search(r'hill-ball hill-promoted".*?style="left: ([\d.]+)%', drawn, re.S)
    assert stood, "the promoted ball carries no position"
    assert float(stood.group(1)) == pytest.approx(100 * _HILL_STOPS["shaping"][0] / _HILL_BOX[0])


def test_the_browser_is_handed_the_numbers_the_page_was_drawn_with() -> None:
    """One geometry, two renderers.

    The detail page's hill is built in Jinja and the card's in JavaScript. This
    payload is what stops them disagreeing about where `ready` is — the mistake
    this codebase paid for once already, when `appetite_weeks` read as three
    different numbers on three pages.
    """
    geometry = hill_geometry()
    assert geometry["path"] == _hill_path()
    assert geometry["stops"] == {word: list(at) for word, at in _HILL_STOPS.items()}
    assert geometry["ladders"]["record"] == list(HILL_LADDERS["record"])
    # The sentence each coordinate draws travels with the coordinates, because
    # position is the one channel a screen reader never gets.
    for word in _HILL_STOPS:
        assert geometry["where"][word]


def test_the_status_row_is_a_hill_and_the_dropdown_is_gone(index: Index) -> None:
    """In place of the chip and the select, not beside them.

    `render.py`'s detail template already records what the same word in the same
    colour twice costs. A dropdown under a hill that sets the same field would be
    that note again with one more control in it.
    """
    record_id = sorted(index.plan)[0]
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    assert 'data-hill="record"' in page
    assert 'role="radiogroup"' in page
    assert not re.search(r"<select[^>]*name=\"status\"", page), "the status dropdown is back"


def test_the_read_only_hill_has_no_stops_on_it(index: Index) -> None:
    """A card and a page nobody may write are pictures, not controls.

    The stops exist only inside the group; the read hill carries none, so there is
    nothing to press, nothing to focus, and nothing for a screen reader to offer
    as a choice on a record this reader cannot change.
    """
    record_id = sorted(index.plan)[0]
    reading = render_detail(index, ROUTES, only=record_id)
    assert 'data-hill="record"' in reading
    assert 'role="radiogroup"' not in reading
    # Asked of the facts list and not of the file: the shell's stylesheet writes
    # `input:not([type="checkbox"]):not([type="radio"])`, and a substring search
    # over the whole page finds a selector and calls it a control.
    facts = re.search(r'<dl id="facts">(.*?)</dl>', reading, re.S).group(1)
    assert "<input" not in facts, "a page nobody may write is drawing controls"


def test_the_card_draws_the_hill_and_keeps_the_word(index: Index) -> None:
    """The card has no labels on its chip line, so the picture keeps its word.

    The detail page drops the chip because a `<dt>` beside the hill says STATUS.
    Here there is nothing to say it, and a shape with no name is a shape half the
    readers of this card will not spend a second working out.
    """
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status == "in_progress")
    page = render_table(index, ROUTES)
    answer = run_js(page, f"cardHtml(DATA.rows[{json.dumps(record_id)}], [])")
    drawn = str(answer["value"])
    assert "card-hill" in drawn
    assert "hill-ball hill-in_progress" in drawn
    assert "chip st-in_progress" in drawn, "the word goes with the shape on a card"
    assert "halfway down the hill" in drawn


def test_a_word_the_card_does_not_know_gets_no_ball_either(index: Index) -> None:
    """The same answer as the server's, and for the same reason.

    It is also what makes the class safe to build at all: the word only ever
    reaches `hill-${status}` after the ladder has been asked whether it is one of
    its own, and `status` is a field that holds whatever a file holds.
    """
    record_id = sorted(index.plan)[0]
    page = render_table(index, ROUTES)
    answer = run_js(
        page,
        "cardHtml(Object.assign({}, DATA.rows["
        f"{json.dumps(record_id)}], {{status: 'banana'}}), [])",
    )
    drawn = str(answer["value"])
    assert "hill-ball" not in drawn
    assert "hill-off" in drawn


# --- and now the pixels ------------------------------------------------------


def test_no_two_stops_on_one_hill_share_a_place() -> None:
    """Every word a given record can stand on is somewhere of its own.

    Per ladder and not across both, because `shelved` and `dropped` ARE one place:
    they are the same sentence in two vocabularies, and no hill ever offers them
    both. `ready` and `shelved` share an x — the summit and the ground directly
    under it — so this asks about points rather than columns. Two stops at one
    point is two statuses a reader cannot tell apart, which is the picture failing
    silently.
    """
    for kind, words in HILL_LADDERS.items():
        places = [_HILL_STOPS[word] for word in words]
        assert len(set(places)) == len(places), f"two stops share a place on a {kind}'s hill"


def test_the_ball_is_painted_where_the_geometry_says(index: Index, tmp_path: Path) -> None:
    """Painted at all, and painted where the stop plus the lift puts it.

    Its centre is deliberately NOT on the curve — a ball centred on a point of the
    line is half buried in it — so the place to check is the stop displaced along
    the outward normal by the ball's own radius plus half the line. Everything
    here comes back in painted pixels and the arithmetic is done in Python, where
    it can be read.

    One page per status the corpus holds, each a record's own page as the server
    sends it. Not the static export, which was tried first and is the wrong
    instrument: it puts every record in one file and shows one at a time, so every
    article but the current one is `display: none` and every ball in it measures
    zero.
    """
    browser = chrome()
    first: dict[str, str] = {}
    for record_id, record in sorted(index.plan.items()):
        # Only a kind that HAS a ladder. A product's rung declares `statuses=()`
        # — jcanton, 2026-08-20, "a codebase is not `in_progress`" — so its page
        # draws no hill at all and `querySelector('.hill-ball')` finds nothing to
        # measure. It still carries `Record.status`, which is how it turned up
        # here: when `thinking` reached every kind but an issue on 2026-08-24 it
        # became the model default, no PLANNED record in the corpus held it, and
        # the representative for that word fell to a product with no hill on it.
        if not RUNG[record.kind].statuses:
            continue
        first.setdefault(record.status, record_id)
    assert len(first) > 1, "the corpus holds one status, so this proves nothing"

    for status, record_id in first.items():
        page = render_detail(index, ROUTES, only=record_id)
        found = measured_in(
            browser, page, tmp_path / f"{status}.html", 1100,
            """
            const hill = document.querySelector('.hill');
            const ball = hill.querySelector('.hill-ball');
            const svg = hill.querySelector('svg').getBoundingClientRect();
            const at = ball.getBoundingClientRect();
            return {frame: {x: svg.x, y: svg.y, width: svg.width},
                    size: at.width,
                    cx: at.x + at.width / 2, cy: at.y + at.height / 2,
                    word: [...ball.classList].find(c => c !== 'hill-ball').slice(5)};
            """,
            height=1000,
        )
        assert found["word"] == status
        assert found["size"] > 0, f"{status}'s ball is laid out at no size"

        scale = found["frame"]["width"] / _HILL_BOX[0]
        x, y = _HILL_STOPS[status]
        nx, ny = _HILL_NORMALS[status]
        # `box-sizing: border-box`, so the laid-out width IS the outer diameter;
        # plus one for half of a 2px non-scaling stroke.
        lift = found["size"] / 2 + 1
        assert found["cx"] == pytest.approx(
            found["frame"]["x"] + x * scale + nx * lift, abs=1.5
        ), f"{status} is across wrong"
        assert found["cy"] == pytest.approx(
            found["frame"]["y"] + y * scale + ny * lift, abs=1.5
        ), f"{status} is up wrong"


def test_pressing_a_stop_moves_the_ball_and_the_form(index: Index, tmp_path: Path) -> None:
    """The radios are the control; everything else follows them.

    What is asserted is the whole chain in one go: the stop takes the press, the
    ball moves, the hidden input the form serialises holds the new word, and the
    commit bar counts one unsaved change. Any link of that broken is a hill that
    looks like it works.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status != "ready")
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        flipEditing();
        // A timer and not `requestAnimationFrame`: this runs under Chrome's
        // virtual clock, which drives timers and does not necessarily drive
        // frames — an `await` on a frame never resolves there, the report is
        // never written, and the harness says the page reported nothing.
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const ball = hill.querySelector('.hill-ball');
        const before = ball.style.left;
        [...hill.querySelectorAll('.hill-stop')]
          .find(s => s.querySelector('input').value === 'ready').click();
        return {
          before,
          after: ball.style.left,
          value: value.value,
          word: value.dataset.word,
          unsaved: document.getElementById('unsaved').textContent,
          checked: hill.querySelector('input:checked').value,
        };
        """,
        height=1400, patience=2500,
    )
    assert found["value"] == "ready"
    assert found["checked"] == "ready"
    # The words on the page and not the words in the file: the create form's
    # refusal prints this, and `in_progress` sends somebody looking for a field
    # with that label.
    assert found["word"] == "Ready"
    assert found["after"] != found["before"], "the ball did not move"
    assert found["unsaved"] == "1 unsaved change"


def test_dragging_the_ball_lands_on_a_stop(index: Index, tmp_path: Path) -> None:
    """And nothing is committed until it is let go.

    A drag is an enhancement over the radios, and it lands only on stops because
    there is nothing between them for a ball to mean. The mid-drag assertion is
    the half that matters: the ball previews, the form does not move, and a
    gesture abandoned halfway has changed nothing.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status != "done")
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        flipEditing();
        // A timer and not `requestAnimationFrame`: this runs under Chrome's
        // virtual clock, which drives timers and does not necessarily drive
        // frames — an `await` on a frame never resolves there, the report is
        // never written, and the harness says the page reported nothing.
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const ball = hill.querySelector('.hill-ball');
        const box = hill.getBoundingClientRect();
        hill.setPointerCapture = () => {};
        const send = (type, fx, fy) => hill.dispatchEvent(new PointerEvent(type, {
          bubbles: true, button: 0, pointerId: 1,
          clientX: box.left + box.width * fx, clientY: box.top + box.height * fy}));
        send('pointerdown', 0.5, 0.2);
        send('pointermove', 0.9, 0.85);
        const midway = {ball: ball.style.left, value: value.value};
        send('pointerup', 0.9, 0.85);
        return {
          midway,
          value: value.value,
          ball: ball.style.left,
          unsaved: document.getElementById('unsaved').textContent,
        };
        """,
        height=1400, patience=2500,
    )
    assert found["value"] == "done"
    assert found["unsaved"] == "1 unsaved change"
    # Previewed, not committed: the ball had already moved while the form had not.
    assert found["midway"]["ball"] == found["ball"]
    assert found["midway"]["value"] != "done"


def test_a_cancelled_drag_puts_the_ball_back(index: Index, tmp_path: Path) -> None:
    """Where it was, and not wherever the pointer happened to die.

    A gesture that never finished is not a status change, and leaving the ball at
    the last place it was previewed is a page that disagrees with the field it is
    drawing.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status != "done")
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        flipEditing();
        // A timer and not `requestAnimationFrame`: this runs under Chrome's
        // virtual clock, which drives timers and does not necessarily drive
        // frames — an `await` on a frame never resolves there, the report is
        // never written, and the harness says the page reported nothing.
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const ball = hill.querySelector('.hill-ball');
        const box = hill.getBoundingClientRect();
        hill.setPointerCapture = () => {};
        const before = ball.style.left;
        const send = (type, fx, fy) => hill.dispatchEvent(new PointerEvent(type, {
          bubbles: true, button: 0, pointerId: 1,
          clientX: box.left + box.width * fx, clientY: box.top + box.height * fy}));
        send('pointerdown', 0.5, 0.2);
        send('pointermove', 0.9, 0.85);
        send('pointercancel', 0.9, 0.85);
        return {before, after: ball.style.left, value: value.value,
                unsaved: document.getElementById('unsaved').textContent};
        """,
        height=1400, patience=2500,
    )
    assert found["after"] == found["before"], "the ball stayed where the drag died"
    assert found["unsaved"] == "Nothing changed yet"


def test_the_hill_takes_a_keyboard(index: Index, tmp_path: Path) -> None:
    """Because it is five real radios and not a div with an opinion.

    Arrow keys, the group, the focus ring and "3 of 5" are all the platform's
    here. What this asks is that the browser really is treating them as one group
    — that the stops are focusable, and that moving between them moves the field
    the form will send.
    """
    browser = chrome()
    record_id = sorted(index.plan)[0]
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        flipEditing();
        // A timer and not `requestAnimationFrame`: this runs under Chrome's
        // virtual clock, which drives timers and does not necessarily drive
        // frames — an `await` on a frame never resolves there, the report is
        // never written, and the harness says the page reported nothing.
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const stops = [...hill.querySelectorAll('input')];
        stops[0].focus();
        const focused = document.activeElement === stops[0];
        // What an arrow key does to a radio group, done the way the group does it:
        // check the next one and let it announce. The key event itself is the
        // browser's own and cannot be synthesised into it from here.
        stops[1].checked = true;
        stops[1].dispatchEvent(new Event('change', {bubbles: true}));
        return {focused, names: new Set(stops.map(s => s.name)).size,
                value: value.value, count: stops.length};
        """,
        height=1400, patience=2500,
    )
    assert found["focused"], "a stop cannot be focused, so the hill has no keyboard"
    assert found["names"] == 1, "the stops are not one group, so arrows will not move between them"
    assert found["count"] == len(HILL_LADDERS["record"])
    assert found["value"] == HILL_LADDERS["record"][1]


def test_every_stop_knows_which_way_is_up() -> None:
    """The ball rests ON the line, and this is the direction it is lifted along.

    A unit vector, because the lift is a length in painted pixels: the ball is an
    HTML element sized in px — so that it can carry a real radio — and the drawing
    is a viewBox that scales with the column it sits in. Anything but a unit
    vector and the lift is a different distance at every angle.

    Pointing up, which in SVG's axes is a negative `y`. A stop whose normal points
    into the hill is a ball buried in it.
    """
    for word, (nx, ny) in _HILL_NORMALS.items():
        assert math.hypot(nx, ny) == pytest.approx(1, abs=0.001), f"{word}'s normal is not a unit"
        assert ny < 0, f"{word} is lifted into the hill rather than out of it"
    # The two ends and the two that came off the path are on level ground, and
    # level ground's normal is straight up.
    for word in ("thinking", "done", *_HILL_OFF_THE_PATH):
        assert _HILL_NORMALS[word] == (0.0, -1.0) or _HILL_NORMALS[word] == (-0.0, -1.0)
    # And the two slopes lean opposite ways, which is the whole shape of the thing.
    assert _HILL_NORMALS["shaping"][0] < 0 < _HILL_NORMALS["in_progress"][0]


def test_the_hill_can_say_the_word_without_printing_it() -> None:
    """A position means nothing to somebody who has not been told what it means.

    jcanton, 2026-08-22: "people are forced to know what the positions mean". So
    every stop and the ball carry the word, and the stylesheet shows it on hover,
    on focus and while a drag is in flight. Not printed permanently: the argument
    for replacing the chip was that the drawing says something the word cannot,
    and a word standing beside it always is the chip back with extra steps.
    """
    live = str(_hill_html("shaping", live=True))
    for word in HILL_LADDERS["record"]:
        assert f'data-word="{_human(word)}"' in live, word
    assert 'class="hill-ball hill-shaping" data-word="Shaping"' in live
    # And it is the app's own status chip rather than a tooltip that happens to
    # say the same word: the colours come from the same tokens `.chip.st-X` uses.
    assert ".hill-ball.hill-shaping::after" in _rendered_shell()
    assert "--st-shaping-soft" in _rendered_shell()


@cache
def _rendered_shell() -> str:
    """Any page, for a question about the one stylesheet every page carries."""
    records, config, _ = load_repo(Path(__file__).resolve().parents[1] / "seed")
    index = build_index(records, config, date(2026, 8, 17))
    return render_detail(index, ROUTES, only=sorted(index.plan)[0])


def test_the_ball_follows_the_field_when_something_else_sets_it(
    index: Index, tmp_path: Path
) -> None:
    """The other direction, which nothing exercises yet and something is about to.

    The hill writes the status and the status is written back into the hill. Today
    nothing but the hill sets that field; Cancel is about to, once it puts back
    what the server rendered — it assigns `ORIGINAL` into every control, and a
    value assigned by script fires no event a picture could hear. The sync hangs
    off the session ending rather than off Cancel, because that is the fact it
    cares about and a session has four doors out of it.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status != "ready")
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "sync.html", 1100,
        """
        flipEditing();
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const ball = hill.querySelector('.hill-ball');
        [...hill.querySelectorAll('.hill-stop')]
          .find(s => s.querySelector('input').value === 'ready').click();
        const moved = ball.style.left;
        // What a restore looks like: the field is put back and nothing is fired.
        value.value = 'shaping';
        dispatchEvent(new CustomEvent('openproj:session', {detail: false}));
        await new Promise(settled => setTimeout(settled, 20));
        return {moved, after: ball.style.left, klass: ball.className,
                checked: hill.querySelector('input:checked').value};
        """,
        height=1400, patience=2500,
    )
    assert found["checked"] == "shaping", "the stop the field names is not the one checked"
    assert found["klass"] == "hill-ball hill-shaping"
    assert found["after"] != found["moved"], "the ball stayed where the hill had put it"


def test_cancelling_an_edit_rolls_the_ball_back(index: Index, tmp_path: Path) -> None:
    """The seam between the hill and Cancel, which only exists once both are here.

    Cancel puts every field back to what the server rendered, and it does that by
    assigning into the control — which fires no event a picture could hear. The
    hill listens for the session ending instead. What this asks is the ORDER those
    two happen in: `showEditing` is what dispatches the end of a session, so the
    fields have to be back before it is called. Ended first, Cancel put
    `in_progress` back into the field and left the ball sitting on `ready`, with
    the picture and the value disagreeing on a page nobody was editing — and both
    branches passed on their own.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.plan.items()) if e.status != "ready")
    was = index.plan[record_id].status
    page = render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "cancel.html", 1100,
        """
        flipEditing();
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const value = document.querySelector('input[name=status]');
        const ball = hill.querySelector('.hill-ball');
        const before = ball.style.left;
        [...hill.querySelectorAll('.hill-stop')]
          .find(s => s.querySelector('input').value === 'ready').click();
        const moved = ball.style.left;
        document.getElementById('cancel').click();
        await new Promise(settled => setTimeout(settled, 50));
        return {before, moved, after: ball.style.left, klass: ball.className,
                status: value.value,
                checked: hill.querySelector('input:checked').value,
                unsaved: document.getElementById('unsaved').textContent};
        """,
        height=1400, patience=3000,
    )
    assert found["moved"] != found["before"], "the ball never moved, so nothing was cancelled"
    assert found["status"] == was, "the field was not put back"
    # All four say the same thing, which is the whole point: the value the form
    # will send, the stop the keyboard is on, the ball, and its colour.
    assert found["after"] == found["before"], "the ball stayed where the cancelled edit put it"
    assert found["checked"] == was, "the stop the keyboard is on is not the one the field holds"
    assert found["klass"] == f"hill-ball hill-{was}"
    assert found["unsaved"] == "Nothing to save"


# ---------------------------------------------------------------------------
# The control takes its ladder, its lock and its hint from the record.
#
# Half of these run today and half are armed. Until the flip commit no kind's
# `state()` disagrees with its `status` — `Record.state` answers `status`, and
# `Issue` and `Note` are not records yet — so the lock is exercised through a
# subclass that derives its state, which is also all an Issue will be. The one
# test that needs a real issue on a real index is skipif-armed on the rung and
# starts running, unedited, the moment the flip lands.
# ---------------------------------------------------------------------------


class Handed(Task):
    """A record whose state comes from somewhere else, before any such kind exists.

    Stands in for `Issue` and `Note`: a stored `ready` and a derived `done`, the
    exact disagreement the lock exists for.
    """

    def state(self, records: dict) -> str:
        return "done"


def test_the_status_ladder_is_the_validator_s_and_not_a_hand_copy() -> None:
    """`STATUSES` was the five words typed out a second time, in the file whose
    own comments record what hand copies of a ladder cost. Aliased, not retyped:
    a word added to `STATUS_ORDER` reaches every chip rule, select and hill here
    without anybody remembering this line exists."""
    assert STATUSES is STATUS_ORDER


def test_every_issue_word_stands_on_the_hill() -> None:
    """All four of `ISSUE_STATUS` already have stops — `ready` at the summit,
    `in_progress` halfway down, `done` at the bottom, `shelved` on the ground
    under the summit — so an issue's record page gets the hill and the last of
    #67's asymmetry goes with it. Derived from the vocabulary, like the other two
    ladders, so a word added to `ISSUE_STATUS` fails here rather than quietly
    having nowhere to stand."""
    assert HILL_LADDERS["issue"] == tuple(ISSUE_STATUS)
    for word in ISSUE_STATUS:
        assert word in _HILL_STOPS, f"{word} is an issue status with nowhere to stand"
    # And the browser is handed it, so a card can draw an issue the day one exists.
    assert hill_geometry()["ladders"]["issue"] == list(ISSUE_STATUS)


def test_the_lock_hint_keeps_the_two_pages_own_words() -> None:
    """Copy carried verbatim from the issue and note pages it replaced. A changed
    word here is a changed sentence on a page somebody already learned to read."""
    assert _STATE_HINT == {
        "issue": "from the work it was pitched into",
        "note": "from what it became",
    }
    assert _LADDER_OF == {"issue": "issue", "note": "note"}


def test_a_derived_state_locks_the_control_in_the_dom_not_in_paint() -> None:
    """Genuinely disabled: the hidden input carries `disabled`, the hill has no
    radios to press and says so as `role="img"`, and the picture shows the
    derived word — the same ball the read view shows, so pressing Edit moves
    nothing."""
    held = Handed(
        id="task-000001", kind="task", title="Waits on something else",
        status="ready", owner="ann",
    )
    index = build_index([held], Config(), date(2026, 8, 17))
    row = next(r for r in _fact_rows(index, held, ROUTES) if r["label"] == "Status")

    assert "hill-ball hill-done" in str(row["display"]), "the page reads the stored word"
    control = str(row["control"])
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', control)
    assert 'role="radiogroup"' not in control, "a locked hill is offering stops to press"
    assert 'role="img"' in control
    assert "hill-ball hill-done" in control, "Edit moves the ball, which the row promises not to"


def test_the_locked_control_carries_its_explanation_for_a_screen_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not just a visual grey: the why-sentence is a real element in the row,
    and the control points at it with `aria-describedby`. The sentence is
    patched in because no planned kind has one — the two kinds that do arrive
    in the flip commit, and the armed test below takes over then.

    A planned kind is also the one record that can carry BOTH sentences at once:
    it is on the `record` ladder, so its status word has teaching copy, and this
    patch gives it a lock as well. That is why the describedby is read as a token
    list here. See `test_a_record_that_locks_and_teaches_points_at_both` in
    `test_teaching.py`, which asks the same row the other question."""
    import openproj.render as render

    monkeypatch.setitem(render._STATE_HINT, "task", "from what it waits on")
    held = Handed(
        id="task-000001", kind="task", title="Handed on", status="ready", owner="ann",
    )
    index = build_index([held], Config(), date(2026, 8, 17))
    page = render_detail(index, ROUTES, only="task-000001", base_commit=HEAD, may_write=True)

    assert '<span class="hint" id="hint-task-000001-status">from what it waits on</span>' in page
    # Among the ids, not the whole attribute. `aria-describedby` is a
    # space-separated token list, and a planned kind that derives its state is
    # exactly the record that carries a SECOND sentence beside this one — the
    # teaching copy for its status word. This assert read the attribute as a
    # single id and failed the day that second sentence arrived, on markup that
    # was correct. What the lock promises is that its id is in there.
    described = re.search(r'aria-describedby="([^"]*)"', page)
    assert described and "hint-task-000001-status" in described.group(1).split()
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', page)
    assert 'role="radiogroup"' not in page


def test_a_text_control_can_carry_a_placeholder_and_refuse_the_pen() -> None:
    """The two field-dict keys `_CONTROL` gained. `placeholder` is how
    `reported_by` and `written_by` will say who the server stamps; `disabled`
    is the generic lock for any boxed control."""
    field = {
        "name": "reported_by", "id": "x-reported_by", "type": "text", "value": None,
        "gates": (), "list": "people", "text": "", "placeholder": "ann",
    }
    drawn = str(_control_html(field))
    assert 'placeholder="ann"' in drawn
    assert " disabled" not in drawn
    assert re.search(r"<input[^>]* disabled", str(_control_html({**field, "disabled": True})))


def test_what_a_person_owns_on_an_issue_or_a_note_and_what_the_server_stamps() -> None:
    """The four new editable fields, with their suggestion lists and their
    reader's names — and the two creation stamps deliberately absent, because a
    date the server set is not a thing a form may offer a box for."""
    assert EDITABLE["reported_by"] == "text"
    assert EDITABLE["written_by"] == "text"
    assert EDITABLE["pitched_into"] == "list"
    assert EDITABLE["became"] == "list"
    assert "opened_on" not in EDITABLE
    assert "written_on" not in EDITABLE
    assert SUGGESTS["reported_by"] == "people"
    assert SUGGESTS["written_by"] == "people"
    assert SUGGESTS["pitched_into"] == "records"
    assert SUGGESTS["became"] == "records"
    for name in (
        "reported_by", "written_by", "pitched_into", "became", "opened_on", "written_on",
    ):
        assert name in LABELS, f"{name} would reach a reader as an identifier"


def test_no_plan_kind_is_offered_an_issue_s_or_a_note_s_fields() -> None:
    """The new `EDITABLE` entries are inert on every planned kind, today and
    forever: the intersection with `model_fields` is what keeps a pitch from
    being offered a `reported_by` box its validator would then refuse."""
    for rung in KINDS:
        if not rung.planned:
            continue
        blank = rung.model(id=f"{rung.prefix}-000000", kind=rung.name, title="")
        offered = {field["name"] for field in _editable_for(blank)}
        assert not offered & {"reported_by", "written_by", "pitched_into", "became"}, (
            f"{rung.name} is offered a box its validator will refuse"
        )


@pytest.mark.skipif(
    "issue" not in RUNG,
    reason="arms in the flip commit, when the issue rung and the Issue record land",
)
def test_an_issue_whose_pitch_is_done_reads_done_with_a_locked_hill_and_the_hint() -> None:
    """Spec test 9. The stored word is `ready`; the pitch it was pitched into is
    `done`; the page must read the derived state on a hill with no stops, say
    why in the page's own copy, and stamp the signed-in login as the
    `reported_by` placeholder."""
    pitch = Pitch(
        id="pitch-000001", kind="pitch", title="The fix", status="done",
        owner="ann", person_weeks=1.0,
    )
    noticed = Issue(
        id="issue-000001", kind="issue", title="Something broke",
        status="ready", pitched_into=["pitch-000001"],
    )
    index = build_index([pitch, noticed], Config(), date(2026, 8, 17))
    rows = _fact_rows(index, noticed, ROUTES, signed_in="ann")

    status = next(r for r in rows if r["label"] == "Status")
    assert "hill-ball hill-done" in str(status["display"]), "the page reads the stored word"
    control = str(status["control"])
    assert 'data-hill="issue"' in control
    assert 'role="radiogroup"' not in control
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', control)
    assert status["hint"] == "from the work it was pitched into"
    assert status["hint_id"] == "hint-issue-000001-status"
    assert f'aria-describedby="{status["hint_id"]}"' in control

    reported = next(r for r in rows if r["label"] == "Reported by")
    assert 'placeholder="ann"' in str(reported["control"])
    opened = next(r for r in rows if r["label"] == "Opened on")
    assert opened["derived"] and opened["control"] == ""
