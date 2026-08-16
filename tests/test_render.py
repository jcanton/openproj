"""The three static pages.

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

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import STATUS_GLYPH, STATUSES, render_static

PAGES = ("index.html", "detail.html", "people.html", "cycles.html",
         "graph.html", "timeline.html")


@pytest.fixture
def seed_index(seed_root: Path) -> Index:
    from datetime import date

    entities, config = load_repo(seed_root)
    return build_index(entities, config, date(2026, 8, 17))


@pytest.fixture
def rendered(seed_index: Index, tmp_path: Path) -> Path:
    render_static(seed_index, tmp_path)
    return tmp_path


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


def test_no_page_reaches_the_network(rendered: Path):
    """No npm, no build step, no CDN. A page that fetches from the internet is a
    page that breaks on a train, and this is the only test that would notice."""
    for name in PAGES:
        body = read(rendered, name)
        # Anchors to github.com are fine and wanted — a PR link that resolves is
        # the point. What must never appear is a page FETCHING from the network.
        assert not re.search(r'<script[^>]+src\s*=', body), name
        assert not re.search(r'<link[^>]+href\s*=\s*["\']https?://', body), name
        assert not re.search(r'<img[^>]+src\s*=\s*["\']https?://', body), name
        assert "cdn." not in body, name


def test_the_libraries_are_inlined_rather_than_linked(rendered: Path):
    graph = read(rendered, "graph.html")
    assert "cytoscape" in graph
    assert 'src="' not in graph


def test_every_library_is_inlined_exactly_once_and_no_marker_survives(rendered: Path):
    """The graph page once rendered blank because `DAGRE_JS` is a substring of
    `CYTOSCAPE_DAGRE_JS`: replacing markers in sequence inlined dagre twice and
    cytoscape-dagre never. Nothing in the page said so — it just drew nothing."""
    static = Path(__file__).resolve().parents[1] / "static"
    graph = read(rendered, "graph.html")

    # Not a bare "@@" check: minified cytoscape genuinely contains `e["@@iterator"]`.
    assert not re.search(r"@@[\w.-]+\.js@@", graph), "an inlining marker survived"
    for name in ("cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js"):
        signature = (static / name).read_text(encoding="utf-8")[:120]
        assert graph.count(signature) == 1, name


def test_the_table_carries_every_entity_and_its_derived_dates(rendered: Path, seed_index: Index):
    payload = json.loads(
        re.search(
            r'<script id="payload" type="application/json">(.*?)</script>',
            read(rendered, "index.html"),
            re.S,
        ).group(1)
    )
    assert set(payload["rows"]) == set(seed_index.entities)
    scheduled = payload["rows"]["task-53a9f0"]
    assert scheduled["start"] == "2026-08-17"
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
    assert f'id="blocker-count">{blockers}<' in read(rendered, "index.html")


def test_a_rendered_file_dresses_its_cells_the_way_the_server_does(rendered: Path):
    """A rendered file has no server, so `EDITABLE` is null and every branch that
    hangs off it is dead. The tag clamp was written into the editable branch
    only, so an export kept the "+2" reveal and showed all five tags beside it —
    caught in a browser, not here, which is why it is here now.

    The chips, the severity marks and the empty states are all drawn from data
    the export carries, so all of them have to survive the loss of the editor.
    """
    index = read(rendered, "index.html")

    assert "base_commit" not in index, "this is the read-only build"
    assert "key === 'tags' || key === 'prs' ? 'clamp' : ''" in index, (
        "the clamp is not behind the editor"
    )
    assert "td.clamp .rest { display: none; }" in index
    for rule in (".chip.st-done", ".chip.kind-pitch", ".sev-row-blocker", ".sev-mark-blocker"):
        assert rule in index, rule
    assert "'The plan could not be loaded.'" in index
    assert '<label class="facet">Flags' in index
    assert '<option value="has_blocker">Has a blocking problem</option>' in index


def test_filter_state_lives_in_query_parameters(rendered: Path):
    """Every view is a shareable URL, and the back button has to work. This is
    also what deletes the entire saved-views feature request."""
    body = read(rendered, "index.html")
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
    assert "dagre" in body and '"rankDir": "LR"' in body.replace("'", '"')


def test_a_node_carries_everything_the_filters_ask_of_it(seed_index: Index):
    """The graph filters on the table's row, not on a graph-shaped subset of it.

    A node holding only what cytoscape draws is how a dropdown comes to filter one
    view and quietly do nothing in the next.
    """
    from openproj.render import _elements, _row

    nodes = {
        e["data"]["id"]: e["data"] for e in _elements(seed_index) if "source" not in e["data"]
    }

    for entity_id in seed_index.entities:
        for field, value in _row(seed_index, entity_id).items():
            assert nodes[entity_id][field] == value, f"{entity_id}.{field}"
        # And the two keys the row does not carry, because only a canvas needs them.
        assert nodes[entity_id]["label"] == seed_index.entities[entity_id].title
        assert nodes[entity_id]["depends_on"] == seed_index.blocked_by[entity_id]


def test_the_graph_filters_the_plan_the_way_the_table_does(rendered: Path):
    """One control bar over one `matches()`. While the filter model lived inside
    the table's script, "three views share one filter" was true of one view, and a
    second copy of the predicate is how a facet acquires a second meaning."""
    table = read(rendered, "index.html")
    graph = read(rendered, "graph.html")
    model = re.search(r"function matches\(row\) \{.*?\n\}", table, re.S).group(0)

    assert model in graph, "the graph must ask the same question, not a similar one"
    assert re.findall(r'<select data-field="([^"]+)"', graph) == re.findall(
        r'<select data-field="([^"]+)"', table
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
    assert "No entity matches these filters." in body
    assert "This plan has no entities yet." in body
    assert "The plan could not be loaded." in body
    # Only the filtered one offers a way out: there is nothing to clear when the
    # plan is empty or the payload never arrived, and a Clear that clears nothing
    # is how a control teaches people it is decoration.
    assert body.count("clearable = false") == 2
    assert "CLEAR.hidden = !clearable;" in body

    assert re.search(r"try \{\s*\n\s*ELEMENTS = JSON\.parse", graph), "the payload may be truncated"
    assert "const LOADED = ELEMENTS !== null;" in graph
    assert "elements: ELEMENTS || []," in graph


def test_the_graph_commits_below_the_canvas_like_every_other_page(
    rendered: Path, seed_index: Index
):
    """F15 moved Create, Edit and Save the setup below the forms they commit; the
    graph is the fourth page with a primary action and was missed, so Save for a
    dependency sat above the 78vh canvas the dependency is drawn on.

    Served rather than rendered: a static export has no server to write to, so it
    has no action bar at all — which is the other half of the claim.
    """
    from openproj.render import ROUTES, render_graph

    live = render_graph(seed_index, ROUTES, base_commit="deadbee")

    assert '<p class="editbar">' not in live, "the bar it replaced"
    assert live.index('id="commitbar"') > live.index('<div class="canvas">')
    assert live.index('id="connect"') > live.index('id="cy"')
    # The shell's bar, not a fourth one drawn by hand.
    assert re.search(r"\.commitbar \{[^}]*position: sticky; bottom: 0", live, re.S)
    assert 'id="commitbar"' not in read(rendered, "graph.html")


def test_the_graph_names_every_colour_it_draws_with(rendered: Path):
    """Status is the only thing on this canvas that is not a word. The swatch is
    the token the node is actually filled with and the glyph the node is actually
    marked with — a legend naming a colour that is not on screen is worse than
    none, because it gets believed, and a legend keying only the colour keys the
    half of the encoding a dichromat cannot use."""
    from openproj.render import STATUS_GLYPH, STATUSES

    graph = read(rendered, "graph.html")
    legend = re.search(r'<ul class="legend".*?</ul>', graph, re.S).group(0)

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
    from openproj.render import STATUSES

    graph = read(rendered, "graph.html")
    repaint = re.search(r"function paint\(\) \{.*?\n\}", graph, re.S).group(0)

    for status in STATUSES:
        assert f"token('--st-{status}-ink')" in graph, status
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
    for status in STATUSES:
        assert f"token('--st-{status}-line')" in graph, status
    assert "'border-color': e => LINE()[e.data('status')]" in graph
    assert "'border-color': e => LINE()[e.data('status')]" in repaint


def test_the_timeline_hatches_what_it_is_guessing(rendered: Path, tmp_path: Path):
    """An estimated or unowned span is a forecast, not a commitment. If the two
    look alike, a guess gets read as a promise.

    Built from a constructed index rather than the seed: every seed entity now
    states a size, so the corpus no longer exercises the defaulted path at all.
    """
    from datetime import date

    from openproj.model import Config, Task

    assert 'id="hatch-estimated-st-ready"' in read(rendered, "timeline.html")
    assert 'id="hatch-unowned-st-ready"' in read(rendered, "timeline.html")

    guessed = Task(id="task-000001", kind="task", title="No size given", owner="ann")
    nobodys = Task(id="task-000002", kind="task", title="Nobody owns this", effort_weeks=1.0)
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
    assert plot.count('class="mark mark-estimated st-shaping"') == 1
    assert plot.count('class="mark mark-unowned st-shaping"') == 1
    assert "rect.mark-estimated.st-shaping { fill: url(#hatch-estimated-st-shaping); }" in body
    assert "rect.mark-unowned.st-shaping { fill: url(#hatch-unowned-st-shaping); }" in body
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
                  appetite_weeks=3.0, parent="proj-000001")
    task = Task(id="task-000001", kind="task", title="A task", owner="bo",
                effort_weeks=1.0, parent="pitch-000001")
    other = Task(id="task-000002", kind="task", title="An unparented task", owner="cy",
                 effort_weeks=1.0)
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
                   owner="ann", appetite_weeks=2.0)
    child = Task(id="task-000001", kind="task", title="Still live", owner="bo",
                 effort_weeks=1.0, parent="pitch-000001")
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
                 effort_weeks=0.2)
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
                effort_weeks=8)
    brief = Task(id="task-000002", kind="task", title="A day of it", owner="bob",
                 effort_weeks=0.2)
    index = build_index([slog, brief], Config(), date(2026, 8, 17))
    body = render_timeline(index, zoom=zoom)

    drawn = dict(re.findall(r'<rect data-id="([^"]+)"[^>]*width="([\d.]+)"', body))
    assert set(drawn) == set(index.spans)

    for entity_id, span in index.spans.items():
        days = (span.end - span.start).days + 1        # inclusive of both ends
        assert float(drawn[entity_id]) == max(_MIN_BAR_PX, zoom, days * zoom), entity_id

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
    unqualified = [
        selector.strip()
        for rule in re.findall(r"([^{}]*)\{", style)
        for selector in rule.split(",")
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
    assert 'id="tip"' in body


def test_the_timeline_names_every_colour_it_draws(rendered: Path):
    """A colour with no key is a colour the reader has to guess at, and the pink
    outline meant something nothing on the page named."""
    from openproj.render import STATUS_GLYPH

    body = read(rendered, "timeline.html")
    legend = re.search(r'<ul class="legend" aria-label="What a bar marking means">(.*?)</ul>',
                       body, re.S).group(1)

    for status in ("shaping", "ready", "in_progress", "done", "shelved"):
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
    for entity_id, explanation in seed_index.explanations.items():
        assert explanation.text in body, entity_id


def test_a_span_less_entity_is_listed_but_not_drawn(rendered: Path, seed_index: Index):
    """Done and shelved work has no span. It still belongs in the table — dropping
    it would make the board lie about what exists."""
    payload = json.loads(
        re.search(
            r'<script id="payload" type="application/json">(.*?)</script>',
            read(rendered, "index.html"),
            re.S,
        ).group(1)
    )
    assert payload["rows"]["task-3d84e9"]["start"] is None
    assert 'data-id="task-3d84e9" class="bar' not in read(rendered, "timeline.html")


# --- the detail page -------------------------------------------------------


def test_a_detail_page_exists_for_every_entity(rendered: Path, seed_index: Index):
    """The whole premise is that the shaping doc IS the record. A viewer that
    never shows the body is a viewer of the frontmatter only."""
    body = read(rendered, "detail.html")
    for entity_id in seed_index.entities:
        assert f'id="{entity_id}"' in body, entity_id


def test_the_detail_page_opens_as_an_index_not_a_wall_of_text(rendered: Path, seed_index: Index):
    """With no hash the page lists what exists; with a hash it shows exactly one
    document. Showing all seventeen bodies at once is not a detail view."""
    body = read(rendered, "detail.html")
    assert 'class="toc"' in body
    for entity_id in seed_index.entities:
        # `detail.html#id` in a rendered file, `/detail/id` on the server: the link
        # comes from Links either way, so the index cannot drift from the routes.
        assert f'href="detail.html#{entity_id}"' in body, entity_id
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
    entity_id, explanation = next(iter(seed_index.explanations.items()))
    assert explanation.text in body
    assert seed_index.spans[entity_id].start.isoformat() in body


@pytest.fixture
def demo_rendered(demo_root: Path, tmp_path: Path) -> tuple[Path, Index]:
    """The shipped demo, which unlike the frozen golden corpus carries real PR
    references and the dependency diamond these tests are about."""
    from datetime import date

    entities, config = load_repo(demo_root)
    index = build_index(entities, config, date(2026, 8, 17))
    out = tmp_path / "demo"
    render_static(index, out)
    return out, index


def test_pr_references_become_links_that_resolve(demo_rendered: tuple[Path, Index]):
    """A dead PR reference teaches people the field is decorative."""
    out, index = demo_rendered
    refs = {ref for e in index.entities.values() for ref in e.prs}
    assert refs, "the demo corpus should carry PR references"
    detail = read(out, "detail.html")
    for ref in refs:
        repo, number = ref.split("#")
        assert f'href="https://github.com/{repo}/pull/{number}"' in detail, ref


def test_every_view_links_to_the_detail_page(rendered: Path):
    assert 'detail.html#' in read(rendered, "index.html")
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
    field, and the picker then offered `jcanton, halungge` as though it were one
    person — so garbage already in the corpus became garbage suggested to whoever
    edited next. The write path is fixed; this stops the spread either way.
    """
    from openproj.model import Task
    from openproj.render import _suggestions

    polluted = dict(seed_index.entities)
    polluted["task-ffffff"] = Task(
        id="task-ffffff", kind="task", title="Bad", reviewers=["jcanton, halungge"]
    )
    suggestions = _suggestions(seed_index.model_copy(update={"entities": polluted}))

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
    assert dated["label"] == f"{starts} → {ends}"


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
        for entity in seed_index.entities.values()
        for field in ("owner", "shaped_by", "assignees", "reviewers")
        for login in (
            lambda v: v if isinstance(v, list) else [v] if v else []
        )(getattr(entity, field, None))
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


