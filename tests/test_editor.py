"""The editing surface, which is a form and a textarea and nothing more.

CodeMirror and vim keys were vendored, considered, and cut: the spec's own cut
line said CodeMirror saves nothing and costs two days, and 690 KB of editor to
change a handful of fields and one markdown body is not a trade this tool should
make before somebody is measurably slowed down by a textarea.

What the tests below actually pin is narrower than what a browser would check,
and deliberately so. They assert the *shape* the page must have — which controls
exist, which do not, and what the save script is built from — because those are
the properties that decide whether work gets lost. Anything requiring the page's
JavaScript to run is checked in a browser by hand, and said so here rather than
faked with an assertion that only looks like coverage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pygit2
import pytest
from browser import chrome, measured_in
from fastapi.testclient import TestClient
from pages import elements
from test_store import commit_directly
from test_web import ANN, PATH, SECRET, SEED, TASK, file_at, git_head, head, save

from openproj.auth import sign_session
from openproj.web import SESSION_COOKIE, create_app

# Computed by the scheduler, never typed. If one of these ever gains an input,
# somebody can put a start date in a file and the next reschedule will silently
# disagree with it.
DERIVED = ("start", "end", "blocks", "overruns_cycle_weeks", "why")


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


@pytest.fixture
def page(client: TestClient) -> str:
    return client.get(f"/detail/{TASK}").text


def controls(html: str) -> set[str]:
    """Every named form control on the page."""
    return set(re.findall(r'<(?:input|textarea|select)[^>]*\bname="([^"]+)"', html))


def control(html: str, name: str) -> str:
    """The one tag that owns a field, so its attributes can be read."""
    match = re.search(rf'<(?:input|textarea|select)[^>]*\bname="{name}"[^>]*>', html)
    assert match, f"no control named {name!r}"
    return match.group(0)


# --------------------------------------------------------------------------- #
# What the page offers
# --------------------------------------------------------------------------- #


def test_the_detail_page_can_be_edited_in_place(page: str):
    assert '<form id="edit"' in page
    assert 'name="body"' in page
    assert "task-c00001" in page


def test_the_body_textarea_holds_what_is_stored(page: str, client: TestClient):
    """The stored body, byte for byte. An editor that shows a rendered or
    re-wrapped version of the text quietly rewrites it on the next save."""
    stored = client.get("/api/index.json").json()["entities"][TASK]["body"]
    shown = re.search(r'<textarea[^>]*name="body"[^>]*>(.*?)</textarea>', page, re.S).group(1)

    assert stored.strip()
    assert stored.strip() in shown.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def test_the_editable_fields_are_the_ones_a_person_owns(page: str):
    named = controls(page)
    for field in ("title", "status", "owner", "reviewers", "assigned_on", "priority", "body"):
        assert field in named, field


def test_no_derived_value_has_an_input_at_all(page: str):
    """Structurally absent, not disabled. A disabled input is one attribute away
    from being editable, and the next contributor will not know why it was
    disabled; a control that does not exist cannot be wired up by accident."""
    named = controls(page)
    for field in DERIVED:
        assert field not in named, f"{field} is derived and must not be editable"


def test_the_id_is_shown_and_cannot_be_edited(page: str):
    """The id is authoritative — the filename's slug drifts around it. Editing it
    would orphan the file from every reference to it in one keystroke."""
    assert "task-c00001" in page
    assert "id" not in controls(page)


def test_the_page_carries_the_commit_it_was_rendered_at(page: str):
    """Compare-and-swap needs the base the person actually saw. Saving against
    whatever HEAD happens to be at the time silently resolves a real conflict by
    discarding whoever committed in between."""
    base = re.search(r'name="base_commit"[^>]*value="([0-9a-f]{40})"', page)
    assert base, "the editor must know which commit it is editing"


def test_the_save_script_sends_only_what_changed(page: str):
    """A proxy for a behaviour a browser test would check properly: the payload is
    built by diffing against the rendered values, never by serialising the form.
    Sending every field would overwrite whatever somebody else changed while this
    tab was open, which is the whole thing scoped compare-and-swap prevents."""
    assert "ORIGINAL" in page
    assert re.search(r"!==\s*ORIGINAL\[", page), "the payload must be diffed, not serialised"
    assert "new FormData" not in page, "a serialised form sends fields nobody touched"


def test_the_editor_pulls_in_no_library_at_all(page: str):
    """The simple option, chosen deliberately. If this ever fails, somebody has
    added an editor dependency and should have to argue for it."""
    assert "codemirror" not in page.lower()
    assert "CodeMirror" not in page
    assert not re.search(r"<script[^>]+src=", page)


def test_the_way_in_is_at_the_top_and_the_two_ways_out_are_together(page: str):
    """Three buttons, and which of them belongs where is decided by what it does.

    Edit is the way IN, and it was in the sticky bar at the foot of the page —
    so on any record worth reading, the button that lets you change it was a
    scroll past the whole shaping document (jcanton, 2026-08-19, using it). It is
    back at the top, which reverses the argument the bar was built on; that
    argument was about Save, and Save has not moved.

    Save and Cancel are the two ways one editing session ends, and they stay
    together in the sticky bar. Splitting them is how somebody closes a tab
    believing the button at the other end of the page was the way out.
    """
    assert page.index('id="commitbar"') > page.index('<dl id="facts">')
    assert page.index('id="commitbar"') > page.index('class="field body-field"')
    assert re.search(r"\.commitbar \{[^}]*position: sticky; bottom: 0", page, re.S)

    bar = re.search(r'<div class="commitbar".*?</div>', page, re.S).group(0)
    assert 'id="save"' in bar and 'id="cancel"' in bar
    assert 'id="toggle"' not in bar, "the way in is not one of the ways out"
    assert page.index('id="toggle"') < page.index('<dl id="facts">')


def test_the_bar_says_how_much_is_unsaved(page: str):
    """A button that looks the same whether or not anything has been typed is a
    button you press to find out. The count is of changed fields plus the body,
    because those are exactly what a save would send."""
    assert 'id="unsaved"' in page
    assert "BAR.classList.toggle('dirty', count > 0)" in page
    assert re.search(r"unsaved change\$\{count === 1 \? '' : 's'\}", page)
    assert ".commitbar.dirty { border-color: var(--warn); }" in page


def test_the_status_a_row_is_set_to_says_what_it_will_be_refused_without(page: str):
    """The rules were a dict in `render.py` and nowhere on screen. Marked live,
    because moving a task to in_progress is the moment `assigned_on` starts
    mattering — and the moment nobody is looking at the validator."""
    assert 'data-required-at="in_progress"' in control(page, "assigned_on")
    assert 'data-required-at="ready in_progress"' in control(page, "reviewers")
    assert "function markRequired(form)" in page
    assert "form.addEventListener('change', () => markRequired(form));" in page
    # The waiver is a rule being let off, not a rule being broken.
    assert "control.name === 'reviewers' && waived" in page


def test_a_date_box_says_what_it_will_store(page: str):
    """`assigned_on` is printed 2026-07-06 in the read view and drawn 07/06/2026 or
    06/07/2026 in the control that edits it, depending on where the reader is
    sitting. The echo is the value the file gets."""
    assert 'type="date"' in control(page, "assigned_on")
    assert "document.querySelectorAll('input[type=date]')" in page
    assert "echo.className = box.classList.contains('field') ? 'iso field' : 'iso'" in page


def test_the_facts_read_as_a_column_beside_the_document(page: str):
    """One `<article>` still — the sidebar is a pane inside the entity, not a
    second entity — and the prose keeps the measure while the facts take the
    space that was empty to the right of it."""
    assert page.count("<article") == 1
    assert '<aside class="facts">' in page
    assert page.index('<aside class="facts">') < page.index('<div class="main">')
    assert re.search(r"article\.entity \{[^}]*margin: 0 auto", page, re.S)


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def base_of(page: str) -> str:
    return re.search(r'name="base_commit"[^>]*value="([0-9a-f]{40})"', page).group(1)


def test_a_save_changes_one_line_and_leaves_the_file_alone(
    client: TestClient, repo_path: Path, page: str
):
    response = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": base_of(page), "fields": {"priority": "high"}, "body": None},
    )
    assert response.status_code == 200

    stored = pygit2.Repository(str(repo_path))[response.json()["commit"]].tree[PATH]
    text = stored.data.decode("utf-8")
    assert "priority: high" in text
    assert "owner: ann" in text  # untouched
    assert text.count("---") >= 2


def test_a_number_typed_as_a_word_is_refused_rather_than_committed(
    client: TestClient, repo_path: Path, page: str
):
    """A form returns strings. `cycle: soon` parses as YAML perfectly well and then
    breaks the timeline on the next read, so the coercion has to fail here rather
    than in the file. Priority is a closed set now, so it cannot be typed wrong."""
    before = str(pygit2.Repository(str(repo_path)).references["refs/heads/main"].target)
    response = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": base_of(page), "fields": {"cycle": "soon"}, "body": None},
    )
    assert response.status_code == 422
    assert str(pygit2.Repository(str(repo_path)).references["refs/heads/main"].target) == before


def test_the_preview_renders_markdown_without_a_client_side_library(client: TestClient):
    """Preview is a round trip rather than a second markdown implementation in
    JavaScript. Two renderers disagree eventually, and the one people trust is the
    one that is not what gets committed."""
    response = client.post("/api/preview", json={"body": "## Heading\n\nSome *text*.\n"})
    assert response.status_code == 200
    # Parsed, not searched for. `"<h2>" in html` was true until the day a block
    # started carrying the source line it came from, and it was never the claim:
    # what this test means is that the preview contains a level-two heading
    # saying Heading, which is a question about an element.
    drawn = [(e.tag, e.text) for e in elements(response.json()["html"])]
    assert ("h2", "Heading") in drawn
    assert ("em", "text") in drawn


def test_a_preview_cannot_be_used_to_smuggle_html(client: TestClient):
    """The body is written by signed-in members and rendered back to everybody, so
    a script tag in a shaping doc would run in every reader's browser."""
    response = client.post("/api/preview", json={"body": "<script>alert(1)</script>\n"})
    assert "<script>" not in response.json()["html"]


def test_a_conflict_reaches_the_page_as_a_report_and_never_as_markers(
    client: TestClient, page: str
):
    stale = base_of(page)
    client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": stale, "fields": {"owner": "bo"}, "body": None},
    )
    response = client.patch(
        f"/api/entity/{TASK}",
        json={"base_commit": stale, "fields": {"owner": "cy"}, "body": None},
    )

    assert response.status_code == 409
    report = response.json()["conflict"]
    assert "bo" in report and "cy" in report
    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marker not in report


def test_a_served_page_listens_for_somebody_elses_commit(page: str):
    """Announced, never applied. Reloading over an open editor throws away work
    that is not in git yet, and one Save being one commit means nothing moves
    under you until you ask for it."""
    assert "EventSource('/api/events')" in page
    assert "location.reload" not in page.split("source.onmessage")[1][:400]


def test_a_static_page_opens_no_event_stream(tmp_path: Path):
    """There is no server behind a rendered file, and a page retrying a dead
    connection forever is a console full of noise on somebody's laptop."""
    from datetime import date

    from openproj.index import build_index
    from openproj.model import load_repo
    from openproj.render import render_static

    entities, config, _ = load_repo(Path("seed"))
    render_static(build_index(entities, config, date(2026, 8, 17)), tmp_path)

    assert "EventSource" not in (tmp_path / "index.html").read_text()


def test_the_graph_explains_its_mode_once_and_beside_the_button(client: TestClient):
    """One mode had two explanations. A second paragraph swapped in under the
    heading on entering edit mode and the standing hint swapped out to make room
    for it, so pressing the button reflowed the canvas under the pointer — and
    the status text beside the button already said the same thing, in the place
    you are looking when you press it.

    The standing hint stays, in both modes: in edit mode you still pan, still
    zoom, still drag a node to move it.
    """
    page = client.get("/graph").text

    assert re.search(r'<p class="hint" id="panhint">', page)
    assert "Double-click a node to open it" in page
    assert "howto" not in page, "the second explanation is gone, not merely hidden"
    assert "PANHINT" not in page, "and the standing one is no longer swapped out"
    # What edit mode adds, said once, in the live region beside the button that
    # turned it on.
    assert "click what must finish first, then what waits for it" in page
    # And the other half of the mode, said in the same breath rather than in a
    # second paragraph: an arrow is a decision the mode can take back.
    assert "or click an arrow to remove it" in page
    assert re.search(r'<button type="button" id="connect">Edit dependencies</button>', page)


def test_the_parent_control_still_holds_the_id(client: TestClient):
    """The facts list reads it as a linked title; the input underneath is what
    gets written, and the file stores an id. Showing the title in the control
    would write the title into the file on the next save."""
    page = client.get(f"/detail/{TASK}").text
    control = re.search(r'<input name="parent"[^>]*value="([^"]*)"', page)

    assert control, "parent must still be editable"
    assert control.group(1).startswith(("proj-", "pitch-", "task-")) or control.group(1) == ""


def test_the_kind_is_read_before_the_name_on_every_page_that_has_one(client: TestClient):
    """What a thing *is* is the first question a page answers.

    The kind was the middle item of a line under the title, between an id and a
    status; it is now the eyebrow above the heading. It is the one fact on this
    page that never changes, which is what makes it the one that belongs there.

    Three headers have to agree, and this is what "agree" means: back link,
    eyebrow, heading, meta line, in that order.
    """
    detail = client.get(f"/detail/{TASK}").text
    kind = detail.index('<p class="eyebrow"><span class="chip kind-')
    assert detail.index('<p class="back">') < kind < detail.index("<h1>")
    meta = detail.index('<p class="meta">')
    assert meta > detail.index("<h1>")
    assert 'class="chip kind-' not in detail[meta:], "and the kind is not said twice"
    # Nor is the status. It was a chip in this line AND a chip forty pixels below
    # it in the facts column, where in edit mode it is also the select that
    # changes it — the same word in the same colour, twice, one of them inert.
    # A field that can be changed is stated where it can be changed.
    assert detail.count('<span class="chip st-') == 1, (
        "the status is said once, in the facts column, where the control for it is"
    )
    facts = detail.index('<dl id="facts">')
    assert facts < detail.index('<span class="chip st-') < detail.index("</dl>", facts)

    # The create form is the same document in another mode, so the picker that
    # decides the kind sits where the kind chip sits.
    new = client.get("/new").text
    picker = new.index('<p class="eyebrow"><label class="kindpick">')
    assert new.index('<p class="back">') < picker < new.index("<h1>")

    # The cycle page has no eyebrow on purpose: its heading is "Cycle 37", so the
    # kind is already the first word of the name and a chip above it would be the
    # restatement the id column's kind chip was. What it does share is the shape.
    cycle = client.get("/cycle/37").text
    assert '<p class="back"><a href="/cycles">' in cycle
    assert cycle.index('<p class="back">') < cycle.index("<h1>") < cycle.index('<p class="meta">')
    assert 'class="eyebrow"' not in cycle


