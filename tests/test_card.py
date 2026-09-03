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
import time
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in
from marionette import driving
from test_injection import run_js
from test_table import script

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
        "table": render_table(index, ROUTES, base_commit=HEAD, may_write=True),
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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True)
    drawn = card_for(page, record_id)["value"]["first"]

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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True)
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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True)

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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True)

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
    page = render_table(index)  # STATIC links: no `body` route

    assert "data-body-url" not in page
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
        render_table(index, ROUTES, base_commit=HEAD, may_write=True),
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
        render_table(index, ROUTES, base_commit=HEAD, may_write=True),
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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True).replace(
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
await new Promise(done => setTimeout(done, 900));
window.__asked = {atOnce, later: CARD.hidden};
"""


def test_a_pointer_passing_over_a_row_does_not_open_a_card(index: Index, tmp_path: Path):
    """A pointer crossing a table on its way somewhere else is not a question, and
    a card that answers it anyway flashes a box over every row on the way past.

    Asked with a real timer in a real browser, because the claim is about time.
    """
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True).replace(
        "</body>",
        # Assigned to a global rather than returned: the measuring script cannot
        # await, and a promise stringifies as `{}`. The wait inside is shorter
        # than the 1200ms `measured_in` gives the page, so the answer is there
        # when it looks.
        "<script>(async () => {"
        + (_HOVER_INTENT % json.dumps(record_id))
        + "})();</script></body>",
    )
    got = measured_in(chrome(), page, tmp_path / "intent.html", 1200, "return window.__asked;")

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


def test_the_card_can_be_reached_and_stays_while_the_pointer_is_in_it(index: Index, tmp_path: Path):
    """The document is capped and scrollable, and a box the pointer passes
    straight through is a scrollbar nobody can grab — which is what shipped.

    Two halves: the card takes pointer events at all, and leaving the row only
    starts a timer that entering the card cancels. Without the second the gap
    between the row and the box cannot be crossed.
    """
    record_id = one_pitch(index)
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True).replace(
        "</body>",
        "<script>(async () => {" + (_REACHABLE % json.dumps(record_id)) + "})();</script></body>",
    )
    got = measured_in(chrome(), page, tmp_path / "reach.html", 1200, "return window.__reach;")

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
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True).replace(
        "</body>",
        "<script>(async () => {" + (_TWICE % json.dumps(record_id)) + "})();</script></body>",
    )
    got = measured_in(chrome(), page, tmp_path / "twice.html", 1200, "return window.__twice;")

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
# `CARD_DELAY` is 600, and this waits 660 once per box plus once at the start.
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
    }, 660);
  };
  askEach(0);
}, 660);
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
    got = measured_in(
        chrome(), page, tmp_path / "boxcard.html", 1400, _OVER_A_BOX, height=1000, patience=3800
    )

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
// is a plausible round trip and well inside the 600ms the card waits anyway.
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
    600ms later, which is hover-intent time that was being spent on nothing —
    so the answer is normally already here and both halves land in one paint.
    """
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True)
    got = measured_in(chrome(), page, tmp_path / "paint.html", 1400, _PAINTS, patience=2500)

    assert got["paints"] is not None, "the continuation never ran"
    assert got["shown"], "no card came up at all"
    assert got["hasBody"], "the card came up without the document it exists to show"
    assert got["paints"] <= 1, (
        f"the card's markup changed {got['paints']} times: the body still lands in a second pass"
    )


# --------------------------------------------------------------------------- #
# The box the document is read in
# --------------------------------------------------------------------------- #


# A document long enough to fill the cap several times over, answered for every
# id: what is being asked here is what the BOX does between two records, not
# which document either of them has.
def _stubbed(page: str, html: str) -> str:
    return page.replace(
        "</body>",
        "<script>window.fetch = async () => ({ok: true, json: async () => "
        f"({{html: {json.dumps(html)}}})}});</script></body>",
    )


LONG = "<p>" + "a long paragraph of shaping. " * 400 + "</p>"


def _two_with_documents(index: Index) -> list[str]:
    ids = [record_id for record_id, record in sorted(index.plan.items()) if record.body][:2]
    assert len(ids) == 2, "the corpus has fewer than two records with a document"
    return ids