def test_every_person_row_links_to_the_entity(rendered: Path, seed_index: Index):
    body = read(rendered, "people.html")
    owned = [i for i, e in seed_index.entities.items() if e.owner]

    assert owned
    for entity_id in owned:
        assert f'href="detail.html#{entity_id}"' in body, entity_id


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
        assert f'select data-field="{attribute}"' in body, attribute
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


def test_a_cycle_with_no_record_is_weeks_bet_against_no_roster(rendered: Path):
    """The golden corpus dates its cycles in config and writes a record for none of
    them, so there is availability for nobody. "0.0 of 0.0 weeks" would be a
    meter reading zero; what is true is that there is nothing to bet against."""
    body = read(rendered, "people.html")

    assert "has no record, so there is no availability to bet it against" in body
    assert "weeks bet against no roster" in body
    assert 'class="bar"' not in body, "no meter without something to measure against"


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
        if opens is None:
            # Only a shaper: `shaped_by` is not one of the table's facets, so the
            # name stays a name rather than becoming a link to a filter that does
            # not exist.
            assert f'<span class="who">{login}</span>' in group, login
            continue
        assert f'<a class="who" href="index.html?{_ROLE_FILTER[opens][0]}={login}"' in group, login
        # And each count is the way into the rows it counted.
        for role in roles & set(_ROLE_FILTER):
            assert f'href="index.html?{_ROLE_FILTER[role][0]}={login}">' in group, (login, role)
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
    moved to a label beside the control and the empty option says `all`."""
    for page in ("index.html", "people.html", "graph.html"):
        body = read(rendered, page)
        for tag in re.findall(r"<select[^>]*>(.*?)</select>", body, re.S):
            assert re.match(r'\s*<option value="">all</option>', tag), tag[:80]


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
    controls disagreed with the picture. What is lost by filling them in — "am I
    looking at everything?" — is answered by the sentence instead."""
    from datetime import date

    from openproj.render import render_timeline

    whole = render_timeline(seed_index)
    origin = re.search(r'name="from" value="([\d-]+)"', whole).group(1)
    last = re.search(r'name="to" value="([\d-]+)"', whole).group(1)

    assert f"Showing the whole plan, {origin} to {last}." in " ".join(whole.split())

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

    assert '<select data-field="status">' in body
    assert '<select data-field="predicate">' in body
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
    assert "This plan has no entities yet." in body
    assert '<button type="button" id="clear-filters" hidden>' in body

    parked = Task(id="task-000001", kind="task", title="Parked", status="shelved")
    render_static(build_index([parked], Config(), date(2026, 8, 17)), tmp_path / "parked")
    parked_body = read(tmp_path / "parked", "timeline.html")
    assert "Nothing in this plan has dates." in parked_body
    assert '<div class="tl" hidden>' in parked_body

    live = Task(id="task-000002", kind="task", title="Live", owner="ann", effort_weeks=1.0)
    index = build_index([live], Config(), date(2026, 8, 17))
    render_static(index, tmp_path / "live")
    live_body = read(tmp_path / "live", "timeline.html")
    assert "No entity matches these filters." in live_body
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
    """Each write moves HEAD. Reusing the page's base for the second entity would
    make it a conflict against a commit the same button had just created."""
    body = read(rendered, "graph.html")
    save = re.search(r"SAVE\.onclick.*?\n  \};", body, re.S).group(0)

    assert "base.value = answer.commit" in save
    assert "already saved" in save, "a partial failure must say what was written"


