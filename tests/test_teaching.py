"""The sentences that say what a Shape Up word means, beside the control.

Five of them, and the count is the whole design. A facts list that doubles in
height turns every hint into wallpaper, and since the record page landed on
preview a read is roughly nine views in ten — so teaching copy on every view is
also how the one sentence in this slot that is a FACT about the record, the
derived-status lock, stops being read. The two tenants of the slot are therefore
different elements with different rules, and most of this file is about keeping
them different.

What is asserted here, in order: that the copy reaches the page at all, that it
reaches only a reader who can act on it, that an empty one takes no line — which
is a claim about the cascade and is resolved against the real cascade — and that
the sentence follows the BALL rather than the saved value, which is a claim about
a running script and is driven in a real browser.

The words themselves are read rather than tested. That is what the diff is for.
"""

from __future__ import annotations

import json
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import ISSUE_STATUS, NOTE_STATUS, STATUS_ORDER, load_repo
from openproj.render import (
    _STATE_HINT,
    FIELD_TEACH,
    ROUTES,
    STATUS_TEACH,
    TEMPLATES,
    render_detail,
)

HEAD = "0123456789abcdef0123456789abcdef01234567"

# The three words this deliberately says nothing about, written down so that
# adding a rung to the ladder fails here rather than shipping a gap. `ready`,
# `in_progress` and `done` are words a person owns before they meet this tool,
# and a hint that restates a word's ordinary meaning is the one that teaches
# people to skim the ones that do not.
UNTAUGHT = {"ready", "in_progress", "done"}


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


# --------------------------------------------------------------------------- #
# Reading the page as a tree, because a substring cannot tell markup from text
# --------------------------------------------------------------------------- #


