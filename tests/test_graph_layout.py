"""What the graph actually draws, measured in a browser.

This file exists because the page shipped looking like the screenshots jcanton
sent on 2026-08-20 — boxes lying across each other, cards inside groups they do
not belong to, one project's rectangle stretched to eight times its contents —
with a green suite. Everything asserted about the layout was a string in a
script: `'elk.hierarchyHandling': 'INCLUDE_CHILDREN'` was present, `packComponents`
was present, and the drawing was wrong.

So nothing here reads the source. Every number comes from cytoscape's own
geometry after the layout has run, on the seed corpus, in Chrome.

The three properties are the complaint itself:

  1. no two boxes overlap
  2. no card is drawn inside a box it does not belong to
  3. a record's children are near it rather than scattered

`containmentViolations` — a child geometrically outside its own parent — is
deliberately NOT among them. A compound's rectangle in cytoscape is derived from
where its children are, so that number is structurally zero for every layout
anybody could write, and a test asserting it would pass forever while proving
nothing.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import load_repo, unread_fields
from openproj.render import ROUTES, render_graph

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


# One pass over the finished drawing. Boxes and leaves are taken as arrays
# because a cytoscape collection is not iterable the way a browser's `for...of`
# wants, which is the sort of thing that turns a measurement into "the page
# reported nothing".
_GEOMETRY = """
const boxes = cy.nodes().filter(n => n.isParent()).toArray();
const leaves = cy.nodes().filter(n => n.isChildless()).toArray();
const rect = n => n.boundingBox({includeLabels: false});
const hits = (a, b) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;

// Two boxes overlap only if neither contains the other: a pitch's box inside its
// project's box is the drawing working, not failing.
const overlapping = [];
for (let i = 0; i < boxes.length; i++)
  for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.ancestors().anySame(b) || b.ancestors().anySame(a)) continue;
    if (hits(rect(a), rect(b))) overlapping.push(a.id() + ' x ' + b.id());
  }

const trespassing = [];
for (const leaf of leaves)
  for (const box of boxes) {
    if (leaf.ancestors().anySame(box)) continue;
    if (hits(rect(leaf), rect(box))) trespassing.push(leaf.id() + ' in ' + box.id());
  }

// How spread out one record's children are: the area their bounding box needs
// over the area they actually occupy. 1.0 is packed tight; 13 is what shipped.
let worst = 0, worstOf = null, total = 0, counted = 0;
for (const box of boxes) {
  const kids = box.children();
  if (kids.length < 2) continue;
  const bb = kids.boundingBox({includeLabels: false});
  let own = 0;
  kids.forEach(k => { const r = rect(k); own += (r.x2 - r.x1) * (r.y2 - r.y1); });
  if (!own) continue;
  const ratio = ((bb.x2 - bb.x1) * (bb.y2 - bb.y1)) / own;
  total += ratio; counted++;
  if (ratio > worst) { worst = ratio; worstOf = box.id(); }
}

// How many edges pass over a card that is neither of their two ends — and it is
// a COUNT and not a fault now. An edge is a straight line drawn beneath every
// box, so a line that crosses a card passes under it; the claim that used to be
// here ("no edge crosses a card") belonged to the router, and the claim that
// replaces it is `test_an_edge_that_crosses_a_card_is_drawn_under_it`, which
// reads pixels rather than geometry.
//
// Sampled along the straight line between the two ends rather than along the
// drawn path: a taxi edge turns once inside the same corridor, so the count is
// the same question asked more cheaply, and the arithmetic for a segment against
// a rectangle is where a measurement quietly starts measuring something else.
const crossesBox = (p, q, r) => {
  for (let i = 0; i <= 20; i++) {
    const x = p.x + (q.x - p.x) * i / 20, y = p.y + (q.y - p.y) * i / 20;
    if (x > r.x1 && x < r.x2 && y > r.y1 && y < r.y2) return true;
  }
  return false;
};
let under = 0;
cy.edges().forEach(edge => {
  const from = edge.source().position(), to = edge.target().position();
  for (const leaf of leaves) {
    // A card inside one of the two records an edge joins is not a card it is
    // crossing: cytoscape draws from the CENTRE of a box, so an edge attached to
    // a compound necessarily starts among its children. Only a stranger counts.
    if (leaf.same(edge.source()) || leaf.same(edge.target())) continue;
    if (leaf.ancestors().anySame(edge.source())) continue;
    if (leaf.ancestors().anySame(edge.target())) continue;
    if (crossesBox(from, to, rect(leaf))) { under++; break; }
  }
});

