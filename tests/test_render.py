"""The static pages.

These assert structure and payload, not pixels. A page is correct here if it is
self-contained, carries the data its JavaScript needs, and encodes the things a
reader must be able to tell apart at a glance: which dates are derived, which are
guesses, and which work is late.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from markupsafe import escape
from pages import elements, headings, lit, render_source, selects

from openproj.index import Index, build_index
from openproj.model import Config, load_repo
from openproj.render import (
    ROUTES,
    STATIC,
    STATUS_GLYPH,
    STATUSES,
    preview_html,
    render_detail,
    render_static,
)

PAGES = ("index.html", "table.html", "detail.html", "people.html", "cycles.html",
         "graph.html", "timeline.html", "issues.html", "notes.html")


@pytest.fixture
def seed_index(seed_root: Path) -> Index:
    from datetime import date

    records, config, _ = load_repo(seed_root)
    return build_index(records, config, date(2026, 8, 17))


@pytest.fixture
def rendered(seed_index: Index, tmp_path: Path) -> Path:
    render_static(seed_index, tmp_path)
    return tmp_path


@pytest.fixture
def unrecorded_cycle(seed_root: Path) -> Index:
    """The same frozen corpus read from inside cycle 36, which `config/cycles.yaml`
    dates and no file records.

    The people page only ever shows `_current_cycle(index)`, and cycle 37 gained a
    record when the corpus grew — it starts on 2026-08-17, which is `seed_index`'s
    own `today` — so at that date the page is about a cycle with a roster. The
    unrecorded case did not go anywhere: 28, 34, 35 and 36 are still dated in
    config with nothing written down behind them. So it is asked of a cycle it is
    true of instead of whichever one the calendar happens to be standing in.
    """
    records, config, _ = load_repo(seed_root)
    return build_index(records, config, date(2026, 7, 1))


def read(directory: Path, name: str) -> str:
    return (directory / name).read_text(encoding="utf-8")


def _luminance(colour: str) -> float:
    """WCAG relative luminance of a #rrggbb."""
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """The WCAG ratio between two colours, either way round."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def tokens(page: str) -> dict[str, dict[str, str]]:
    """Every colour token, per theme, read out of a page that actually rendered.

    Three blocks, not two: a reader who has never touched the toggle matches only
    the media query, so a value that is right in `[data-theme="dark"]` and wrong
    in the media block is wrong for most of the people who will ever see it. They
    are returned separately so a test can say they agree.
    """
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    blocks = {
        "light": re.search(r"^:root \{(.*?)^\}", style, re.S | re.M).group(1),
        "dark": re.search(r'^:root\[data-theme="dark"\] \{(.*?)^\}', style, re.S | re.M).group(1),
        "dark-by-system": re.search(
            r'@media \(prefers-color-scheme: dark\) \{\s*'
            r':root:not\(\[data-theme="light"\]\) \{(.*?)^  \}',
            style, re.S | re.M).group(1),
    }
    return {
        name: dict(re.findall(r"(--[\w-]+): (#[0-9a-f]{6})", body))
        for name, body in blocks.items()
    }


def test_render_static_writes_every_page_and_says_which(rendered: Path, seed_index):
    """The export grew from three pages to six; the count in this test's own name,
    in `render`'s help and in the line it prints did not.

    So `render` handed over six files and announced three, and the two pages a
    reader would most want to send somebody — the people table and the cycles
    index — were not among the ones it named. The names come back from
    `render_static` now, which is the only thing that knows them.
    """
    for name in PAGES:
        assert (rendered / name).is_file(), name
        assert read(rendered, name).lstrip().startswith("<!doctype html>")

    import tempfile

    from openproj.render import render_static

    with tempfile.TemporaryDirectory() as directory:
        assert render_static(seed_index, Path(directory)) == PAGES


def fetches_nothing(body: str, where: str) -> None:
    """Every way a page can ask the network for a file, in one place.

    Written out inside the test that reads the exported files, this rule had
    never once been applied to an editing surface: `render_static` calls
    `render_detail` with no `base_commit`, so the exported `detail.html` carries
    no textarea, no toolbar, no Yjs bundle and no room script at all. The rule was
    unenforced exactly where the newest bytes in this repository land. It is a
    function now so that the page which carries an editor is held to the same
    words, and not to a second copy of them that can drift.
    """
    # Anchors to github.com are fine and wanted — a PR link that resolves is
    # the point. What must never appear is a page FETCHING from the network.
    assert not re.search(r'<script[^>]+src\s*=', body), where
    assert not re.search(r'<link[^>]+href\s*=\s*["\']https?://', body), where
    assert not re.search(r'<img[^>]+src\s*=\s*["\']https?://', body), where
    assert "cdn." not in body, where


def asks_for_no_font(body: str, where: str) -> None:
    """The fourth way out, and the one a stylesheet can open without a tag.

    A bare scan for `url(` over the whole page, `<script>` bodies included, which
    is deliberate: it is the assertion a vendored editor mode was measured
    failing twice on a tokeniser regex that fetches nothing at all. A rule that
    holds only over the text it is allowed to read is not a rule.
    """
    for url in re.findall(r"url\(\s*[\"']?([^\"')]+)", body):
        assert url.startswith("data:") or url.startswith("#"), (where, url[:60])
    assert "fonts.googleapis" not in body and "fonts.gstatic" not in body, where


def test_no_page_reaches_the_network(rendered: Path):
    """No npm, no build step, no CDN. A page that fetches from the internet is a
    page that breaks on a train, and this is the only test that would notice."""
    for name in PAGES:
        fetches_nothing(read(rendered, name), name)


def test_the_libraries_are_inlined_rather_than_linked(rendered: Path):
    graph = read(rendered, "graph.html")
    assert "cytoscape" in graph
    assert 'src="' not in graph


def test_every_library_is_inlined_exactly_once_and_no_marker_survives(
    rendered: Path, seed_index: Index
):
    """The graph page once rendered blank because `DAGRE_JS` is a substring of
    `CYTOSCAPE_DAGRE_JS`: replacing markers in sequence inlined dagre twice and
    cytoscape-dagre never. Nothing in the page said so — it just drew nothing.

    Rewritten when Ace arrived, because the old form — "four `.js` files, each
    once in `graph.html`" — encoded an assumption that stopped being true rather
    than a rule: every vendored script used to be a graph library. The rule the
    old test meant is the one below, said properly.
    """
    static = Path(__file__).resolve().parents[1] / "static"
    graph = read(rendered, "graph.html")

    # Not a bare "@@" check: minified cytoscape genuinely contains `e["@@iterator"]`.
    assert not re.search(r"@@[\w.-]+\.js@@", graph), "an inlining marker survived"
    # Read from the directory rather than listed here: the set changed the day
    # ELK replaced dagre, and a list written down in a test is a list that says
    # a page is fine while it inlines a library nobody checked.
    inlined = sorted(path.name for path in static.iterdir() if path.suffix == ".js")
    assert len(inlined) == 4, inlined

    # **"Exactly once, into the page that uses it" — which is not the same claim
    # as "exactly once, into the graph".** It was, when every vendored script was
    # a graph library. Ace is the first that is not: it belongs to an editing
    # surface, the graph page has none, and asserting it appears once there would
    # have been asserting it is somewhere it must never be. So the pages are
    # named beside the files, and a file nobody claims fails the last line rather
    # than passing quietly.
    editing = editable_page(seed_index, editor="ace")[1]
    for name in inlined:
        # 200 and not 120: two of these are webpack bundles whose first 120
        # characters are the same UMD preamble, so the shorter signature found
        # each of them twice and called one of them a defect. Same length as the
        # sibling check in test_injection.py, which is where that was learnt.
        signature = (static / name).read_text(encoding="utf-8")[:200]
        wanted = editing if name in ("ace.js", "keybinding-vim.js") else graph
        other = graph if wanted is editing else editing
        assert wanted.count(signature) == 1, name
        assert other.count(signature) == 0, f"{name} is in a page that does not use it"


def test_the_table_carries_the_whole_plan_and_its_derived_dates(rendered: Path, seed_index: Index):
    payload = json.loads(
        re.search(
            r'<script id="payload" type="application/json">(.*?)</script>',
            read(rendered, "table.html"),
            re.S,
        ).group(1)
    )
    assert set(payload["rows"]) == set(seed_index.plan)
    scheduled = payload["rows"]["task-53a9f0"]
    # Its own `assigned_on`, because it is in progress: work under way started
    # when it started, and the floor at today applies to what has not begun.
    assert scheduled["start"] == "2026-08-13"
    assert scheduled["derived"] is True
    # And nothing beyond what the script reads. `facets` and `predicates` were the
    # whole facet index inlined into every table page for a control bar that is
    # rendered by the server and re-read from its own `<select>`s — dead weight
    # two assertions had grown up to protect.
    assert "facets" not in payload
    assert "predicates" not in payload


def test_the_table_shows_a_persistent_blocker_count(rendered: Path, seed_index: Index):
    blockers = sum(1 for p in seed_index.problems if p.severity == "blocker")
    assert blockers > 0
    assert f'id="blocker-count">{blockers}<' in read(rendered, "table.html")


def test_a_rendered_file_dresses_its_cells_the_way_the_server_does(rendered: Path):
    """A rendered file has no server, so `EDITABLE` is null and every branch that
    hangs off it is dead. The tag clamp was written into the editable branch
    only, so an export kept the "+2" reveal and showed all five tags beside it —
    caught in a browser, not here, which is why it is here now.

    The chips, the severity marks and the empty states are all drawn from data
    the export carries, so all of them have to survive the loss of the editor.
    """
    index = read(rendered, "table.html")

    assert "base_commit" not in index, "this is the read-only build"
    assert "CLAMPED.has(key) ? 'clamp' : ''" in index, (
        "the clamp is not behind the editor"
    )
    assert "td.clamp .rest { display: none; }" in index
    for rule in (".chip.st-done", ".chip.kind-pitch", ".sev-row-blocker", ".sev-mark-blocker"):
        assert rule in index, rule
    assert "'The plan could not be loaded.'" in index
    assert '<span class="facetname">Flags' in index
    assert '<input type="checkbox" value="has_blocker">Has a blocking problem</label>' in index


def test_filter_state_lives_in_query_parameters(rendered: Path):
    """Every view is a shareable URL, and the back button has to work. This is
    also what deletes the entire saved-views feature request."""
    body = read(rendered, "table.html")
    assert "URLSearchParams" in body
    assert "history.replaceState" in body or "history.pushState" in body


def test_the_graph_is_a_compound_dag_coloured_by_status(rendered: Path):
    body = read(rendered, "graph.html")
    elements = json.loads(
        re.search(
            r'<script id="elements" type="application/json">(.*?)</script>', body, re.S
        ).group(1)
    )
    by_id = {e["data"]["id"]: e["data"] for e in elements if "source" not in e["data"]}
    assert by_id["task-31f6c4"]["parent"] == "pitch-3c9a41"
    assert by_id["task-31f6c4"]["status"] == "done"

    edges = [e["data"] for e in elements if "source" in e["data"]]
    assert {"source": "task-5a4e39", "target": "task-5c1d84", "kind": "depends"} in edges
    # ELK, measured rather than chosen: dagre knows nothing about nested nodes,
    # and on the real plan it drew three of six dependency edges across a box
    # they are not attached to and fitted the whole thing into 7% of the canvas.
    # See `LAYOUT`, which carries the numbers.
    assert "elk" in body
    # The word survives in the comment that explains why it went, which is where
    # it belongs; what must be gone is the library and the call.
    assert "cytoscapeDagre" not in body, "the layout it replaced is still registered"
    assert "dagre.min.js" not in body
    # What the graph looks like is asserted by measuring it — see
    # `test_graph_layout.py`. There is deliberately nothing here about which
    # layout options are set: this test used to require `INCLUDE_CHILDREN` and
    # `packComponents`, and both of those strings were present on the day the
    # page shipped drawing boxes across each other. A string in a script is not
    # a picture of anything.


def test_a_node_carries_everything_the_filters_ask_of_it(seed_index: Index):
    """The graph filters on the table's row, not on a graph-shaped subset of it.

    A node holding only what cytoscape draws is how a dropdown comes to filter one
    view and quietly do nothing in the next.

    The dependency keys are the exception, and they say the rule rather than the
    stored field: `depends_on` is `blocked_by` narrowed to the plan, and
    `off_plan_deps` says whether the narrowing took anything.
    """
    from openproj.render import _elements, _row

    nodes = {
        e["data"]["id"]: e["data"] for e in _elements(seed_index) if "source" not in e["data"]
    }

    for record_id in seed_index.plan:
        for field, value in _row(seed_index, record_id).items():
            assert nodes[record_id][field] == value, f"{record_id}.{field}"
        # And the three keys the row does not carry, because only a canvas needs them.
        assert nodes[record_id]["label"] == seed_index.plan[record_id].title
        # `depends_on` is `blocked_by` NARROWED to the plan, never the stored
        # field: `blocked_by` is total over records, so a hand-written edge to
        # an unplanned record would otherwise put an inbox id on a plan page
        # and hand cytoscape an edge whose source is a node it was never given.
        # This asserted the whole stored field, which was only ever right
        # because nothing had been narrowed: until the corpus grew notes and
        # issues, `Index.plan` WAS `Index.records` here and the guard in
        # `_elements` could not drop anything. It drops one edge now.
        stored = seed_index.blocked_by[record_id]
        drawable = [b for b in stored if b in seed_index.plan]
        assert nodes[record_id]["depends_on"] == drawable, record_id
        # And the flag says the field holds MORE than the canvas drew, which is
        # what stops an edge edit rebuilding `depends_on` from the drawn list
        # and silently deleting somebody's line. A boolean and never the ids.
        assert nodes[record_id]["off_plan_deps"] == (drawable != stored), record_id

    # Neither claim above may pass by never happening. The first was vacuous in
    # every corpus before 2026-08-23 — an unplanned rung to depend ON is what
    # the growth added — and the second is the whole of `off_plan_deps`.
    assert set(nodes) == set(seed_index.plan), "an unplanned rung is not a node"
    assert any(n["off_plan_deps"] for n in nodes.values()), "nothing was narrowed"


def test_the_graph_filters_the_plan_the_way_the_table_does(rendered: Path):
    """One control bar over one `matches()`. While the filter model lived inside
    the table's script, "three views share one filter" was true of one view, and a
    second copy of the predicate is how a facet acquires a second meaning."""
    table = read(rendered, "table.html")
    graph = read(rendered, "graph.html")
    model = re.search(r"function matches\(row\) \{.*?\n\}", table, re.S).group(0)

    assert model in graph, "the graph must ask the same question, not a similar one"
    assert re.findall(r'<div class="facet" data-field="([^"]+)"', graph) == re.findall(
        r'<div class="facet" data-field="([^"]+)"', table
    )
    assert "URLSearchParams" in graph and "history.replaceState" in graph
    assert '<input id="q"' in graph


def test_hiding_a_node_never_leaves_an_edge_pointing_at_nothing(rendered: Path):
    """An arrow leaving the canvas for something you filtered out is the one thing
    a dependency graph must not draw: it says a dependency exists and refuses to
    say what it is, which is exactly the fact somebody filtered to find."""
    graph = read(rendered, "graph.html")
    body = re.search(r"function applyFilter\(\) \{.*?\n\}", graph, re.S).group(0)

    assert "neighborhood('node')" in body, "what a shown node points at stays on the canvas"
    assert "toggleClass('aside'" in body, "and is faded, because it did not match"
    assert "ancestors()" in body, "the box that holds it comes too, or its contents float"
    assert re.search(r"on\(edge\.source\(\)\.id\(\)\) && on\(edge\.target\(\)\.id\(\)\)", body)
    assert "selector: 'node.aside'" in graph


def test_the_graph_says_which_of_the_three_emptinesses_it_is(rendered: Path):
    """An empty canvas is indistinguishable from a graph that failed to draw, and
    it was one hardcoded sentence saying the filters did it — which is the wrong
    thing to do next in two of the three cases. The table has said which one it is
    since F1; the graph is the fourth view and was left behind.

    The parse guard is half of it: without it a payload that did not survive the
    trip threw on `JSON.parse` and took the whole script with it, so the page that
    could least afford to be silent was the one that said nothing at all.
    """
    graph = read(rendered, "graph.html")
    body = re.search(r"function drawNothing\(\) \{.*?\n\}", graph, re.S).group(0)

    assert 'id="nothing"' in graph
    assert "#nothing[hidden] { display: none; }" in graph, "hidden loses to display:flex"
    assert "No record matches these filters." in body
    assert "This plan has no records yet." in body
    assert "The plan could not be loaded." in body
    # Only the filtered one offers a way out: there is nothing to clear when the
    # plan is empty or the payload never arrived, and a Clear that clears nothing
    # is how a control teaches people it is decoration.
    assert body.count("clearable = false") == 2
    assert "CLEAR.hidden = !clearable;" in body

    assert re.search(r"try \{\s*\n\s*ELEMENTS = JSON\.parse", graph), "the payload may be truncated"
    assert "const LOADED = ELEMENTS !== null;" in graph
    assert "elements: ELEMENTS || []," in graph


def test_the_graph_commits_in_the_same_place_every_other_page_does(
    rendered: Path, seed_index: Index
):
    """The fourth page with a commit bar, and it is where the other three are —
    above what it writes, jcanton 2026-08-20, "consistency!".

    Twice re-argued, and both times the coordinate was the part that was wrong.
    F15 moved this bar BELOW the canvas because Create, Edit and Save the setup
    had all moved below the forms they commit; what those moves actually bought
    was reach, and the `position: sticky` each shipped alongside is what delivers
    reach from either edge. So when the shell's one rule became `top: 0`, a bar
    last in the markup was a bar you could not see from the top of a page short
    enough to scroll — measured in Chrome at 1400x380, off screen at scrollY 0.

    It costs the drawing nothing, which is the objection that would otherwise
    stop it: `measureRoom` sizes the canvas from what is above the box and what is
    below it, both measured, so a bar crossing from one term to the other lands in
    the other. Measured, `--room` went 595px to 607px at 1400x900 — the canvas
    gained twelve pixels to a margin that collapses up there and did not down
    there.

    Served rather than rendered: a static export has no server to write to, so it
    has no action bar at all — which is the other half of the claim.
    """
    from openproj.render import ROUTES, render_graph

    live = render_graph(seed_index, ROUTES, base_commit="deadbee")

    assert '<p class="editbar">' not in live, "the bar it replaced"
    assert live.index('id="commitbar"') < live.index('<div class="canvas">')
    assert live.index('id="connect"') < live.index('id="cy"')
    # The shell's bar, not a fourth one drawn by hand. That this page has no
    # second answer to which edge a commit bar sticks to is asked where it can be
    # asked properly — `tests/test_cascade.py::test_every_commit_bar_sticks_to_
    # the_same_edge_and_one_rule_decides_it`, which resolves the cascade by name
    # over all four pages that draw one. A substring search here cannot tell a rule from the
    # comment above it, and this one was written and deleted for saying that a
    # paragraph explaining the old override was the old override.
    assert re.search(r"\.commitbar \{[^}]*position: sticky; top: 0; bottom: auto", live, re.S)
    assert 'id="commitbar"' not in read(rendered, "graph.html")


def test_the_graph_names_every_colour_it_draws_with(rendered: Path):
    """Status is the only thing on this canvas that is not a word. The swatch is
    the token the node is actually filled with and the glyph the node is actually
    marked with — a legend naming a colour that is not on screen is worse than
    none, because it gets believed, and a legend keying only the colour keys the
    half of the encoding a dichromat cannot use."""
    from openproj.render import STATUS_GLYPH, STATUSES

    graph = read(rendered, "graph.html")
    # The status list, by name. There are two legends now — priority is the other
    # — and taking the first `<ul class="legend">` took whichever happened to be
    # written first, which is the priority one and holds no status at all.
    legend = re.search(
        r'<ul class="legend" aria-label="What a node\'s colour and mark mean">.*?</ul>',
        graph, re.S,
    )
    assert legend, "the status legend is gone"
    legend = legend.group(0)

    for status in STATUSES:
        assert f'<span class="swatch st-{status}" aria-hidden="true">' in legend, status
        assert STATUS_GLYPH[status] in legend, status
        # Border as well as fill and ink. A node is a bordered shape now — on the
        # light theme the fill is a tint and the border is what makes it one — so
        # a key drawn without it keys a shape that is not on the canvas.
        assert (
            f".legend .swatch.st-{status} {{ background: var(--st-{status}); "
            f"color: var(--st-{status}-ink);\n"
            f"                             border: 1px solid var(--st-{status}-line); }}"
        ) in graph
    assert "In progress" in legend, "the reader's word, not the stored one"


_LEGEND_GEOMETRY = """
const grid = document.querySelector('.legends');
const rows = [...grid.querySelectorAll('.legend')].map(ul => ({
  name: ul.querySelector('.legendname').textContent.trim(),
  nameX: +ul.querySelector('.legendname').getBoundingClientRect().left.toFixed(1),
  xs: [...ul.querySelectorAll('li:not(.legendname)')]
       .map(li => +li.getBoundingClientRect().left.toFixed(1)),
  ys: [...ul.querySelectorAll('li:not(.legendname)')]
       .map(li => +li.getBoundingClientRect().top.toFixed(1)),
}));
return {rows, bands: [...new Set(rows.flatMap(r => r.ys))].length};
"""


def test_the_legend_is_two_rows_and_the_keys_line_up(rendered: Path, tmp_path: Path):
    """`docs/QUEUE.md` §7.5: "the legend is not vertically aligned ... third time
    this has been reported; whatever is done here should be a measurement in a
    test, not an eye". This is the eye replaced.

    The two lists are `display: contents`, so their keys are items of ONE grid and
    the layout only reads as two rows because something puts each name at the
    start of one. Nothing did: it read as two rows for as long as the two lists
    happened to be the same length, which is a fact no line of the stylesheet
    stated. Status now has six rungs and priority five, and both ways of getting
    it wrong were measured at 1400px before this was written:

    * `repeat(5, max-content)` — the sixth status key wraps to a THIRD row and
      sits in column 1, directly under the word STATUS. Grid 60.4px tall.
    * `repeat(6, max-content)` with nothing pinning the names — two rows, and
      worse: priority's name plus its five keys exactly fill row 1, so
      auto-placement puts the word STATUS in row 1 column 7 and shifts the entire
      status row one cell left. Not one priority key sits over its counterpart.

    What is asserted is the property, not the pixel: two bands, both names at one
    x, and every priority key starting at the same x as the status key under it —
    with the ladder's extra rungs hanging past the end of the shorter row, which
    is what "one more cell for the status row" means and what jcanton accepted.
    """
    from browser import chrome, measured_in

    got = measured_in(chrome(), read(rendered, "graph.html"),
                      tmp_path / "legend.html", 1400, _LEGEND_GEOMETRY, height=900)
    # Status leads — jcanton, 2026-08-24: "put the status row on top of the
    # priority row, better!" It is the longer of the two now, so the longer row
    # leads and the shorter hangs under its right end, which reads as one block
    # rather than as a step.
    status, priority = got["rows"]
    assert [status["name"], priority["name"]] == ["status", "priority"]

    assert got["bands"] == 2, "the keys are not on two rows"
    assert len(status["xs"]) == len(STATUSES)
    assert len(status["xs"]) > len(priority["xs"]), (
        "status is meant to be the longer row — if priority grew a rung, the grid's"
        " column count follows the wrong list"
    )
    # Paired from the RIGHT, so the last key of each row shares a column and the
    # slack is taken by the shorter row's name cell. From the left they are
    # deliberately staggered by exactly the difference in their lengths — see
    # `test_the_two_key_rows_are_one_length_and_sit_on_the_drawing`, which
    # measures the same claim in painted pixels.
    for column, (over, under) in enumerate(
        zip(reversed(priority["xs"]), reversed(status["xs"]), strict=False)
    ):
        assert over == under, (column, over, under)
    # The names no longer start together: the shorter row's is what absorbs the
    # extra column, so it is wider by one column and starts where the other does.
    assert priority["nameX"] == status["nameX"], "the two row names do not start together"
    # And each row is one row.
    assert len(set(priority["ys"])) == 1 and len(set(status["ys"])) == 1


def test_the_corner_of_the_graph_holds_the_legend_and_nothing_else(rendered: Path):
    """jcanton, 2026-08-24: "move it below the legend instead please? this way
    the legend can move a little upwards into the corner." Then, 2026-08-25, the
    count left the drawing altogether — the three plan views share one bar now,
    and a count over the canvas as well would be the same number in two places.

    So what this asserts is what is left: the legend is the first thing in the
    corner box, and the corner box holds nothing but the legend. Read off the
    parsed document because order and containment are facts about a document: a
    substring search for `id="summary"` against `class="legends"` would also
    match either name inside the stylesheet's own comments, which is how
    `page.index("<h1>")` found a heading inside a CSS comment once already. The
    pixels this buys are measured where pixels live, in
    `test_the_two_key_rows_are_one_length_and_sit_on_the_drawing`
    (`test_graph_layout.py`).
    """
    parsed = elements(read(rendered, "graph.html"))
    keys = next(i for i, el in enumerate(parsed)
                if el.tag == "div" and el.attrs.get("class") == "keys")
    legends = next(i for i, el in enumerate(parsed)
                   if el.tag == "div" and el.attrs.get("class") == "legends")
    assert legends == keys + 1, (
        f"the legend is not the first thing in the corner: keys at {keys}, "
        f"legends at {legends}"
    )
    # The count is in the control bar, which is above the canvas rather than in
    # it — so between the corner box and the canvas there is nothing left.
    canvas = next(i for i, el in enumerate(parsed) if el.attrs.get("id") == "cy")
    summary = next(i for i, el in enumerate(parsed) if el.attrs.get("id") == "summary")
    assert summary < keys, (
        "the count is still inside the corner box, so the graph says how much is "
        "on screen twice"
    )
    # And every element the script writes by id went with it — the move must not
    # strand `getElementById('shown')`, `('context')` or the blocker link's two
    # halves somewhere the graph's own script cannot find them.
    moved = [el.attrs.get("id") for el in parsed[summary : summary + 7]]
    for name in ("shown", "context", "blockers", "blocker-count", "blocker-word"):
        assert name in moved, f"{name} did not move with the count: {moved}"
    assert keys < canvas, "the corner box is drawn after the canvas it floats over"


def test_both_halves_of_the_app_write_a_date_the_same_way(seed_index: Index):
    """One format, in two languages, driven against the same strings.

    jcanton, 2026-08-25: "all dates everywhere should be as in the table: dd.mm
    or dd.mm.YY or dd.mm.YYYY". The server prints the dates a page is rendered
    with (`_read_date`, the `on()` global); the browser has to write one too,
    because the echo beside a date box changes as somebody picks a date and that
    is a thing only the browser sees. Two copies of one rule is this
    repository's characteristic failure — "the invariant is written in two
    languages, which copy is guarded" — so both are asked the same questions
    here rather than being trusted to agree.

    The odd inputs are the ones that decide it. An empty box is what an unset
    date is, the em dash is what a table cell with no date holds, and a value
    that is not three parts is a hand-edited file: none of the three may come
    back rearranged or crash a page.
    """
    from test_injection import run_js

    from openproj.render import render_detail
    from openproj.render.tokens import _read_date

    asked = ["2026-09-01", "2026-12-31", "2027-01-02", "", "—", "not-a-date",
             "2026-09", "2026-09-01-02"]
    # A record page rather than the table: `readDate` is the shell's and is on
    # every page, and the table's own script reaches for a box the node shim has
    # no layout for, which would put an unrelated error in the way of this one.
    answer = run_js(
        render_detail(
            seed_index, ROUTES, base_commit="deadbee",
            only=sorted(seed_index.plan)[0], may_write=True, signed_in="ann",
            editor="plain",
        ),
        "(" + json.dumps(asked) + ").map(readDate)",
        page=True,
    )
    assert not answer["errors"], answer["errors"]
    assert answer["value"] == [_read_date(one) for one in asked], (
        f"the two halves disagree: {answer['value']} against "
        f"{[_read_date(one) for one in asked]}"
    )
    # And it is the format, not merely agreement: two functions that both
    # answered ISO would pass the line above.
    assert _read_date("2026-09-01") == "01.09.2026"
    # `not-a-date` comes back as `date.a.not` from both, which is silly and is
    # the honest consequence of "three dash-separated parts is a date": nothing
    # here validates, both halves are wrong in the same way, and the alternative
    # is a second date parser in two languages. It is asserted so that a future
    # reader meets the decision rather than the surprise.


def test_a_group_name_is_readable_inside_its_own_box(rendered: Path):
    """It was 9px of --muted sitting on the box border, where every edge crossing
    the box ran through it — a label saying only that something is grouped."""
    graph = read(rendered, "graph.html")
    parent = re.search(r"\{ selector: ':parent', style: \{(.*?)\} \},", graph, re.S).group(1)
    node = re.search(r"\{ selector: 'node', style: \{(.*?)\} \},", graph, re.S).group(1)

    assert "'text-valign': 'top'" in parent and "'text-halign': 'left'" in parent
    assert "'text-margin-x'" in parent, "pulled inside the box rather than left of it"
    assert "'text-background-color': token('--surface')" in parent, "on its own ground"
    assert "'font-size': GROUP_SIZE" in parent
    assert int(re.search(r"const GROUP_SIZE = (\d+)", graph).group(1)) > int(
        re.search(r"'font-size': (\d+)", node).group(1)
    ), "the group is the heading of what is inside it"


def test_a_node_takes_its_ink_from_the_fill_it_sits_on(rendered: Path):
    """In dark mode the fills are light shapes carrying dark ink, so the label
    colour belongs to the status, not to the theme's foreground."""
    graph = read(rendered, "graph.html")
    repaint = re.search(r"function paint\(\) \{.*?\n\}", graph, re.S).group(0)

    assert "'color': e => INK()[e.data('status')]" in graph
    # Resolved once at build time, the ink stays light on a fill that just turned
    # light, so the repaint has to re-read it exactly as it re-reads the fill.
    assert "'color': e => INK()[e.data('status')]" in repaint
    assert "'background-color': e => COLOUR()[e.data('status')]" in repaint
    assert "'text-background-color': token('--surface')" in repaint
    # The border draws priority, so it is a channel of its own — and one colour
    # for all five fills is 2:1 against the darkest rung of the ladder. It is the
    # status's own --st-X-line now, the same value the timeline strokes its bars
    # with, and it is re-read on a theme flip exactly as the fill and ink are.
    assert "'border-color': e => LINE()[e.data('status')]" in graph
    assert "'border-color': e => LINE()[e.data('status')]" in repaint
    # The three maps are BUILT from the ladder the page was handed, not written
    # out. They were three five-key object literals, and what that cost is the
    # subject of the test below — this line is what stops them going back.
    assert f"const STATUS_LADDER = {json.dumps(list(STATUSES))};" in graph
    assert "const byStatus = suffix => Object.fromEntries(" in graph


