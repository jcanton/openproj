"""Two hostile plans, every page, both modes, and the shipped JavaScript driven.

Every free-text field a signed-in member can type carries the same string, and
that string is a payload: a double quote to end whatever attribute it lands in,
a `>` to end the tag, an `<img onerror>` to prove an element was created, an
ampersand, and a `</script>` with a second image behind it to prove a script
block was closed. Five separate escaping bugs shipped under a green suite
because every test that touched them asserted on a substring of the page. A
substring cannot tell markup from text; a parser can.

The general assertion is a *census*: the same plan is rendered twice, once with
the payload in every field and once with an ordinary sentence of the same shape,
and the two pages must contain exactly the same elements. Text may differ; the
element tree may not. That is "zero elements the plan did not put there" written
as something a machine can check, and it holds for anything a future field might
carry, not only for the four characters this payload happens to use.

The two named checks beside it — no `on*` attribute anywhere, no image the plan
did not write — exist so that a failure says what went wrong instead of printing
two Counters.

The pages are only half of it. The table's rows, the timeline's tooltip, the
combobox popup and the cycle roster are built by the shipped JavaScript at
runtime and appear in no rendered file, so `drive()` runs those exact scripts in
node against the real payload and hands the strings they assign to `innerHTML`
back to the same parser. Without that the four JS defects are invisible here.

The second plan, at the bottom of the file, is the same census over a different
kind of payload: not a character an escaper would touch, but a value that
*equals* something the renderer used to substitute into its own finished output.
Nothing about that payload is hostile to look at, which is exactly why the first
corpus could not see it, and why the second one is read out of the renderer's
source rather than written down here.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import pygit2
import pytest
from fastapi.testclient import TestClient
from hypothesis import example, given, settings
from hypothesis import strategies as st
from test_store import commit_directly

from openproj.index import build_index
from openproj.model import load_repo
from openproj.render import _json, render_static
from openproj.web import create_app

# The quote comes first so the payload escapes an attribute before it opens a
# tag, and the second image sits behind the `</script>` so a value written raw
# into a script block is caught as well as one written into markup. Anything
# less and a chip whose class attribute swallows the whole payload reads as
# "one span, same as the benign page" and the test passes over a live bug.
PAYLOAD = '" ><img src=x onerror=alert(1)> & </script><img src=y onerror=alert(2)>'
# The same field, filled the way a person fills it. Nothing here can become
# markup, so every element on this page is one the renderer meant to write.
BENIGN = "a perfectly ordinary sentence about the tracer advection port"

# What the payload builds if anything lets it. Kept as a set rather than a
# substring search, because the whole point is to ask the parser.
FORGED_IMAGES = {"x", "y"}

# The app's own inline handler, written into two templates by hand — grep
# `onsubmit`: the record page's edit form, the cycle page's setup form — and into no
# value: a form on a page that saves over fetch must not navigate. Named here so
# that "no event handlers" can stay an absolute rule with one stated exception
# rather than a rule with a hole in it.
OURS = ("form", "onsubmit", "return false")

# What `served()` names an entity's own detail page — the editable one.
ONE_ENTITY = "one entity"

STATIC_PAGES = ("index.html", "table.html", "detail.html", "people.html", "cycles.html",
                "graph.html", "timeline.html")


def ids(text: str) -> tuple[str, str, str]:
    """The three ids this plan uses, each carrying the payload."""
    return (f"pitch-b2000{id_text(text)}",
            f"task-c0000{id_text(text)}",
            f"task-c0001{id_text(text)}")


def inbox_ids(text: str) -> tuple[str, str]:
    """The issue and the note, each carrying the payload in its id — the same
    shape the three entity ids take. They were deliberately NOT armed while the
    inbox routes refused their paths and the census read only the list pages;
    an issue now renders on /detail/<id> like everything else, so its id is
    free text to exactly the same renderer."""
    return (f"issue-d0000{id_text(text)}", f"note-e0000{id_text(text)}")


def corpus(text: str) -> dict[str, str]:
    """A plan whose every free-text field holds `text`.

    Three entities, not one. A parent link, a Blocks row and a Blocked-by row
    only exist between records and are rendered by a different code path from
    the fields an entity holds alone, so the plan is a pitch with two tasks under
    it and the second waiting on the first. A task that waited on its own parent
    would have been simpler and useless: that is a contradiction, the scheduler
    refuses to place it, and the timeline then draws no bars at all — which is
    the one page whose tooltip is under test.

    All three are bet into a cycle whose roster names the same hostile login, so
    the cycle page, the people page and the cycles index come with the fixture.

    And one issue and one note, because a corpus that does not hold the one
    string that matters proves nothing about them. They are entities on
    unplanned rungs now, drawn by the one record template — but through fact
    rows no planned kind has (`reported_by`, `written_by`, `pitched_into`,
    `became`), and each links at the hostile pitch — so one record's id
    reaching another record's markup is under test on those rows too.

    The ids are hostile too. A malformed id is a *reported* blocker and not a
    refusal — the entity still loads and every page still draws it — so an id is
    free text as far as the renderer is concerned.
    """
    pitch_id, first_id, second_id = ids(text)
    issue_id, note_id = inbox_ids(text)
    quoted = text_yaml(text)
    common = (
        f"title: '{quoted}'\n"
        f"status: '{quoted}'\n"
        f"priority: '{quoted}'\n"
        f"owner: '{quoted}'\n"
        f"assignees: ['{quoted}']\n"
        f"reviewers: ['{quoted}']\n"
        f"cycle: 41\n"
        f"assigned_on: 2026-08-17\n"
        f"tags: ['{quoted}']\n"
        f"prs: ['{quoted}']\n"
    )
    body = f"\nA shaping document that mentions {text} in its prose.\n"
    return {
        "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
        "pitches/p.md": (
            f"---\nid: '{text_yaml(pitch_id)}'\nkind: pitch\n{common}"
            f"shaped_by: '{quoted}'\nperson_weeks: 2\n---\n{body}"
        ),
        "tasks/one.md": (
            f"---\nid: '{text_yaml(first_id)}'\nkind: task\n{common}"
            f"parent: '{text_yaml(pitch_id)}'\nperson_weeks: 1\n---\n{body}"
        ),
        "tasks/two.md": (
            f"---\nid: '{text_yaml(second_id)}'\nkind: task\n{common}"
            f"parent: '{text_yaml(pitch_id)}'\n"
            f"depends_on: ['{text_yaml(first_id)}']\nperson_weeks: 1\n---\n{body}"
        ),
        # Both inbox records armed like the entities above them: a malformed id
        # is a reported blocker rather than a refusal, so the record loads, and
        # /detail/<id> draws it now that an issue is a rung.
        "issues/i.md": (
            f"---\nid: '{text_yaml(issue_id)}'\ntitle: '{quoted}'\n"
            f"status: '{quoted}'\nreported_by: '{quoted}'\nopened_on: 2026-08-11\n"
            f"tags: ['{quoted}']\npitched_into: ['{text_yaml(pitch_id)}']\n---\n{body}"
        ),
        "notes/n.md": (
            f"---\nid: '{text_yaml(note_id)}'\ntitle: '{quoted}'\n"
            f"status: '{quoted}'\nwritten_by: '{quoted}'\nwritten_on: 2026-08-11\n"
            f"tags: ['{quoted}']\nbecame: ['{text_yaml(pitch_id)}']\n---\n{body}"
        ),
        "cycles/41.md": (
            f"---\ncycle: 41\nstarts_on: 2026-08-17\nbuild_weeks: 4\ncooldown_weeks: 2\n"
            f"availability:\n  '{quoted}': 0.5\n---\n"
            f"\nThe goal of this cycle, which mentions {text}.\n"
        ),
    }


def id_text(text: str) -> str:
    """The payload as an id can hold everything but the `</script>`.

    An id is a URL path segment on the server — `/detail/<id>` — and a slash in
    a path segment is a routing fact, not an escaping one: percent-encoded or
    not, it addresses a different route and the page under test never renders.
    Everything that makes the payload dangerous in markup survives; only the
    script terminator, which no code path writes an id into unescaped, does not.
    """
    return text.split("</script>")[0].strip()


def text_yaml(text: str) -> str:
    """A single-quoted YAML scalar. Neither payload holds a single quote, so this
    only has to be right for the two strings above — it is a fixture helper, not
    a serialiser."""
    return text.replace("'", "''")


class _Census(HTMLParser):
    """Every element and every event handler a page actually contains.

    `HTMLParser` and not a regex: a regex cannot tell `&lt;img&gt;` in a title
    from `<img>` in the markup, which is precisely the distinction under test.
    It also enters raw-text mode inside `<script>` exactly as a browser does, so
    a payload that closes a script block early shows up here as the elements it
    lets loose rather than as text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: Counter[str] = Counter()
        self.handlers: list[str] = []
        self.forged: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] += 1
        for name, value in attrs:
            # An inline handler is the shape every one of these bugs takes, and
            # this app writes exactly one, three times: a `<form>` that refuses
            # to navigate. Everything else attaches its listeners from script,
            # so any other `on*` attribute anywhere is somebody else's.
            if name.startswith("on") and (tag, name, value) != OURS:
                self.handlers.append(f"<{tag} {name}={value!r}>")
        if tag == "img" and dict(attrs).get("src") in FORGED_IMAGES:
            self.forged.append(f"<img src={dict(attrs).get('src')}>")