def test_a_betting_cell_saves_only_what_somebody_typed(client: TestClient):
    """The bet table's fields are inputs from the start, so blur is not evidence
    of a decision: the browser restores form values across a reload, autofills,
    and the people picker rewrites a field to add its separator. All three used to
    reach git — one of them emptied an assignees list nobody had touched."""
    page = client.get("/cycle/37").text
    live = re.search(
        r"for \(const input of document\.querySelectorAll\('#bets input\.live'\)\)"
        r".*?\n\}",
        page,
        re.S,
    ).group(0)

    assert "let edited = false;" in live
    assert "input.addEventListener('input', () => { edited = true; });" in live
    assert "!edited" in live, "a blur without an edit must not write"
    assert 'autocomplete="off"' in page


def test_picking_a_suggestion_counts_as_typing(client: TestClient):
    """`choose` sets the value directly, which fires no event — so a name picked
    from the list without a keystroke would look like a field nobody edited."""
    page = client.get("/cycle/37").text
    choose = re.search(r"function choose\(value\) \{.*?\n  \}", page, re.S).group(0)

    assert "dispatchEvent(new Event('input', {bubbles: true}))" in choose


def test_nothing_on_the_cycle_page_is_written_until_save(client: TestClient):
    """A betting table is a conversation — a row gets staffed, argued about and
    restaffed inside a minute. One commit per keystroke turns that into a history
    nobody can read and a plan that is briefly wrong in public between two halves
    of one decision."""
    page = client.get("/cycle/37").text

    assert "const PENDING = new Map();" in page
    for handler in ("input.onblur", "box.onchange"):
        block = re.search(rf"{re.escape(handler)} = .*?\n  \}};", page, re.S).group(0)
        assert "fetch(" not in block, f"{handler} must stage, not write"
    assert re.search(r"SAVE\.onclick = async \(\) => \{\s*if \(await flush\(false\)\)", page)


def test_a_cycle_has_a_box_for_what_came_up_at_the_betting_table(client: TestClient):
    """A betting table produces decisions that are not fields on anything — why a
    pitch was left out, what would make it a bet next time. The record already had
    a body and the page rendered it read-only, so those decisions went to a HackMD
    note nobody linked."""
    page = client.get("/cycle/37").text

    assert '<textarea id="notes"' in page
    # Saved with the setup, in the write the roster already makes — and only when
    # it changed, or every roster save would be a body edit too.
    assert "put(fields, NOTES_DIRTY ? NOTES.value : null)" in page
    assert "async function put(fields, body = null)" in page


def test_work_is_autosaved_so_a_dropped_connection_costs_two_minutes(client: TestClient):
    page = client.get("/cycle/37").text

    assert re.search(
        r"setInterval\(\(\) => \{\s*"
        r"if \(PENDING\.size \|\| ROSTER_DIRTY \|\| NOTES_DIRTY\) flush\(true\);\s*"
        r"\}, 120000\);",
        page,
    )
    # And the browser's own warning, which is the only thing that can stop a tab
    # closing on unsaved work.
    assert "addEventListener('beforeunload'" in page
    assert "event.returnValue = ''" in page


def test_taking_somebody_out_of_a_cycle_takes_two_clicks(client: TestClient):
    """The second click answers a question rather than repeating the gesture that
    asked it. The first one used to remove the row, and the row above it was one
    pixel away from the availability field somebody was typing in."""
    page = client.get("/cycle/37").text
    drop = re.search(r"function dropRow\(button\) \{.*?\n\}", page, re.S).group(0)

    assert "asking.hidden = false;" in drop, "the glyph asks"
    assert "asking.querySelector('.no').onclick" in drop, "and can be told no"
    yes = re.search(
        r"asking\.querySelector\('\.yes'\)\.onclick = \(\) => \{.*?\n  \};", drop, re.S
    ).group(0)
    assert "row.remove();" in yes, "only the answer removes anything"
    assert "row.remove();" not in drop.split("asking.querySelector('.yes')")[0]


def test_a_write_from_the_cycle_page_is_not_reported_back_as_somebody_else_s(
    client: TestClient,
):
    """Every commit comes back down the event stream, including this page's own.
    The shell suppresses the ones it made, but only if it is told a write is in
    the air before it starts — the server announces a commit before it answers
    the request that made it."""
    page = client.get("/cycle/37").text

    assert page.count("dispatchEvent(new Event('openproj:writing'));") == 3, (
        "the cycle record, each entity in the batch, and the asset upload the "
        "shared editor helpers carry onto this page"
    )
    assert page.count("dispatchEvent(new CustomEvent('openproj:wrote'") == 3
    assert "window.SHOWING = ['cycle-' + NUMBER]" in page, (
        "so a write that lands here reads as landing here"
    )


def test_capacity_moves_while_the_rate_is_being_typed(client: TestClient):
    """Left to the next page load, the number somebody is setting is invisible at
    the moment they are setting it — which is most of the moment that matters.

    A rate only. The other half of `rate × build weeks` is working days between
    two meetings with the holidays taken out, and this page does not have the
    holidays — so a date change says the column is stale instead of showing a
    number computed by a rule that is only nearly the server's."""
    page = client.get("/cycle/37").text

    assert "function recount()" in page
    assert re.search(r"if \(event\.target\.matches\('input\.rate'\)\) recount\(\);", page)
    assert re.search(r"const BUILD_WEEKS = [0-9.]+;", page), "the server's own answer"
    assert "#setup input[type=date]" in page and 'getElementById(\'stale\')' in page


def test_a_new_cycle_starts_from_the_last_one_s_roster(client: TestClient, repo_path: Path):
    """A team changes slowly and availability changes every cycle, so the people
    who worked the last one are a starting point to correct — which beats
    retyping fifteen names to change three of them."""
    from test_web import git_head

    client.put(
        "/api/cycle/50",
        json={
            "base_commit": git_head(repo_path),
            "fields": {
                "starts_on": "2027-06-07",
                "build_weeks": 4,
                "availability": {"cy": 0.5, "ann": 1.0},
            },
            "body": None,
        },
    )
    page = client.get("/cycles").text
    carried = re.search(r"const ROSTER = (\{.*?\});", page).group(1)

    assert json.loads(carried) == {"cy": 0.5, "ann": 1.0}
    # The roster is carried, and the form no longer says so. It said "2 people
    # carried from cycle 50" beside a button, which is a fact about a page you
    # are about to leave: the roster is on the new cycle's own page, editable,
    # the moment the button is pressed. The behaviour asserted above is what
    # matters and it is unchanged.
    assert "people carried from cycle" not in page


def test_an_image_can_be_pasted_or_dropped_into_the_body(client: TestClient):
    """This is a handler on the textarea, not an editor feature. CodeMirror would
    not have brought it — paste and drop are DOM events, and a plain textarea
    receives them exactly the same way."""
    for path in (f"/detail/{TASK}", "/new"):
        page = client.get(path).text
        assert "function attachUploads(surface, status)" in page, path
        assert "attachUploads(SURFACE, document.getElementById('upload'));" in page, path
        assert "addEventListener('paste'" in page, path
        assert "addEventListener('drop'" in page, path
        assert "fetch('/api/asset'" in page, path


def test_a_slow_upload_holds_its_place_in_the_text(client: TestClient):
    """Inserted before the request, replaced after. Without it a slow upload looks
    like nothing happened, and whatever gets typed meanwhile lands in the spot the
    image was going to."""
    page = client.get(f"/detail/{TASK}").text
    send = re.search(r"async function send\(file\) \{.*?\n  \}", page, re.S).group(0)

    assert "const token = `![uploading" in send
    assert "insert(token)" in send
    assert "surface.splice(at, at + token.length," in send
    assert "response.ok ? `![${alt}](${answer.path})` : ''" in send


def test_every_control_on_the_form_has_a_name(page: str):
    """A `<dt>` beside a `<dd>` is a caption to somebody reading the page and two
    unrelated blocks of text to everything else, so before this not one control
    on the detail form had a name at all.

    The label carries the id of the control it names, and the ids are prefixed
    with the entity's — the static export puts every entity in one file, and
    `owner` alone would be the same id sixteen times over.
    """
    from openproj.render import LABELS

    facts = re.search(r'<dl id="facts">(.*?)</dl>', page, re.S).group(1)
    named = dict(re.findall(r'<label for="([^"]+)">([^<]+)</label>', facts))

    assert named, "the labels are the whole of the fix"
    for control_id, word in named.items():
        assert control_id.startswith(f"{TASK}-"), control_id
        assert re.search(rf'<(?:input|select|textarea)[^>]*\bid="{control_id}"', page), word
    for field in ("status", "owner", "assignees", "reviewers", "priority", "cycle"):
        assert named[f"{TASK}-{field}"] == LABELS[field], field

    # The two boxes with no fact row to hang a label on: the title is the page's
    # heading and the body is the document.
    assert re.search(r'<input name="title"[^>]*aria-label="Title"', page)
    assert re.search(r'<textarea name="body"[^>]*aria-label="Shaping document"', page, re.S)


def test_a_derived_row_carries_no_label_because_it_carries_no_control(page: str):
    """`for` pointing at nothing is a name the reader is told about and cannot
    reach, which is worse than the caption it replaced."""
    facts = re.search(r'<dl id="facts">(.*?)</dl>', page, re.S).group(1)
    derived = re.findall(r'<dt class="[^"]*derived[^"]*">(.*?)</dt>', facts, re.S)

    assert derived, "the page draws no derived fact"
    for row in derived:
        assert "<label" not in row, row


def test_the_detail_page_announces_a_save_it_only_used_to_draw(page: str):
    """`#state` was written to directly, and on every page that has no `#state` —
    which is every page you can only read — the same message went nowhere."""
    body = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", page, re.S))

    assert "STATE.textContent" not in body, "the direct write this replaced"
    for message in ("'saving…'", "'not saved'", "'nothing changed'"):
        assert f"announce({message})" in body, message
    # The restored draft says two different things — one of them "somebody else
    # has changed this since it was written" — so it is announced as a chosen
    # value rather than as a literal. Both spellings are on the page, and both
    # go through `announce` rather than into a region this page happens to have.
    restored = re.search(r"announce\(moved\s*\n\s*\?\s*('[^']+')\s*\n\s*:\s*('[^']+')\)", body)
    assert restored, "the restored draft no longer announces both of its messages"
    assert "somebody else has changed this" in restored.group(1)
    assert restored.group(2) == "'unsaved draft restored'"
    # Through the shell's `refusal`, which knows that a 409 carries the report
    # rather than a `detail` — the key this line used to read on its own.
    assert "announce(refusal(answer, response.status))" in body
    # And the region it lands in exists whether or not this page drew one.
    assert '<p id="announce" class="sr-only" role="status" aria-live="polite">' in page
    assert '<span id="state" role="status"></span>' in page


def test_every_answer_a_write_gives_lands_in_a_live_region(client: TestClient, page: str):
    """A refusal, a conflict and an upload are all answers to a write, and each of
    them was a box that appeared with nothing said about it.

    They keep their own places on the page — a conflict belongs beside the editor
    it refused, not in a status bar — so each one is a region of its own rather
    than being routed through `announce`.
    """
    new = client.get("/new?kind=pitch").text

    assert '<div id="conflict" role="status" aria-live="polite" hidden>' in page
    assert '<span class="hint" id="upload" role="status" aria-live="polite">' in page
    assert '<span class="hint" id="upload" role="status" aria-live="polite">' in new
    assert '<ul id="problems" class="problems" role="status" aria-live="polite" hidden>' in new
    # And the table's, which writes the conflict into the box and returns.
    assert '<div id="row-conflict" role="status" aria-live="polite" hidden>' in client.get("/").text


def test_a_refusal_names_the_field_the_way_the_form_labels_it(client: TestClient):
    """The form's own check already refused in the words on the page — and said so
    in a comment — while the server's refusal ten lines below printed `p.field`.

    So one rejected save read "still needed at status Ready: Appetite (weeks)" and
    the next read "person_weeks: a ready pitch needs an appetite", from the same
    `<ul>`, about the same box. Both go through `labelOf` now.

    The list is built from text nodes rather than interpolated into `innerHTML`,
    because `answer.detail` quotes back a key the request supplied: a 422 is the
    server repeating the client's own string, and repeating it as markup is how a
    refusal becomes an element.
    """
    new = client.get("/new?kind=pitch").text

    assert "function refusals(answer, status) {" in new
    assert "return control ? `${labelOf(control)}: ${problem.message}` : problem.message;" in new
    assert "if (!problems.length) return [refusal(answer, status)];" in new
    assert "CSS.escape(problem.field)" in new, "the field arrives over the wire"
    # Built, not interpolated.
    assert "item.textContent = text;" in new
    assert "PROBLEMS.replaceChildren(" in new
    assert "PROBLEMS.innerHTML = (answer.problems" not in new, "the interpolation this replaced"
    assert "${p.field}" not in new, "the identifier this replaced"


# --------------------------------------------------------------------------- #
# The unsaved draft
# --------------------------------------------------------------------------- #