def test_every_status_a_node_can_hold_reaches_cytoscape_as_a_colour(
    rendered: Path, tmp_path: Path
):
    """The graph's three status maps, asked in the browser instead of grepped.

    This is the tripwire that was in the wrong medium. It used to assert that the
    string `token('--st-<status>-ink')` appeared somewhere in the file, once per
    status — which is a claim about the source text and not about the canvas, and
    the day `thinking` joined the ladder the maps were hand-written five-key
    literals: every lookup came back `undefined`, cytoscape logged it and fell
    back to its own #999 with a black border, and the legend beside it named a
    colour that was not on the drawing. Nothing threw and the picture looked
    deliberate.

    So the question is asked where the answer lives. `COLOUR()`, `INK()` and
    `LINE()` are the exact functions the stylesheet calls, run against the exact
    tokens the page ships, and every status a node can hold has to come back with
    a colour a canvas can parse — which is what `inSRGB` in the page is for, and
    why `rgb(...)` rather than the token stream is the shape of a right answer."""
    from browser import chrome, measured_in

    got = measured_in(
        chrome(), read(rendered, "graph.html"), tmp_path / "node-colours.html", 1200,
        "return {colour: COLOUR(), ink: INK(), line: LINE()};", height=800,
    )
    missing = [
        f"{which}[{status}] = {maps.get(status)!r}"
        for which, maps in got.items()
        for status in STATUSES
        if not re.fullmatch(r"(#[0-9a-fA-F]{3,8}|rgba?\([\d.,\s%/]+\))", maps.get(status) or "")
    ]
    assert not missing, missing


def test_the_timeline_hatches_what_it_is_guessing(rendered: Path, tmp_path: Path):
    """An estimated or unowned span is a forecast, not a commitment. If the two
    look alike, a guess gets read as a promise.

    Built from a constructed index rather than the seed: every seed record now
    states a size, so the corpus no longer exercises the defaulted path at all.
    """
    from datetime import date

    from openproj.model import Config, Task

    assert 'id="hatch-estimated-st-ready"' in read(rendered, "timeline.html")
    assert 'id="hatch-unowned-st-ready"' in read(rendered, "timeline.html")

    guessed = Task(id="task-000001", kind="task", title="No size given", owner="ann")
    nobodys = Task(id="task-000002", kind="task", title="Nobody owns this", person_weeks=1.0)
    index = build_index([guessed, nobodys], Config(), date(2026, 8, 17))
    out = tmp_path / "guesses"
    render_static(index, out)
    body = read(out, "timeline.html")

    assert 'data-id="task-000001" class="bar estimated' in body
    assert 'data-id="task-000002" class="bar unowned' in body
    # The patterns were declared and then referenced by nothing, so the class was
    # the whole of the encoding and the bar looked exactly like a commitment. The
    # legend draws itself from the same patterns, so only the plot is counted.
    plot = body[body.index("<svg width="):]
    # The rung these two bars stand on is whatever a record with nothing typed in
    # it opens at, which is the model's default and not a word to write down here:
    # this test named `shaping` and started failing on the commit that put a rung
    # below it, about a hatch that was drawing perfectly well. The subject is the
    # hatch, so the status is asked of the record rather than asserted.
    opens = guessed.status
    assert plot.count(f'class="mark mark-estimated st-{opens}"') == 1
    assert plot.count(f'class="mark mark-unowned st-{opens}"') == 1
    assert f"rect.mark-estimated.st-{opens} {{ fill: url(#hatch-estimated-st-{opens}); }}" in body
    assert f"rect.mark-unowned.st-{opens} {{ fill: url(#hatch-unowned-st-{opens}); }}" in body
    # The outline channel says one thing only, and it is not this one.
    assert "rect.estimated { stroke" not in body


def test_a_hatch_is_drawn_in_the_ink_of_the_bar_it_covers(rendered: Path):
    """One --hatch for all five statuses was only ever right while all five fills
    were one lightness. On the ladder the light theme's shelved bar is pale and
    the dark theme's done bar is nearly white, so a white hatch on either is no
    hatch at all — and a pattern resolves its custom properties against the tree
    it is declared in, never against the shape referencing it, so there is no way
    to say "the ink of whatever I am painting" with one pattern."""
    from openproj.render import STATUSES

    body = read(rendered, "timeline.html")

    assert "--hatch" not in body, "one hatch colour cannot serve the whole ladder"
    for status in STATUSES:
        for mark in ("estimated", "unowned"):
            pattern = re.search(
                rf'<pattern id="hatch-{mark}-st-{status}".*?</pattern>', body, re.S
            )
            assert pattern, (mark, status)
            assert f"stroke=\"var(--st-{status}-ink)\"" in pattern.group(0), (mark, status)
            assert (
                f"rect.mark-{mark}.st-{status} {{ fill: url(#hatch-{mark}-st-{status}); }}"
            ) in body


def test_the_timeline_orders_its_rows_by_containment(tmp_path: Path):
    """A project, then its pitches, then their tasks. Ordered by start date the
    rows said nothing the table's start column does not say better."""
    from datetime import date

    from openproj.model import Config, Pitch, Project, Task

    project = Project(id="proj-000001", kind="project", title="A project")
    pitch = Pitch(id="pitch-000001", kind="pitch", title="A pitch", owner="ann",
                  person_weeks=3.0, parent="proj-000001")
    task = Task(id="task-000001", kind="task", title="A task", owner="bo",
                person_weeks=1.0, parent="pitch-000001")
    other = Task(id="task-000002", kind="task", title="An unparented task", owner="cy",
                 person_weeks=1.0)
    index = build_index([task, other, pitch, project], Config(), date(2026, 8, 17))
    out = tmp_path / "tree"
    render_static(index, out)

    rows = re.findall(r'<div class="row" role="listitem" data-id="([^"]+)" data-depth="(\d+)"',
                      read(out, "timeline.html"))

    assert rows[:3] == [("proj-000001", "0"), ("pitch-000001", "1"), ("task-000001", "2")]
    assert ("task-000002", "0") in rows
    # Depth is an indent in the label column, not a fact the plot draws.
    assert 'style="padding-left: 32px"' in read(out, "timeline.html")


def test_a_child_stays_indented_when_its_parent_is_not_drawn(tmp_path: Path):
    """Indentation is containment, not adjacency: a task that jumps to the left
    margin when its parent falls out of the window reads as a task that changed
    parents."""
    from datetime import date

    from openproj.model import Config, Pitch, Task

    # A shelved pitch has no span at all, so it is never a row.
    parent = Pitch(id="pitch-000001", kind="pitch", title="Parked", status="shelved",
                   owner="ann", person_weeks=2.0)
    child = Task(id="task-000001", kind="task", title="Still live", owner="bo",
                 person_weeks=1.0, parent="pitch-000001")
    index = build_index([parent, child], Config(), date(2026, 8, 17))
    out = tmp_path / "orphaned"
    render_static(index, out)
    body = read(out, "timeline.html")

    assert 'data-id="pitch-000001" class="bar' not in body
    assert re.search(r'data-id="task-000001" data-depth="1"', body)


def test_a_same_day_span_is_still_wide_enough_to_hit(tmp_path: Path):
    """At the fitted day width a one-day span was 1.6px of target. Nobody hovers
    that and nobody clicks it either."""
    from datetime import date

    from openproj.model import Config, Task

    brief = Task(id="task-000001", kind="task", title="A day of it", owner="ann",
                 person_weeks=0.2)
    index = build_index([brief], Config(), date(2026, 8, 17))
    out = tmp_path / "brief"
    render_static(index, out)

    widths = re.findall(r'<rect data-id="[^"]+"[^>]*width="([\d.]+)"',
                        read(out, "timeline.html"))

    assert widths and all(float(width) >= 3 for width in widths)


def test_a_bar_is_exactly_as_wide_as_the_span_the_scheduler_computed(tmp_path: Path):
    """The geometry of a bar is the only thing the chart says.

    Nothing pinned it, so a `.bar { width: 140px; height: 8px }` written for the
    capacity meter drew every rect on the timeline at 140x8 — `width` and `height`
    are CSS geometry properties on an SVG2 rect and an author rule beats the
    presentation attribute. The chart still looked like a Gantt and had stopped
    being about dates. Both directions, because one shared width is a chart where
    a two-month build and a one-day task are the same picture.
    """
    from datetime import date

    from openproj.model import Config, Task
    from openproj.render import _MIN_BAR_PX, render_timeline

    zoom = 2.0    # a drawn day width, so the arithmetic below is exact
    slog = Task(id="task-000001", kind="task", title="A long one", owner="ann",
                person_weeks=8)
    brief = Task(id="task-000002", kind="task", title="A day of it", owner="bob",
                 person_weeks=0.2)
    index = build_index([slog, brief], Config(), date(2026, 8, 17))
    body = render_timeline(index, zoom=zoom)

    drawn = dict(re.findall(r'<rect data-id="([^"]+)"[^>]*width="([\d.]+)"', body))
    assert set(drawn) == set(index.spans)

    for record_id, span in index.spans.items():
        days = (span.end - span.start).days + 1        # inclusive of both ends
        assert float(drawn[record_id]) == max(_MIN_BAR_PX, zoom, days * zoom), record_id

    # Said again as two numbers rather than a formula: eight weeks and one day are
    # not the same width, and neither of them is the meter's 140.
    assert float(drawn["task-000001"]) == 108.0
    assert float(drawn["task-000002"]) == 3.0

    # The rect keeps its height too.
    assert re.search(r'<rect data-id="task-000001"[^>]*height="14"', body)

    # And the attribute is only half the story: the widths above were right all
    # along and the chart was still wrong, because CSS geometry outranks a
    # presentation attribute. So no selector on this page may reach a bar without
    # naming what kind of element it is — `span.bar` for the meter, `rect.bar`
    # for a bar, never a bare `.bar` that is both.
    style = re.search(r"<style>(.*?)</style>", body, re.S).group(1)
    style = re.sub(r"/\*.*?\*/", " ", style, flags=re.S)   # a comment is not a selector
    # Split rather than `re.findall(r"([^{}]*)\{", style)`, which is the same
    # answer and took 13.4 of this test's 13.6 seconds. `[^{}]*` runs to the
    # closing `}` of a declaration block, fails the `\{`, and backtracks a
    # character at a time from every start position inside the block — quadratic
    # in the block length, over a 110 KB inlined stylesheet. Splitting on `{`
    # leaves each chunk holding the text before one brace; the last brace such a
    # chunk can contain is a `}`, so what follows it is exactly the selector the
    # regex captured. Checked: same 318 strings, in the same order, in 0.1ms.
    unqualified = [
        selector.strip()
        for chunk in style.split("{")[:-1]
        for selector in chunk.rsplit("}", 1)[-1].split(",")
        if re.search(r"(^|[\s>+~])\.bar\b", selector.strip())
    ]
    assert not unqualified, unqualified


def test_the_timeline_draws_cycle_boundaries_and_today(rendered: Path):
    body = read(rendered, "timeline.html")
    assert 'class="today"' in body
    assert 'class="cycle-rule"' in body
    assert "cycle 36" in body


def test_a_cycle_gets_a_band_of_its_own_above_the_months(rendered: Path):
    """The cycle label was drawn at y=10 and the month label at y=18 inside one
    26px strip, so a cycle closing near the first of a month wrote one word over
    the other. And the one line every reader looks for was unlabelled."""
    body = read(rendered, "timeline.html")

    assert 'class="cycle-band"' in body
    band = int(re.search(r'<line class="band-rule" x1="0" y1="(\d+)"', body).group(1))
    cycle_label = float(re.search(r'<text class="cycle-label"[^>]*y="([\d.]+)"', body).group(1))
    month_label = float(re.search(r'<text class="month-label"[^>]*y="([\d.]+)"', body).group(1))
    month_rule = float(re.search(r'<line class="month-rule" x1="[\d.]+" y1="([\d.]+)"',
                                 body).group(1))

    assert cycle_label < band < month_label
    assert month_rule == band
    assert re.search(r'<text class="today-label"[^>]*>today</text>', body)


def test_a_bar_carries_what_it_is_holding(rendered: Path, seed_index: Index):
    """A bar said its dates nowhere. The only hoverable thing on it was a native
    tooltip with one sentence about why it starts when it does."""
    body = read(rendered, "timeline.html")
    payload = json.loads(
        re.search(r'<script id="bars" type="application/json">(.*?)</script>', body, re.S).group(1)
    )
    drawn = re.findall(r'<rect data-id="([^"]+)"', body)

    assert set(payload["rows"]) == set(drawn)
    row = payload["rows"][drawn[0]]
    for key in ("title", "status", "owner", "weeks", "start", "end", "tip", "predicates"):
        assert key in row, key
    assert payload["human"]["in_progress"] == "In progress"
    assert 'id="card"' in body


def test_the_timeline_names_every_colour_it_draws(rendered: Path):
    """A colour with no key is a colour the reader has to guess at, and the pink
    outline meant something nothing on the page named."""
    from openproj.render import STATUS_GLYPH

    body = read(rendered, "timeline.html")
    legend = re.search(r'<ul class="legend" aria-label="What a bar marking means">(.*?)</ul>',
                       body, re.S).group(1)

    # STATUSES and not the five words written out, which is what this said until
    # the ladder grew a sixth rung and this test went on being green about a page
    # it was no longer checking all of. A key is owed to every status a record can
    # hold, so the list to walk is the vocabulary itself.
    for status in STATUSES:
        assert f'<span class="swatch st-{status}" aria-hidden="true">' in body, status
        assert STATUS_GLYPH[status] in body, status
    assert "appetite assumed" in legend
    assert "nobody on it" in legend
    assert "overruns its cycle" in legend
    assert "today" in legend
    assert "a cycle closes" in legend


def test_every_explanation_reaches_the_reader(rendered: Path, seed_index: Index):
    """The per-date explanation is the trust mechanism, not decoration: the first
    unexplained surprising date is when people stop believing the timeline."""
    body = read(rendered, "timeline.html")
    assert seed_index.explanations
    for record_id, explanation in seed_index.explanations.items():
        assert explanation.text in body, record_id


def test_a_span_less_record_is_listed_but_not_drawn(rendered: Path, seed_index: Index):
    """Done and shelved work has no span. It still belongs in the table — dropping
    it would make the board lie about what exists."""
    payload = json.loads(
        re.search(
            r'<script id="payload" type="application/json">(.*?)</script>',
            read(rendered, "table.html"),
            re.S,
        ).group(1)
    )
    assert payload["rows"]["task-3d84e9"]["start"] is None
    assert 'data-id="task-3d84e9" class="bar' not in read(rendered, "timeline.html")


# --- the detail page -------------------------------------------------------


def test_a_detail_page_exists_for_every_record(rendered: Path, seed_index: Index):
    """The whole premise is that the shaping doc IS the record. A viewer that
    never shows the body is a viewer of the frontmatter only."""
    body = read(rendered, "detail.html")
    # `records`, not the plan: this is the one page every kind gets.
    for record_id in seed_index.records:
        assert f'id="{record_id}"' in body, record_id


def test_the_detail_page_opens_as_an_index_not_a_wall_of_text(rendered: Path, seed_index: Index):
    """With no hash the page lists what exists; with a hash it shows exactly one
    document. Showing all seventeen bodies at once is not a detail view."""
    body = read(rendered, "detail.html")
    assert 'class="toc"' in body
    for record_id in seed_index.records:
        # `detail.html#id` in a rendered file, `/detail/id` on the server: the link
        # comes from Links either way, so the index cannot drift from the routes.
        assert f'href="detail.html#{record_id}"' in body, record_id
    # The script must hide every article unless one is selected.
    assert "article.style.display = match ? '' : 'none'" in body


def test_the_detail_page_renders_the_shaping_doc_as_markdown(rendered: Path):
    body = read(rendered, "detail.html")
    assert "<h2>" in body, "markdown headings should render as headings"
    # Line-initial only: `## Appetite` inside a code span is correctly rendered
    # markdown, not leaked source.
    assert not re.search(r"^## ", body.split("<script")[0], re.M), "raw markdown leaked"


def test_the_detail_page_shows_the_derived_dates_and_the_explanation(
    rendered: Path, seed_index: Index
):
    body = read(rendered, "detail.html")
    record_id, explanation = next(iter(seed_index.explanations.items()))
    assert explanation.text in body
    assert seed_index.spans[record_id].start.isoformat() in body


@pytest.fixture
def demo_rendered(demo_root: Path, tmp_path: Path) -> tuple[Path, Index]:
    """The shipped demo, which unlike the frozen golden corpus carries real PR
    references and the dependency diamond these tests are about."""
    from datetime import date

    records, config, _ = load_repo(demo_root)
    index = build_index(records, config, date(2026, 8, 17))
    out = tmp_path / "demo"
    render_static(index, out)
    return out, index


def test_pr_references_become_links_that_resolve(demo_rendered: tuple[Path, Index]):
    """A dead PR reference teaches people the field is decorative."""
    out, index = demo_rendered
    refs = {ref for e in index.plan.values() for ref in e.prs}
    assert refs, "the demo corpus should carry PR references"
    detail = read(out, "detail.html")
    for ref in refs:
        repo, number = ref.split("#")
        assert f'href="https://github.com/{repo}/pull/{number}"' in detail, ref


def test_every_view_links_to_the_detail_page(rendered: Path):
    assert 'detail.html#' in read(rendered, "table.html")
    for name in ("graph.html", "timeline.html"):
        assert "detail.html#" in read(rendered, name), name


def test_the_detail_page_links_dependencies_both_ways(demo_rendered: tuple[Path, Index]):
    """Blocked-by and blocks are the two questions a reader actually has, and
    `blocks` exists nowhere in the files — it is only ever derived."""
    out, _ = demo_rendered
    body = read(out, "detail.html")
    assert "Blocked by" in body
    assert "Blocks" in body
    assert 'href="detail.html#task-0d1001"' in body


def test_the_suggestion_list_offers_names_and_not_sentences(seed_index: Index):
    """A login has no comma in it.

    An early version of the table wrote a whole comma-separated string into a list
    field, and the picker then offered `jackdawrie, hoopoegrove` as though it were one
    person — so garbage already in the corpus became garbage suggested to whoever
    edited next. The write path is fixed; this stops the spread either way.
    """
    from openproj.model import Task
    from openproj.render import _suggestions

    # Into `records`, because that is the map `_suggestions` gathers people
    # from — a name polluted into the plan alone would never reach the list,
    # and the assertion below would pass with the filter deleted.
    polluted = dict(seed_index.records)
    polluted["task-ffffff"] = Task(
        id="task-ffffff", kind="task", title="Bad", reviewers=["jackdawrie, hoopoegrove"]
    )
    suggestions = _suggestions(seed_index.model_copy(update={"records": polluted}))

    assert all("," not in person["value"] for person in suggestions["people"])


def test_a_cycle_number_is_offered_the_way_every_other_reference_is(seed_index: Index):
    """It was the one reference on the form typed from memory, and it is a bare
    number: nothing about `34` says whether it is the cycle running now. Every
    cycle the plan names, newest first, labelled with the window somebody is
    actually agreeing to."""
    from openproj.render import _cycle_numbers, _suggestions

    cycles = _suggestions(seed_index)["cycles"]

    assert [c["value"] for c in cycles] == [
        str(n) for n in sorted(_cycle_numbers(seed_index), reverse=True)
    ]
    dated = next(c for c in cycles if int(c["value"]) in seed_index.cycles)
    starts, ends = seed_index.cycles[int(dated["value"])]
    # In the app's own format and not the file's: this label is read by somebody
    # choosing a cycle from a popup, and every date beside it on that page is
    # `dd.mm.YYYY`.
    from openproj.render.tokens import _read_date

    assert dated["label"] == f"{_read_date(starts)} → {_read_date(ends)}"
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} → \d{2}\.\d{2}\.\d{4}", dated["label"])


# --- the people page --------------------------------------------------------


def test_the_people_page_lists_everyone_the_plan_names(rendered: Path, seed_index: Index):
    """Built from the fields, not from the roster.

    A page that reads `config/people.yaml` would list somebody who has nothing to
    do and miss whoever was assigned this morning — the plan itself is the only
    record of who is on the hook for what.
    """
    body = read(rendered, "people.html")
    named = {
        login
        for record in seed_index.plan.values()
        for field in ("owner", "assignees", "reviewers")
        for login in (
            lambda v: v if isinstance(v, list) else [v] if v else []
        )(getattr(record, field, None))
    }

    assert named
    for login in named:
        assert login in body, login


def test_a_person_row_says_which_hat_they_are_wearing(rendered: Path):
    """Owning something and reviewing it are different obligations, and the point
    of the page is telling somebody which of theirs is which."""
    body = read(rendered, "people.html")

    for role in ("owner", "assignee", "reviewer"):
        assert f'class="role">{role}<' in body, role


def test_every_person_row_links_to_the_record(rendered: Path, seed_index: Index):
    body = read(rendered, "people.html")
    owned = [i for i, e in seed_index.plan.items() if e.owner]

    assert owned
    for record_id in owned:
        assert f'href="detail.html#{record_id}"' in body, record_id


def test_the_people_page_is_alphabetical_and_filterable(rendered: Path):
    """Sorted by login, and filterable the way the table is.

    Alphabetical because there is no better default: any other order — most work
    first, say — makes finding one named person a scan rather than a lookup.

    `data-field` and not `data-attr`: the control bar is the shared one now, so a
    dropdown means the same thing and writes the same query-string key on every
    page that has one.
    """
    body = read(rendered, "people.html")
    logins = re.findall(r'<tbody class="person" data-login="([^"]+)"', body)

    assert logins == sorted(logins, key=str.lower)
    # Case-folded, and the corpus has to hold both cases or a plain `sorted()`
    # would pass this while putting every capitalised login ahead of the rest.
    assert logins != sorted(logins), "the corpus no longer mixes case; this proves nothing"
    assert '<input id="q"' in body
    for attribute in ("role", "kind", "status"):
        assert f'<div class="facet" data-field="{attribute}"' in body, attribute
    assert re.search(r'<tr data-role="[^"]+" data-kind="[^"]+" data-status="[^"]+"', body)


def test_the_people_page_is_one_table_with_one_header(rendered: Path):
    """F22. Fifteen people meant fifteen tables, each sizing its own columns, so
    `status` began at a different place for every person and the page could not be
    read down a column. One table, the person as a group row inside it, one
    header — and the header sticks, because the page is longer than the screen and
    a column heading that scrolled away leaves five unlabelled columns.
    """
    body = read(rendered, "people.html")
    people = re.findall(r'<tbody class="person"', body)
    table = re.search(r"<table id=\"roles\">.*?</table>", body, re.S).group(0)

    assert len(people) > 5, "the corpus names enough people for this to matter"
    assert body.count("<table") == 1, "one table, not one per person"
    assert body.count("<thead>") == 1
    # Every person is a tbody inside that one table rather than a section beside it.
    assert table.count('<tbody class="person"') == len(people)
    assert len(re.findall(r'<tr class="group', table)) == len(people)
    assert '<th colspan="5" scope="colgroup">' in table
    assert "#roles thead th { position: sticky; top: 0;" in body


def test_a_people_row_wears_the_chips_the_table_wears(rendered: Path):
    """F3. The one view people live in was the one view with no colour language at
    all: `in_progress` in plain text beside `task` in plain text, while the graph
    and the timeline had been drawing both in tokens for months."""
    body = read(rendered, "people.html")

    assert '<span class="chip st-in_progress">In progress</span>' in body
    assert '<span class="chip kind-task">Task</span>' in body
    # The identifier stays in `data-status`, where the filter reads it, and never
    # reaches a reader.
    assert ">in_progress<" not in body


def test_one_persons_rows_do_not_run_into_the_next(rendered: Path):
    """Fifteen people share one table so the status column can be read down it,
    and the price was that a person's name began on the line the previous
    person's last row ended on.

    Space, and not a rule: every row here already ends in a hairline and the
    group row already has a ground of its own, so a third boundary between two
    things that are each already bounded is noise. It is a thick border in the
    page's own colour, which a collapsed table resolves in favour of the wider of
    the two borders it joins — so it eats the hairline above it and leaves a
    clean gap rather than a gap with a line in it.
    """
    body = read(rendered, "people.html")

    assert body.count('<tbody class="person"') > 1, "there is something to sit between"
    gap = re.search(
        r"tbody\.person \+ tbody\.person > tr\.group > th \{ border-top: ([^;]+); \}", body
    )
    assert gap, "the gap belongs between people, so the first group must not open with one"
    size, style, colour = gap.group(1).split()
    assert (style, colour) == ("solid", "var(--bg)"), gap.group(1)
    assert float(size.removesuffix("rem")) >= 0.5, "space somebody can actually see"
    # And it is the only top border anything on this page draws in the table, so
    # nothing puts a line where the space is. The hover card's own rule is
    # excluded by name: it is a popup that is not on the page until somebody
    # points at a row, and it draws its rule between two parts of itself.
    drawn = [
        rule
        for rule in re.findall(r"([-#.\w ]+) \{ [^}]*border-top: ([^;]+);", body)
        if not rule[0].strip().startswith("#card")
    ]
    assert [rule[1] for rule in drawn] == [gap.group(1)], drawn


def test_a_person_is_weighed_in_weeks_and_not_in_things(demo_rendered: tuple[Path, Index]):
    """F23. "1 as owner, 2 as assignee, 12 as reviewer" adds a half-hour review to
    a six-week build and calls the sum a workload.

    The weeks come from `index.load`, which is the function the cycle page bets
    with, so the two pages cannot reach different answers about the same person —
    and the meter is the one the cycle page draws, so they cannot disagree about
    what full looks like either.
    """
    out, index = demo_rendered
    body = read(out, "people.html")
    held, plan = index.load(37), index.plans[37]
    who = max(plan.availability, key=lambda login: held.get(login, 0.0))
    capacity = plan.capacity(who, index.nominal_availability)
    group = re.search(rf'<tbody class="person" data-login="{who}">.*?</tr>', body, re.S).group(0)

    assert index.cycles[37][0] <= index.today <= index.cycles[37][1], "37 is the live cycle"
    assert "The weeks are cycle 37's" in body
    assert held[who] and capacity
    assert f'<b class="num held">{held[who]:.1f}</b>' in group
    assert f'<b class="num">{capacity:.1f}</b>' in group
    percent = min(100, round(100 * held[who] / capacity))
    assert f'<span class="bar"><span style="width: {percent}%">' in group
    assert ".bar > span { display: block; height: 100%; background: var(--accent); }" in body
    # Weeks lead and the counts follow: the counts are a way into the table now,
    # not the answer to "how much is on this person".
    assert group.index('class="load"') < group.index('class="tally"')


def test_a_person_over_their_availability_says_so_in_the_group_row(
    demo_rendered: tuple[Path, Index],
):
    """The number the room acts on. Over capacity is the one state on this page
    that changes what happens next, so it is a colour and not only a ratio."""
    out, index = demo_rendered
    body = read(out, "people.html")
    held, plan = index.load(37), index.plans[37]
    over = [
        who for who in plan.availability
        if held.get(who, 0.0) > plan.capacity(who, index.nominal_availability)
    ]

    assert over, "the demo overbets somebody"
    for who in over:
        group = re.search(rf'<tbody class="person" data-login="{who}">.*?</tr>', body, re.S)
        assert '<tr class="group over">' in group.group(0), who
    assert ".over span.bar > span { background: var(--danger); }" in body
    assert "tr.group.over .load b.held { color: var(--danger); }" in body


def test_weeks_bet_into_another_cycle_are_counted_beside_this_one(
    demo_rendered: tuple[Path, Index],
):
    """One cycle is the honest denominator — availability is recorded per cycle —
    but somebody booked solid in the next one reads as idle if that is the only
    cycle the page ever asks about."""
    out, index = demo_rendered
    body = read(out, "people.html")
    elsewhere: dict[str, float] = {}
    for number in set(index.cycles) - {37}:
        for login, weeks in index.load(number).items():
            elsewhere[login] = elsewhere.get(login, 0.0) + weeks

    assert elsewhere, "the demo bets work into more than one cycle"
    for login, weeks in elsewhere.items():
        group = re.search(rf'<tbody class="person" data-login="{login}">.*?</tr>', body, re.S)
        assert re.search(rf'\+<span class="num">{weeks:.1f}</span>\s+weeks in other cycles',
                         group.group(0)), login