_ANOTHER_RECORD = """
const ids = %s;
await showCard(DATA.rows[ids[0]], 100, 100);
for (let i = 0; i < 20; i++) await Promise.resolve();
const first = CARD.querySelector('.card-body');
first.scrollTop = first.scrollHeight;
const left = first.scrollTop;

await showCard(DATA.rows[ids[1]], 100, 100);
for (let i = 0; i < 20; i++) await Promise.resolve();
const second = CARD.querySelector('.card-body');
const arrived = second.scrollTop;

// And the same document drawn again into the box it is already in, which is the
// one path that reuses the element rather than replacing it: a cached answer and
// a fetched one landing for one card.
second.scrollTop = second.scrollHeight;
const before = second.scrollTop;
await fillCardBody(ids[1]);
for (let i = 0; i < 20; i++) await Promise.resolve();
const again = CARD.querySelector('.card-body');
return {left, arrived, before, reused: again === second, redrawn: again.scrollTop};
"""


def test_a_card_for_another_record_starts_at_the_top_of_its_document(
    index: Index, tmp_path: Path
):
    """jcanton, 2026-09-03: "if I scroll the body in one record's card, then hover
    over another record, the second record's card is scrolled at the bottom".

    One box is drawn for every record hovered, and a scroll offset is a property
    of the box rather than of the document in it. Where the last pitch was left
    off reading is not where the next one starts — a card that opens at the end
    of a document nobody has read yet reads as a card with nothing in it.

    Asked of both paths, because they are two different mechanisms and only one
    of them is the obvious one: the element is normally REPLACED, which resets
    the offset as a side effect, and it is REUSED when two answers land for one
    card — where nothing resets it unless this says so.
    """
    ids = _two_with_documents(index)
    page = _stubbed(render_table(index, ROUTES, base_commit=HEAD, may_write=True), LONG)
    got = measured_in(chrome(), page, tmp_path / "scrolled.html", 1200,
                      _ANOTHER_RECORD % json.dumps(ids))

    assert got["left"] > 0, "the first card's document did not scroll at all"
    assert got["arrived"] == 0, (
        f"the next record's card opened {got['arrived']}px down its own document"
    )
    assert got["reused"], "the redraw replaced the box, so it asked nothing"
    assert got["before"] > 0 and got["redrawn"] == 0, "a redrawn document kept the old offset"


# The drag, and what it is worth after it: the height a reader sets is a
# statement about how much of a document they want at once, so it has to survive
# the card that was open when they said it.
_DRAGGED = """
const ids = %s;
let cancelled = false;
const drag = by => {
  const grip = CARD.querySelector('.card-grip');
  if (!grip) return false;
  const at = grip.getBoundingClientRect();
  const down = new PointerEvent('pointerdown',
    {bubbles: true, cancelable: true, pointerId: 1, clientX: at.left + 4, clientY: at.top + 4});
  grip.dispatchEvent(down);
  cancelled = cancelled || down.defaultPrevented;
  dispatchEvent(new PointerEvent('pointermove',
    {bubbles: true, pointerId: 1, clientX: at.left + 4, clientY: at.top + 4 + by}));
  dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 1}));
  return true;
};
const tall = () => Math.round(CARD.querySelector('.card-body').getBoundingClientRect().height);

await showCard(DATA.rows[ids[0]], 60, 60);
for (let i = 0; i < 20; i++) await Promise.resolve();
const was = tall();
const gripped = !!CARD.querySelector('.card-grip');
// The cap itself, and the font it is written in ems of: the box around it also
// carries a border and the padding that separates it from the facts.
const styled = getComputedStyle(CARD.querySelector('.card-body'));
const cap = Math.round(parseFloat(styled.maxHeight));
const em = parseFloat(styled.fontSize);
drag(140);
const grown = tall();
const shown = !CARD.hidden;

// The next record, which was never dragged.
await showCard(DATA.rows[ids[1]], 60, 60);
for (let i = 0; i < 20; i++) await Promise.resolve();
const next = tall();

// Dragged back up, well past the default it started at.
drag(-400);
const floored = tall();
// Grown again, so that the other way back — the one the deck's rail has too —
// has something to undo.
drag(300);
const again = tall();
CARD.querySelector('.card-grip').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
const reset = tall();

// And dragged at the window rather than at a number: where the edge stops is
// the claim, because the handle is ON that edge.
drag(2000);
const card = CARD.getBoundingClientRect();
const grip = CARD.querySelector('.card-grip').getBoundingClientRect();
return {was, cap, em, gripped, grown, shown, next, floored, again, reset, cancelled,
        spilled: {card: card.bottom, grip: grip.bottom}, room: innerHeight};
"""