def test_a_restored_draft_is_saved_against_the_commit_it_was_drafted_against(
    client: TestClient, repo_path: Path
):
    """A draft is text plus the commit it was written on top of, or it is a way
    to revert a colleague without being told.

    The draft used to be bare text. Restoring one into a page rendered an hour
    later paired hour-old text with today's `base_commit`, so `store.write`
    compared the two things that agreed, found nothing to refuse, and committed
    a body that silently threw away whoever had saved in between: no 409, no
    conflict report, their paragraph simply gone.

    Driven end to end and in the medium it happens in — the page's own script
    stores the draft, the page's own script restores it and builds the PATCH,
    and the request that comes out of it is answered by the real server rather
    than by a scripted reply. Nothing here is asserted about a string in a file.
    """
    from test_injection import run_js

    first = head(client)
    drafted_on = client.get(f"/detail/{TASK}").text

    # Ann types a paragraph and closes the tab without saving.
    typed = "Rewritten from the top, by ann.\n"
    typing = run_js(
        drafted_on,
        f"(() => {{ BODY.value = {json.dumps(typed)};"
        "   BODY.dispatchEvent(new Event('input')); return BODY.value; })()",
        page=True,
    )
    key = f"openproj:draft:2:{TASK}"
    assert key in typing["stored"], (
        f"a draft was stored that does not record the commit it was written on "
        f"top of: {typing['stored']}"
    )
    draft = json.loads(typing["stored"][key])
    assert draft == {"base": first, "text": typed}

    # Bo rewrites the same paragraph and saves. (One client, because what a
    # compare-and-swap compares is commits, not logins.)
    assert save(client, TASK, {}, body="A different paragraph, by bo.\n").status_code == 200
    second = head(client)

    # Ann opens the page again. It is rendered at Bo's commit; her draft is not.
    reopened = client.get(f"/detail/{TASK}").text
    assert f'name="base_commit" value="{second}"' in reopened
    restoring = run_js(
        reopened,
        "save()",
        page=True,
        storage={key: json.dumps(draft)},
        # Enough of an answer for the page to take its 409 branch and stop; the
        # request it made on the way is what this test carries to the server.
        replies=[{"status": 409, "json": {"conflict": "scripted, so that save() returns"}}],
    )
    assert not restoring["errors"], restoring["errors"]
    sent = [call for call in restoring["calls"] if call["method"] == "PATCH"]
    assert len(sent) == 1, restoring["calls"]
    written = json.loads(sent[0]["body"])
    assert written["base_commit"] == first, (
        "the restored draft was saved against the commit the page was rendered at, "
        "which is the commit its text was never written against"
    )
    assert written["body"] == typed

    # And the real server refuses it, in the words every other write path shows.
    refused = client.patch(f"/api/entity/{TASK}", json=written)
    assert refused.status_code == 409
    report = refused.json()["conflict"]
    assert PATH in report and "somebody changed this before you" in report
    assert "by bo" in report and "by ann" in report, report
    assert git_head(repo_path) == second, "refused, and yet something was committed"

    # The defect itself, one line, so this test cannot pass for the wrong reason:
    # the same body against the page's fresh commit is taken without a murmur and
    # Bo's paragraph is gone from the file.
    silent = client.patch(f"/api/entity/{TASK}", json={**written, "base_commit": second})
    assert silent.status_code == 200
    assert "by bo" not in file_at(repo_path, git_head(repo_path), PATH)


def test_cancelling_a_restored_draft_keeps_the_commit_it_was_written_against(
    client: TestClient,
):
    """Cancel drops the stored draft, not the base it arrived with.

    The text is still in the textarea after a cancel — Cancel hides the editor,
    it does not put back what was there — so the page is still holding work
    written against an older commit. Letting `base_commit` spring forward when
    the storage entry goes would be the same silent overwrite by another route,
    so this drives the button rather than reading the handler.
    """
    from test_injection import run_js

    first = head(client)
    save(client, TASK, {}, body="Somebody else's paragraph.\n")
    second = head(client)
    assert first != second

    reopened = client.get(f"/detail/{TASK}").text
    key = f"openproj:draft:2:{TASK}"
    draft = {"base": first, "text": "Half a paragraph, left in the box.\n"}
    after = run_js(
        reopened,
        "(() => { document.getElementById('toggle')"
        "   .dispatchEvent(new Event('click'));"
        "  return [document.querySelector('[name=base_commit]').value,"
        "          document.querySelector('[name=body]').value]; })()",
        page=True,
        storage={key: json.dumps(draft)},
    )
    base, body = after["value"]

    assert key not in after["stored"], "cancelling left the draft in storage"
    assert body == draft["text"], "the text a cancel leaves in the box"
    assert base == first, "cancelling put the page's own commit back under older text"
# --- writing in the body ----------------------------------------------------


# The adapter's own boundary, read off the shipped page rather than off a module
# constant — an adapter that moved into a new constant would otherwise be
# invisible to every guard below.
_SURFACE_OPENS = "// --- the textarea, as a surface ---"
_SURFACE_CLOSES = "// --- end of the textarea surface ---"


def _surface_source(page: str) -> str:
    """The one region of any of these pages that knows the box is a textarea."""
    opens = page.index(_SURFACE_OPENS)
    closes = page.index(_SURFACE_CLOSES, opens)
    return page[opens:closes]


def _coedit_source(page: str) -> str:
    """The room's script, as it ships."""
    found = re.search(r"const COEDIT = \(\(\) => \{.*?\n\}\)\(\);", page, re.S)
    assert found, "the room's script is not on the page under the name this looks for"
    return found.group(0)


# Every read of the document that used to be a `.value` on the box, by the name
# it goes by in the block it lives in. The list is here rather than in prose
# because S6.2 asks for it to be enumerable BEFORE anything is allowed to stop
# writing to the box: if one of these has no replacement, the sweep was partial
# and the boundary is a boundary with a hole in it.
_THROUGH_THE_SURFACE = (
    "let ORIGINAL_BODY = SURFACE.text();",                       # the baseline
    "const count = Object.keys(fields).length + (SURFACE.text()",  # dirty
    "const body = SURFACE.text() === ORIGINAL_BODY ? null : SURFACE.text();",  # save
    "text: SURFACE.text()}))",                                   # the draft writer
    "draft.text !== SURFACE.text()",                             # the draft restorer
    "SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, draft.text))",
    "body: SURFACE.text(), title: TITLED.value",                 # the preview
    "SURFACE.lineCoords()",                                      # the scroll sync
    "const now = SURFACE.text(), was = text.toString();",        # typed
    "const want = text.toString(), was = SURFACE.text();",       # reflect
    "SURFACE.coordsAt(",                                         # drawSeats
    "const at = SURFACE.caret().from;",                          # sit
    "const mine = SURFACE.text() !== ORIGINAL_BODY;",            # welcomed
    "const draft = SURFACE.text();",                             # welcomed's report
    "const count = surface.text().split",                        # attachGutter
    "const text = surface.text();",                              # attachStatus, applyMark
    "surface.text().indexOf(token)",                             # attachUploads
)


def test_the_body_is_read_through_one_place_and_nothing_else(client: TestClient):
    """S6.2. `BODY.value` may appear in exactly one region of the page.

    The adapter is worth nothing as a boundary if anything can still reach past
    it, and "nothing reaches past it" is a claim about the whole document rather
    than about the function somebody happened to be editing. So this reads the
    shipped page, cuts out the surface's own source, and asserts that no read or
    write of the box's text or selection survives anywhere else — on all four
    pages that inline an editing surface, because the block is shared and the
    mount sites are not.

    The `<input>`s are deliberately not in scope: the suggestion combobox calls
    `setSelectionRange` on a text field, which is a different control with no
    document in it and no room behind it. The names below are the body's.
    """
    for path in (f"/detail/{TASK}", "/new"):
        page = client.get(path).text
        surface = _surface_source(page)
        assert "function textareaSurface(area)" in surface, path
        # Every one of the seven, by name, in the one place they are implemented.
        for method in ("text:", "caret:", "setCaret(", "splice(", "onInput(",
                       "onCaret(", "coordsAt("):
            assert method in surface, f"{method} is not in the surface on {path}"
        assert "let applying = false;" in surface, path

        rest = page.replace(surface, "")
        for reach in ("BODY.value", "BODY.selectionStart", "BODY.selectionEnd",
                      "BODY.setSelectionRange", "area.value", "area.selectionStart",
                      "area.selectionEnd", "area.setSelectionRange"):
            assert reach not in rest, (
                f"`{reach}` on {path} reads the document from outside the one place "
                "that is allowed to. Every other surface fires its change event for "
                "its own edits and a person's alike, and a read that dodges the "
                "boundary is the one that will not be found when that matters."
            )

    # And the seventeen call sites, enumerated. A sweep that missed one is a
    # sweep that left a `.value` behind, and the assertion above would catch
    # that; this one catches the other half — a call site quietly deleted
    # instead of converted.
    page = client.get(f"/detail/{TASK}").text
    for site in _THROUGH_THE_SURFACE:
        assert site in page, f"this call site no longer goes through the surface: {site}"

    # `reflect`, read as source, because the two things that matter about it are
    # invisible to a textarea and therefore to every behavioural test in the
    # suite. Both ends of the splice have to be bounded — `to` is
    # `was.length - tail` and not `was.length`, or the write is a whole-document
    # replacement wearing a splice's signature — and it has to be inside `apply`,
    # which is what a surface that fires its own change events will read.
    reflect = re.search(r"function reflect\(\) \{.*?\n  \}", page, re.S)
    assert reflect, "the room no longer has a `reflect` under that name"
    assert "was.length - tail" in reflect.group(0), (
        "reflect's splice is not bounded at the tail, so it replaces everything "
        "from the first differing character to the end of the document"
    )
    assert "SURFACE.apply(" in reflect.group(0), (
        "reflect writes the box without saying it is the page writing"
    )


def test_no_script_ever_assigns_a_textarea_its_value(client: TestClient):
    """`textarea.value = …` wipes the browser's native undo stack. Paste a diagram
    into a four-hundred-line pitch, press ctrl-Z, and the last ten minutes are
    gone. Every programmatic edit goes through `replaceRange`, which uses
    `execCommand('insertText')` — deprecated, and still the only API in any
    shipping browser that edits a textarea as though a person had typed.

    **Extended to `_COEDIT`, which it deliberately did not look at.** The audit
    named that omission as a live defect: `reflect()` assigned `.value` on every
    remote update while the comment forty lines above said what that costs, and
    this test's scope — `replaceRange`, `FORMATS` and `attachUploads` — was
    exactly why nobody noticed. The room's script now writes through the
    surface's `splice` like everything else, so it can be held to the same rule.
    It is still not a fix for the undo stack: `splice` under `apply` assigns
    `.value` inside the implementation, which is the one place allowed to, and
    S4's `Y.UndoManager` is what answers it.
    """
    page = client.get(f"/detail/{TASK}").text
    helpers = _surface_source(page)
    # Everything that edits the body while somebody is working in it — plus, now,
    # the room, which is the caller that had a `.value` assignment in it all
    # along. A draft restored at page load replaces the whole field rather than
    # part of it, and it says so through `splice(0, length, …)` inside `apply`
    # rather than by writing to the box behind the boundary's back.
    editing = re.search(r"const FORMATS = \[.*?\n\}\n", page, re.S).group(0)
    editing += re.search(r"function attachUploads.*?\n\}\n", page, re.S).group(0)
    editing += _coedit_source(page)

    assert "document.execCommand('insertText', false, text)" in helpers
    assert "area.value =" not in editing, "only the fallback inside replaceRange may assign"
    assert "BODY.value =" not in editing, "and the room may not assign either"
    assert "surface.splice(" in editing or "SURFACE.splice(" in editing, (
        "and a splice through the surface is what the editing code calls"
    )


def test_the_toolbar_is_the_one_in_the_screenshot_and_that_overrules_a_count(
    client: TestClient,
):
    """`docs/hackmd-observed.md` records the toolbar off the pixels of a real
    HackMD note: four groups, drawn with separators, in a fixed order. jcanton
    asked for "the buttons along the top of the editor" and pointed at that.

    **This overrules a measurement, and the measurement was not wrong.** The
    seven buttons this replaces were counted from the seed and migrated corpora —
    485 lines with an inline code span, 161 a bullet, 124 a heading, 83 bold,
    against 8 markdown links — and the link button was cut on that count,
    correctly, because you do not add a button before somebody asks for one.
    Somebody has now asked. The count is overruled, not refuted, and this test
    holds the toolbar to the shot rather than to the corpus.

    Three deliberate departures, each of which this test pins: two code buttons,
    because a backtick is a dead key on a Swiss-German layout and a fence is
    three in a row; no comment button, which is a HackMD collaboration feature
    with nothing behind it here; and no undo and redo yet, because they are the
    first two in the shot and they belong with the `reflect()` defect that makes
    them necessary.
    """
    page = client.get(f"/detail/{TASK}").text
    marks = re.search(r"const FORMATS = \[(.*?)\n\];", page, re.S).group(1)
    # Comment lines out first, then one chunk per entry. A bare `\{[^{}]*\}`
    # finds the code-block button's own label — `{ }` — and reports it as a
    # fifteenth mark with no title on it.
    body = "\n".join(ln for ln in marks.splitlines() if not ln.strip().startswith("//"))
    entries = [chunk for chunk in re.split(r"\n(?=  \{)", body) if "title:" in chunk]
    named = [re.search(r"title: '([^']*)'", entry).group(1).split("  ")[0] for entry in entries]

    assert named == [
        "Bold", "Italic", "Strikethrough", "Heading",
        "Code", "Code block", "Quote", "Bullet list", "Numbered list", "Check list",
        "Link", "Image", "Table", "Horizontal rule",
    ]
    # Where the rules fall, and not merely how many there are: a separator in the
    # wrong place groups the buttons into a claim about them that is false.
    assert [i for i, entry in enumerate(entries) if "group: true" in entry] == [4, 10]
    assert "comment" not in marks.lower(), "a collaboration feature with nothing behind it"
    assert "undo" not in marks.lower(), "history arrives with the UndoManager that answers it"
    # Every shifted shortcut is bound to a letter. The handler matches on
    # `event.key`, and shift-8 on a US layout is `*` and not `8` — so ⌘⇧8 beside
    # the bullet's ⌘8 would have been a shortcut that could never once fire.
    for entry in entries:
        if "shift: true" in entry:
            assert re.search(r"key: '[a-z]'", entry), entry