def test_edges_are_routed_rather_than_drawn_over_whatever_is_between(rendered: Path):
    body = read(rendered, "graph.html")

    assert "'curve-style': 'round-taxi'" in body
    assert "'taxi-radius'" in body
    assert "'curve-style': 'bezier'" not in body


def test_the_index_is_grouped_in_the_order_work_moves(rendered: Path, seed_index: Index):
    """shaping first, done last. Alphabetical put `done` at the top, which is the
    one group nobody opens the index looking for."""
    from openproj.render import STATUSES, _human

    body = read(rendered, "detail.html")
    headings = re.findall(r'<h2 class="tocgroup">\s*([^<]+?)\s*<span', body)
    present = [s for s in STATUSES if any(e.status == s for e in seed_index.entities.values())]

    assert headings == [_human(s) for s in present]
    assert set(headings) == {_human(e.status) for e in seed_index.entities.values()}
    # The heading was the last place a status was still spelled the way the file spells it,
    # two lines above a kind that already read as a word.
    assert not [h for h in headings if "_" in h]


def test_a_status_nobody_uses_gets_no_heading(seed_index: Index):
    from openproj.render import _by_status

    rows = [{"status": "ready"}, {"status": "done"}, {"status": "ready"}]

    assert [g["status"] for g in _by_status(rows)] == ["ready", "done"]