// Which way the arrows read. RIGHT is the direction asked of ELK, so a
// dependency whose source is right of its target is one drawn backwards.
let forward = 0, backward = 0;
cy.edges().forEach(e => {
  if (e.source().position().x <= e.target().position().x) forward++; else backward++;
});

return {
  boxes: boxes.length, leaves: leaves.length, edges: cy.edges().length, under,
  overlapping, trespassing,
  sparseWorst: +worst.toFixed(2), sparseWorstOf: worstOf,
  sparseMean: +(total / (counted || 1)).toFixed(2),
  forward, backward, zoom: +cy.zoom().toFixed(2),
};
"""


@pytest.fixture
def drawn(index: Index, tmp_path: Path) -> dict:
    page = render_graph(index, ROUTES, base_commit=HEAD)
    return measured_in(chrome(), page, tmp_path / "layout.html", 1900, _GEOMETRY,
                       height=820, patience=3500)


def test_the_corpus_is_worth_measuring(drawn: dict):
    """A plan with no boxes in it cannot fail any of the tests below, and would
    pass all of them silently the day somebody trimmed the demo corpus."""
    assert drawn["boxes"] >= 3, drawn
    assert drawn["leaves"] >= 5, drawn
    assert drawn["edges"] >= 1, drawn


def test_no_box_lies_across_another(drawn: dict):
    """The first thing wrong with the screenshots.

    Measured before and after `packComponents()` on the real plan: 0 overlapping
    pairs became 17 to 21. That function split the drawing by edge-connectivity
    and containment is deliberately not an edge here, so it took every group
    apart and each parent's rectangle — nothing but the bounding box of wherever
    its children landed — stretched across its neighbours.
    """
    assert drawn["overlapping"] == [], drawn["overlapping"]


def test_no_card_is_drawn_inside_a_group_it_does_not_belong_to(drawn: dict):
    """The second. A card sitting inside a box it has nothing to do with is the
    view lying about the one relationship it exists to show."""
    assert drawn["trespassing"] == [], drawn["trespassing"]


def test_a_records_children_are_drawn_near_it(drawn: dict):
    """The third: "nodes belonging to the same parent are not close to each
    other".

    The bound is generous on purpose. Grouping is the layout's primary objective
    BETWEEN boxes and still secondary INSIDE one, because a box lays its children
    out by their own dependencies — so siblings in a chain are genuinely spread,
    and that is the drawing being informative rather than being wrong. What is
    pinned is the order of magnitude: the shipped version measured 4.7 to 13.1
    and the recursive layout measures 1.3 to 2.2.
    """
    assert drawn["sparseMean"] < 2.5, drawn
    assert drawn["sparseWorst"] < 4, f"{drawn['sparseWorstOf']} is {drawn['sparseWorst']}x"


def test_the_arrows_read_the_way_the_layout_was_asked_for(drawn: dict):
    """`elk.direction: RIGHT`, so a dependency should point right.

    This one is also the canary for the ordering that ELK's recursive engine does
    NOT guarantee — see the queue entry about ghost edges. On this corpus it is
    6 of 6, and a plan shape exists where it would not be; if this ever fails on
    a corpus nobody touched, that is the thing to read.
    """
    assert drawn["backward"] == 0, f"{drawn['backward']} of {drawn['edges']} drawn backwards"


# A card dragged out of its box, and what happens to the box.
_DRAGGED = """
const leaf = cy.nodes().filter(n => n.isChildless() && n.parent().length)[0];
if (!leaf) return {error: 'no card has a box to be dragged out of'};
const box = leaf.parent();
const was = box.boundingBox({includeLabels: false});
// Copied. `position()` hands back a live object, so a "before" taken from it
// moves with the node and every measurement comes out zero.
const from = {...leaf.position()};

leaf.emit('grab');
leaf.position({x: from.x + 600, y: from.y + 400});
leaf.emit('dragfree');

