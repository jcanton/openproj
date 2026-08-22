"""The landing list: every record, sorted by when a commit last touched it.

The time comes from a history walk (`Store.last_edited`), never from a field or
an mtime; the search box is the shared control bar over the shared `matches()`;
and there are FOUR ways for the list to be empty, each with its own sentence,
because a filter matching nothing, a plan with nothing in it, a query that
cannot be read and a payload that never arrived are four different things to do
next. The export renders the same page, minus the time column when the
directory it reads has no history to ask.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pygit2
from fastapi.testclient import TestClient
from pages import lit, nav_of
from test_injection import run_js
from test_store import commit_directly

from openproj.index import apply_filters, build_index
from openproj.model import edited_by_id, load_repo
from openproj.render import _ago, render_records, render_static
from openproj.web import create_app

# The task's path is the one the tests edit, so it gets a name. Every filename
# carries its record's id in the stem — `<id>--<slug>.md`, the layout rule
# `edited_by_id` joins by — because a file named otherwise is a reported
# blocker whose row rightly has no time on it, and these tests are about the
# rows that do.
TASK_PATH = "tasks/task-c00001--downgrade-numpy.md"

PLAN = {
    "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
    "projects/proj-a10000--tracer-engine.md": (
        "---\nid: proj-a10000\nkind: project\ntitle: Tracer engine\n"
        "status: in_progress\nowner: ann\n---\n\nThe project.\n"
    ),
    # A non-ASCII title and tag, because blob drift between the shared search
    # helper and its JS twin is exactly the kind of defect ASCII cannot see.
    "pitches/pitch-b20000--tracage.md": (
        "---\nid: pitch-b20000\nkind: pitch\ntitle: \"Traçage à l'équateur\"\n"
        "status: ready\nowner: ann\ntags: [gpu, 平流]\nparent: proj-a10000\n"
        "person_weeks: 2\n---\n\nA pitch.\n"
    ),
    TASK_PATH: (
        "---\nid: task-c00001\nkind: task\ntitle: Downgrade numpy\nstatus: ready\n"
        "owner: bo\nprs: ['C2SM/icon4py#1223']\nparent: pitch-b20000\n"
        "person_weeks: 1\n---\n\nA task.\n"
    ),
    # An issue and a note, in the file format that never changed: no `kind:`
    # key, because the parser resolves the kind from the id prefix. They rode
    # in this corpus one commit ahead of the flip, matching nothing; now they
    # are records like everything else, and the needles below land on them.
    "issues/issue-ab12cd.md": (
        "---\nid: issue-ab12cd\ntitle: \"Renormalisation à l'équateur\"\n"
        "status: ready\nreported_by: ann\ntags: [数值]\n---\n\nSeen near the pole.\n"
    ),
    "notes/note-ef34ab.md": (
        "---\nid: note-ef34ab\ntitle: \"Idée: traceur passif\"\nstatus: thinking\n"
        "written_by: bo\ntags: [gpu]\n---\n\nHalf a thought.\n"
    ),
}


def plan_repo(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    return path


def load_repo_from_git(path: Path):
    """The corpus as the server reads it, via a worktree-free read of head.

    `load_repo` reads a worktree and these fixtures are bare repositories, so
    this reuses `web.py`'s own `_entities_at`/`_config_at` rather than growing
    a third reader.
    """
    from openproj.store import Store
    from openproj.web import _config_at, _entities_at

    store = Store(path)
    try:
        head = store.head()
        config, bad_config = _config_at(store, head)
        entities, bad_entities = _entities_at(store, head)
    finally:
        store.close()
    return entities, config, [*bad_config, *bad_entities]


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


def test_the_landing_lists_every_record_newest_edit_first(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    edited = dict(PLAN)
    edited[TASK_PATH] = PLAN[TASK_PATH].replace("Downgrade numpy", "Downgrade numpy again")
    commit_directly(path, edited, "edit the task", when=1_000_500)

    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    entities, config, _ = load_repo_from_git(path)
    index = build_index(entities, config, date(2026, 8, 17))
    rows = re.findall(r'<li data-id="([\w-]+)"', page)
    # Derived from `index.records`, not written out — which is how this page and
    # this expectation widened together on the flip commit, with no edit here.
    # The membership pin below is what keeps the derivation honest.
    assert set(rows) == set(index.records)
    assert "issue-ab12cd" in rows and "note-ef34ab" in rows, (
        "the corpus's inbox records are records now, and the landing lists them"
    )
    assert "task-c00001" in rows, "an empty records map would make this pass vacuously"
    assert rows[0] == "task-c00001", "the record edited last is the record listed first"
    assert 'href="/detail/task-c00001"' in page
    assert '<span class="chip kind-task">' in page
    assert '<span class="when">' in page


def test_the_nav_says_records_at_the_root_and_table_at_table(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        landing = client.get("/").text
        table = client.get("/table").text
    assert lit(landing) == ["Records"]
    assert lit(table) == ["Table"]
    assert [label for label, _, _ in nav_of(landing)][:2] == ["Records", "Table"]


def test_every_row_carries_an_empty_predicates_array(tmp_path: Path):
    """`matches()` dereferences `row.predicates` without a guard, so an omitted
    array plus a `?predicate=` in the URL is a TypeError and a blank page."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    block = re.search(
        r'<script id="landing" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    data = json.loads(block)
    assert data["rows"], "an empty payload proves nothing"
    assert all(row["predicates"] == [] for row in data["rows"].values())


