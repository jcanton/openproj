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
from fastapi.testclient import TestClient
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


def test_edit_and_save_follow_the_thing_they_commit(page: str):
    """Edit sat above the title, so on an entity with a shaping doc the action was
    a scroll away from every field it acted on. The bar is sticky and it is the
    same bar the cycle page and the create page carry, because three answers to
    "have I saved this yet" is three ways to close a tab with work in it."""
    assert page.index('id="commitbar"') > page.index('<dl id="facts">')
    assert page.index('id="commitbar"') > page.index('class="field body-field"')
    assert re.search(r"\.commitbar \{[^}]*position: sticky; bottom: 0", page, re.S)
    assert '<p class="editbar">' not in page, "the bar it replaced"
    # And both buttons are in it, so Cancel is never somewhere else from Save.
    bar = re.search(r'<div class="commitbar".*?</div>', page, re.S).group(0)
    assert 'id="toggle"' in bar and 'id="save"' in bar


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
    assert "<h2>" in response.json()["html"]
    assert "<em>" in response.json()["html"]


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
    assert "'click what must finish first, then what waits for it'" in page
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


def test_work_is_autosaved_so_a_dropped_connection_costs_two_minutes(client: TestClient):
    page = client.get("/cycle/37").text

    assert re.search(
        r"setInterval\(\(\) => \{ if \(PENDING\.size \|\| ROSTER_DIRTY\)"
        r" flush\(true\); \}, 120000\);",
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
    the moment they are setting it — which is most of the moment that matters."""
    page = client.get("/cycle/37").text

    assert "function recount()" in page
    assert re.search(
        r"if \(event\.target\.matches\('input\.rate, \[name=build_weeks\]'\)\)"
        r" recount\(\);",
        page,
    )


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
    hint = re.search(r"(\d+) people carried from cycle\s+(\d+)", page)
    assert hint and (hint.group(1), hint.group(2)) == ("2", "50")


def test_an_image_can_be_pasted_or_dropped_into_the_body(client: TestClient):
    """This is a handler on the textarea, not an editor feature. CodeMirror would
    not have brought it — paste and drop are DOM events, and a plain textarea
    receives them exactly the same way."""
    for path in (f"/detail/{TASK}", "/new"):
        page = client.get(path).text
        assert "function attachUploads(area, status)" in page, path
        assert "attachUploads(BODY, document.getElementById('upload'));" in page, path
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
    assert "replaceRange(area," in send
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
    the next read "appetite_weeks: a ready pitch needs an appetite", from the same
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


def test_no_script_ever_assigns_a_textarea_its_value(client: TestClient):
    """`textarea.value = …` wipes the browser's native undo stack. Paste a diagram
    into a four-hundred-line pitch, press ctrl-Z, and the last ten minutes are
    gone. Every programmatic edit goes through `replaceRange`, which uses
    `execCommand('insertText')` — deprecated, and still the only API in any
    shipping browser that edits a textarea as though a person had typed."""
    page = client.get(f"/detail/{TASK}").text
    helpers = re.search(r"function replaceRange.*?\n\}", page, re.S).group(0)
    # Everything that edits the body while somebody is working in it. A draft
    # restored at page load is not in scope: there is no history to protect yet,
    # and it replaces the whole field rather than part of it.
    editing = re.search(r"const FORMATS = \[.*?\n\}\n", page, re.S).group(0)
    editing += re.search(r"function attachUploads.*?\n\}\n", page, re.S).group(0)

    assert "document.execCommand('insertText', false, text)" in helpers
    assert "area.value =" not in editing, "only the fallback inside replaceRange may assign"
    assert "replaceRange(area" in editing, "and it is what the editing code calls"


def test_the_toolbar_carries_what_this_team_writes(client: TestClient):
    """Counted across the seed and migrated corpora: 485 lines carry an inline
    code span, 161 a bullet, 124 a heading, 83 bold — and eight a markdown link,
    which is why there is no link button: people write `C2SM/icon4py#1364` bare
    and the renderer already links it.

    The two code buttons are here for a better reason than frequency. The team
    types on a mix of US and Swiss-German layouts, and on CH a backtick is a dead
    key, so a fence is three of them in a row — the two fenced blocks in the whole
    corpus measure how awkward that is, not how little code people would paste."""
    page = client.get(f"/detail/{TASK}").text
    marks = re.search(r"const FORMATS = \[(.*?)\];", page, re.S).group(1)

    assert marks.count("{key:") == 7
    for wanted in ("Bold", "Italic", "Code  ", "Code block", "Heading", "Bullet", "Quote"):
        assert wanted in marks, wanted
    assert "](" not in marks, "bare PR references are already linked by the renderer"


def test_a_fence_takes_whole_lines_of_its_own(client: TestClient):
    """A fence only opens a block if nothing shares its line, so wrapping a
    selection in place would produce three paragraphs of literal backticks."""
    page = client.get(f"/detail/{TASK}").text
    fence = re.search(r"if \(mark\.fence\) \{.*?\n    return;\n  \}", page, re.S).group(0)

    assert "const [from, to] = lineRange(area);" in fence
    assert "'```\\n' + chosen + '\\n```'" in fence
    assert "area.setSelectionRange(from + 3, from + 3)" in fence, "the caret lands on the language"
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

    bound = "button.onmousedown = event => { event.preventDefault(); applyMark(area, mark); };"
    assert bound in page
    assert "button.onclick" not in page.split("const FORMATS")[1][:2000]
