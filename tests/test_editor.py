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
from test_web import ANN, PATH, SECRET, SEED, TASK

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

    entities, config = load_repo(Path("seed"))
    render_static(build_index(entities, config, date(2026, 8, 17)), tmp_path)

    assert "EventSource" not in (tmp_path / "index.html").read_text()


def test_the_editing_instructions_appear_with_the_mode(client: TestClient):
    """Hidden until Edit dependencies is pressed, and hidden again on the way
    out — an instruction for a mode you are not in is noise on every visit."""
    page = client.get("/graph").text

    assert re.search(r'<p class="hint" id="howto" hidden>', page)
    assert "getElementById('howto').hidden = !connecting" in page


def test_the_parent_control_still_holds_the_id(client: TestClient):
    """The facts list reads it as a linked title; the input underneath is what
    gets written, and the file stores an id. Showing the title in the control
    would write the title into the file on the next save."""
    page = client.get(f"/detail/{TASK}").text
    control = re.search(r'<input name="parent"[^>]*value="([^"]*)"', page)

    assert control, "parent must still be editable"
    assert control.group(1).startswith(("proj-", "pitch-", "task-")) or control.group(1) == ""


def test_a_betting_cell_saves_only_what_somebody_typed(client: TestClient):
    """The bet table's fields are inputs from the start, so blur is not evidence
    of a decision: the browser restores form values across a reload, autofills,
    and the people picker rewrites a field to add its separator. All three used to
    reach git — one of them emptied an assignees list nobody had touched."""
    page = client.get("/cycle/37").text
    live = re.search(r"for \(const input of document\.querySelectorAll\('#bets input\.live'\)\)"
                     r".*?\n\}", page, re.S).group(0)

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

    assert re.search(r"setInterval\(\(\) => \{ if \(PENDING\.size \|\| ROSTER_DIRTY\)"
                     r" flush\(true\); \}, 120000\);", page)
    # And the browser's own warning, which is the only thing that can stop a tab
    # closing on unsaved work.
    assert "addEventListener('beforeunload'" in page
    assert "event.returnValue = ''" in page


def test_capacity_moves_while_the_rate_is_being_typed(client: TestClient):
    """Left to the next page load, the number somebody is setting is invisible at
    the moment they are setting it — which is most of the moment that matters."""
    page = client.get("/cycle/37").text

    assert "function recount()" in page
    assert re.search(r"if \(event\.target\.matches\('input\.rate, \[name=build_weeks\]'\)\)"
                     r" recount\(\);", page)


def test_a_new_cycle_starts_from_the_last_one_s_roster(client: TestClient, repo_path: Path):
    """A team changes slowly and availability changes every cycle, so the people
    who worked the last one are a starting point to correct — which beats
    retyping fifteen names to change three of them."""
    from test_web import git_head

    client.put(
        "/api/cycle/50",
        json={"base_commit": git_head(repo_path),
              "fields": {"starts_on": "2027-06-07", "build_weeks": 4,
                         "availability": {"cy": 0.5, "ann": 1.0}}, "body": None},
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
    assert "area.value.replace(" in send
    assert "response.ok ? `![${alt}](${answer.path})` : ''" in send
