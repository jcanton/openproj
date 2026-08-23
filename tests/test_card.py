"""One hover card, drawn by three views.

The timeline had it and it was good. A graph node carries a title and a status
glyph; the table's title cell is the one cell whose real field — the shaping
document — is not on the row at all. So all three draw the same card, and the
point of this file is the word *same*: this codebase has already paid once for
one fact formatted three ways, when `appetite_weeks` read as three different
numbers on three pages.

The body is fetched on hover rather than shipped with the rows, so half of this
is about what happens between the pointer arriving and the answer coming back —
including the answers that never come.
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
from openproj.model import RUNG, load_repo
from openproj.render import ROUTES, render_graph, render_table, render_timeline

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def one_pitch(index: Index) -> str:
    """A record with people, a cycle, dates and a document — so a card of it has
    something in every row rather than four dashes."""
    for record_id, record in sorted(index.plan.items()):
        if record.kind == "pitch" and record.body and record.tags and record.owner:
            return record_id
    raise AssertionError("the corpus has no pitch with a document on it")


# The card, drawn for one row, with the body fetch answered by hand. `drive.js`
# hands the page a `fetch` that returns these in order, so what is asked for and
# what is done with the answer are both visible from here.
def card_for(page: str, record_id: str, replies: list[dict] | None = None) -> dict:
    answer = run_js(
        page,
        "(async () => {"
        f"  const arriving = showCard(DATA.rows[{json.dumps(record_id)}], 100, 100);"
        "  const first = CARD.innerHTML;"
        "  await arriving;"
        # Microtasks and not a timer: `drive.js` queues timers rather than
        # running them, so a `setTimeout` here never fires and the expression
        # comes back as never settled — which reads as a card that drew nothing.
        "  for (let i = 0; i < 20; i++) await Promise.resolve();"
        f"  return {{first, then: CARD.innerHTML, hidden: CARD.hidden,"
        f"          held: CARD_BODIES.get({json.dumps(record_id)})}};"
        "})()",
        page=True,
        replies=replies or [],
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    return answer


# Each view is asked for the card it draws for one row, in its own words: the
# graph has no `DATA` at all — a node's data IS the row — which is how the first
# version of the graph's card drew nothing whatsoever.
_DRAWN = {
    "table": "showCard(DATA.rows[%s], 100, 100); return {html: CARD.innerHTML};",
    "timeline": "showCard(DATA.rows[%s], 100, 100); return {html: CARD.innerHTML};",
    "graph": "showCard(cy.getElementById(%s).data(), 100, 100); return {html: CARD.innerHTML};",
}


def test_the_three_views_draw_the_same_card(index: Index, tmp_path: Path):
    """One row, three pages, one box.

    Asked of the markup each page actually produces rather than of the fact that
    all three call one function: the views hand it different rows — the
    timeline's carries `weeks` and a sentence about scheduling that the others do
    not — and the claim is that everything they share is drawn identically.

    In Chrome and not in the shim, because one of the three pages is the graph and
    the graph is cytoscape: a harness that cannot build the view cannot be asked
    what the view draws.
    """
    record_id = one_pitch(index)
    drawn = {
        "table": render_table(index, ROUTES, base_commit=HEAD),
        "graph": render_graph(index, ROUTES, base_commit=HEAD),
        "timeline": render_timeline(index, ROUTES),
    }
    html = {
        name: measured_in(
            chrome(),
            page,
            tmp_path / f"{name}.html",
            1200,
            _DRAWN[name] % json.dumps(record_id),
        )["html"]
        for name, page in drawn.items()
    }

    # The timeline adds one line the others have nothing to say for: why a bar
    # starts when it does. Everything above it is the shared card.
    shared = {
        name: re.sub(r'<p class="card-why">.*?</p>', "", drawn_html)
        for name, drawn_html in html.items()
    }
    assert "card-title" in shared["table"], "no card was drawn at all"
    assert shared["table"] == shared["graph"], "the table and the graph disagree"
    assert shared["table"] == shared["timeline"], "the timeline disagrees with the other two"


def test_the_card_says_the_things_a_row_does_not(index: Index):
    """A node is a title and a glyph; a bar is a rectangle. What the card is for
    is the rest of the record, so it says who owns it, when it runs, what it is
    tagged and what kind it is."""
    record_id = one_pitch(index)
    record = index.plan[record_id]
    drawn = card_for(render_table(index, ROUTES, base_commit=HEAD), record_id)["value"]["first"]

    assert record.title in drawn
    assert record.owner in drawn
    assert record.tags[0] in drawn
    for word in ("Owner", "Scheduled", "Tags"):
        assert f"<dt>{word}</dt>" in drawn, word


def test_the_document_is_fetched_on_hover_and_not_shipped_with_the_rows(index: Index):
    """Inlining every body into the table's payload puts the whole corpus in every
    page load to answer a question about the one row somebody is pointing at.

    So the card asks for one, by id, when a pointer arrives — and the page it asks
    from is the server's, which is the only place the answer exists.
    """
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD)
    assert index.plan[record_id].body not in page, "the corpus is in the page after all"

    answer = card_for(page, record_id, [{"status": 200, "json": {"html": "<p>the document</p>"}}])

    asked = [call["url"] for call in answer["calls"]]
    assert asked == [f"/api/body/{record_id}"], asked
    assert "card-body" not in answer["value"]["first"], "the card waited for the fetch"
    # What was done with the answer is asked in the browser below: the shim's
    # `innerHTML` reports the string that was assigned to it, not a serialisation
    # of the children — so an appended document is invisible to it, and a test
    # that believed otherwise would be a test of the shim.
    assert answer["value"]["held"] == "<p>the document</p>"


def test_a_refused_document_costs_the_document_and_nothing_else(index: Index):
    """A 404, a 500 or a policy that refuses the request leaves the card holding
    what the row already carried. The fields are the part that was never in
    doubt, and a card that empties itself because a fetch failed is a card that
    reports a network as a plan."""
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD)

    for reply in ({"status": 404, "text": "no such record"}, {"status": 500, "text": "boom"}):
        answer = card_for(page, record_id, [reply])
        assert "card-title" in answer["value"]["then"], reply
        assert "card-body" not in answer["value"]["then"], reply
        assert answer["value"]["hidden"] is False, reply


def test_a_document_that_arrives_late_is_not_drawn_on_the_wrong_card(index: Index):
    """The pointer moves faster than a fetch answers.

    Two rows hovered in a row, and the first document arriving after the second
    card is up: without the check this draws one record's shaping document under
    another record's title, which is worse than showing nothing at all.
    """
    ids = sorted(index.plan)[:2]
    page = render_table(index, ROUTES, base_commit=HEAD)

    answer = run_js(
        page,
        "(async () => {"
        f"  const first = showCard(DATA.rows[{json.dumps(ids[0])}], 10, 10);"
        f"  const second = showCard(DATA.rows[{json.dumps(ids[1])}], 20, 20);"
        "  await Promise.all([first, second]);"
        "  for (let i = 0; i < 20; i++) await Promise.resolve();"
        "  return {html: CARD.innerHTML};"
        "})()",
        page=True,
        replies=[
            {"status": 200, "json": {"html": "<p>first document</p>"}},
            {"status": 200, "json": {"html": "<p>second document</p>"}},
        ],
    )
    html = answer["value"]["html"]

    assert index.plan[ids[1]].title in html, "the card is not the one that was asked for last"
    assert "first document" not in html, "one record's document is under another's title"


def test_a_rendered_file_draws_a_card_with_no_server_to_ask(index: Index):
    """The static export has no server, so the card degrades: the fields it was
    given, and no document. The title beside it is still a link into
    `detail.html#id`, where the whole document is — the same shape as co-editing
    falling back to a plain textarea."""
    record_id = one_pitch(index)
    page = render_table(index)     # STATIC links: no `body` route

    assert 'data-body-url' not in page
    answer = card_for(page, record_id)

    assert "card-title" in answer["value"]["first"]
    assert "card-body" not in answer["value"]["then"]
    assert answer["calls"] == [], "a rendered file asked a server for something"


# --------------------------------------------------------------------------- #
# What a browser has to answer
# --------------------------------------------------------------------------- #


_PLACED = """
const row = DATA.rows[%s];
showCard(row, innerWidth - 20, innerHeight - 20);
const box = CARD.getBoundingClientRect();
return {right: box.right, bottom: box.bottom, width: box.width,
        room: {w: innerWidth, h: innerHeight}};
