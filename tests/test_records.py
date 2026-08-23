"""The landing list: every record, sorted by when a commit last touched it —
and, held to one kind each, the inbox views `/issues` and `/notes`, which are
the same page over a smaller population.

The time comes from a history walk (`Store.last_edited`), never from a field or
an mtime; the search box is the shared control bar over the shared `matches()`;
and there are FOUR ways for the list to be empty, each with its own sentence,
because a filter matching nothing, a view with nothing in it, a query that
cannot be read and a payload that never arrived are four different things to do
next. The export renders the same three pages, minus the time column when the
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
from openproj.render import ROUTES, _ago, render_records, render_static
from openproj.web import create_app

# The task's path is the one the tests edit, so it gets a name. Every filename
# carries its record's id in the stem — `<id>--<slug>.md`, the layout rule
# `edited_by_id` joins by — because a file named otherwise is a reported
# blocker whose row rightly has no time on it, and these tests are about the
# rows that do.
TASK_PATH = "tasks/task-c00001--downgrade-numpy.md"

PLAN = {
    "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
    # The corpus holds at least one value for EVERY field the landing row can
    # be asked about — product and project through the holder walk, cycle,
    # assignees, reviewers, owner, priority (the model's default), status,
    # tags, prs — because the parity test below compares the box against the
    # server field by field, and a field no record holds is a field whose
    # parity check passes vacuously. That shape is what broke last time: a
    # sweep seeded `depends_on` but not `parent`, and the twin hazard sat
    # green behind it.
    "products/prod-e00001--icon4py.md": (
        "---\nid: prod-e00001\nkind: product\ntitle: icon4py\n---\n\nThe codebase.\n"
    ),
    "projects/proj-a10000--tracer-engine.md": (
        "---\nid: proj-a10000\nkind: project\ntitle: Tracer engine\n"
        "status: in_progress\nowner: ann\nparent: prod-e00001\n---\n\nThe project.\n"
    ),
    # A non-ASCII title and tag, because blob drift between the shared search
    # helper and its JS twin is exactly the kind of defect ASCII cannot see.
    "pitches/pitch-b20000--tracage.md": (
        "---\nid: pitch-b20000\nkind: pitch\ntitle: \"Traçage à l'équateur\"\n"
        "status: ready\nowner: ann\ntags: [gpu, 平流]\nparent: proj-a10000\n"
        "cycle: 1\nperson_weeks: 2\n---\n\nA pitch.\n"
    ),
    TASK_PATH: (
        "---\nid: task-c00001\nkind: task\ntitle: Downgrade numpy\nstatus: ready\n"
        "owner: bo\nassignees: [cara]\nreviewers: [dan]\n"
        "prs: ['C2SM/icon4py#1223']\nparent: pitch-b20000\n"
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
    this reuses `web.py`'s own `_records_at`/`_config_at` rather than growing
    a third reader.
    """
    from openproj.store import Store
    from openproj.web import _config_at, _records_at

    store = Store(path)
    try:
        head = store.head()
        config, bad_config = _config_at(store, head)
        records, bad_records = _records_at(store, head)
    finally:
        store.close()
    return records, config, [*bad_config, *bad_records]


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

    records, config, _ = load_repo_from_git(path)
    index = build_index(records, config, date(2026, 8, 17))
    rows = re.findall(r'<tr data-id="([\w-]+)"', page)
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
    assert '<td data-col="edited">' in page