def test_a_cycle_with_no_record_is_weeks_bet_against_no_roster(unrecorded_cycle: Index):
    """A cycle dated in config with no record behind it has availability for
    nobody. "0.0 of 0.0 weeks" would be a meter reading zero; what is true is that
    there is nothing to bet against.

    It took `rendered` while every cycle in the corpus was unrecorded. Cycle 37 has
    a record now and is the current one at the fixture's `today`, so the case is
    asked of cycle 36 — see `unrecorded_cycle`. The corpus lost nothing: four of
    its six cycles are still dated and unwritten.
    """
    from openproj.render import render_people

    body = render_people(unrecorded_cycle)

    assert "has no record, so there is no availability to bet it against" in body
    assert "weeks bet against no roster" in body
    assert 'class="bar"' not in body, "no meter without something to measure against"


def test_a_cycle_with_a_record_bets_its_weeks_against_the_roster(rendered: Path):
    """The other half of the branch above, and nothing could reach it until the
    corpus grew cycle records: with `index.plans` empty every capacity was 0.0, so
    the meter was never drawn on this page by any test, and the stranger line —
    somebody holding weeks in a cycle whose roster does not name them — could not
    happen at all."""
    body = read(rendered, "people.html")

    assert "has no record, so there is no availability to bet it against" not in body
    assert 'class="bar"' in body, "a roster is something to measure against"
    assert "weeks bet, and not on cycle 37's roster" in body


def test_every_person_links_to_the_table_filtered_by_them(rendered: Path):
    """F24. A name on this page was a heading, and the question a name raises —
    show me all of it — is a filter the table already has. The link opens the most
    answerable role somebody actually holds, because a link to what a person owns
    lands on an empty table for a person who owns nothing, and a link that lands on
    nothing teaches people the link is broken."""
    from openproj.render import _FILTER_JS, _ROLE_FILTER, _ROLE_ORDER

    body = read(rendered, "people.html")
    groups = re.findall(r'<tbody class="person" data-login="[^"]+">.*?</tbody>', body, re.S)

    assert groups
    for group in groups:
        login = re.search(r'data-login="([^"]+)"', group).group(1)
        roles = set(re.findall(r'<tr data-role="(\w+)"', group))
        opens = next((r for r in _ROLE_ORDER if r in roles and r in _ROLE_FILTER), None)
        # Every role is a table facet now that the shaper row retired with
        # `shaped_by`, so a person on the page always has somewhere to open.
        assert opens is not None, login
        assert f'<a class="who" href="table.html?{_ROLE_FILTER[opens][0]}={login}"' in group, login
        # And each count is the way into the rows it counted.
        for role in roles & set(_ROLE_FILTER):
            assert f'href="table.html?{_ROLE_FILTER[role][0]}={login}">' in group, (login, role)
    # The keys are the table's own, or the link opens a table that filters nothing.
    for field, _ in _ROLE_FILTER.values():
        assert f"'{field}'" in _FILTER_JS, field


def test_the_people_page_says_when_its_filters_match_nothing(rendered: Path):
    """F1. Filtered to nothing, the page hid every section and left a control bar
    over a void — which reads as a broken app rather than as a filter that matched
    nothing. The message goes inside the table body, where the rows were."""
    body = read(rendered, "people.html")
    empty = re.search(r'<tbody id="nothing"[^>]*>.*?</tbody>', body, re.S).group(0)

    assert re.search(r'<tbody id="nothing" hidden>', body), "hidden while there is anything"
    assert '<tr class="nothing"><td colspan="5">' in empty, "inside the body, not beside it"
    assert "No person matches these filters." in empty
    assert '<button type="button" id="clear-filters">Clear filters</button>' in empty
    assert "NOTHING.hidden = visible > 0;" in body
    assert "if (CLEAR) CLEAR.onclick = clearFilters;" in body


def test_a_plan_that_names_nobody_says_so_instead_of_offering_a_clear(tmp_path: Path):
    """The emptiness decides what to do about it, and there is nothing to clear on
    a plan nobody is named in."""
    from datetime import date

    from openproj.model import Config
    from openproj.render import render_people

    body = render_people(build_index([], Config(), date(2026, 8, 17)))

    assert "Nobody is named in this plan yet." in body
    assert "No person matches these filters." not in body
    assert '<button type="button" id="clear-filters">' not in body


def test_every_filter_offers_a_way_back_to_everything(rendered: Path):
    """`<option value="">` used to repeat the field name, so a chosen filter had no
    "off" — the way back looked like the label, not like a choice. The field name
    moved to a label beside the control and the empty option says `all`.

    Asked of the parsed document rather than of a regex over the page. The
    shell's stylesheet is inlined into every page, so a CSS comment naming a
    `<select>` put the characters of an opening tag into the served bytes and
    the regex read the next real dropdown's options as that comment's contents —
    the failure `tests/pages.py` was written for, arriving through a new door.
    """
    for page in ("table.html", "people.html", "graph.html"):
        for options in selects(read(rendered, page)):
            assert options[:1] == [("", "all")], options[:3]


# --- the timeline window ----------------------------------------------------


def counts(html: str) -> tuple[int, float]:
    bars = re.findall(r'<rect data-id="[^"]+"[^>]*width="([\d.]+)"', html)
    width = float(re.search(r'<svg width="([\d.]+)"', html).group(1))
    return len(bars), width


def test_a_narrowed_window_clips_bars_rather_than_dropping_them(seed_index: Index):
    """A row that vanishes when you narrow the dates reads as work that went away.

    Anything overlapping the window keeps its row and is drawn to the edge; only
    work entirely outside it leaves, which is the one case where its absence means
    what it looks like.
    """
    from datetime import date

    from openproj.render import render_timeline

    whole = render_timeline(seed_index)
    window = render_timeline(seed_index, window=(date(2026, 9, 1), date(2026, 9, 30)))
    spans = seed_index.spans
    overlapping = sum(
        1
        for span in spans.values()
        if not span.unscheduled and span.end >= date(2026, 9, 1) and span.start <= date(2026, 9, 30)
    )

    assert counts(window)[0] == overlapping
    assert counts(window)[0] < counts(whole)[0]
    assert 'value="2026-09-01"' in window and 'value="2026-09-30"' in window


def test_zoom_is_drawn_rather_than_stretched(seed_index: Index):
    """A day width the server renders at, not a transform the browser applies.

    Scaling the finished SVG would stretch every month label and rounded corner
    with it, so zooming has to change the geometry — which shows up as a wider
    drawing holding the same number of bars, and unchanged text.
    """
    from openproj.render import render_timeline

    near, far = render_timeline(seed_index, zoom=14.0), render_timeline(seed_index, zoom=2.0)

    assert counts(near)[0] == counts(far)[0]
    assert counts(near)[1] > counts(far)[1] * 3
    assert "scale(" not in near
    assert re.search(r'<text class="month-label"[^>]*>\w+', near)


def test_a_window_that_excludes_today_draws_no_today_line(seed_index: Index):
    """Clamping it to the edge would put "now" on a date it is not on."""
    from datetime import date

    from openproj.render import render_timeline

    past = render_timeline(seed_index, window=(date(2026, 1, 1), date(2026, 2, 1)))

    assert 'class="today"' not in past
    assert 'class="today"' in render_timeline(seed_index)


def test_the_date_boxes_hold_the_window_on_screen(seed_index: Index):
    """They rendered empty under a sentence naming the dates being drawn, so the
    controls disagreed with the picture. The boxes are what answer "am I looking
    at everything?" now — the sentence used to say the same dates a third time,
    after the boxes and the axis had both already said them."""
    from datetime import date

    from openproj.render import render_timeline

    whole = render_timeline(seed_index)
    origin = re.search(r'name="from" value="([\d-]+)"', whole).group(1)
    last = re.search(r'name="to" value="([\d-]+)"', whole).group(1)

    assert origin and last, "the boxes hold the window the chart is drawing"
    assert "Showing the whole plan" not in " ".join(whole.split()), (
        "the axis and the boxes say the dates; the sentence says how to move"
    )
    assert "Drag sideways or scroll" in " ".join(whole.split())

    windowed = render_timeline(seed_index, window=(date(2026, 9, 1), date(2026, 9, 30)))
    assert 'name="from" value="2026-09-01"' in windowed
    assert "a window of the plan" in " ".join(windowed.split())
    # Apply was a button and Reset a bare link, which reads as one control and one
    # afterthought.
    assert '<button type="submit" class="button primary">Apply</button>' in whole
    assert 'class="button reset"' in whole


def test_the_timeline_filters_with_the_same_bar_the_table_does(rendered: Path):
    """The README has always said three views filter the same plan the same way.
    Two of them do now, and the third read the same query string for its dates
    and ignored it for everything else."""
    body = read(rendered, "timeline.html")

    assert '<div class="facet" data-field="status">' in body
    assert '<div class="facet" data-field="predicate">' in body
    assert "function matches(row)" in body
    assert "addEventListener('openproj:filter', applyFilter)" in body
    assert 'id="clear-filters"' in body
    # The window is the server's and the facets are the page's, and a plain submit
    # would carry only the form's own fields.
    assert "params.set(control.name, control.value)" in body


def test_an_empty_timeline_says_which_kind_of_empty_it_is(tmp_path: Path):
    """A blank rectangle is the same picture for a plan with nothing in it, a plan
    with nothing scheduled, and a filter that matched nothing. Which one it is
    decides what to do next."""
    from datetime import date

    from openproj.model import Config, Task

    empty = build_index([], Config(), date(2026, 8, 17))
    render_static(empty, tmp_path / "empty")
    body = read(tmp_path / "empty", "timeline.html")
    assert "This plan has no records yet." in body
    assert '<button type="button" id="clear-filters" hidden>' in body

    parked = Task(id="task-000001", kind="task", title="Parked", status="shelved")
    render_static(build_index([parked], Config(), date(2026, 8, 17)), tmp_path / "parked")
    parked_body = read(tmp_path / "parked", "timeline.html")
    assert "Nothing in this plan has dates." in parked_body
    assert '<div class="tl" data-fills hidden>' in parked_body

    live = Task(id="task-000002", kind="task", title="Live", owner="ann", person_weeks=1.0)
    index = build_index([live], Config(), date(2026, 8, 17))
    render_static(index, tmp_path / "live")
    live_body = read(tmp_path / "live", "timeline.html")
    assert "No record matches these filters." in live_body
    assert '<button type="button" id="clear-filters">Clear' in live_body

    # A window with nothing in it is the dates' fault, and clearing a filter would
    # not bring a single bar back.
    from openproj.render import render_timeline

    elsewhere = render_timeline(index, window=(date(2027, 1, 1), date(2027, 2, 1)))
    assert "Nothing is scheduled in this window." in elsewhere
    assert '<button type="button" id="clear-filters" hidden>' in elsewhere


def test_a_month_names_its_year_only_when_the_year_changes(seed_index: Index):
    """"Aug 2026" on every tick spends a third of a narrow month restating what
    the tick before it already said."""
    from openproj.render import render_timeline

    labels = re.findall(r'<text class="month-label"[^>]*>([^<]+)</text>',
                        render_timeline(seed_index))

    assert labels
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{4}", labels[0]), labels[0]
    assert [label for label in labels[1:] if " " in label] == [
        label for label in labels[1:] if label.startswith("Jan ")
    ]


def test_opening_a_node_takes_two_clicks(rendered: Path):
    """A single tap is also the first half of drawing an edge, and on a graph you
    drag around, one stray click should not navigate away from the page."""
    body = read(rendered, "graph.html")

    assert "cy.on('dbltap', 'node'" in body
    navigating = re.search(r"cy\.on\('tap', 'node'.*?\n\}\);", body, re.S).group(0)
    assert "location.href" not in navigating, "a single tap must not navigate"


def test_drawing_a_dependency_does_not_write_one(rendered: Path):
    """Edges accumulate in the browser and are committed together.

    Saving on the second click meant one round trip and one full re-layout per
    edge, so drawing five moved the graph four times underneath the person
    drawing them.
    """
    body = read(rendered, "graph.html")
    tap = re.search(r"cy\.on\('tap', 'node'.*?\n\}\);", body, re.S).group(0)

    assert "fetch(" not in tap, "a click must not write"
    assert "location.reload" not in tap, "a click must not re-lay-out the graph"
    assert "classes: 'pending'" in tap


def test_a_batch_of_edges_is_saved_against_the_commit_before_it(rendered: Path):
    """Each write moves HEAD. Reusing the page's base for the second record would
    make it a conflict against a commit the same button had just created."""
    body = read(rendered, "graph.html")
    save = re.search(r"SAVE\.onclick.*?\n  \};", body, re.S).group(0)

    assert "base.value = answer.commit" in save
    assert "already saved" in save, "a partial failure must say what was written"


def test_edges_turn_at_right_angles_and_are_drawn_beneath_the_boxes(rendered: Path):
    """The drawing's whole design, and the smallest statement of it.

    The shape is the same one a router of ours used to compute — right angles
    with rounded corners — and cytoscape computes it now, from
    `taxi-direction: auto`. The old code overrode that per edge with a guess at
    which way each should turn, on top of bends it placed itself; every fix for
    those bends was found by screenshot rather than by test, and the fourth one
    was the last. jcanton, 2026-08-21, having compared a gallery of every curve
    style on the real plan: "the same but rounded".

    `bottom` is the other half and the one that makes it work: under the boxes,
    a line that crosses a card passes beneath it. What the drawing does with that
    is `test_graph_layout.test_an_edge_that_crosses_a_card_is_drawn_under_it`,
    which reads pixels. This is the stylesheet's half.
    """
    body = read(rendered, "graph.html")

    assert "'curve-style': 'round-taxi'" in body
    assert "'taxi-direction': 'auto'" in body
    assert "'z-compound-depth': 'bottom'" in body
    assert "'curve-style': 'bezier'" not in body
    # Asked of the page's own style block and not of the file: the vendored
    # cytoscape bundle is inlined here and names every curve style it supports,
    # so a search over the bytes finds the library's vocabulary rather than this
    # page's settings.
    ours = re.search(r"const cy = cytoscape\(\{.*?\n\}\);", body, re.S)
    assert ours, "the cytoscape call is not where this test thinks it is"
    assert "taxi-direction" in ours.group(0)
    assert "segment-weights" not in ours.group(0), (
        "a bend of our own is being placed again"
    )


def test_the_index_is_grouped_in_the_order_work_moves(tmp_path: Path):
    """thinking first, dropped last — `shaping` first until the ladder grew a rung
    below it, and this line said so for one commit longer than it was true.
    Alphabetical put `done` at the top, which is the one group nobody opens the
    index looking for — and, once notes arrived, put a note's terminal state
    above its live one.

    Grouped by `state()`, never the stored status: `_TOC_LADDER` is built from
    `NOTE_STATES` precisely so `promoted` has a heading, and grouping by the
    stored word filed every promoted note under "Thinking" and left that rung
    unreachable — this test pinned the wrong grouping for as long as it read
    `r.status` too.

    Its own corpus, not `seed_root`: the frozen golden corpus deliberately
    holds no inbox records (its docstring in conftest.py forbids it moving),
    so rendering it can never show a derived state — which is exactly how the
    first version of this test asserted "Promoted" over a page that could not
    contain it. This corpus is the smallest one whose states cover EVERY rung
    of `_TOC_LADDER`, and it reaches two of them only by derivation: no file
    stores `promoted` (`NOTE_STATUS` cannot) or `in_progress`, so those two
    headings exist on this page only if the TOC asks `state()` — the note's
    through `became`, the issue's through `pitched_into`.
    """
    from openproj.model import parse_text
    from openproj.render import _TOC_LADDER, _human

    files = {
        "projects/proj-f00001.md": (
            "---\nid: proj-f00001\nkind: project\ntitle: Ladder project\n"
            "status: shaping\n---\n\nx\n"),
        "pitches/pitch-f00001.md": (
            "---\nid: pitch-f00001\nkind: pitch\ntitle: Ready pitch\n"
            "parent: proj-f00001\nstatus: ready\nowner: ann\nreviewers: [bo]\n"
            "person_weeks: 1\n---\n\nx\n"),
        "pitches/pitch-f00002.md": (
            "---\nid: pitch-f00002\nkind: pitch\ntitle: Shelved pitch\n"
            "parent: proj-f00001\nstatus: shelved\nperson_weeks: 1\n---\n\nx\n"),
        "tasks/task-f00001.md": (
            "---\nid: task-f00001\nkind: task\ntitle: Done task\n"
            "parent: pitch-f00001\nstatus: done\nowner: ann\nreview_waived: true\n"
            "person_weeks: 1\n---\n\nx\n"),
        "notes/note-f00001.md": (
            "---\nid: note-f00001\nkind: note\ntitle: Live thought\n"
            "status: thinking\n---\n\nx\n"),
        "notes/note-f00002.md": (
            "---\nid: note-f00002\nkind: note\ntitle: Dropped thought\n"
            "status: dropped\n---\n\nx\n"),
        "notes/note-f00003.md": (
            "---\nid: note-f00003\nkind: note\ntitle: Grown thought\n"
            "status: thinking\nbecame: [pitch-f00001]\n---\n\nx\n"),
        "issues/issue-f00001.md": (
            "---\nid: issue-f00001\nkind: issue\ntitle: Picked-up breakage\n"
            "status: ready\npitched_into: [pitch-f00001]\n---\n\nx\n"),
    }
    records = [parse_text(text, path) for path, text in files.items()]
    index = build_index(records, Config(known_people=["ann", "bo"]), date(2026, 8, 17))
    render_static(index, tmp_path)

    body = read(tmp_path, "detail.html")
    headings = re.findall(r'<h2 class="tocgroup">\s*([^<]+?)\s*<span', body)
    states = {r.state(index.records) for r in index.records.values()}
    stored = {r.status for r in index.records.values()}
    present = [s for s in _TOC_LADDER if s in states]

    assert headings == [_human(s) for s in present]
    assert set(headings) == {_human(s) for s in states}
    # The whole ladder, derived from the ladder: a rung added later fails here
    # asking for a record that stands on it, instead of silently never being
    # asked about — how the promoted gap survived the first time.
    assert set(states) == set(_TOC_LADDER), (
        "this corpus no longer covers every rung of _TOC_LADDER"
    )
    assert {"promoted", "in_progress"} & stored == set(), (
        "a stored word reached a derived-only rung, so the two guards below "
        "would pass without state() being asked"
    )
    assert _human("promoted") in headings, (
        "no promoted note in this corpus, so the derived-state rung is untested"
    )
    assert _human("in_progress") in headings, (
        "no pitched issue in this corpus, so the issue derivation is untested"
    )
    # The heading was the last place a status was still spelled the way the file
    # spells it, two lines above a kind that already read as a word.
    assert not [h for h in headings if "_" in h]


def test_a_status_nobody_uses_gets_no_heading(seed_index: Index):
    from openproj.render import _by_status

    rows = [{"status": "ready"}, {"status": "done"}, {"status": "ready"}]

    assert [g["status"] for g in _by_status(rows)] == ["ready", "done"]


def test_an_unknown_status_still_reaches_the_index(seed_index: Index):
    """A record missing from the index because its status is misspelt is
    invisible — and the index is how you find the thing to fix."""
    from openproj.render import _by_status

    groups = _by_status([{"status": "done"}, {"status": "wip"}])

    assert [g["status"] for g in groups] == ["done", "wip"]


def test_a_pr_reference_completes_in_two_halves(demo_rendered: tuple[Path, Index]):
    """`kilnlab/kiln4py#` and whole references, from what the plan already cites.

    Nobody remembers whether it is kiln4py or kiln4pygen, or which org owns it,
    and that half of the reference is the same on almost every row — so it is
    offered on its own, with the number left to type.
    """
    from openproj.render import _suggestions

    _, index = demo_rendered
    offered = _suggestions(index)["prs"]
    values = [item["value"] for item in offered]
    cited = {ref for e in index.plan.values() for ref in e.prs}

    assert "kilnlab/kiln4py#" in values
    assert cited <= set(values)
    assert values.index("kilnlab/kiln4py#") < min(values.index(c) for c in cited)


def test_pull_requests_are_offered_newest_first(demo_rendered: tuple[Path, Index]):
    """Sorted as text, #999 sits above #1400 — so the oldest work is what the
    list shows first and the newest is what falls off the end of it."""
    from openproj.render import _suggestions

    _, index = demo_rendered
    numbers = [
        int(item["value"].split("#")[1])
        for item in _suggestions(index)["prs"]
        if item["value"].split("#")[1]
    ]

    assert numbers == sorted(numbers, reverse=True)


def test_choosing_a_repository_does_not_end_the_entry(seed_index: Index):
    """Half a reference is not a reference. Appending the separator after one
    would close the entry at exactly the point the number has to be typed."""
    from openproj.render import _combobox_html

    html = _combobox_html(seed_index)

    assert "const partial = value.endsWith('#');" in html
    assert "(partial ? '' : ', ')" in html


# --- theme ------------------------------------------------------------------


def test_the_theme_is_chosen_before_the_first_paint(rendered: Path):
    """A stored choice applied from the bottom of the page renders light first and
    then turns dark in front of whoever chose dark, which is worse than not
    offering the choice."""
    body = read(rendered, "table.html")
    head = body[: body.index("</head>")]

    assert "remembered.get('openproj:theme')" in head
    assert "documentElement.dataset.theme" in head
    # And the helper it reads through is declared above it, in the same block:
    # a page whose theme is chosen by a function defined further down the
    # document is a page that throws before it has a theme at all.
    assert head.index("const door = ") < head.index("remembered.get('openproj:theme')")


def test_every_page_carries_the_toggle(rendered: Path):
    for page in PAGES:
        assert '<button type="button" id="theme">' in read(rendered, page), page


# --- storage ----------------------------------------------------------------


def test_nothing_touches_a_browser_store_except_the_helper_that_survives_a_refusal():
    """One door, because the browsers that slam it slam it on the property.

    Three of the twelve reads and writes were wrapped in a try and carried a
    comment saying why; the other nine were bare, and one of those was at the
    top of the script that draws the table's rows — so on a browser with storage
    denied the whole plan rendered as an empty body. A guard remembered nine
    times out of twelve is a guard that will be forgotten the tenth time, which
    is exactly how that line got written.

    Both stores, because one policy denies both and the second one was reached
    outside the door for as long as it existed: the cycle page's receipt carried
    a `try` of its own, which is this same rule written a second time and the
    copy that would have gone missing next.

    Which makes this a grep on purpose: what a page *does* with denied storage
    is proved by running it (`test_table`, `test_editor`, and the back link in
    `test_a_browser_that_refuses_its_stores_still_draws_the_page`), and what this
    pins is that the next call site cannot be written bare.
    """
    source = render_source()
    helper = re.search(r"const door = reach => \(\{.*?\n\}\);", source, re.S)
    assert helper, "the storage helper is gone or has been renamed"

    outside = source.replace(helper.group(0), "")
    bare = [
        line
        for line in outside.splitlines()
        # The prose above and below the helper has to be able to name the two
        # things it wraps, and the two lines that open it are the whole point.
        if ("localStorage" in line or "sessionStorage" in line)
        and not line.lstrip().startswith("//")
        and not line.startswith(("const remembered = door(", "const forThisTab = door("))
    ]
    assert not bare, f"a bare browser store is back: {bare}"
    # Once each, like `esc`: two classic scripts on one page share one lexical
    # scope, so a second `const remembered` would be a SyntaxError that takes the
    # page down rather than a duplicate that drifts quietly.
    for once in ("const door = ", "const remembered = ", "const forThisTab = "):
        assert source.count(once) == 1, once
    # And the helper answers every question a caller could otherwise ask the
    # property directly — a missing verb is how the next bare call gets written.
    for verb in ("get(key, fallback = null)", "map(key)", "set(key, value)", "forget(key)"):
        assert verb in helper.group(0), verb