"""


def test_a_card_at_the_edge_of_the_window_stays_inside_it(index: Index, tmp_path: Path):
    """Pointed at from the bottom-right corner, the card flips to the other side
    of the pointer rather than hanging off the page. The timeline's did this
    already; it is asserted here because two more views now depend on it, and one
    of them is a table whose last row is at the bottom of the window."""
    record_id = one_pitch(index)
    got = measured_in(
        chrome(),
        render_table(index, ROUTES, base_commit=HEAD),
        tmp_path / "edge.html",
        1200,
        _PLACED % json.dumps(record_id),
        height=800,
    )

    assert got["width"] > 0, "nothing was drawn"
    assert got["right"] <= got["room"]["w"], "the card runs off the right of the window"
    assert got["bottom"] <= got["room"]["h"], "the card runs off the bottom of the window"


_TALL_BODY = """
const row = DATA.rows[%s];
showCard(row, 40, 40);
const body = document.createElement('div');
body.className = 'card-body';
body.innerHTML = '<p>' + 'a long paragraph of shaping. '.repeat(400) + '</p>';
CARD.appendChild(body);
const card = CARD.getBoundingClientRect();
return {card: card.height, body: body.getBoundingClientRect().height,
        scrolls: body.scrollHeight > body.clientHeight + 1, room: innerHeight};