def test_the_nav_says_records_at_the_root_and_table_at_table(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        landing = client.get("/").text
        table = client.get("/table").text
    assert lit(landing) == ["Records"]
    assert lit(table) == ["Table"]
    labels = [label for label, _, _ in nav_of(landing)]
    assert labels[:2] == ["Records", "Table"]
    assert labels[-2:] == ["Issues", "Notes"], (
        "the inbox views are back in the nav: quick access to what would "
        "otherwise be a click on a filter"
    )


def test_the_inbox_routes_render_the_landing_held_to_one_kind(tmp_path: Path):
    """`/issues` and `/notes` are the landing page over a smaller population —
    not a redirect (which is what they briefly were) and not pages of their
    own (which is what they were before that). A row of the wrong kind on
    either is the filter leaking; a 301 is the route regressing to the flip
    commit's stopgap."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        issues = client.get("/issues")
        notes = client.get("/notes")
    assert issues.status_code == 200 and notes.status_code == 200
    assert re.findall(r'<tr data-id="([\w-]+)"', issues.text) == ["issue-ab12cd"]
    assert re.findall(r'<tr data-id="([\w-]+)"', notes.text) == ["note-ef34ab"]
    assert lit(issues.text) == ["Issues"]
    assert lit(notes.text) == ["Notes"]
    # One page: the same header row, the same search box, the same payload
    # script — and none of the old pages' second vocabulary: no state dropdown
    # (the query box says `status:shelved`) and no facet dropdowns at all.
    for view in (issues.text, notes.text):
        assert '<th data-col="kind">' in view and '<th data-col="who">' in view
        assert 'id="q"' in view and 'id="landing"' in view
        assert 'state-filter' not in view
        assert 'class="facet"' not in view and "data-field=" not in view


def test_each_view_offers_its_own_create_button(tmp_path: Path):
    """Create record / Create issue / Create note, kind pre-filled — and on
    `/` the picker's default, which is what a bare `/new` opens on. The label
    and the href move together: a button saying one kind and opening another
    is the control lying about what will happen."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        wanted = {
            "/": ('href="/new"', "Create record"),
            "/issues": ('href="/new?kind=issue"', "Create issue"),
            "/notes": ('href="/new?kind=note"', "Create note"),
        }
        for route, (href, label) in wanted.items():
            page = client.get(route).text
            assert f'<a class="button" {href}>{label}</a>' in page, route


def test_the_who_column_reads_the_field_the_rung_says(tmp_path: Path):
    """Per rung, off the ladder: an issue's Who is `reported_by`, a note's is
    `written_by`, work's is `owner` — and the header is Who, not "Created by",
    because `owner` is who HOLDS a record, not who typed it. Asserted on the
    cells so the wrong field per rung fails here, not just the label."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    assert '<th data-col="who">Who</th>' in page
    cells = dict(re.findall(
        r'<tr data-id="([\w-]+)">.*?<td data-col="who">([^<]*)</td>', page, re.S
    ))
    assert cells["issue-ab12cd"] == "ann", "an issue's Who is its reporter"
    assert cells["note-ef34ab"] == "bo", "a note's Who is its writer"
    assert cells["task-c00001"] == "bo", "work's Who is its owner"
    # A product does not read `owner` (it is not work), so a stray value in its
    # file must not surface: Who is the em dash every unset field wears.
    assert cells["prod-e00001"] == "—"


def test_every_row_carries_the_predicates_the_server_computes(tmp_path: Path):
    """The row's `predicates` are real now, and exactly the server's own:
    `matches()` dereferences `row.predicates` without a guard (an omitted array
    plus a `?predicate=` in the URL is a TypeError and a blank page), and the
    shipped `[]` it used to carry made `predicate:blocked` answer nothing in
    the box while the server answered rows — the disagreement this branch
    closes. Field-identical to `query_fields`, not merely present, so a row
    computing its flags a second, different way fails here."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    block = re.search(
        r'<script id="landing" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    data = json.loads(block)
    assert data["rows"], "an empty payload proves nothing"

    from openproj.index import query_fields

    records, config, _ = load_repo_from_git(path)
    index = build_index(records, config, date(2026, 8, 17))
    for record_id, row in data["rows"].items():
        assert row["predicates"] == query_fields(index, record_id)["predicate"], record_id
    assert any(row["predicates"] for row in data["rows"].values()), (
        "a corpus where no predicate holds anywhere proves only that [] == []"
    )