def census(html: str) -> _Census:
    parser = _Census()
    parser.feed(html)
    parser.close()
    return parser


def assert_clean(html: str, where: str) -> _Census:
    seen = census(html)
    assert not seen.handlers, f"{where}: event handler attributes injected: {seen.handlers}"
    assert not seen.forged, f"{where}: the payload created elements: {seen.forged}"
    return seen


def assert_same_shape(hostile: str, benign: str, where: str) -> None:
    """The element census must not depend on what the text says.

    Stated this way it covers every field and every future one: if swapping a
    sentence for a payload changes the tree, some value reached the markup as
    markup. Attribute values and text are free to differ — that is the escaping
    doing its job.
    """
    got, want = census(hostile).tags, census(benign).tags
    assert got == want, (
        f"{where}: the hostile plan renders a different element tree from the "
        f"benign one. Extra: {got - want}. Missing: {want - got}."
    )


# --------------------------------------------------------------------------- #
# The two modes
# --------------------------------------------------------------------------- #


def static_pages(root: Path, out: Path, plan: dict[str, str]) -> dict[str, str]:
    for path, content in plan.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content, encoding="utf-8")
    entities, config, _ = load_repo(root)
    index = build_index(entities, config, date(2026, 8, 17))
    render_static(index, out)
    return {name: (out / name).read_text(encoding="utf-8") for name in STATIC_PAGES}


