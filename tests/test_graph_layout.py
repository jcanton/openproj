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

from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import ROUTES, render_graph

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    entities, config, _ = load_repo(demo_root)
    return build_index(entities, config, date(2026, 8, 17))


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

// How many edges cross a card that is neither of their two ends. The measurement
// the routing work in `docs/QUEUE.md` has to beat, and the reason it is worth
// having before that work starts: without a number, "the graph looks better" is
// the only thing anybody can say about it.
//
// Reconstructed from the bend points, which IS the drawn path when the curve
// style is `segments`, and from the two ends when it is not. Sampled along each
// leg rather than solved, because the arithmetic for a segment against a
// rectangle is where a measurement quietly starts measuring something else.
const crossesBox = (p, q, r) => {
  for (let i = 0; i <= 20; i++) {
    const x = p.x + (q.x - p.x) * i / 20, y = p.y + (q.y - p.y) * i / 20;
    if (x > r.x1 && x < r.x2 && y > r.y1 && y < r.y2) return true;
  }
  return false;
};
function pathOf(edge) {
  const from = edge.source().position(), to = edge.target().position();
  const path = [from];
  if (edge.style('curve-style') === 'segments') {
    // Split on commas as well as spaces: the value goes in as a string and comes
    // back parsed, so `String(...)` of it is comma-joined — and a whitespace
    // split then yields one token, every routed edge measures as a straight
    // line, and the number this whole probe exists to report is wrong in the
    // reassuring direction.
    // `parseFloat` and not `Number`: cytoscape hands the distances back with
    // their units on — "47px 5.8px" — and `Number('47px')` is NaN, which the
    // guard below then skips. Every routed edge measured as a straight line and
    // this probe reported the drawing was no better than before it was routed.
    const split = v => String(v || '').trim().split(/[\s,]+/).filter(Boolean).map(parseFloat);
    const ws = split(edge.style('segment-weights'));
    const ds = split(edge.style('segment-distances'));
    const dx = to.x - from.x, dy = to.y - from.y, span = Math.hypot(dx, dy) || 1;
    ws.forEach((w, i) => {
      if (!isFinite(w) || !isFinite(ds[i])) return;
      path.push({x: from.x + dx * w + (dy / span) * ds[i],
                 y: from.y + dy * w - (dx / span) * ds[i]});
    });
  }
  path.push(to);
  return path;
}

let under = 0;
cy.edges().forEach(edge => {
  const path = pathOf(edge);
  for (const leaf of leaves) {
    // A card inside one of the two records an edge joins is not a card it is
    // crossing: cytoscape draws from the CENTRE of a box, so an edge attached to
    // a compound necessarily starts among its children. Only a stranger counts.
    if (leaf.same(edge.source()) || leaf.same(edge.target())) continue;
    if (leaf.ancestors().anySame(edge.source())) continue;
    if (leaf.ancestors().anySame(edge.target())) continue;
    const r = rect(leaf);
    let hit = false;
    for (let i = 0; i < path.length - 1 && !hit; i++) hit = crossesBox(path[i], path[i + 1], r);
    if (hit) { under++; break; }
  }
});