def test_a_predicate_in_the_url_filters_rows_and_an_unmatched_one_is_a_sentence(
    tmp_path: Path,
):
    """Both directions, because each catches what the other cannot: a row
    payload regressing to `predicates: []` makes `untracked` show zero rows
    (the first half fails), and a broken empty state makes the unmatched
    predicate a blank page rather than a sentence (the second half fails).
    `review_waived` is the unmatched one by construction — nothing in the
    corpus waives review."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    records, config, _ = load_repo_from_git(path)
    index = build_index(records, config, date(2026, 8, 17))
    untracked = sorted(apply_filters(index, {}, "predicate:untracked", over=index.records))
    assert untracked, "the corpus must hold untracked work or this test asks nothing"

    answer = run_js(
        page,
        "(() => { params.set('predicate', 'untracked'); recordsApply();"
        " const shown = [...document.querySelectorAll('#records tbody tr[data-id]')]"
        "   .filter(tr => !tr.hidden).map(tr => tr.dataset.id).sort();"
        " params.delete('predicate');"
        " params.set('predicate', 'review_waived'); recordsApply();"
        " return [shown,"
        "  document.getElementById('records-empty').hidden,"
        "  document.querySelector('#records-empty .headline').textContent,"
        "  [...document.querySelectorAll('#records tbody tr[data-id]')]"
        "    .filter(tr => !tr.hidden).length]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    shown, hidden, headline, none_shown = answer["value"]
    assert shown == untracked, "the box and the server disagree about ?predicate="
    assert none_shown == 0
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
    records, config, unreadable = load_repo(root)
    index = build_index(records, config, date(2026, 8, 17))

    page = render_records(index, edited={}, now=0)
    assert "This plan has no records yet." in page
    assert '<tr class="nothing"' in page, (
        "inside the table body, under the header row, like every other empty "
        "record table — not a sentence floating beside a void"
    )
    # No server behind the page (`base_commit=None`, the export): no create
    # control, so the state must not point at one.
    assert "Create record" not in page

    # With a server the empty state carries the way out of it.
    served = render_records(index, ROUTES, base_commit="abc", edited={}, now=0)
    assert "This plan has no records yet." in served
    assert '<a class="button primary" href="/new">Create record</a>' in served


def test_an_empty_view_and_an_empty_plan_are_different_sentences(tmp_path: Path):
    """The corpus HAS records; `/issues` without issues must say "no issues
    are open", not claim the plan is empty — and each view's empty state
    invites the create control for its own kind. One shared sentence across
    the three views is the regression this pins out."""
    without_inbox = {
        name: text for name, text in PLAN.items()
        if not name.startswith(("issues/", "notes/"))
    }
    path = plan_repo(tmp_path)
    commit_directly(path, without_inbox, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        issues = client.get("/issues").text
        notes = client.get("/notes").text
        landing = client.get("/").text

    assert "No issues are open." in issues
    assert '<a class="button primary" href="/new?kind=issue">Create issue</a>' in issues
    assert "no records yet" not in issues

    assert "Nothing has been written down yet." in notes
    assert '<a class="button primary" href="/new?kind=note">Create note</a>' in notes

    # The landing still has rows, so its nothing-row is hidden and empty —
    # the sentence rides only the SAID payload, for the states the browser
    # can still reach.
    assert 'id="records-empty" hidden' in landing
    nothing = re.search(r'<tr class="nothing".*?</tr>', landing, re.S).group(0)
    assert "This plan has no records yet." not in nothing


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
    because `#records li`'s `display: flex` was (1,0,1) and the browser's own
    `[hidden] { display: none }` is (0,1,0). Found on a screenshot, the same
    way `.commitbar[hidden]` was. The rows are `<tr>`s now and no author rule
    gives them a display, so the UA rule would win today — the pin holds the
    guard that keeps a future `#records tr { display: … }` from putting every
    hidden row back."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    assert "#records tbody tr[hidden] { display: none; }" in page


def test_a_search_that_matches_nothing_says_so_in_the_views_own_words(tmp_path: Path):
    """"No record", "no issue", "no note" — the population the sentence is
    about is the view's, and one shared sentence would claim more than the
    page shows on the two filtered views."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        pages = {
            "record": client.get("/").text,
            "issue": client.get("/issues").text,
            "note": client.get("/notes").text,
        }
    for word, page in pages.items():
        answer = run_js(
            page,
            "(() => { params.set('q', 'zzyzzx'); recordsApply();"
            " return document.querySelector('#records-empty .headline').textContent; })()",
            page=True,
        )
        assert answer["value"] == f"No {word} matches this search.", word