def test_no_colour_is_defined_only_in_the_dark_block(rendered: Path):
    """The default is no stamp at all, where only the media query separates one
    theme from the other. A token whose only definition sits behind
    `[data-theme]` never applies in that state, and the page renders one theme's
    text on the other theme's ground."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "table.html"), re.S).group(1)
    light = re.search(r":root \{(.*?)\}", style, re.S).group(1)
    dark = re.search(r':root\[data-theme="dark"\] \{(.*?)\}', style, re.S).group(1)

    defined = set(re.findall(r"(--[\w-]+):", light))
    assert set(re.findall(r"(--[\w-]+):", dark)) <= defined
    assert {"--bg", "--fg", "--surface", "--accent", "--danger"} <= defined
    assert "background: var(--bg)" in style, "a transparent body borrows the host's ground"


def test_a_status_colour_is_a_token_and_not_baked_into_a_bar(rendered: Path):
    """A `fill` written at render time cannot change when the toggle is flipped."""
    timeline = read(rendered, "timeline.html")

    assert not re.search(r'<rect data-id="[^"]*"[^>]*fill="#', timeline)
    assert re.search(r'<rect data-id="[^"]*" class="[^"]*st-\w+', timeline)
    assert "rect.st-done { fill: var(--st-done); }" in timeline


# --- the corner of the nav --------------------------------------------------


def test_the_export_draws_no_sign_in(rendered: Path):
    """The corner is filled from `/api/me`, which over file:// is a fetch that
    fails — so a static page shows nothing there, which is the truth about a file
    with no server and no session. It must not draw a signed-out state either:
    "Sign in" on a page that cannot is the dead control this suite exists over."""
    for page in PAGES:
        body = read(rendered, page)
        assert '<span id="who" hidden></span>' in body, page
        assert ">Sign in<" not in body, page
        assert 'action="/logout"' not in body, page


# --- the tab icon -----------------------------------------------------------


def test_every_page_carries_its_own_icon(rendered: Path):
    """Without a link element the browser goes and asks for `/favicon.ico` by
    itself: a 404 in the log of every served page load, and over file:// — where
    this export lives — a console error against a path that cannot exist."""
    for page in PAGES:
        body = read(rendered, page)
        assert re.search(r'<link rel="icon" href="data:image/svg\+xml,%3Csvg', body), page


def test_the_icon_needs_no_escaping_to_sit_in_an_attribute(rendered: Path):
    """Percent-encoded with nothing safe, so the URI cannot contain a quote, an
    angle bracket or an ampersand — the four ways a data: URI ends an attribute
    early and turns a picture into markup."""
    for page in PAGES:
        href = re.search(r'<link rel="icon" href="([^"]*)"', read(rendered, page))
        assert href, page
        assert not set(href.group(1)) & set("<>&\"'"), page


# --- typeface ---------------------------------------------------------------


def test_the_typeface_travels_with_the_page(rendered: Path):
    """Linked, the face is one more thing a CDN or a proxy can take away, and the
    static export has to work from file:// where a relative font URL resolves
    against whatever directory somebody dropped the page in."""
    for page in PAGES:
        body = read(rendered, page)
        assert "@font-face" in body, page
        assert re.search(r'src: url\("data:font/woff2;base64,[A-Za-z0-9+/=]{100,}"\)', body), page


def test_no_page_asks_the_network_for_a_font(rendered: Path):
    """The network assertion covers scripts, stylesheets and images. A font is the
    fourth way out, and the one a stylesheet can open without a tag."""
    for page in PAGES:
        asks_for_no_font(read(rendered, page), page)


def test_every_vendored_file_is_the_one_that_was_checksummed():
    """A vendored binary nobody verifies is a vendored binary nobody can audit.

    The list comes off the directory rather than out of this test. Naming the
    font here — which is what this did — is a list written down by hand, and a
    list written by hand is a list that goes stale: `yjs.bundle.mjs` arrived
    beside it and would have been covered by nothing at all. Everything shipped
    in `static/` is either code, a typeface, or the two files that describe them.
    """
    import hashlib

    from openproj.render import _static_dir

    static = _static_dir()
    sums = dict(
        reversed(line.split(maxsplit=1))
        for line in (static / "SHA256SUMS").read_text().splitlines()
        if line.strip()
    )
    # The list itself, and the licence texts that are notices rather than assets:
    # a licence is read, not executed, and a changed word in one is a change
    # somebody meant to make.
    described = {"SHA256SUMS", "VENDOR.md"}
    vendored = sorted(
        path.name
        for path in static.iterdir()
        if path.is_file() and path.name not in described and not path.name.endswith("LICENSE.txt")
    )
    assert "inter-latin-wght-normal.woff2" in vendored and "yjs.bundle.mjs" in vendored
    for name in vendored:
        assert name in sums, f"{name} ships in every page and is checksummed nowhere"
        digest = hashlib.sha256((static / name).read_bytes()).hexdigest()
        assert digest == sums[name].strip(), name


def test_the_vendoring_note_covers_every_file_it_is_about():
    """VENDOR.md was titled "Vendored JavaScript" and never mentioned the font that
    had been sitting beside the scripts, so the one binary in the repository was
    the one with no provenance written down.

    Its update procedure was worse than incomplete: `shasum -a 256 *.js >
    SHA256SUMS` truncates, so following it wrote three lines over four and deleted
    the woff2's checksum — the instruction for keeping the files auditable was the
    instruction that stopped them being auditable.
    """
    from openproj.render import _static_dir

    static = _static_dir()
    doc = (static / "VENDOR.md").read_text(encoding="utf-8")
    listed = [
        line.split(maxsplit=1)[1].strip()
        for line in (static / "SHA256SUMS").read_text().splitlines()
        if line.strip()
    ]

    for name in listed:
        assert name in doc, f"{name} is checksummed and undocumented"
    assert "*.js > SHA256SUMS" not in doc, "that command deletes the woff2's checksum"
    assert "*.js *.woff2 > SHA256SUMS" not in doc, "that command deletes the mjs's checksum"
    assert "*.js *.mjs *.woff2 > SHA256SUMS" in doc
    assert "SIL Open Font License" in doc and "inter-LICENSE.txt" in doc
    assert "MIT" in doc and "yjs-LICENSE.txt" in doc


def test_the_editor_licence_travels_with_the_editor(seed_index: Index):
    """The same rule the font is held to, for the same reason.

    All three of Ace's minified files contain zero occurrences of `Copyright`,
    `BSD` and `Ajax.org` — upstream strips the notice when it minifies, and
    `src-noconflict/ace.js` opens with the whole block. BSD-3 clause 2 asks for
    the notice in a binary redistribution, and this repository already reads
    "every rendered page is a copy" that way for Inter: a static export mailed to
    somebody, or one HTML file on a memory stick, has redistributed the software.

    So the notice is written into the page ahead of the bytes, where it travels
    with them, and `static/ace-LICENSE.txt` is where it is read from — not typed
    into `render.py`, so a re-vendoring that changed the licence would change
    this too.
    """
    from openproj.render import _static_dir

    _, page = editable_page(seed_index, editor="ace")
    licence = (_static_dir() / "ace-LICENSE.txt").read_text(encoding="utf-8")
    assert licence in page, "the editor ships in the page and its licence does not"
    assert "Copyright (c) 2010, Ajax.org B.V." in page
    # Ahead of the bytes rather than anywhere on the page: a notice after 475 KB
    # of minified script is a notice nobody finds.
    assert page.index("Ajax.org B.V.") < page.index("ace.define")


def test_the_font_licence_travels_with_the_font(rendered: Path):
    """Every page carries the whole face as a base64 `data:` URI, so every page IS
    a copy of the font — a single exported HTML file handed to somebody has
    redistributed it. The OFL asks the notice to travel with a copy, and a notice
    that lives only in the repository does not travel with a page."""
    for name in PAGES:
        body = read(rendered, name)
        assert "SIL Open Font License" in body, name
        assert "The Inter Project Authors" in body, name
        assert "inter-LICENSE.txt" in body, name


def test_the_page_names_its_fonts_once(rendered: Path):
    """Two font stacks written out by hand drift the first time one is changed."""
    body = read(rendered, "table.html")
    style = re.search(r"<style>(.*?)</style>", body, re.S).group(1)

    assert "font-family: var(--font-sans)" in style
    declarations = re.findall(r"font-family:\s*([^;]+);", style)
    for value in declarations:
        assert "var(--font-" in value or "Inter var" in value, value


def test_the_furniture_every_page_shares_is_written_once(rendered: Path):
    """`#summary` was defined on four pages and `#state` on three, and they had
    already come apart: the table's summary alone was the page's own font size
    with no margin under it, so the one line every view uses to say how much of
    itself is on screen looked different on the view people use most.

    `#shown` was three copies of `.num` under another name. It wears `.num`.
    """
    for name in PAGES:
        style = re.search(r"<style>(.*?)</style>", read(rendered, name), re.S).group(1)
        # The selector on its own, anchored: `.keyrow > #summary` and
        # `.editbar #summary` place the line on a row it shares, which is a
        # modifier and not a second answer to what the line looks like.
        assert len(re.findall(r"(?m)^#summary \{", style)) == 1, name
        assert len(re.findall(r"(?m)^#state \{", style)) == 1, name
        assert "#shown {" not in style, name

    for name in ("table.html", "graph.html", "timeline.html", "people.html"):
        assert '<span id="shown" class="num">' in read(rendered, name), name


def test_the_people_page_draws_the_control_bar_the_plan_draws(rendered: Path):
    """Two facet bars, the same markup, one of them written out by hand over its
    own three fields — and already drifted, because only one of the two search
    boxes had been given a name when the other was. `_FACETS` takes the field list
    as a parameter now, so there is one bar and the people page passes its own
    fields through it.

    `role` is only ever offered here: which hat somebody is wearing is not a field
    of a record, it is which field their name is in.
    """
    people, index = read(rendered, "people.html"), read(rendered, "table.html")
    shape = (r'<div id="controls">\s*<div class="searching">\s*'
             r'<input id="q" type="search" aria-label="([^"]+)" placeholder="\1">')

    for name, page in (("people", people), ("index", index)):
        assert re.search(shape, page), name

    assert re.findall(r'<div class="facet" data-field="([^"]+)"', people) == [
        "role", "kind", "status"
    ]
    assert 'aria-label="Search person, record, id"' in people
    assert 'aria-label="Search titles, tags, PRs, people"' in index


def test_no_fact_is_formatted_for_the_detail_page_twice(seed_index: Index):
    """`_fact_rows` builds each line of the facts list with its value AND its
    control, so the read view and the edit view cannot show different things.
    `_detail_rows` carried a second, read-only copy of thirteen of those facts — a
    size, a span, an overrun, an explanation, blockers, blocks, PRs, tags — and
    not one of them reached a template or a test after `_fact_rows` superseded
    them. A field formatted in two places is a field formatted two ways, and the
    dead copy is the one that goes on being maintained by accident.
    """
    from openproj.render import _DETAIL, _detail_rows

    # `e.` is one record's own line; `group.` is the index, which reads `status`
    # to group by it and prints it as the heading over each group. The status
    # left the meta line under the title — it was the same chip the facts column
    # shows forty pixels below, said twice — and the grouping is the reader that
    # is left. Either counts; neither being present is a fact built for nobody.
    for key in _detail_rows(seed_index)[0]:
        assert re.search(rf"\b(e|group)\.{key}\b", _DETAIL), f"{key} is built and read by nobody"


def test_the_labels_and_the_bars_are_laid_out_on_one_row_height(
    seed_index: Index, monkeypatch: pytest.MonkeyPatch
):
    """The label column's rows have to be exactly as tall as the rows the plot is
    drawn with, or the names walk out of step with the bars they name, one pixel
    per row — a drift nothing catches until somebody reads a long plan and finds a
    title against the wrong bar. It was `height: 22px` written into the stylesheet,
    a third copy of `_ROW_PX`, so this moves the constant and asks both."""
    from openproj import render

    monkeypatch.setattr(render.timeline, "_ROW_PX", 30)
    page = render.render_timeline(seed_index)

    assert "height: 30px; line-height: 30px;" in page
    ys = [int(y) for y in re.findall(r'<rect data-id="[^"]+"[^>]*\sy="(\d+)"', page, re.S)]
    assert len(ys) > 2
    assert sorted(ys)[1] - sorted(ys)[0] == 30, "the bars step by what the labels are tall"


def test_the_renderer_asks_the_model_rather_than_reaching_into_it():
    """`render` imported `model._status_problems` at import time to derive the
    create form's required-field gates. A private name crossing a module boundary
    is an interface nobody agreed to: the renderer had to know the shape of a
    problem tuple to unpack it, so a change to the validator's own bookkeeping
    would have broken a page. `model.required_at()` is the front door."""

    source = render_source()
    # Comments dropped: this file explains what it stopped doing, and the point is
    # that nothing executable reaches for the name any more.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    assert "_status_problems" not in code
    for imported in re.findall(r"^from \.model import (.+)$", code, re.M):
        assert not re.search(r"\b_", imported), imported


# --- tokens shared by every page --------------------------------------------


def test_a_status_carries_a_chip_palette_as_well_as_a_fill(rendered: Path):
    """Fill and ink draw shapes — a graph node, a timeline bar. Soft and text draw
    a chip, which has to sit inside a row of running text without shouting."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "table.html"), re.S).group(1)
    light = re.search(r":root \{(.*?)\}", style, re.S).group(1)

    # Derived, and that is the whole point of this one: it is the test whose job is
    # to catch a status with no tokens, and written as five literal words it could
    # not see the status that had none. Every `{% for s in statuses %}` loop in the
    # shell emits `.chip.st-<word>` the instant a word joins the ladder, so the
    # rule always appears — what goes missing is the values it names, and a
    # dangling var() does not throw. It paints: a chip with no ground and no
    # border, and, because `fill` is inherited, a solid black timeline bar.
    for status in STATUSES:
        for suffix in ("", "-ink", "-line", "-soft", "-text"):
            assert f"--st-{status}{suffix}:" in light, f"--st-{status}{suffix}"
        assert f".chip.st-{status} {{" in style


def test_the_ink_on_a_shape_stays_a_per_status_token(rendered: Path):
    """--on-status and --hatch assumed one label colour read on all five fills,
    and the ladder is what broke that assumption; both tokens are gone.

    The light theme happens to carry one ink on all five today — a ladder of
    tints has one — but the tokens stay per status, because the dark theme still
    needs an exception and a collapsed token has nowhere to put it. The exception
    is measured here rather than asserted: `shelved` keeps white ink for exactly
    as long as #101416 fails 4.5:1 on the fill under it."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "table.html"), re.S).group(1)
    themes = tokens(read(rendered, "table.html"))

    assert "--on-status" not in style, "one ink for five fills is the assumption that broke"
    assert "--hatch:" not in style
    assert {themes["light"][f"--st-{s}-ink"] for s in STATUSES} == {"#101416"}
    assert themes["dark"]["--st-shelved-ink"] == "#ffffff"
    assert contrast(themes["dark"]["--st-shelved"], "#101416") < 4.5, (
        "the dark exception has stopped being necessary — unify the ink"
    )


# --- the palette is a contract ----------------------------------------------

# The ten fills and the ten borders, written out rather than read from the file
# they are being checked against. Every other assertion in this block is a
# computed property, and a computed property tells you a value is
# *self-consistent*, not that it is the value that was agreed: a palette drifting
# one hex at a time passes every ratio test on the way down. This is the list
# somebody has to change on purpose.
PALETTE = {
    "light": {
        "thinking": ("#a1d6e3", "#101416", "#1c8da3"),
        "shaping": ("#bfb2d8", "#101416", "#7e61c2"),
        "ready": ("#7ba8d9", "#101416", "#275e92"),
        "in_progress": ("#d67c07", "#101416", "#603a04"),
        "done": ("#2b925e", "#101416", "#0d311f"),
        "shelved": ("#e1e5e9", "#101416", "#88959d"),
    },
    "dark": {
        "thinking": ("#448c99", "#101416", "#26555d"),
        "shaping": ("#a286e3", "#101416", "#5e4d86"),
        "ready": ("#80b4e7", "#101416", "#456381"),
        "in_progress": ("#fbc376", "#101416", "#84653b"),
        "done": ("#d7f4e6", "#101416", "#6a7972"),
        "shelved": ("#5e6a73", "#ffffff", "#3c4449"),
    },
}


def test_every_status_fill_carries_ink_that_reads_on_it(rendered: Path):
    """A bar and a node are the two places where a status is drawn as a shape, and
    which ink reads on a fill is a per-status question with a per-status answer.
    4.5:1 because the ink is text: the node's title, and the glyph at the bar's
    left edge.

    Both themes are tints under dark ink now. The light one was white ink on
    every fill, and white ink is what dragged every fill down the luminance scale
    to carry it — which is how the amber came out brown and the green nearly
    black."""
    themes = tokens(read(rendered, "table.html"))

    for name, wanted in PALETTE.items():
        for status, (fill, ink, _) in wanted.items():
            assert themes[name][f"--st-{status}"] == fill, (name, status)
            assert themes[name][f"--st-{status}-ink"] == ink, (name, status)
            assert contrast(fill, ink) >= 4.5, (name, status, contrast(fill, ink))


def test_a_status_shape_is_bounded_against_the_page_it_sits_on(rendered: Path):
    """--st-X-line is the edge of a status shape, and it is not decoration: the
    faintest light fill is 1.27:1 against a white page, so without a border a
    pale bar is not a shape at all. Which of the two carries the 3:1 a drawn
    boundary owes differs by theme, and both answers are asserted rather than one
    generalised into a number that happens to pass twice:

    * light — the border carries it. Each value is version 2's fill, already
      measured against this page; `shelved` is nudged one step off #8a979f,
      which was 2.9966 and written down as 3.00.
    * dark — the fill carries it, at 3.23:1 at worst, and the border is one step
      inside the fill rather than outside it. It still has to be *seen*, because
      the graph draws priority as border width and a border the colour of its own
      box is a width nobody can read. Each one is the contrast midpoint between
      its fill and the page: the same ratio either side.
    """
    themes = tokens(read(rendered, "table.html"))
    page = {name: themes[name]["--bg"] for name in PALETTE}

    for name, wanted in PALETTE.items():
        for status, (fill, _, line) in wanted.items():
            assert themes[name][f"--st-{status}-line"] == line, (name, status)
            if name == "light":
                assert contrast(line, page[name]) >= 3.0, (
                    name, status, contrast(line, page[name]))
            else:
                assert contrast(fill, page[name]) >= 3.0, (
                    name, status, contrast(fill, page[name]))
            # The border against the shape it borders, in both themes: an edge
            # nobody can see is an edge that is not there.
            assert contrast(line, fill) >= 1.75, (name, status, contrast(line, fill))
    # Defined in all three blocks, not two. A reader who has never touched the
    # toggle matches only the media query.
    for name in ("dark", "dark-by-system"):
        for status in STATUSES:
            assert themes[name][f"--st-{status}-line"] == PALETTE["dark"][status][2], name


def test_the_fills_are_separated_by_lightness_and_not_only_by_hue(rendered: Path):
    """Hue is the channel a dichromat loses, and on the graph and the timeline the
    fill used to be the only channel there was: five hues at one lightness
    (1.02–1.11:1 between any two) collapsed into one colour. Lightness is what
    every kind of colour vision keeps, so consecutive rungs are held apart by it.

    **1.25, and it moved from 1.27 to let `thinking` on.** The floor is not a
    perceptual threshold and never was — it is a drift tripwire set just under the
    worst gap that ships, so that no two rungs can quietly slide together. Adding
    a rung re-cuts the ladder, so it re-sets the floor, and the number is worth
    the arithmetic that produced it:

    * The light band spans 3.085:1, top to bottom, and it is pinned at BOTH ends —
      `shelved`'s fill is only 1.27 from the page above it, and `done` owes its own
      ink 4.5:1 below it, which stops at L=0.205. Six rungs at the old 1.27 need
      3.304 of band. They do not fit, and no gap could take one either: the widest
      that shipped was 1.416, which splits into two of 1.190 — under the 1.11 at
      which the flat palette this test was written against "collapsed into one
      colour".
    * So the three rungs BETWEEN the two ends were re-spaced — hue and chroma
      untouched, scaled in linear light so the hue is arithmetically identical —
      and six even gaps of 3.085^(1/5) = 1.2527 is the most that band holds.
      Rounding to eight bits per channel costs the rest: 1.2520 is what the hexes
      in `PALETTE` actually measure, and 1.25 is the floor just under it.
    * The dark band spans 4.748 and had room to spare — its gaps are 1.365, 1.372,
      1.361, 1.293 and 1.442 — but it could not take a rung by insertion either
      (widest gap 1.541, which splits into two of 1.241), so it was re-cut the
      same way.

    Lowering this floor is a thing to do on purpose and to say out loud, which is
    why the numbers are here rather than in a commit message. Raising it again
    means either repainting `done` or accepting five rungs."""
    themes = tokens(read(rendered, "table.html"))

    for name in ("light", "dark"):
        rungs = sorted(_luminance(themes[name][f"--st-{s}"]) for s in STATUSES)
        for lower, upper in zip(rungs, rungs[1:], strict=False):
            gap = (upper + 0.05) / (lower + 0.05)
            assert gap >= 1.25, (name, gap)


def test_a_chip_pair_is_readable_in_both_themes(rendered: Path):
    """A chip carries its word, so it does not need the ladder — but the word is
    text on a tinted ground, and text owes 4.5:1 wherever it is."""
    themes = tokens(read(rendered, "table.html"))

    for name in ("light", "dark"):
        for status in STATUSES:
            soft = themes[name][f"--st-{status}-soft"]
            text = themes[name][f"--st-{status}-text"]
            assert contrast(soft, text) >= 4.5, (name, status, contrast(soft, text))


def test_a_boundary_and_an_absent_value_are_both_visible(rendered: Path):
    """--line-strong is the sole boundary of every drawn input, button and popup,
    which makes it a UI component boundary at 3:1; it was 1.81. --empty is the em
    dash that means "no value", which makes it text at 4.5:1, not the 3.45 it was
    first given — whether a field is empty is a fact, not a hint.

    Measured against --surface-2 as well as the page, and that is the assertion
    that was missing: a bordered control sits on the panel tint as often as on
    the page — a hovered table cell, a popup, the commit bar — and both themes
    passed 3:1 on the page while landing at 2.95 and 2.97 on the tint. A ratio
    against the wrong ground is a measurement of something nobody is looking at.
    """
    themes = tokens(read(rendered, "table.html"))

    for name in ("light", "dark"):
        page = themes[name]["--bg"]
        for ground in (page, themes[name]["--surface"], themes[name]["--surface-2"]):
            assert contrast(themes[name]["--line-strong"], ground) >= 3.0, (
                name, ground, contrast(themes[name]["--line-strong"], ground))
        assert contrast(themes[name]["--empty"], page) >= 4.5, name
    # One value, referenced rather than copied: the kind chip's hairline is the
    # same boundary an input has, and a copy is how one of them gets fixed.
    assert "--kind-line: var(--line-strong)" in read(rendered, "table.html")


def test_the_three_theme_blocks_agree_about_every_colour(rendered: Path):
    """A reader who has never touched the toggle matches only the media query. A
    token that is right under [data-theme="dark"] and stale in the media block is
    stale for most of the people who will ever see the page."""
    themes = tokens(read(rendered, "table.html"))

    assert themes["dark"] == themes["dark-by-system"]
    assert set(themes["dark"]) <= set(themes["light"]), "no colour defined only in the dark"


# --- the channel that is not colour ------------------------------------------


def test_every_status_owns_a_mark_that_is_not_a_colour(rendered: Path):
    """The ladder makes five fills separable. It does not make one of them
    nameable: you can see that a bar is darker than its neighbour and still not
    know which state that is. Five different SHAPES, so no reader has to compare
    two sizes of the same one."""
    assert set(STATUS_GLYPH) == set(STATUSES)
    assert len(set(STATUS_GLYPH.values())) == len(STATUSES), "two statuses share a glyph"


def test_a_bar_says_its_status_without_using_colour(rendered: Path):
    """Fill is the only status channel on a bar — no label sits on one — so the
    glyph goes at its left edge, in the fill's own ink, and moves with the bar
    when a filter closes the rows above it."""
    body = read(rendered, "timeline.html")
    plot = body[body.index("<svg width="):]
    # One anchor per row, so a glyph is checked against the bar it is inside
    # rather than against whichever bar happens to share its x.
    rows = re.findall(
        r"<a href=\"[^\"]*\" tabindex=\"-1\" aria-label=\"[^\"]*\"\s*>(.*?)</a>", plot, re.S
    )
    assert rows, "the seed corpus draws no bars"

    marked = 0
    for row in rows:
        bar = re.search(
            r'<rect data-id="[^"]+" class="[^"]*(st-\w+)"\s+x="([\d.]+)" y="([\d.]+)"'
            r'\s+width="([\d.]+)"',
            row,
        )
        assert bar, row[:120]
        status, x, y, width = bar.group(1), *(float(bar.group(i)) for i in (2, 3, 4))
        glyph = re.search(r'<text class="bar-glyph (st-\w+)"[^>]*x="([\d.]+)" y="([\d.]+)">(.)<',
                          row)
        if width < 11:
            assert glyph is None, "a mark wider than its bar spills onto the page"
            continue
        assert glyph, (status, width)
        marked += 1
        assert glyph.group(1) == status
        assert glyph.group(4) == STATUS_GLYPH[status.removeprefix("st-")]
        # Inside the bar it names, on the baseline the filter script re-places it at.
        assert float(glyph.group(2)) == x + 3
        assert float(glyph.group(3)) == y + 10.5
    assert marked, "no bar on the seed corpus carries its status as a shape"
    for status in STATUSES:
        assert f"text.bar-glyph.st-{status} {{ fill: var(--st-{status}-ink); }}" in body
    assert "const glyph = rect.parentNode.querySelector('text.bar-glyph');" in body
    assert "glyph.setAttribute('y', y + GLYPH_DY)" in body


def test_a_node_says_its_status_without_using_colour(rendered: Path):
    """Same glyph, same meaning, on the other surface where a fill is the only
    thing telling two shapes apart. Prefixed to the node's own title, so the box
    still reads as the thing it names."""
    graph = read(rendered, "graph.html")

    assert re.search(r"const GLYPH = \{.*shelved.*\};", graph)
    for glyph in STATUS_GLYPH.values():
        assert glyph.encode("unicode_escape").decode() in graph or glyph in graph, glyph
    assert "'label': labelOf" in graph, "the mapper, not data(label)"
    # The group ruler measures what the box is actually labelled with. Measuring
    # the bare title puts every group name a glyph's width off its own box.
    assert "ruler.measureText(labelOf(node))" in graph


def test_the_cycle_band_is_one_token_and_it_can_be_seen(rendered: Path):
    """It was --surface-2 — a panel tint, 1.07:1 behind the page — keyed in the
    legend by that same token plus a border the plot does not draw. Two wrong
    answers agreeing with each other."""
    body = read(rendered, "timeline.html")
    themes = tokens(body)

    assert ".cycle-band { fill: var(--band); }" in body
    assert ".legend .swatch.band { background: var(--band); }" in body
    assert "--surface-2" not in re.search(r"\.cycle-band \{[^}]*\}", body).group(0)
    for name in ("light", "dark"):
        page, band = themes[name]["--bg"], themes[name]["--band"]
        assert contrast(band, page) >= 1.45, (name, contrast(band, page))
        # It carries the cycle number, and that number is 10px text.
        accent = themes[name]["--accent"]
        assert contrast(band, accent) >= 4.5, (name, contrast(band, accent))


def test_the_legend_draws_a_cycle_boundary_the_way_the_plot_does(rendered: Path):
    """The key drew it in --line-strong and the plot in --line, so the legend was
    describing a dashed rule that at 1.13:1 was not on the chart at all."""
    body = read(rendered, "timeline.html")
    themes = tokens(body)

    plot = re.search(r"\.cycle-rule \{([^}]*)\}", body).group(1)
    key = re.search(r"\.legend \.swatch\.boundary \{([^}]*)\}", body).group(1)
    stroke = re.search(r"var\((--[\w-]+)\)", plot).group(1)

    assert stroke == re.search(r"var\((--[\w-]+)\)", key).group(1)
    assert "dashed" in key and "dasharray" in plot
    for name in ("light", "dark"):
        assert contrast(themes[name][stroke], themes[name]["--bg"]) >= 3.0, name


def test_a_bar_that_overruns_its_cycle_is_one_of_the_bars_on_the_corpus(rendered: Path):
    """The cascade test that pins the overrun outline against the status border
    asks about `rect.bar.late`. This is what says such a rect exists at all: if
    nothing in the corpus overruns, that test is asking about a bar nobody
    draws, and it would keep passing while the outline was painted out."""
    body = read(rendered, "timeline.html")
    plot = body[body.index("<svg width="):]

    # By label, not by id: the fixture rewrites every id, and the failure message
    # is only useful if it names the bar somebody can go and look at.
    late = re.findall(
        r'aria-label="([^"]*)"\s*><rect data-id="[^"]+" class="([^"]*\blate\b[^"]*)"', plot
    )
    assert late, "no bar on the corpus overruns its cycle any more"
    for label, classes in late:
        # `bar` as well as `late`: the outline is written as `rect.bar.late`, so a
        # rect that lost the `bar` class would silently lose the outline too.
        assert "bar" in classes.split(), label
        assert any(cls.startswith("st-") for cls in classes.split()), label
    # And the row beside the plot says it in words, for a reader who has neither
    # the colour nor the width.
    assert "overruns its cycle" in body


def test_a_dependency_arrow_can_be_seen_on_the_canvas_it_is_drawn_on(rendered: Path):
    """The arrows were drawn in --st-ready, from when that fill was a dark blue.
    Inverting the light theme made it a tint — #7ba8d9 is 2.49:1 on a white page,
    and it was 2.10:1 before the ladder was re-cut for a sixth rung, so the fill
    has never been anywhere near what an edge owes — and a dependency graph whose
    dependencies you cannot see is a box of boxes. An arrow is a drawn boundary,
    not a status, so it takes the token that is held at 3:1 against the page in
    both themes."""
    graph = read(rendered, "graph.html")
    themes = tokens(graph)

    edge = re.search(r"'line-color': token\('(--[\w-]+)'\)", graph).group(1)
    assert not edge.startswith("--st-"), f"an arrow is not a status: {edge}"
    # Both the build-time style and the repaint, or the toggle undoes it.
    assert graph.count(f"'line-color': token('{edge}')") == 2, edge
    assert graph.count(f"'target-arrow-color': token('{edge}')") == 2, edge
    for name in ("light", "dark"):
        # #cy has no background of its own, so the canvas is the page.
        assert contrast(themes[name][edge], themes[name]["--bg"]) >= 3.0, (
            name, contrast(themes[name][edge], themes[name]["--bg"]))


def test_every_page_can_draw_a_problem_and_a_focus_ring(rendered: Path):
    """Severity and focus are shell rules, not table rules: a warning means the
    same thing on the cycle page, and every page has something to tab to."""
    for page in PAGES:
        body = read(rendered, page)
        assert ":focus-visible {" in body, page
        assert "outline: 2px solid var(--focus)" in body, page
        assert ".sev-row-blocker { border-left: 3px solid var(--sev-blocker); }" in body, page
    assert "outline: none" not in read(rendered, "table.html")


def test_the_dash_that_means_no_value_is_readable(rendered: Path):
    """It was --line-strong: 1.77:1 against white, which is not a colour, it is an
    absence. Whether a field is empty is a fact somebody has to be able to read."""
    detail = read(rendered, "detail.html")

    assert '<span class="empty">—</span>' in detail
    assert ".empty { color: var(--empty); }" in detail


# --- one word per identifier -------------------------------------------------


def test_every_identifier_a_reader_could_meet_has_a_word_for_it():
    """Five pages inventing their own map is how `in_progress` became "In
    progress", "in progress" and "in_progress" on the same screen."""
    from openproj.index import COMPUTED_PREDICATES
    from openproj.render import HUMAN, KINDS, PRIORITIES, STATUSES, _human

    for value in (*STATUSES, *PRIORITIES, *KINDS, *COMPUTED_PREDICATES):
        assert value in HUMAN, value
        assert _human(value) != value, f"{value} is still its own identifier"

    assert _human("in_progress") == "In progress"
    assert _human(None) == ""
    assert _human("a status nobody has added yet") == "a status nobody has added yet"


def test_one_quantity_is_called_appetite_wherever_it_is_read(rendered: Path):
    """APPETITE (WEEKS) on detail, EFFORT (WEEKS) on the create form and WEEKS in
    the table were one number under three names — over two storage fields that are
    one field now. Appetite is still the reader's word; the unit is in the field
    name because the unit is what D1 got wrong."""
    from openproj.render import LABELS

    assert LABELS["person_weeks"] == "Appetite (person-weeks)"
    assert "Effort" not in read(rendered, "detail.html")
    index = read(rendered, "table.html")
    header = re.search(r'<th data-col="size"[^>]*>(.*?)</th>', index, re.S).group(1)
    # The header is now the label map's own word rather than a literal beside it,
    # so this is the same assertion made of one source instead of two.
    assert LABELS["size"] in header and "weeks" not in header.lower()


def test_the_graph_repaints_rather_than_reloads_on_a_theme_change(rendered: Path):
    """Cytoscape resolved those colours once, when it was built: the tokens
    change, the values it already computed do not."""
    graph = read(rendered, "graph.html")

    assert "addEventListener('themechange'" in graph
    assert "getPropertyValue" in graph
    assert not re.search(r"'background-color':\s*e => \{?\s*['\"]#", graph)


def test_a_persons_rows_lead_with_what_they_own(rendered: Path):
    """Built one record at a time, a person with twenty rows had their four
    ownerships scattered through it — and ownership is what being on the page is
    for. Ordered by answerability, then by title within a role."""
    from openproj.render import _ROLE_ORDER

    body = read(rendered, "people.html")
    groups = re.findall(r'<tbody class="person".*?</tbody>', body, re.S)

    assert groups
    for group in groups:
        roles = re.findall(r'<tr data-role="(\w+)"', group)
        assert roles == sorted(roles, key=_ROLE_ORDER.index), group[:60]
    assert _ROLE_ORDER[0] == "owner"


def test_the_graph_carries_one_hint_and_no_mode_paragraph(rendered: Path):
    """The standing hint is true of the rendered build as much as of the served
    one: it pans, it zooms, and a double-click opens the record. The paragraph
    that used to swap in for edit mode is gone from both — the served page says
    what edit mode is for beside the button that turns it on, and this build has
    no such button."""
    graph = read(rendered, "graph.html")

    assert "Double-click a node to open it" in graph
    assert "howto" not in graph, "there is no second hint to hide"
    assert 'id="connect"' not in graph, "and no edit mode to explain"