return {
  moved: Math.round(leaf.position().x - from.x),
  grew: Math.round((box.boundingBox({includeLabels: false}).x2 - was.x2)),
  boxes: cy.nodes().filter(n => n.isParent()).length,
  grabbable: cy.nodes().filter(n => n.isParent() && n.grabbable()).length,
};
"""


def test_a_card_stays_where_it_was_dragged(index: Index, tmp_path: Path):
    """It used to be put back inside the box it came from, and the clamp is gone —
    jcanton, 2026-08-20, having watched it drop a card straight back onto the line
    it had been moved off: "let people drag".

    The clamp was there because a compound's rectangle follows its children, so a
    card dragged out stretches the box rather than leaving it. That is still true
    and is now the price: the alternative was an automatic layout that never puts
    a card on a line, and ELK cannot give one — it returns bend points for an edge
    whose obstacles are at the level it is working on, and none at all for one
    that spans the hierarchy, in each of its three routing modes.

    The clamp contributed nothing to the drawing you arrive at. It ran on
    `dragfree` and nowhere else, so the starting view is the layout alone.
    """
    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "drag.html", 1900, _DRAGGED,
                      height=820, patience=3500)

    assert not got.get("error"), got
    assert got["moved"] > 500, "the card was moved back"
    # And a box can be picked up too, which is how two boxes drawn over each other
    # get pulled apart.
    assert got["grabbable"] == got["boxes"], (
        f"{got['boxes'] - got['grabbable']} of {got['boxes']} boxes cannot be dragged"
    )


@pytest.fixture
def big(tmp_path: Path) -> Index:
    """A plan four times the size of the real one, built by `tests/plans.py`.

    31 records is not a test of a layout. Four projects of three pitches of three
    tasks is 52 records in sixteen boxes with twenty dependencies — chains inside
    the groups and edges across them, which is the shape that matters, because a
    flat plan of any size exercises none of what goes wrong.

    Modest on purpose: this runs a real browser. Bigger plans are one command
    away (`uv run python tests/plans.py /tmp/big 14 6 5`) and the numbers measured
    at 208 and 518 records are in the `LAYOUT` comment.
    """
    from plans import build

    root = tmp_path / "big"
    build(root, 4, 3, 3)
    records, config, _ = load_repo(root)
    return build_index(records, config, date(2026, 8, 17))


def test_the_grouping_holds_on_a_plan_larger_than_the_real_one(big: Index, tmp_path: Path):
    """Everything above, on a corpus the demo does not flatter.

    The defect this file was written for got worse the more containment there
    was, because a packer blind to boxes has more boxes to take apart — and the
    seed corpus has eight. Measured at 52, 208 and 518 records the recursive
    layout holds all three properties; what degrades with size is the zoom, not
    the correctness.
    """
    page = render_graph(big, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "big.html", 1900, _GEOMETRY,
                      height=820, patience=6000)

    assert got["boxes"] >= 12, f"the corpus is not the shape this test needs: {got}"
    assert got["overlapping"] == [], got["overlapping"][:6]
    assert got["trespassing"] == [], got["trespassing"][:6]
    assert got["sparseMean"] < 2.5, got


_KEYS = """
const rows = [...document.querySelectorAll('.keys .legend')];
const widths = rows.map(r => Math.round(r.getBoundingClientRect().width));
// The space between one key's word and the next key's swatch, on every row.
const gaps = [];
rows.forEach(row => {
  const items = [...row.querySelectorAll('li:not(.legendname)')];
  for (let i = 0; i < items.length - 1; i++) {
    const a = items[i].getBoundingClientRect(), b = items[i + 1].getBoundingClientRect();
    gaps.push(Math.round(b.left - a.right));
  }
});
// Every swatch on both rows, and where each key's word sits. Two rows of keys
// that are not the same height are two rows that cannot be level, which is what
// a 34x17 priority swatch beside a 20x11 status one did.
const swatches = [...document.querySelectorAll('.keys .legend .swatch')].map(one => {
  const r = one.getBoundingClientRect();
  return {w: +r.width.toFixed(1), h: +r.height.toFixed(1), cls: one.className,
          pri: one.classList.contains('pri')};
});
// The mark inside the thickest border. A 6px border on a 12px swatch leaves
// nothing in the middle, so this is the rung that tells a mark drawn ON the
// border from one drawn inside it.
const thickest = document.querySelector('.keys .swatch.pri-very_high .primark');
const meter = thickest ? thickest.getBoundingClientRect() : null;
const rowtops = rows.map(row => Math.round(
  row.querySelector('li:not(.legendname)').getBoundingClientRect().height));