def test_an_unknown_status_still_reaches_the_index(seed_index: Index):
    """An entity missing from the index because its status is misspelt is
    invisible — and the index is how you find the thing to fix."""
    from openproj.render import _by_status

    groups = _by_status([{"status": "done"}, {"status": "wip"}])

    assert [g["status"] for g in groups] == ["done", "wip"]


def test_a_pr_reference_completes_in_two_halves(demo_rendered: tuple[Path, Index]):
    """`C2SM/icon4py#` and whole references, from what the plan already cites.

    Nobody remembers whether it is icon4py or icon4pygen, or which org owns it,
    and that half of the reference is the same on almost every row — so it is
    offered on its own, with the number left to type.
    """
    from openproj.render import _suggestions

    _, index = demo_rendered
    offered = _suggestions(index)["prs"]
    values = [item["value"] for item in offered]
    cited = {ref for e in index.entities.values() for ref in e.prs}

    assert "C2SM/icon4py#" in values
    assert cited <= set(values)
    assert values.index("C2SM/icon4py#") < min(values.index(c) for c in cited)


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
    body = read(rendered, "index.html")
    head = body[: body.index("</head>")]

    assert "localStorage.getItem('openproj:theme')" in head
    assert "documentElement.dataset.theme" in head


def test_every_page_carries_the_toggle(rendered: Path):
    for page in PAGES:
        assert '<button type="button" id="theme">' in read(rendered, page), page