def test_the_parent_reads_as_a_title_and_edits_as_an_id(demo_rendered: tuple[Path, Index]):
    """`blocked_by` already lists what it points at by title. `parent` showed a
    bare id in two places — the facts list and the line under the heading — and an
    id is what the field stores, not what somebody asking "what is this part of"
    is looking for. The control underneath still holds the id: that is what gets
    written, and the autocomplete offers ids with titles beside them."""
    out, index = demo_rendered
    body = read(out, "detail.html")
    child = next(e for e in index.plan.values() if e.parent in index.plan)
    parent = index.plan[child.parent]

    assert f">{parent.title}</a>" in body
    assert "· in <a" in body
    # The record's OWN id stays in its meta line — that one is wanted. It is the
    # parent's id that was standing in for a title.
    article = re.search(rf'<article id="{child.id}".*?</article>', body, re.S).group(0)
    parent_row = re.search(r"<dt[^>]*>Parent</dt>\s*<dd.*?</dd>", article, re.S).group(0)

    assert parent.title in parent_row
    assert f">{child.parent}<" not in parent_row


def test_an_empty_field_is_a_dash_and_not_a_word(demo_rendered: tuple[Path, Index]):
    """`nothing`, `none`, `no` and `not scheduled` sat at the same weight as a
    real value and had to be read before you knew the row was empty. One faint
    dash is empty at a glance, and it is the same mark in every row."""
    out, _ = demo_rendered
    body = read(out, "detail.html")

    assert '<span class="empty">—</span>' in body
    for word in (">nothing<", ">none<", ">not scheduled<"):
        assert word not in body, word


def test_the_shaping_doc_does_not_repeat_the_heading_it_is_under(
    rendered: Path, seed_index: Index
):
    """In git that leading `# Title` is the only thing naming the file, so nearly
    every doc in the corpus opens with it. On the page it lands directly under an
    `<h1>` of the same words at the same weight, which reads as a rendering fault
    rather than as a convention."""
    body = read(rendered, "detail.html")
    repeated = next(
        e for e in seed_index.plan.values() if e.body.lstrip().startswith(f"# {e.title}")
    )
    article = re.search(rf'<article id="{repeated.id}".*?</article>', body, re.S).group(0)
    headings = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", article, re.S)

    assert sum(repeated.title in heading for heading in headings) == 1
    # The file is untouched: the heading is what names it everywhere else.
    assert repeated.body.lstrip().startswith("# ")


def test_a_first_heading_that_is_not_the_title_is_left_alone(rendered: Path, seed_index: Index):
    """Only the repeat goes. A doc that opens on `## Problem` opens on Problem."""
    body = read(rendered, "detail.html")
    differs = next(
        e
        for e in seed_index.plan.values()
        if e.body.lstrip().startswith("# ") and not e.body.lstrip().startswith(f"# {e.title}")
    )
    article = re.search(rf'<article id="{differs.id}".*?</article>', body, re.S).group(0)
    first = differs.body.lstrip().splitlines()[0].lstrip("# ").strip()

    # Through the parser: an `<h1>` carries the source line it came from now, so
    # the tag is no longer four characters, and it was the heading and not the
    # characters that this ever meant.
    assert first in [text for _, text in headings(article)]


# The two syntaxes HackMD has that commonmark does not, and the line each block
# was written on. Kept together because they are one commit's worth of renderer
# and are checked the same way: through the parser, since the page also carries
# the raw source of the same document inside a `<textarea>` and every one of
# these claims is trivially true of a substring search over that.
_WRITTEN = """## Progress

- [ ] shape it
- [x] bet on it

~~Dropped~~ for now.
"""


def editable_page(
    index: Index, body: str | None = None, editor: str = ""
) -> tuple[str, str]:
    """One record's detail page as a writer receives it: the id, and the page.

    `base_commit` and `may_write`, which is the combination the static export
    never produces — `render_static` passes neither, so the exported file carries
    no editing surface for a test to look at.

    `editor` is the query string's `?editor=`, and it is a parameter here for the
    same reason it is one on the route: it decides whether 594 KB of second
    editor is in the page, and the rules about what a page may fetch have to be
    asked of the page that carries the newest bytes.
    """
    one = next(iter(index.plan))
    if body is not None:
        index.plan[one].body = body
    return one, render_detail(
        index, ROUTES, only=one, base_commit="deadbee", may_write=True, editor=editor
    )


def test_a_struck_out_line_and_a_task_list_render_as_what_they_are(seed_index: Index):
    """`~~x~~` rendered as four literal tildes and `- [ ] a task` as the literal
    text `[ ]`, so a dropped line read as emphasis nobody could see and a
    checklist — which is the shape a pitch's Progress section is written in —
    read as a bullet with a box drawn in ASCII."""
    _, page = editable_page(seed_index, _WRITTEN)
    drawn = elements(page)
    boxes = [
        e for e in drawn
        if e.tag == "input" and "task-list-item-checkbox" in e.attrs.get("class", "")
    ]

    assert [("checked" in e.attrs) for e in boxes] == [False, True], "two boxes, one ticked"
    assert ("s", "Dropped") in [(e.tag, e.text) for e in drawn]
    # And the source spelling is gone from the rendered half. Not from the page:
    # the box below holds the document verbatim, which is the whole reason this
    # is asked of the parsed elements and not of the served bytes.
    items = [
        e.text for e in drawn
        if e.tag == "li" and "task-list-item" in e.attrs.get("class", "")
    ]
    assert items == ["shape it", "bet on it"]
    assert "~~" not in " ".join(e.text for e in drawn if e.tag == "p")


def test_the_preview_shows_the_same_two_syntaxes_the_page_will(seed_index: Index):
    """The preview is the one place somebody checks a document before committing
    it, and it renders through `_MD` for exactly this reason: a preview that
    disagrees with the page about what a checkbox is, is worse than none."""
    drawn = elements(preview_html(_WRITTEN))

    assert [e.attrs.get("class") for e in drawn if e.tag == "ul"] == ["contains-task-list"]
    assert ("s", "Dropped") in [(e.tag, e.text) for e in drawn]


_LINKED = """A pitch worth reading: [Port the transport](pitch-000001).

And [the docs](https://example.com/a), [a sibling](./notes.md), [an anchor](#top),
[a fragment](task-abc123#progress) and `[not a link](task-abc123)` in a code span.
"""


def test_a_link_to_a_record_points_at_that_record_s_page(seed_index: Index):
    """jcanton, 2026-08-25: "I'd like to have links to other records in the body
    of a record".

    `[Title](pitch-000001)` is what a person types, and it is a relative link to
    nothing in git and on GitHub — which is the trade this takes deliberately, so
    that the plan's own files do not carry this tool's URL shape. The prefix is
    the renderer's, exactly as an asset's is: `/detail/<id>` where there is a
    server and `detail.html#<id>` in the export, one renderer drawing both.

    The four hrefs beside it are the allowlist said out loud. A record id with a
    fragment glued on is somebody meaning an anchor and not a record, and the
    code span is markdown-it's own guarantee rather than this rule's — a
    `code_inline` token is never walked at all — which is why it is here: the PR
    rule was written over finished HTML once and turned exactly this into a link.
    """
    served = {
        (e.text, e.attrs.get("href")) for e in elements(preview_html(_LINKED))
        if e.tag == "a"
    }
    assert ("Port the transport", "/detail/pitch-000001") in served, served
    # Untouched, every one of them.
    assert ("the docs", "https://example.com/a") in served
    assert ("a sibling", "./notes.md") in served
    assert ("an anchor", "#top") in served
    assert ("a fragment", "task-abc123#progress") in served
    assert not [href for _, href in served if href and href.endswith("#progress")
                and href.startswith("/detail/")], served
    # And the code span is text, not a link.
    assert "not a link" not in {text for text, _ in served}, served

    # The same document in the export, where the record page is a fragment of one
    # file. Only the prefix differs, which is the whole claim.
    exported = {
        (e.text, e.attrs.get("href"))
        for e in elements(preview_html(_LINKED, STATIC))
        if e.tag == "a"
    }
    assert ("Port the transport", "detail.html#pitch-000001") in exported, exported
    assert ("the docs", "https://example.com/a") in exported


def test_a_rendered_block_carries_the_source_line_it_came_from(seed_index: Index):
    """The box and the document are two views of one text, and nothing in the
    browser can line them up unless the rendered half says where each piece was
    written. One-based and inclusive, because that is what the editing surface
    counts in."""
    _, page = editable_page(seed_index, _WRITTEN)
    at = {
        (e.tag, e.attrs["data-startline"], e.attrs["data-endline"])
        for e in elements(page)
        if "data-startline" in e.attrs
    }

    assert ("h2", "1", "1") in at, "## Progress is on line 1"
    # 3 to 5 and not 3 to 4: markdown-it's own span for a list runs to the blank
    # line that ends it, and that is the number this passes on rather than one
    # trimmed here. A second opinion about where a block stops is a second thing
    # for the browser's half to disagree with.
    assert ("ul", "3", "5") in at, "the list runs from line 3 to the blank line that ends it"
    assert ("p", "6", "6") in at, "and the paragraph under it is line 6"
    # Only the blocks a reader scrolls past. Every paragraph inside every list
    # item stamped too would be bytes on every page for a resolution nothing
    # wants, and the one thing a scroll position interpolates between is these.
    assert not [e for e in elements(page) if e.tag == "li" and "data-startline" in e.attrs]


def test_an_editable_page_reaches_the_network_no_more_than_a_read_only_one(seed_index: Index):
    """The hole under both network assertions, and it is older than any editor.

    `PAGES` is the static-export files; `render_static` calls
    `render_detail` with no `base_commit`, so `editable` is False and the
    exported `detail.html` carries no textarea, no toolbar, no Yjs bundle and no
    room script. Neither rule had ever inspected an editing surface — the one
    part of this application that is being added to — and that is what concealed
    two `url(` tokens in a vendored editor mode from a green suite.
    """
    one, page = editable_page(seed_index)

    # The page really is the editing one, or the rest of this passes over a
    # reader's page and says nothing about the bytes it was written for.
    assert '<textarea name="body"' in page and "attachEditing(" in page
    assert "const YJS" in page and "WebSocket" in page

    fetches_nothing(page, f"the editable detail page for {one}")
    asks_for_no_font(page, f"the editable detail page for {one}")

    # And the same page with 594 KB of second editor in it, which is where the
    # newest bytes in this repository actually land. Both rules, unchanged and
    # not loosened: `ace.js` carries 24 `url(` tokens and every one of them is a
    # `data:` URI, and `keybinding-vim.js` carries none.
    #
    # The two that would have failed are in `mode-markdown.js`, at offsets 9046
    # and 47867 — a tokeniser regex and a completion template, both of which
    # fetch nothing at all — and that file is deliberately not vendored. Had it
    # been, the honest answer would have been to say so in the assertion rather
    # than to widen the pattern until a real remote URL could slip through it:
    # this scan reads `<script>` bodies on purpose, because a rule that holds
    # only over the text it is allowed to read is not a rule.
    one, with_ace = editable_page(seed_index, editor="ace")
    assert "ace.define" in with_ace, "?editor=ace did not put the editor in the page"
    fetches_nothing(with_ace, f"the second editor on the detail page for {one}")
    asks_for_no_font(with_ace, f"the second editor on the detail page for {one}")


def test_a_reader_who_may_not_write_is_sent_no_editor_library(seed_index: Index):
    """Who pays for the second editor, and it is the half of that question the
    2026-08-20 flip could most easily have destroyed.

    Ace is the DEFAULT now — jcanton, "make ace the default, I think it's worth
    it" — so the arm of `_ace_wanted` that ships 594 KB is the one an address
    reaches by saying nothing at all. `editable = base_commit is not None` and the
    served route passes a commit for everyone, so a signed-out reader already
    receives the `<textarea>`, the toolbar and two `attachEditing(` calls; if the
    inversion had been written as one flipped comparison and nothing else, every
    public reader would now carry the library unasked.

    It did not, because the gate is `may_write` and `may_write` did not move. This
    asks a reader's page all three ways round — no parameter, the opt-out, and the
    opt-in they are free to type — and every one of them has to be the same bytes.
    """
    from openproj.render import ROUTES, render_detail

    one = next(iter(seed_index.plan))
    # A signed-out reader on the SERVED route, which is the case the audit
    # measured and the one `editable` cannot see: the route passes a commit for
    # everyone, so this page already carries the box, the toolbar and two
    # `attachEditing(` calls. `may_write` is the gate, and it is a different
    # question from `editable`.
    reader = {
        how: render_detail(
            seed_index, ROUTES, only=one, base_commit="deadbee", may_write=False, **asked
        )
        for how, asked in (
            ("saying nothing", {}),
            ("asking for the plain box", {"editor": "plain"}),
            ("asking for Ace", {"editor": "ace"}),
        )
    }
    for how, page in reader.items():
        assert "ace.define" not in page, (
            f"a reader the server would refuse a write from carries 594 KB of editor, "
            f"{how} — for a keymap whose every save is a 403"
        )
    # And no switch — which is no longer a fact about READERS. There is no switch
    # on any page for anybody since 2026-08-24: the plain box is reached by
    # `?editor=plain` and by nothing else. Kept here, pointed at every page rather
    # than at a reader's, because the assertion that used to be about a control
    # that would lie is now about a control that must not come back.
    for how, page in reader.items():
        assert 'id="editorswitch"' not in page, (
            f"a switch between two editors is rendered, {how}"
        )
    # Not merely "no `ace.define`": the same bytes, all three ways. A gate that
    # dropped the library and still changed the page would mean the address was
    # being read for a reader at all, which is the thing being denied.
    assert len(set(reader.values())) == 1, (
        "the address changes a reader's page, so something on it is reading a "
        "parameter that must buy them nothing"
    )
    # And the static export, which passes neither gate.
    exported = render_detail(seed_index, ROUTES, only=one, base_commit=None, editor="ace")
    assert "ace.define" not in exported
    # The controls, both ways round, or the assertions above pass because the
    # parameter never works. A writer who says nothing gets it; a writer who opts
    # out does not.
    writing = render_detail(
        seed_index, ROUTES, only=one, base_commit="deadbee", may_write=True
    )
    assert "ace.define" in writing, (
        "Ace is the default for a writer since 2026-08-20 and this page has none of it"
    )
    plain = render_detail(
        seed_index, ROUTES, only=one, base_commit="deadbee", may_write=True, editor="plain"
    )
    assert "ace.define" not in plain, "?editor=plain is the way out and it did not work"
    assert len(writing) > len(plain) + 500_000, (
        "the second editor is not the 594 KB this gate exists for, so either the "
        "gate or the measurement has moved"
    )


def test_the_leading_heading_is_matched_on_words_and_not_on_bytes():
    """A heading wrapped across two lines, or double-spaced, or in different case
    is the same heading — and a doc whose first section merely starts with the
    same word is not."""
    from openproj.render import _drop_repeated_title

    assert _drop_repeated_title("# Port  the burner\n\nBody.\n", "Port the burner") == "Body.\n"
    assert _drop_repeated_title("## port the burner ##\n\nBody.\n", "Port the burner") == "Body.\n"
    assert _drop_repeated_title(
        "# Port the burner near-IR\n\nB.\n", "Port the burner"
    ).startswith("#")
    assert _drop_repeated_title("Plain prose.\n", "Plain prose") == "Plain prose.\n"


def test_the_detail_page_wears_the_same_chips_every_other_view_wears(rendered: Path):
    """Status had a colour on the graph, on the timeline, in the table and in the
    bet table, and was a bold word here — on the page where somebody decides what
    to do about it."""
    body = read(rendered, "detail.html")

    assert '<span class="chip st-in_progress">In progress</span>' in body
    assert '<span class="chip kind-task">Task</span>' in body
    assert "<b>in_progress</b>" not in body


def test_the_line_that_says_a_bet_does_not_fit_is_drawn_as_a_problem(
    demo_rendered: tuple[Path, Index],
):
    """It wore the same muted italic as every other derived value, so the sentence
    saying this overruns its cycle read exactly like the sentence saying when it
    starts. It stays italic — it is still computed — and gains the warning
    colour."""
    out, index = demo_rendered
    body = read(out, "detail.html")
    over = next(i for i, span in index.spans.items() if span.overruns_cycle_weeks)
    article = re.search(rf'<article id="{over}".*?</article>', body, re.S).group(0)
    row = re.search(r"<dt[^>]*>Scheduled</dt>\s*<dd([^>]*)>(.*?)</dd>", article, re.S)

    assert "derived" in row.group(1), "still marked as computed"
    assert '<span class="overrun">' in row.group(2)
    assert "dt.derived, dd.derived { font-style: italic; }" in body
    assert ".overrun { color: var(--sev-warn); font-weight: 600; }" in body


def test_the_header_spans_the_page_and_the_facts_sit_beside_the_document(rendered: Path):
    """The header — back link, switcher, commit bar, kind, title, meta — is the
    page's own width and starts where the nav starts. jcanton, 2026-08-24: "all
    above the red lines should be full width, same as in the side-by-side view,
    and only the body and fields below it keep the current horizontal sizing".

    So the measure is `.panes`'s, and the CONTAINER moved down with it. That
    pairing is the whole risk in the change: a container query and not a media
    query, because the width that decides whether the facts fit beside the prose
    is the column's and the reader sets that with the grip — and a container
    left behind on a full-width article would be answering about the WINDOW,
    which is a window breakpoint by another name and puts a sidebar on a column
    dragged to 400px.

    (It was an 832px article flush left with a full-height rule down its right
    edge, which on a wide screen is not a document but the left half of a
    two-pane layout whose right half failed to load. The rule is a short grip
    now, and the header above the column is what says the page is this wide on
    purpose.)"""
    body = read(rendered, "detail.html")

    assert re.search(r"\.panes \{[^}]*width: var\(--measure[^}]*container-type: inline-size",
                     body, re.S)
    assert not re.search(r"article\.record \{[^}]*(width|container-type):", body, re.S)
    assert re.search(r"article\.record \{[^}]*margin: 0 0 3rem", body, re.S)
    assert "@container (min-width: 56rem)" in body
    assert re.search(r"\.panes > \.facts \{[^}]*grid-column: 2", body, re.S)
    assert re.search(r"\.panes > \.main \{[^}]*grid-column: 1", body, re.S)
    # The grip is a handle now, not a border: a full-height rule in --line is
    # exactly how a page draws the edge of a pane.
    assert re.search(r"#grip::before \{[^}]*height: 48px", body, re.S)
    # And it belongs to a document. On the index every article is hidden, so it
    # measured zero and parked itself down the left edge of the list.
    assert "grip.hidden = !article" in body
    # `getClientRects()` and not `offsetParent`, which was the visibility test
    # until a `position: fixed` full-page article started answering null to it —
    # the same parked handle, reached through a second door. A box with no client
    # rects is one nothing is drawing, which is the question being asked.
    assert "candidate.getClientRects().length > 0" in body


def test_no_page_prints_a_date_twice(rendered: Path):
    """A date box is drawn in the reader's locale and nothing on the page repeats
    the value beside it.

    Every one of these pages carried an echo until 2026-08-25 — a `.iso` span
    after each `<input type=date>`, saying which day the box held in the app's
    own `dd.mm.YYYY`. It existed because the same stored 2026-09-01 reads as
    01/09/2026 at one desk and 09/01/2026 at the next. jcanton, having used it:
    "delete the echo: it's confusing to have both formats."

    So the ambiguity is back, for anybody whose browser draws a month first, and
    that was the choice rather than an oversight. Asserted across every exported
    page because the echo was inserted by the shell and would come back the same
    way — on all of them at once, silently.
    """
    for name in PAGES:
        body = read(rendered, name)
        assert "insertAdjacentElement('afterend', echo)" not in body, name
        assert ".iso { display: block;" not in body, name


# --- cycles -----------------------------------------------------------------


def test_a_new_cycle_still_has_a_roster_to_set_availability_against(
    demo_rendered: tuple[Path, Index],
):
    """Built only from who is bet or already listed, a cycle nobody has bet into
    yet shows an empty table — and setting the roster up is the first thing you
    do on it. The team list seeds it.

    Against the demo and not the corpus: the corpus has no config/people.yaml, so
    `known_people` is empty there and this passed over an empty set for as long
    as `_cycle_view` ignored the roster it names."""
    from openproj.render import _cycle_view

    _, index = demo_rendered
    view = _cycle_view(index, 99)
    logins = [row["login"] for row in view["people"]]

    assert index.known_people, "the demo names a team"
    assert set(index.known_people) <= set(logins)
    assert logins == sorted(logins, key=str.lower)
    assert all(row["held"] == 0.0 for row in view["people"])
    assert not view["recorded"], "and it says the record does not exist yet"


def test_a_recorded_cycle_is_its_roster_and_nobody_else(demo_rendered: tuple[Path, Index]):
    """The team list seeds a cycle that has no record. It must never leak into one
    that has: being on the roster is what being in the cycle means, and a name
    that appears by itself makes the roster a report instead of a decision."""
    from openproj.render import _cycle_view

    _, index = demo_rendered
    view = _cycle_view(index, 37)
    logins = [row["login"] for row in view["people"]]

    assert 37 in index.plans
    assert logins == sorted(index.plans[37].availability, key=str.lower)
    assert set(index.known_people) - set(logins), "the demo team is larger than the cycle"


def test_one_capacity_formula_answers_both_cycle_pages(demo_rendered: tuple[Path, Index]):
    """Weeks a person can hold in a cycle is `Cycle.capacity`. The cycle page was
    multiplying `rate * build_weeks` out itself while the cycles index asked the
    cycle, so one number had two implementations — and the two pages showing it
    beside each other would disagree the first time the definition acquired a
    holiday, a part week or a floor.

    Asked of every person on a real roster, at whatever rate they were recorded
    at, because a formula that is only checked at 1.0 is a formula only checked
    where every version of it agrees.
    """
    from openproj.render import _cycle_totals, _cycle_view

    out, index = demo_rendered
    plan = index.plans[37]
    view = _cycle_view(index, 37)
    page = read(out, "cycles.html")

    assert {row["rate"] for row in view["people"]} - {1.0}, "the demo records real rates"
    for row in view["people"]:
        assert row["capacity"] == plan.capacity(row["login"], index.nominal_availability)
    # And the card adds up exactly what the page's rows show, one roster, one sum.
    assert _cycle_totals(index, 37)["capacity"] == sum(r["capacity"] for r in view["people"])
    assert f'<b class="num">{_cycle_totals(index, 37)["capacity"]:.1f}</b>' in page


def test_the_cycles_index_lists_every_cycle_the_plan_names(demo_rendered: tuple[Path, Index]):
    """F25. A cycle with dates in config/cycles.yaml, or one the plan points
    at with nothing behind it, is the cycle worth finding — and it was the one
    the index left out, because it iterated the records."""
    out, index = demo_rendered
    body = read(out, "cycles.html")
    # Named, not linked: a rendered plan is a handful of files and none of them is a
    # cycle, so the card says which cycle it is and stops there. The server's
    # copy of this page does link — `test_a_rendered_plan_offers_no_dead_control`
    # is what pins the difference.
    cards = [int(n) for n in re.findall(r"<h2>Cycle (\d+)</h2>", body)]
    named = set(index.plans) | set(index.cycles) | {
        e.cycle for e in index.plan.values() if e.cycle is not None
    }

    assert set(cards) == named
    assert cards == sorted(cards, reverse=True), "newest first"
    assert len(named - set(index.plans)) >= 1, "the demo has cycles with no record"


def test_a_cycle_card_carries_the_meter_the_cycle_page_draws(
    demo_rendered: tuple[Path, Index],
):
    """F25. `9.2 of 19.8 weeks bet` is the sentence the method turns on, and it
    was a fragment at the end of a bullet list."""
    from openproj.render import _cycle_totals

    out, index = demo_rendered
    totals = _cycle_totals(index, 37)
    card = re.search(r'<li class="card[^"]*">\s*<h2>Cycle 37</h2>.*?</li>',
                     read(out, "cycles.html"), re.S).group(0)

    assert totals["capacity"] > 0 and totals["bet"] > 0
    assert f'<b class="num">{totals["bet"]:.1f}</b>' in card
    assert f'<b class="num">{totals["capacity"]:.1f}</b>' in card
    assert f'<span class="bar"><span style="width: {totals["percent"]}%">' in card
    # The bar is the one the cycle page draws, so the two pages cannot disagree
    # about what full looks like.
    assert ".bar > span { display: block; height: 100%; background: var(--accent); }" in \
        read(out, "cycles.html")


def test_a_cycle_bet_into_by_somebody_off_the_roster_is_not_counted_short(
    demo_rendered: tuple[Path, Index],
):
    """The direction this number must never be wrong in. Summed over the roster's
    rows, a cycle looked emptier the more of it was bet by people nobody had
    added to it."""
    from openproj.render import _cycle_totals, _cycle_view

    _, index = demo_rendered
    view = _cycle_view(index, 37)
    totals = _cycle_totals(index, 37)

    assert view["strangers"], "the demo bets work by somebody the cycle does not name"
    assert totals["bet"] > sum(person["held"] for person in view["people"])
    assert totals["bet"] == pytest.approx(sum(index.load(37).values()))


def test_load_is_charged_where_the_assignees_are(demo_rendered: tuple[Path, Index]):
    """D-C2: a pitch whose children carry the names charges nothing itself. Its
    appetite is a rollup, and charging both counts the same work twice."""
    _, index = demo_rendered
    held = index.load(37)
    rolled_up = [
        e for e in index.plan.values() if e.cycle == 37 and index.children.get(e.id)
    ]

    assert rolled_up, "the corpus has a parent bet into cycle 37"
    for parent in rolled_up:
        only_parent = index.model_copy(
            update={"plan": {parent.id: parent}, "children": {}}
        )
        assert only_parent.load(37), "the same parent IS charged when it has no children"
    assert held, "and the leaves are charged in the real index"


def test_a_size_is_split_evenly_between_the_people_on_it(demo_rendered: tuple[Path, Index]):
    """Even split, decided 2026-08-16: one number to maintain instead of one per
    person per task."""
    from openproj.model import Config, size_weeks

    _, index = demo_rendered
    # `counts_in` and not `e.cycle == 37`: a task takes its cycle from the pitch
    # it is part of, so the demo's tasks no longer carry one of their own.
    shared = next(
        e for e in index.plan.values()
        if index.counts_in(e, 37) and len(e.assignees) > 1 and not index.children.get(e.id)
    )
    size, _ = size_weeks(shared, Config(default_task_effort=index.default_task_effort))
    held = index.load(37)
    people = list(dict.fromkeys(([shared.owner] if shared.owner else []) + shared.assignees))

    assert len(people) > 1
    for who in people:
        assert held[who] >= size / len(people) - 1e-9


# --------------------------------------------------------------------------- #
# The page as a document: a name, a landmark, and a way past the furniture
# --------------------------------------------------------------------------- #

# What each page calls itself, in the words the nav uses for it — a heading that
# disagrees with the link that got you there is a heading that has to be read
# twice. The detail page is not here: it is a bundle of documents rather than one
# page, and `test_the_detail_page_names_each_document_it_holds` covers it.
PAGE_NAMES = {
    "index.html": "Records",
    "table.html": "Table",
    "graph.html": "Graph",
    "timeline.html": "Timeline",
    "cycles.html": "Cycles",
    "people.html": "People",
}


def test_every_page_names_itself_and_holds_exactly_one_main(rendered: Path):
    """Four of the six pages had no heading and none of them had a `<main>`.

    A page with no `<h1>` cannot be announced by name, cannot be found by a
    heading list, and gives a skip link nowhere to land — which is why the skip
    link came second. One `<main>` and one only, or "the content" is ambiguous.

    Still true with five of those headings clipped to `.sr-only`. That is the
    whole reason they were clipped rather than deleted, so this test is the one
    that has to keep passing across the change — see
    `test_a_heading_that_repeats_the_nav_is_announced_and_not_drawn` for which of
    them a reader can see.
    """
    for page in PAGES:
        body = read(rendered, page)
        assert body.count('<main id="main">') == 1, page
        assert body.count("</main>") == 1, page

    for page, name in PAGE_NAMES.items():
        # These five draw no stored markdown, so every heading on them is the
        # page's own. The detail and cycle pages render shaping documents, and a
        # `# Heading` somebody wrote is not the page failing to have one.
        assert [text for _, text in headings(read(rendered, page))] == [name], page


def test_the_detail_page_names_each_document_it_holds(rendered: Path, seed_index: Index):
    """It is a hash router over every record: with no hash it is an index, with
    one it is exactly that document. Each of those views needs a name of its own,
    and only ever one of them is displayed."""
    body = read(rendered, "detail.html")

    assert "<h1>Every record in this plan</h1>" in body
    for record in seed_index.records.values():
        article = re.search(rf'<article id="{record.id}".*?</article>', body, re.S).group(0)
        named = escape(record.title)
        assert f'<h1><span class="read">{named}</span></h1>' in article, record.id
    # And the router shows one or the other, never both.
    assert "article.style.display = match ? '' : 'none';" in body
    assert "document.querySelector('.toc').style.display = found ? 'none' : '';" in body