// Where each key STARTS, per row. Two rows of keys that line up are two rows
// whose nth key has the same left edge; the gap between one key's word and the
// next key's mark is then whatever each column's wider word makes it, which is
// the point rather than a fault.
const columns = rows.map(row => [...row.querySelectorAll('li')]
  .map(one => Math.round(one.getBoundingClientRect().left)));
const box = document.querySelector('[data-fills]').getBoundingClientRect();
const keys = document.querySelector('.keys').getBoundingClientRect();
return {
  rows: rows.length, gaps, swatches, rowtops, columns,
  meter: meter && {w: Math.round(meter.width), h: Math.round(meter.height)},
  spread: widths.length ? Math.max(...widths) - Math.min(...widths) : -1,
  inside: keys.top >= box.top - 1 && keys.right <= box.right + 1,
  // Every card and every box, each with the rung it is on — because WHICH marks
  // a node wears is a fact about its kind and not about its position in this
  // list. `slice(0, 3)` was here and read the first three boxes, which is a
  // sample that says nothing about the fourth; the whole drawing is 26 nodes and
  // reading a style off each is cheaper than the layout that produced them.
  //
  // `title` is `data('label')` — what the record is called — while `label` is
  // what cytoscape draws, which is `labelOf()`'s work. Both, so the test can say
  // what a box's name is made of rather than only what it starts with.
  //
  // A card's label should be its title and nothing else: its marks are the
  // drawing in `image`. A box's are characters in its own name, because a
  // drawing cannot be put on a compound's line.
  marked: cy.nodes().filter(n => n.isChildless()).map(n => ({
    kind: n.data('kind'),
    title: (n.data('label') || '').replace(/\s+/g, ''),
    label: (n.style('label') || '').replace(/\s+/g, ''),
    image: String(n.style('background-image') || ''),
  })),
  boxed: cy.nodes().filter(n => n.isParent()).map(n => ({
    kind: n.data('kind'),
    title: (n.data('label') || '').replace(/\s+/g, ''),
    label: (n.style('label') || '').replace(/\s+/g, ''),
  })),
};
"""


def test_the_two_key_rows_are_one_length_and_sit_on_the_drawing(
    index: Index, tmp_path: Path
):
    """One gap between keys, and both rows anchored on the same edge.

    jcanton asked for the rows to be the same length, and then — having seen what
    that cost — for them not to be: "there is too much horizontal space between
    cards in the legend". Making them exactly equal means padding every key to the
    width of the widest word in either row, which put a hand's width of nothing
    between Done and Shelved. Two attempts did it by two routes, `min-width` on
    each key and a grid of equal columns, and both looked the same way.

    So a key is as wide as what is in it, the gap between keys is one number, and
    the rows line up on their right edge where the eye already is. What is pinned
    here is the gap, because that is the thing that was wrong.
    """
    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "keys.html", 1900, _KEYS,
                      height=820, patience=3500)

    assert got["rows"] == 2, "priority and status are two rows"
    # The two rows line up key for key. jcanton, three times about this legend,
    # most recently: "still wonky: not aligned (make it a table with two rows
    # maybe?)". It is one grid now, so this is the claim — the nth key of one row
    # starts where the nth key of the other does.
    assert len(got["columns"]) == 2 and len(got["columns"][0]) == len(got["columns"][1])
    off = [abs(a - b) for a, b in zip(*got["columns"], strict=True)]
    assert max(off) <= 1, f"the two rows are staggered by {max(off)}px: {got['columns']}"
    # And the space between keys stays the width of a word, not of a hand — which
    # is the fault the equal-width version of this had.
    assert max(got["gaps"]) <= 40, f"{max(got['gaps'])}px between keys is too much air"
    assert got["inside"], "the keys are not over the drawing"

    # One swatch, whichever row it is on. jcanton, 2026-08-20: "the legend is
    # again not vertically aligned and the boxes for priority are larger than
    # those for status" — which are one fault, because two rows of keys that are
    # not the same height cannot be level.
    sizes = {(one["w"], one["h"]) for one in got["swatches"]}
    assert len(sizes) == 1, (
        f"the two rows draw {len(sizes)} sizes of swatch: "
        f"{[(one['cls'], one['w'], one['h']) for one in got['swatches']]}"
    )
    assert len(set(got["rowtops"])) == 1, (
        f"the key rows are {got['rowtops']}px tall, so they cannot sit level"
    )
    # And the whole meter is drawn on the rung whose border would otherwise eat
    # it: 6px of border on an 11px swatch leaves nothing in the middle, so the
    # bars go over the border rather than inside it.
    assert got["meter"] and got["meter"]["h"] >= 8 and got["meter"]["w"] >= 5, (
        f"the very-high key has no room for its mark: {got['meter']}"
    )


def test_a_card_wears_both_its_marks_in_front_of_its_name(index: Index, tmp_path: Path):
    """Priority, then status, then the title — and each mark in its own colour.

    That last word is why they are a drawing rather than two characters in the
    label: cytoscape draws a label into a canvas with ONE `color` for the whole
    string, so two differently-coloured marks cannot be written into it. An SVG
    holds two `<text>` elements and two fills, which is the same two characters
    `PRIORITY_GLYPH` and `STATUS_GLYPH` put in a chip, a menu and a legend key,
    with the colour the table gives them.

    A box gets them as characters in its own name instead, uncoloured: a
    compound's label sits on the box's top edge with an opaque background, and an
    image placed in a compound's rectangle is positioned against the rectangle —
    it lands in the corner, under the name and clipped by the box's radius.

    *Which* marks a node wears is off the ladder in `model.py`, not a constant
    here: a product reads neither priority nor status — both are in
    `unread_fields("product")`, and `_row` nulls them — so it has no mark to
    wear and its name is its title alone. This asserted that every box leads
    with a priority glyph, and passed for a year because every kind that could
    be a box happened to read one; the corpus grew a product on 2026-08-23 and
    the first box measured was `kiln4py`, whose label starts `ki`. The record is
    right and the assertion was over-claiming.
    """
    from openproj.render import PRIORITY_GLYPH, STATUS_GLYPH

    def marks_of(kind: str) -> tuple[bool, bool]:
        """Whether this rung reads a priority and a status, off the ladder."""
        unread = unread_fields(kind)
        return "priority" not in unread, "status" not in unread

    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "marks.html", 1900, _KEYS,
                      height=820, patience=3500)

    assert got["marked"], "no card was measured"
    for card in got["marked"]:
        pri, stat = marks_of(card["kind"])
        # Whatever it wears, it does not write it into the label: the label is
        # the title, and only the title.
        assert card["label"] == card["title"], (
            f"a {card['kind']} card's label is {card['label']!r} and its title is "
            f"{card['title']!r}, so it is writing its marks into the name again"
        )
        drawn = unquote(card["image"]) if card["image"] and card["image"] != "none" else ""
        if drawn:
            assert card["image"].startswith("data:image/svg+xml"), card["image"][:40]
        # One `<text>` per mark the rung actually reads — so a card of a kind
        # that reads neither draws no marks rather than two invented ones.
        assert drawn.count("<text") == pri + stat, (
            f"a {card['kind']} card draws {drawn.count('<text')} marks and its rung "
            f"reads {pri + stat}: {drawn or '(no drawing)'}"
        )
        assert any(one in drawn for one in PRIORITY_GLYPH.values()) == pri, drawn
        assert any(one in drawn for one in STATUS_GLYPH.values()) == stat, drawn
        # A fill each, and no two marks sharing one: the point of the drawing is
        # that the marks are coloured apart from each other, which is the whole
        # reason they are an SVG instead of two characters in the label.
        fills = set(re.findall(r'fill="([^"]+)"', drawn))
        assert len(fills) == pri + stat, (
            f"a {card['kind']} card's {pri + stat} marks resolve to {sorted(fills)}"
        )
    # Both branches of that rule were asked, or the loop above proves only that
    # the corpus is uniform. Every earlier version of this test measured five
    # cards off the top of one list and could not have said which kinds it saw.
    assert any(marks_of(card["kind"]) == (True, True) for card in got["marked"]), (
        "no card of a kind that reads both marks was measured"
    )

    # And a box says the same things in its own name, where a drawing cannot go.
    # Read off the label, which for a compound is what carries them.
    assert got["boxed"], "no box was measured"
    for box in got["boxed"]:
        pri, stat = marks_of(box["kind"])
        if pri:
            assert box["label"][0] in PRIORITY_GLYPH.values(), (
                f"a {box['kind']} box does not lead with its priority mark: {box['label']!r}"
            )
        if stat:
            assert box["label"][pri] in STATUS_GLYPH.values(), (
                f"a {box['kind']} box does not carry its status glyph: {box['label']!r}"
            )
        if not pri and not stat:
            # No mark to write, so nothing is written: the box's name is the
            # record's name. A glyph here would be a priority somebody would
            # then try to change.
            assert box["label"] == box["title"], (
                f"a {box['kind']} box reads neither mark and is labelled "
                f"{box['label']!r} over a title of {box['title']!r}"
            )
    assert any(marks_of(box["kind"]) == (True, True) for box in got["boxed"]), (
        "no box of a kind that reads both marks was measured"
    )
    assert any(marks_of(box["kind"]) == (False, False) for box in got["boxed"]), (
        "no box of a kind that reads neither mark is on this graph, so the rule "
        "that such a box is named by its title alone is untested"
    )


_UNDERNEATH = """
// Where an edge crosses a card it has nothing to do with, what is on top?
//
// Read off the drawing itself rather than from a style value: `cy.png()`
// composites the three canvases cytoscape paints on, and the pixel at a crossing
// is the answer to the only question worth asking — a reader looking at that
// point sees either the card or a line through it.
const cards = cy.nodes().filter(n => n.isChildless());
const rect = n => n.boundingBox({includeLabels: false});
const spots = [];
cy.edges().forEach(edge => {
  const a = edge.source().position(), b = edge.target().position();
  cards.forEach(card => {
    if (card.same(edge.source()) || card.same(edge.target())) return;
    if (card.ancestors().anySame(edge.source())) return;
    if (card.ancestors().anySame(edge.target())) return;
    const r = rect(card);
    // Walk the line and keep the points that fall well inside the card, away
    // from its border and from its own text: a pixel on the border is the
    // border's, and one under the title is the label's.
    const inset = 10;
    for (let i = 1; i < 40; i++) {
      const x = a.x + (b.x - a.x) * i / 40, y = a.y + (b.y - a.y) * i / 40;
      if (x > r.x1 + inset && x < r.x2 - inset && y > r.y1 + inset && y < r.y2 - inset) {
        // Model coordinates to rendered ones, which is what a pixel is in.
        const p = {x: x * cy.zoom() + cy.pan().x, y: y * cy.zoom() + cy.pan().y};
        spots.push({card: card.id(), edge: edge.source().id() + '->' + edge.target().id(),
                    x: p.x, y: p.y, fill: card.style('background-color')});
      }
    }
  });
});