def test_a_predicate_in_the_url_is_a_sentence_and_not_a_blank_page(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('predicate', 'has_blocker'); recordsApply();"
        " return [document.getElementById('records-empty').hidden,"
        "  document.querySelector('#records-empty .headline').textContent,"
        "  [...document.querySelectorAll('#records li[data-id]')]"
        "    .filter(li => !li.hidden).length]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    hidden, headline, shown = answer["value"]
    assert shown == 0
    assert hidden is False
    assert headline == "No record matches this search."


# --------------------------------------------------------------------------- #
# The four empty states
# --------------------------------------------------------------------------- #


def test_a_plan_with_no_records_says_so_from_the_server(tmp_path: Path):
    root = tmp_path / "empty"
    (root / "config").mkdir(parents=True)
    (root / "config" / "defaults.yaml").write_text(
        "schema_version: 1\nnominal_availability: 1.0\n", encoding="utf-8"
    )
    entities, config, unreadable = load_repo(root)
    page = render_records(build_index(entities, config, date(2026, 8, 17)), edited={}, now=0)
    assert "This plan has no records yet." in page
    assert "Nothing has been written down." in page


def test_an_unreadable_query_goes_to_the_error_region_not_to_a_row(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('q', 'kind:'); sayQueryError(); recordsApply();"
        " const err = document.getElementById('query-error');"
        " return [err.hidden, err.textContent,"
        "  document.querySelector('#records-empty .headline').textContent]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    hidden, said, headline = answer["value"]
    assert hidden is False
    assert said, "the parse error must reach #query-error"
    assert headline == "That search cannot be read."


def test_a_filtered_out_row_is_display_none_and_not_merely_marked(tmp_path: Path):
    """Pinned at source because the driver above has no layout and cannot tell
    painted from unpainted: it said 0 shown while every row stayed on screen,
    because `#records li`'s `display: flex` is (1,0,1) and the browser's own
    `[hidden] { display: none }` is (0,1,0). Found on a screenshot, the same
    way `.commitbar[hidden]` was."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    assert "#records li[hidden] { display: none; }" in page


def test_a_search_that_matches_nothing_says_so(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('q', 'zzyzzx'); recordsApply();"
        " return document.querySelector('#records-empty .headline').textContent; })()",
        page=True,
    )
    assert answer["value"] == "No record matches this search."


def test_a_lost_payload_degrades_to_an_unfiltered_list_and_says_so(tmp_path: Path):
    """The rows are server-rendered, so a payload that did not survive the trip
    must NOT empty the page — the table's fourth emptiness inverted. Driven, not
    grepped: the payload text is corrupted in the page string, so the real
    JSON.parse throws, the real catch runs, and the real recordsApply() decides
    what a reader sees — a regression that keeps the sentence but hides the rows
    fails here, where a source-substring assertion would stay green."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    total = len(re.findall(r'<li data-id="', page))
    broken = page.replace(
        '<script id="landing" type="application/json">',
        '<script id="landing" type="application/json">not json ', 1,
    )
    answer = run_js(
        broken,
        "(() => [document.querySelector('#records-empty .headline').textContent,"
        " document.querySelector('#records-empty .hint').textContent,"
        " [...document.querySelectorAll('#records li[data-id]')]"
        "   .filter(li => !li.hidden).length])()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    headline, hint, shown = answer["value"]
    assert headline == "This search cannot run."
    assert hint == "The page arrived without its search data, so the list is shown unfiltered."
    assert total and shown == total, (
        "a lost payload must leave every server-rendered row on the page"
    )


# --------------------------------------------------------------------------- #
# The time string
# --------------------------------------------------------------------------- #


def test_the_time_is_relative_when_recent_and_absolute_past_two_weeks():
    """The shape read off docs/hackmd-observed.md: `17 hours ago` … `10 days
    ago`, then a date. Past the threshold the relative form is abandoned, not
    extended, and a stamp from a clock ahead of ours is a date, never a
    countdown."""
    now = 1_755_600_000
    assert _ago(now - 30, now) == "just now"
    assert _ago(now - 5 * 60, now) == "5 minutes ago"
    assert _ago(now - 3600, now) == "an hour ago"
    assert _ago(now - 17 * 3600, now) == "17 hours ago"
    assert _ago(now - 86400, now) == "a day ago"
    assert _ago(now - 10 * 86400, now) == "10 days ago"
    assert _ago(now - 13 * 86400, now) == "13 days ago"
    fortnight = now - 14 * 86400
    absolute = datetime.fromtimestamp(fortnight, tz=UTC).date().isoformat()
    assert _ago(fortnight, now) == absolute
    ahead = datetime.fromtimestamp(now + 7200, tz=UTC).date().isoformat()
    assert _ago(now + 7200, now) == ahead


# --------------------------------------------------------------------------- #
# Search parity with the JS twin (spec test 15)
# --------------------------------------------------------------------------- #


def test_the_landing_box_and_the_server_find_the_same_records(tmp_path: Path):
    """The landing's `matches()` runs over its own payload, which is a second
    place the search blob travels — so both halves are asked the same
    questions, non-ASCII included. The corpus carries an issue and a note, so
    parity is asked about the very records where `records` is more than
    `entities`."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    entities, config, _ = load_repo_from_git(path)
    index = build_index(entities, config, date(2026, 8, 17))

    needles = ["traçage", "équateur", "Équateur", "平流", "gpu", "ann",
               "task-c00001", "1223", "downgrade", "tag:gpu", "kind:pitch",
               # The issue's and the note's words, non-ASCII where it counts —
               # and their kinds by name, which only exist as facet values on
               # the records side.
               "renormalisation", "数值", "idée", "issue-ab12cd", "note-ef34ab",
               "kind:issue", "kind:note"]
    disagreed = {}
    for needle in needles:
        # Membership is the claim; the two sides answer in different orders
        # (walk order here, sorted in the JS expression), so both are sorted.
        # `over=index.records`, because the JS twin filters RECORDS.rows —
        # the record population, not the plan.
        here = sorted(apply_filters(index, {}, needle, over=index.records))
        answer = run_js(
            page,
            "(() => { params.set('q', " + json.dumps(needle) + ");"
            " return Object.keys(RECORDS.rows)"
            "   .filter(id => matches(RECORDS.rows[id])).sort(); })()",
            page=True,
        )
        assert not [e for e in answer["errors"] if e.startswith("expression:")], (
            needle, answer["errors"],
        )
        if here != answer["value"]:
            disagreed[needle] = (here, answer["value"])
    assert not disagreed, f"the landing box and the server disagree: {disagreed}"


# --------------------------------------------------------------------------- #
# The export
# --------------------------------------------------------------------------- #


def test_an_export_without_git_omits_the_time_column(tmp_path: Path):
    """Omitted, not blank: blank looks broken. And never file mtimes, which
    say "just now" about the whole plan after every fresh clone."""
    from openproj.store import last_edited_in

    root = tmp_path / "plain"
    for name, text in PLAN.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    assert last_edited_in(root) is None

    entities, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    written = render_static(build_index(entities, config, date(2026, 8, 17)), out)
    assert written[:2] == ("index.html", "table.html")
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="when">' not in landing
    assert '<li data-id="task-c00001">' in landing


def test_an_export_of_a_repository_carries_the_times(tmp_path: Path):
    from openproj.store import last_edited_in

    root = tmp_path / "checkout"
    pygit2.init_repository(str(root), bare=False, initial_head="main")
    for name, text in PLAN.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    commit_directly(root, PLAN, "seed", when=1_000_000)
    edited = dict(PLAN)
    edited[TASK_PATH] = PLAN[TASK_PATH].replace("Downgrade numpy", "Downgrade numpy again")
    (root / TASK_PATH).write_text(edited[TASK_PATH], encoding="utf-8")
    commit_directly(root, edited, "edit the task", when=2_000_000)

    stamps = last_edited_in(root)
    assert stamps is not None and stamps[TASK_PATH] == 2_000_000

    entities, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    render_static(
        build_index(entities, config, date(2026, 8, 17)), out,
        edited=edited_by_id(stamps), now=2_000_000 + 3600,
    )
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="when">an hour ago</span>' in landing
    rows = re.findall(r'<li data-id="([\w-]+)"', landing)
    assert rows[0] == "task-c00001", "sorted by last edit in the export too"