def test_a_heading_that_repeats_the_nav_is_announced_and_not_drawn(
    rendered: Path, seed_index: Index
):
    """The sibling of `test_every_page_names_itself_and_holds_exactly_one_main`.

    That one says the heading is in the document. This one says which of them a
    reader can see, because "remove the title" and "keep exactly one `<h1>`" are
    only compatible if the answer is different for the two kinds of heading:

    * A heading that repeats the nav — one word, the same word the nav item two
      rows above it wears, and the nav now says which page you are on by lighting
      that item. On screen it was a row of space saying nothing new. Clipped.
    * A heading that names the thing you are looking at — a record's own title, a
      cycle's number, the whole plan listed. That is content, and it is the reason
      the rule is not "delete the h1". Drawn.

    Getting this backwards is silent: `.sr-only` on the record title would take
    the name of the document off its own page and every test above would still
    pass.
    """
    for page, name in PAGE_NAMES.items():
        classes, text = headings(read(rendered, page))[0]
        assert text == name, page
        assert "sr-only" in classes, f"{page}: the nav says this already, twice over"

    seen = {text: classes for classes, text in headings(read(rendered, "detail.html"))}
    listing = "Every record in this plan"
    assert "sr-only" not in seen[listing], "the listing is what is on the screen, not a route"
    for record in seed_index.records.values():
        assert record.title in seen, record.id
        assert "sr-only" not in seen[record.title], (
            f"{record.id}: a document with its own name clipped off it"
        )


@pytest.fixture
def server_pages(seed_index: Index) -> dict[str, str]:
    """Three of the four pages `render_static` never writes — the cycle page,
    the create form and the served record page — rendered at the routes. The
    fourth, the deck, has a suite of its own in `tests/test_deck.py`.

    Rendered here rather than fetched, because what is under test is the page and
    not the plumbing; `test_web.test_every_route_says_which_nav_item_it_is` asks
    the real URLs, which is the half this cannot see.
    """
    from openproj.render import ROUTES, render_cycle, render_detail

    one = next(iter(seed_index.plan))
    return {
        "cycle": render_cycle(seed_index, 37, ROUTES, base_commit="deadbee"),
        "new": render_detail(seed_index, ROUTES, base_commit="deadbee", creating="task"),
        "record": render_detail(seed_index, ROUTES, only=one, base_commit="deadbee"),
    }


def test_the_headings_a_server_draws_are_the_same_two_kinds(server_pages: dict[str, str]):
    """The same three unexported pages, decided the same way.

    A cycle page and a record page name what you are looking at and stay visible;
    the create form is the odd one, and it is visible for the opposite reason to
    the other two — its nav item does not exist (the record page's does not
    either), so with nothing lit above it the heading is all that says what the
    form will make.
    """
    for route, name in (("cycle", "Cycle 37"), ("new", "New record")):
        found = headings(server_pages[route])
        assert [text for _, text in found] == [name], route
        assert "sr-only" not in found[0][0], f"{route}: nothing else on the page says this"


def test_the_nav_says_which_page_you_are_on(rendered: Path, server_pages: dict[str, str]):
    """`aria-current="page"` on exactly one item, and it is the right one.

    The nav used to mark nothing at all: six links, six identical underlined
    words, and the page you were standing on indistinguishable from the five you
    were not. A screen reader was told nothing either — which is the half a
    stylesheet can never fix, and the reason the attribute is the thing under test
    here and the paint is measured from it in
    `test_the_current_nav_item_is_drawn_and_not_merely_resolved`.

    A rendered export is the case with no server to ask. It marks its own item out
    of what it knew when it wrote the file, which is the only source there is.
    """
    for page, name in PAGE_NAMES.items():
        assert lit(read(rendered, page)) == [name], page

    # `detail.html` is off the nav now — it was the table with none of its
    # controls — so it lights nothing, and that is a state the nav has to be able
    # to draw rather than a page that forgot to say where it is. In the export
    # this file is still the whole corpus, and every title in the table links
    # into it.
    assert lit(read(rendered, "detail.html")) == []

    # The two routes that are not the href of the link that leads to them. Nothing
    # about `/cycle/37` matches `cycles.html` or `/cycles`, so an implementation
    # that compared the current URL against the hrefs would light nothing on
    # either of these — and both are pages somebody arrives at from the nav.
    assert lit(server_pages["cycle"]) == ["Cycles"]
    # A record page lights nothing now: it is reached from the table and goes
    # back there, and the tab it used to light no longer exists.
    assert lit(server_pages["record"]) == []

    # And the one page that marks nothing, on purpose: the create form is not one
    # of them, and pressing Table from it abandons the form rather than staying
    # put. `aria-current="page"` claims a page *within* the set.
    assert lit(server_pages["new"]) == []


def test_a_nav_item_that_is_not_a_nav_item_is_refused():
    """`current` is a string, and a typo in one lights nothing — which is exactly
    the defect this round is here to fix, arriving silently instead.

    `"cycle"` and not a nonsense word: the route is `/cycle/<n>` and the nav item
    is `cycles`, so the plausible mistake is the singular, and a page that marks
    nothing looks fine until somebody opens it.
    """
    from openproj.render import _page

    with pytest.raises(ValueError, match="cycle"):
        _page("t", "", current="cycle")


# --------------------------------------------------------------------------- #
# Where "back" goes
# --------------------------------------------------------------------------- #

# The record page's back link, driven the way a reader arrives at it: a view runs
# its scripts and leaves a stamp behind, and the record page runs its own with
# that stamp already in the tab. Two runs, because that is two page loads — the
# thing under test is what one page leaves for the next one, which no single
# rendered file can show.
BACK = ("[document.querySelector('a.origin').getAttribute('href'),"
        " document.querySelector('a.origin').textContent]")
ORIGIN = "openproj:origin"


def stamp(href: str, label: str) -> dict[str, str]:
    """A tab that has already been on a view, as that view would have left it."""
    return {ORIGIN: json.dumps({"href": href, "label": label})}


def test_a_view_leaves_the_page_you_were_standing_on(views: dict[str, str]):
    """Not the view — the page. `/table?owner=ann` is a filter somebody set, a
    sort they chose and a scroll they had reached, and a link back to `/table` is
    a link that throws all three away and looks like it worked.

    So the stamp is `pathname + search` and not the nav's own href, which is the
    same string for every state a view can be in.
    """
    from test_injection import run_js

    for view, label, here in (
        ("table", "Table", "/table?owner=ann"),
        ("graph", "Graph", "/graph"),
        ("timeline", "Timeline", "/timeline"),
    ):
        left = run_js(views[view], page=True, here=here)["tabbed"]
        assert json.loads(left[ORIGIN]) == {"href": here, "label": label}, view


def test_the_records_list_keeps_the_name_the_link_already_had(seed_index: Index):
    """Every other view is stamped with the word the nav uses for it. Records is
    stamped "all records", which is what the link says when nothing is stamped at
    all — one destination wearing two names depending on how you had arrived
    would be the same link reading differently on the same page.
    """
    from test_injection import run_js

    from openproj.render import ROUTES, render_records

    left = run_js(render_records(seed_index, ROUTES), page=True, here="/?kind=issue")["tabbed"]
    assert json.loads(left[ORIGIN]) == {"href": "/?kind=issue", "label": "all records"}


def test_a_record_page_goes_back_to_the_view_it_was_opened_from(
    server_pages: dict[str, str],
):
    """The whole point. Opening a record off the table and pressing back put you
    on the records list — a third page, and not the one with the filter and the
    sort you had left behind.
    """
    from test_injection import run_js

    got = run_js(server_pages["record"], BACK, page=True,
                 session=stamp("/table?owner=ann", "Table"))
    assert got["value"] == ["/table?owner=ann", "← Table"]


def test_a_record_page_opened_cold_still_goes_to_the_records_list(
    server_pages: dict[str, str],
):
    """A bookmark, a link in a chat window, a fresh tab. There is no view behind
    this page, and the rendered markup is already the answer — which is why the
    fallback is what the server wrote rather than something the script computes.

    Per tab and not per browser for exactly this: a record opened in a new tab
    beside a table has no origin, rather than one belonging to a window whose
    Back button would not go there either.
    """
    from test_injection import run_js

    assert run_js(server_pages["record"], BACK, page=True)["value"] == ["/", "← all records"]


def test_a_page_reached_from_a_view_leaves_the_stamp_where_it_found_it(
    server_pages: dict[str, str],
):
    """The record page and the create form are not views, so neither overwrites
    the origin. A record page that stamped itself would send the NEXT record you
    opened — through a parent link, or the export's index — back to a record
    instead of back to the table, one hop further from the view each time.
    """
    from test_injection import run_js

    was = stamp("/table?owner=ann", "Table")
    for page in ("record", "new"):
        assert run_js(server_pages[page], page=True, session=was)["tabbed"] == was, page


def test_an_address_smuggled_into_the_stamp_is_not_followed(server_pages: dict[str, str]):
    r"""A store is a place somebody's devtools can write, and an `href` is the one
    field on this path a scheme fits inside. The check is an allowlist, because
    there is no list of URL spellings that is ever finished.

    `//host/x` and `/\host/x` are why it is not merely a leading slash, and they
    are here because the first draft of the check took both: one is a
    protocol-relative URL to somebody else's host — the exact spelling that got
    past this repository's image check once — and the other is what the URL
    parser folds into it. This test caught that draft.

    Refused means the link is what the server rendered, not that the page is
    broken: a stamp nobody can read is the same case as no stamp at all.
    """
    from test_injection import run_js

    for hostile in ("javascript:alert(1)", "//host/x", "/\\host/x",
                    "https://host/x", "data:text/html,x"):
        got = run_js(server_pages["record"], BACK, page=True, session=stamp(hostile, "Table"))
        assert got["value"] == ["/", "← all records"], hostile


def test_a_browser_that_refuses_its_stores_still_draws_the_page(
    views: dict[str, str], server_pages: dict[str, str],
):
    """`sessionStorage` throws on the property itself, exactly as `localStorage`
    does and for the same reasons — a private window, blocked cookies, a policy.
    Every read and write of it goes through the shell's door for that, and this
    is the case the door is for: the back link is a convenience and the record is
    the page.
    """
    from test_injection import run_js

    denied = run_js(server_pages["record"], BACK, page=True,
                    storage="denied", session=stamp("/table", "Table"))
    assert denied["value"] == ["/", "← all records"]
    assert not [e for e in denied["errors"] if "SecurityError" in e], denied["errors"]

    left = run_js(views["table"], page=True, storage="denied", here="/table")
    assert not [e for e in left["errors"] if "SecurityError" in e], left["errors"]


def test_every_record_in_the_export_carries_the_link_back(rendered: Path):
    """`detail.html` is the whole corpus in one file, so the rewrite is every
    article's link and not the first one — and the address it goes back to is the
    exported file, whose `pathname` over `file://` is an absolute path on disk
    and passes the same allowlist a route does.
    """
    from test_injection import run_js

    here = "/home/ann/plan/table.html"
    left = run_js(read(rendered, "table.html"), page=True, here=here)["tabbed"]
    assert json.loads(left[ORIGIN]) == {"href": here, "label": "Table"}

    every = ("[...document.querySelectorAll('a.origin')]"
             ".map(a => a.getAttribute('href') + ' ' + a.textContent)")
    got = run_js(read(rendered, "detail.html"), every, page=True, session=left)["value"]
    assert len(got) == read(rendered, "detail.html").count("<article")
    assert set(got) == {f"{here} ← Table"}


def test_every_page_carries_a_skip_link_and_a_live_region(rendered: Path):
    """Two shell obligations, because a page cannot opt out of either.

    Every `role="status"` on this app used to be inside `{% if editable %}`, so a
    rendered plan announced nothing at all — including the sentence a computed
    column answers a double-click with.
    """
    for page in PAGES:
        body = read(rendered, page)
        assert '<a class="skip" href="#main">' in body, page
        assert body.index('class="skip"') < body.index("<nav>"), f"{page}: first in the order"
        assert '<p id="announce" class="sr-only" role="status" aria-live="polite">' in body, page
        # Clipped, not hidden: display:none and visibility:hidden both take an
        # element out of the accessibility tree, which is the one place this
        # element exists to be in.
        assert ".sr-only { position: absolute;" in body, page
        assert "clip-path: inset(50%)" in body, page

    # And the table's own place for a message is a live region on the rendered
    # file too, where the refusal a derived column gives is the only thing that
    # ever writes to it.
    assert '<span id="state" role="status"></span>' in read(rendered, "table.html")


def test_a_rendered_plan_offers_no_dead_control(rendered: Path, seed_index: Index):
    """A read-only export must not draw a control that cannot work.

    `links.new` is the empty string on a rendered file, so "New record" was a
    button back to the page you were already on; the hint beside it promised an
    editor with no server to save to; and every cycle card linked to a per-cycle
    page that `render_static` does not write.

    The button is gone from the table altogether since 2026-08-25 — the `+` row
    at the foot creates a record in place — so the first assertion below can no
    longer fail and is kept only as the name of what must not come back. The
    second is still live and moved with the sentence it is about: the hint is in
    `#controls .aside` now, drawn only where `may_write` and a `base_commit`
    both say there is a server behind the page.
    """
    table = read(rendered, "table.html")
    cycles = read(rendered, "cycles.html")

    assert "New record" not in table
    assert "double-click a cell" not in table
    assert '<a class="button" href="">' not in table
    for number in sorted(set(seed_index.plans) | set(seed_index.cycles)):
        assert f"<h2>Cycle {number}</h2>" in cycles, number
    # No anchor anywhere in the export points at a file that was not written.
    # `data:` is the page carrying the thing rather than pointing at it — the tab
    # icon — so it is the one href that cannot be a dead file by construction.
    written = {path.name for path in rendered.iterdir()}
    for page in PAGES:
        for href in re.findall(r'href="([^"#?]+)[^"]*"', read(rendered, page)):
            if href.startswith(("http://", "https://", "assets/", "data:")):
                continue
            assert href in written, f"{page} links to {href}, which is not in the export"


def test_the_timeline_lists_beside_the_chart_what_the_chart_draws(rendered: Path):
    """`role="img"` prunes the whole SVG, seventeen bar links included — which is
    right only once what it prunes exists somewhere else.

    The column of labels beside the plot is that somewhere else: it already
    carried a link per row, and now carries the status the fill means, the dates
    the width means, the marks the hatching means and the sentence the tooltip
    holds.
    """
    body = read(rendered, "timeline.html")
    labels = re.search(r'<div class="labels" role="list".*?\n</div>', body, re.S).group(0)
    rows = re.findall(r'<div class="row" role="listitem" data-id="([^"]+)".*?</div>',
                      labels, re.S)
    bars = re.findall(r'<rect data-id="([^"]+)" class="bar', body)

    assert bars, "the corpus draws no bars"
    assert [row for row in rows] == bars, "one row beside the plot per bar on it"
    assert 'aria-label="Every bar on the chart, with its status and its dates"' in labels
    for row in re.findall(r'<div class="row" role="listitem".*?</div>', labels, re.S):
        record_id = re.search(r'data-id="([^"]+)"', row).group(1)
        says = re.search(r'<span class="sr-only">(.*?)</span>', row, re.S).group(1)
        assert record_id in says, record_id
        # A status word and a pair of dates, which the fill and the width are the
        # only channels for on the chart itself.
        assert re.search(r"\d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d\.", says), says
        assert f'<a href="detail.html#{record_id}"' in row
    # And the anchors the role prunes are out of the tab order, or Firefox stops
    # on seventeen links that announce nothing.
    assert body.count('tabindex="-1" aria-label=') == len(bars)


def test_the_hatching_says_in_words_what_it_says_in_texture(demo_rendered: tuple[Path, Index]):
    """An assumed appetite, work nobody is on and a bet that overruns its cycle
    are a texture and a stroke over a bar, and neither reaches anybody who is not
    looking at the plot."""
    from openproj.model import Config, Task
    from openproj.render import _MARK_WORDS, _timeline

    # A task with no effort and nobody on it: both marks at once, which the
    # shipped corpora do not happen to contain.
    bare = build_index(
        [Task(id="task-000009", kind="task", title="Nobody has this", status="ready")],
        Config(),
        date(2026, 8, 17),
    )
    guessed = _timeline(bare)["bars"][0]

    assert guessed["marks"] == ["estimated", "unowned"]
    for mark in guessed["marks"]:
        assert _MARK_WORDS[mark] in guessed["reads"].lower(), mark

    # And the outline that means a bet does not fit the cycle it was made in.
    _, index = demo_rendered
    late = [bar for bar in _timeline(index)["bars"] if "late" in bar["classes"]]
    assert late, "the demo corpus overruns nothing"
    for bar in late:
        assert "overruns its cycle" in bar["reads"].lower(), bar["id"]


def test_only_an_asset_this_tool_stored_is_ever_drawn_as_an_image():
    """A remote image makes the page fetch from the network, which is what inlining
    every library was for — and in a plan anybody can write to, it aims a tracking
    pixel at every colleague who opens the document.

    This asked whether the source started with `http://` or `https://`: the two
    ways somebody writes it on purpose, and none of the ways they do not. Both of
    the spellings below drew a live `<img>`, and a real browser fetched both,
    referer and all. `//host` inherits the page's scheme; `HTTP://host` is the same
    URL to a browser and a different string to `startswith`. Neither is exotic —
    the first is what a copied `<img>` tag from a CDN looks like.

    So the question is asked the other way round now, and the assertion is the
    shape of the rule rather than a list of the spellings somebody thought of: an
    image is drawn only if it is an asset this tool stored. Everything else is a
    link, which keeps the reference and drops the dependency.
    """
    from openproj.model import Task
    from openproj.render import _body_html

    def _record(body: str) -> Task:
        return Task(id="task-000001", kind="task", title="t", person_weeks=1, body=body)

    stored = "assets/0123456789abcdef.png"
    assert f'<img src="{stored}"' in _body_html(_record(f"![ok]({stored})"))

    for source in (
        "//example.com/a.png",              # scheme-relative: inherits the page's
        "HTTP://example.com/a.png",         # the same URL, a different string
        "HtTpS://example.com/a.png",
        "http://example.com/a.png",
        "\thttp://example.com/a.png",       # leading whitespace a parser forgives
        "data:image/png;base64,iVBORw0KGgo=",
        "javascript:alert(1)",
        "../../etc/passwd.png",             # same origin, still not ours
        "assets/notahash.png",              # our directory, not our naming
        "assets/0123456789abcdef.svg",      # our naming, a format we do not store
    ):
        drawn = _body_html(_record(f"![x]({source})"))
        # The invariant is that nothing fetches: no `<img>`, ever. What happens
        # instead varies in one case, and honestly — markdown-it refuses to link
        # `javascript:` at all and leaves the line as text, which is a better
        # answer than the link this would otherwise have made of it.
        assert "<img" not in drawn, source
        assert "(external image)" in drawn or source in str(drawn), source


# --------------------------------------------------------------------------- #
# The end of the calendar
# --------------------------------------------------------------------------- #


def _index_reaching_the_end_of_the_calendar(seed_root: Path) -> Index:
    """The seed corpus with one `done` task dated at the end of the calendar.

    A `done` span is whatever `assigned_on` says and no rule refuses a date, so
    this is what one keystroke too many in the detail page's date box leaves in
    the repository — permanently, on a protected branch.
    """
    records, config, _ = load_repo(seed_root)
    # Already `done`, and nothing depends on it — the narrowest possible blast
    # radius, which is what the audit hit: every other page stayed up and only
    # `/timeline` broke.
    marked = [e for e in records if e.id == "task-3e07b2"]
    assert marked, "the fixture corpus no longer holds the record this test edits"
    marked[0].assigned_on = date.max
    return build_index(records, config, date(2026, 8, 17))


def test_the_timeline_survives_a_date_at_the_end_of_the_calendar(seed_root: Path):
    """`_month_ticks` built the month after December 9999 to find out it was too
    far, and `date(10000, 1, 1)` is a ValueError — twelve lines after the `x()`
    helper that was fixed for this exact failure and carries a comment saying so.

    `/timeline` answered 500 for good, and both tools you would reach for to
    diagnose it were no use: `openproj check` reported nothing wrong and
    `openproj render` wrote no files at all, because every page is rendered
    before any is written.
    """
    from openproj.render import render_timeline

    html = render_timeline(_index_reaching_the_end_of_the_calendar(seed_root))

    assert '<svg width=' in html


def test_a_bar_at_the_end_of_time_does_not_make_a_page_nobody_can_open(seed_root: Path):
    """Not raising is half the fix. Left to its own devices the plot draws every
    day between here and the year 9999 at the 1.6px/day floor: 4.7 million pixels
    of SVG, 95,686 month ticks and fourteen megabytes of markup — which is a hung
    tab, not a page, and is the outcome the scheduler already refuses elsewhere.

    Measured off the drawing rather than off the source: a stylesheet or a
    constant can say the right number while the SVG says another one, and it is
    the SVG the browser lays out.
    """
    from openproj.render import render_timeline

    index = _index_reaching_the_end_of_the_calendar(seed_root)
    html = render_timeline(index)
    width = float(re.search(r'<svg width="([\d.]+)"', html).group(1))
    ticks = re.findall(r'<text class="month-label"', html)

    assert width < 30_000, f"{width}px of plot is not a page anybody scrolls"
    assert len(ticks) < 600, f"{len(ticks)} month labels"
    assert len(html) < 1_000_000, f"{len(html)} bytes"
    # And it is still a drawing of the plan, not an empty frame: the bars that
    # fit the window are all there, and the page says what it is not showing.
    #
    # Named rather than counted. This was `== 11`, which was the number of spans
    # the corpus happened to have when it was written, and growing the corpus
    # from 17 records to 30 made it wrong — a literal that has to be re-derived
    # every time the fixture moves is one somebody eventually re-derives by
    # pasting what the run printed. The claim is "everything except the absurd
    # one", so that is what it says, and it cannot go stale.
    drawn = set(re.findall(r'<rect data-id="([^"]+)"', html))
    assert drawn == index.spans.keys() - {"task-3e07b2"}, "every bar but the one at date.max"


def test_a_window_typed_into_the_url_cannot_run_off_the_calendar(seed_index: Index):
    """No commit needed for this one: `from` and `to` are query parameters, so
    `?from=9999-12-31` is a link anybody can send. It walked one day past
    `date.max` deciding a backwards window was backwards, and `?to=9999-12-31`
    walked the months instead — both 500 on a repository with nothing wrong in
    it at all."""
    from openproj.render import render_timeline

    for window in (
        (date.max, None),
        (None, date.max),
        (date.min, date.max),
        (date(9999, 12, 1), None),
    ):
        html = render_timeline(seed_index, window=window)
        assert '<svg width=' in html, window
        assert len(html) < 1_000_000, (window, len(html))


# --------------------------------------------------------------------------- #
# The room the window has left, measured in a browser
# --------------------------------------------------------------------------- #

# Three views, three boxes, one measurement. The graph's canvas is the only one
# with a `height` — a canvas has no size of its own, so it IS the room — while the
# table's rows and the timeline's plot are capped at it and stay as tall as their
# own contents when those are shorter.
_ROOM = """
const box = document.querySelector('[data-fills]');
const bar = document.querySelector('.commitbar');
const root = document.documentElement;
const rect = box.getBoundingClientRect();
const bars = bar && bar.getBoundingClientRect();
// Cytoscape draws into a canvas, so where a node ended up is a question only it
// can answer. Rendered coordinates are relative to the container's own origin.
const graph = (typeof cy !== 'undefined' && cy.nodes) ? cy : null;
const nodes = graph ? graph.nodes(':visible').map(node => {
  const seen = node.renderedBoundingBox();
  return {id: node.id(), top: rect.top + seen.y1, bottom: rect.top + seen.y2,
          left: rect.left + seen.x1, right: rect.left + seen.x2};
}) : [];
const span = what => nodes.length
  ? {top: Math.min(...nodes.map(n => n.top)), bottom: Math.max(...nodes.map(n => n.bottom)),
     left: Math.min(...nodes.map(n => n.left)), right: Math.max(...nodes.map(n => n.right))}
  : null;
const drawn = span();
return {
  window: innerHeight,
  scrolls: root.scrollHeight - root.clientHeight,
  boxTop: Math.round(rect.top), boxBottom: Math.round(rect.bottom),
  // Positive is clear air between the box and the bar, whichever of them is on
  // top. It used to be `bars.top - rect.bottom`, which is that gap only while the
  // bar is BELOW the box, and read as -596px the day the bar moved above it —
  // a number that says "the box is underneath the bar" about a page where the two
  // do not touch. The claim was never about which one is lower; it is that a bar
  // which is always on screen is always in front of something, and that something
  // must not be the box. So: the larger of the two gaps, which is the real one,
  // and negative only when they genuinely overlap.
  clearance: bars ? Math.round(Math.max(bars.top - rect.bottom, rect.top - bars.bottom)) : null,
  drawnCount: nodes.length,
  // Under the bar means overlapping the band it occupies, for the same reason.
  underBar: bars
    ? nodes.filter(n => n.bottom > bars.top + 0.5 && n.top < bars.bottom - 0.5).map(n => n.id)
    : [],
  offCanvas: nodes.filter(n => n.bottom > rect.bottom + 1 || n.top < rect.top - 1).map(n => n.id),
  // How far the drawing sits from each edge of the box it was fitted into. Equal
  // means centred in the room it got; unequal by hundreds means centred in the
  // room it thought it had.
  fitted: drawn ? {above: Math.round(drawn.top - rect.top),
                   below: Math.round(rect.bottom - drawn.bottom),
                   left: Math.round(drawn.left - rect.left),
                   right: Math.round(rect.right - drawn.right)} : null,
};
"""

# Six windows from a tall desktop down to the short one the notes asked for, and
# one below anything usable. The floor the shell reports engages somewhere near
# the bottom of this range, and where it does the page is supposed to scroll —
# that is the honest answer at a window with no room in it, and it is why the
# short end is a separate expectation rather than the same one again.
_WINDOWS = (1200, 900, 806, 700, 620)


@pytest.fixture
def views(seed_index: Index) -> dict[str, str]:
    """The three pages that size a box to the window, served rather than exported:
    the graph's commit bar is the thing the canvas has to clear and a static
    export has no server to commit to, so it has no bar at all."""
    from openproj.render import STATIC, render_graph, render_table, render_timeline

    return {
        "graph": render_graph(seed_index, STATIC, base_commit="deadbee"),
        "table": render_table(seed_index, STATIC, base_commit="deadbee", may_write=True),
        "timeline": render_timeline(seed_index, STATIC),
    }


@pytest.mark.parametrize("view", ("graph", "table", "timeline"))
def test_the_box_each_view_fills_stops_where_the_window_does(
    views: dict[str, str], view: str, seed_index: Index, tmp_path: Path
):
    """`#cy` was `height: 78vh` — a fraction of the window that knows nothing
    about the six rows above the canvas or the sticky commit bar beside it. At an
    806px window the canvas ran from 268 to 899 while the bar sat across 759–806,
    so 140px of it was underneath the bar, two nodes loaded hidden there, and the
    page scrolled as well.

    "Beside" and not "below" since 2026-08-20: the graph's bar moved above the
    canvas so that every page keeps the control that commits it in one place. The
    measurement did not care and the assertions did — `clearance` was written as
    the gap under the box, which is the gap only while the bar is under it. It is
    the gap between the two now, whichever way round they are.

    A fraction was always going to be wrong; only the amount was in question. So
    the number is measured, and this asks the browser what the measurement
    produced — at five windows, because one window is the one thing that cannot
    show a fraction is wrong.

    Nothing here reads the stylesheet. `height: var(--room)` resolving is not the
    claim; where the bottom of the box ends up is.
    """
    from browser import chrome, measured_in

    browser = chrome()
    for height in _WINDOWS:
        got = measured_in(
            browser, views[view], tmp_path / f"{view}-{height}.html", 1400, _ROOM, height
        )
        where = f"{view} at a {got['window']}px window"
        assert got["scrolls"] == 0, f"{where}: the page scrolls {got['scrolls']}px"
        if got["clearance"] is not None:
            assert got["clearance"] >= 0, (
                f"{where}: {-got['clearance']}px of the box and the commit bar overlap"
            )
        assert not got["underBar"], f"{where}: {got['underBar']} are drawn under the bar"

        if view != "graph":
            continue
        # The other half of the note: the fit has to centre the plan in the space
        # the canvas actually gets. Cytoscape measures its container when it is
        # built and never looks again, so a canvas that is resized afterwards and
        # not told keeps drawing at the size it was given — the plan centred for a
        # box it no longer has, with nodes off the edge of the one it does.
        # Every planned record, and no number written down here. It was `== 17`,
        # which was the size of the fixture corpus on the day it was written and
        # became a lie the morning the corpus grew to 26 — and a count that has
        # to be edited when the corpus moves is a count nobody trusts by the
        # second time. `len(index.plan)` is the claim the assertion was always
        # making: the graph draws the plan, all of it, at every window. It is
        # also what makes the two lines below mean anything, since a canvas that
        # drew nothing is centred and inside its box.
        assert got["drawnCount"] == len(seed_index.plan), (
            f"{where}: {got['drawnCount']} nodes drawn for "
            f"{len(seed_index.plan)} planned records"
        )
        assert not got["offCanvas"], f"{where}: {got['offCanvas']} are outside the canvas"
        fitted = got["fitted"]
        for axis, (near, far) in (("vertically", ("above", "below")),
                                  ("horizontally", ("left", "right"))):
            assert abs(fitted[near] - fitted[far]) <= 2, (
                f"{where}: the plan sits {fitted[near]}px from the {near} edge and "
                f"{fitted[far]}px from the {far} one, so it is not centred {axis} "
                f"in the canvas it was given"
            )