class _Facts(HTMLParser):
    """Every `<dd>` in the facts list, and what is inside it.

    A control, its `aria-describedby`, and each `<span>` with its classes and its
    text — which is what the four questions below are all actually about. Parsed
    and not searched: whether a sentence is INSIDE the `<dd>` that holds the
    control it describes is a fact about the tree, and five escaping bugs have
    already shipped here under tests that asserted on substrings.
    """

    def __init__(self) -> None:
        super().__init__()
        self.facts: list[dict] = []
        self.ids: set[str] = set()
        self._depth = 0
        self._span: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "dd":
            self._depth = 1
            self.facts.append({"controls": [], "spans": [], "described": set()})
            return
        if not self._depth:
            return
        self._depth += 1
        # From any element, not only from a control. Status's describedby is on
        # the hill's radiogroup span rather than on an input, because a `<label
        # for>` can name one element and naming one stop of six would tell a
        # screen reader that "Status" is the word for `shaping`.
        for one in (a.get("aria-describedby") or "").split():
            self.facts[-1]["described"].add(one)
        if tag in ("input", "select", "textarea"):
            self.facts[-1]["controls"].append(
                {"name": a.get("name", ""), "id": a.get("id", ""),
                 "describedby": a.get("aria-describedby", ""), "type": a.get("type", "")}
            )
        if tag == "span":
            self._span = {"id": a.get("id", ""),
                          "classes": frozenset((a.get("class") or "").split()),
                          "data": a.get("data-teach", ""), "text": ""}
            self.facts[-1]["spans"].append(self._span)

    def handle_data(self, data: str) -> None:
        if self._span is not None:
            self._span["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "dd":
            self._depth = 0
            self._span = None
        elif self._depth:
            self._depth -= 1
            if tag == "span":
                self._span = None


def facts_of(page: str) -> tuple[list[dict], set[str]]:
    parser = _Facts()
    parser.feed(page)
    return parser.facts, parser.ids


def teaching_in(page: str) -> dict[str, dict]:
    """The teaching span of each `<dd>` that has one, keyed by the control it
    sits with — which is the relationship being claimed, and the reason this is
    keyed by control rather than by span id."""
    found = {}
    for fact in facts_of(page)[0]:
        teach = [s for s in fact["spans"] if "teach" in s["classes"]]
        if not teach:
            continue
        assert len(teach) == 1, "one row grew two teaching sentences"
        name = fact["controls"][0]["name"] if fact["controls"] else ""
        found[name] = teach[0] | {"described": fact["described"]}
    return found


def editable_page(index: Index, record_id: str) -> str:
    return render_detail(index, ROUTES, only=record_id, base_commit=HEAD, may_write=True)


def a_pitch(index: Index) -> str:
    return next(i for i, e in sorted(index.plan.items()) if e.kind == "pitch")


# --------------------------------------------------------------------------- #
# That it arrives
# --------------------------------------------------------------------------- #


def test_every_sentence_written_reaches_the_page(index: Index) -> None:
    """The whole point of the branch, asserted once.

    Both maps at once, because they are one decision split by how the control is
    shaped: `person_weeks` and `cycle` are fields with one meaning each, status is
    one field with six places to stand. A sentence in a map that no page renders
    is a copy pass that shipped nothing.
    """
    record_id = a_pitch(index)
    record = index.plan[record_id]

    found = teaching_in(editable_page(index, record_id))
    for name, sentence in FIELD_TEACH.items():
        assert name in found, f"{name} has a sentence and the page does not carry it"
        assert found[name]["text"] == sentence

    for word, sentence in STATUS_TEACH.items():
        record.status = word
        found = teaching_in(editable_page(index, record_id))
        assert found["status"]["text"] == sentence, f"{word} did not reach the page"


def test_a_word_with_nothing_to_teach_still_gets_its_span(index: Index) -> None:
    """Empty, and emitted anyway — which is not an oversight but the mechanism.

    `attachHill` fills this element as the ball moves, and it cannot fill one
    that was never rendered: without it, opening a `done` record and dragging to
    `shelved` would teach nothing, which is the one moment the sentence exists
    for. Genuinely empty and not whitespace, because `.record.editing
    .teach:empty` is what stops it taking a line and a newline between the tags
    is a text node.
    """
    record_id = a_pitch(index)
    record = index.plan[record_id]
    for word in sorted(UNTAUGHT):
        record.status = word
        found = teaching_in(editable_page(index, record_id))
        assert "status" in found, f"a {word} record has nowhere to put the sentence"
        assert found["status"]["text"] == "", f"{word} was given copy this map does not hold"


def test_the_status_row_carries_the_map_the_script_reads(index: Index) -> None:
    """And only that row.

    The sentences travel on the element that shows them rather than in the page's
    data, because `hill.py` draws a hill and has no business importing the Shape
    Up copy. What has to hold is that the attribute parses and says exactly what
    the server holds — a map that arrives half-escaped is a script that throws on
    the first drag, in a handler nothing is watching.
    """
    found = teaching_in(editable_page(index, a_pitch(index)))
    assert json.loads(found["status"]["data"]) == STATUS_TEACH
    for name, span in found.items():
        if name != "status":
            assert not span["data"], f"{name} is a fixed sentence and needs no map"


def test_each_sentence_describes_the_control_it_sits_with(index: Index) -> None:
    """`aria-describedby`, pointing at an id that is on the page.

    Position is the channel that reaches nobody using a screen reader, so a
    sentence that is merely NEAR a control is a sentence half the readers of this
    page never get. A describedby naming an id that does not exist is worse than
    none: it is silent in every browser and in every test that only asks whether
    the attribute is present.
    """
    page = editable_page(index, a_pitch(index))
    ids = facts_of(page)[1]
    found = teaching_in(page)
    assert set(found) >= {"status", "cycle", "person_weeks"}
    for name, span in found.items():
        if not span["text"] and not span["data"]:
            continue
        assert span["id"] in span["described"], (
            f"{name}'s control does not point at its sentence"
        )
        for one in span["described"]:
            assert one in ids, f"{name} is described by {one}, which is not on this page"


def test_the_lock_and_the_lesson_are_two_spans_and_survive_each_other(index: Index) -> None:
    """The slot has two tenants and they are not interchangeable.

    A note whose status is derived says "from what it became" — a fact about THIS
    record, true in both modes — and that is not a substitute for what a word
    means, nor the sentence that may be dropped when both apply. This is the row
    where one variable holding both would have quietly lost one of them.
    """
    record_id = next(i for i, e in sorted(index.records.items()) if e.kind == "note" and e.became)
    page = editable_page(index, record_id)
    facts, ids = facts_of(page)
    status = next(f for f in facts if any(c["name"] == "status" for c in f["controls"]))
    hint = [s for s in status["spans"] if "hint" in s["classes"] and "teach" not in s["classes"]]
    assert [s["text"] for s in hint] == [_STATE_HINT["note"]]
    # And the lock reads in BOTH modes, which is the difference being kept.
    assert "editing-only" not in hint[0]["classes"]


# --------------------------------------------------------------------------- #
# That it arrives only where it is any use
# --------------------------------------------------------------------------- #


def test_a_reader_who_cannot_write_is_not_taught(index: Index) -> None:
    """The static export carries no controls, so it carries no lessons either.

    Not a size argument. A sentence explaining how to set a field, on a page with
    no field to set, is the clutter that made this copy edit-only in the first
    place — and in the export it could never appear at all, since nothing ever
    puts `.editing` on that page. Rendered, it would be four hundred records'
    worth of markup that no reader can reach.
    """
    page = render_detail(index, ROUTES, only=a_pitch(index))
    assert teaching_in(page) == {}


def test_the_inbox_ladders_keep_the_slot_for_their_own_sentence(index: Index) -> None:
    """An issue and a note are not taught the planned vocabulary.

    They cannot stand where it applies: an issue has no `thinking` at all, and a
    note's `thinking` is a different idea — "still turning this over" rather than
    "written down, nobody has started". One shared sentence would be false on one
    of the two, which is why the map is read on the `record` ladder alone.
    """
    assert "thinking" not in ISSUE_STATUS
    assert set(NOTE_STATUS) & set(STATUS_TEACH) == {"thinking"}, (
        "a note's vocabulary has drifted; check whether these sentences still miss it"
    )
    for kind in ("issue", "note"):
        record_id = next(i for i, e in sorted(index.records.items()) if e.kind == kind)
        found = teaching_in(editable_page(index, record_id))
        assert "status" not in found, f"an {kind} was taught a planned record's word"


def test_every_word_a_planned_record_stands_on_is_decided_about(index: Index) -> None:
    """A rung added to the ladder has to be either taught or deliberately not.

    Derived from `STATUS_ORDER` rather than restating it, so the day somebody
    adds a word this fails and somebody decides — which is the whole reason the
    omissions are written down. `thinking` is the live example: it reached the
    planned rungs on 2026-08-24 and needed the sentence more than any word
    already there, because it is the one nobody has a prior for.
    """
    assert set(STATUS_TEACH) | UNTAUGHT == set(STATUS_ORDER), (
        "the status ladder and this file's two lists disagree"
    )
    assert not set(STATUS_TEACH) & UNTAUGHT

    # And the fields, against the ones a pitch actually offers.
    offered = {c["name"] for f in facts_of(editable_page(index, a_pitch(index)))[0]
               for c in f["controls"]}
    assert set(FIELD_TEACH) <= offered, "a sentence is written for a field no pitch has"


def test_no_lesson_runs_to_wallpaper() -> None:
    """One sentence each, and short enough to sit under a control.

    The bound is the design constraint written as a number: the facts list is a
    narrow column beside the document, and a hint that wraps to three lines there
    is the thing that turns a form into a wall of advice nobody reads. Four
    fields, not fourteen — and four short ones, not four paragraphs.
    """
    for name, sentence in (FIELD_TEACH | STATUS_TEACH).items():
        assert sentence.endswith("."), f"{name} does not finish its sentence"
        assert len(sentence) <= 120, f"{name} is {len(sentence)} characters and wants cutting"
        assert "\n" not in sentence


# --------------------------------------------------------------------------- #
# That it says what the pitch template asks for
# --------------------------------------------------------------------------- #


def test_the_pitch_template_names_both_ways_to_get_the_level_wrong(index: Index) -> None:
    """The one line that is not a hint, because it is not about a control.

    Abstraction level is chosen while the Solution is being written, not while a
    field is being set, so it goes where the writing happens: an HTML comment in
    the body the template drops into an empty box — invisible to every reader
    under preview-first landing, visible to the writer, and transient by
    construction, since you delete it as you fill the section in.

    Given as the symptom pair rather than as the aphorism, so that a draft can be
    held against it. Deliberately NOT in `_shaping_hints`, whose every note is
    specific and detectable and which fires only on `ready`/`in_progress`
    pitches — excluding exactly the moment this decision is made.
    """
    template = TEMPLATES["pitch"]
    solution = template.split("## Solution", 1)[1].split("\n## ", 1)[0]
    assert "Too vague" in solution and "Too concrete" in solution
    # Inside the comment, which is what makes it invisible to a reader and
    # harmless when nobody deletes it.
    assert solution.strip().startswith("<!--") and solution.strip().endswith("-->")


# --------------------------------------------------------------------------- #
# That an empty one takes no line — resolved against the real cascade
# --------------------------------------------------------------------------- #


def _teach_span(editing: bool, empty: bool) -> list:
    from cascade import el

    return [
        el("body"),
        el("div", "record editing" if editing else "record"),
        el("dl"),
        el("dd"),
        el("span", "hint teach editing-only", states="empty" if empty else ""),
    ]


def test_an_empty_lesson_is_hidden_in_the_mode_that_shows_the_rest(index: Index) -> None:
    """Which is a claim about specificity, so it is asked of the real cascade.

    A rule being in the stylesheet says nothing about whether it wins, and
    qualifying a selector to win one fight in this file has twice silently lost
    three. `.record.editing .editing-only` is (0,3,0) and would give an empty
    span a block box; the rule that hides it repeats both ancestors and lands at
    (0,4,0), so it wins on specificity and not on order — which is what keeps it
    correct if either rule moves.

    All four states, because the interesting failure is not "the empty one shows"
    but "the rule that hides the empty one also hid the full one".
    """
    from cascade import sheet_of

    sheet = sheet_of(editable_page(index, a_pitch(index)))
    assert sheet.value(_teach_span(editing=True, empty=False), "display") == "block"
    assert sheet.value(_teach_span(editing=True, empty=True), "display") == "none"
    assert sheet.value(_teach_span(editing=False, empty=False), "display") == "none"
    assert sheet.value(_teach_span(editing=False, empty=True), "display") == "none"


# --------------------------------------------------------------------------- #
# That the sentence follows the ball — driven in a real browser
# --------------------------------------------------------------------------- #


def test_the_sentence_follows_the_ball(index: Index, tmp_path: Path) -> None:
    """Pressed, not saved: the copy describes the stop you are choosing.

    Somebody moving the ball onto `shelved` is deciding what shelved means, and a
    line still describing where they came from is help for the wrong decision.
    Driven in Chrome and not in the node shim, because the claim is that a change
    on a radio reaches a listener on the group — and `drive.js` dispatches without
    bubbling, so it would answer for the shim rather than for the page.

    The last leg is the one that would ship broken quietly: pressing a word with
    nothing to teach has to EMPTY the line rather than leave the previous lesson
    standing under a stop it is not about.
    """
    browser = chrome()
    record_id = a_pitch(index)
    index.plan[record_id].status = "shaping"
    page = editable_page(index, record_id)
    found = measured_in(
        browser, page, tmp_path / "detail.html", 1100,
        """
        flipEditing();
        // A timer and not `requestAnimationFrame`: this runs under Chrome's
        // virtual clock, which drives timers and does not necessarily drive
        // frames.
        await new Promise(settled => setTimeout(settled, 50));
        const hill = document.querySelector('.hill[role=radiogroup]');
        const teach = document.querySelector('.teach[data-teach]');
        const press = word => [...hill.querySelectorAll('.hill-stop')]
          .find(s => s.querySelector('input').value === word).click();
        const said = {start: teach.textContent};
        for (const word of ['shelved', 'done', 'thinking']) {
          press(word);
          said[word] = teach.textContent;
          said[word + '_shown'] = getComputedStyle(teach).display;
        }
        return said;
        """,
        height=1400, patience=2500,
    )
    assert found["start"] == STATUS_TEACH["shaping"]
    assert found["shelved"] == STATUS_TEACH["shelved"]
    assert found["thinking"] == STATUS_TEACH["thinking"]
    assert found["done"] == "", "a lesson stayed under a stop it is not about"
    # And the row does not keep a blank line where that lesson was.
    assert found["done_shown"] == "none"
    assert found["shelved_shown"] != "none"


def test_a_status_nobody_may_set_is_never_taught_a_lesson(index: Index, tmp_path: Path) -> None:
    """A locked control has no stops, so there is nothing to choose and nothing
    to teach — and `attachHill` leaves before it reaches the sentence.

    The failure this guards is the other order: a script that filled the lesson
    first and then found no radiogroup would print what `promoted` means beside a
    control nobody can move, under the sentence that already says the word is
    derived. Two explanations for one row, one of them useless.
    """
    browser = chrome()
    record_id = next(i for i, e in sorted(index.records.items()) if e.kind == "note" and e.became)
    page = editable_page(index, record_id)
    found = measured_in(
        browser, page, tmp_path / "note.html", 1100,
        """
        flipEditing();
        await new Promise(settled => setTimeout(settled, 50));
        return {
          live: !!document.querySelector('.hill[role=radiogroup]'),
          teach: !!document.querySelector('.teach'),
          lock: document.querySelector('#facts .hint:not(.teach)')?.textContent.trim() || '',
        };
        """,
        height=1400, patience=2500,
    )
    assert found["live"] is False, "a derived status offered stops"
    assert found["teach"] is False
    assert found["lock"] == _STATE_HINT["note"]
