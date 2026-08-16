"""The three static pages.

These assert structure and payload, not pixels. A page is correct here if it is
self-contained, carries the data its JavaScript needs, and encodes the things a
reader must be able to tell apart at a glance: which dates are derived, which are
guesses, and which work is late.
"""

import json
import re
from pathlib import Path

import pytest

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import render_static

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


def test_render_static_writes_all_three_pages(rendered: Path):
    for name in PAGES:
        assert (rendered / name).is_file(), name
        assert read(rendered, name).lstrip().startswith("<!doctype html>")


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
    assert payload["facets"]["owner"] == seed_index.facets["owner"]
    assert payload["predicates"] == list(seed_index.facets["predicate"])


def test_the_table_shows_a_persistent_blocker_count(rendered: Path, seed_index: Index):
    blockers = sum(1 for p in seed_index.problems if p.severity == "blocker")
    assert blockers > 0
    assert f'id="blocker-count">{blockers}<' in read(rendered, "index.html")


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


def test_the_timeline_hatches_what_it_is_guessing(rendered: Path, tmp_path: Path):
    """An estimated or unowned span is a forecast, not a commitment. If the two
    look alike, a guess gets read as a promise.

    Built from a constructed index rather than the seed: every seed entity now
    states a size, so the corpus no longer exercises the defaulted path at all.
    """
    from datetime import date

    from openproj.model import Config, Task

    assert 'id="hatch-estimated"' in read(rendered, "timeline.html")
    assert 'id="hatch-unowned"' in read(rendered, "timeline.html")

    guessed = Task(id="task-000001", kind="task", title="No size given", owner="ann")
    nobodys = Task(id="task-000002", kind="task", title="Nobody owns this", effort_weeks=1.0)
    index = build_index([guessed, nobodys], Config(), date(2026, 8, 17))
    out = tmp_path / "guesses"
    render_static(index, out)
    body = read(out, "timeline.html")

    assert 'data-id="task-000001" class="bar estimated' in body
    assert 'data-id="task-000002" class="bar unowned' in body


def test_the_timeline_draws_cycle_boundaries_and_today(rendered: Path):
    body = read(rendered, "timeline.html")
    assert 'class="today"' in body
    assert 'class="cycle-rule"' in body
    assert "cycle 36" in body


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
    """
    body = read(rendered, "people.html")
    logins = re.findall(r'<section class="person" data-login="([^"]+)"', body)

    assert logins == sorted(logins, key=str.lower)
    # Case-folded, and the corpus has to hold both cases or a plain `sorted()`
    # would pass this while putting every capitalised login ahead of the rest.
    assert logins != sorted(logins), "the corpus no longer mixes case; this proves nothing"
    assert '<input id="q"' in body
    for attribute in ("role", "kind", "status"):
        assert f'select data-attr="{attribute}"' in body, attribute
    assert re.search(r'<tr data-role="[^"]+" data-kind="[^"]+" data-status="[^"]+"', body)


def test_every_filter_offers_a_way_back_to_everything(rendered: Path):
    """`<option value="">` used to repeat the field name, so a chosen filter had no
    "off" — the way back looked like the label, not like a choice. The field name
    moved to a label beside the control and the empty option says `all`."""
    for page in ("index.html", "people.html"):
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
    from openproj.render import STATUSES

    body = read(rendered, "detail.html")
    headings = re.findall(r'<h2 class="tocgroup">\s*(\w+)', body)
    present = [s for s in STATUSES if any(e.status == s for e in seed_index.entities.values())]

    assert headings == present
    assert set(headings) == {e.status for e in seed_index.entities.values()}


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


def test_the_page_names_its_fonts_once(rendered: Path):
    """Two font stacks written out by hand drift the first time one is changed."""
    body = read(rendered, "index.html")
    style = re.search(r"<style>(.*?)</style>", body, re.S).group(1)

    assert "font-family: var(--font-sans)" in style
    declarations = re.findall(r"font-family:\s*([^;]+);", style)
    for value in declarations:
        assert "var(--font-" in value or "Inter var" in value, value


# --- tokens shared by every page --------------------------------------------


def test_a_status_carries_a_chip_palette_as_well_as_a_fill(rendered: Path):
    """Fill and ink draw shapes — a graph node, a timeline bar. Soft and text draw
    a chip, which has to sit inside a row of running text without shouting."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "index.html"), re.S).group(1)
    light = re.search(r":root \{(.*?)\}", style, re.S).group(1)

    for status in ("shaping", "ready", "in_progress", "done", "shelved"):
        for suffix in ("", "-ink", "-soft", "-text"):
            assert f"--st-{status}{suffix}:" in light, f"--st-{status}{suffix}"
        assert f".chip.st-{status} {{" in style


def test_the_dark_theme_flips_the_ink_with_the_fill(rendered: Path):
    """Dark fills are light shapes: white label text on them is exactly the
    failure the light theme's white text avoids. The graph reads --on-status for
    its node labels and the timeline reads --hatch, so both have to flip too."""
    style = re.search(r"<style>(.*?)</style>", read(rendered, "index.html"), re.S).group(1)
    dark = re.search(r':root\[data-theme="dark"\] \{(.*?)\}', style, re.S).group(1)

    assert "--on-status: #ffffff" not in dark
    assert "--hatch: #ffffff" not in dark
    assert re.search(r"--st-done-ink: (#0f1416)", dark)


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
    assert '<th data-sort="size">appetite</th>' in read(rendered, "index.html")


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
    for section in re.findall(r'<section class="person".*?</section>', body, re.S):
        roles = re.findall(r'<tr data-role="(\w+)"', section)
        assert roles == sorted(roles, key=_ROLE_ORDER.index), section[:60]
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


# --- cycles -----------------------------------------------------------------


def test_a_new_cycle_still_has_a_roster_to_set_availability_against(seed_index: Index):
    """Built only from who is bet or already listed, a cycle nobody has bet into
    yet shows an empty table — and setting the roster up is the first thing you
    do on it. The team list seeds it."""
    from openproj.render import _cycle_view

    view = _cycle_view(seed_index.model_copy(update={"plans": {}}), 99)
    logins = [row["login"] for row in view["people"]]

    assert set(seed_index.known_people) <= set(logins)
    assert logins == sorted(logins, key=str.lower)
    assert all(row["held"] == 0.0 for row in view["people"])


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