@pytest.fixture
def hostile_static(tmp_path: Path) -> dict[str, str]:
    return static_pages(tmp_path / "hostile", tmp_path / "hostile-out", corpus(PAYLOAD))


@pytest.fixture
def benign_static(tmp_path: Path) -> dict[str, str]:
    return static_pages(tmp_path / "benign", tmp_path / "benign-out", corpus(BENIGN))


# Emptied on the flip commit: /issue/{id} and /note/{id} became 301 redirects,
# so they are no longer HTML GET routes and the census reaches every page again.
# The set stays so the completeness test keeps failing closed if a route ever
# needs an exemption with a reason.
CENSUS_BLIND: set[str] = set()


def census_routes(entity_ids: tuple[str, ...]) -> dict[str, str]:
    """Every page the census opens, module-level so the completeness test can
    hold it against `app.routes`. Named rather than keyed by URL: the entity
    pages have the payload in their path, so the hostile plan and the benign
    one address different URLs for the same page."""
    return {
        "records": "/", "table": "/table", "graph": "/graph", "timeline": "/timeline",
        "people": "/people", "cycles": "/cycles", "cycle 41": "/cycle/41",
        # The deck was left out of a census that says it covers every page the
        # server draws, and it is the page a field is most likely to leave the
        # building on: a deck is printed and handed to somebody who was not in
        # the room. Same cycle as the one above, so both read the same plan.
        "deck 41": "/deck/41",
        # The inbox views of the landing — the same page held to one kind, so
        # each renders the hostile issue or note rows under its own URL.
        "issues": "/issues", "notes": "/notes",
        "new issue": "/new?kind=issue", "new note": "/new?kind=note",
        "new task": "/new?kind=task", "new pitch": "/new?kind=pitch",
        # `/detail` is the whole plan and read-only; an entity's own page is the
        # editable one, and the only one that carries the combobox.
        "every detail": "/detail",
        **{
            f"{ONE_ENTITY} {n}": f"/detail/{quote(entity_id, safe='')}"
            for n, entity_id in enumerate(entity_ids)
        },
    }


def served(
    tmp_path: Path, plan: dict[str, str], name: str, entity_ids: tuple[str, ...]
) -> dict[str, str]:
    """Every page the server draws, including the three the export has not.

    The editable pages are the ones that matter most: they are what a signed-in
    member sees, and a page that offers a Save button is the worst possible place
    to run somebody else's script.

    The plan and the ids to open are passed in, not derived from one string,
    because the second corpus in this file has one entity per marker rather than
    one payload in every field.
    """
    path = tmp_path / f"{name}.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, plan, "seed a hostile plan")
    routes = census_routes(entity_ids)
    pages = {}
    with TestClient(create_app(path, auth="dev", secret="a-signing-secret-for-tests")) as client:
        for name, route in routes.items():
            response = client.get(route)
            assert response.status_code == 200, f"{route}: {response.status_code}"
            pages[name] = response.text
    return pages


@pytest.fixture
def hostile_served(tmp_path: Path) -> dict[str, str]:
    return served(tmp_path, corpus(PAYLOAD), "hostile",
                  (*ids(PAYLOAD), *inbox_ids(PAYLOAD)))


@pytest.fixture
def benign_served(tmp_path: Path) -> dict[str, str]:
    return served(tmp_path, corpus(BENIGN), "benign",
                  (*ids(BENIGN), *inbox_ids(BENIGN)))


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #


def test_no_static_page_lets_a_field_become_markup(hostile_static, benign_static):
    for name, html in hostile_static.items():
        assert_clean(html, f"static {name}")
        assert_same_shape(html, benign_static[name], f"static {name}")


def test_no_served_page_lets_a_field_become_markup(hostile_served, benign_served):
    for route, html in hostile_served.items():
        assert_clean(html, f"served {route}")
        assert_same_shape(html, benign_served[route], f"served {route}")


def test_every_html_get_route_is_in_the_census(tmp_path: Path):
    """Risk 2 in the design, closed permanently: the census was a hand-written
    list, and a hand-written list fails OPEN — move the table to /table and the
    census stays green while covering the wrong URL. Held against `app.routes`
    it fails CLOSED: an HTML GET route the census does not open is a failure on
    the commit that adds the route, not a hole found later.

    Filtered on `response_class`: JSON routes, redirects and the asset stream
    are not pages, and a census of them would be a different test.
    """
    from fastapi.responses import HTMLResponse
    from fastapi.routing import APIRoute

    path = tmp_path / "census.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, corpus(BENIGN), "seed a plan for the route census")
    app = create_app(path, auth="dev", secret="a-signing-secret-for-tests")
    with TestClient(app):
        def is_page(route) -> bool:
            drawn = getattr(route, "response_class", None)
            # FastAPI wraps an undeclared response class in a DefaultPlaceholder.
            drawn = getattr(drawn, "value", drawn)
            return isinstance(drawn, type) and issubclass(drawn, HTMLResponse)

        # A list, not a set: `APIRoute` defines `__eq__` and no `__hash__`, so
        # a set of routes is a TypeError before anything is checked at all.
        pages = [
            route
            for route in app.routes
            if isinstance(route, APIRoute) and "GET" in route.methods and is_page(route)
        ]
        assert pages, "no HTML GET routes at all, so nothing was checked"

        # Each census URL is resolved the way Starlette dispatches it: walk
        # `app.routes` in registration order and stop at the FIRST GET route
        # whose regex matches — that route is the one the request reaches.
        # Matching every page against every URL was subtly generous: Starlette's
        # compiled `/issue/new` also matched `/issue/{issue_id}`, so a `{id}`
        # route registered after a literal sibling counted as covered by a URL
        # that could never reach it, and an exemption set fed by that arithmetic
        # was dead code.
        covered: set[str] = set()
        for url in census_routes((*ids(BENIGN), *inbox_ids(BENIGN))).values():
            where = url.partition("?")[0]
            for route in app.routes:
                if not (isinstance(route, APIRoute) and "GET" in route.methods):
                    continue
                if route.path_regex.match(where):
                    # `is_page` again rather than membership in `pages` — the
                    # same filter, asked without route equality or hashing.
                    if is_page(route):
                        covered.add(route.path)
                    break

        templates = {route.path for route in pages}
        missing = templates - covered - CENSUS_BLIND
        assert not missing, (
            "HTML GET routes the injection census never opens — add each to "
            f"census_routes() or, with a reason, to CENSUS_BLIND: {sorted(missing)}"
        )
        stale = CENSUS_BLIND - templates
        assert not stale, f"CENSUS_BLIND names routes that no longer exist: {sorted(stale)}"


