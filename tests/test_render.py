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

PAGES = ("index.html", "graph.html", "timeline.html")


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
        assert not re.search(r'(src|href)\s*=\s*["\']https?://', body), name
        assert "cdn." not in body, name


def test_the_libraries_are_inlined_rather_than_linked(rendered: Path):
    graph = read(rendered, "graph.html")
    assert "cytoscape" in graph
    assert 'src="' not in graph


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