def test_no_colour_is_defined_only_in_the_dark_block(rendered: Path):
    """The default is no stamp at all, where only the media query separates one
    theme from the other. A token whose only definition sits behind
    `[data-theme]` never applies in that state, and the page renders one theme's
    text on the other theme's ground."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "index.html"), re.S).group(1)
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
        body = read(rendered, page)
        for url in re.findall(r"url\(\s*[\"']?([^\"')]+)", body):
            assert url.startswith("data:") or url.startswith("#"), (page, url[:60])
        assert "fonts.googleapis" not in body and "fonts.gstatic" not in body, page


def test_the_vendored_face_is_the_one_that_was_checksummed():
    """A vendored binary nobody verifies is a vendored binary nobody can audit.
    The other three files in static/ have been listed since they were added."""
    import hashlib

    from openproj.render import _static_dir

    static = _static_dir()
    sums = dict(
        reversed(line.split(maxsplit=1))
        for line in (static / "SHA256SUMS").read_text().splitlines()
        if line.strip()
    )
    name = "inter-latin-wght-normal.woff2"
    assert name in sums, "the face must be listed in SHA256SUMS"
    digest = hashlib.sha256((static / name).read_bytes()).hexdigest()
    assert digest == sums[name].strip()


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
    assert "*.js *.woff2 > SHA256SUMS" in doc
    assert "SIL Open Font License" in doc and "inter-LICENSE.txt" in doc


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
    body = read(rendered, "index.html")
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
        assert style.count("#summary {") == 1, name
        assert style.count("#state {") == 1, name
        assert "#shown {" not in style, name

    for name in ("index.html", "graph.html", "timeline.html", "people.html"):
        assert '<span id="shown" class="num">' in read(rendered, name), name


def test_the_people_page_draws_the_control_bar_the_plan_draws(rendered: Path):
    """Two facet bars, the same markup, one of them written out by hand over its
    own three fields — and already drifted, because only one of the two search
    boxes had been given a name when the other was. `_FACETS` takes the field list
    as a parameter now, so there is one bar and the people page passes its own
    fields through it.

    `role` is only ever offered here: which hat somebody is wearing is not a field
    of an entity, it is which field their name is in.
    """
    people, index = read(rendered, "people.html"), read(rendered, "index.html")
    shape = (r'<div id="controls"><input id="q" type="search" aria-label="([^"]+)"'
             r' placeholder="\1">\s*<div class="facets">')

    for name, page in (("people", people), ("index", index)):
        assert re.search(shape, page), name

    assert re.findall(r'<select data-field="([^"]+)"', people) == ["role", "kind", "status"]
    assert 'aria-label="Search person, entity, id"' in people
    assert 'aria-label="Search title, tags, body"' in index


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

    for key in _detail_rows(seed_index)[0]:
        assert re.search(rf"\be\.{key}\b", _DETAIL), f"{key} is built and read by nobody"


def test_the_labels_and_the_bars_are_laid_out_on_one_row_height(
    seed_index: Index, monkeypatch: pytest.MonkeyPatch
):
    """The label column's rows have to be exactly as tall as the rows the plot is
    drawn with, or the names walk out of step with the bars they name, one pixel
    per row — a drift nothing catches until somebody reads a long plan and finds a
    title against the wrong bar. It was `height: 22px` written into the stylesheet,
    a third copy of `_ROW_PX`, so this moves the constant and asks both."""
    from openproj import render

    monkeypatch.setattr(render, "_ROW_PX", 30)
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
    from openproj import render

    source = Path(render.__file__).read_text(encoding="utf-8")
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
    style = re.search(r"<style>(.*?)</style>", read(rendered, "index.html"), re.S).group(1)
    light = re.search(r":root \{(.*?)\}", style, re.S).group(1)

    for status in ("shaping", "ready", "in_progress", "done", "shelved"):
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
    style = re.search(r"<style>(.*?)</style>", read(rendered, "index.html"), re.S).group(1)
    themes = tokens(read(rendered, "index.html"))

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
        "shaping": ("#d2c5ee", "#101416", "#7e61c2"),
        "ready": ("#83b8e9", "#101416", "#275e92"),
        "in_progress": ("#e18606", "#101416", "#603a04"),
        "done": ("#2b925e", "#101416", "#0d311f"),
        "shelved": ("#e1e5e9", "#101416", "#88959d"),
    },
    "dark": {
        "shaping": ("#9077cb", "#101416", "#56477a"),
        "ready": ("#7aacdc", "#101416", "#44607a"),
        "in_progress": ("#f9c275", "#101416", "#82663d"),
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
    themes = tokens(read(rendered, "index.html"))

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
    themes = tokens(read(rendered, "index.html"))
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


def test_the_five_fills_are_separated_by_lightness_and_not_only_by_hue(rendered: Path):
    """Hue is the channel a dichromat loses, and on the graph and the timeline the
    fill used to be the only channel there was: five hues at one lightness
    (1.02–1.11:1 between any two) collapsed into one colour. Lightness is what
    every kind of colour vision keeps, so consecutive rungs are held apart by it.

    1.27 and not the 1.3 this once asked for. Inverting the light theme narrowed
    the band the five rungs live in: the ink no longer flips, so no rung has to
    be dark enough to carry white text, and the whole ladder now spans 3.08:1
    instead of the old 14.2. The four gaps it shipped with are 1.280, 1.296,
    1.313 and 1.416 — the closest pair being `shelved` to `shaping` — and this
    floor sits just under the worst of them rather than at a round number that
    would have let two more rungs drift together before anything failed."""
    themes = tokens(read(rendered, "index.html"))

    for name in ("light", "dark"):
        rungs = sorted(_luminance(themes[name][f"--st-{s}"]) for s in STATUSES)
        for lower, upper in zip(rungs, rungs[1:], strict=False):
            gap = (upper + 0.05) / (lower + 0.05)
            assert gap >= 1.27, (name, gap)


def test_a_chip_pair_is_readable_in_both_themes(rendered: Path):
    """A chip carries its word, so it does not need the ladder — but the word is
    text on a tinted ground, and text owes 4.5:1 wherever it is."""
    themes = tokens(read(rendered, "index.html"))

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
    themes = tokens(read(rendered, "index.html"))

    for name in ("light", "dark"):
        page = themes[name]["--bg"]
        for ground in (page, themes[name]["--surface"], themes[name]["--surface-2"]):
            assert contrast(themes[name]["--line-strong"], ground) >= 3.0, (
                name, ground, contrast(themes[name]["--line-strong"], ground))
        assert contrast(themes[name]["--empty"], page) >= 4.5, name
    # One value, referenced rather than copied: the kind chip's hairline is the
    # same boundary an input has, and a copy is how one of them gets fixed.
    assert "--kind-line: var(--line-strong)" in read(rendered, "index.html")


def test_the_three_theme_blocks_agree_about_every_colour(rendered: Path):
    """A reader who has never touched the toggle matches only the media query. A
    token that is right under [data-theme="dark"] and stale in the media block is
    stale for most of the people who will ever see the page."""
    themes = tokens(read(rendered, "index.html"))

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
    Inverting the light theme made it a tint — #83b8e9 is 2.10:1 on a white page
    — and a dependency graph whose dependencies you cannot see is a box of
    boxes. An arrow is a drawn boundary, not a status, so it takes the token
    that is held at 3:1 against the page in both themes."""
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
    assert "outline: none" not in read(rendered, "index.html")


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
    the table were one number under three names. The stored fields keep theirs."""
    from openproj.render import LABELS

    assert LABELS["appetite_weeks"] == LABELS["effort_weeks"] == "Appetite (weeks)"
    assert "Effort" not in read(rendered, "detail.html")
    index = read(rendered, "index.html")
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
    """Built one entity at a time, a person with twenty rows had their four
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