def test_a_fence_takes_whole_lines_of_its_own(client: TestClient):
    """A fence only opens a block if nothing shares its line, so wrapping a
    selection in place would produce three paragraphs of literal backticks."""
    page = client.get(f"/detail/{TASK}").text
    fence = re.search(r"if \(mark\.fence\) \{.*?\n    return;\n  \}", page, re.S).group(0)

    assert "const [from, to] = lineRange(surface);" in fence
    assert "'```\\n' + chosen + '\\n```'" in fence
    assert "surface.setCaret(from + 3)" in fence, "the caret lands on the language"
    assert "fenced" in fence, "and pressing it again unwraps"


def test_a_list_continues_and_an_empty_item_ends_it(client: TestClient):
    """The one thing everybody misses from HackMD inside a minute. 161 bullet
    lines across the two corpora."""
    page = client.get(f"/detail/{TASK}").text
    handler = re.search(r"area\.addEventListener\('keydown'.*?\n  \}\);", page, re.S).group(0)

    assert "if (event.key !== 'Enter' || event.shiftKey) return;" in handler
    assert "LIST_ITEM.exec(line)" in handler
    assert "if (!text.trim())" in handler, "an empty item ends the list"
    assert "parseInt(bullet, 10) + 1" in handler, "a numbered list counts on"


def test_a_toolbar_button_keeps_the_selection_it_acts_on(client: TestClient):
    """`click` runs after the textarea has lost focus, and with it the selection
    the mark is supposed to wrap."""
    page = client.get(f"/detail/{TASK}").text

    bound = "button.onmousedown = event => { event.preventDefault(); applyMark(surface, mark); };"
    assert bound in page
    # And a click as well, which is the only thing Enter and Space produce.
    # `detail === 0` is how a click synthesised from a key is told from one a
    # pointer made, so the two bindings cannot both fire for one press.
    keyed = "button.onclick = event => { if (event.detail === 0) applyMark(surface, mark); };"
    assert keyed in page
    assert "event.detail" in page


def test_the_create_form_does_not_echo_the_dates_it_is_asking_for(page: str):
    """Every `input[type=date]` gets an ISO echo beside it, because a date box is
    drawn in the reader's locale and the same stored 2026-09-01 reads as
    01/09/2026 here and 09/01/2026 one desk over.

    On the create form that echo has nothing to disambiguate against — those two
    boxes are the only dates on screen — so it read as a second, differently
    formatted copy of a value somebody is in the middle of typing. Two dates,
    four numbers.
    """
    assert "if (box.closest('#create')) continue;" in page
    # And the echo itself is still there for every other date box on the page.
    assert "echo.className = box.classList.contains('field') ? 'iso field' : 'iso'" in page


def test_the_goal_is_above_the_bet_and_the_notes_are_below_it(client: TestClient, repo_path: Path):
    """There is no arrangement of one box that is both above the table where the
    room is looking and below it where the room is writing, which is why the goal
    became a field and the notes stayed the body."""
    from test_web import git_head

    client.put(
        "/api/cycle/51",
        json={
            "base_commit": git_head(repo_path),
            "fields": {"starts_on": "2027-06-07", "reviews_on": "2027-07-05",
                       "goal": "Ship the dycore port"},
            "body": "Turbulence was left out: no reviewer free.\n",
        },
    )
    page = client.get("/cycle/51").text

    goal, bet, notes = (page.index(f"<h2>{h}</h2>") for h in ("Goal", "The bet", "Notes"))
    assert goal < bet < notes
    assert 'id="goal"' in page and 'id="notes"' in page
    assert "Ship the dycore port" in page
    assert "Turbulence was left out" in page
    # An untouched box must not be sent: `patch_text` leaves a field alone only
    # if it is absent, so a roster save would otherwise rewrite the goal too.
    assert "if (GOAL_DIRTY) fields.goal = GOAL.value.trim();" in page


def test_starting_a_cycle_asks_for_dates_and_nothing_else(client: TestClient):
    """The goal box was on this form for one round. It belongs on the cycle's own
    page, above the betting table it is about — this form's whole job is to bring
    a record into existence, and two places to write one field is one too many."""
    page = client.get("/cycles").text
    create = page[page.index('<section id="create">'):page.index("</section>")]

    assert 'id="number"' in create and 'id="starts"' in create and 'id="reviews"' in create
    assert 'id="start"' in create
    assert "<textarea" not in create, "no goal box here any more"


# --- Tab, and the way back out of the box -----------------------------------

# Asked of Chrome and not of `tests/js/drive.js`, on the rule in `AGENTS.md`:
# the shim is a DOM, not a browser, and it has misled three rounds of this work.
# Everything below is selection, key handling and the browser's own undo stack,
# which is exactly the class of claim it cannot answer — `execCommand('insertText')`
# is a browser API and the shim has no history for it to keep.
_TABBING = """
const area = document.querySelector('textarea[name=body]');
document.getElementById('toggle').click();

const press = (key, shift) => {
  area.focus();
  return area.dispatchEvent(new KeyboardEvent(
    'keydown', {key, shiftKey: !!shift, bubbles: true, cancelable: true}));
};
const set = (text, from, to) => {
  area.value = text;
  area.dispatchEvent(new Event('input', {bubbles: true}));
  area.focus();
  area.setSelectionRange(from, to);
};

// A selection across two lines: both lines move, and both come back.
set('alpha\\nbeta\\n', 0, 10);
const swallowed = !press('Tab');
const indented = area.value;
const still = [area.selectionStart, area.selectionEnd];
press('Tab', true);
const back = area.value;

// A caret in the middle of a sentence is the other gesture: spaces to the next
// stop, and nothing else on the line moves. An odd column takes one space and an
// even one takes two, which is what "stop" means and what a fixed two would not.
set('alpha beta', 3, 3);
press('Tab');
const odd = area.value;
set('alpha beta', 6, 6);
press('Tab');
const even = area.value;

// A caret inside a bullet's marker nests the item under the one above it.
set('- one\\n- two\\n', 8, 8);
press('Tab');
const nested = area.value;

// One undo press gives the whole gesture back, which is the entire reason every
// write goes through `execCommand` rather than through `area.value =`.
set('alpha\\nbeta\\n', 0, 10);
press('Tab');
const wrote = area.value;
document.execCommand('undo');
const undone = area.value;

// And Escape arms exactly one Tab, out loud, so the field can still be left by
// keyboard.
set('alpha', 0, 0);
press('Escape');
const said = document.getElementById('state').textContent;
const passed = press('Tab');
const untouched = area.value;
// Spent: the press after it indents again.
press('Tab');
const spent = area.value;

return {swallowed, indented, still, back, odd, even, nested, wrote, undone,
        said, passed, untouched, spent};
"""


def test_tab_indents_the_lines_the_selection_touches_and_escape_then_tab_leaves_the_field(
    client: TestClient, tmp_path: Path
):
    """Tab is the fifth ask, and taking Tab away is how an editor traps somebody
    who has no pointer. Both halves are here because neither is safe alone: an
    indent that swallows Tab with no way out is worse than no indent, and an
    escape hatch nobody is told about is not one."""
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "tab.html", 1200, _TABBING
    )

    assert got["swallowed"], "Tab was left to the browser and moved focus instead"
    assert got["indented"] == "  alpha\n  beta\n"
    assert got["still"] == [2, 14], "the selection no longer covers the words it moved"
    assert got["back"] == "alpha\nbeta\n", "Shift-Tab did not take the indent back"
    assert got["odd"] == "alp ha beta", "a caret in a sentence types to the next stop"
    assert got["even"] == "alpha   beta", "and a whole indent when it is already on one"
    assert got["nested"] == "- one\n  - two\n", "Tab in a bullet did not nest the item"
    assert got["wrote"] == "  alpha\n  beta\n"
    assert got["undone"] == "alpha\nbeta\n", "the whole indent is not one undo step"
    assert "Tab" in got["said"], "swallowing Tab was not announced"
    assert got["passed"], "Escape did not give the next Tab back to the browser"
    assert got["untouched"] == "alpha", "the armed Tab indented instead of leaving"
    assert got["spent"] == "  alpha", "the hatch stayed open for a second Tab"


# The four marks the renderer learnt in the same commit, and the two pastes.
# Driven in Chrome rather than read out of the page, because every one of these
# is a claim about a selection: which characters were chosen when the button was
# pressed, and which are chosen afterwards.
_MARKING = """
const area = document.querySelector('textarea[name=body]');
document.getElementById('toggle').click();
const mark = name => FORMATS.find(m => m.title.split('  ')[0] === name);
const set = (text, from, to) => {
  area.value = text;
  area.focus();
  area.setSelectionRange(from, to);
};
const apply = (name, text, from, to) => {
  set(text, from, to);
  applyMark(SURFACE, mark(name));
  return area.value;
};

const struck = apply('Strikethrough', 'alpha beta', 0, 5);
const numbered = apply('Numbered list', 'one\\ntwo\\nthree', 0, 13);
const unnumbered = apply('Numbered list', '1. one\\n2. two\\n3. three', 0, 22);
const linkedUp = apply('Link', 'read the notes', 5, 14);
const urlChosen = area.value.slice(area.selectionStart, area.selectionEnd);
const bareLink = apply('Link', '', 0, 0);
const wordChosen = area.value.slice(area.selectionStart, area.selectionEnd);
const checked = apply('Check list', 'one\\ntwo', 0, 7);
// On lines that are already bullets the box goes onto the bullet that is there.
const boxed = apply('Check list', '- one\\n- two', 0, 11);
const unboxed = apply('Check list', '- [ ] one\\n- [ ] two', 0, 19);
// A block goes in on lines of its own, or `---` under a line of text is a
// heading and a table does not interrupt a paragraph at all.
const nestedOff = apply('Numbered list', '  1. one\\n  2. two', 0, 17);
const nestedOn = apply('Numbered list', '  one\\n  two', 0, 11);
// A bracket inside the label ends the label, so `[a]b](url)` renders as literal
// text with no link in it and no sign that anything failed.
const bracketed = apply('Link', 'a]b', 0, 3);
const table = apply('Table', 'alpha', 5, 5);
const picked = area.value.slice(area.selectionStart, area.selectionEnd);
const rule = apply('Horizontal rule', 'alpha', 5, 5);

// The two marks that leave a caret and no selection, which is the one-argument
// form of `setCaret` and its only two callers. Both are a POSITION, not a
// range, and a range with a missing end is a caret at the top of the document.
const fenced = apply('Code block', 'alpha beta', 0, 10);
const afterFence = [area.selectionStart, area.selectionEnd];
const emptyBold = apply('Bold', 'alpha', 5, 5);
const insideBold = [area.selectionStart, area.selectionEnd];

// A paste is what the browser hands over, so it is given one.
const paste = text => {
  const data = new DataTransfer();
  data.setData('text/plain', text);
  area.focus();
  const event = new ClipboardEvent(
    'paste', {clipboardData: data, bubbles: true, cancelable: true});
  area.dispatchEvent(event);
  return {text: area.value, taken: event.defaultPrevented};
};
set('read the notes', 5, 14);
const linked = paste('https://example.org/a?b=c');
set('', 0, 0);
const tabled = paste('a\\tb\\nc\\td\\n');
// Everything else is the browser's, pasted as the text it is.
set('one', 3, 3);
const plain = paste(' and two');
set('read the notes', 5, 14);
const bare = paste('a sentence');

// The image button writes no markdown at all: `_image` refuses anything that is
// not an asset this repository stored, so a typed `![](https://…)` draws a link
// and not a picture. It opens the same upload path paste and drop use, and this
// catches the element that path builds.
let opened = null;
const built = document.createElement.bind(document);
document.createElement = tag => {
  const made = built(tag);
  if (tag === 'input') opened = made;
  return made;
};
const button = title => [...document.querySelectorAll('#marks button')]
  .find(b => b.title.split('  ')[0] === title);
button('Image').click();
document.createElement = built;
const picker = opened ? {type: opened.type, accept: opened.accept} : null;
const wrote = area.value;

// The image entry is a fifth shape and `applyMark`'s tail was "anything I do not
// recognise is a wrap", which reads `mark.wrap.length`. Nothing reaches it today
// — the button is bound to click and the shortcut matcher cannot match a mark
// with no key — so this is the trap the next mark falls into rather than a live
// bug, and it is cheaper to shut than to rediscover. Shut by the tail asking
// whether it is the shape it can do, and saying so when it is not: a guard
// naming this one entry would close the case that exists and leave the trap set
// for the sixth.
set('untouched', 0, 0);
document.getElementById('state').textContent = '';
let threw = null;
try { applyMark(SURFACE, mark('Image')); } catch (error) { threw = String(error); }
const unwritable = {said: document.getElementById('state').textContent, wrote: area.value};

// The keyboard. Enter and Space on a focused button produce a click and no
// mousedown at all, so a bar bound only to mousedown is a row of focus stops
// that do nothing.
set('alpha beta', 0, 5);
button('Bold').focus();
button('Bold').dispatchEvent(
  new MouseEvent('click', {bubbles: true, cancelable: true, detail: 0}));
const keyed = area.value;
// And a pointer press still applies it exactly once, which is what `detail` is
// being read for.
set('alpha beta', 0, 5);
button('Bold').dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
button('Bold').dispatchEvent(
  new MouseEvent('click', {bubbles: true, cancelable: true, detail: 1}));
const pressed = area.value;

// A file the dialog offered that is not an image. `accept="image/*"` filters the
// dialog and does not bind it — macOS Chrome's format popup still offers All
// Files — so this is the branch that decides not to act, and it has to say so.
const chosen = new DataTransfer();
chosen.items.add(new File(['x'], 'appetite.pdf', {type: 'application/pdf'}));
opened.files = chosen.files;
opened.dispatchEvent(new Event('change'));
const refused = document.getElementById('upload').textContent;

// One row, and where the rows are is the only thing that can tell. Every count
// and every `nextElementSibling` below is identical whether the bar is drawn on
// one row or on four.
//
// Measured with the longest thing that shares the line actually on it: an upload
// says `assets/<sha256>.png — already in the plan`, which is 97 characters, and
// the toolbar has to keep its row while a sentence that long is beside it.
document.getElementById('upload').textContent =
  `assets/${'0'.repeat(64)}.png — already in the plan`;
const bar = {
  buttons: document.querySelectorAll('#marks button').length,
  rules: document.querySelectorAll('#marks .sep').length,
  // Where the rules fall in the drawn bar, not only how many there are.
  before: [...document.querySelectorAll('#marks .sep')]
    .map(rule => rule.nextElementSibling.title.split('  ')[0]),
  rows: [...new Set([...document.getElementById('marks').children]
    .map(one => Math.round(one.getBoundingClientRect().y)))].length,
};

return {fenced, afterFence, emptyBold, insideBold,
        struck, numbered, unnumbered, nestedOff, nestedOn, linkedUp, urlChosen, bareLink,
        wordChosen, bracketed, checked, boxed, unboxed, table, picked, rule,
        linked, tabled, plain, bare, picker, wrote, threw, unwritable,
        keyed, pressed, refused, bar};
"""


