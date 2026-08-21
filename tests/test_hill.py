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
import re
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in
from test_injection import run_js

from openproj.index import Index, build_index
from openproj.model import NOTE_STATUS, load_repo
from openproj.render import (
    _HILL_ALONG,
    _HILL_BOX,
    _HILL_GROUND,
    _HILL_OFF_THE_PATH,
    _HILL_STOPS,
    HILL_LADDERS,
    ROUTES,
    STATUSES,
    _hill_at,
    _hill_html,
    _hill_path,
    hill_geometry,
    render_detail,
    render_table,
)

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    entities, config, _ = load_repo(demo_root)
    return build_index(entities, config, date(2026, 8, 17))


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
    assert set(HILL_LADDERS["entity"]) == set(STATUSES)
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


def test_an_entity_cannot_stand_where_only_a_note_can() -> None:
    """And a note cannot stand where only an entity can.

    The stop sets are per record kind, so this is not a rule enforced at the
    moment of a drag — there is no stop there to drag to. `thinking` is a word an
    entity's file could hold after a hand edit, and on a pitch's hill it is as
    unrecognisable as `banana`.
    """
    assert 'value="thinking"' not in str(_hill_html("shaping", live=True))
    assert "hill-ball" not in str(_hill_html("thinking"))
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
    stood = re.search(r'hill-ball hill-promoted"\s*style="left: ([\d.]+)%', drawn)
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
    assert geometry["ladders"]["entity"] == list(HILL_LADDERS["entity"])
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
    entity_id = sorted(index.entities)[0]
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    assert 'data-hill="entity"' in page
    assert 'role="radiogroup"' in page
    assert not re.search(r"<select[^>]*name=\"status\"", page), "the status dropdown is back"


def test_the_read_only_hill_has_no_stops_on_it(index: Index) -> None:
    """A card and a page nobody may write are pictures, not controls.

    The stops exist only inside the group; the read hill carries none, so there is
    nothing to press, nothing to focus, and nothing for a screen reader to offer
    as a choice on a record this reader cannot change.
    """
    entity_id = sorted(index.entities)[0]
    reading = render_detail(index, ROUTES, only=entity_id)
    assert 'data-hill="entity"' in reading
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
    entity_id = next(i for i, e in sorted(index.entities.items()) if e.status == "in_progress")
    page = render_table(index, ROUTES)
    answer = run_js(page, f"cardHtml(DATA.rows[{json.dumps(entity_id)}], [])")
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
    entity_id = sorted(index.entities)[0]
    page = render_table(index, ROUTES)
    answer = run_js(
        page,
        "cardHtml(Object.assign({}, DATA.rows["
        f"{json.dumps(entity_id)}], {{status: 'banana'}}), [])",
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
    """Painted at all, and painted in the right place.

    One page per status the corpus holds, and each one is a record's own page as
    the server sends it. Not the static export, which was tried first and is the
    wrong instrument: it puts every entity in one file and shows one at a time, so
    every article but the current one is `display: none` and every ball in it
    measures zero — a page that would have reported "the hill is painted at no
    size" for a hill that is perfectly fine.

    A resolved `left` is not the claim either. Chrome painted nothing at all for
    the frozen column's edge on a value every test agreed with. So this measures
    the box the browser actually laid out and checks its centre against what
    `_hill_at` computed, in the hill's own pixels.
    """
    browser = chrome()
    first = {}
    for entity_id, entity in sorted(index.entities.items()):
        first.setdefault(entity.status, entity_id)
    assert len(first) > 1, "the corpus holds one status, so this proves nothing"

    for status, entity_id in first.items():
        page = render_detail(index, ROUTES, only=entity_id)
        found = measured_in(
            browser, page, tmp_path / f"{status}.html", 1100,
            """
            const hill = document.querySelector('.hill');
            const ball = hill.querySelector('.hill-ball');
            const box = hill.getBoundingClientRect();
            const at = ball.getBoundingClientRect();
            return {width: at.width, height: at.height,
                    across: (at.x + at.width / 2 - box.x) / box.width,
                    down: (at.y + at.height / 2 - box.y) / box.height,
                    word: [...ball.classList].find(c => c !== 'hill-ball').slice(5)};
            """,
            height=1000,
        )
        assert found["word"] == status
        assert found["width"] > 0 and found["height"] > 0, f"{status}'s ball is laid out at no size"
        x, y = _HILL_STOPS[status]
        assert found["across"] == pytest.approx(x / _HILL_BOX[0], abs=0.01), f"{status} across"
        assert found["down"] == pytest.approx(y / _HILL_BOX[1], abs=0.01), f"{status} up"


def test_pressing_a_stop_moves_the_ball_and_the_form(index: Index, tmp_path: Path) -> None:
    """The radios are the control; everything else follows them.

    What is asserted is the whole chain in one go: the stop takes the press, the
    ball moves, the hidden input the form serialises holds the new word, and the
    commit bar counts one unsaved change. Any link of that broken is a hill that
    looks like it works.
    """
    browser = chrome()
    entity_id = next(i for i, e in sorted(index.entities.items()) if e.status != "ready")
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        document.getElementById('toggle').click();
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
    entity_id = next(i for i, e in sorted(index.entities.items()) if e.status != "done")
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        document.getElementById('toggle').click();
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
    entity_id = next(i for i, e in sorted(index.entities.items()) if e.status != "done")
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        document.getElementById('toggle').click();
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
    entity_id = sorted(index.entities)[0]
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        document.getElementById('toggle').click();
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
    assert found["count"] == len(HILL_LADDERS["entity"])
    assert found["value"] == HILL_LADDERS["entity"][1]