def test_the_graph_explains_the_mode_only_inside_it(rendered: Path):
    """Instructions for a mode you are not in are noise on every other visit."""
    graph = read(rendered, "graph.html")
    editable = re.search(r'<p class="hint" id="howto"[^>]*>', graph)

    assert "Double-click a node to open it" in graph
    assert editable is None, "the static build has no edit mode to explain"


def test_the_parent_reads_as_a_title_and_edits_as_an_id(demo_rendered: tuple[Path, Index]):
    """`blocked_by` already lists what it points at by title. `parent` showed a
    bare id in two places — the facts list and the line under the heading — and an
    id is what the field stores, not what somebody asking "what is this part of"
    is looking for. The control underneath still holds the id: that is what gets
    written, and the autocomplete offers ids with titles beside them."""
    out, index = demo_rendered
    body = read(out, "detail.html")
    child = next(e for e in index.entities.values() if e.parent in index.entities)
    parent = index.entities[child.parent]

    assert f">{parent.title}</a>" in body
    assert "· in <a" in body
    # The entity's OWN id stays in its meta line — that one is wanted. It is the
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
        e for e in seed_index.entities.values() if e.body.lstrip().startswith(f"# {e.title}")
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
        for e in seed_index.entities.values()
        if e.body.lstrip().startswith("# ") and not e.body.lstrip().startswith(f"# {e.title}")
    )
    article = re.search(rf'<article id="{differs.id}".*?</article>', body, re.S).group(0)
    first = differs.body.lstrip().splitlines()[0].lstrip("# ").strip()

    assert f"<h1>{first}</h1>" in article