def test_a_state_only_the_script_reaches_is_announced_and_only_once(tmp_path: Path):
    """Filtering to nothing was silent for a screen-reader user: the nothing-row
    is a `tr` and must not be a live region (`role="status"` there would
    overwrite the table's row semantics), so `recordsApply` speaks through the
    shell's `announce` into the sr-only #announce region — this page has no
    #state for it to prefer. The parse-error state must NOT go there:
    #query-error is `role="status"` itself and already announces, and a second
    sentence would double-speak. And a cleared filter empties the region, so
    filtering to nothing a second time is a change the region announces rather
    than a repeat it may swallow."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { const region = document.getElementById('announce');"
        " const heard = [];"
        " params.set('q', 'zzyzzx'); recordsApply(); heard.push(region.textContent);"
        " params.set('q', ''); recordsApply(); heard.push(region.textContent);"
        " params.set('q', 'zzyzzx'); recordsApply(); heard.push(region.textContent);"
        " params.set('q', 'kind:'); sayQueryError(); recordsApply();"
        " heard.push(region.textContent);"
        " return heard; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    said, cleared, again, on_error = answer["value"]
    assert said == "No record matches this search."
    assert cleared == "", "rows showing again must empty the region, not leave it stale"
    assert again == "No record matches this search.", (
        "the second no-match must be announced, not swallowed as a repeat"
    )
    assert on_error == "", "#query-error speaks the parse error itself; this would double-speak"


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
    total = len(re.findall(r'<tr data-id="', page))
    broken = page.replace(
        '<script id="landing" type="application/json">',
        '<script id="landing" type="application/json">not json ', 1,
    )
    answer = run_js(
        broken,
        "(() => [document.querySelector('#records-empty .headline').textContent,"
        " document.querySelector('#records-empty .hint').textContent,"
        " [...document.querySelectorAll('#records tbody tr[data-id]')]"
        "   .filter(tr => !tr.hidden).length])()",
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
    `plan`.

    The row now carries every field `QUERY_FIELDS` names — status, owner,
    priority, cycle, assignees, reviewers, prs, project, product and real
    predicates beside the id/kind/title/tags it always had — so the needles
    ask about all of them, each with at least one holder in the corpus (a
    field nobody holds is a parity check that passes vacuously). Before this,
    `status:done` in the box or `/?owner=ann` pasted from a table URL hid
    every row and said "no match" while the server answered rows.

    What the two sides still agree NOT to answer: bodies. Neither the blob
    nor any field carries prose, per the `SEARCH_FIELDS` ruling in index.py —
    a population-wide fact, not a box-versus-server disagreement."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    records, config, _ = load_repo_from_git(path)
    index = build_index(records, config, date(2026, 8, 17))

    needles = ["traçage", "équateur", "Équateur", "平流", "gpu", "ann",
               "task-c00001", "1223", "downgrade", "tag:gpu", "kind:pitch",
               # The issue's and the note's words, non-ASCII where it counts —
               # and their kinds by name, which only exist as facet values on
               # the records side.
               "renormalisation", "数值", "idée", "issue-ab12cd", "note-ef34ab",
               "kind:issue", "kind:note",
               # One needle per field the row could not answer before the
               # widening, each finding something. `status:ready` lands on the
               # pitch, the task AND the issue — the field crosses the
               # plan/inbox line. `assignee:` and `reviewer:` are the aliases,
               # so the alias map is in the claim too.
               "status:ready", "owner:ann", "priority:medium",
               "cycle:1", "assignee:cara", "reviewer:dan", "prs:1223",
               "project:proj-a10000", "product:prod-e00001",
               "predicate:untracked", "predicate:has_blocker"]
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
    # The vacuity guard for the widened fields: every field-needle must FIND
    # something on the server side, or its parity above proved [] == [].
    for needle in ("status:ready", "owner:ann", "priority:medium", "cycle:1",
                   "assignee:cara", "reviewer:dan", "prs:1223",
                   "project:proj-a10000", "product:prod-e00001",
                   "predicate:untracked", "predicate:has_blocker"):
        assert apply_filters(index, {}, needle, over=index.records), needle


def test_the_issues_view_box_searches_issues_and_nothing_else(tmp_path: Path):
    """The filtered view's payload is its population: a query on `/issues`
    that names a pitch's word must find nothing there while finding the pitch
    on `/` — a payload that quietly carried the whole plan would answer both
    the same and the view would "match" rows it cannot show."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        issues = client.get("/issues").text

    answer = run_js(
        issues,
        "(() => {"
        " const over = q => { params.set('q', q);"
        "   return Object.keys(RECORDS.rows)"
        "     .filter(id => matches(RECORDS.rows[id])).sort(); };"
        " return [over('renormalisation'), over('traçage'), over('status:ready')]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    the_issue, the_pitch, ready = answer["value"]
    assert the_issue == ["issue-ab12cd"]
    assert the_pitch == [], "a plan record's word found something on the issues view"
    assert ready == ["issue-ab12cd"], (
        "status: crosses the plan/inbox line, held to this view's population"
    )


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

    records, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    written = render_static(build_index(records, config, date(2026, 8, 17)), out)
    assert written[:2] == ("index.html", "table.html")
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<th data-col="edited">' not in landing, "omitted, not blank: the header too"
    assert '<td data-col="edited">' not in landing
    assert '<tr data-id="task-c00001">' in landing

    # The two inbox views ride the export too — every page's nav names them,
    # and a nav link into a file nobody wrote is a dead link on all the others.
    assert {"issues.html", "notes.html"} <= set(written)
    issues = (out / "issues.html").read_text(encoding="utf-8")
    assert re.findall(r'<tr data-id="([\w-]+)"', issues) == ["issue-ab12cd"]
    assert '<td data-col="edited">' not in issues
    assert "Create issue" not in issues, "a rendered file has nowhere to post"


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

    records, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    render_static(
        build_index(records, config, date(2026, 8, 17)), out,
        edited=edited_by_id(stamps), now=2_000_000 + 3600,
    )
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<td data-col="edited">an hour ago</td>' in landing
    rows = re.findall(r'<tr data-id="([\w-]+)"', landing)
    assert rows[0] == "task-c00001", "sorted by last edit in the export too"


# --------------------------------------------------------------------------- #
# The scroll mechanism
# --------------------------------------------------------------------------- #


def test_the_header_row_is_sticky_and_nothing_on_this_page_outranks_it(tmp_path: Path):
    """Resolved through the real cascade, not grepped: the documented hazard on
    this mechanism is a qualifier added to win one fight silently outranking
    the rules that correct it — `dd, td.edit { position: relative }` once stole
    `position: sticky` from the record table's title column, and the
    `.table-scroll [data-col]` fix for THAT dropped the frozen headers behind
    their own rows. A rule being in the stylesheet says nothing about whether
    it wins, so this asks which rule wins, by name."""
    from cascade import el, sheet_of

    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    sheet = sheet_of(page)

    header = [el("div", "table-scroll"), el("table", id="records"),
              el("thead"), el("tr"), el("th", data_col="title")]
    assert sheet.value(header, "position") == "sticky", (
        sheet.selectors_reaching(header, "position")
    )
    assert sheet.value(header, "top") == "0"
    # Over the rows that pass beneath it, on its own ground: translucent, the
    # frozen row would still be "sticky" and unreadable.
    assert sheet.value(header, "background") == "var(--surface)"
    # The container sticky holds against: `overflow: auto` plus a bounded
    # height is what makes `top: 0` mean the top of the BOX, not of the page.
    box = [el("div", "table-scroll")]
    assert sheet.value(box, "overflow") == "auto"
    assert sheet.value(box, "max-height") == "var(--room)"


def test_the_page_furniture_stands_outside_the_scroll_box(tmp_path: Path):
    """jcanton: "when scrolling scroll just the body of the table, leave the
    rest of the page static (nav, description, search box, table title row)".
    The title row holds by being sticky INSIDE the box (above); the rest holds
    by not being in it — an element inside the scroll container scrolls,
    whatever its rules say."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    box = page.index('<div class="table-scroll"')
    for furniture in ('<p class="hint">', 'class="editbar"', 'id="q"', "</nav>"):
        assert page.index(furniture) < box, furniture
    # And the box is measured by the shell into `--room`, like the table's.
    assert '<div class="table-scroll" data-fills>' in page