# Where the two lines that describe a view — the instruction and the count — end
# up. Both used to be rows of their own; both are now the far end of a row that
# already existed.
_ROWS = """
const line = el => el && {
  top: Math.round(el.getBoundingClientRect().top),
  bottom: Math.round(el.getBoundingClientRect().bottom),
  right: Math.round(el.getBoundingClientRect().right),
};
const controls = document.getElementById('controls');
// Every top-level block between the heading and the box the view fills. This is
// the count the notes were about: six of them left 268px of an 806px window for
// the graph.
const box = document.querySelector('[data-fills]');
const rows = [...document.querySelector('main').children]
  .filter(el => el.getClientRects().length && el.getBoundingClientRect().height > 0
                && el.getBoundingClientRect().top < box.getBoundingClientRect().top)
  .map(el => el.tagName.toLowerCase()
       + (el.id ? '#' + el.id : '')
       + (typeof el.className === 'string' && el.className.trim()
          ? '.' + el.className.trim().split(/\\s+/).join('.') : ''));
return {
  rows,
  boxTop: Math.round(box.getBoundingClientRect().top),
  search: line(document.getElementById('q')),
  aside: line(document.querySelector('#controls .aside')),
  key: line(document.querySelector('.keyrow .legend')),
  keyTwo: line(document.querySelector('.keyrow .legend + .legend')),
  keys: line(document.querySelector('.keys')),
  count: line(document.getElementById('summary')),
  blockers: line(document.getElementById('blockers')),
  controlsRight: Math.round(controls.getBoundingClientRect().right),
};
"""


def _shares_a_line(one: dict, other: dict) -> bool:
    """Two boxes are on the same row of the page when their vertical extents
    overlap. Not "same top": a 12px sentence beside a 29px input has a different
    top by design, and comparing tops would pass for a sentence sitting one line
    below as well."""
    return one["top"] < other["bottom"] and other["top"] < one["bottom"]


@pytest.mark.parametrize("view", ("graph", "table", "timeline"))
def test_a_sentence_about_the_view_never_costs_the_view_a_row(
    views: dict[str, str], view: str, tmp_path: Path
):
    """The graph stacked six rows before the canvas started: heading, pan/zoom
    hint, search box, filters, key, count. Two of the six were not controls at
    all — a sentence about how to move the drawing, and a count of what is in it —
    and each was a full row wide to hold twelve words.

    **One row on all three views, and one row is now the whole claim.** jcanton,
    2026-08-25: "these three should actually share the nav+login+theme, search
    box+description (to each its own)+problems+N/M shown, and filter rows". Until
    that day each view had answered the question its own way — the table in a
    `<p>` of its own above the controls, the graph in the corner of the canvas,
    the timeline beside its key — which is three answers, three places to look,
    and three things to keep in step. They are one fragment now
    (`_summary_html`), in one slot, so what this test says of each view it says
    in the same words.

    The heading is still first in the list and is `.sr-only` — the seventh of the
    six rows going. It is `position: absolute`, so it is out of flow and the rows
    below it start where the nav ends; the test named below is the one that
    measures that, and this one only has to know the heading did not turn back
    into something a reader can see.

    See `test_the_heading_costs_the_view_no_row`.
    """
    from browser import chrome, measured_in

    got = measured_in(chrome(), views[view], tmp_path / f"{view}-rows.html", 1400, _ROWS)

    # Nothing between the heading and the box is a bare paragraph or a lone count.
    # Named, because the next thing anybody adds here is the row this is guarding
    # against.
    assert got["rows"] == {
        # `div.commitbar` is a row of CONTROLS, which is the thing a sentence was
        # being asked to stop displacing rather than an instance of it. It moved
        # above the canvas on 2026-08-20 so that every page keeps the control that
        # commits it in one place, and it cost the drawing nothing — `--room` went
        # 595px to 607px at 1400x900, because up here its top margin collapses
        # with the filter row's and below the canvas it did not.
        "graph": ["h1.sr-only", "div#controls", "div#commitbar.commitbar"],
        # The table's `p.editbar` is gone: it held the count and the save receipt
        # for one day, which is a row of furniture with one sentence at its right
        # end and nothing at its left.
        "table": ["h1.sr-only", "div#controls"],
        # And the timeline's two keys are one row rather than two — status on the
        # left, marks on the right.
        "timeline": ["h1.sr-only", "div#controls", "form.tl-controls", "div.keyrow"],
    }[view], got["rows"]

    # The same three claims on every view, which is what "share the bar" means.
    assert got["aside"], "the view says nothing about itself"
    assert _shares_a_line(got["aside"], got["search"]), (
        f"the instruction is at {got['aside']} and the search box at {got['search']}"
    )
    assert _shares_a_line(got["count"], got["search"]), (
        f"the count is at {got['count']} and the search box at {got['search']}"
    )
    assert got["blockers"], "the view does not say what is wrong with the plan"
    assert _shares_a_line(got["blockers"], got["count"])
    # Flush with the right edge of the bar above it.
    assert got["count"]["right"] == got["controlsRight"], (
        f"the count ends at {got['count']['right']} and the bar at {got['controlsRight']}"
    )
    # The instruction keeps the search box's line — that is what stops it costing
    # a row above the drawing — but it reads left to right like the sentence on
    # every other page, rather than being pushed to the far end and set
    # right-aligned. Asked for on 2026-08-17, having been the one thing about
    # these two views that did not match the rest of the site.
    assert got["aside"]["right"] < got["controlsRight"], (
        f"the instruction ends at {got['aside']['right']} and the bar at "
        f"{got['controlsRight']}: it is still pinned to the right edge"
    )

    if view == "graph":
        # The key is still over the drawing rather than above it, which is the
        # same rule taken one step further on the view where a row is worth the
        # most. The count used to ride with it and does not any more.
        assert got["keys"], "the keys are gone from the graph"
        assert got["keys"]["top"] >= got["boxTop"], (
            f"the keys are at {got['keys']['top']} and the drawing starts at "
            f"{got['boxTop']}: they are still costing the view a row"
        )
        assert got["count"]["bottom"] <= got["boxTop"], (
            "the count is still drawn over the canvas as well as in the bar"
        )
    if view == "timeline":
        # Both keys on one line, and the second hangs off the right end —
        # jcanton, 2026-08-25: "left-aligned for status and right aligned the
        # others".
        assert got["key"], "the timeline lost its key"
        assert got["keyTwo"], "the timeline's second key is not beside the first"
        assert _shares_a_line(got["key"], got["keyTwo"]), (
            f"the two keys are on two rows: {got['key']} and {got['keyTwo']}"
        )
        assert got["keyTwo"]["right"] == got["controlsRight"], (
            f"the second key ends at {got['keyTwo']['right']} and the bar at "
            f"{got['controlsRight']}: it is not right-aligned"
        )


# What the nav and the box that fills the window are actually at, in the browser.
_GEOMETRY = """
const nav = document.querySelector('nav').getBoundingClientRect();
const box = document.querySelector('[data-fills]').getBoundingClientRect();
const here = document.querySelector('nav a[aria-current="page"]');
const other = [...document.querySelectorAll('nav a')].find(a => a !== here);
const at = el => { const r = el.getBoundingClientRect();
                   return {top: r.top, bottom: r.bottom, height: r.height}; };
return {
  navHeight: Math.round(nav.height * 100) / 100,
  navBottom: Math.round(nav.bottom * 100) / 100,
  boxTop: Math.round(box.top * 100) / 100,
  boxHeight: Math.round(box.height * 100) / 100,
  room: getComputedStyle(document.documentElement).getPropertyValue('--room').trim(),
  here: at(here),
  other: at(other),
  scrolls: document.documentElement.scrollHeight > innerHeight,
};
"""

# `.sr-only` undone, and nothing else: one declaration puts the heading back in
# flow, which is the state every one of these pages shipped in until this round.
# (0,1,1) against `.sr-only`'s (0,1,0), so it wins on weight rather than on being
# written last.
_HEADING_BACK = ("<style>h1.sr-only { position: static; width: auto; height: auto; "
                 "margin: .2rem 0 .6rem; clip-path: none; }</style>")


@pytest.mark.parametrize("view", ("graph", "table", "timeline"))
def test_the_heading_costs_the_view_no_row(views: dict[str, str], view: str, tmp_path: Path):
    """The row of space was the point of the change, so it is measured.

    A heading that is merely *styled* `.sr-only` and a heading that actually costs
    the page nothing are two different claims, and the second is the one the owner
    asked for. `.sr-only` is `position: absolute`, so the heading leaves the flow
    entirely rather than shrinking to a pixel in it — this puts it back with one
    declaration and asks the browser what the page looked like before.

    The number goes into the box that fills the window, because the shell measures
    the room rather than counting the rows above it: whatever the heading stops
    taking, the view gets.
    """
    from browser import chrome, measured_in

    browser = chrome()

    def geometry(name: str, extra: str) -> dict:
        page = views[view].replace("</body>", extra + "</body>")
        return measured_in(browser, page, tmp_path / f"{view}-{name}.html", 1280, _GEOMETRY)

    now, before = geometry("now", ""), geometry("before", _HEADING_BACK)

    reclaimed = before["boxTop"] - now["boxTop"]
    assert reclaimed > 30, (
        f"{view}: the heading was drawn at {before['boxTop']} and is clipped at "
        f"{now['boxTop']} — {reclaimed}px, which is not a row of a 1.35rem heading "
        f"and its margin. The clip resolved and changed no layout."
    )
    assert now["boxTop"] < before["boxTop"]
    # And the room is handed to the view rather than left at the top of the page.
    assert int(now["room"].removesuffix("px")) >= int(before["room"].removesuffix("px"))


def test_the_current_nav_item_is_drawn_and_not_merely_resolved(
    views: dict[str, str], tmp_path: Path
):
    """Weight, colour and a box — three channels, each proved to paint.

    A stylesheet resolving is not a pixel appearing: the frozen column's edge
    resolved to exactly the asserted value on exactly the asserted element and
    Chrome drew nothing, for a whole round, under a green suite. So each channel
    is switched off on its own here and the page is photographed again. A channel
    that changes no pixel is a channel that is not there, and "colour alone" is
    precisely what this design was not allowed to be.

    One at a time and never together: all three at once passes on any one of them,
    which would let two dead channels ship behind one live one.
    """
    from browser import chrome, measured_in, screenshot

    browser = chrome()
    page = views["table"]

    # Each is the same two selectors the shell uses, appended after them, so each
    # is the last declaration standing for exactly its own property. `:visited` is
    # in the list because the shell's rule is, and a nav link on a page a reader
    # has opened before is the case the pair exists for.
    def off(declarations: str) -> str:
        return ('<style>nav a[aria-current="page"], nav a[aria-current="page"]:visited '
                f"{{ {declarations} }}</style>")

    def shot(name: str, extra: str) -> bytes:
        html = tmp_path / f"nav-{name}.html"
        html.write_text(page.replace("</body>", extra + "</body>"))
        return screenshot(browser, html, tmp_path / f"nav-{name}.png")

    # The control, and it is a `skip` rather than a failure when it does not
    # hold. Everything below measures one page against another by comparing
    # bytes, so a renderer that draws the same page two ways cannot be asked the
    # question at all — the test has no reading, which is not the same as a
    # reading of "broken". A CI runner did exactly this: identical HTML, two
    # different PNGs, on a machine where the suite is otherwise green and where
    # this same test passes locally every time.
    #
    # Retried first, because the usual cause is a font or a raster that has not
    # settled on the first paint and does settle by the third.
    marked = shot("marked", "")
    for attempt in range(3):
        if marked == shot(f"again{attempt}", "<style>/* nothing */</style>"):
            break
        marked = shot("marked", "")
    else:
        pytest.skip(
            "this browser does not render the same page the same way twice, so no "
            "inequality below would mean anything"
        )

    for channel, declarations in (
        ("weight", "font-weight: 400;"),
        ("colour", "color: var(--muted);"),
        # The border keeps its width and loses its ink, so this is the box's
        # pixels and not the box's geometry: a difference here cannot come from
        # the row reflowing.
        ("box", "background: none; border-color: transparent;"),
    ):
        assert marked != shot(channel, off(declarations)), (
            f"the {channel} of the current nav item changes no pixel: the "
            f"declaration is dead, and what is left is two channels doing the "
            f"work of three"
        )

    # And the mark costs the row nothing. The item gains padding and a border, so
    # the question is whether the nav got taller — it does not, because the theme
    # toggle is a 28px circle and the marked item comes to less than that.
    def navbox(name: str, extra: str) -> dict:
        html = page.replace("</body>", extra + "</body>")
        return measured_in(browser, html, tmp_path / f"navbox-{name}.html", 1280, _GEOMETRY)

    lit_up = navbox("lit", "")
    plain = navbox("plain", off("padding: 0; border: 0; background: none;"))
    assert lit_up["navHeight"] == plain["navHeight"], (
        f"the mark made the nav {lit_up['navHeight']}px against {plain['navHeight']}px, "
        f"so the row it gave back at the heading it took again here"
    )
    assert lit_up["here"]["height"] > lit_up["other"]["height"], (
        "the marked item is the same box as its siblings: the padding and the "
        "border resolved and were not drawn"
    )
    assert not lit_up["scrolls"], "the page scrolls, so the room is not the window's"


# The window changes under a page that is already open, and the graph's commit bar
# grows a line of buttons above a canvas that is already drawn. Both are answered
# by re-measuring, and both are events rather than rendering frames — which is the
# whole reason they are the two the shell listens for.
_AFTER = """
const box = document.querySelector('[data-fills]');
const bar = document.querySelector('.commitbar');
const state = () => ({
  room: document.documentElement.style.getPropertyValue('--room'),
  barHeight: Math.round(bar.getBoundingClientRect().height),
  scrolls: document.documentElement.scrollHeight - document.documentElement.clientHeight,
  // The gap between the bar and the box, whichever of them is on top. See `_ROOM`,
  // which carries the same measurement and the reason it is written this way.
  clearance: Math.round(Math.max(
    bar.getBoundingClientRect().top - box.getBoundingClientRect().bottom,
    box.getBoundingClientRect().top - bar.getBoundingClientRect().bottom)),
  // How far the box runs past the bottom of the window. This is what a stale
  // measurement looks like now that the bar is above the canvas rather than
  // below it: the box does not stop where the window does. It used to show up as
  // the box running UNDER the bar, which was the same fact seen through the one
  // piece of furniture that happened to be in the way.
  overflow: Math.round(box.getBoundingClientRect().bottom - innerHeight),
});
const settled = state();
// A row of furniture appears above the canvas — a heading a future page adds, or
// a filter bar that rewrapped. Followed by a resize, because that is the event
// the shell is listening for and the point is that it answers a page that has
// already changed shape under it.
const spacer = document.createElement('p');
spacer.style.margin = '0';
spacer.style.height = '120px';
spacer.textContent = 'one more row';
document.querySelector('.canvas').before(spacer);
const stale = state();
dispatchEvent(new Event('resize'));
const remeasured = state();
spacer.remove();
dispatchEvent(new Event('resize'));

// And edit mode, which puts Save and Reset into the bar the canvas has to clear.
const before = state();
document.getElementById('connect').click();
const editing = state();
return {settled, stale, remeasured, before, editing};
"""


def test_a_window_that_changes_under_an_open_page_is_measured_again(
    views: dict[str, str], tmp_path: Path
):
    """The measurement is only as good as the moments it is taken at.

    A `ResizeObserver` on the body was the first version of this and is
    deliberately not what shipped: an observer is delivered on a rendering frame,
    and neither of the places this can be run produces them — a headless Chrome
    under a virtual clock manages two frames in three seconds, a background tab
    manages none. A test of it would have passed against an observer that had been
    deleted, which is the shape of every defect the audits before this one found.

    So the two triggers are events. This fires both and reads back what they did:
    a page whose furniture changed is wrong until the resize, and right after it.
    """
    from browser import chrome, measured_in

    # 700px wide, because the second half of this needs a window narrow enough
    # that Save and Reset put the commit bar onto a second line. At 1400 they fit
    # beside the button that reveals them, the bar does not grow, and the edit-mode
    # assertion below would hold against a `tally` that measured nothing.
    got = measured_in(chrome(), views["graph"], tmp_path / "after.html", 700, _AFTER, 900)

    assert got["settled"]["scrolls"] == 0 and got["settled"]["clearance"] >= 0
    assert got["settled"]["overflow"] <= 0

    # A row appeared and nothing has been told yet: this is the state `78vh` was
    # in permanently, and it is what the resize has to undo. Asked as overflow
    # rather than as clearance since the bar moved above the canvas: a spacer
    # inserted between the two pushes the box off the bottom of the window and
    # never into the bar, so clearance would report a page in perfect health here
    # and this test would prove nothing about the measurement that follows.
    assert got["stale"]["overflow"] > 0, (
        "120px of furniture appeared above the canvas and it still stopped where "
        "the window does, so this proves nothing about the measurement that follows"
    )
    assert got["stale"]["scrolls"] > 0

    assert got["remeasured"]["overflow"] <= 0, (
        f"after the resize the canvas still runs {got['remeasured']['overflow']}px "
        f"past the bottom of the window"
    )
    assert got["remeasured"]["clearance"] >= 0
    assert got["remeasured"]["scrolls"] == 0
    assert got["remeasured"]["room"] != got["stale"]["room"], "nothing was measured again"

    # Edit mode is the one thing that changes the height around the box without
    # the window moving, so `tally` asks for the measurement itself.
    assert got["editing"]["barHeight"] > got["before"]["barHeight"], (
        "the bar did not grow, so nothing here is a test of what happens when it does"
    )
    assert got["editing"]["room"] != got["before"]["room"], (
        f"the bar grew from {got['before']['barHeight']} to "
        f"{got['editing']['barHeight']}px and the canvas kept all "
        f"{got['before']['room']} of its room"
    )
    assert got["editing"]["clearance"] >= 0 and got["editing"]["scrolls"] == 0


# --- the motion floor --------------------------------------------------------


_MOTION = """
// The grip belongs to whichever document is on screen, and the exported page opens
// on the index, where every article is hidden and `place()` hides the grip with
// them. So drive the page the way a reader does — set the hash, call the page's
// own `show()` — rather than clearing `hidden` from here, which would be this test
// inventing a state the app never puts itself in.
location.hash = document.querySelector('article.record').id;
show();
const grip = document.getElementById('grip');
const painted = getComputedStyle(grip, '::before');
return {
  asked: matchMedia('(prefers-reduced-motion: reduce)').matches,
  shown: !grip.hidden,
  // "0.15s, 0.15s" resting, one value once the blanket rule wins. Numbers, so the
  // assertion is about how long the fade lasts and not about how Chrome spells it.
  seconds: painted.transitionDuration.split(',').map(one => parseFloat(one)),
};
"""


def test_a_reader_who_asked_for_less_motion_gets_none_of_the_motion_there_is(
    rendered: Path, tmp_path: Path
):
    """The quality floor, asked of the browser because nothing else can answer it.

    `prefers-reduced-motion` is a setting on the reader's machine. A page cannot
    see it, `cascade.py` skips at-rules by construction, and a test that searched
    the stylesheet for the block would be the same test that passed on the frozen
    column's edge while Chrome painted nothing — presence is not effect.

    So the app's one animated rule is measured twice, and the assertion is the
    difference between the runs. The resting run matters as much as the forced
    one: without it a page that had lost the transition altogether would pass this
    quietly, and the floor would be a claim about nothing.

    It also proves the `!important` in the shell's block is load-bearing rather
    than decorative. `#grip::before` is a `_DETAIL_STYLE` rule, inlined *after* the
    shell's, and at equal importance it would win the tie on order and keep its
    fade. It does not.
    """
    from browser import chrome, measured_in

    browser = chrome()
    page = read(rendered, "detail.html")

    resting = measured_in(browser, page, tmp_path / "motion-resting.html", 1400, _MOTION)
    assert not resting["asked"], "Chrome came up already asking for reduced motion"
    assert resting["shown"], "the grip is hidden, so nothing below is about the app's animation"
    assert min(resting["seconds"]) >= 0.1, (
        f"the grip's fade resolves to {resting['seconds']}s, so there is no motion here "
        f"to switch off and this test proves nothing"
    )

    reduced = measured_in(
        browser, page, tmp_path / "motion-reduced.html", 1400, _MOTION,
        flags=("--force-prefers-reduced-motion",),
    )
    assert reduced["asked"], "the flag did not reach the media query"
    assert reduced["shown"]
    assert max(reduced["seconds"]) <= 0.001, (
        f"a reader who asked for less motion still gets a {max(reduced['seconds'])}s fade"
    )


def test_the_motion_floor_is_the_shell_s_and_not_one_page_s(rendered: Path):
    """Where the block lives, which is the half the browser test cannot see.

    It measures `detail.html`, the only page with a transition on it. Written into
    `_DETAIL_STYLE` that test would pass unchanged and every other exported
    page would have no floor at all the day one of them grew an animation —
    which is the same
    shape as the capacity meter's `.bar` rule reaching the timeline: a rule's page
    is a fact about the rule, and nobody notices it from inside one page.
    """
    for name in PAGES:
        style = re.search(r"<style>(.*?)</style>", read(rendered, name), re.S).group(1)
        assert "@media (prefers-reduced-motion: reduce) {" in style, name


_MOVES = re.compile(r"@keyframes|\b(?:transition|animation)(?:-[a-z]+)?\s*:")


def _outside_the_floor(page: str) -> str:
    """A page's stylesheet with the reduced-motion block cut whole out of it, so
    what is left is the motion that block exists to switch off."""
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    css = re.sub(r"/\*.*?\*/", " ", style, flags=re.S)
    at = css.find("@media (prefers-reduced-motion: reduce) {")
    assert at >= 0, "this page has no motion floor, so there is nothing to cut out of it"
    depth, i = 0, at
    while True:
        depth += (css[i] == "{") - (css[i] == "}")
        if depth == 0 and css[i] == "}":
            break
        i += 1
    return css[:at] + css[i + 1:]


# The pages that inline `_DETAIL_STYLE`, which is where the app's one animated rule
# is written. `#grip` exists on the detail page alone, so on the cycles index the
# declaration ships with no element to move — a stylesheet meant for one page,
# loaded by another, which is the shape of the worst defect this branch had. Inert
# here rather than harmful, and it is why the floor is written in the shell: a rule
# that travels has to be switched off wherever it lands, not next to where it was
# written.
_CARRIES_MOTION = ("detail.html", "cycles.html")


def test_the_app_moves_in_two_places(rendered: Path):
    """The inventory the floor's comment claims, kept true by something other than
    the person who wrote it.

    The blanket rule covers whatever is written next, so this is not a ban on new
    motion — it is what lets the comment say "these and no others" without going
    stale, and the trigger to check the two things a new `transition` needs: that
    it is inside the shell's reach, and that it is not on a canvas.

    Two, since the hill. The ball rolls between its stops when the status changes,
    which is in the shell and therefore on every page — a ball that teleports says
    a different thing from a ball that moves, and what this picture is about is
    *which way the work is going*. It passed both checks: the shell's own
    reduced-motion block is inlined before every page's stylesheet and marked
    `!important`, and the hill is SVG and HTML rather than a canvas.

    The `--roll` token is why there is one declaration and not two. A ball under
    the pointer has to be under the pointer, so a drag switches the roll off — and
    written as `transition: none` that read here as a second moving thing, which is
    the absence of motion spelled in the grammar of motion.
    """
    for name in PAGES:
        found = _MOVES.findall(_outside_the_floor(read(rendered, name)))
        expected = 2 if name in _CARRIES_MOTION else 1
        assert len(found) == expected, f"{name} moves in {len(found)} places, not {expected}"
        assert (name in _CARRIES_MOTION) == (
            "transition: opacity .15s, background .15s" in read(rendered, name)
        ), name
    assert 'id="grip"' in read(rendered, "detail.html")
    assert 'id="grip"' not in read(rendered, "cycles.html"), (
        "the cycles index grew a grip, so the rule it has been carrying now moves "
        "something and the floor is doing more than it was measured doing"
    )


def test_the_graph_does_not_animate_where_css_cannot_stop_it():
    """A canvas is the exception the floor cannot cover: cytoscape draws into one,
    and no stylesheet slows that down.

    Nothing on this page animates, and since the layout became a direct call to
    ELK there is no cytoscape layout to ask for animation in the first place —
    ELK returns positions and they are applied inside a `cy.batch`. What is left
    to guard is that neither cytoscape's own animation API nor a re-introduced
    `layout({...})` brings a slide back for a reader who asked for stillness.
    """

    source = render_source()
    for spec in re.findall(r"\.layout\((\{[^}]*\})\)", source):
        assert "animate" not in spec, (
            f"cytoscape was told to animate in {spec}; CSS cannot reach a canvas, so "
            f"the layout has to ask matchMedia('(prefers-reduced-motion: reduce)') itself"
        )
    assert ".animate(" not in source, "cytoscape's own animation API moves the canvas too"
    assert "const LAYOUT_OPTIONS = {" in source, "the ELK options are not where this expects"
    assert "animate" not in re.search(
        r"^const LAYOUT_OPTIONS = (\{.*?^\};)", source, re.M | re.S
    ).group(1)