@pytest.mark.parametrize("width", [1200, 1000])
def test_the_new_marks_write_blocks_and_a_pasted_url_becomes_the_link_it_is(
    client: TestClient, tmp_path: Path, width: int
):
    """A button that emits syntax the committed renderer does not honour is worse
    than no button, which is why these arrived in the commit that taught `_MD`
    strikethrough and task lists — and why a table and a rule are a fourth shape
    in `applyMark` rather than a wrap with newlines in it."""
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "marks.html", width, _MARKING
    )

    assert got["struck"] == "~~alpha~~ beta"
    assert got["numbered"] == "1. one\n2. two\n3. three", "a list of five `1.`s reads as a mistake"
    assert got["unnumbered"] == "one\ntwo\nthree", "and pressing it again did not take it back"
    assert got["linkedUp"] == "read [the notes](url)"
    assert got["urlChosen"] == "url", "the half you are about to paste was not selected"
    assert got["bareLink"] == "[text](url)"
    assert got["wordChosen"] == "text", "with nothing selected, the words are what you replace"
    assert got["checked"] == "- [ ] one\n- [ ] two"
    assert got["boxed"] == "- [ ] one\n- [ ] two", "the prefix was stacked on the bullet"
    assert got["unboxed"] == "- one\n- two", "and pressing it again did not take the box off"
    assert got["table"] == (
        "alpha\n\n| Heading | Heading |\n| --- | --- |\n| Cell | Cell |"
    ), "a table that interrupts a paragraph is a wall of pipes"
    assert got["picked"] == "Heading", "the word to replace was not chosen for you"
    # A caret and not a selection, on the two marks that leave one. The fence
    # puts it on the language — the one word you type before the code and cannot
    # paste from anywhere — and an empty Bold puts it between the marks, ready to
    # type. Both are `setCaret(position)` with no second argument, and a second
    # argument that arrives as `undefined` is a caret at the top of the document
    # rather than where the mark just went in.
    assert got["fenced"] == "```\nalpha beta\n```"
    assert got["afterFence"] == [3, 3], (
        f"the caret did not land on the fence's language: {got['afterFence']}"
    )
    assert got["emptyBold"] == "alpha****"
    assert got["insideBold"] == [7, 7], (
        f"the caret did not land between the marks it just wrote: {got['insideBold']}"
    )
    assert got["rule"] == "alpha\n\n---", "`---` under a line of text is a heading, not a rule"

    assert got["linked"] == {"text": "read [the notes](https://example.org/a?b=c)", "taken": True}
    assert got["tabled"] == {"text": "| a | b |\n| --- | --- |\n| c | d |", "taken": True}
    assert got["plain"]["taken"] is False, "an ordinary paste was taken over"
    assert got["bare"]["taken"] is False, "prose over a selection is not a link"

    assert got["picker"] == {"type": "file", "accept": "image/*"}, (
        "the image button did not reach the upload path paste and drop use"
    )
    assert "![" not in got["wrote"], "and it wrote markdown into the box instead"
    assert got["bar"] == {
        "buttons": 14,
        "rules": 2,
        "before": ["Code", "Link"],
        "rows": 1,
    }, "the drawn toolbar is not the shot's three groups, on one row"

    assert got["nestedOff"] == "  one\n  two", (
        "a nested numbered list was numbered a second time instead of being taken "
        "back — the indent it is nested by is what the toggle could not see, and "
        "a nested list is what this repository's own documents are made of"
    )
    assert got["nestedOn"] == "  1. one\n  2. two", "and numbering it un-nested it"
    assert got["bracketed"] == "[a\\]b](url)", "a bracket in the label ended the label"
    assert got["threw"] is None, "the image mark fell through into the branch for wraps"
    assert got["unwritable"]["wrote"] == "untouched", (
        "a mark this function cannot write changed the document anyway"
    )
    assert "Image" in got["unwritable"]["said"], (
        f"and it was refused in silence, which is the pattern this application has "
        f"shipped three times: {got['unwritable']['said']!r}"
    )
    assert got["keyed"] == "**alpha** beta", "the toolbar cannot be reached from the keyboard"
    assert got["pressed"] == "**alpha** beta", "a mouse press applied the mark twice"
    assert got["refused"] == "appetite.pdf is not an image", (
        "a file that is not an image was refused in silence"
    )
# --- three views, a full page, and the two panes -----------------------------
#
# Layout, selection and pixels, so Chrome: `tests/js/drive.js` has no box model
# at all and would answer that every pane is visible, the right size and in the
# right place on a page where nothing is drawn.
#
# `fetch` is stubbed, and that is deliberate rather than a shortcut. The page is
# opened over `file://` and there is no server behind it; and the claim being
# made here is about what the pane does with an answer — when it asks, when it
# does not, what it keeps when it redraws — not about the markdown, which
# `test_the_preview_renders_markdown_without_a_client_side_library` already asks
# of the real endpoint. The stub answers with blocks carrying `data-startline`,
# which is the renderer's real output shape and what the scroll sync reads.
_STUB_PREVIEW = """
window.asked = [];
window.replies = 0;
window.fetch = async (url, options) => {
  window.asked.push(JSON.parse(options.body).body);
  if (options.signal) options.signal.addEventListener('abort', () => { window.aborted = true; });
  await new Promise(go => setTimeout(go, 20));
  window.replies++;
  // `ok`, because the page checks it: a stub that answers a Response without one
  // is a stub the page reads as a failure, which is the shape a real 500 has.
  return {ok: true, json: async () => ({html:
    '<h2 data-startline="1" data-endline="1">One</h2>'
    + '<p data-startline="3" data-endline="3">' + 'alpha '.repeat(600) + '</p>'
    + '<h2 data-startline="5" data-endline="5">Two</h2>'
    + '<p data-startline="7" data-endline="7">' + 'omega '.repeat(600) + '</p>'})};
};
"""

_VIEWING = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const marks = document.getElementById('marks');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
const drawn = element => element.getClientRects().length > 0;
const state = () => ({
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  pressed: ['edit', 'both', 'view'].filter(
    n => seg(n).getAttribute('aria-pressed') === 'true'),
  box: drawn(area),
  pane: drawn(pane),
  marks: drawn(marks),
  position: getComputedStyle(article).position,
});

document.getElementById('toggle').click();
// Enough lines that the box has something to scroll, and enough that a source
// line is not a visual row.
area.value = Array.from({length: 200}, (_, i) => `line ${i + 1} ` + 'w'.repeat(90)).join('\\n');
area.dispatchEvent(new Event('input', {bubbles: true}));
const editing = state();

// Let the gutter settle before counting. Its column is the box's own left
// padding, so switching it on rewraps every line — it says so through this same
// event, on purpose, and it says it once for the document below because two
// hundred lines is three digits from the first draw to the last. Counting from
// before that first draw would count a redraw as a view change.
await new Promise(go => setTimeout(go, 80));

// Every view change has to tell the seat layer the box moved. The Preview button
// this replaces set `BODY.hidden = true` and dispatched nothing.
let told = 0;
addEventListener('openproj:editing', () => { told++; });

seg('both').click();
const both = state();
await new Promise(go => setTimeout(go, 400));
const split = {
  // Side by side, not stacked, and both inside the window.
  sideBySide: area.getBoundingClientRect().right <= pane.getBoundingClientRect().left + 1,
  inside: area.getBoundingClientRect().bottom <= innerHeight + 1
          && pane.getBoundingClientRect().bottom <= innerHeight + 1,
  // Each pane scrolls on its own, and the page does not scroll at all.
  boxScrolls: area.scrollHeight > area.clientHeight + 1,
  paneScrolls: pane.scrollHeight > pane.clientHeight + 1,
  pageScrolls: document.documentElement.scrollHeight > innerHeight + 1,
};

seg('view').click();
const viewing = state();
seg('edit').click();
const writing = state();
// Pressing the pressed segment is the way back out with a pointer.
seg('edit').click();
const out = state();

// The chord, matched on `event.code`: shift-2 is `@` on a US layout and `"` on a
// Swiss-German one, so a binding read off `key` is one that could never fire.
const chord = code => dispatchEvent(new KeyboardEvent(
  'keydown', {ctrlKey: true, shiftKey: true, code, key: '@', bubbles: true}));
chord('Digit2');
const chorded = state();
chord('Digit2');
const unchorded = state();

// And AltGr does not reach it. Chrome on Windows delivers the AltGr key as
// `ctrlKey` and `altKey` together, and on the Swiss-German layout half this team
// types on, AltGr+E is the euro sign — so the chord this replaces swallowed a
// character people type. The euro is dispatched here exactly as Chrome reports
// it, including the modifier state, and the view must not move.
dispatchEvent(new KeyboardEvent('keydown', {
  ctrlKey: true, altKey: true, modifierAltGraph: true, code: 'KeyE', key: '€',
  bubbles: true, cancelable: true,
}));
const afterEuro = state();

// Escape in the box, arbitrated: the page first while there is something to come
// back out of, then the hatch that gives Tab back.
seg('both').click();
const escape = () => area.dispatchEvent(
  new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
area.focus();
escape();
const escaped = state();
// `announce` writes into `#state` on a page that has one, which this page does.
document.getElementById('state').textContent = '';
escape();
const said = document.getElementById('state').textContent;

return {editing, both, split, viewing, writing, out, chorded, unchorded, afterEuro,
        escaped, said, told, asked: window.asked.length};
"""


def test_the_three_views_are_one_of_three_and_each_pane_scrolls_on_its_own(
    client: TestClient, tmp_path: Path
):
    """Asks 1 and 3, which are the top two on the list, and they are one feature:
    the three views are three shapes of the full-page surface.

    Four states and not three. The note this is modelled on is always full page,
    so exactly one of its three segments is always pressed; here the reading
    measure, the facts column and the width handle are the ordinary page, and the
    surface is somewhere you go and come back from. So `full page off` is a real
    state with nothing pressed, and the way back out is the pressed segment, the
    same chord, or Escape.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "views.html", 1400, _VIEWING
    )

    assert got["editing"] == {
        "classes": [], "pressed": [], "box": True, "pane": False, "marks": True,
        "position": "relative",
    }, "editing on its own is not full page and presses nothing"

    assert got["both"]["classes"] == ["full", "view-both"]
    assert got["both"]["pressed"] == ["both"], "two segments pressed is not a choice of three"
    assert got["both"]["position"] == "fixed", "the surface does not fill the window"
    assert got["both"]["box"] and got["both"]["pane"]

    assert got["split"] == {
        "sideBySide": True, "inside": True,
        "boxScrolls": True, "paneScrolls": True, "pageScrolls": False,
    }, "the two panes do not scroll on their own inside the window"

    assert got["viewing"] == {
        "classes": ["full", "view-view"], "pressed": ["view"],
        "box": False, "pane": True, "marks": False, "position": "fixed",
    }, "preview only still draws the box, or draws a toolbar over no box"
    assert got["writing"] == {
        "classes": ["full", "view-edit"], "pressed": ["edit"],
        "box": True, "pane": False, "marks": True, "position": "fixed",
    }
    assert got["out"]["classes"] == [] and got["out"]["pressed"] == []
    assert got["out"]["position"] == "relative", "the pressed segment did not leave full page"

    assert got["chorded"]["pressed"] == ["both"], (
        "Ctrl+Shift+2 was not read off event.code"
    )
    assert got["unchorded"]["pressed"] == [], "and the same chord did not take it back"
    assert got["afterEuro"]["pressed"] == [], (
        "AltGr+E moved the view: the chord is on a modifier combination that half "
        "this team types the euro sign with"
    )

    assert got["escaped"]["classes"] == [], "Escape did not leave full page"
    assert "Tab" in got["said"], (
        "and the next Escape did not open the hatch that gives Tab back, which is "
        "the claimant Escape has when there is nothing to leave"
    )

    # Eight view changes above this line, and the seat layer told about every
    # one of them: three segments, the pressed one again, the chord on and off,
    # the split re-entered, and Escape.
    assert got["told"] == 8, "a view change the seat layer was not told about"
    assert got["asked"] >= 1, "the preview was never asked for"


_DEEP_LINK = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
return {
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  editing: article.classList.contains('editing'),
  pressed: ['view-edit', 'view-both', 'preview'].filter(
    id => document.getElementById(id).getAttribute('aria-pressed') === 'true'),
};
"""


def test_a_link_to_the_split_view_opens_in_the_split_view(client: TestClient, tmp_path: Path):
    """`?both`, off `location.search`, read once at load — the spelling the
    address bar in the observed note actually carries. A flag and not a value:
    `?both=` answers the empty string to `get`, which reads as false."""
    page = client.get(f"/detail/{TASK}").text
    got = measured_in(
        chrome(), page, tmp_path / "deep.html", 1400, _DEEP_LINK, query="?both="
    )

    assert got["classes"] == ["full", "view-both"]
    assert got["pressed"] == ["view-both"]
    assert got["editing"], "a link into a writing view that does not open the writing view"

    plain = measured_in(chrome(), page, tmp_path / "plain.html", 1400, _DEEP_LINK)
    assert plain["classes"] == [] and plain["pressed"] == []
    assert not plain["editing"], "no link, and the page opened in a view anyway"


_GRIPPING = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const grip = document.getElementById('grip');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
// Against the pane's own right edge, and how far that is from the window's — a
// handle parked at the edge of the screen is the bug this is about, and it is
// the one arrangement that looks deliberate.
const where = () => ({
  hidden: grip.hidden,
  onEdge: Math.abs(parseFloat(grip.style.left || '0')
                   - article.getBoundingClientRect().right) < 1,
  spare: Math.round(innerWidth - article.getBoundingClientRect().right),
});

const reading = where();
document.getElementById('toggle').click();
const editing = where();
const full = {};
for (const name of ['edit', 'both', 'view']) { seg(name).click(); full[name] = where(); }
seg('view').click();
const back = where();
return {reading, editing, full, back};
"""