def test_the_bottom_edge_is_dragged_to_show_more_of_the_document(index: Index, tmp_path: Path):
    """8em is one reader's answer and not everybody's. The cap keeps a card from
    covering the table it was opened from, which is the right default and the
    wrong ceiling for somebody reading a pitch on a large screen — so the bottom
    edge is a handle, the default is the floor, and the height outlives the card
    that was open when it was set.

    A double-click puts it back, the way the deck's rail is put back: a drag with
    no way to undo it is a preference somebody is stuck with.
    """
    ids = _two_with_documents(index)
    page = _stubbed(render_table(index, ROUTES, base_commit=HEAD, may_write=True), LONG)
    got = measured_in(chrome(), page, tmp_path / "dragged.html", 1200,
                      _DRAGGED % json.dumps(ids), height=900)

    assert got["gripped"], "a document longer than the box had nothing to drag"
    assert got["cap"] == 8 * got["em"], f"the default is not the stylesheet's 8em: {got['cap']}px"
    assert got["grown"] >= got["was"] + 130, (
        f"the drag moved the edge {got['grown'] - got['was']}px"
    )
    assert got["shown"], "the card was dismissed by the gesture that was resizing it"
    assert got["next"] == got["grown"], "the next card went back to the default"
    assert got["floored"] == got["was"], "the card can be dragged shorter than its default"
    assert got["again"] > got["was"], "the second drag did nothing"
    assert got["reset"] == got["was"], "a double-click did not put the height back"
    # The one a synthetic `dblclick` cannot notice: cancelling a `pointerdown`
    # suppresses the compatibility mouse events the browser builds on it, and
    # the double-click above is one of them. Driving a real mouse at this over
    # CDP on 2026-09-03 is how the handler lost its reset the first time; a test
    # that dispatches `dblclick` itself would have gone on passing.
    assert not got["cancelled"], (
        "the pointerdown is cancelled, which takes the double-click with it"
    )
    assert got["spilled"]["card"] <= got["room"], (
        f"dragged at the window, the card ends {got['spilled']['card'] - got['room']}px below it"
    )
    assert got["spilled"]["grip"] <= got["room"], (
        "the handle itself is dragged off the bottom of the window, where nothing can reach it"
    )


_SHORT = """
await showCard(DATA.rows[%s], 60, 60);
for (let i = 0; i < 20; i++) await Promise.resolve();
const body = CARD.querySelector('.card-body');
return {drawn: !!body, scrolls: body.scrollHeight > body.clientHeight + 1,
        gripped: !!CARD.querySelector('.card-grip')};
"""


def test_a_document_that_fits_has_no_handle_to_drag(index: Index, tmp_path: Path):
    """The handle is drawn where there is something to reveal. A card already
    showing everything it has would answer a drag with nothing moving, which
    teaches a reader that the edge does not work rather than that this card has
    nothing more."""
    ids = _two_with_documents(index)
    page = _stubbed(render_table(index, ROUTES, base_commit=HEAD, may_write=True),
                    "<p>one line, and the whole of it.</p>")
    got = measured_in(chrome(), page, tmp_path / "short.html", 1200,
                      _SHORT % json.dumps(ids[0]))

    assert got["drawn"], "no document was drawn at all"
    assert not got["scrolls"], "the fixture's document did not fit the box"
    assert not got["gripped"], "a card with nothing to reveal drew a handle anyway"


# The one claim in this file a browser here cannot make. It is about Firefox, the
# suite drives Chrome, and the difference between them is the whole defect.
_PUT_BACK = re.compile(
    r"if \(!already\) CARD\.appendChild\(body\);"
    r"(?P<between>.*?)"
    r"void body\.scrollHeight;\s*\n\s*body\.scrollTop = 0;",
    re.S,
)