"""


def test_a_nine_hundred_word_document_does_not_cover_the_table(index: Index, tmp_path: Path):
    """Larger and scrollable, with a cap. A pitch drawn in full is taller than the
    window it is drawn over, and a card that covers the table it was opened from
    is a card that has to be dismissed before the plan can be read again."""
    record_id = one_pitch(index)
    got = measured_in(
        chrome(),
        render_table(index, ROUTES, base_commit=HEAD),
        tmp_path / "tall.html",
        1200,
        _TALL_BODY % json.dumps(record_id),
        height=800,
    )

    assert got["card"] < got["room"] / 2, (
        f"the card is {got['card']}px of an {got['room']}px window"
    )
    assert got["scrolls"], "the document was clipped rather than made scrollable"


# The card is opened by a script of its own, at load, because the measuring
# script runs once and cannot await anything: `measured_in` wraps it in a plain
# arrow function. So the page answers the fetch itself — it cannot reach a server
# from a `file://` URL, and what is being asked is what the card DOES with an
# answer rather than whether one arrives.
_OPENS_A_CARD = """
<script>
window.fetch = async () => ({ok: true, json: async () => ({html: '<p>the document</p>'})});
showCard(DATA.rows[%s], 100, 100);
</script>
"""

_WITH_A_DOCUMENT = """
const body = CARD.querySelector('.card-body');
return {
  drawn: !!body,
  text: body ? body.textContent : '',
  belowTheFacts: body ? body.previousElementSibling.tagName : '',
};
"""


def test_the_document_is_drawn_under_the_fields(index: Index, tmp_path: Path):
    """And it is drawn where a document belongs: under the facts, not instead of
    them. The shim cannot answer this — its `innerHTML` reports what was assigned
    to it rather than what the element now contains — so it is asked of a
    browser."""
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD).replace(
        "</body>", _OPENS_A_CARD % json.dumps(record_id) + "</body>"
    )
    got = measured_in(chrome(), page, tmp_path / "body.html", 1200, _WITH_A_DOCUMENT)

    assert got["drawn"], "the answer arrived and the card ignored it"
    assert "the document" in got["text"]
    assert got["belowTheFacts"] == "DL", "the document is not under the record's fields"


# --------------------------------------------------------------------------- #
# Asking for a card, and reaching it
# --------------------------------------------------------------------------- #


_HOVER_INTENT = """
const row = DATA.rows[%s];
queueCard(row, 100, 100);
const atOnce = CARD.hidden;
await new Promise(done => setTimeout(done, 700));
window.__asked = {atOnce, later: CARD.hidden};
"""


def test_a_pointer_passing_over_a_row_does_not_open_a_card(index: Index, tmp_path: Path):
    """A pointer crossing a table on its way somewhere else is not a question, and
    a card that answers it anyway flashes a box over every row on the way past.

    Asked with a real timer in a real browser, because the claim is about time.
    """
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD).replace(
        "</body>",
        # Assigned to a global rather than returned: the measuring script cannot
        # await, and a promise stringifies as `{}`. The wait inside is shorter
        # than the 1200ms `measured_in` gives the page, so the answer is there
        # when it looks.
        "<script>(async () => {"
        + (_HOVER_INTENT % json.dumps(record_id))
        + "})();</script></body>",
    )
    got = measured_in(
        chrome(), page, tmp_path / "intent.html", 1200, "return window.__asked;"
    )

    assert got["atOnce"] is True, "the card opened on the first pointer event"
    assert got["later"] is False, "the card never opened at all"


_REACHABLE = """
const row = DATA.rows[%s];
showCard(row, 100, 100);
const style = getComputedStyle(CARD);
// The pointer leaves the row and is on its way to the card.
hideCard();
const leaving = CARD.hidden;
CARD.dispatchEvent(new PointerEvent('pointerenter'));
await new Promise(done => setTimeout(done, 500));
window.__reach = {events: style.pointerEvents, leaving, afterGrace: CARD.hidden};
"""


def test_the_card_can_be_reached_and_stays_while_the_pointer_is_in_it(
    index: Index, tmp_path: Path
):
    """The document is capped and scrollable, and a box the pointer passes
    straight through is a scrollbar nobody can grab — which is what shipped.

    Two halves: the card takes pointer events at all, and leaving the row only
    starts a timer that entering the card cancels. Without the second the gap
    between the row and the box cannot be crossed.
    """
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD).replace(
        "</body>",
        "<script>(async () => {"
        + (_REACHABLE % json.dumps(record_id))
        + "})();</script></body>",
    )
    got = measured_in(
        chrome(), page, tmp_path / "reach.html", 1200, "return window.__reach;"
    )

    assert got["events"] != "none", "the pointer goes straight through the card"
    assert got["leaving"] is False, "the card went the instant the row was left"
    assert got["afterGrace"] is False, "the card went while the pointer was inside it"


_TWICE = """
window.fetch = async () => ({ok: true, json: async () => ({html: '<p>the document</p>'})});
const row = DATA.rows[%s];
await showCard(row, 100, 100);
// Again, which is a pointer that left and came back — and, with the answer
// cached, lands in the same tick.
await showCard(row, 100, 100);
await showCard(row, 100, 100);
window.__twice = {bodies: CARD.querySelectorAll('.card-body').length,
        text: CARD.textContent.split('the document').length - 1};