def test_the_width_handle_finds_the_pane_in_every_view(client: TestClient, tmp_path: Path):
    """`place` exists because a handle measured against a hidden element parks
    itself against the left edge of the page, and that shipped once. Full page is
    a second way to produce the same thing by a different route: it drags
    `--measure`, and in full page there is no measure — the surface is the
    window — so a handle drawn there would sit against the right edge of the
    screen and change nothing when dragged."""
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "grip.html", 1400, _GRIPPING
    )

    for mode in ("reading", "editing"):
        assert not got[mode]["hidden"], f"no handle while {mode}"
        assert got[mode]["onEdge"], f"the handle is not on the column's edge while {mode}"
        assert got[mode]["spare"] > 20, f"the handle is against the window edge while {mode}"

    for name in ("edit", "both", "view"):
        assert got["full"][name]["hidden"], f"a width handle in the {name} view"

    assert not got["back"]["hidden"] and got["back"]["onEdge"], (
        "the handle did not come back with the column"
    )


# The document the scroll sync is asked about: 161 lines, one of which is long
# enough to wrap. One that wrapped nowhere would be a corpus that does not
# contain the string that matters — `scrollTop / lineHeight` is exactly right on
# it, and the measuring mirror this replaces it with would have nothing to prove.
_WRAPPING_BODY = (
    "\n".join(
        ("word " * 60).strip() if at == 40 else f"line {at + 1}"
        for at in range(161)
    )
)

# The stub's blocks, moved onto the lines the body above actually has: this is
# the shape the renderer emits and the sync reads, not a document of its own.
_SYNC_STUB = _STUB_PREVIEW
for _was, _now in (("3", "41"), ("5", "82"), ("7", "121")):
    _SYNC_STUB = _SYNC_STUB.replace(f'data-startline="{_was}"', f'data-startline="{_now}"')

_SYNCING = f"const WRAPPING_BODY = {json.dumps(_WRAPPING_BODY)};" + _SYNC_STUB + """
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
// A timer and not `requestAnimationFrame`, and that is worth recording: under
// `--virtual-time-budget` a frame never comes at all, so a test that waited for
// one waited for ever and reported nothing. The page has the same problem for
// the same reason in a background tab, which is why the sync clears its flags on
// a timer too.
const settle = ms => new Promise(go => setTimeout(go, ms));
const after = () => settle(90);

document.getElementById('toggle').click();
area.value = WRAPPING_BODY;
area.dispatchEvent(new Event('input', {bubbles: true}));
document.getElementById('view-both').click();
await settle(500);

// The ground truth for the source side, measured off the textarea itself rather
// than off the mirror under test: 160 lines that cannot wrap plus one that does,
// so the box's own scrollHeight says how many rows the long one took.
const style = getComputedStyle(area);
const step = parseFloat(style.lineHeight);
const padTop = parseFloat(style.paddingTop);
// Rounded, because `scrollHeight` is an integer and a row is 20.15px: the count
// of visual rows is a whole number and the division is only an approximation of
// it. Still independent of the mirror under test — it comes off the textarea.
const rows = Math.round(
  (area.scrollHeight - padTop - parseFloat(style.paddingBottom)) / step);
const longRows = rows - 160;
const topOfEightyTwo = padTop + (80 + longRows) * step;
// The block's top **inside the pane it scrolls in**, and not its `offsetTop`.
// Nothing positions `#body-preview`, so the offset parent of every block in it is
// `article.entity` — which full page makes `position: fixed` — and `offsetTop` is
// therefore a distance from the top of the window while `scrollTop`, which is
// what this number is compared against, is a distance inside the pane. The two
// differ by a constant: the pane's own top within the article, 283.625px at this
// size on a pane 458px tall. The page used to make the same mistake, so the test
// agreed with it and both were wrong together; this arithmetic is the pane's own
// scroll space and it asks the question that is actually being asked.
const block = pane.querySelector('[data-startline="82"]');
const inPane = element =>
  element.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop;
const blockOfEightyTwo = inPane(block);
// And the same number the other way round, as a control on the arithmetic above:
// if this is 0 then the two really do agree, and `offsetTop` reports 283 here.
const offsetSays = block.offsetTop;

area.scrollTop = topOfEightyTwo;
area.dispatchEvent(new Event('scroll'));
await after();
const followed = pane.scrollTop;
// The assertion neither side of the implementation can produce: after the sync,
// the block for line 82 is at the top of the pane, measured in screen pixels off
// two rects. It is 0 whatever coordinate space either side chose, and it is the
// thing a reader actually sees.
const whereIsIt = block.getBoundingClientRect().top - pane.getBoundingClientRect().top;

// Back to the top first, so driving from the rendered side has somewhere to
// move the box to — otherwise this direction passes without running at all.
area.scrollTop = 0;
await after();
pane.scrollTop = blockOfEightyTwo;
pane.dispatchEvent(new Event('scroll'));
await after();
const backAgain = area.scrollTop;
// And the pane did not then drive the box back: one more turn of the loop would
// move one of them off the line they agreed on.
await after();
const settled = {box: area.scrollTop, pane: pane.scrollTop};

return {longRows, step, topOfEightyTwo, blockOfEightyTwo, offsetSays, whereIsIt,
        followed, backAgain, settled};
"""


def test_the_two_panes_scroll_to_the_same_line(client: TestClient, tmp_path: Path):
    """The rendered side knows which source line each block came from, because the
    renderer stamps `data-startline` on every top-level block from markdown-it's
    own token map. The source side has to be measured: a textarea has no DOM
    inside it, one logical line is any number of visual rows, and this document
    contains one line that wraps precisely so that `scrollTop / lineHeight` — the
    obvious answer — is wrong on it.

    The ground truth here is not the mirror under test. The 160 lines that cannot
    wrap and the one that does mean the textarea's own `scrollHeight` says how
    many rows the long line took, and everything else is arithmetic.

    And the ground truth for the rendered side is not `offsetTop`. It was, and
    that is why this test passed while both panes were a third of a screen out:
    the page measured the blocks with `offsetTop`, the test measured them with
    `offsetTop`, and the two agreed with each other about a number that was in the
    wrong coordinate space. Nothing positions `#body-preview`, so the offset
    parent is the article, which full page makes `position: fixed`. Both sides are
    rects against the scroller now, and `whereIsIt` is the assertion that needs
    neither: after the sync, line 82's block is at the top of the pane.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "sync.html", 1400,
        _SYNCING, budget=3000,
    )

    assert got["longRows"] > 1, (
        "nothing wrapped, so this document cannot tell a measured line from a counted one"
    )
    assert abs(got["followed"] - got["blockOfEightyTwo"]) < 2, (
        "scrolling the source to line 82 did not bring line 82's block to the top"
    )
    assert abs(got["whereIsIt"]) < 2, (
        "line 82's block is not at the top of the pane — measured off two rects, so "
        "this is what a reader sees and not what either side of the sync computed"
    )
    assert abs(got["offsetSays"] - got["blockOfEightyTwo"]) > 2, (
        "`offsetTop` and the pane's own scroll space agree here, so this document "
        "cannot tell the two apart and the test above proves nothing"
    )
    assert abs(got["backAgain"] - got["topOfEightyTwo"]) < 2, (
        "and scrolling the rendered pane back did not bring the source with it"
    )
    assert abs(got["settled"]["box"] - got["backAgain"]) < 2, "the two panes drove each other"
    assert abs(got["settled"]["pane"] - got["blockOfEightyTwo"]) < 2


_LIVE = _STUB_PREVIEW + """
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const settle = ms => new Promise(go => setTimeout(go, ms));
const type = text => {
  area.value = text;
  area.dispatchEvent(new Event('input', {bubbles: true}));
};

document.getElementById('toggle').click();
document.getElementById('view-both').click();
await settle(400);
const opened = window.asked.length;

// Three keystrokes, one round trip: a request per keystroke is what a debounce
// exists to stop.
type('one'); type('one t'); type('one two');
const duringTyping = window.asked.length - opened;
// And still nothing a fifth of a second later, which is the half of this a
// debounce of zero would pass: three keystrokes in one turn of the event loop
// coalesce into one request whatever the delay is.
await settle(180);
const soonAfter = window.asked.length - opened;
await settle(400);
const afterTyping = window.asked.length - opened;
const sent = window.asked[window.asked.length - 1];

// An input event that changes nothing asks for nothing. This is the case a
// keystroke that is undone, or a caret move that fires input, actually produces.
type('one two');
await settle(400);
const unchanged = window.asked.length - opened;

// And the pane keeps its place when it is redrawn. `innerHTML` with no memory
// scrolls back to the top on every keystroke, which is worse than no live
// preview at all.
pane.scrollTop = 200;
const held = pane.scrollTop;
type('one two three');
await settle(400);
const kept = pane.scrollTop;

return {opened, duringTyping, soonAfter, afterTyping, sent, unchanged, held, kept,
        replies: window.replies};
"""


def test_the_preview_keeps_up_and_stays_where_the_reader_left_it(
    client: TestClient, tmp_path: Path
):
    """Still the server's markdown, and still the same round trip — a second
    markdown implementation in JavaScript is refused on record, because two
    renderers disagree eventually and the one people would trust is not the one
    whose output gets committed. What is asked here is the other half: that
    making it live did not make it either expensive or annoying.

    `fetch` is stubbed. The page is opened over `file://` and there is no server
    behind it, and the claim is about when the pane asks and what it keeps —
    `test_the_preview_renders_markdown_without_a_client_side_library` asks the
    real endpoint what it renders.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "live.html", 1400,
        _LIVE, budget=3400,
    )

    assert got["opened"] == 1, "opening the split view did not draw a preview"
    assert got["duringTyping"] == 0, "a round trip on every keystroke"
    assert got["soonAfter"] == 0, "the wait is not long enough to be one"

    assert got["afterTyping"] == 1, "and then one for the three of them together"
    assert got["sent"] == "one two", "the request carried a version of the text nobody has"
    assert got["unchanged"] == 1, "an input that changed nothing asked for a re-render"
    # Honest about what this one is: Chrome keeps a scroller's offset across a
    # wholesale replacement of its contents, so no line of ours is what makes it
    # pass — measured, and the save-and-restore the plan asked for was deleted
    # rather than left in as three lines that look like the reason. It stays as
    # a regression test, because the ways to break it are ordinary: building the
    # pane's children and calling `replaceChildren`, or setting `scrollTop = 0`
    # to "start at the top", and both of them look like tidying.
    assert got["held"] == 200 and got["kept"] == 200, (
        "the pane scrolled back to the top when it redrew"
    )


_OVERTAKEN = """
window.asked = [];
window.aborted = 0;
window.fetch = async (url, options) => {
  window.asked.push(1);
  if (options.signal) options.signal.addEventListener('abort', () => { window.aborted++; });
  // Slower than the debounce, which is the only way two of these are ever in the
  // air at once — and the case an AbortController is for.
  await new Promise(go => setTimeout(go, 500));
  return {ok: true, json: async () => ({html: '<p data-startline="1" data-endline="1">x</p>'})};
};
const area = document.querySelector('textarea[name=body]');
const settle = ms => new Promise(go => setTimeout(go, ms));
const type = text => {
  area.value = text;
  area.dispatchEvent(new Event('input', {bubbles: true}));
};
document.getElementById('toggle').click();
document.getElementById('view-both').click();
await settle(340);
type('later');
await settle(340);
return {asked: window.asked.length, aborted: window.aborted};
"""


def test_a_preview_that_has_been_overtaken_is_called_off(client: TestClient, tmp_path: Path):
    """A render that is already out of date is a render nobody wants, and one that
    arrives after the one that replaced it draws the wrong document. The debounce
    is 300ms and a slow render is longer than that, so this is not a corner: it is
    what a big pitch on a busy server does every time."""
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "abort.html", 1400,
        _OVERTAKEN, budget=2400,
    )

    assert got["asked"] == 2, "the second render was never asked for"
    assert got["aborted"] == 1, "the first render was left in the air to land on top of it"


def test_a_view_change_tells_the_seat_layer_the_box_moved(client: TestClient):
    """The `#preview` toggle this replaces set `BODY.hidden = true` and dispatched
    nothing, so `drawSeats` never learnt that the box it measures against had gone
    — every band stayed where the box used to be. That was transient, because the
    only way to reach it was pressing one button; three views make it the normal
    case, so every change now says so.

    The count is asked of Chrome in
    `test_the_three_views_are_one_of_three_and_each_pane_scrolls_on_its_own`,
    which listens for the event through eight of them. This is the static half:
    that the dispatch is in the one function every view change goes through, and
    that the line that caused the defect is gone from the page altogether.
    """
    page = client.get(f"/detail/{TASK}").text
    switching = re.search(r"function showView\(mode\) \{.*?\n\}", page, re.S).group(0)

    assert "dispatchEvent(new Event('openproj:editing'))" in switching
    # The box is taken away by a class the seat layer can see, never behind its back.
    assert "BODY.hidden" not in page
    # And `drawSeats` is still listening for it, which is the other end of the
    # seam and the half a grep of one file cannot see.
    assert "addEventListener('openproj:editing', () => { drawSeats(); sit(); });" in page


# Ask 4: the numbers down the side of the box, asked of Chrome because a line
# number is a pixel claim and nothing else can answer one.
#
# Six lines chosen for the six ways a run of text decides where to break, because
# the whole feature is a mirror agreeing with a textarea about exactly that: prose
# that wraps on spaces, CJK that wraps between any two characters, a ZWJ sequence
# and a regional-indicator pair that must not be broken through the middle of a
# character, a hard tab whose width is `tab-size` and not a space, a URL with
# nothing in it to break on, and an empty line — which has no box at all unless
# something is put in it.
_GUTTER_BODY = "\n".join((
    "line one is short",
    # Long on purpose, and this is the sensitivity of the whole test. A line of
    # two rows changes its row count only at the few widths where its one break
    # moves; a line of fifty changes it at most of them, so an error of two pixels
    # in the mirror's width — which is exactly the error the old seat mirror had —
    # shows up as every number below it being a whole row out.
    "and the second line is ordinary prose, long enough that it has to wrap many "
    "times over at any of the widths below, which is the case the whole mirror "
    "exists for and the one a count of characters gets wrong. " * 12,
    "這是一段中文字這是一段中文字這是一段中文字這是一段中文字這是一段中文字這是一段中文字這是一段中文字",
    "\tone\ttwo\tthree tabbed columns and then a run of words long enough to wrap",
    "family 👨‍👩‍👧‍👦 flags 🇨🇭🇩🇪 and coders "
    "👩‍💻👨‍🚒 with words after them to carry the line past a break",
    "https://example.com/a/very/long/unbreakable/path/that/has/nothing/in/it/to/break/on/at/all",
    "",
    "last line",
))