def test_the_leading_heading_is_matched_on_words_and_not_on_bytes():
    """A heading wrapped across two lines, or double-spaced, or in different case
    is the same heading — and a doc whose first section merely starts with the
    same word is not."""
    from openproj.render import _drop_repeated_title

    assert _drop_repeated_title("# Port  ecRad\n\nBody.\n", "Port ecRad") == "Body.\n"
    assert _drop_repeated_title("## port ecrad ##\n\nBody.\n", "Port ecRad") == "Body.\n"
    assert _drop_repeated_title("# Port ecRad shortwave\n\nB.\n", "Port ecRad").startswith("#")
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


def test_the_detail_column_is_centred_and_the_facts_sit_beside_the_document(rendered: Path):
    """It was an 832px article flush left with a full-height rule down its right
    edge, which on a wide screen is not a document — it is the left half of a
    two-pane layout whose right half failed to load.

    A container query and not a media query: the width that decides whether the
    facts fit beside the prose is the column's, and the reader sets that with the
    grip. A window breakpoint would put a sidebar on a column dragged to 400px."""
    body = read(rendered, "detail.html")

    assert re.search(r"article\.entity \{[^}]*margin: 0 auto", body, re.S)
    assert "container-type: inline-size" in body
    assert "@container (min-width: 56rem)" in body
    assert re.search(r"\.panes > \.facts \{[^}]*grid-column: 2", body, re.S)
    assert re.search(r"\.panes > \.main \{[^}]*grid-column: 1", body, re.S)
    # The grip is a handle now, not a border: a full-height rule in --line is
    # exactly how a page draws the edge of a pane.
    assert re.search(r"#grip::before \{[^}]*height: 48px", body, re.S)
    # And it belongs to a document. On the index every article is hidden, so it
    # measured zero and parked itself down the left edge of the list.
    assert "grip.hidden = !article" in body
    assert "candidate.offsetParent !== null" in body