def test_no_page_uses_one_id_for_more_than_one_element(rendered: Path):
    """An id names one element, and five of them named five.

    `detail.html` is every record in one document with a hash router over them,
    and the facts list inside each article carried `id="facts"` — so the export
    held five, which is invalid, and `getElementById('facts')` would answer with
    the first record's list whatever the hash said. Nothing calls it today: it is
    a hook, the styling is `.panes > .facts dl`, and a hook that answers the
    wrong element is worse than no hook. It is written now only on the page that
    holds one record, which is what an id means.

    Asked of every page and not of that one, because this is the kind of thing
    that arrives with the next template that gets rendered in a loop.
    """
    from collections import Counter
    from html.parser import HTMLParser

    class Ids(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.seen: Counter[str] = Counter()

        def handle_starttag(self, tag, attrs):
            found = dict(attrs).get("id")
            if found:
                self.seen[found] += 1

    for page in PAGES:
        parser = Ids()
        parser.feed(read(rendered, page))
        repeated = {one: n for one, n in parser.seen.items() if n > 1}
        assert not repeated, f"{page} uses one id for several elements: {repeated}"

# --------------------------------------------------------------------------- #
# Where a cycle stops building
# --------------------------------------------------------------------------- #


def test_the_solid_rule_is_the_end_of_build_and_the_dashed_one_the_end_of_the_window(
    seed_index: Index,
):
    """An overrun is measured against the end of BUILD (`schedule._overrun`), and
    the chart drew its only rule at the end of the window — two weeks of cool-down
    further right. A bar could finish visibly before the line and still be amber,
    which is how a timeline loses a room."""
    from openproj.render import _timeline

    drawn = {c["number"]: c for c in _timeline(seed_index)["cycles"]}
    cycle = drawn[36]

    assert cycle["build_x"] is not None and cycle["rule_x"] is not None
    assert cycle["build_x"] < cycle["rule_x"], "build ends before the window does"
    # And the cool-down is shaded from one to the other, rather than reading as
    # two more weeks of building time.
    assert cycle["cool_x"] == cycle["build_x"]
    assert cycle["cool_width"] > 0


def test_the_page_draws_both_rules(rendered: Path):
    page = read(rendered, "timeline.html")
    assert 'class="build-rule"' in page
    assert 'class="cycle-rule"' in page
    assert "stops building here" in page


# --------------------------------------------------------------------------- #
# The shaping document, read rather than required
# --------------------------------------------------------------------------- #


def test_a_templates_guidance_never_reaches_the_page(seed_index: Index):
    """The team's pitch template carries its instructions in HTML comments, which
    are invisible in HackMD. With `html: False` markdown-it prints them as text,
    so every pitch drafted from the template would arrive with its own
    instructions showing."""
    from openproj.render import preview_html

    body = "## Problem\n<!-- The raw idea. -->\n\nReal text.\n"
    out = str(preview_html(body))
    assert "The raw idea" not in out
    assert "Real text." in out
    # But an example inside a fence is the author's, and stays.
    fenced = "```\n<!-- kept -->\n```\n"
    assert "kept" in str(preview_html(fenced))


def test_a_ready_pitch_missing_a_no_gos_section_is_told_so_on_its_own_page(rendered: Path):
    """A printed note and nothing more: it never reaches `openproj check`, never
    fails CI and never blocks a save.

    Only live bets are told. Three corpus pitches are ready or in progress, one of
    which was shaped with both sections and two of which are thin, with
    neither — so the page carries exactly two of each note, and the two finished
    pitches are left alone."""
    page = read(rendered, "detail.html")
    assert 'class="hints"' in page
    assert page.count("No No-gos section") == 2
    assert page.count("No Rabbit holes section") == 2


def test_the_progress_column_counts_the_bodys_own_checklist():
    """Counted, never written: nothing requires a checklist, and a body without
    one shows an empty cell rather than 0/0."""
    from openproj.model import Config, Task
    from openproj.render import _payload, _row

    index = build_index(
        [
            Task(id="task-000009", kind="task", title="With a list",
                 body="## Progress\n\n- [x] a\n- [ ] b\n"),
            Task(id="task-000010", kind="task", title="Without one", body="prose"),
        ],
        Config(),
        date(2026, 8, 17),
    )
    # With its unit, like the rollup's weeks: one column holding `1/2` beside
    # `0/1 wk` reads as two measurements of one thing.
    assert _row(index, "task-000009")["progress_text"] == "1/2 items"
    assert _row(index, "task-000009")["progress"] == 0.5
    assert _row(index, "task-000010")["progress"] is None
    # And it is derived, so no cell offers to edit it.
    assert "progress" not in _payload(index)["editable"]


def test_a_pitch_draws_its_tasks_as_the_progress_it_has_made(rendered: Path, seed_index: Index):
    """The question a pitch page is opened for is where the work has got to, and
    the answer was a checklist somewhere in the middle of the prose — or, for a
    pitch whose work is tracked as tasks, nowhere at all. Every tick is a task's
    own status, so there is no checkbox here to keep in step by hand.

    The panel is a CONTAINMENT rollup over any planned record with children, not a
    tasks-of-a-pitch panel. It only ever listed tasks because a pitch was the only
    parent kind the corpus had; a product's lines are its projects and a project's
    are its pitches.
    """
    page = read(rendered, "detail.html")
    panels = re.findall(r'<section class="progress read">.*?</section>', page, re.S)

    assert panels, "the corpus has pitches with tasks under them"
    # Ticked from status, both ways round somewhere on the page: the corpus holds
    # finished tasks and unfinished ones under the same pitches.
    assert any("☑" in panel for panel in panels)
    assert any("☐" in panel for panel in panels)
    # And every line is a link to the CHILD it counts, whatever rung that child is
    # on, which is the other half of moving this out of the prose. This asked for
    # `task-[0-9a-f]{6}` and passed on a corpus accident: nothing but a pitch could
    # be a parent, so nothing but a task could be a line. Products and projects
    # became parents on 2026-08-23 and three of the nine panels stopped matching.
    linked = [re.findall(r'<a href="[^"]*?([a-z]+-[0-9a-f]{6})">', panel) for panel in panels]
    assert sorted(linked) == sorted(p.of for p in seed_index.progress.values() if p.of)
    # And it reaches three rungs, so none of the above is a claim about tasks
    # wearing a general shape.
    kinds = {seed_index.plan[child].kind for ids in linked for child in ids}
    assert kinds == {"task", "pitch", "project"}, kinds


def test_a_pitch_says_what_its_tasks_add_up_to_beside_what_it_was_bet_at(rendered: Path):
    """An appetite read on its own says nothing about whether the work still fits.
    The corpus's pitch-5e7b1c was bet at four weeks and holds 8.1 of tasks."""
    page = read(rendered, "detail.html")
    assert "8.1 in tasks" in page
    assert 'class="overrun">8.1 in tasks' in page, "over the bet, and said so"


def test_a_pitch_that_keeps_a_checklist_as_well_as_tasks_is_told_which_one_counts():
    """A list somebody is ticking that moves no number on the page is worse than
    no list at all, so the one being ignored says so instead of being silently
    ignored."""
    from openproj.model import Pitch
    from openproj.render import _shaping_hints

    live = Pitch(id="pitch-000001", kind="pitch", title="Q", status="in_progress",
                 body="## Progress\n\n- [x] a\n- [ ] b\n")
    both = _shaping_hints(live, has_tasks=True)
    alone = _shaping_hints(live, has_tasks=False)

    assert any("the checklist is not" in note for note in both)
    assert not any("the checklist is not" in note for note in alone), (
        "with no tasks under it, the checklist is what there is"
    )


def test_the_pitch_template_leaves_progress_to_its_tasks():
    """The one place the template departs from the team's HackMD original: a
    pitch's progress is its tasks, each a record with an owner and a size, and
    the sub-items of the HackMD list are what a task's own checklist is for."""
    from openproj.render import TEMPLATES

    assert "## Progress" not in TEMPLATES["pitch"]
    assert "## Progress" in TEMPLATES["task"]
    assert "## For later" in TEMPLATES["pitch"]


def test_a_pitch_with_no_appetite_yet_is_not_accused_of_exceeding_it():
    """`_rollup_problems` says nothing where no bet was made, and the page has to
    agree: a number shouted in warning colour where `check` is silent teaches a
    reader that one of the two is lying."""
    from openproj.model import Config, Pitch, Task
    from openproj.render import _fact_rows

    index = build_index(
        [
            Pitch(id="pitch-000001", kind="pitch", title="Q"),
            Task(id="task-000001", kind="task", title="T", parent="pitch-000001",
                 person_weeks=3.0),
        ],
        Config(),
        date(2026, 8, 17),
    )
    from openproj.render import STATIC

    row = next(
        r for r in _fact_rows(index, index.plan["pitch-000001"], STATIC)
        if r["label"].startswith("Appetite")
    )

    assert "3 in tasks" in row["display"]
    assert 'class="quiet"' in row["display"], "no bet to be over"


def test_the_progress_column_appears_only_once_a_plan_has_a_checklist(seed_index: Index):
    """Counted out of the body rather than stored, so a plan where nobody keeps a
    list would carry a permanently empty column across fourteen others — which
    reads as broken, not as unused."""
    from openproj.model import Config, Task
    from openproj.render import _columns_for

    def index_of(*bodies: str) -> Index:
        return build_index(
            [
                Task(id=f"task-00000{n}", kind="task", title="T", body=body)
                for n, body in enumerate(bodies)
            ],
            Config(),
            date(2026, 8, 17),
        )

    assert "progress" not in dict(_columns_for(index_of("prose only")))
    assert "progress" in dict(_columns_for(index_of("prose only", "- [ ] a\n")))
    # The corpus does keep lists — its migration stubs carry them — so the column
    # is there, which is what makes the two rendered pages differ.
    assert seed_index.progress
    assert "progress" in dict(_columns_for(seed_index))


def test_a_cycle_with_no_record_says_what_every_other_view_says_about_it(seed_index: Index):
    """Cool-down is inside a window, so taking the window's last day for the
    review meeting made the page offer 7.8 weeks of capacity against a build the
    scheduler ends seven weeks in. Three answers about one cycle, and a betting
    table would have bet against the largest.

    The corpus dates cycles 28 and 34–36 in `config/cycles.yaml` and writes a
    record for none of them, which is the state every plan passes through."""
    from openproj.render import _cycle_view
    from openproj.schedule import build_end

    config = Config(holidays=seed_index.holidays, cooldown_weeks=seed_index.cooldown_weeks)
    unrecorded = [n for n in seed_index.cycles if n not in seed_index.plans]
    assert unrecorded, "the corpus dates cycles it has written no record for"

    for number in unrecorded:
        view = _cycle_view(seed_index, number)
        window = seed_index.cycles[number]

        assert view["builds_until"] == build_end(number, window, config).isoformat(), number
        assert view["ends_on"] == window[1].isoformat(), number
        assert float(view["build_weeks"]) <= config.working_weeks(*window), number


def test_the_page_is_allowed_to_talk_to_its_own_server(rendered: Path):
    """Every save is a `fetch` and the live update is an `EventSource`, and both
    are `connect-src`. It was never listed, so both fell back to
    `default-src 'none'`: the whole app was readable and could write nothing.
    A save reported "Failed to fetch" and the stream closed the moment it opened,
    on every page, in every browser that enforces the policy — which is all of
    them."""
    from openproj.render import CSP

    assert "connect-src 'self'" in CSP
    # `'self'`, not a host: the same string has to be right on localhost and
    # behind the service URL.
    assert "connect-src http" not in CSP
    assert "connect-src 'self'" in read(rendered, "table.html")


def test_a_remembered_width_of_nothing_is_thrown_away(rendered: Path):
    """Half-trusting one is worse than ignoring the lot. Skipped at apply time
    the column still drew, so the table was set narrower than the columns it
    contains and every one of them squeezed until the text wrapped; measured
    instead, it measures the squeeze it is already in and stays there. A stored
    `"progress":0` made the header and the first six rows up to five times their
    height, at every window width, until the entry was deleted by hand."""
    page = read(rendered, "table.html")
    guard = re.search(r"function trustworthy\(stored\) \{.*?\n\}", page, re.S).group(0)

    assert "some(width => !(width > 0))" in guard
    assert "remembered.forget(WIDTH_KEY)" in guard, "cleared, not re-rejected every load"
    assert "trustworthy(remembered.map(WIDTH_KEY))" in page
    # And the fit that writes them never writes a nothing in the first place.
    assert "WIDTHS[key] = Math.max(1, Math.round(width[i]))" in page


# --------------------------------------------------------------------------- #
# The icon a person picks for themselves
#
# Drawn on the People page and nowhere else. What is under test here is mostly
# the choice of medium: an inline path is in the file, and the emoji it is not
# would be resolved by whatever colour font the reader's machine happens to have
# — which for a static export mailed to somebody, opened over `file://` with no
# network, is the one thing on the page that would not arrive.
# --------------------------------------------------------------------------- #


def with_icons(root: Path, chosen: dict[str, str]) -> Index:
    """The corpus, plus a person record for each login named here.

    Built through `Config.with_people`, which is the door `load_repo` and the
    server both use, so this cannot pass over an index shape the loaders do not
    produce.
    """
    from openproj.model import Person

    records, config, unreadable = load_repo(root)
    people = [Person(login=login, icon=icon) for login, icon in chosen.items()]
    return build_index(
        records, config.with_people(people), date(2026, 8, 17), unreadable
    )


def someone(index: Index) -> str:
    """A login the People page actually draws a row for, taken from the corpus
    rather than written down: the page is built from who holds work, so a name
    chosen by hand here is a name the page is free to stop listing."""
    return sorted(record.owner for record in index.plan.values() if record.owner)[0]


def test_a_persons_icon_is_drawn_in_the_page_and_not_fetched(seed_root: Path):
    """The whole argument for inline SVG over an emoji or an image, asserted in
    one place: the mark is an element with a path in it, on the row of the person
    who chose it, and the page asks nothing of the network to draw it.

    An `<img>` would need a server or a directory beside the file; an emoji would
    need a font, and on an ordinary Linux workstation with no colour-emoji font
    it is a tofu box — a login whose icon is a box looks like the tool is broken
    rather than like nobody has chosen.
    """
    from openproj.render import render_people

    who = someone(with_icons(seed_root, {}))
    page = render_people(with_icons(seed_root, {who: "fox"}))

    row = page.split(f'data-login="{who}"')[1].split("</tbody>")[0]
    assert '<svg class="icon"' in row, row[:400]
    assert "<path" in row
    assert "<img" not in row
    assert "src=" not in row


def test_a_plan_where_nobody_has_picked_one_draws_the_page_as_it_was(seed_root: Path):
    """The ordinary case, and the live one: no `people/` directory at all. A
    feature that needs somebody to have used it before the page works is a
    feature that ships broken."""
    from openproj.render import render_people

    page = render_people(with_icons(seed_root, {}))

    assert '<svg class="icon"' not in page
    assert 'class="who"' in page, "the names are still there"
    assert 'id="picker"' not in page


def test_an_icon_nothing_draws_costs_the_drawing_and_nothing_else(seed_root: Path):
    """`Person.icon` is a plain `str | None` and deliberately not an enum of the
    the ones that exist today, for the same reason `status` is a plain `str`: a file
    written before
    an icon was renamed has to survive being read. So a stored `dragon` is a name
    the page has no drawing for, and the row is otherwise exactly the row."""
    from openproj.render import render_people

    who = someone(with_icons(seed_root, {}))
    page = render_people(with_icons(seed_root, {who: "dragon"}))

    assert '<svg class="icon"' not in page
    assert f'data-login="{who}"' in page


def test_no_icon_is_a_character_the_reader_has_to_own_a_font_for():
    """The decision, guarded where it can be undone in one edit.

    Twelve emoji would be a shorter constant and a worse page: an emoji is drawn
    by the platform's colour font, so the same file draws a different fox on
    every machine and no fox at all on one with no such font — and every other
    thing these pages need is inside them, down to the typeface being a `data:`
    URI. Read out of `render.py` rather than restated, so the next icon is checked
    on the commit that adds it.
    """
    from openproj import render

    for name, art in render._ICON_ART.items():
        assert name.isascii() and name.islower(), name
        assert art.isascii(), f"{name} is drawn with a character and not with a path"
        assert "<path" in art or "<circle" in art, name


def test_no_two_icons_are_the_same_mark(seed_root: Path):
    """A set of marks is worth having only if each one is somebody's own.

    The names cannot collide — they are dict keys — so the collision this guards
    against is the other one: a drawing pasted twice under two names, which is
    the ordinary way a set doubles in size. Two people would then have the same
    mark under different words, and nothing anywhere would say so.

    What it cannot do is tell two DIFFERENT paths apart at 20px, which is the
    real constraint. That question has no test in this suite and is not pretended
    to have one: every candidate was rendered at 20px beside the whole set and
    looked at, and the seven that failed are named in the comment above
    `_ICON_ART`. A test that resolved a path to pixels and compared them would be
    a worse version of a person's eye, not a better one.
    """
    from openproj.render import _ICON_ART, ICONS

    drawings = {}
    for name, art in _ICON_ART.items():
        assert art not in drawings, f"{name} is drawn exactly like {drawings.get(art)}"
        drawings[art] = name

    assert tuple(drawings.values()) == ICONS, "the vocabulary is the drawings and nothing else"


def test_every_icon_is_a_row_in_the_picker_with_its_name_beside_it(seed_root: Path):
    """A `<select>` cannot hold an SVG and a strip of bare buttons cannot hold
    twenty-five rows, so the picker is a listbox — and what makes it one is that
    every row carries both the drawing and the word.

    The word is not decoration: it is what is stored, what `PUT /api/icon` will
    refuse by name, and the only thing a reader can use to tell two marks apart
    when they cannot see either. Parsed rather than searched for, because a
    substring cannot tell a `data-icon` attribute from the same letters in a
    title, and every row's id has to be unique — `aria-activedescendant` is a
    reference by id, and two rows sharing one is a keyboard that lands on the
    wrong drawing.
    """
    from html.parser import HTMLParser

    from openproj.render import ICONS, render_people

    class Rows(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.rows: list[dict] = []
            self.depth = 0

        def handle_starttag(self, tag, attrs):
            got = dict(attrs)
            if got.get("role") == "option":
                self.rows.append({"id": got.get("id"), "icon": got.get("data-icon"),
                                  "svg": 0, "name": ""})
                self.depth = 1
            elif self.depth:
                self.depth += 1
                self.rows[-1]["svg"] += tag == "svg"

        def handle_endtag(self, tag):
            self.depth = max(0, self.depth - 1)

        def handle_data(self, data):
            if self.depth and data.strip():
                self.rows[-1]["name"] += data.strip()

    who = someone(with_icons(seed_root, {}))
    reader = Rows()
    reader.feed(render_people(with_icons(seed_root, {}), editable=True, me=who))

    # The way out first, and it is the one row with no drawing: nothing is what
    # it sets, so a mark beside it would be a mark it does not mean.
    assert reader.rows[0] == {"id": "pick-none", "icon": "", "svg": 0, "name": "No icon"}
    assert [row["icon"] for row in reader.rows[1:]] == list(ICONS)
    for row, name in zip(reader.rows[1:], ICONS, strict=True):
        assert row["name"] == name, f"{name} has no name beside its drawing"
        assert row["svg"] == 1, f"{name} has no drawing beside its name"
        assert row["id"] == f"pick-{name}"
    assert len({row["id"] for row in reader.rows}) == len(reader.rows)


def test_the_static_export_carries_the_drawings_and_offers_no_picker(
    seed_root: Path, tmp_path: Path
):
    """`openproj render` is what happens if the service goes away, and a plan
    read off a memory stick has to still say who is who. It also has no server,
    so a control that posts to one would be a button that does nothing — the
    export's own version of a dead end you can only find by pressing it."""
    who = someone(with_icons(seed_root, {}))
    render_static(with_icons(seed_root, {who: "owl"}), tmp_path)

    page = read(tmp_path, "people.html")

    assert '<svg class="icon"' in page
    assert 'id="picker"' not in page
    assert 'id="pick"' not in page
    assert "/api/icon" not in page


def test_the_facade_reaches_every_name_anything_outside_the_package_asks_for():
    """`render/__init__.py` exists to be the whole of what `openproj.render` is,
    private names included — `web.py` reaches `render._payload`, and tests import
    `_TABLE_COLUMNS`, `_body_html`, `_TASK_TEMPLATE` and a dozen more.

    **Be clear about what this catches, because it is narrower than it looks.**
    A missing `from openproj.render import X` is an ImportError at COLLECTION and
    this test never gets to run — that is how `_containment_rows` was found, and
    this test would not have caught it. What it catches is the other half:
    ATTRIBUTE reaches, `render.X`, which import fine and raise at runtime. Those
    are the dangerous ones, because `web.py` is full of them and a route that
    raises `AttributeError` in production is a 500 nobody saw in CI.

    It also turns the collection error into a sentence. A traceback that says
    `cannot import name '_containment_rows'` tells you a name is missing; this
    tells you the facade is what is missing it, which is where the fix goes.

    Derived rather than listed, so the next name arrives with a failing test
    rather than with a list somebody forgot to update.
    """
    import ast

    from openproj import render

    root = Path(__file__).resolve().parents[1]
    wanted: set[str] = set()
    for source in [*root.glob("tests/*.py"), *root.glob("src/openproj/*.py")]:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"openproj.render", ".render"}:
                wanted.update(alias.name for alias in node.names)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "render"
            ):
                wanted.add(node.attr)

    # `render` is also the name of an argparse subparser in cli.py, so its
    # attributes land in the sweep. Nothing else is exempt.
    wanted -= {"add_argument", "set_defaults"}

    missing = sorted(name for name in wanted if not hasattr(render, name))
    assert not missing, f"the facade does not re-export {missing}"


def test_one_record_on_its_own_page_is_the_row_the_export_would_have_built(seed_index: Index):
    """`only` is applied inside `_detail_rows` now, not by filtering after it.

    It used to build a row for every record in the plan — each carrying a full
    `markdown_it` render of that record's body — and then keep one. Measured
    under twenty readers on a 561-record corpus, 369 of those page renders were
    92.6 of the server's 113.4 CPU-seconds: about 63% of the machine spent
    drawing markdown that was discarded before it reached anybody.

    Moving the filter is only safe if the surviving row is the SAME row. Asked
    of the ROWS and not of the rendered page, because the two pages are
    legitimately different documents: `only` sets `single`, which changes the
    furniture around the record. What must not change is the record.

    `_detail_rows` is a per-record comprehension with no cross-row state, so it
    should hold — but "should" is how the two halves of a page come apart, and
    this repository has already paid for one fact formatted in two places.
    """
    from openproj.render import _detail_rows

    every = {row["id"]: row for row in _detail_rows(seed_index, ROUTES)}
    assert every.keys() == seed_index.records.keys(), "the export is not every record"

    for record_id in seed_index.records:
        alone = _detail_rows(seed_index, ROUTES, only=record_id)
        assert [row["id"] for row in alone] == [record_id]
        assert alone[0] == every[record_id], (
            f"{record_id} built alone is not the row the export builds for it"
        )


def test_a_record_that_is_not_there_is_an_empty_page_and_not_a_KeyError(seed_index: Index):
    """The route 404s first, so only a non-route caller reaches this — but the
    filter that used to run after the build could not raise, and the one that
    runs inside it can. Same answer as before: nothing, quietly."""
    from openproj.render import _detail_rows

    assert _detail_rows(seed_index, ROUTES, only="task-ffffff") == []
    page = render_detail(seed_index, ROUTES, only="task-ffffff")

    assert "task-ffffff" not in page
    assert "<article" not in page


@pytest.fixture
def phone_pages(seed_index: Index) -> dict[str, str]:
    """Every surface a plan is READ on, served rather than exported.

    Served, because the server's pages are the ones somebody opens on a phone —
    a static export reaches a phone as a file somebody mailed, and it is the
    narrower case of the two. The cycle page and the record page exist only here
    at all.

    The editing surfaces are deliberately absent, and that is a decision rather
    than an omission: the create form, the Ace editor and the betting table's
    inline boxes are a laptop's, and nothing below claims otherwise. What is
    claimed is that a phone can READ the plan without the page fighting it.
    """
    from openproj.render import (
        render_cycle,
        render_detail,
        render_graph,
        render_people,
        render_records,
        render_table,
        render_timeline,
    )

    return {
        "records": render_records(seed_index, STATIC),
        "table": render_table(seed_index, STATIC, base_commit="deadbee", may_write=True),
        "graph": render_graph(seed_index, STATIC, base_commit="deadbee"),
        "timeline": render_timeline(seed_index, STATIC),
        "people": render_people(seed_index, STATIC),
        "cycle": render_cycle(seed_index, 37, ROUTES, base_commit="deadbee"),
        "record": render_detail(
            seed_index, ROUTES, only=next(iter(seed_index.plan)), base_commit="deadbee"),
    }


# What a 390px viewport gets, per page. One script, because one Chrome answering
# seven pages is 3 seconds and seven Chromes are 27 — see `measured_on_a_phone`.
#
# `over` is measured against the DOCUMENT and not against the viewport, and the
# difference is the whole reliability of it: a bar inside the timeline's scroller
# and a column inside the table's are both far past the right edge of the screen
# and both entirely correct, because the box they are in scrolls. What is wrong
# is the PAGE scrolling, which is `scrollWidth` — so that is what is asked, and
# `over` is only there to name the culprit when it does.
_ON_A_PHONE = """
const name = el => el.tagName.toLowerCase()
  + (el.id ? '#' + el.id : '')
  + (typeof el.className === 'string' && el.className.trim()
     ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
const root = document.documentElement;
const vw = root.clientWidth;
const over = [];
for (const el of document.querySelectorAll('body *')) {
  const box = el.getBoundingClientRect();
  if (box.width > 0 && box.height > 0 && (box.right > vw + 1 || box.left < -1)
      && !el.closest('[data-sideways], .sideways, .table-scroll, .scroll')) {
    over.push(name(el) + ' ' + Math.round(box.left) + '..' + Math.round(box.right));
  }
}
const small = [];
for (const el of document.querySelectorAll('input, select, textarea')) {
  const size = parseFloat(getComputedStyle(el).fontSize);
  if (el.getClientRects().length && size < 16) small.push(name(el) + ' at ' + size + 'px');
}
const timeline = document.querySelector('.tl');
const wide = el => Math.round(el.getBoundingClientRect().width);
const search = document.getElementById('q');
const column = document.querySelector('main');
const keys = document.querySelector('.keys');
const off = keys ? [...keys.querySelectorAll('li')].filter(li => {
  const box = li.getBoundingClientRect();
  return box.width > 0 && (box.left < -1 || box.right > vw + 1);
}).map(li => li.textContent.trim() + ' ' + Math.round(li.getBoundingClientRect().left)) : [];
return {
  viewport: vw,
  scrollWidth: root.scrollWidth,
  over: [...new Set(over)].slice(0, 8),
  small: [...new Set(small)],
  labels: timeline ? wide(timeline.querySelector('.labels')) : null,
  chart: timeline ? wide(timeline.querySelector('.scroll')) : null,
  keysOffPage: off,
  search: search ? wide(search) : null,
  column: column ? Math.round(column.clientWidth) : null,
};
"""


@pytest.fixture
def on_a_phone(phone_pages: dict[str, str], tmp_path: Path) -> dict[str, dict]:
    """One Chrome, seven pages, one report each, at a real 390px viewport."""
    from browser import chrome, measured_on_a_phone

    return measured_on_a_phone(chrome(), phone_pages, tmp_path / "phone", _ON_A_PHONE)


def test_a_phone_lays_every_read_surface_out_at_the_width_it_says_it_has(
    on_a_phone: dict[str, dict]
):
    """The harness's own premise, asserted before anything is asked of it.

    `Emulation.setDeviceMetricsOverride` hands a page the width only if the page
    asks for it: without `<meta name="viewport" content="width=device-width">`
    Chrome lays a mobile override out at 980px, the legacy desktop width. So a
    page that loses that tag does not fail the tests below — it PASSES them, at a
    width no phone has, and the suite goes green over a page nobody can read.

    One line, and it is the reason every number under it means anything.
    """
    for page, got in on_a_phone.items():
        assert got["viewport"] == 390, (
            f"{page} laid out at {got['viewport']}px on a 390px phone: it has lost "
            f"its viewport meta tag, and every width measured here is fiction"
        )


def test_no_read_surface_scrolls_sideways_on_a_phone(on_a_phone: dict[str, dict]):
    """A page that is wider than the screen is a page where reading one column
    moves every other thing on it.

    The cycle page did exactly that: the roster is seven columns and the betting
    table eight, both written down as "eight columns fit a screen; the page
    scrolls" — measured against a screen. At 390px the roster ran to 617 and the
    betting table to 865, so `scrollWidth` was 865 against a 390px viewport and
    the headings, the prose, the Save bar and the notes box all slid sideways
    together to let a `load` column be read. The two date boxes in the setup grid
    added 14px of their own past the right edge.

    **Asked of every read surface and not only of the one that broke.** The two
    that legitimately scroll — the table's columns and the timeline's chart —
    scroll INSIDE a box, which is why this asks the document and not the
    elements: `over` exists to name a culprit, `scrollWidth` is the claim.
    """
    for page, got in on_a_phone.items():
        assert got["scrollWidth"] <= got["viewport"], (
            f"{page} is {got['scrollWidth']}px wide on a {got['viewport']}px phone, so the "
            f"whole page scrolls sideways. Past the edge: {got['over'] or 'nothing named'}"
        )


def test_nothing_a_phone_can_focus_is_small_enough_to_zoom_the_page(
    on_a_phone: dict[str, dict]
):
    """Focus a control whose text is under 16px on iOS and Safari scales the whole
    page up to read it — and does not scale back when the control blurs.

    The reader is left on a page too wide for the screen, scrolling sideways
    through a layout that fitted a moment ago, with nothing on screen saying what
    happened or how to undo it. It is the one mobile defect that does not look
    like a layout bug, because the layout was right until it was touched.

    Every read surface had at least one: the search box at 13px, the scheme
    picker at 12px, the timeline's two date boxes and its zoom at 13px, the cycle
    page's rate and bet boxes at 13-14px.

    The stylesheet cannot answer this. The floor is `!important` in the shell and
    every one of these controls has a page rule of its own at higher specificity,
    so what is asked is the RESOLVED size, on the page, at the width where the
    rule applies.
    """
    for page, got in on_a_phone.items():
        assert not got["small"], (
            f"{page} draws a control under 16px, so focusing it zooms the page "
            f"on iOS and never zooms back: {got['small']}"
        )


def test_the_search_box_is_the_whole_row_on_a_phone(on_a_phone: dict[str, dict]):
    """`#q` is `min-width: 16rem`, and a minimum in `rem` is a promise about a
    number of characters that the 16px floor above quietly broke: 256px of 13px
    text became 256px of 16px text, so "Search titles, tags, PRs, people" came
    back clipped at "peopl" on every page that has a search box.

    The claim is the row and not a width. On a 350px column there is nothing else
    beside this box and no reason for it to be anything other than the row it is
    on — which is also true at every phone size, and true whatever the placeholder
    is changed to say next.
    """
    for page, got in on_a_phone.items():
        if got["search"] is None:
            continue
        assert got["search"] >= got["column"] - 1, (
            f"{page} draws a {got['search']}px search box in a {got['column']}px column, "
            f"so its placeholder is clipped with room going spare beside it"
        )


def test_the_timeline_gives_a_phone_more_chart_than_labels(on_a_phone: dict[str, dict]):
    """`.labels` was `flex: 0 0 250px` — a constant, against a viewport that is
    390px and a `.tl` that is 350. The label column took 261 of it and the Gantt
    it labels got 87: not a chart that needs scrolling, a chart with no room to
    draw one bar in.

    The claim is the SPLIT and not the pixel. A number here would be the same
    mistake in a test that the constant was in the stylesheet — what has to hold
    is that the picture gets more of the box than the captions do, at whatever
    width a phone turns out to have.

    Both halves of the fix are needed and only this can tell: with `flex-basis`
    set and `min-width: 0` missing, the basis resolves to `40%`, the query
    applies, and the column is still 261.4px — a flex item's automatic minimum
    size is its min-content size, and these rows are `white-space: nowrap`, so
    the minimum wins outright. A test that read the stylesheet would have found
    a 40% that was doing nothing.
    """
    got = on_a_phone["timeline"]
    assert got["chart"] > got["labels"], (
        f"the timeline gives {got['labels']}px to labels and {got['chart']}px to the "
        f"chart on a {got['viewport']}px phone, so the picture is the smaller half"
    )


def test_the_graphs_legend_is_on_the_page_a_phone_can_see(on_a_phone: dict[str, dict]):
    """`.keys` is pinned by its right edge and sized by its content, and its
    content is a grid of `auto repeat(6, max-content)` — about 620px whatever is
    underneath it. At 390px the box ran from -262 to 358: two thirds of the
    legend hung off the LEFT edge of the page, clipped and unreachable, so the
    reader saw four keys out of eleven.

    Nothing overflowed to the right and the document did not scroll, which is why
    it survived and why the test above cannot see it — a box off the left edge
    adds nothing to `scrollWidth`. It is asked key by key instead.

    The keys are what is asked about rather than the box: a legend is a list of
    names, and one that is drawn where a reader cannot see it says nothing at all
    while looking exactly like a legend from the corner of the eye.
    """
    got = on_a_phone["graph"]
    assert not got["keysOffPage"], (
        f"{len(got['keysOffPage'])} of the graph's legend keys are off the page on a "
        f"{got['viewport']}px phone, at: {got['keysOffPage']}"
    )
