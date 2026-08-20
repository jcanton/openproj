"""Drawing a dependency, and taking one away.

Edit mode could only add. "What waits for what is wrong on this diagram" is one
job, and a mode that could only do half of it was a mode you had to leave — and
open a record — to finish the thought.

Both halves are grouped by the entity that WAITS, because that is the record
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


def a_dependency(index: Index) -> tuple[str, str]:
    """One edge the plan already has, as (waits, first)."""
    for entity_id, blockers in sorted(index.blocked_by.items()):
        if blockers:
            return entity_id, blockers[0]
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
    assert [call["url"] for call in got["wrote"]] == [f"/api/entity/{waits}"]

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


def a_child(index: Index) -> tuple[str, str]:
    """One entity the plan already files inside another, as (child, parent)."""
    for entity_id, entity in sorted(index.entities.items()):
        if getattr(entity, "parent", None):
            return entity_id, entity.parent
    raise AssertionError("the corpus has nothing filed inside anything")


_REFILE_ON_A_DEAD_CONNECTION = """
const loose = [];
addEventListener('unhandledrejection', event => {
  loose.push(String(event.reason));
  event.preventDefault();
});
let paired = 0;
addEventListener('openproj:writing', () => { paired++; });
addEventListener('openproj:wrote', () => { paired--; });
document.getElementById('state').textContent = '';
window.fetch = async () => { throw new TypeError('Failed to fetch'); };
let threw = null;
try { await refile(%s, %s); } catch (error) { threw = String(error); }
await new Promise(go => setTimeout(go, 120));
return {loose, threw, paired, said: document.getElementById('state').textContent};
"""


def test_a_refile_on_a_dead_connection_takes_its_own_sentence_back_down(
    index: Index, page: str, tmp_path: Path
):
    """Dragging a node into a box says `filing task-3 into project-a…` before the
    request, and `refile` was `try`/`finally` with no `catch`.

    A rejection runs the `finally` and carries on unwinding, so the sentence
    stayed — over a diagram still drawn the way it was, with the rejection
    escaping unhandled and `location.reload()` never reached. `e82ce55` fixed the
    same shape on the editing surface and its message named the uploader and Save
    as the only two sites with a sentence left behind them; this and the table's
    drag are the other two.

    The reload is the reason the recovery `return`s rather than falling through:
    the refusal branch above it skips the reload for the same reason, and a page
    that reloaded here would throw away the only thing that says what happened.
    """
    child, parent = a_child(index)
    got = measured_in(
        chrome(), page, tmp_path / "refile-dropped.html", 1400,
        _REFILE_ON_A_DEAD_CONNECTION % (json.dumps(child), json.dumps(parent)),
        height=1000, budget=6000,
    )

    assert got["loose"] == [], f"the rejection still escapes: {got['loose']}"
    assert got["threw"] is None, f"and it reaches the gesture that called it: {got['threw']}"
    assert got["paired"] == 0, (
        "an `openproj:writing` was left unpaired, which holds every later banner "
        "on this page for ever"
    )
    assert "…" not in got["said"], (
        f"the page is still saying the move is happening: {got['said']!r}"
    )
    assert child in got["said"] and "was not moved" in got["said"], got["said"]
    assert "Drag it again" in got["said"], (
        f"and it does not say what to do about it: {got['said']!r}"
    )
