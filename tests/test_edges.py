"""Drawing a dependency, and taking one away.

Edit mode could only add. "What waits for what is wrong on this diagram" is one
job, and a mode that could only do half of it was a mode you had to leave — and
open a record — to finish the thought.

Both halves are grouped by the record that WAITS, because that is the record
`depends_on` is stored on: an edge removed is a line taken out of the dependent's
own file, exactly as an edge added is one put in.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import Config, Issue, Task, load_repo
from openproj.render import ROUTES, render_graph

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


@pytest.fixture
def page(index: Index) -> str:
    return render_graph(index, ROUTES, base_commit=HEAD)


def a_dependency(index: Index) -> tuple[str, str]:
    """One edge the plan already has, as (waits, first)."""
    for record_id, blockers in sorted(index.blocked_by.items()):
        if blockers:
            return record_id, blockers[0]
    raise AssertionError("the corpus has no dependency to remove")


# The request is recorded when it is made and never answered: a successful Save
# ends in `location.reload()`, which cannot be stubbed and would take the page
# and the report with it.
_REMOVE = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
document.getElementById('connect').click();
const edge = cy.edges().filter(one =>
  one.source().id() === %s && one.target().id() === %s)[0];
edge.emit('tap');
const marked = edge.hasClass('dropping');
const said = document.getElementById('state').textContent;
const canSave = !document.getElementById('save').disabled;
document.getElementById('save').click();
return {marked, said, canSave, wrote: window.__wrote};
"""


def test_an_existing_dependency_can_be_taken_off_the_diagram(
    index: Index, page: str, tmp_path: Path
):
    """Click the arrow, press Save. What goes to the server is the dependent's
    whole `depends_on` without that one in it — a PATCH of a list replaces it, and
    there is no "and also remove this" on the wire."""
    waits, first = a_dependency(index)
    got = measured_in(
        chrome(), page, tmp_path / "remove.html", 1400,
        _REMOVE % (json.dumps(first), json.dumps(waits)), height=1000,
    )

    assert got["marked"], "the arrow was clicked and nothing was marked"
    assert "will be removed" in got["said"]
    assert got["canSave"], "a diagram with a removal on it could not be saved"
    assert [call["url"] for call in got["wrote"]] == [f"/api/record/{waits}"]

    sent = got["wrote"][0]["body"]["fields"]["depends_on"]
    assert first not in sent, f"{first} is still in what was sent"
    assert sorted(sent) == sorted(set(index.blocked_by[waits]) - {first})


_UNDRAW = """
document.getElementById('connect').click();
const [one, two] = cy.nodes().filter(node => node.isChildless()).slice(0, 2);
one.emit('tap');
two.emit('tap');
const drawn = cy.edges('.pending').length;
cy.edges('.pending')[0].emit('tap');
return {drawn, after: cy.edges('.pending').length,
        said: document.getElementById('state').textContent,
        canSave: !document.getElementById('save').disabled};
"""


def test_an_edge_drawn_by_mistake_is_simply_undrawn(page: str, tmp_path: Path):
    """A dependency drawn in this session and not saved has nothing to remove
    from any file, so clicking it takes it off the canvas rather than marking it.
    Two states for two different things."""
    got = measured_in(chrome(), page, tmp_path / "undraw.html", 1400, _UNDRAW, height=1000)

    assert got["drawn"] == 1, "no edge was drawn, so nothing was undrawn"
    assert got["after"] == 0
    assert got["said"].startswith("undrawn")
    assert got["canSave"] is False, "an empty diagram offered to commit itself"


_RESET = """
document.getElementById('connect').click();
const edge = cy.edges().filter(one =>
  one.source().id() === %s && one.target().id() === %s)[0];
edge.emit('tap');
const marked = cy.edges('.dropping').length;
document.getElementById('discard').click();
const afterReset = cy.edges('.dropping').length;
edge.emit('tap');
document.getElementById('connect').click();
return {marked, afterReset, afterLeaving: cy.edges('.dropping').length,
        stillThere: cy.edges().filter(one =>
          one.source().id() === %s && one.target().id() === %s).length};
"""