const line = cy.edges()[0] ? cy.edges()[0].style('line-color') : 'rgb(0,0,0)';
const rgb = value => {
  const m = String(value).match(/(\d+(?:\.\d+)?)/g) || [];
  return [Math.round(+m[0] || 0), Math.round(+m[1] || 0), Math.round(+m[2] || 0)];
};
const near = (one, two, slack) =>
  Math.abs(one[0] - two[0]) <= slack && Math.abs(one[1] - two[1]) <= slack
  && Math.abs(one[2] - two[2]) <= slack;

// The composite, read back through an image because that is the only way to get
// every layer's pixel at once. Answered from the continuation: the harness lets
// the second write of `data-report` win.
const url = cy.png({output: 'base64uri', full: false, scale: 1});
const img = new Image();
img.onload = () => {
  const sheet = document.createElement('canvas');
  sheet.width = img.width; sheet.height = img.height;
  const ink = sheet.getContext('2d', {willReadFrequently: true});
  ink.drawImage(img, 0, 0);
  // `cy.png()` is the canvas at device pixels; the spots are in CSS pixels.
  const scale = img.width / cy.container().clientWidth;
  const inked = [];
  for (const spot of spots.slice(0, 400)) {
    const x = Math.round(spot.x * scale), y = Math.round(spot.y * scale);
    if (x < 1 || y < 1 || x >= img.width - 1 || y >= img.height - 1) continue;
    const px = [...ink.getImageData(x, y, 1, 1).data].slice(0, 3);
    if (near(px, rgb(line), 24)) inked.push(`${spot.edge} shows through ${spot.card}`);
  }
  document.body.dataset.report = JSON.stringify(
    {spots: spots.length, sampled: Math.min(spots.length, 400), inked: inked.slice(0, 5),
     line: rgb(line), size: [img.width, img.height]});
};
img.src = url;
return {pending: true};
"""


def test_an_edge_that_crosses_a_card_is_drawn_under_it(big: Index, tmp_path: Path):
    """The whole design of the drawing, in one measurement.

    The edges turn at right angles — cytoscape's `round-taxi`, not a route of
    ours — and they are painted beneath every box, so an edge that passes over a
    card passes UNDER it. That is what replaced the router; jcanton, 2026-08-21,
    asked first for "straight edges drawn underneath the nodes. simplifies
    everything, removes our own edge drawing", then picked the rounded right
    angle off a gallery of every curve style on the real plan. Both halves of
    that are the same simplification: the shape is the library's either way.

    Read off the composited canvas rather than off a style value, because
    `z-compound-depth: bottom` in the stylesheet is a claim about what cytoscape
    will do and this is what it did: at every point where a line passes well
    inside a card that is not one of its ends, the pixel is the card's, not the
    line's.
    """
    # The generated plan and not the seed corpus: the demo is small enough that no
    # line passes inside a card it is unrelated to, so it cannot answer this.
    page = render_graph(big, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "under.html", 1900, _UNDERNEATH,
                      height=820, patience=4000)

    assert got.get("spots", 0) > 0, (
        "no edge on this corpus passes inside a card it is unrelated to, so this "
        f"measures nothing: {got}"
    )
    assert got["inked"] == [], (
        f"an edge is painted over a card instead of under it: {got['inked']}"
    )


def test_two_boxes_that_wait_on_each_other_are_ranked_by_the_majority(tmp_path: Path):
    """A cycle in the ghosts is not a cycle in the plan.

    Two projects can each hold work waiting on the other with nothing circular
    about any single record — legal, common, and the one shape no arrangement of
    two boxes on a line can express. ELK cannot rank both directions, so it used
    to break one arbitrarily: measured on a generated plan of 518 records, two
    arrows came out backwards between one such pair, which had two dependencies
    running one way and one the other.

    The weaker direction is now dropped before ELK sees it, so the majority ranks
    correctly and only the minority reads backwards. That last one is honest:
    those records really are waiting on each other.
    """
    from plans import build

    root = tmp_path / "mutual"
    # Without the generator's own edges between boxes: this test writes the pair
    # it is about, and a project waiting on a project elsewhere is one more
    # constraint on the same ranking than it asked for.
    build(root, 4, 3, 3, box_deps=False)

    records, config, _ = load_repo(root)
    index = build_index(records, config, date(2026, 8, 17))
    projects = sorted(e for e, one in index.plan.items() if one.kind == "project")
    under = {
        project: sorted(
            e for e, one in index.plan.items()
            if one.kind == "pitch" and one.parent == project
        )
        for project in projects
    }
    left = under[projects[0]]
    right = under[projects[1]]
    assert len(left) >= 2 and len(right) >= 2, "the corpus is not the shape this needs"

    def waits(record_id: str, on: str) -> None:
        """Add one dependency, keeping whatever the generator already wrote."""
        path = next(root.glob(f"*/{record_id}.md"))
        text = path.read_text()
        if "depends_on:" in text:
            text = text.replace("depends_on: [", f"depends_on: [{on}, ", 1)
        else:
            text = text.replace("---\n\n", f"depends_on: [{on}]\n---\n\n", 1)
        path.write_text(text)

    # Two dependencies from the second project's work to the first's, and one back
    # the other way: a mutual pair whose majority direction is unambiguous.
    waits(right[0], left[0])
    waits(right[1], left[1])
    waits(left[0], right[0])

    records, config, _ = load_repo(root)
    index = build_index(records, config, date(2026, 8, 17))
    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "mutual.html", 1900, _GEOMETRY,
                      height=820, patience=3500)

    # One arrow may read backwards — the minority — and no more. Broken
    # arbitrarily it was two of three; ranked by weight it is one of three.
    assert got["backward"] <= 1, (
        f"{got['backward']} arrows read backwards where at most the minority "
        "direction should"
    )
    assert got["overlapping"] == [], got["overlapping"][:4]