_NUMBERING = f"const GUTTER_BODY = {json.dumps(_GUTTER_BODY)};" + """
const area = document.querySelector('textarea[name=body]');
const article = document.querySelector('article.entity');
const settle = ms => new Promise(go => setTimeout(go, ms));

// The ground truth, built here and owing nothing to the page. It is a
// CONTENT-box div with no padding and no border, given the box's real content
// width term by term, where the page's mirror is a BORDER-box div handed the
// box's padding and border and a width that includes them. Two constructions
// that must agree; if the test used the page's own it would agree with whatever
// the page did, which is how the scroll-sync test came to pin its own defect.
function truth() {
  const style = getComputedStyle(area);
  const mirror = document.createElement('div');
  for (const name of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
                      'letterSpacing', 'whiteSpace', 'wordBreak', 'overflowWrap',
                      'tabSize']) {
    mirror.style[name] = style[name];
  }
  mirror.style.position = 'absolute';
  mirror.style.top = '0';
  mirror.style.left = '-9999px';
  mirror.style.boxSizing = 'content-box';
  mirror.style.padding = '0';
  mirror.style.border = '0';
  const bars = area.offsetWidth - area.clientWidth
    - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
  mirror.style.width = (area.getBoundingClientRect().width
    - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth)
    - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - bars) + 'px';
  const lines = area.value.split('\\n');
  for (const line of lines) {
    const row = document.createElement('div');
    row.textContent = line || '\\u200b';
    mirror.append(row);
  }
  document.body.append(mirror);
  const zero = mirror.getBoundingClientRect().top;
  const tops = [...mirror.children].map(row => row.getBoundingClientRect().top - zero);
  const rows = Math.round(
    mirror.getBoundingClientRect().height / parseFloat(style.lineHeight));
  mirror.remove();
  // Where the box's first row of text is drawn on the screen: its border box,
  // plus its border, plus its padding. Every term written out, because the one
  // that was missing is what put every number a pixel high.
  const origin = area.getBoundingClientRect().top
    + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop);
  return {tops, rows, lines: lines.length, origin};
}

document.getElementById('toggle').click();
area.value = GUTTER_BODY;
area.dispatchEvent(new Event('input', {bubbles: true}));
// The gutter coalesces onto a frame with a 32ms backstop, and under the headless
// clock the rendering step runs once, so the backstop is the one that fires.
await settle(120);

// Swept one CSS pixel at a time, because the failure this stage is named for
// only shows at a width sitting on a wrap boundary: two pixels of error in the
// mirror's width flips one break and puts every line below it a whole row out,
// and a coarse sweep steps straight over the widths where that happens.
const answers = [];
for (let measure = 520; measure < 580; measure++) {
  article.style.setProperty('--measure', measure + 'px');
  dispatchEvent(new Event('openproj:editing'));
  // The gutter's backstop is 32ms.
  await settle(40);
  const ground = truth();
  const numbers = [...document.querySelectorAll('.lineno')];
  answers.push({
    measure,
    count: numbers.length,
    lines: ground.lines,
    wrapped: ground.rows - ground.lines,
    labels: numbers.map(number => number.textContent).join(','),
    boxWidth: Math.round(area.getBoundingClientRect().width * 100) / 100,
    worst: numbers.length === ground.lines ? Math.max(...numbers.map(
      (number, at) => Math.abs(
        number.getBoundingClientRect().top - (ground.origin + ground.tops[at])))) : null,
  });
}

// And the one control whose entire job is to change the width of the box. The
// handle writes `--measure` and calls `place()`; before this it dispatched
// nothing, so the numbers stayed where the old width had put them — measured, up
// to six whole rows out — until a window resize happened to put them back. The
// inline property this sweep has been using is removed first, or it would beat
// the one the handle writes on the root and the drag would move nothing.
article.style.removeProperty('--measure');
const grip = document.getElementById('grip');
grip.dispatchEvent(new PointerEvent(
  'pointerdown', {bubbles: true, pointerId: 1, clientX: innerWidth / 2 + 400}));
dispatchEvent(new PointerEvent(
  'pointermove', {bubbles: true, pointerId: 1, clientX: innerWidth / 2 + 231}));
dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 1}));
await settle(80);
const ground = truth();
const numbers = [...document.querySelectorAll('.lineno')];
const dragged = {
  boxWidth: Math.round(area.getBoundingClientRect().width * 100) / 100,
  count: numbers.length,
  lines: ground.lines,
  worst: numbers.length === ground.lines ? Math.max(...numbers.map(
    (number, at) => Math.abs(
      number.getBoundingClientRect().top - (ground.origin + ground.tops[at])))) : null,
};

return {answers, dragged};
"""


def test_every_line_number_sits_on_the_line_it_numbers(client: TestClient, tmp_path: Path):
    """Ask 4, pinned against a mirror this test builds itself.

    One number per LOGICAL line, on the first visual row of it — which is what the
    note this is modelled on draws, and what makes the number mean the same thing
    as a line number in a diff, a stack trace or a review comment. A count of
    visual rows would be a number that changes when you drag the width handle.

    The corpus is chosen for the ways a run of text decides where to break, and
    the widths are swept because the failure this whole stage is about only
    appears at a width sitting on a wrap boundary. The tolerance is under a pixel
    on purpose: the two errors this catches are a whole border-width (the column
    is anchored to the box's border box and the rows are measured from its padding
    box) and the accumulating rounding of an integer `offsetTop` against a
    20.15625px row.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "gutter.html", 1400,
        _NUMBERING, budget=6000,
    )

    for answer in got["answers"]:
        where = f"at --measure: {answer['measure']}px (box {answer['boxWidth']}px)"
        assert answer["count"] == answer["lines"], (
            f"{where}: {answer['count']} numbers for {answer['lines']} logical lines"
        )
        assert answer["wrapped"] > 0, (
            f"{where}: nothing wrapped, so this width proves nothing about a gutter "
            "that counts logical lines rather than visual rows"
        )
        assert answer["labels"] == ",".join(
            str(n + 1) for n in range(answer["lines"])
        ), f"{where}: the numbers are not 1..n in order"
        assert answer["worst"] < 0.25, (
            f"{where}: a line number is {answer['worst']:.3f}px off the line it numbers"
        )

    assert got["dragged"]["boxWidth"] != got["answers"][-1]["boxWidth"], (
        "the width handle moved nothing, so the drag below asks nothing"
    )
    assert got["dragged"]["count"] == got["dragged"]["lines"]
    assert got["dragged"]["worst"] < 0.25, (
        f"after a drag of the width handle a line number is "
        f"{got['dragged']['worst']:.3f}px off the line it numbers — the one control "
        "whose whole job is to change the width of the box did not tell the column "
        "of numbers beside it"
    )


_LEAVING = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const nav = document.querySelector('body > nav');
const link = nav.querySelector('a');
// What a pointer would actually hit in the middle of the first nav link. The
// whole finding is that the surface paints over it, so a class name is not the
// question — `elementFromPoint` is.
const overLink = () => {
  const box = link.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return hit ? hit.tagName : null;
};
const shape = () => ({
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  fullpage: document.body.classList.contains('fullpage'),
  navInert: !!nav.inert,
  over: overLink(),
  switcher: document.getElementById('views').getClientRects().length > 0,
  editing: article.classList.contains('editing'),
});

const answers = {};
for (const [name, id] of [['edit', 'view-edit'], ['both', 'view-both'], ['view', 'preview']]) {
  document.getElementById('toggle').click();
  document.getElementById(id).click();
  const inside = shape();
  document.getElementById('cancel').click();
  answers[name] = {inside, after: shape()};
}
return answers;
"""


def test_cancel_leaves_the_surface_it_was_pressed_in(client: TestClient, tmp_path: Path):
    """The worst thing this branch shipped, and it is on the main path: press a
    view, decide not to save, press Cancel.

    `flipEditing` dropped `.editing` and left `.full` and `body.fullpage` alone —
    and `.views` is drawn only under `.entity.editing`, so the switcher, which the
    commit message named as the way back, vanished at the same instant. The box
    went with it, so Escape could not be reached either; the nav was painted over
    by an opaque fixed article; and the only exits left were an undiscoverable
    chord, the Back button and a reload.

    Ending the session leaves the surface the session was in. Asked of all three
    views, because each one takes a different thing away.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "leave.html", 1400,
        _LEAVING, budget=3000,
    )

    for name, answer in got.items():
        assert answer["inside"]["classes"] == ["full", f"view-{name}"], name
        assert answer["inside"]["navInert"], f"{name}: the page behind the surface is not inert"
        assert answer["inside"]["over"] != "A", (
            f"{name}: the surface does not actually cover the nav, so nothing here is proved"
        )
        assert answer["after"] == {
            "classes": [], "fullpage": False, "navInert": False, "over": "A",
            "switcher": False, "editing": False,
        }, (
            f"Cancel from the {name} view left the reader in the surface: "
            f"{answer['after']}"
        )


_A_FAILED_PREVIEW = """
window.asked = 0;
window.fetch = async () => { window.asked++; return {ok: false, status: 500,
  json: async () => ({detail: 'the body could not be rendered'})}; };
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const said = () => document.getElementById('state').textContent;
const settle = ms => new Promise(go => setTimeout(go, ms));

document.getElementById('toggle').click();
document.getElementById('view-both').click();
await settle(400);
const refused = {pane: pane.textContent.trim(), said: said(), asked: window.asked};

// And the shape that is worse, because it is silent: a 400 from this server, and
// a proxy's own error page, both answer JSON with no `html` in it.
window.fetch = async () => { window.asked++; return {ok: true,
  json: async () => ({detail: 'no document here'})}; };
document.getElementById('state').textContent = '';
area.value = 'a different document';
area.dispatchEvent(new Event('input', {bubbles: true}));
await settle(500);
const shapeless = {pane: pane.textContent.trim(), said: said()};

// A failure is not remembered as "already shown", or the pane is stuck on this
// text for the life of the page.
window.fetch = async () => { window.asked++; return {ok: true, json: async () => (
  {html: '<p data-startline="1" data-endline="1">it came back</p>'})}; };
area.dispatchEvent(new Event('input', {bubbles: true}));
await settle(500);
const recovered = pane.textContent.trim();

return {refused, shapeless, recovered};
"""


def test_a_preview_that_fails_says_so_and_never_writes_the_word_undefined(
    client: TestClient, tmp_path: Path
):
    """`askPreview` had no `response.ok` check and one bare `catch { return }`, so
    every way a render can fail left the pane exactly as it was and said nothing.
    On the first open of the split view "exactly as it was" is empty, which reads
    as a document that renders to nothing.

    The second shape is worse and is the one a proxy produces: an answer that IS
    JSON and carries no `html`. `innerHTML = undefined` writes the nine letters of
    the word into the pane, and `previewShown` was then set, so it was never
    retried for that text.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "failed.html", 1400,
        _A_FAILED_PREVIEW, budget=4000,
    )

    # At least one, not exactly one: a failure is deliberately not remembered as
    # "already shown", so anything that asks again asks again, which is the point.
    assert got["refused"]["asked"] >= 1, "the preview was never asked for"
    assert "could not be rendered" in got["refused"]["pane"], (
        "a 500 left an empty pane beside a document full of text"
    )
    assert "500" in got["refused"]["said"], (
        f"and said nothing in the live region: {got['refused']['said']!r}"
    )
    assert "undefined" not in got["shapeless"]["pane"], (
        f"an answer with no document in it was written into the pane: "
        f"{got['shapeless']['pane']!r}"
    )
    assert got["shapeless"]["said"], "and it was not announced either"
    assert got["recovered"] == "it came back", (
        "the failure was remembered as the text that had been shown, so the pane "
        "never asked again"
    )


# --------------------------------------------------------------------------- #
# The preference, the status bar and the draft receipt
# --------------------------------------------------------------------------- #


def _before_the_page_runs(page: str, script: str) -> str:
    """The same page with `script` running ahead of every one of its own.

    `measured_in` appends its question at `</body>`, which is after everything —
    and both questions below are about what the page does with a store it reads
    before the first paint: `remembered` is declared in the head, and the editor
    preference is read the moment `_COMBOBOX` parses. So this goes in ahead of the
    shell's first `<script>`, which is the one right after the icon link.
    """
    return page.replace('<link rel="icon"', f"<script>{script}</script><link rel=\"icon\"", 1)


_SEED = """try { localStorage.setItem('openproj:editor:1', JSON.stringify(%s)); } catch (e) {}"""

# The store this application is written against the refusal of. `localStorage`
# does not answer null when it is denied — it THROWS, on the property itself,
# before any method is called — so a stub that returns null is a stub for a
# failure this browser does not have.
_NO_STORE = """
window.__errors = [];
addEventListener('error', event => window.__errors.push(String(event.message)));
Object.defineProperty(window, 'localStorage', {
  get() { throw new DOMException('denied', 'SecurityError'); },
});
"""

# Every question below is asked of a page whose preview is stubbed, because
# entering an editing session may restore a remembered view and a view asks the
# server to render the document.
_STUB_RENDER = """
window.fetch = async () => ({ok: true, json: async () => (
  {html: '<p data-startline="1">rendered</p>'})});
"""