def test_no_template_marks_a_value_safe():
    """The Python half of the boundary, stated once.

    `|safe` is a claim about what a variable holds today, and this file had
    twenty of them: `{{ facets|safe }}` beside `{{ e.body }}` beside
    `{{ row.display|safe }}`, all reading alike, one of them a title somebody
    typed. Markup is a *type* now — `_fragment`, `_links`, `_pr_link`,
    `_body_html` and every `display` return `Markup` — so autoescaping decides
    per value rather than per template line, and a plain `str` that turns up
    where markup is expected is escaped rather than injected. Which only stays
    true while nothing writes `|safe` again.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "openproj" / "render.py")
    lines = [
        line for line in source.read_text(encoding="utf-8").splitlines()
        if "|safe" in line and not line.lstrip().startswith(("#", "*"))
        # The rule is written down in three docstrings, which have to be able to
        # name the thing they forbid.
        and "`|safe`" not in line
    ]
    assert not lines, f"a template marks a value safe again: {lines}"


def test_every_page_carries_exactly_one_escaper():
    """And the JavaScript half.

    Two copies of `esc` is how the timeline came to escape the text of a chip
    and not the class beside it, and how the combobox — a third script, on four
    pages — came to have neither copy in scope and escape nothing at all. One
    declaration, in the shell, before the content. It also cannot be two: top
    level `const` in two classic scripts on one page is a SyntaxError, so a
    second copy would take the whole page down rather than drift quietly.
    """
    from openproj.render import _SHELL

    assert _SHELL.count("const esc = ") == 1
    source = (Path(__file__).resolve().parents[1] / "src" / "openproj" / "render.py")
    assert source.read_text(encoding="utf-8").count("const esc = ") == 1


def test_the_fixture_really_is_hostile(hostile_static):
    """A payload that never reaches the page proves nothing.

    Every assertion above passes trivially against a plan whose values were
    dropped on the floor, so this one insists the text is there — escaped, as
    text — on the page that shows the most of it, and on the landing, which is
    where every record surfaces now that the two inbox list pages are folded
    into the shared surfaces.
    """
    for name in ("index.html", "detail.html"):
        page = hostile_static[name]
        assert "&lt;img src=x onerror=alert(1)&gt;" in page, name
        assert census(page).tags["img"] == 0, name
    # The issues.html and notes.html this loop used to name are gone; what
    # carried their meaning — a census that actually SEES the payload-bearing
    # inbox records — is the count: five hostile records, five articles on the
    # shared page, the issue and the note among them. A fold that quietly
    # dropped the two would pass every substring above off the three entities
    # alone.
    assert hostile_static["detail.html"].count("<article") == 5


# --------------------------------------------------------------------------- #
# The shipped JavaScript
# --------------------------------------------------------------------------- #

DRIVER = Path(__file__).parent / "js" / "drive.js"


def run_js(html: str, expression: str = "null", **options: object) -> dict:
    """The page's own scripts, run, with everything they wrote reported back.

    node, not a substring search: `rowHtml`, `tipHtml`, the combobox's `<li>` and
    the cycle roster's `<tr>` exist only after a script has run, so nothing in
    the rendered file shows what they build. The harness runs the page's real
    script blocks against a minimal DOM and reports the raw strings; the parsing
    and the judgement stay here, in the same census the pages get.

    `options` is the driver's — `page`, `replies` — and is what `test_writes`
    drives a refusal with. One entry point, because two ways to start the same
    shim is two shims a year from now.
    """
    if shutil.which("node") is None:  # pragma: no cover - depends on the machine
        pytest.skip("node is not installed, so the shipped JavaScript cannot be driven")
    result = subprocess.run(
        ["node", str(DRIVER), expression, json.dumps(options)],
        input=html, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"the driver failed:\n{result.stderr}"
    return json.loads(result.stdout)


def drive(html: str, expression: str = "null") -> list[str]:
    """Every string those scripts turned into markup: what innerHTML was handed,
    and whatever the expression itself returned."""
    answer = run_js(html, expression)
    strings = [str(s) for s in answer["written"]]
    value = answer["value"]
    if isinstance(value, list):
        strings += [str(v) for v in value]
    elif isinstance(value, str):
        strings.append(value)
    return strings


def assert_js_clean(strings: list[str], where: str) -> None:
    assert strings, f"{where}: the driver produced no markup, so nothing was tested"
    for produced in strings:
        assert_clean(produced, f"{where}: {produced[:160]}")


def test_the_table_draws_its_rows_without_letting_a_field_become_markup(hostile_served):
    """`draw()` runs at load, so every cell of every row is in what it wrote."""
    assert_js_clean(drive(hostile_served["table"]), "table rows")


def test_the_table_cell_editor_does_not_let_a_stored_value_become_markup(hostile_served):
    """Double-clicking a cell writes the stored value back into an input.

    Which is a second seam over the same data: the row is drawn once by
    `rowHtml` and again, differently, by the editor that replaces one of its
    cells.
    """
    written = drive(
        hostile_served["table"],
        "(() => { for (const id of Object.keys(DATA.rows))"
        "   for (const field of Object.keys(EDITABLE)) {"
        "     const cell = document.createElement('td');"
        "     cell.className = 'edit';"
        "     cell.dataset.entity = id; cell.dataset.field = field;"
        "     openEditor(cell);"
        "   } return ''; })()",
    )
    assert_js_clean(written, "table cell editor")


def test_the_hover_card_does_not_let_a_field_become_markup(hostile_served):
    """The card the timeline, the graph and the table all draw.

    It was the timeline's alone and this test was `tipHtml`. One function now, so
    a title that becomes markup here becomes markup on three pages — and the
    class attributes are as much of the census as the words are: a status
    reading `ready" onmouseover=alert(1) x="` came back out of the chips line as
    a real event handler, on the one element of the box a pointer is guaranteed
    to cross.
    """
    written = drive(
        hostile_served["timeline"], "Object.values(DATA.rows).map(row => cardHtml(row, []))"
    )
    assert_js_clean(written, "hover card")


@pytest.mark.parametrize("page", ["table", f"{ONE_ENTITY} 0", "new task", "cycle 41"])
def test_the_combobox_popup_does_not_let_a_suggestion_become_markup(hostile_served, page):
    """Every source, on every page that carries the widget.

    For the `entities` source the label IS an entity title, so opening the Parent
    list is enough to run somebody else's script — on the detail page, which
    offers a Save button one line below it.
    """
    written = drive(
        hostile_served[page],
        "Object.keys(SUGGEST).map(source => {"
        " const input = document.createElement('input');"
        " input.dataset.suggest = source;"
        " attachSuggest(input);"
        " input.dispatchEvent(new Event('input'));"
        " return ''; })",
    )
    assert_js_clean(written, f"combobox on {page}")


ADD_TO_ROSTER = (
    "(() => { const box = document.getElementById('joining');"
    f" box.value = {json.dumps(PAYLOAD)};"
    " document.getElementById('add').onclick();"
    " return ''; })()"
)


def test_adding_somebody_to_a_cycle_does_not_let_the_name_become_markup(hostile_served):
    """The name is typed into the page rather than read from the plan, and it is
    written straight back out as a row — so the person it runs for is whoever
    the typo lands in front of once Save has put it in the file."""
    assert_js_clean(drive(hostile_served["cycle 41"], ADD_TO_ROSTER), "cycle roster")


def test_adding_somebody_whose_name_holds_a_quote_does_not_break_the_button(hostile_served):
    """The check for "are they already in this cycle" is a selector built by
    concatenation, so a name with a quote or a bracket in it is not a selector at
    all. The browser throws inside the click handler, and Add stops working with
    nothing on screen to say why — for every later click too, not only that one.
    """
    answer = run_js(hostile_served["cycle 41"], ADD_TO_ROSTER)
    raised = [error for error in answer["errors"] if error.startswith("expression:")]
    assert not raised, f"the Add button threw rather than adding the row: {raised}"


# --------------------------------------------------------------------------- #
# The seventh site: values that used to be substituted into a finished page
#
# Every page was rendered and then `str.replace`d — `PAYLOAD_JSON`,
# `ELEMENTS_JSON`, `BARS_JSON`, `HELD_JSON`, `ROSTER_JSON`, `ENTITY_HREF` and
# three `@@library@@` markers — over text that by then already held every title,
# owner, tag and login somebody had typed. So a value that merely *equalled* a
# marker was substituted: a title of `BARS_JSON` and an owner of
# `x onmouseover=alert(1) y`, neither containing one character an escaper would
# touch, put a live event handler on every bar link on the timeline; a title of
# `@@cytoscape.min.js@@` re-inlined 796 KB into the graph's data block and left
# the graph with nothing to draw.
#
# The corpus above could not see any of it, because none of those words was in
# it. The corpus below is the marker list itself, read out of the renderer's own
# source so that a marker introduced tomorrow is in the corpus tomorrow.
# --------------------------------------------------------------------------- #

RENDER_PY = Path(__file__).resolve().parents[1] / "src" / "openproj" / "render.py"
WEB_PY = RENDER_PY.with_name("web.py")
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

# A marker is a SHOUTING word or an `@@delimited@@` filename inside a template.
_SHOUTED = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_DELIMITED = re.compile(r"@@[\w.-]+@@")

# The nine that were really substituted, named because the fix deleted them from
# the source: a derivation alone would now come back without the very strings
# this is a regression test for.
SUBSTITUTED = (
    "PAYLOAD_JSON", "ELEMENTS_JSON", "BARS_JSON", "HELD_JSON", "ROSTER_JSON", "ENTITY_HREF",
    "@@cytoscape.min.js@@", "@@dagre.min.js@@", "@@cytoscape-dagre.js@@",
)


def markers() -> tuple[str, ...]:
    """Those nine, and every marker-shaped string the renderer's source still holds.

    Derived and not merely listed. A list is a list that goes stale, and going
    stale is precisely how this defect shipped: the nine were in the templates for
    months and in no test's corpus. So anything shaped like a marker is taken —
    every shouted word in every string constant, every `@@name@@`, and every
    filename under `static/` with and without the delimiters. A tenth marker
    cannot be introduced without landing in this corpus on the same commit.
    """
    found: set[str] = set(SUBSTITUTED)
    for node in ast.walk(ast.parse(RENDER_PY.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= set(_SHOUTED.findall(node.value))
            found |= set(_DELIMITED.findall(node.value))
    for path in STATIC_DIR.iterdir():
        found |= {path.name, f"@@{path.name}@@"}
    return tuple(sorted(found))


MARKERS = markers()


def marker_plan(values: tuple[str, ...]) -> dict[str, str]:
    """One task per value, carrying that value as its title, its owner and its tag,
    and a cycle whose roster names every value as a login.

    One entity per value rather than `corpus()`'s one payload in every field,
    because what triggers this defect is a whole field *equalling* a marker —
    thirty markers concatenated into one title is a title that equals nothing.
    """
    plan = {
        "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
        "cycles/41.md": (
            "---\ncycle: 41\nstarts_on: 2026-08-17\nbuild_weeks: 4\ncooldown_weeks: 2\n"
            "availability:\n"
            + "".join(f"  '{text_yaml(value)}': 0.5\n" for value in values)
            + "---\n\nThe goal of this cycle.\n"
        ),
    }
    for n, value in enumerate(values):
        quoted = text_yaml(value)
        plan[f"tasks/{n:03d}.md"] = (
            f"---\nid: task-c{n:05x}\nkind: task\ntitle: '{quoted}'\n"
            f"status: ready\nowner: '{quoted}'\nreviewers: ['{quoted}']\n"
            f"tags: ['{quoted}']\ncycle: 41\nperson_weeks: 0.5\npriority: medium\n"
            "---\n\nA shaping document.\n"
        )
    return plan


# Same shape, same count, same ids as the marker plan: only the words differ, so
# any difference in the element census is a word that became markup.
BENIGN_VALUES = tuple(f"an ordinary value number {n}" for n in range(len(MARKERS)))

# The ids the marker plan uses, and the three of them whose own detail page is
# opened. Three and not all of them: an entity's page carries the whole plan's
# suggestions either way, so opening the hundred-and-somethingth adds nothing but
# a hundred requests.
MARKER_IDS = tuple(f"task-c{n:05x}" for n in range(3))

JSON_BLOCK = re.compile(r'<script id="([\w-]+)" type="application/json">(.*?)</script>', re.S)
# The two blocks that are a `const` rather than a `<script type>`: same data, same
# `_json`, and they would fail the same way.
JSON_CONST = re.compile(r"^const (HELD|ROSTER) = (.*);$", re.M)


@pytest.fixture(scope="module")
def marker_static(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, str]]:
    root = tmp_path_factory.mktemp("markers")
    return {
        "hostile": static_pages(root / "h", root / "h-out", marker_plan(MARKERS)),
        "benign": static_pages(root / "b", root / "b-out", marker_plan(BENIGN_VALUES)),
    }


@pytest.fixture(scope="module")
def marker_served(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, str]]:
    root = tmp_path_factory.mktemp("markers-served")
    return {
        "hostile": served(root, marker_plan(MARKERS), "hostile", MARKER_IDS),
        "benign": served(root, marker_plan(BENIGN_VALUES), "benign", MARKER_IDS),
    }


def json_blocks(html: str) -> list[tuple[str, str]]:
    return JSON_BLOCK.findall(html) + JSON_CONST.findall(html)


def assert_json_parses(html: str, where: str) -> int:
    """Every data block on the page reads back as JSON.

    The census cannot see this one: a data block blown apart by a substitution is
    text inside a `<script>`, so the element tree is unchanged and the page simply
    arrives with no plan on it. `json.loads` on `<script id="elements">` is what
    the page itself does, and what raised.
    """
    blocks = json_blocks(html)
    for name, text in blocks:
        try:
            json.loads(text)
        except ValueError as error:
            raise AssertionError(f"{where}: the {name} block does not parse: {error}") from None
    return len(blocks)


def test_no_marker_string_reaches_a_static_page_as_anything_but_text(marker_static):
    parsed = 0
    for name, html in marker_static["hostile"].items():
        assert_clean(html, f"static {name}")
        assert_same_shape(html, marker_static["benign"][name], f"static {name}")
        parsed += assert_json_parses(html, f"static {name}")
    assert parsed >= 3, "no data block was checked, so nothing was tested"


def test_no_marker_string_reaches_a_served_page_as_anything_but_text(marker_served):
    parsed = 0
    for route, html in marker_served["hostile"].items():
        assert_clean(html, f"served {route}")
        assert_same_shape(html, marker_served["benign"][route], f"served {route}")
        parsed += assert_json_parses(html, f"served {route}")
    assert parsed >= 6, "no data block was checked, so nothing was tested"


def test_no_title_can_inline_a_library_a_second_time(marker_static, marker_served):
    """`@@cytoscape.min.js@@` as a title inlined the whole library into the graph's
    data block: 796 KB became 1.5–3.8 MB, `json.loads` on `<script id="elements">`
    raised, and the graph drew nothing. Counted from the files rather than from a
    size, because a size is a number somebody has to keep up to date."""
    # The graph's four, named by what they are for rather than by "every `.js` in
    # the directory". That listing was the whole set until Ace was vendored, and
    # Ace belongs to an editing surface: the graph page has none, so counting it
    # here would have asserted it appears once on a page it must never appear on
    # at all. `test_every_library_is_inlined_exactly_once_and_no_marker_survives`
    # is where the pairing of file to page is kept, and it holds both halves.
    heads = {
        path.name: path.read_text(encoding="utf-8")[:200]
        for path in STATIC_DIR.iterdir()
        if path.suffix == ".js" and not path.name.startswith(("ace", "keybinding-"))
    }
    assert len(heads) == 2, "the graph vendors two libraries"
    for where, graph in (
        ("static", marker_static["hostile"]["graph.html"]),
        ("served", marker_served["hostile"]["graph"]),
    ):
        for name, head in heads.items():
            times = graph.count(head)
            assert times == 1, f"{where}: {name} is on the page {times} times, not once"


def test_the_marker_corpus_really_holds_the_markers():
    """A corpus that lost the strings it is named after proves nothing.

    Both halves are checked: the nine are in it, and the derivation is doing work
    — a `markers()` that silently stopped reading the source would leave a corpus
    of exactly the nine, which is the stale list this is meant not to be.
    """
    assert set(SUBSTITUTED) <= set(MARKERS)
    assert len(MARKERS) > 3 * len(SUBSTITUTED), "the derivation found next to nothing"
    plan = marker_plan(MARKERS)
    for value in ("BARS_JSON", "@@cytoscape.min.js@@"):
        assert any(f"title: '{value}'" in text for text in plan.values()), value
        assert any(f"owner: '{value}'" in text for text in plan.values()), value
        assert any(f"tags: ['{value}']" in text for text in plan.values()), value
        assert any(f"  '{value}': 0.5" in text for text in plan.values()), value


def test_no_page_is_assembled_by_substitution():
    """The mechanism itself, gone rather than escaped harder.

    Post-render substitution over text that already holds user data is the defect;
    any escaping scheme layered on top of it is a second thing to get right. Every
    JSON block is a template variable now, rendered through Jinja, and the
    libraries are inlined as values before user data is anywhere near the string —
    so `str.replace` and `re.sub` have no business left in either module.

    Read as syntax and not as text: `render.py` ships JavaScript that calls
    `.replace()` on a string, inside a Python string constant, and a grep cannot
    tell that from a Python call. The parser can.
    """
    offenders = []
    for source in (RENDER_PY, WEB_PY):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            if isinstance(called, ast.Attribute) and called.attr in ("replace", "sub", "subn"):
                offenders.append(f"{source.name}:{node.lineno}: {ast.unparse(node)[:80]}")
    assert not offenders, (
        "a page is being assembled by substitution again:\n" + "\n".join(offenders)
    )


def strings_in(data: object) -> int:
    """How many strings a JSON document holds, keys included — which is how many
    quote characters a correctly escaped rendering of it may contain."""
    if isinstance(data, str):
        return 1
    if isinstance(data, list):
        return sum(strings_in(item) for item in data)
    if isinstance(data, dict):
        return sum(strings_in(key) + strings_in(value) for key, value in data.items())
    return 0


_JSONABLE = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=20,
)


# A string ending in a backslash is the case a blind replace of `\"` gets wrong:
# `json.dumps` writes it `"a\\"`, and taking the last two characters for an
# escaped quote eats the quote that closes the string.
@example({"a\\": 'b"c'})
@example(["a\\", '"', '\\"'])
@example({'<img src=x onerror=alert(1)>': "</script>&amp;"})
@settings(max_examples=200)
@given(_JSONABLE)
def test_the_json_a_page_ships_reads_back_and_can_end_nothing(data: object):
    """What `_json` promises the templates, as a property rather than an example.

    Every JSON block is written into the page as `Markup` — trusted, unescaped —
    on the strength of exactly this: it reads back as what went in, and it carries
    no character that can close a tag, a block or an attribute. The double quote
    is belt and braces; nothing writes JSON into an attribute today, and the
    guarantee is cheaper to keep than to check for at every site.
    """
    text = _json(data)

    assert json.loads(text) == data, "the page would parse back something else"
    assert not set("<>&") & set(text), f"a character that can end a block survived: {text}"
    # Two per string, and not one more: a structural quote is unavoidable — it is
    # what JSON is — and every other one has been respelled `\\u0022`. Counted
    # rather than searched for, because `\\"` also spells an escaped backslash
    # followed by the quote that closes the string, and the two look identical.
    assert text.count('"') == 2 * strings_in(data), f"a raw quote survived: {text}"


def test_no_vendored_library_can_end_the_block_it_is_written_into():
    """`_library` hands the graph template a `Markup`, which is a claim that the
    text is safe to write into a `<script>` unescaped. It is only true while no
    vendored file contains a script terminator, and the files change when they are
    re-vendored."""
    for path in STATIC_DIR.iterdir():
        if path.suffix == ".js":
            assert "</script" not in path.read_text(encoding="utf-8").lower(), path.name