"""


def test_one_card_holds_one_document(index: Index, tmp_path: Path):
    """Two answers can be in flight for one card — the pointer leaves and comes
    back, or a cached body lands in the same tick as a fetched one. Appending
    drew the shaping document twice inside one box, which is the thing jcanton
    saw and could not reproduce."""
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD).replace(
        "</body>",
        "<script>(async () => {"
        + (_TWICE % json.dumps(record_id))
        + "})();</script></body>",
    )
    got = measured_in(
        chrome(), page, tmp_path / "twice.html", 1200, "return window.__twice;"
    )

    assert got["bodies"] == 1, f"{got['bodies']} documents in one card"
    assert got["text"] == 1


# The card is queued behind a delay, so this cannot read `hidden` in the same
# breath as the hover — it would report "no card" about a card that was on its
# way. The answer is written from a continuation instead: `--dump-dom` reads the
# page at the end of its virtual time, so the last write of `data-report` is the
# one the harness brings back.
#
# The arithmetic matters and it is the harness's `patience` that pays for it: the
# script is injected at 1200ms and the virtual clock stops `patience` later, so a
# continuation that runs past it leaves the placeholder in the DOM and the test
# reports nothing at all — which reads exactly like a card that never came up.
# `CARD_DELAY` is 400, and this waits 460 once per box plus once at the start.
_OVER_A_BOX = """
const card = document.getElementById('card');
// One box of each kind that draws one. A project holding pitches and a pitch
// holding tasks are the same thing to cytoscape — both are `isParent()` — but
// asking only the first parent asked only about a project, and "it is the same
// code path" is the sort of claim that stops being true quietly.
const boxes = {};
for (const node of cy.nodes().filter(one => one.isParent())) {
  const kind = node.data('kind');
  if (!boxes[kind]) boxes[kind] = node;
}
const picked = Object.values(boxes);
if (!picked.length) return {error: 'the corpus has no box'};

const hover = (node, at) =>
  node.emit({type: 'mouseover', position: at, originalEvent: {clientX: 10, clientY: 10}});
const middleOf = node => {
  const box = node.boundingBox({includeLabels: false});
  return {x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2};
};
const titleOf = node => {
  const box = node.boundingBox({includeLabels: false});
  return {x: box.x1 + 20, y: box.y1 + 10};
};