def test_reset_and_leaving_the_mode_both_put_a_marked_edge_back(
    index: Index, page: str, tmp_path: Path
):
    """Nothing has happened until Save, so both ways out have to be able to say
    so — and the edge is still on the diagram either way, because it is still in
    the plan."""
    waits, first = a_dependency(index)
    got = measured_in(
        chrome(), page, tmp_path / "reset.html", 1400,
        _RESET % (json.dumps(first), json.dumps(waits), json.dumps(first), json.dumps(waits)),
        height=1000,
    )

    assert got["marked"] == 1
    assert got["afterReset"] == 0, "Reset left an edge marked for removal"
    assert got["afterLeaving"] == 0, "leaving the mode left an edge marked for removal"
    assert got["stillThere"] == 1, "an edge nobody committed came off the diagram"


_OFF_PLAN = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url});
  return new Promise(() => {});
};
document.getElementById('connect').click();
// Adding: pick a blocker, then tap the record whose stored field the canvas
// cannot fully see.
cy.getElementById('task-cc0001').emit('tap');
cy.getElementById('task-aa0001').emit('tap');
const refusedAdd = document.getElementById('state').textContent;
const drawn = cy.edges('.pending').length;
// Removing: tap the one stored edge the canvas does draw into that record.
const edge = cy.edges().filter(one =>
  one.source().id() === 'task-bb0001' && one.target().id() === 'task-aa0001')[0];
edge.emit('tap');
const marked = edge.hasClass('dropping');
// The same sentence twice in a row goes through announce()'s repeat trick —
// cleared, then re-set on a zero timer so the live region speaks again — so
// the read has to wait a tick.
await new Promise(go => setTimeout(go, 30));
const refusedDrop = document.getElementById('state').textContent;
// And the same gestures on a record the canvas sees whole still work.
cy.getElementById('task-cc0001').emit('tap');
cy.getElementById('task-bb0001').emit('tap');
return {refusedAdd, drawn, marked, refusedDrop,
        drawnOk: cy.edges('.pending').length,
        canSave: !document.getElementById('save').disabled,
        wrote: window.__wrote};
"""


@pytest.fixture
def hand_index() -> Index:
    """A plan where one task's stored `depends_on` also names an issue — the
    hand-written edge the canvas cannot draw and must not rebuild away."""
    from datetime import date

    waits = Task(id="task-aa0001", kind="task", title="Waits by hand", status="ready",
                 depends_on=["task-bb0001", "issue-0f0001"])
    first = Task(id="task-bb0001", kind="task", title="Finishes first", status="ready")
    third = Task(id="task-cc0001", kind="task", title="A third record", status="ready")
    noticed = Issue(id="issue-0f0001", kind="issue", title="Hand-written blocker")
    return build_index([waits, first, third, noticed], Config(), date(2026, 8, 17))


def test_an_edge_edit_is_refused_where_it_would_delete_a_hand_written_line(
    hand_index: Index, tmp_path: Path
):
    """Save PATCHes the waiter's whole `depends_on` rebuilt from what the canvas
    carries, and the canvas deliberately carries only what it can draw — so on
    a record whose stored field also names an issue, either edge gesture would
    silently delete the hand-written line under a commit message that says only
    "depends_on". The server cannot refuse it for us: the record page draws the
    full field through `_links`, so a list arriving without that target is a
    legitimate removal from THERE and destruction from HERE, and the two are
    the same bytes on the wire. So the canvas is the only gate, the gesture is
    refused where the other impossible edges are refused, and the message names
    the way out. A rare gesture failing with a sentence that teaches beats a
    common gesture silently destroying somebody's line."""
    page = render_graph(hand_index, ROUTES, base_commit=HEAD)
    assert "issue-0f0001" not in page, "the off-plan id must not reach a plan page"

    got = measured_in(chrome(), page, tmp_path / "offplan.html", 1400, _OFF_PLAN, height=1000)

    assert got["drawn"] == 0, "the refused edge was drawn anyway"
    for said in (got["refusedAdd"], got["refusedDrop"]):
        assert "task-aa0001" in said and "cannot draw" in said, said
        assert "its own page" in said, "the refusal must name the way out"
    assert got["marked"] is False, "the stored edge was marked for a removal that destroys"
    assert got["drawnOk"] == 1, "a record the canvas sees whole stopped taking edges"
    assert got["wrote"] == [], "a refusal must not reach the server"