// Whether the drawing is orthogonal, which is the thing the router exists to
// make it. Every leg of a routed edge should run along one axis; a leg that runs
// along neither is a diagonal, and a long one is the zig-zag across the canvas
// jcanton photographed on 2026-08-20.
//
// EVERY leg, the two ends included. They were exempt, on the grounds that
// cytoscape draws from a node's CENTRE — which was true, and was the reason the
// ends leaned: a card's centre is 22px from its border and the stub is a
// rounding error, while a project's box is hundreds of pixels wide and the stub
// is a long diagonal across it and out the side. The endpoints are the route's
// own anchors now (`drawRoutes`), so a leaning end is a defect like any other.
let diagonal = 0, legs = 0, longest = 0, longestOf = null;
cy.edges().forEach(edge => {
  const path = pathOf(edge);
  if (path.length < 3) return;          // nothing was routed
  for (let i = 0; i < path.length - 1; i++) {
    const dx = Math.abs(path[i + 1].x - path[i].x), dy = Math.abs(path[i + 1].y - path[i].y);
    legs++;
    if (dx > 1.5 && dy > 1.5) {
      diagonal++;
      const len = Math.hypot(dx, dy);
      if (len > longest) { longest = len; longestOf = edge.id(); }
    }
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
  diagonal, legs, longest: Math.round(longest), longestOf,
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
    entities, config, _ = load_repo(root)
    return build_index(entities, config, date(2026, 8, 17))


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
    # Including the ends, which is where the leaning was: this corpus has
    # dependencies between the boxes themselves, and a compound's centre is
    # nowhere near the side a route leaves from.
    assert got["legs"] > 0 and got["diagonal"] == 0, (
        f"{got['diagonal']} of {got['legs']} legs run along neither axis, the "
        f"longest {got['longest']}px on {got['longestOf']}"
    )
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
// The meter drawn over the thickest border. Inside a 6px border on an 11px box
// there is nothing left to draw in, so this is the rung that tells the two
// arrangements apart.
const thickest = document.querySelector('.keys .swatch.pri-very_high .bars');
const meter = thickest ? thickest.getBoundingClientRect() : null;
const rowtops = rows.map(row => Math.round(
  row.querySelector('li:not(.legendname)').getBoundingClientRect().height));
const box = document.querySelector('[data-fills]').getBoundingClientRect();
const keys = document.querySelector('.keys').getBoundingClientRect();
return {
  rows: rows.length, gaps, swatches, rowtops,
  meter: meter && {w: Math.round(meter.width), h: Math.round(meter.height)},
  spread: widths.length ? Math.max(...widths) - Math.min(...widths) : -1,
  inside: keys.top >= box.top - 1 && keys.right <= box.right + 1,
  marked: cy.nodes().filter(n => n.isChildless()).slice(0, 5)
    .map(n => (n.style('label') || '').slice(0, 2)),
  meters: cy.nodes().filter(n => n.isChildless()).slice(0, 3)
    .map(n => decodeURIComponent(String(n.style('background-image') || ''))
      .replace(/^url\(["']?|["']?\)$/g, '')),
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
    assert len(set(got["gaps"])) == 1, (
        f"the keys are spaced {sorted(set(got['gaps']))} apart, which is not one gap"
    )
    assert got["gaps"][0] <= 20, f"{got['gaps'][0]}px between keys is a hand's width"
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
    assert got["meter"] and got["meter"]["h"] >= 8 and got["meter"]["w"] >= 15, (
        f"the very-high key has no room for its meter: {got['meter']}"
    )


def test_every_card_carries_its_priority_as_a_picture(index: Index, tmp_path: Path):
    """The channel priority is drawn with here is the border's THICKNESS, which is
    legible only against a neighbour to compare it against — jcanton saw one
    project drawn thicker and had to ask what it meant. So the card carries the
    same five-bar meter the legend and the table draw.

    As an image and NOT as a character in the label, which is what shipped first
    and what jcanton saw: cytoscape draws a label into a canvas with the font it
    is given and no fallback chain, and Inter has no Block Elements — so the rung
    came out as a .notdef box in front of every node's name. A mark that depends
    on the typeface having a glyph is a mark that fails silently on somebody
    else's machine, and a canvas is where that failure is invisible to CSS.

    The status glyph stays in the label, where it has always been: those five are
    characters every typeface has.
    """
    from openproj.render import STATUS_GLYPH

    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "marks.html", 1900, _KEYS,
                      height=820, patience=3500)

    assert got["marked"], "no node was measured"
    for prefix in got["marked"]:
        assert prefix[0] in STATUS_GLYPH.values(), (
            f"{prefix!r} does not start with a status glyph"
        )
    assert got["meters"], "no card carries a priority meter"
    for image in got["meters"]:
        assert image.startswith("data:image/svg+xml"), image[:40]
        assert "rect" in image, "the meter has no bars in it"


def test_no_edge_crosses_a_card_it_has_nothing_to_do_with(drawn: dict):
    """Zero, and it is reachable — which it was not before the router.

    ELK returns bend points for none of the edges that span the hierarchy, in any
    of its three routing modes, because at the level ELK works the route between
    two boxes genuinely is unobstructed: the cards it appears to cross are inside
    other boxes. So `routeEdges` routes them here, over the absolute positions ELK
    produces, which is where the obstacles are. Measured at 1900x820 it went from
    4 / 13 / 43 at 31 / 208 / 518 records to 0 at all three.

    An edge the router cannot find a way for keeps cytoscape's taxi router and may
    cross something, which is why this could fail on a plan shaped in a way nobody
    has seen. If it does, the fallback is working as intended and the router is
    what needs looking at.
    """
    assert drawn["under"] == 0, (
        f"{drawn['under']} of {drawn['edges']} edges cross a card they are not "
        "attached to"
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

    entities, config, _ = load_repo(root)
    index = build_index(entities, config, date(2026, 8, 17))
    projects = sorted(e for e, one in index.entities.items() if one.kind == "project")
    under = {
        project: sorted(
            e for e, one in index.entities.items()
            if one.kind == "pitch" and one.parent == project
        )
        for project in projects
    }
    left = under[projects[0]]
    right = under[projects[1]]
    assert len(left) >= 2 and len(right) >= 2, "the corpus is not the shape this needs"

    def waits(entity_id: str, on: str) -> None:
        """Add one dependency, keeping whatever the generator already wrote."""
        path = next(root.glob(f"*/{entity_id}.md"))
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

    entities, config, _ = load_repo(root)
    index = build_index(entities, config, date(2026, 8, 17))
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


def test_every_routed_edge_runs_along_an_axis(drawn: dict):
    """The router draws right angles or it is not routing.

    jcanton, 2026-08-20, with a screenshot of the deployed graph: long diagonal
    zig-zags leaning across the canvas between the groups. A diagonal is not a
    worse-looking orthogonal route, it is a route that was never followed — the
    bends are being placed somewhere other than where the path went.

    The two stubs are exempt because cytoscape draws from a node's centre to the
    first bend, so the leg leaving a box is diagonal however well the middle is
    routed. Everything between them is the router's own work.
    """
    assert drawn["legs"] > 0, "no edge has a middle, so this measures nothing"
    assert drawn["diagonal"] == 0, (
        f"{drawn['diagonal']} of {drawn['legs']} legs run along neither axis, the "
        f"longest {drawn['longest']}px on {drawn['longestOf']}"
    )


_SHEAR = """
const split = v => String(v || '').trim().split(/[\\s,]+/).filter(Boolean).map(parseFloat);
function pathOf(edge) {
  const from = edge.source().position(), to = edge.target().position();
  const path = [from];
  if (edge.style('curve-style') === 'segments') {
    const ws = split(edge.style('segment-weights')), ds = split(edge.style('segment-distances'));
    const dx = to.x - from.x, dy = to.y - from.y, span = Math.hypot(dx, dy) || 1;
    ws.forEach((w, i) => { if (isFinite(w) && isFinite(ds[i]))
      path.push({x: from.x + dx * w + (dy / span) * ds[i],
                 y: from.y + dy * w - (dx / span) * ds[i]}); });
  }
  path.push(to);
  return path;
}
function diagonals() {
  let diagonal = 0, legs = 0, longest = 0;
  cy.edges().forEach(edge => {
    const path = pathOf(edge);
    if (path.length < 4) return;
    for (let i = 1; i < path.length - 2; i++) {
      const dx = Math.abs(path[i + 1].x - path[i].x), dy = Math.abs(path[i + 1].y - path[i].y);
      legs++;
      if (dx > 1.5 && dy > 1.5) { diagonal++; longest = Math.max(longest, Math.hypot(dx, dy)); }
    }
  });
  return {diagonal, legs, longest: Math.round(longest)};
}

const before = diagonals();
// Moved by hand rather than dragged, and that is the point: `dragfree` was the
// only thing that re-routed, so every other way a node moves left the routes
// behind. A box carried by its parent, a filter putting cards back, a restored
// position and a re-fit are all this line.
const leaf = cy.nodes().filter(n => n.isChildless() && n.connectedEdges().length)[0];
leaf.position({x: leaf.position().x + 260, y: leaf.position().y - 190});
// Answered from a continuation: the second write of `data-report` wins, and a
// measurement taken in the same tick as the move is a measurement of the shear
// rather than of what the page settles on.
setTimeout(() => {
  document.body.dataset.report = JSON.stringify(
    {before, after: diagonals(), moved: leaf.id()});
}, 300);
return {pending: true};
"""


def test_a_node_that_moves_takes_its_routes_with_it_and_they_are_re_laid(
    index: Index, tmp_path: Path
):
    """The zig-zags jcanton photographed on 2026-08-20, and where they come from.

    A `segments` edge holds its bends as a distance from the line between its two
    ends and a fraction along it. Move an end and that line turns; the bends turn
    with it, and two right angles arrive on screen as two diagonals leaning across
    the canvas. Nothing is wrong with the route — it is a correct route measured
    against a line that no longer exists.

    The initial view was never the problem: this same probe reports zero diagonal
    legs at 31, 54 and 518 records. What was missing is that only `dragfree`
    re-routed, so the drawing was correct until anything moved a node by any other
    means.
    """
    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "shear.html", 1900, _SHEAR,
                      height=820, patience=2500)

    assert got.get("before", {}).get("legs"), f"nothing was routed to begin with: {got}"
    assert got["before"]["diagonal"] == 0, got["before"]
    assert got["after"]["diagonal"] == 0, (
        f"moving {got['moved']} left {got['after']['diagonal']} sheared legs, the "
        f"longest {got['after']['longest']}px"
    )