// Every middle first, so nothing is showing before the titles are tried.
picked.forEach(node => hover(node, middleOf(node)));
setTimeout(() => {
  const middles = card.hidden;
  const said = {};
  // One title at a time, each answered before the next is asked — two hovers in
  // one frame would leave only the last one's card up.
  const askEach = i => {
    if (i === picked.length) {
      document.body.dataset.report = JSON.stringify({middles, said});
      return;
    }
    hover(picked[i], titleOf(picked[i]));
    setTimeout(() => {
      said[picked[i].data('kind')] = card.hidden ? 'nothing' : 'a card';
      cy.emit('pan');   // put it away before the next one is asked
      askEach(i + 1);
    }, 460);
  };
  askEach(0);
}, 460);
return {middles: null};
"""


def test_a_box_answers_for_its_label_and_not_for_its_acres(index: Index, tmp_path: Path):
    """jcanton, 2026-08-20: the card should come up over a box's title, not over
    the whole box.

    A compound node is hit over its entire area, and almost all of that area is
    where its children are drawn. So reading a project's tasks meant dragging the
    pointer through a card about their parent — in the way of the very thing being
    read, on the view whose whole job is showing what is inside what.
    """
    page = render_graph(index, ROUTES, base_commit=HEAD)
    # Longer than the default: this answers from a continuation, and the waits it
    # needs are one `CARD_DELAY` per box plus the first one.
    got = measured_in(chrome(), page, tmp_path / "boxcard.html", 1400, _OVER_A_BOX,
                      height=1000, patience=3000)

    assert not got.get("error"), got
    assert got["middles"] is not None, "the continuation never ran, so nothing was measured"
    assert got["middles"] is True, "a card came up over the middle of a box"
    # A project holding pitches and a pitch holding tasks, both of them.
    assert set(got["said"]) >= {"project", "pitch"}, (
        f"only {sorted(got['said'])} was asked, so the other kind of box is untested"
    )
    # WHICH boxes answer is a fact about the ladder and not about this list.
    # `carded` is a property on `Rung` in `model.py` — a product declares
    # `carded: false`, because a card of one would be a title, a sentence and
    # eight dashes, which teaches a reader that cards are not worth hovering
    # for. The graph reads that same property (`CARDED` in `graph.py`), so this
    # asserts the rule rather than a list of kinds that has to be edited every
    # time a rung is added.
    #
    # Untestable until 2026-08-23: `carded: false` had no record in any corpus,
    # so the one rung that declares it was never hovered and the branch that
    # honours it was never reached. This test asserted "every box opens a card"
    # and passed for four kinds that all happen to be carded.
    for kind, answer in got["said"].items():
        wanted = "a card" if RUNG[kind].carded else "nothing"
        assert answer == wanted, (
            f"a {kind}'s own title brought up {answer}, and the ladder says "
            f"carded={RUNG[kind].carded}, so it should bring up {wanted}"
        )
    # And both halves of that rule were actually asked. A corpus with no
    # uncarded box would pass the loop above without ever reaching the branch it
    # was written for — which is exactly the state this suite was in yesterday.
    carded = {kind for kind in got["said"] if RUNG[kind].carded}
    assert carded, "no carded box was hovered, so 'a card comes up' is untested"
    assert set(got["said"]) - carded, (
        "no box of an uncarded kind is on this graph, so the rule that a hover "
        "over one brings up nothing is untested"
    )


# How many times the card's markup changes between the hover and the card being
# up. Two is the defect: the fields, then the body a moment later, with the box
# growing and re-placing itself in between.
_PAINTS = """
// The title cell, which is what the table listens on — a hover anywhere else in
// the row is a pointer on its way somewhere and opens nothing.
const cell = document.querySelector('tbody tr[data-id] td[data-col="title"]');
const card = document.getElementById('card');
// A server, stubbed, because this page is a file and there is none — and the
// point under test is when the document is DRAWN, not where it came from. 50ms
// is a plausible round trip and well inside the 400ms the card waits anyway.
window.fetch = () => new Promise(resolve => setTimeout(() => resolve({
  ok: true, json: () => Promise.resolve({html: '<p>the shaping document</p>'}),
}), 50));

let paints = 0;
new MutationObserver(() => paints++).observe(card, {childList: true, subtree: true});

cell.dispatchEvent(new PointerEvent('pointerover', {bubbles: true, clientX: 40, clientY: 40}));
setTimeout(() => {
  document.body.dataset.report = JSON.stringify({
    paints,
    shown: !card.hidden,
    hasBody: !!card.querySelector('.card-body'),
  });
}, 900);
return {paints: null};
"""


def test_the_card_arrives_in_one_piece(index: Index, tmp_path: Path):
    """jcanton, 2026-08-20: "the frontmatter is rendered faster than the body,
    which lags behind for a split second".

    The fields were drawn the moment the card appeared and the shaping document
    was fetched afterwards, so the box grew and re-placed itself just after
    arriving. The fetch now starts when the pointer arrives and the card is drawn
    400ms later, which is hover-intent time that was being spent on nothing —
    so the answer is normally already here and both halves land in one paint.
    """
    page = render_table(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "paint.html", 1400, _PAINTS,
                      patience=2500)

    assert got["paints"] is not None, "the continuation never ran"
    assert got["shown"], "no card came up at all"
    assert got["hasBody"], "the card came up without the document it exists to show"
    assert got["paints"] <= 1, (
        f"the card's markup changed {got['paints']} times: the body still lands "
        "in a second pass"
    )