_STATUS = _STUB_RENDER + r"""
const bar = document.getElementById('statusbar');
const area = document.querySelector('textarea[name=body]');
const item = at => bar.children[at].textContent;
const spaces = bar.querySelector('button');
document.getElementById('toggle').click();

// A document whose third line carries an astral character, so "column" has to
// mean a character and not a UTF-16 code unit.
area.value = 'one\ntwo\nthe \u{1F44D} is one character\n';
area.dispatchEvent(new Event('input'));
const lines = item(3);

const caretAt = at => {
  area.setSelectionRange(at, at);
  area.dispatchEvent(new Event('keyup'));
  return item(0);
};
const start = caretAt(0);
// Immediately after the thumb, which is two code units in and one character in.
const afterEmoji = caretAt(area.value.indexOf('\u{1F44D}') + 2);
area.setSelectionRange(0, 7);
area.dispatchEvent(new Event('select'));
const selected = item(0);

// The picker: what it says, what it does to the next Tab, and what it does to
// the document, which must be nothing at all.
const wasText = area.value;
const said = [spaces.textContent];
spaces.click();
said.push(spaces.textContent);
const stored = localStorage.getItem('openproj:editor:1');
// Measured before the Tab below, which is the gesture that IS allowed to change
// the document: what the picker itself may change is nothing.
const untouched = area.value === wasText;
area.focus();
area.setSelectionRange(0, 0);
area.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true}));
return {
  lines, start, afterEmoji, selected, said, stored, untouched, title: spaces.title,
  typed: area.value.slice(0, area.value.indexOf('one')),
  drawn: bar.getClientRects().length > 0,
  order: [...bar.children].map(child => child.id || child.tagName.toLowerCase()),
};
"""


def test_the_status_bar_says_where_the_caret_is_how_long_it_is_and_what_tab_types(
    client: TestClient, tmp_path: Path
):
    """Ask 5, in the shape the screenshot settles: a strip along the foot of the
    box holding two facts and a control, and the control is two words that STATE
    the current value and are themselves the click target.

    The three things this pins that a substring in the page could not:

    * the caret readout counts CHARACTERS, not UTF-16 code units — the same
      index-space question that shipped a splice cutting an emoji in half;
    * the picker changes what the next Tab types and does not touch one
      character of what is already written, which is the bulk-gesture rule: a
      global re-indent reaches a live room as one delete-all-insert-all, which
      `tests/test_coedit.py:756` already measures as larger than a body may be;
    * and the choice is remembered under the one versioned key.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "status.html", 1400,
        _STATUS, budget=6000,
    )

    assert got["drawn"], "the status bar is not drawn in an editing session"
    assert got["order"] == ["span", "button", "draftevery", "span"], (
        "the strip is caret, the indent picker, whatever the page put in it, and "
        f"the length — in that order: {got['order']}"
    )
    assert got["lines"] == "Length: 32", got["lines"]
    assert got["start"] == "Line 1, Column 1 — 4 Lines", got["start"]
    assert got["afterEmoji"] == "Line 3, Column 6 — 4 Lines", (
        f"a caret one character past a thumbs-up is in column 6 and this says "
        f"{got['afterEmoji']!r} — the readout is counting UTF-16 code units"
    )
    assert "7 selected" in got["selected"], got["selected"]

    assert got["said"] == ["Spaces: 2", "Spaces: 4"], got["said"]
    assert "press for 8" in got["title"], (
        f"a picker that says only what it is leaves somebody to press it to find "
        f"out what it does: {got['title']!r}"
    )
    assert json.loads(got["stored"])["indent"] == 4
    assert got["untouched"], "pressing the indent picker rewrote the document"
    assert got["typed"] == "    ", (
        f"Tab typed {got['typed']!r} after the picker was moved to four"
    )


_LONG = _STUB_RENDER + r"""
const size = document.getElementById('statusbar').lastElementChild;
const area = document.querySelector('textarea[name=body]');
document.getElementById('toggle').click();
const said = () => document.getElementById('state').textContent;
const shape = () => ({text: size.textContent, over: size.classList.contains('over')});
area.value = 'x'.repeat(%d);
area.dispatchEvent(new Event('input'));
const under = shape();
area.value = 'x'.repeat(%d);
area.dispatchEvent(new Event('input'));
const over = {...shape(), said: said()};
return {under, over};
"""


def test_the_length_says_the_ceiling_before_a_save_is_refused(
    client: TestClient, tmp_path: Path
):
    """`MAX_BODY_BYTES` was a number only the server knew, and the only way to
    find out you were over it was to press Save on writing you had already done.

    Characters and bytes are said separately rather than one being passed off as
    the other: the count is UTF-16 code units, which is what the editor this
    copies counts, and the ceiling is UTF-8 bytes.
    """
    from openproj.model import MAX_BODY_BYTES

    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "long.html", 1400,
        _LONG % (MAX_BODY_BYTES // 2, MAX_BODY_BYTES + 1000), budget=6000,
    )

    assert got["under"]["text"] == f"Length: {MAX_BODY_BYTES // 2:,}", got["under"]
    assert not got["under"]["over"], "half the ceiling was drawn as over it"
    assert got["over"]["over"], "a body over the ceiling is not marked as such"
    assert f"of {MAX_BODY_BYTES:,} bytes" in got["over"]["text"], got["over"]["text"]
    assert "too long to save" in got["over"]["text"], (
        "the word is in the element too: a colour on its own is a channel a "
        f"dichromat does not have — {got['over']['text']!r}"
    )
    assert "cannot be saved" in got["over"]["said"], (
        f"and it was never announced: {got['over']['said']!r}"
    )


_DRAFTING = _STUB_RENDER + r"""
const area = document.querySelector('textarea[name=body]');
const key = 'openproj:draft:2:' + document.getElementById('edit').dataset.id;
const held = () => {
  const raw = localStorage.getItem(key);
  return raw === null ? null : JSON.parse(raw).text;
};
const receipt = () => document.getElementById('draftsaved').textContent;
const type = what => { area.value = what; area.dispatchEvent(new Event('input')); };
document.getElementById('toggle').click();
localStorage.removeItem(key);

// The leading edge: the first keystroke of a burst goes in at once, so a tab
// closed a second after somebody starts typing still holds their sentence.
type('the first thing typed');
const first = {held: held(), receipt: receipt()};
// And the second is throttled — the interval seeded on this page is ten seconds,
// which is longer than this whole run.
type('and the second thing');
const throttled = held();
// Then the tab goes.
dispatchEvent(new Event('pagehide'));
const flushed = held();

// A draft that is committed or cancelled stops existing, and the receipt stops
// claiming it.
document.getElementById('cancel').click();
return {first, throttled, flushed, after: {held: held(), receipt: receipt()},
        every: document.getElementById('draftevery').textContent};
"""


def test_a_throttled_draft_is_still_written_before_the_tab_can_be_closed(
    client: TestClient, tmp_path: Path
):
    """Ask 7. The draft used to be written on every keystroke — a whole document
    into `localStorage`, synchronously, per character — and the interval is now
    settable, which is the thing that was asked for.

    A throttle and not a debounce, and this is what tells them apart: the first
    keystroke is written immediately and the last one is flushed when the tab
    goes. A debounce writes nothing at all while somebody types steadily, which
    is exactly the person the draft exists for.
    """
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}").text, _SEED % '{"indent": 2, "autosave": 10}'
        ),
        tmp_path / "draft.html", 1400, _DRAFTING, budget=6000,
    )

    assert got["every"] == "Draft: 10", (
        f"the remembered interval is not the one in the picker: {got['every']!r}"
    )
    assert got["first"]["held"] == "the first thing typed", (
        "the first keystroke of a burst was throttled, so a tab closed a second "
        "later holds nothing"
    )
    assert got["first"]["receipt"] == "draft saved just now", got["first"]["receipt"]
    assert got["throttled"] == "the first thing typed", (
        "the second keystroke was written straight through, so there is no "
        "throttle here at all"
    )
    assert got["flushed"] == "and the second thing", (
        "the throttled write was never flushed, so the last thing typed before "
        "the tab closed is gone"
    )
    assert got["after"]["held"] is None, "cancelling left the draft in storage"
    assert got["after"]["receipt"] == "", (
        f"the receipt still claims a draft that no longer exists: "
        f"{got['after']['receipt']!r}"
    )


_REFUSED = _STUB_RENDER + r"""
const bar = document.getElementById('statusbar');
const area = document.querySelector('textarea[name=body]');
document.getElementById('toggle').click();
// Every control still works, in memory, against a store that throws.
bar.querySelector('button').click();
area.value = 'writing into a browser that keeps nothing';
area.dispatchEvent(new Event('input'));
document.getElementById('view-both').click();
return {
  errors: window.__errors,
  labels: [...bar.children].map(child => child.textContent),
  indent: INDENT.length,
  view: VIEW,
  editor: JSON.parse(JSON.stringify(EDITOR)),
  receipt: document.getElementById('draftsaved').textContent,
  said: document.getElementById('state').textContent,
};
"""


def test_the_editor_preference_is_one_key_and_survives_a_browser_that_refuses_storage(
    client: TestClient, tmp_path: Path
):
    """One key, one JSON object, the version in the name — and a store that
    throws on the property itself, which is what `remembered` exists for and what
    took the whole table down the last time a call was bare.

    The second half is the one worth the test: a receipt that says "draft saved
    just now" over a store that refused the write is this application telling
    somebody their writing is somewhere it is not. That is the branch that
    decides not to act, and this repository has shipped three of them in silence.
    """
    page = client.get(f"/detail/{TASK}").text

    # One key, versioned, and every read and write of it through `remembered`.
    assert page.count("const EDITOR_KEY = 'openproj:editor:1';") == 1
    assert "remembered.map(EDITOR_KEY)" in page
    assert "remembered.set(EDITOR_KEY, JSON.stringify(EDITOR))" in page
    assert not re.search(r"localStorage\.\w+\('openproj:editor", page), (
        "a bare localStorage call for the preference"
    )

    got = measured_in(
        chrome(), _before_the_page_runs(page, _NO_STORE), tmp_path / "denied.html",
        1400, _REFUSED, budget=6000,
    )

    assert got["errors"] == [], f"the page threw against a refusing store: {got['errors']}"
    assert got["labels"][1] == "Spaces: 4" and got["indent"] == 4, (
        f"the picker did not move against a store that will not keep it: {got['labels']}"
    )
    assert got["view"] == "both" and got["editor"]["mode"] == "both"
    assert got["receipt"] == "this browser is not keeping drafts", (
        f"a draft that was never stored was reported as stored: {got['receipt']!r}"
    )
    assert "will not keep an unsaved draft" in got["said"], (
        f"and it was never announced: {got['said']!r}"
    )


_STICKY = _STUB_RENDER + r"""
const article = document.querySelector('article.entity');
const mode = () => VIEW;
// Reading a record is the ordinary case on this page, so a remembered mode does
// not open one as a screen-filling editor.
const atLoad = {view: mode(), full: article.classList.contains('full'),
                editing: article.classList.contains('editing')};
document.getElementById('toggle').click();
const afterEdit = {view: mode(), full: article.classList.contains('full')};
// And leaving the session is not a choice about how to look at documents.
document.getElementById('cancel').click();
const afterCancel = {view: mode(), stored: JSON.parse(localStorage.getItem('openproj:editor:1'))};
// A segment IS a choice.
document.getElementById('toggle').click();
document.getElementById('view-edit').click();
return {atLoad, afterEdit, afterCancel,
        chosen: JSON.parse(localStorage.getItem('openproj:editor:1')).mode};
"""


def test_the_view_a_person_chose_is_the_one_the_next_session_opens_in(
    client: TestClient, tmp_path: Path
):
    """The third field of the preference, and two arguments inside it.

    Sticky at LOAD would mean that after once choosing the split, every detail
    page anybody opened afterwards opened as a full-screen editor over a record
    they had come to read. So it is restored when an editing session begins.

    And leaving a session is not a choice about how to look at documents: Cancel
    goes through `showView`, which does not write the preference, or somebody who
    edits, cancels and edits again would have lost the split by using it.
    """
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}").text, _SEED % '{"mode": "both"}'
        ),
        tmp_path / "sticky.html", 1400, _STICKY, budget=6000,
    )

    assert got["atLoad"] == {"view": None, "full": False, "editing": False}, (
        f"a remembered mode opened a record somebody came to read as a "
        f"full-screen editor: {got['atLoad']}"
    )
    assert got["afterEdit"] == {"view": "both", "full": True}, (
        f"pressing Edit did not restore the remembered view: {got['afterEdit']}"
    )
    assert got["afterCancel"]["view"] is None
    assert got["afterCancel"]["stored"]["mode"] == "both", (
        "Cancel was read as a preference for no surface, so using the split once "
        "and cancelling takes it away"
    )
    assert got["chosen"] == "edit", "pressing a segment did not remember it"


_ONE_FACE = """
const area = document.querySelector('textarea[name=body]');
const gutter = document.querySelector('.gutter');
document.getElementById('toggle').click();
return {
  box: getComputedStyle(area).fontFamily,
  gutter: getComputedStyle(gutter).fontFamily,
  size: [getComputedStyle(area).fontSize, getComputedStyle(gutter).fontSize],
  height: [getComputedStyle(area).lineHeight, getComputedStyle(gutter).lineHeight],
};
"""


def test_the_box_and_the_column_beside_it_are_one_face(client: TestClient, tmp_path: Path):
    """Asked of Chrome because a shorthand is what decides it.

    The box and the gutter are one declaration, and they have to be: `--gutter`
    is written in `ch`, and `ch` is resolved in the font of whoever uses the
    value — the column resolves it, and so does the box's own `padding-left`. The
    declaration is in `_EDITING_STYLE` now, which is concatenated after each of
    the two stylesheets that carry it, and on the detail page that ORDER is the
    whole of the answer: `input.field, select.field, textarea.field { font:
    inherit }` is the same weight and sets the same two properties through a
    shorthand.

    `tests/cascade.py` cannot see that conflict — it records a property under the
    name it is written under, so `font` and `font-family` are two properties to
    it and one to a browser. That is why this is here and not there.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "face.html", 1400,
        _ONE_FACE, budget=4000,
    )

    assert "mono" in got["box"].lower(), (
        f"the box resolved to {got['box']!r} — the sans face won, so `--gutter` is "
        "one width in the column and another in the box's own padding"
    )
    assert got["box"] == got["gutter"], f"{got['box']!r} beside {got['gutter']!r}"
    assert got["size"][0] == got["size"][1], got["size"]
    assert got["height"][0] == got["height"][1], got["height"]
