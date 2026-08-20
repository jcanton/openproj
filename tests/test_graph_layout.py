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

// Which way the arrows read. RIGHT is the direction asked of ELK, so a
// dependency whose source is right of its target is one drawn backwards.
let forward = 0, backward = 0;
cy.edges().forEach(e => {
  if (e.source().position().x <= e.target().position().x) forward++; else backward++;
});

return {
  boxes: boxes.length, leaves: leaves.length, edges: cy.edges().length,
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


# A card dragged out of its box, which is the half of the complaint that no
# layout choice touches: a compound's rectangle follows its children, so a card
# dragged away does not leave its box, it stretches it.
_DRAGGED = """
const leaf = cy.nodes().filter(n => n.isChildless() && n.parent().length)[0];
if (!leaf) return {error: 'no card has a box to be dragged out of'};
const box = leaf.parent();
const was = box.boundingBox({includeLabels: false});
const from = leaf.position();

leaf.emit('grab');
leaf.position({x: from.x + 600, y: from.y + 400});
leaf.emit('dragfree');

const now = box.boundingBox({includeLabels: false});
return {
  grew: Math.round((now.x2 - now.x1) - (was.x2 - was.x1)),
  taller: Math.round((now.y2 - now.y1) - (was.y2 - was.y1)),
  boxes: cy.nodes().filter(n => n.isParent()).length,
  grabbable: cy.nodes().filter(n => n.isParent() && n.grabbable()).length,
};
"""


def test_a_card_dragged_out_of_its_box_goes_back_into_it(index: Index, tmp_path: Path):
    """Complaint 3, and it survives every layout: "dragging makes this even much
    worse".

    Measured on a clean layout, one card dragged 250x120 took the drawing from 0
    overlapping pairs to 2 and 0 trespasses to 5 — correct until somebody touched
    it. The card is put back rather than the layout re-run: ELK ignores current
    positions and is deterministic, so a re-run would move every card back to
    where it already was and the drag would simply vanish, which is a stranger
    thing to watch than a card sliding home.
    """
    page = render_graph(index, ROUTES, base_commit=HEAD)
    got = measured_in(chrome(), page, tmp_path / "drag.html", 1900, _DRAGGED,
                      height=820, patience=3500)

    assert not got.get("error"), got
    assert got["grew"] <= 1 and got["taller"] <= 1, (
        f"one drag stretched the box by {got['grew']}x{got['taller']}px"
    )
    # And a box cannot be picked up at all: cytoscape moves a parent rigidly with
    # its whole subtree, so nothing stretches — but nothing stops it being shoved
    # across its neighbours either, and nothing re-lays-out afterwards.
    assert got["grabbable"] == 0, f"{got['grabbable']} of {got['boxes']} boxes can be dragged"


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
    assert got["overlapping"] == [], got["overlapping"][:6]
    assert got["trespassing"] == [], got["trespassing"][:6]
    assert got["sparseMean"] < 2.5, got