def test_the_document_is_put_back_to_the_top_after_the_layout_that_restores_it(index: Index):
    """`hidden` on the way out is `display: none`, which destroys the scroll frame
    the shaping document is read in. Chrome drops that frame's offset. Firefox
    SAVES it — keyed by where the box sits in the card rather than by the element,
    so a unique `id` does not change the key — and puts it back on the frame it
    builds for the next record's document. The element is new; the offset belongs
    to a document nobody has opened.

    So the order is the fix, and the order is what this asserts: appended, then
    the layout that applies Firefox's saved offset, then the reset behind it. The
    reset used to sit one line earlier, on an element that was not in the document
    yet, where it did nothing at all and Firefox had the last word — which is why
    jcanton saw this on 2026-09-03 in Firefox while every card in Chrome, driven
    over CDP against a running server, arrived at the top.

    Asserted of the shipped script because the browser that would notice is not
    the browser the suite drives. The behaviour itself — a card for another record
    starting at the top — is
    `test_a_card_for_another_record_starts_at_the_top_of_its_document`.
    """
    js = script(render_table(index, ROUTES, base_commit=HEAD, may_write=True))
    ordered = _PUT_BACK.search(js)

    assert ordered, "the document is not put back to the top after a layout it can be restored by"
    assert "scrollTop" not in ordered.group("between"), (
        "something scrolls the box between the append and the reset"
    )
    assert js.count("body.scrollTop = 0") == 1, (
        "a second reset: whichever runs last is the one that decides, and two of "
        "them is a decision nobody is making on purpose"
    )


# --------------------------------------------------------------------------- #
# The other engine
# --------------------------------------------------------------------------- #


# Hovering, leaving and looking, as three sandbox scripts: Marionette cannot wait
# and the page's own clocks are what is being waited for — 600ms of hover intent
# and 220ms of grace on the way out — so the waiting is done from Python between
# calls rather than inside the page.
_HOVER = """(() => {
  const cell = [...document.querySelectorAll('tbody tr[data-id] td[data-col="title"]')][%d];
  const box = cell.getBoundingClientRect();
  cell.dispatchEvent(new PointerEvent('pointerover',
    {bubbles: true, clientX: box.x + 20, clientY: box.y + 6}));
  return cell.closest('tr').dataset.id;
})()"""

_LEAVE = """(() => {
  const cell = [...document.querySelectorAll('tbody tr[data-id] td[data-col="title"]')][%d];
  cell.dispatchEvent(new PointerEvent('pointerout', {bubbles: true}));
  return true;
})()"""

_READ = """(() => {
  const card = document.getElementById('card');
  const body = card.querySelector('.card-body');
  const title = card.querySelector('.card-title');
  return {hidden: card.hidden, title: title ? title.textContent : '',
          top: body ? body.scrollTop : -1,
          room: body ? body.scrollHeight - body.clientHeight : -1};
})()"""

_TO_THE_END = """(() => {
  const body = document.querySelector('#card .card-body');
  body.scrollTop = 99999;
  return body.scrollTop;
})()"""


def test_another_record_starts_at_the_top_in_firefox_too(index: Index, tmp_path: Path):
    """The one claim in this file that Chrome cannot make, driven in the engine
    that could not keep it.

    `hidden` on the way out is `display: none`, which destroys the scroll frame
    the document is read in. Chrome drops that frame's offset; Firefox saves it,
    keyed by where the box sits in the card rather than by the element, and puts
    it back on the frame built there for the NEXT record's document. So this is
    the reported sequence exactly — read one pitch to its end, leave the row long
    enough for the card to go, hover another record — and the middle step is not
    decoration: without the hide there is nothing for Firefox to restore, and
    this passes against the defect.

    jcanton, Firefox, 2026-09-03, against a commit whose Chrome test was green.
    """
    page = _stubbed(render_table(index, ROUTES, base_commit=HEAD, may_write=True), LONG)
    with driving(page, tmp_path / "firefox.html") as browser:
        first = browser.js(_HOVER % 2)
        time.sleep(1.4)
        opened = browser.js(_READ)
        left = browser.js(_TO_THE_END)

        browser.js(_LEAVE % 2)
        time.sleep(0.8)
        between = browser.js(_READ)

        second = browser.js(_HOVER % 4)
        time.sleep(1.4)
        arrived = browser.js(_READ)

    assert opened["room"] > 0, "the first card's document was not long enough to scroll"
    assert left > 0, "the first card's document did not scroll at all"
    assert between["hidden"], (
        "the card never went away between the two rows, so nothing was ever saved "
        "and this test cannot see the defect it is written for"
    )
    assert first != second and arrived["title"] != opened["title"], "the same card twice"
    assert not arrived["hidden"] and arrived["room"] > 0, "no second card was drawn"
    assert arrived["top"] == 0, (
        f"the card for {second} opened {arrived['top']}px down a document nobody has read"
    )