def test_every_page_echoes_the_iso_value_of_a_date_box(rendered: Path):
    """Every date the plan prints is ISO and every `<input type=date>` is drawn in
    the reader's locale, so one desk edits 2026-09-01 as 01/09/2026 and the next
    as 09/01/2026. The box keeps its locale; the stored value is echoed beside
    it."""
    for name in PAGES:
        body = read(rendered, name)
        assert "document.querySelectorAll('input[type=date]')" in body, name
        assert ".iso { display: block;" in body, name


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
    """F25. A cycle with dates in config/cycles.yaml, or one that entities point
    at with nothing behind it, is the cycle worth finding — and it was the one
    the index left out, because it iterated the records."""
    out, index = demo_rendered
    body = read(out, "cycles.html")
    # Named, not linked: a rendered plan is six files and none of them is a
    # cycle, so the card says which cycle it is and stops there. The server's
    # copy of this page does link — `test_a_rendered_plan_offers_no_dead_control`
    # is what pins the difference.
    cards = [int(n) for n in re.findall(r"<h2>Cycle (\d+)</h2>", body)]
    named = set(index.plans) | set(index.cycles) | {
        e.cycle for e in index.entities.values() if e.cycle is not None
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
        e for e in index.entities.values() if e.cycle == 37 and index.children.get(e.id)
    ]

    assert rolled_up, "the corpus has a parent bet into cycle 37"
    for parent in rolled_up:
        only_parent = index.model_copy(
            update={"entities": {parent.id: parent}, "children": {}}
        )
        assert only_parent.load(37), "the same parent IS charged when it has no children"
    assert held, "and the leaves are charged in the real index"


def test_a_size_is_split_evenly_between_the_people_on_it(demo_rendered: tuple[Path, Index]):
    """Even split, decided 2026-08-16: one number to maintain instead of one per
    person per task."""
    from openproj.model import Config, size_weeks

    _, index = demo_rendered
    shared = next(
        e for e in index.entities.values()
        if e.cycle == 37 and len(e.assignees) > 1 and not index.children.get(e.id)
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
    "index.html": "Table",
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
    """
    for page in PAGES:
        body = read(rendered, page)
        assert body.count('<main id="main">') == 1, page
        assert body.count("</main>") == 1, page

    for page, name in PAGE_NAMES.items():
        body = read(rendered, page)
        assert f"<h1>{name}</h1>" in body, page
        # These five draw no stored markdown, so every heading on them is the
        # page's own. The detail and cycle pages render shaping documents, and a
        # `# Heading` somebody wrote is not the page failing to have one.
        assert body.count("<h1") == 1, page


def test_the_detail_page_names_each_document_it_holds(rendered: Path, seed_index: Index):
    """It is a hash router over every entity: with no hash it is an index, with
    one it is exactly that document. Each of those views needs a name of its own,
    and only ever one of them is displayed."""
    body = read(rendered, "detail.html")

    assert "<h1>Every entity in this plan</h1>" in body
    for entity in seed_index.entities.values():
        article = re.search(rf'<article id="{entity.id}".*?</article>', body, re.S).group(0)
        named = escape(entity.title)
        assert f'<h1><span class="read">{named}</span></h1>' in article, entity.id
    # And the router shows one or the other, never both.
    assert "article.style.display = match ? '' : 'none';" in body
    assert "document.querySelector('.toc').style.display = found ? 'none' : '';" in body


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
    assert '<span id="state" role="status"></span>' in read(rendered, "index.html")


def test_a_rendered_plan_offers_no_dead_control(rendered: Path, seed_index: Index):
    """A read-only export must not draw a control that cannot work.

    `links.new` is the empty string on a rendered file, so "New entity" was a
    button back to the page you were already on; the hint beside it promised an
    editor with no server to save to; and every cycle card linked to a per-cycle
    page that `render_static` does not write.
    """
    table = read(rendered, "index.html")
    cycles = read(rendered, "cycles.html")

    assert "New entity" not in table
    assert "double-click a cell" not in table
    assert '<a class="button" href="">' not in table
    for number in sorted(set(seed_index.plans) | set(seed_index.cycles)):
        assert f"<h2>Cycle {number}</h2>" in cycles, number
    # No anchor anywhere in the export points at a file that was not written.
    written = {path.name for path in rendered.iterdir()}
    for page in PAGES:
        for href in re.findall(r'href="([^"#?]+)[^"]*"', read(rendered, page)):
            if href.startswith(("http://", "https://", "assets/")):
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
        entity_id = re.search(r'data-id="([^"]+)"', row).group(1)
        says = re.search(r'<span class="sr-only">(.*?)</span>', row, re.S).group(1)
        assert entity_id in says, entity_id
        # A status word and a pair of dates, which the fill and the width are the
        # only channels for on the chart itself.
        assert re.search(r"\d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d\.", says), says
        assert f'<a href="detail.html#{entity_id}"' in row
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
