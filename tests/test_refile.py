"""Filing one thing under another by dragging it, on the graph.

The gesture had to be told apart from the one the canvas already has: a plain
drag means "move the node", and always has. So refiling is a mode, named in the
bar beside the mode that draws dependencies, and the drop is judged before it is
sent — `PARENT_KINDS` decides which box may hold which, and the server refuses
the same way if the page gets it wrong.

Everything here runs in Chrome. The interesting half is geometry — which box a
point is inside while a node is in the air — and cytoscape computes that from a
layout, which is the one thing a DOM shim does not have.
"""

from __future__ import annotations

import json
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


@pytest.fixture
def page(index: Index) -> str:
    return render_graph(index, ROUTES, base_commit=HEAD)


def kinds(index: Index) -> dict[str, str]:
    return {entity_id: e.kind for entity_id, e in index.entities.items()}


def a_task_in_a_pitch(index: Index) -> tuple[str, str]:
    for entity_id, entity in sorted(index.entities.items()):
        holder = index.entities.get(entity.parent) if entity.parent else None
        if entity.kind == "task" and holder is not None and holder.kind == "pitch":
            return entity_id, entity.parent
    raise AssertionError("the corpus has no task inside a pitch")


# Every drag below is emitted rather than performed: cytoscape's own `grab`,
# `drag` and `free` are what the page listens to, and driving a pointer across a
# canvas in a headless browser tests the driver.
_DRAG = """
// The request is recorded when it is MADE and then never answered. A successful
// write ends in `location.reload()`, which cannot be stubbed — it is not
// configurable — and would take the page and this report with it. A promise that
// never settles leaves the page exactly where the write left it, which is the
// state being asked about.
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};

document.getElementById('refile').click();
const child = cy.getElementById(%s);
const before = child.data('parent') || null;
child.emit('grab');
child.position(%s);
child.emit('drag');
const marks = cy.nodes('.can-hold, .cannot-hold').map(one => one.id() + ':'
  + (one.hasClass('can-hold') ? 'can' : 'cannot'));
child.emit('free');
return {before, marks, said: document.getElementById('state').textContent,
        wrote: window.__wrote};
"""


def at(target: str) -> str:
    """The position of another node, as the drop point."""
    return f"cy.getElementById({json.dumps(target)}).position()"


def test_a_task_dropped_on_a_pitch_is_filed_under_it(index: Index, page: str, tmp_path: Path):
    """The gesture the item was asked for. One PATCH, the same one the table's own
    drag sends — a parent is a field like any other, so the save path is not new."""
    task, pitch = a_task_in_a_pitch(index)
    other = next(
        i for i, e in sorted(index.entities.items()) if e.kind == "pitch" and i != pitch
    )
    got = measured_in(
        chrome(), page, tmp_path / "onto.html", 1400,
        _DRAG % (json.dumps(task), at(other)), height=1000,
    )

    assert got["marks"] == [f"{other}:can"], got["marks"]
    assert [call["url"] for call in got["wrote"]] == [f"/api/entity/{task}"]
    assert got["wrote"][0]["body"]["fields"] == {"parent": other}
    assert got["wrote"][0]["body"]["base_commit"] == HEAD


def test_a_drop_the_server_would_refuse_is_refused_before_it_is_sent(
    index: Index, page: str, tmp_path: Path
):
    """A task cannot hold a task. The canvas says so while the mouse is still
    down, in the validator's own words, and sends nothing — the rule you can only
    learn by breaking it is the rule nobody learns."""
    task, _ = a_task_in_a_pitch(index)
    another = next(
        i for i, e in sorted(index.entities.items()) if e.kind == "task" and i != task
    )
    got = measured_in(
        chrome(), page, tmp_path / "refused.html", 1400,
        _DRAG % (json.dumps(task), at(another)), height=1000,
    )

    assert got["marks"] == [f"{another}:cannot"]
    assert got["said"] == "A task belongs under a pitch or a project"
    assert got["wrote"] == [], "the canvas sent a write it had already refused"


_OUTSIDE = """
window.__wrote = [];
window.fetch = (url, options) => {
  window.__wrote.push({url, body: JSON.parse(options.body)});
  return new Promise(() => {});
};
document.getElementById('refile').click();
const child = cy.getElementById(%s);
const before = child.data('parent') || null;
child.emit('grab');
// Far outside everything, which is the whole question: a compound parent's box
// is drawn around its children, so while one is being dragged the box follows
// it — and until `boxWithout` measured the leaves instead, there was no point on
// this canvas that meant "out".
child.position({x: 40000, y: 40000});
child.emit('drag');
const target = under(child.position(), child);
child.emit('free');
return {before, target: target ? target.id() : null, wrote: window.__wrote};
"""


def test_a_node_dropped_outside_everything_is_taken_out_of_what_held_it(
    index: Index, page: str, tmp_path: Path
):
    """The half the item costed as hard: the canvas has no bottom edge that means
    "outside the tree". It has one now — anywhere that is not inside a box — and
    getting there needed the boxes to be measured without the node in the air."""
    task, pitch = a_task_in_a_pitch(index)
    got = measured_in(
        chrome(), page, tmp_path / "out.html", 1400,
        _OUTSIDE % json.dumps(task), height=1000,
    )

    assert got["before"] == pitch
    assert got["target"] is None, f"dropped outside everything and landed in {got['target']}"
    assert [call["body"]["fields"] for call in got["wrote"]] == [{"parent": None}]


def test_a_drag_that_changes_nothing_writes_nothing(index: Index, page: str, tmp_path: Path):
    """Cytoscape fires `free` for every drag, including the ones that moved a node
    two pixels. A commit per nudge is a history nobody can read."""
    task, pitch = a_task_in_a_pitch(index)
    got = measured_in(
        chrome(), page, tmp_path / "same.html", 1400,
        _DRAG % (json.dumps(task), at(task)), height=1000,
    )

    assert got["before"] == pitch
    assert got["wrote"] == [], "a drag that landed where it started committed"


_MODES = """
const refile = document.getElementById('refile');
const connect = document.getElementById('connect');
connect.click();
const bothOn = connect.textContent + ' / ' + refile.textContent;
refile.click();
return {bothOn, after: connect.textContent + ' / ' + refile.textContent,
        said: document.getElementById('state').textContent};
"""


def test_the_two_modes_are_exclusive(page: str, tmp_path: Path):
    """Drawing an edge and refiling are both "press a node, then somewhere else",
    and a canvas where that means two things at once is a canvas nobody can
    predict."""
    got = measured_in(chrome(), page, tmp_path / "modes.html", 1400, _MODES, height=1000)

    assert got["bothOn"].startswith("Discard and exit"), "the edge mode did not open"
    assert got["after"] == "Edit dependencies / Stop refiling", got["after"]
    assert "Drag a node onto another" in got["said"]
