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

# The plain box, asked for by name, on every test that is ABOUT the plain box.
#
# Ace is what a writer gets since 2026-08-20 — jcanton, "make ace the default, I
# think it's worth it" — so an address that says nothing now means the other
# surface. Every test below that drives a `<textarea>` in a browser used to rest
# on that silence and now says which surface it means; the ones that only read the
# markup are surface-agnostic and deliberately keep the default, so the page a
# writer actually gets is still the one most of this file is looking at.
PLAIN = "?editor=plain"


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


def test_the_plain_box_carries_no_editor_library_at_all(client: TestClient):
    """This used to be `test_the_editor_pulls_in_no_library_at_all`, and its
    docstring said: "If this ever fails, somebody has added an editor dependency
    and should have to argue for it."

    Somebody has, twice. Ace 1.44.0 is vendored — `static/VENDOR.md` carries the
    search, the price and the argument — and then on 2026-08-20 it moved to the
    default side of the parameter. Both times the old test would have passed
    **unchanged**, because it was a check on the string `codemirror`: it would
    have caught the library that was refused and never the one that was taken. A
    name check is not an argument.

    What this holds is the way OUT: `?editor=plain` and the page has no editor
    bytes of any kind in it, fetches nothing, and reaches no CDN. The other half
    of who pays — a reader the server would refuse a save from, who gets no
    library whatever the address says — cannot be asked here and is asked where
    it can be: `--auth dev` invents a login for every request, so `may_write` is
    true on this fixture whatever the cookie says, and dropping the cookie proves
    nothing. `test_a_reader_who_may_not_write_is_sent_no_editor_library` in
    `tests/test_render.py` calls the renderer with `may_write=False` directly.

    **And the CodeMirror clause is now a measurement rather than a slogan.**
    `keybinding-vim.js` contains the string once — Ace's vim keymap is a port of
    CodeMirror's and ships a `CodeMirror` compatibility object — so a page that
    carries Ace carries that name too, and asserting its absence over the default
    page would be asserting that Ace is not there while saying something else.
    What is actually still true is that neither CodeMirror is a dependency here:
    `docs/EDITOR.md` refuses CM6 on a fifty-one-import linker and CM5 on an
    archived upstream, and the page below has no editor bytes of any kind in it.

    The page that DOES carry Ace is held to its own rules in
    `test_the_second_editor_is_inlined_checksummed_and_named` beside this.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text
    assert "codemirror" not in page.lower()
    assert not re.search(r"<script[^>]+src=", page)
    assert "cdn." not in page
    assert "ace.define" not in page, (
        "a writer who said `?editor=plain` in the address was sent 594 KB of editor "
        "anyway, so the way out of the default does not work"
    )
    # The control, and it is the half that makes the assertion above evidence
    # rather than a test of a parameter nothing reads: the same page with nothing
    # said does carry it, because that is what jcanton asked for on 2026-08-20.
    assert "ace.define" in client.get(f"/detail/{TASK}").text, (
        "Ace is the default for a writer and this page has none of it"
    )


def test_the_second_editor_is_inlined_checksummed_and_named(client: TestClient):
    """And the page that asked for it, held to the same four rules the refusal
    was written out of: inlined rather than fetched, checksummed, licensed, and
    named where a person will find it.

    The last one is the one a grep cannot fake. `static/VENDOR.md`'s "What is
    deliberately not here" section said "No editor library" for as long as that
    was true; a commit that vendors one and leaves that sentence standing has
    made the file lie about the repository it documents.
    """
    import hashlib

    from openproj.render import _static_dir

    page = client.get(f"/detail/{TASK}?editor=ace").text
    assert "ace.define" in page, "?editor=ace did not put the editor in the page"
    assert not re.search(r"<script[^>]+src=", page), "an editor that fetches is not inlined"
    assert "cdn." not in page

    static = _static_dir()
    sums = dict(
        reversed(line.split(maxsplit=1))
        for line in (static / "SHA256SUMS").read_text().splitlines()
        if line.strip()
    )
    note = (static / "VENDOR.md").read_text(encoding="utf-8")
    for name in ("ace.js", "keybinding-vim.js"):
        assert name in sums, f"{name} ships in a page and is checksummed nowhere"
        digest = hashlib.sha256((static / name).read_bytes()).hexdigest()
        assert digest == sums[name].strip(), name
        assert name in note, f"{name} is inlined and undocumented"
        assert (static / name).read_text(encoding="utf-8")[:200] in page

    # BSD-3 clause 2 asks for the notice in a binary redistribution, and this
    # repository already reads "every rendered page is a copy" that way for
    # Inter. The minified files carry no notice at all — upstream strips it — so
    # a page that inlines them and says nothing has redistributed without it.
    assert "Ajax.org" in page and "BSD-3-Clause" in page
    assert "ace-LICENSE.txt" in note and "BSD-3-Clause" in note
    # And the file that said there was no editor library says what there is now.
    assert "No editor library" not in note.split("## What is deliberately not here")[1]


def test_the_way_in_is_at_the_top_and_the_two_ways_out_are_together(page: str):
    """All three in one place, at the top — jcanton, 2026-08-20.

    They were split: Edit at the head of the record and Save and Cancel in a
    sticky bar at its foot. Both halves were argued for and both arguments were
    about reachability, which the stickiness had already settled — what the split
    actually decided was that the three controls which begin, end and abandon one
    edit were in two places, a shaping document apart.

    Still sticky, so it is still reachable from the bottom of a long record; stuck
    to the top, which is where it now is. `bottom: auto` matters as much as `top`:
    with both set the browser keeps the first and the bar stays at the foot.

    The rule is the SHELL's `.commitbar` since 2026-08-20 and this asks for it by
    that name. It was `#commitbar { top: 0; bottom: auto }` in `_DETAIL_STYLE`,
    which four pages load and only one of them had moved its bar — so the create
    form and the cycle page silently lost `bottom: 0` while keeping their bar last
    in the markup, and ended up stuck to neither edge. An id override beating a
    shell rule on some of the pages that load it is this repository's
    characteristic failure, and the fix was to make the shell say the true thing
    once. Which rule actually wins is resolved by name in `tests/test_cascade.py`.
    """
    assert page.index('id="commitbar"') < page.index('<dl id="facts">')
    assert page.index('id="commitbar"') < page.index('class="field body-field"')
    assert re.search(r"\.commitbar \{[^}]*position: sticky; top: 0; bottom: auto", page, re.S), (
        "the bar is not stuck to the top, or is stuck to both"
    )

    bar = re.search(r'<div class="commitbar".*?</div>', page, re.S).group(0)
    assert 'id="save"' in bar and 'id="cancel"' in bar
    # Edit stays its own control: it is the way IN, and a button that is Edit and
    # Cancel by turns puts the way out under whatever you were doing.
    assert 'id="toggle"' not in bar, "the way in is not one of the ways out"
    assert page.index('id="toggle"') < page.index('id="commitbar"')
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
    # Nor is the status, and it is not a chip here at all any more: the facts
    # column draws it as a ball on a hill, which is also the control that sets it.
    # It was a chip in this line AND a chip forty pixels below it, the same word in
    # the same colour twice, one of them inert. A field that can be changed is
    # stated where it can be changed, and drawn in the one way a word cannot be —
    # `shaping` and `in_progress` are one rung apart in a list and opposite sides
    # of a hill.
    assert '<span class="chip st-' not in detail, (
        "the status is a hill on this page, and a chip is the thing it replaced"
    )
    facts = detail.index('<dl id="facts">')
    assert facts < detail.index('data-hill="entity"') < detail.index("</dl>", facts)

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
    for field in ("owner", "assignees", "reviewers", "priority", "cycle"):
        assert named[f"{TASK}-{field}"] == LABELS[field], field

    # Status is the exception and has to be: its control is a group of radios, and
    # a `<label for>` can name exactly one element — pointing it at one stop of
    # five would tell a screen reader that "Status" is the word for `shaping`. The
    # group carries the name instead, which is the same fix by the other route.
    assert f"{TASK}-status" not in named
    assert 'role="radiogroup" aria-label="Status"' in page

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
    drafted_on = client.get(f"/detail/{TASK}{PLAIN}").text

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
    reopened = client.get(f"/detail/{TASK}{PLAIN}").text
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

    reopened = client.get(f"/detail/{TASK}{PLAIN}").text
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


def _without_the_library(page: str) -> str:
    """The page minus the vendored editor's own bytes.

    Ace has a `<textarea>` of its own — 2.5x1 CSS px, opacity 0, parked at the
    caret — and reads `.value` off it in a dozen places, which is Ace's business
    and not this application's. Cut by reading the files out of `static/` rather
    than by matching a marker, so a re-vendoring cannot leave the guard scanning
    bytes it was never meant to judge, and a guard scanning nothing at all is
    caught by the length check below.
    """
    from openproj.render import _static_dir

    for name in ("ace.js", "keybinding-vim.js"):
        body = (_static_dir() / name).read_text(encoding="utf-8")
        assert body in page, f"{name} is not inlined in the page this is cutting it from"
        page = page.replace(body, "")
    return page


_ACE_OPENS = "// --- Ace, as the same surface ---"
_ACE_CLOSES = "// --- end of Ace as a surface ---"


def _ace_surface_source(page: str) -> str:
    """The one region of a page that knows the document may be in Ace.

    Delimited by its own banners for the same reason the textarea's is: a guard
    that names a function moves out of step with the code the day somebody
    renames it, and a guard that names a banner takes the banner with it.
    """
    opens = page.index(_ACE_OPENS)
    closes = page.index(_ACE_CLOSES, opens)
    return page[opens:closes]


def _shared_editing_source(page: str) -> str:
    """Everything in the shared block that is NOT the textarea surface.

    Defined by subtraction, and that is the whole point of the spelling. The
    previous window was `const FORMATS = \\[.*?\\n\\}\\n` — non-greedy, so it
    stopped at the first closing brace after the mark table and never once
    reached `applyMark`, which is the largest thing in this block that writes to
    the document. A guard that names the functions it checks goes out of step
    with the code the day somebody adds one; a guard that says "the surface, and
    then everything else" cannot.
    """
    opens = page.index(_SURFACE_CLOSES)
    closes = page.index("</script>", opens)
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

    **`?editor=plain`, and it is not the default's absence — it is the only page
    a substring scan can answer this on.** Ace's own minified bytes contain
    `this.textarea.value`, `area.value` and half a dozen more of these names, and
    a scan over text cannot tell a library's internals from application code. So
    the page whose entire script is ours is the one asked, and the page that
    carries the library is asked separately below, with the library cut out of it
    by `_without_the_library` — which is the same question and a different
    method, kept apart on purpose rather than merged into a looser pattern.
    """
    for path in (f"/detail/{TASK}{PLAIN}", f"/new{PLAIN}"):
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

    # And the same page with the second editor in it. The boundary is worth
    # nothing if a second surface is where it leaks — `ace.edit(BODY)` REMOVES
    # the textarea from the DOM and from the form, and the sibling arrangement
    # this ships instead leaves a stale box in the page that anything could still
    # read. The Ace surface is handed the document by the textarea surface rather
    # than reading it, so this stays literally one place.
    with_ace = _without_the_library(client.get(f"/detail/{TASK}?editor=ace").text)
    rest = with_ace.replace(_surface_source(with_ace), "")
    for reach in ("BODY.value", "BODY.selectionStart", "BODY.setSelectionRange",
                  "area.value", "area.selectionStart", "area.setSelectionRange"):
        assert reach not in rest, (
            f"`{reach}` is in the page that carries the second editor, outside the one "
            "place allowed to read a textarea — and on that page the textarea is stale"
        )
    ace_surface = _ace_surface_source(with_ace)
    assert "function aceSurface(area, seeded)" in ace_surface
    assert "aceSurface(area, box.text())" in with_ace, (
        "the second surface is not seeded through the one place that reads the box"
    )

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


def test_the_second_surface_never_sets_or_replaces_the_whole_document(client: TestClient):
    """The rule the Ace binding exists to obey, read off the shipped page.

    `session.setValue()` is remove-all-then-insert-all: two change events with an
    EMPTY DOCUMENT between them. Measured, `setValue` of a document onto itself
    reports `deleted=1532, inserted=1532`, and no prefix/suffix walk can recover
    a splice from `""` against a whole document. `session.replace(Range, text)` —
    the API the first design recommended as "strictly better, splices in place" —
    is **also** remove-then-insert, two change events, and a handler reading the
    document between them sees a state that never existed on either side.

    What that costs is not an abstraction: one remote four-character keystroke
    reflected that way made a PASSIVE tab push a 97,890-character body up the
    socket and take the authorship credit for it. `Room.credits`' "authored by
    whoever typed the most" becomes "authored by whoever reflected last".

    So: `Document.remove` and `Document.insert`, bounded, and nothing else. The
    one `setValue` is the seeding call, which happens on construction before
    anything observes the document, and it is asserted to be the only one rather
    than exempted by a comment.
    """
    page = client.get(f"/detail/{TASK}?editor=ace").text
    surface = _ace_surface_source(page)

    assert "session.setValue(" not in surface, (
        "the second surface sets the whole document, which is remove-all-then-"
        "insert-all with an empty document between the two change events"
    )
    assert "session.replace(" not in surface and ".replace(Range" not in surface
    assert surface.count("editor.setValue(seeded, -1);") == 1
    # Over the CODE and not over the prose: the block argues at length about the
    # two APIs it refuses, and a count that included the argument would go up
    # every time somebody explained it better.
    code = "\n".join(
        line for line in surface.splitlines() if not line.lstrip().startswith("//")
    )
    assert code.count("setValue") == 1, (
        "there is more than one whole-document write in the second surface"
    )
    # The write, and both halves of it bounded by a range built from the index.
    assert "document_.remove(Range.fromPoints(positionOf(from), positionOf(to)))" in surface
    assert "document_.insert(positionOf(from), put)" in surface
    # And the re-entrancy flag, which is the whole difference between reflecting
    # somebody's keystroke and pushing the document back up the socket under your
    # own name: every other surface fires its change event for its own edits and
    # a person's alike, indistinguishably.
    assert "session.on('change', delta => {\n    if (applying) return;" in surface, (
        "the second surface hears its own writes, so a remote keystroke comes back "
        "up the socket as this tab's typing"
    )
    # The five commands that fetch a module over the network, by name.
    for command in ("'find'", "'replace'", "'showSettingsMenu'",
                    "'goToNextError'", "'goToPreviousError'"):
        assert command in surface, f"{command} still reaches config.loadModule"
    assert "removeCommand" in surface
    # And the line-ending boundary, which is the case no length or index check
    # can see: `"a\nb\rc\nd"` comes back the same length and different bytes.
    assert "document_.setNewLineMode('unix');" in surface


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
    exactly why nobody noticed.

    **And then widened again, because the scope was still a list of names.** It
    read `const FORMATS = \\[.*?\\n\\}\\n`, which is non-greedy and stops at the
    first closing brace after the mark table: `applyMark` — the biggest write
    path in the block and the newest — was four functions past the end of the
    window, so a mutation of it left this green. The window is the surface
    subtracted from the shared block now, which is the rule itself rather than a
    list that goes stale.

    `splice` under `apply` still assigns `.value` inside the implementation,
    which is the one place allowed to. What that costs — the browser's undo stack,
    on every remote keystroke — is answered by `Y.UndoManager` in `_COEDIT` and
    by the two buttons that reach it, not by moving this assignment.
    """
    page = client.get(f"/detail/{TASK}").text
    helpers = _surface_source(page)
    # Everything that edits the body while somebody is working in it — the whole
    # of the shared block below the surface, plus the room, which is the caller
    # that had a `.value` assignment in it all along. A draft restored at page
    # load replaces the whole field rather than part of it, and it says so
    # through `splice(0, length, …)` inside `apply` rather than by writing to the
    # box behind the boundary's back.
    editing = _shared_editing_source(page) + _coedit_source(page)
    # The window is derived, so it is asserted to contain the things it is
    # supposed to be judging. A guard scanning nothing passes for ever, and the
    # spelling this replaced was scanning a window that stopped four functions
    # short of `applyMark` — the largest write path in the block, and the newest.
    for named in ("function applyMark", "function indentLines", "function attachEditing",
                  "function attachUploads", "function historyOf"):
        assert named in editing, f"the guard's window does not contain {named}"

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

    Two deliberate departures, each of which this test pins: two code buttons,
    because a backtick is a dead key on a Swiss-German layout and a fence is
    three in a row; and no comment button, which is a HackMD collaboration
    feature with nothing behind it here.

    **Sixteen now, not fourteen.** Undo and redo are the leftmost group in the
    shot and they were held back until there was a history for them to reach:
    in a live room every keystroke of somebody else's arrives as an assignment
    to `.value` and destroys the browser's stack, so a history button was a
    button that did nothing the moment a second person joined. `Y.UndoManager`
    is what answers that, and they are the first two entries here now.
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
        "Undo", "Redo",
        "Bold", "Italic", "Strikethrough", "Heading",
        "Code", "Code block", "Quote", "Bullet list", "Numbered list", "Check list",
        "Link", "Image", "Table", "Horizontal rule",
    ]
    # Where the rules fall, and not merely how many there are: a separator in the
    # wrong place groups the buttons into a claim about them that is false.
    assert [i for i, entry in enumerate(entries) if "group: true" in entry] == [2, 6, 12]
    assert "comment" not in marks.lower(), "a collaboration feature with nothing behind it"
    # And the two that are not marks say so in the table rather than being told
    # apart by their titles: `applyMark` never sees one, and neither does the
    # keyboard branch that applies one.
    assert [i for i, entry in enumerate(entries) if "history:" in entry] == [0, 1]
    for entry in entries[2:]:
        assert "history:" not in entry, entry
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
//
// Two presses, and the order is the one the handler documents: a session now
// starts in a full-page view, so the first Escape leaves that — "what a person
// pressing Escape in a screen-filling editor means" — and the second opens the
// Tab hatch. On a page with no view up the first press opens it, which is what
// the third assertion below still shows.
set('alpha', 0, 0);
press('Escape');
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "tab.html", 1200, _TABBING
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

// One press of Ctrl+Z gives the whole mark back, and this is the only question
// that can tell `replaceRange` apart from an assignment to `.value`. Both leave
// exactly the same characters in the box — every assertion above passes either
// way — and only one of them leaves a stack behind it for the person who
// pressed the button and then changed their mind.
//
// Two words seeded, not one, so "one step back" is distinguishable from
// "everything gone": a mark that went in as three separate writes would undo to
// `alpha`, and an empty stack leaves the marked text sitting there untouched.
// `set()` assigns `.value` on purpose — that is what clears the stack down to a
// known floor, so the only entry on it is the one `applyMark` just made.
//
// Both shapes, because they are different branches taking different paths into
// the surface: `mark.insert` splices at a collapsed caret after the line, and
// the wrap tail splices over the selection.
apply('Table', 'alpha beta', 10, 10);
document.execCommand('undo');
const undoneTable = area.value;
apply('Bold', 'alpha beta', 0, 5);
document.execCommand('undo');
const undoneBold = area.value;

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

return {fenced, afterFence, emptyBold, insideBold, undoneTable, undoneBold,
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
    in `applyMark` rather than a wrap with newlines in it.

    **And it presses undo, which every assertion here used to be blind to.** The
    twenty text assertions below say what ends up in the box; a mark written by
    assigning `.value` puts exactly the same characters there and destroys the
    browser's undo stack on the way, which is this application's oldest
    data-loss invariant. The static guard cannot see it either — `applyMark`
    writes through `surface.splice`, whose only implementation is inside the
    surface block that guard subtracts on purpose. Measured: a `.value` splice
    put into that branch left the guard and all twenty assertions passing.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "marks.html", width, _MARKING
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

    # And the invariant the whole toolbar rests on, asked of the browser rather
    # than of the source. `test_no_script_ever_assigns_a_textarea_its_value`
    # cannot reach this: `applyMark` writes through `surface.splice`, and the
    # one implementation of `splice` lives inside the surface block — the one
    # region that guard deliberately subtracts, because the remote-update path
    # in there is allowed to assign. So the branch a person's press goes down is
    # visible to nothing static, and a `.value` write put into it leaves the
    # source guard and all twenty text assertions above green. Only pressing
    # undo can see it.
    assert got["undoneTable"] == "alpha beta", (
        "one undo did not take the table back out: the mark was written by "
        "assigning `.value`, which wipes the stack Ctrl+Z reaches, so pressing "
        f"a button costs whatever was typed before it — {got['undoneTable']!r}"
    )
    assert got["undoneBold"] == "alpha beta", (
        "one undo did not take the wrap back off, and a wrap is the shape "
        f"eleven of the sixteen buttons use — {got['undoneBold']!r}"
    )

    assert got["linked"] == {"text": "read [the notes](https://example.org/a?b=c)", "taken": True}
    assert got["tabled"] == {"text": "| a | b |\n| --- | --- |\n| c | d |", "taken": True}
    assert got["plain"]["taken"] is False, "an ordinary paste was taken over"
    assert got["bare"]["taken"] is False, "prose over a selection is not a link"

    assert got["picker"] == {"type": "file", "accept": "image/*"}, (
        "the image button did not reach the upload path paste and drop use"
    )
    assert "![" not in got["wrote"], "and it wrote markdown into the box instead"
    assert got["bar"] == {
        "buttons": 16,
        "rules": 3,
        "before": ["Bold", "Code", "Link"],
        "rows": 1,
    }, "the drawn toolbar is not the shot's four groups, on one row"

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

    A session no longer STARTS in that state, which is the one thing here that
    changed: pressing Edit lands in `edit` unless a remembered mode says
    otherwise. jcanton, 2026-08-21 — "entering edit mode the first time opened the
    editor without having selected one of the three... it looked different and
    then jumped to fit width when I clicked one of them". The state is still real
    and still reachable, three ways, and the three of them are asserted below.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "views.html", 1400, _VIEWING
    )

    assert got["editing"] == {
        "classes": ["full", "view-edit"], "pressed": ["edit"],
        "box": True, "pane": False, "marks": True, "position": "fixed",
    }, "pressing Edit does not land in one of the three views"

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
// Pressing Edit lands in the `edit` VIEW now, which is full page — and the
// handle is deliberately not drawn there. The state this asks about is the
// ordinary page with a session open, which is one press of the lit segment away.
seg('edit').click();
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


# The handle between the two panes, driven the way a hand drives it. Everything
# here is geometry, selection and keys, so all of it is asked of Chrome and none
# of it of `tests/js/drive.js`, where `getClientRects()` answers `[]` for every
# element and the one question this feature turns on — is there a handle drawn —
# would answer "no" for ever.
_DIVIDING = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const split = article.querySelector('.bodysplit');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
const facts = article.querySelector('.panes > .facts');
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 80));

const where = () => ({
  // The one number this whole change is about. `left` and not `width`, because a
  // column that grew leftwards by the amount it moved rightwards would keep its
  // width and still be somewhere else.
  facts: facts.getBoundingClientRect().left,
  box: box.getBoundingClientRect().width,
  pane: pane.getBoundingClientRect().width,
  handle: handle.getBoundingClientRect().left,
  wide: handle.getBoundingClientRect().width,
  now: Number(handle.getAttribute('aria-valuenow')),
  least: Number(handle.getAttribute('aria-valuemin')),
  most: Number(handle.getAttribute('aria-valuemax')),
  says: handle.getAttribute('aria-valuetext'),
});

// Taken hold of in the middle of the handle and moved by `by` pixels, which is
// the gesture: the join should end up exactly that far along, wherever on the
// handle it was grabbed.
const drag = by => {
  const grip = handle.getBoundingClientRect();
  const from = grip.left + grip.width / 2;
  handle.dispatchEvent(new PointerEvent('pointerdown', {
    bubbles: true, cancelable: true, pointerId: 1,
    clientX: from, clientY: grip.top + 40}));
  dispatchEvent(new PointerEvent('pointermove', {
    bubbles: true, pointerId: 1, clientX: from + by}));
  dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 1}));
  return where();
};

const before = where();
const wider = drag(200);
const stored = JSON.parse(localStorage.getItem('openproj:editor:1'));
// Dragged clean off the side of the window, which is what a fast drag is and
// what a clamp exists for: a pane crushed to nothing is a pane nobody can take
// hold of again.
const crushed = drag(innerWidth);
const back = drag(-innerWidth);
const evened = (() => {
  handle.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
  return where();
})();
return {
  before, wider, crushed, back, evened, stored,
  role: handle.getAttribute('role'),
  orientation: handle.getAttribute('aria-orientation'),
  name: handle.getAttribute('aria-label'),
  focusable: handle.tabIndex,
  cursor: getComputedStyle(handle).cursor,
  // The two width handles on this application, and the answer to "two controls
  // that both change widths on one page".
  grip: document.getElementById('grip').hidden,
};
"""


def test_the_facts_column_does_not_move_when_the_join_between_the_panes_does(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-20: "in the side-by-side edit-preview view, can you make
    it possible to horizontally resize the editor vs the preview boxes? keeping
    their total width constant (so they don't move the fields which are displayed
    on their right)".

    The second half of that sentence is the requirement and this is the assertion
    for it: the facts column's left edge, to the pixel, before and after a drag
    that moves 200px of width from one pane to the other.

    **It holds structurally rather than arithmetically**, and that is worth
    knowing about this assertion before trusting it. `.panes` gives `.facts` a
    fixed `20rem` track beside a `minmax(0, 1fr)` one, so no ratio inside
    `.bodysplit` can reach the facts at all — which means nothing that could be
    got wrong INSIDE this feature makes this line fail. Measured, rather than
    assumed: with the handle's `--split` deleted it still passes, and with the
    first track written `minmax(0, max-content)`, `auto` or
    `fit-content(100%)` it still passes. It fails on `min-content 20rem`, which
    is the shape of the defect it is for — the day the column on the right stops
    being a fixed track, the panes start pushing it and this says so.

    The clamp is measured through the gesture that produces it rather than by
    calling the clamp: a drag off the side of the window is what a fast hand does,
    and a pane crushed to nothing is one that cannot be taken hold of again.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "split.html",
        1400, _DIVIDING, patience=4800,
    )

    # It is a separator, it says which way it lies, it has a name, and it can be
    # reached from the keyboard. A splitter that answers only a mouse is the same
    # defect as the thirteen mouse-only toolbar buttons earlier on this branch.
    assert got["role"] == "separator" and got["orientation"] == "vertical"
    assert got["name"] and got["focusable"] == 0, got["name"]
    assert got["cursor"] == "col-resize"

    # Even at rest, and both panes actually drawn.
    before = got["before"]
    assert before["box"] == before["pane"] > 0, before
    assert before["now"] == 50 and before["says"] == "50% writing, 50% preview"

    # THE assertion. Same pixel, and the width really did move.
    for name in ("wider", "crushed", "back", "evened"):
        at = got[name]
        assert at["facts"] == before["facts"], (
            f"the facts column moved from {before['facts']} to {at['facts']} when the "
            f"panes were resized ({name}), which is the one thing that must not happen"
        )
        assert at["box"] + at["pane"] == before["box"] + before["pane"], (
            f"the two panes stopped summing to a constant at {name}: "
            f"{at['box']} + {at['pane']} against {before['box']} + {before['pane']}"
        )

    assert got["wider"]["box"] == before["box"] + 200, (
        f"a 200px drag moved the join to {got['wider']['box']} from {before['box']}"
    )
    assert got["wider"]["pane"] == before["pane"] - 200
    assert got["wider"]["now"] > 50 and got["wider"]["says"].startswith(
        f"{got['wider']['now']}% writing"
    )

    # Neither pane collapses, in either direction, and the floor is the same one
    # from both sides.
    assert got["crushed"]["pane"] == got["back"]["box"] > 0, (
        f"dragged off the edge of the window the panes were "
        f"{got['crushed']['pane']} and {got['back']['box']}"
    )
    assert got["crushed"]["now"] == got["crushed"]["most"]
    assert got["back"]["now"] == got["back"]["least"]

    # And the way back to even, which is the one position a drag cannot be
    # trusted to hit.
    assert got["evened"]["box"] == got["evened"]["pane"] == before["box"]

    # Written down, per browser rather than per document, in the key that already
    # holds this reader's other four editor settings.
    assert got["stored"]["split"] > 1, got["stored"]
    assert got["stored"]["mode"] == "both"

    # The other width handle is not on the screen at the same time. `#grip` drags
    # the reading measure and full page has none, so the page never shows two
    # controls that both change widths.
    assert got["grip"], "the width grip is on screen beside the pane splitter"


@pytest.mark.parametrize("where", ["/detail/{task}", "/new", "/issue/new", "/note/new"])
def test_every_surface_that_splits_carries_the_same_handle(client: TestClient, where: str):
    """One control, four templates — the argument `_VIEW_SEGMENTS` is one constant
    for, applied to the thing between the panes.

    The four pages that inline a body editor are one surface in four places, and a
    fifth copy of a separator is a fifth place for its role, its name and its
    position in the markup to drift. Position is what this reads: the handle has
    to be a grid item of `.bodysplit`, between the box and the rendered pane and
    not before or after both, because the stylesheet places it by track order and
    nothing else.
    """
    page = client.get(where.format(task=TASK)).text
    split = re.search(r'<div class="bodysplit">(.*?)</div>\s*(?:{#-|<p|</div>)', page, re.S)
    assert split, "no split on a page that carries an editing surface"

    assert page.count('id="splitter"') == 1, "one handle, or an id naming two elements"
    inside = split.group(1)
    assert 'id="splitter"' in inside, "the handle is outside the grid it divides"
    assert (
        inside.index("bodywrap") < inside.index('id="splitter"') < inside.index("body-preview")
    ), "the handle is not between the two panes it divides"
    assert 'role="separator"' in inside and 'aria-orientation="vertical"' in inside
    assert 'tabindex="0"' in inside, "a splitter no key can reach"

_SPLIT_BY_KEY = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 80));

const where = () => ({box: box.getBoundingClientRect().width,
                      pane: pane.getBoundingClientRect().width,
                      now: Number(handle.getAttribute('aria-valuenow'))});
const press = key => {
  handle.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
  return where();
};
handle.focus();
const before = where();
const focused = document.activeElement === handle;
const right = press('ArrowRight');
const left = press('ArrowLeft');
const end = press('End');
const past = press('ArrowRight');
const home = press('Home');
const ignored = press('a');
return {before, focused, right, left, end, past, home, ignored,
        stored: JSON.parse(localStorage.getItem('openproj:editor:1')).split};
"""


def test_the_join_between_the_panes_moves_for_the_keyboard_too(
    client: TestClient, tmp_path: Path
):
    """A splitter that answers only a mouse is the same defect as the thirteen
    mouse-only toolbar buttons this branch shipped and had to fix, and it is one
    jcanton's reviewers have already caught once here.

    Both directions, both extremes, and one key that is none of the four — a
    handler that swallowed everything would take a `Tab` out of the tab order and
    an `a` out of the box the moment focus was anywhere near it.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "keys.html",
        1400, _SPLIT_BY_KEY, patience=4800,
    )

    assert got["focused"], "the separator cannot take focus, so no key can reach it"
    assert got["right"]["box"] == got["before"]["box"] + 32, got["right"]
    assert got["left"] == got["before"], (
        f"a press each way did not come back to where it started: {got['left']}"
    )
    # The extremes are the floor, from both sides, and pressing past one does
    # nothing rather than going through it.
    assert got["end"]["pane"] < got["before"]["pane"], got["end"]
    assert got["past"] == got["end"], "ArrowRight went through the end stop"
    assert got["home"]["box"] == got["end"]["pane"] > 0, (
        f"the two extremes are not the same floor: {got['home']} against {got['end']}"
    )
    assert got["ignored"] == got["home"], "a key that is not a nudge moved the join"
    assert got["stored"] == pytest.approx(
        got["home"]["box"] / got["home"]["pane"], rel=1e-6
    ), "the keyboard moved the join without writing down where it left it"


_SPLIT_AT_A_WIDTH = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const facts = article.querySelector('.panes > .facts');
const main = article.querySelector('.panes > .main');
const pane = article.querySelector('#body-preview');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
seg('both').click();
await new Promise(go => setTimeout(go, 80));
const drawn = () => handle.getClientRects().length > 0;
const inTheSplit = {
  handle: drawn(),
  // Beside the document, or under it: the container query this breakpoint is
  // written to agree with, asked as the pixels it produces.
  factsBeside: facts.getBoundingClientRect().left > main.getBoundingClientRect().left + 10,
  // One line down the middle and not two: where the handle draws it, the pane
  // must not, and where the handle is gone the pane must.
  paneBorder: parseFloat(getComputedStyle(pane).borderLeftWidth),
  // And the line the handle draws in its place. Asked of the pseudo-element,
  // which is the only thing that draws it and which `querySelectorAll` cannot be
  // asked about at all.
  handleLine: handle.getClientRects().length
    ? parseFloat(getComputedStyle(handle, '::before').width) : 0,
};
const elsewhere = {};
for (const name of ['edit', 'view']) { seg(name).click(); elsewhere[name] = drawn(); }
seg('view').click();               // out of full page altogether
const outside = drawn();
return {inTheSplit, elsewhere, outside, win: innerWidth};
"""


@pytest.mark.parametrize("width", [1400, 936, 934, 700])
def test_there_is_no_handle_where_there_is_nothing_to_divide(
    client: TestClient, tmp_path: Path, width: int
):
    """Only where it means something: the split view, and only while the facts are
    still a column on the right.

    58.5rem is the width at which `.panes` hands the facts their own track — a
    CONTAINER width of 56rem plus the surface's `1.25rem` of padding on each side
    — and the two flip at the same pixel, which is the point of the number. Below
    it there is no fixed column on the right to hold still, which is the whole of
    what the handle is for, and the two panes are 256px each against a floor of
    240.

    The divider goes with it, both ways round: where the handle draws the line the
    pane must not, and where the handle is gone the pane must — two lines down the
    middle of a split is worse than none.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / f"where-{width}.html", width, _SPLIT_AT_A_WIDTH, patience=4800,
    )
    wide = width >= 936

    assert got["inTheSplit"]["handle"] is wide, (
        f"at {width}px the handle is "
        f"{'missing' if wide else 'drawn'} in the split view"
    )
    assert got["inTheSplit"]["factsBeside"] is wide, (
        f"at {width}px the facts are {'under' if wide else 'beside'} the document, "
        "so this width is no longer the one the breakpoint was written for"
    )
    assert got["inTheSplit"]["paneBorder"] == (0 if wide else 1), (
        f"at {width}px the rendered pane draws {got['inTheSplit']['paneBorder']}px of "
        "border down its left edge and the handle draws one too"
    )
    assert got["inTheSplit"]["handleLine"] == (1 if wide else 0), (
        f"at {width}px the handle draws {got['inTheSplit']['handleLine']}px down the "
        "middle, so the split has no divider at all or two of them"
    )
    assert got["elsewhere"] == {"edit": False, "view": False}, (
        f"a splitter in a view with one pane in it: {got['elsewhere']}"
    )
    assert not got["outside"], "a splitter on the page outside the writing surface"


_SPLIT_REMEMBERED = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
const split = article.querySelector('.bodysplit');
document.getElementById('toggle').click();
await new Promise(go => setTimeout(go, 80));
return {
  view: VIEW,
  box: box.getBoundingClientRect().width,
  pane: pane.getBoundingClientRect().width,
  now: Number(handle.getAttribute('aria-valuenow')),
  held: EDITOR.split,
  // Three tracks and not the `none` an invalid `grid-template-columns` computes
  // to, which is what a `--split` of `wide` would leave behind.
  tracks: getComputedStyle(split).gridTemplateColumns.split(' ').length,
};
"""


@pytest.mark.parametrize(
    "held, wider",
    [(2.5, True), (1, False), ("wide", False), (400, False), (None, False)],
)
def test_the_split_a_reader_chose_is_there_the_next_time(
    client: TestClient, tmp_path: Path, held: object, wider: bool
):
    """Remembered per browser and not per document, for the reason `#grip`'s
    comment gives about the reading measure: it is a property of the screen this
    is being read on, not of the plan. So it is a field of the one editor
    preference — same key, same version, same `remembered` — and it comes back
    when the next session opens the split view.

    The three that are not a ratio are the point of the parametrisation. A stored
    value is a string in a store anybody can hand-edit, and `{"split": "wide"}`
    would reach `minmax(0, wide)` — not a track size, so the whole
    `grid-template-columns` declaration is invalid at computed value time and the
    three tracks compute to `none`. That is the split view with its panes in the
    wrong places rather than a value quietly ignored, which is why the guard is
    `Number.isFinite` and a bound rather than a truthiness test.
    """
    stored = {"mode": "both"} if held is None else {"mode": "both", "split": held}
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % json.dumps(stored)
        ),
        tmp_path / f"held-{held}.html", 1400, _SPLIT_REMEMBERED, patience=4800,
    )

    assert got["view"] == "both", "the remembered view did not open, so nothing was split"
    assert got["tracks"] == 3, (
        f"the grid has {got['tracks']} tracks, so a stored {held!r} reached the "
        "stylesheet and took the template down with it"
    )
    if wider:
        assert got["held"] == held
        assert got["box"] > got["pane"], (
            f"a remembered {held} split came back as {got['box']} to {got['pane']}"
        )
        assert got["now"] == round(100 * held / (1 + held))
    else:
        assert got["held"] == 1, f"{held!r} was taken for a ratio"
        assert got["box"] == got["pane"], (
            f"{held!r} left the panes at {got['box']} and {got['pane']}"
        )


def test_the_pane_splitter_takes_a_focus_ring_that_is_actually_painted(
    client: TestClient, tmp_path: Path
):
    """The same pair of screenshots the editor switch is held to, for the same
    reason: `outline: 2px solid` resolving on the element says nothing about
    paint, and the ring is drawn entirely OUTSIDE the border box — so an
    `overflow: hidden` ancestor throws it away with every assertion about it still
    passing. `article.entity.full` is one, `.panes` is another, and this handle is
    full height inside both of them.

    Two shots of the same page, differing only in which element has focus.
    """
    from browser import screenshot

    browser = chrome()
    page = client.get(f"/detail/{TASK}{PLAIN}").text

    def shot(name: str, focus: str) -> bytes:
        html = tmp_path / f"splitring-{name}.html"
        html.write_text(page.replace(
            "</body>",
            "<script>setTimeout(() => {"
            "  document.getElementById('view-both').click();"
            f" {focus}"
            "}, 900);</script></body>",
        ))
        return screenshot(browser, html, tmp_path / f"splitring-{name}.png", 1400, 900)

    dark = shot("off", "")
    lit = shot("on", "document.querySelector('#splitter').focus({focusVisible: true});")
    assert dark != lit, (
        "focusing the pane splitter changed not one pixel, so the ring the shell "
        "draws for it is being clipped away or is not being drawn at all"
    )


# The join dragged as far as it will go, on a window wide enough that the outer
# fence is what stops it rather than the pixel floor.
_SPLIT_TO_THE_END = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 80));
handle.focus();
handle.dispatchEvent(new KeyboardEvent('keydown', {key: 'End', bubbles: true, cancelable: true}));
return {box: box.getBoundingClientRect().width, pane: pane.getBoundingClientRect().width,
        now: Number(handle.getAttribute('aria-valuenow')),
        most: Number(handle.getAttribute('aria-valuemax')),
        stored: localStorage.getItem('openproj:editor:1')};
"""

# And the same page opened again with exactly what that left behind in the store.
_SPLIT_AS_FOUND = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
document.getElementById('toggle').click();
await new Promise(go => setTimeout(go, 80));
return {box: box.getBoundingClientRect().width, pane: pane.getBoundingClientRect().width,
        held: EDITOR.split, view: VIEW};
"""


@pytest.mark.parametrize("width", [1400, 3440])
def test_the_split_dragged_to_the_end_on_a_wide_screen_is_the_one_that_comes_back(
    client: TestClient, tmp_path: Path, width: int
):
    """A round trip through the store, in two loads, because one load cannot show
    that a value survives being read back.

    **This is a defect with a monitor size attached to it.** The clamp was the
    240px floor alone, so what a drag stored was `(space - 240) / 240` — which
    passes `SPLIT_RANGE` the moment the panes have more than 2,160px between them.
    On a 3440px ultrawide, pushing the preview down to its floor stored `11.57`
    and the next load put that through `EDITOR`'s own `<= SPLIT_RANGE` guard, read
    it as out of range and drew 50/50 — then wrote `1` back over it as soon as the
    split view opened. Not ignored: destroyed, in silence, and only for the people
    with the biggest screens. Verified with a real mouse over DevTools before it
    was fixed, and this is that with `End` instead of a drag.

    1400 is the control. Under 2,584px of window the floor is still the tighter
    bound and nothing about this changes, which is what says the fix is a fence
    and not a new behaviour.
    """
    first = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / f"end-{width}.html", width, _SPLIT_TO_THE_END, patience=4800,
    )
    # It went somewhere, and the separator says it is at the end of its own range.
    assert first["box"] > first["pane"] and first["now"] == first["most"], first

    again = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % first["stored"]
        ),
        tmp_path / f"back-{width}.html", width, _SPLIT_AS_FOUND, patience=4800,
    )
    assert again["view"] == "both", "the remembered view did not open"
    assert (again["box"], again["pane"]) == (first["box"], first["pane"]), (
        f"a split of {json.loads(first['stored'])['split']} chosen at {width}px came back "
        f"as {again['box']} to {again['pane']} instead of {first['box']} to {first['pane']} "
        "— the value the drag wrote is one the next load will not read"
    )


_CANCELLED_DRAG = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 80));
const w = () => ({box: box.getBoundingClientRect().width,
                  dragging: handle.classList.contains('dragging')});
const grip = handle.getBoundingClientRect();
const from = grip.left + grip.width / 2;
handle.dispatchEvent(new PointerEvent('pointerdown', {
  bubbles: true, cancelable: true, pointerId: 1, clientX: from, clientY: grip.top + 40}));
const down = w();
// What the browser sends when it takes the gesture for itself. There is no
// `pointerup` after this one — that is the whole of the case.
handle.dispatchEvent(new PointerEvent('pointercancel', {bubbles: true, pointerId: 1}));
const cancelled = w();
// And the pointer moving afterwards with nothing held down.
dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerId: 1,
  clientX: from + 260}));
return {down, cancelled, after: w(), touch: getComputedStyle(handle).touchAction};
"""


def test_a_drag_the_browser_takes_away_lets_go_of_the_join(
    client: TestClient, tmp_path: Path
):
    """A drag does not always end in a `pointerup`.

    The browser can revoke the pointer — a touch it decides is a pan is the
    ordinary way — and what arrives then is `pointercancel` and nothing else. The
    handler listened for `pointerup` alone, so measured in Chrome before this fix:
    the handle kept `.dragging`, the move listener stayed on the window, and the
    next `pointermove` with nothing held down moved the join 248px. That is the
    handle stuck to the cursor that `setPointerCapture` is there to prevent,
    reached through the one door capture does not close.

    `touch-action: none` is the other half and it is asserted here rather than in
    the cascade file because what matters is the value on the element a finger
    lands on: it is what stops the browser wanting the gesture at all.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "cancel.html", 1400, _CANCELLED_DRAG, patience=4800,
    )
    assert got["down"]["dragging"], "the drag never started, so nothing here is being tested"
    assert not got["cancelled"]["dragging"], (
        "the handle is still drawn as being dragged after the browser cancelled the pointer"
    )
    assert got["after"] == got["cancelled"], (
        f"the join followed the pointer after the drag was cancelled: {got['after']} "
        f"against {got['cancelled']}"
    )
    assert got["touch"] == "none", (
        f"the handle's touch-action is {got['touch']}, so a finger dragging it is a "
        "gesture the browser is free to take away"
    )


_MODIFIED_KEYS = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 80));
handle.focus();
const press = (key, mod) => {
  const event = new KeyboardEvent('keydown',
    {key, ...mod, bubbles: true, cancelable: true});
  handle.dispatchEvent(event);
  return {box: box.getBoundingClientRect().width, swallowed: event.defaultPrevented};
};
const before = box.getBoundingClientRect().width;
return {
  before,
  alt: press('ArrowLeft', {altKey: true}),
  ctrl: press('Home', {ctrlKey: true}),
  meta: press('ArrowRight', {metaKey: true}),
  shift: press('End', {shiftKey: true}),
  // The unmodified one, so this cannot pass by the handler being gone.
  plain: press('ArrowRight', {}),
};
"""


def test_the_separator_hands_back_every_key_that_carries_a_modifier(
    client: TestClient, tmp_path: Path
):
    """Alt+Left is Back.

    Measured in Chrome with focus on the handle and before this guard: Alt+Left
    was `preventDefault`ed and moved the join 32px instead of going back a page,
    and Ctrl+Home and Cmd+Right went the same way. This branch has already paid
    for one binding that swallowed a keystroke somebody meant for something else —
    the view chord was Ctrl+Alt, which IS AltGr, and it ate a euro — and the guard
    here is the one that fix put in: any modifier and the key is not this
    control's.

    `defaultPrevented` as well as the width, because a handler that moves nothing
    and still cancels the event is a Back button that silently does nothing, which
    is the worse half of the same defect.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "modified.html", 1400, _MODIFIED_KEYS, patience=4800,
    )
    for name in ("alt", "ctrl", "meta", "shift"):
        assert got[name]["box"] == got["before"], (
            f"a modified key ({name}) moved the join from {got['before']} to "
            f"{got[name]['box']}"
        )
        assert not got[name]["swallowed"], (
            f"the separator cancelled a modified key ({name}), so whatever the browser "
            "or the platform does with it does not happen"
        )
    assert got["plain"]["box"] == got["before"] + 32, (
        f"the unmodified arrow stopped working too: {got['plain']}"
    )
    assert got["plain"]["swallowed"], "the arrow that IS this control's was not taken"


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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "sync.html", 1400,
        _SYNCING, patience=1800,
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "live.html", 1400,
        _LIVE, patience=2200,
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "abort.html", 1400,
        _OVERTAKEN, patience=1200,
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
// Out of full page: a session now starts in the `edit` VIEW, where the
// surface is the window and `--measure` — the thing this sweeps — decides
// nothing. The gutter's claim is about the ordinary page's column.
document.getElementById('view-edit').click();
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "gutter.html", 1400,
        _NUMBERING, patience=4800,
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
// Whether a pointer aimed at the middle of the first nav link would actually
// reach it. The whole finding is that the surface paints over it, so a class name
// is not the question — `elementFromPoint` is.
//
// Asked as `is it that link`, not as `is it an <a>`. The tag was enough until the
// theme toggle and the sign-in control moved out of the nav into the editor's own
// bar: the nav lost 28px of height, its links slid up, and they now sit at the
// same y as the article's own `← table` link — which is also an `A`, and is a
// control on the surface rather than behind it.
const overLink = () => {
  const box = link.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return hit === link;
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
  // Only if it is not already the view being asked about: a session starts in
  // `edit` now, and pressing the lit segment is how you LEAVE full page — so
  // clicking it here took the surface down instead of putting it up.
  const seg = document.getElementById(id);
  if (seg.getAttribute('aria-pressed') !== 'true') seg.click();
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "leave.html", 1400,
        _LEAVING, patience=1800,
    )

    for name, answer in got.items():
        assert answer["inside"]["classes"] == ["full", f"view-{name}"], name
        assert answer["inside"]["navInert"], f"{name}: the page behind the surface is not inert"
        assert not answer["inside"]["over"], (
            f"{name}: the surface does not actually cover the nav, so nothing here is proved"
        )
        assert answer["after"] == {
            "classes": [], "fullpage": False, "navInert": False, "over": True,
            "switcher": False, "editing": False,
        }, (
            f"Cancel from the {name} view left the reader in the surface: "
            f"{answer['after']}"
        )


# The same question as `_LEAVING`, asked at the door Cancel is not.
#
# A Save made in a room does NOT reload — the document is already what everybody
# in the room has — so `_COEDIT`'s `saved` branch ends the session with a bare
# `showEditing(false)` and nothing else. That is the line driven here, and the
# test above it checks it really is the line, so that this is the room's door and
# not one invented for a test.
_SAVED_IN_A_ROOM = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const nav = document.querySelector('body > nav');
const link = nav.querySelector('a');
const corner = document.querySelector('.corner');
const overLink = () => {
  const box = link.getBoundingClientRect();
  return document.elementFromPoint(
    box.left + box.width / 2, box.top + box.height / 2) === link;
};
const shape = () => ({
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  fullpage: document.body.classList.contains('fullpage'),
  navInert: !!nav.inert,
  over: overLink(),
  switcher: document.getElementById('views').getClientRects().length > 0,
  editing: article.classList.contains('editing'),
  // The corner went into the bar with the session; ending the session has to
  // hand it back, or the theme toggle and the way in are lodged inside a record.
  cornerInNav: corner.parentElement === nav,
});

const answers = {};
for (const [name, id] of [['edit', 'view-edit'], ['both', 'view-both'], ['view', 'preview']]) {
  document.getElementById('toggle').click();
  // Only if it is not already lit: a session starts in `edit`, and pressing the
  // lit segment is how full page is left.
  const seg = document.getElementById(id);
  if (seg.getAttribute('aria-pressed') !== 'true') seg.click();
  const inside = shape();
  // Ending the session and nothing else — the call every door makes.
  showEditing(false);
  answers[name] = {inside, after: shape()};
  // Back to read mode for the next pass: this door leaves Edit on the bar.
  if (article.classList.contains('editing')) document.getElementById('cancel').click();
}
return answers;
"""


def test_the_room_s_own_save_ends_the_session_by_leaving_the_page():
    """How a room's save ends the session, read out of the product.

    It was `showEditing(false)` — the door that had no `showView` and was the
    reason the surface stayed up — and it is a reload now, for a defect one layer
    further out: the read view under the editor is HTML the server rendered at the
    commit the page LOADED at, so closing the editor onto it showed the body as it
    was until somebody refreshed (jcanton, 2026-08-20). A reload takes the surface
    down on its way past, which is the same ending the path without a room has
    always had.

    The claim below — that ending a session by any door leaves the surface — is
    unchanged and still worth driving: Cancel and the view toggle are doors too.
    """
    from openproj.render import _COEDIT

    saved = re.search(r"if \(message\.t === 'saved'\) \{.*?\n    \}", str(_COEDIT), re.S)
    assert saved, "the room's `saved` branch is not where this test thinks it is"
    assert "location.reload()" in saved.group(0), (
        "a room's save no longer ends by leaving the page, so the read view under "
        "the editor is whatever the server rendered before the save"
    )
    assert "showView" not in saved.group(0), (
        "the `saved` branch has grown its own copy of leaving the surface — that "
        "is the fourth copy this was consolidated to remove"
    )


def test_ending_a_session_leaves_the_surface_by_every_door(client: TestClient, tmp_path: Path):
    """Cancel was fixed and the room's Save was not, because the rule was written
    at the call sites rather than at the event.

    Three copies of `showView(null)` existed — `flipEditing`, the issue page's
    toggle, the note page's — and a fourth door had none: a Save in a room ended
    the session with a bare `showEditing(false)` and did not reload. (It reloads
    now, for a different defect — see the test above — so the door driven here is
    the one Cancel and the view toggle use.)
    Measured in Chrome from the split view before the fix: the article kept
    `full view-both`, `<body>` kept `fullpage`, the nav stayed `inert`, and the
    switcher — drawn only under `.entity.editing`, and named by the commit that
    fixed Cancel as the documented way back — went at the same instant. The
    reader was left inside a fixed, opaque, window-filling article showing a
    record nobody was editing.

    It is one listener on `openproj:session` now, so this asks the question the
    call sites cannot: end a session, any way, and the surface comes down.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "roomsave.html",
        1400, _SAVED_IN_A_ROOM, patience=1800,
    )

    for name, answer in got.items():
        assert answer["inside"]["classes"] == ["full", f"view-{name}"], name
        assert answer["inside"]["navInert"], f"{name}: the page behind the surface is not inert"
        assert not answer["inside"]["over"], (
            f"{name}: the surface does not actually cover the nav, so nothing here is proved"
        )
        assert answer["after"] == {
            "classes": [], "fullpage": False, "navInert": False, "over": True,
            "switcher": False, "editing": False, "cornerInNav": True,
        }, (
            f"a room's save from the {name} view left the reader in the surface: "
            f"{answer['after']}"
        )


# The two page-chrome controls, followed into the surface and out of it again.
#
# `#who` is filled by the shell's own `/api/me` fetch, which cannot answer over
# `file://` — so it is filled here with exactly what that script builds for a
# stranger. What is being asked is where the control ENDS UP and whether a
# pointer can reach it, not whether a fetch succeeded.
_THE_CORNER = _STUB_PREVIEW + """
const nav = document.querySelector('body > nav');
const corner = document.querySelector('.corner');
const theme = document.getElementById('theme');
const who = document.getElementById('who');
const link = document.createElement('a');
link.textContent = 'Sign in';
link.href = '/login';
who.replaceChildren(link);
who.hidden = false;

const bar = document.querySelector('article.entity .editbar');
// What a pointer aimed at the middle of a control would actually hit. A class
// name cannot answer this: the whole finding is that an opaque fixed surface was
// painted over these two, and `elementFromPoint` is the question.
const reaches = el => {
  const box = el.getBoundingClientRect();
  return document.elementFromPoint(
    box.left + box.width / 2, box.top + box.height / 2) === el;
};
const shape = () => ({
  parent: corner.parentElement.tagName,
  inBar: bar.contains(corner),
  inert: corner.closest('[inert]') !== null,
  navInert: !!nav.inert,
  themeReachable: reaches(theme),
  themeNamed: theme.getAttribute('aria-label'),
  signInReachable: reaches(link),
  keyboard: [...bar.querySelectorAll('a[href], button, select')]
    .filter(el => el.getClientRects().length)
    .map(el => el.id || el.tagName),
});

const before = shape();
document.getElementById('toggle').click();
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 300));
const inside = shape();
// The listeners came with the node, because it IS the node: pressing the toggle
// still changes the theme and still relabels itself.
const was = document.documentElement.dataset.theme || '';
theme.click();
const themed = {
  was, now: document.documentElement.dataset.theme,
  named: theme.getAttribute('aria-label'),
};
document.getElementById('cancel').click();
await new Promise(go => setTimeout(go, 200));
return {before, inside, themed, after: shape()};
"""


def test_the_theme_toggle_and_the_way_in_come_into_the_surface_with_you(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-20: "the light/dark mode toggle and sign in button seem to
    have disappeared from the edit view, bring those back please".

    The cause is ours and it was right: `body > nav` and `body > a.skip` are made
    `inert` while the full-page surface is up, because an audit found eight
    focusable elements geometrically covered by an opaque fixed article and still
    in the tab order. That fix stays — un-inerting the nav would put the defect
    back — so the two controls move instead, into the editor's own header row
    beside the view switcher.

    The same nodes, not copies: `#theme` and `#who` are ids on a template the
    static export renders once per entity into one file, and the shell's own
    scripts reach for both by id. So the test asks what a MOVE has to be true of
    and a copy would not — the listener still fires, the label still changes, and
    the control is reachable by a pointer at the place it is drawn.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "corner.html",
        1400, _THE_CORNER, patience=2400,
    )

    assert got["before"]["parent"] == "NAV" and not got["before"]["inBar"]
    assert got["before"]["themeReachable"] and got["before"]["signInReachable"]

    inside = got["inside"]
    assert inside["inBar"], "the corner did not come into the editor's bar"
    assert inside["navInert"], (
        "the nav is not inert while the surface is up, so the tab-order defect the "
        "move exists to keep fixed has been fixed the wrong way instead"
    )
    assert not inside["inert"], "the two controls came with the nav's inertness"
    assert inside["themeReachable"], (
        "the theme toggle is in the bar and something is painted over it"
    )
    assert inside["signInReachable"], "the way in is in the bar and unreachable"
    assert inside["themeNamed"] in ("Dark mode", "Light mode"), inside["themeNamed"]
    # In this order, and the order is the argument: the controls that act on the
    # document you are writing come before the two that act on the application.
    assert inside["keyboard"] == [
        "view-edit", "view-both", "preview", "editorswitch", "A", "scheme", "theme"
    ], inside["keyboard"]

    assert got["themed"]["now"] != got["themed"]["was"], (
        "the theme toggle is in the bar and does nothing, so what moved is a "
        "picture of it"
    )
    assert got["themed"]["named"] != inside["themeNamed"], (
        "it switched the theme and went on calling itself what it was"
    )

    # And back, because a control that only travels one way is a control the nav
    # has lost. Cancel is the ordinary way out and is what somebody presses.
    assert got["after"]["parent"] == "NAV"
    assert not got["after"]["navInert"]
    assert got["after"]["themeReachable"] and got["after"]["signInReachable"]


# The editor switch, asked of the browser. Two presses' worth of state and the
# geometry of the ring, in one page.
_THE_SWITCH = _STUB_PREVIEW + """
const sw = document.getElementById('editorswitch');
document.getElementById('toggle').click();
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 300));

const track = sw.querySelector('.etrack');
const knob = sw.querySelector('.eknob');
const knobAt = () => Math.round(
  knob.getBoundingClientRect().left - track.getBoundingClientRect().left);
const drawn = getComputedStyle(sw);
const out = {
  tag: sw.tagName,
  tabindex: sw.getAttribute('tabindex'),
  role: sw.getAttribute('role'),
  checked: sw.getAttribute('aria-checked'),
  // The accessible name, and it comes from the visible words rather than from an
  // `aria-label` — so what a screen reader says and what a speech-control user
  // can say out loud are the same string.
  name: sw.textContent.trim(),
  labelled: sw.getAttribute('aria-label'),
  title: sw.title,
  border: drawn.borderTopWidth + ' ' + drawn.borderTopStyle,
  radius: drawn.borderTopLeftRadius,
  besideTheViews: sw.previousElementSibling && sw.previousElementSibling.id,
  knobAtRest: knobAt(),
};

// Focused the way a keyboard focuses it, and then asked what would clip the ring
// the shell draws. The failure this is about is not a missing outline — it is an
// outline drawn entirely outside a border box that an ancestor's `overflow`
// throws away, which resolves perfectly and paints nothing.
sw.focus({focusVisible: true});
out.focusVisible = sw.matches(':focus-visible');
const ringed = getComputedStyle(sw);
out.outline = ringed.outlineWidth + ' ' + ringed.outlineStyle;
const reach = parseFloat(ringed.outlineWidth) + parseFloat(ringed.outlineOffset);
const box = sw.getBoundingClientRect();
out.clippers = [];
for (let el = sw.parentElement; el; el = el.parentElement) {
  const style = getComputedStyle(el);
  const held = el.getBoundingClientRect();
  if (style.overflow !== 'visible'
      && (held.left > box.left - reach || held.right < box.right + reach
          || held.top > box.top - reach || held.bottom < box.bottom + reach)) {
    out.clippers.push((el.tagName + '.' + el.className).slice(0, 60));
  }
  // The walk stops at the surface, and that is a rule rather than a convenience:
  // `article.entity.full` is `position: fixed`, so its containing block is the
  // viewport and an `overflow` on anything above it — `body.fullpage`, which has
  // one — cannot reach in. Chrome stops painting the clip there and so does this.
  if (style.position === 'fixed') break;
}

// Pressed. This is a `file://` page, which is the one case the switch refuses
// out loud instead of navigating — and that sentence is the proof the press
// reached the handler at all.
sw.click();
await new Promise(go => setTimeout(go, 100));
out.said = document.getElementById('state').textContent;
out.checkedAfter = sw.getAttribute('aria-checked');
out.busyAfter = sw.getAttribute('aria-busy');

// And the look it wears while a real page is on its way, driven as the class it
// is rather than by pressing it, because over http the press takes the document
// away before anything can be measured.
sw.classList.add('waiting');
out.knobWaiting = knobAt();
out.waitingOpacity = getComputedStyle(sw).opacity;
return out;
"""


@pytest.mark.parametrize("asked, on", [("", True), (PLAIN, False)])
def test_the_editor_switch_says_which_editor_it_is_and_that_it_reloads(
    client: TestClient, tmp_path: Path, asked: str, on: bool
):
    """jcanton, 2026-08-20: "can we have the editor toggle as a toggle switch next
    to the three views buttons (?edit / ?both / ?view)".

    A switch and not a fourth segment. The three segments are one control with
    three states; which editor you are writing in is a two-state setting, and a
    fourth icon in that box would read as a fourth way of looking at the document.

    **It is a navigation and it has to be honest about that.** It decides which
    bytes the SERVER rendered — 594 KB of them — and the preference that would
    remember it is this browser's own store, which the server cannot read. So
    flipping it cannot be a class swap, and a switch whose knob completes its
    travel and is then wiped out by a page load reads as one that worked and then
    glitched. The knob does not move on the press; the resting `title` says what
    pressing it will do AND that it reloads; the press says the same thing in the
    live region.

    Both ways round, because a switch that draws itself the same whatever the page
    is carrying is a picture of a switch.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{asked}").text, tmp_path / f"switch{asked}.html",
        1400, _THE_SWITCH, patience=6800,
    )

    # A real `<button>`, which is what makes Enter and Space work without a line
    # of code — and a synthetic `keydown` cannot prove that, because an untrusted
    # event fires no default action. What can be proved is that nothing here
    # opted out of it: not a `<div>`, not `tabindex="-1"`, and it takes the ring.
    assert got["tag"] == "BUTTON" and got["tabindex"] is None
    assert got["focusVisible"], "the switch cannot take keyboard focus"

    # The state in the accessibility tree, not only in a class.
    assert got["role"] == "switch"
    assert got["checked"] == str(on).lower(), (
        f"the switch says {got['checked']} on a page that "
        f"{'carries' if on else 'does not carry'} the second editor"
    )
    assert got["name"] == "Ace editor", got["name"]
    assert got["labelled"] is None, (
        "an `aria-label` would replace the visible words, so what a screen reader "
        "says and what a speech-control user can say would stop being the same"
    )
    assert "reloads the page" in got["title"], got["title"]
    assert ("the plain box" if on else "the Ace editor") in got["title"], got["title"]

    # Beside the segments, and wearing the app's one look. `.views` draws the
    # rectangle its three segments share; this draws its own, because it is its
    # own control.
    assert got["besideTheViews"] == "views"
    assert got["border"] == "1px solid" and got["radius"] == "3px"

    # The ring is drawn OUTSIDE the border box, so the failure to look for is an
    # ancestor that throws it away. `article.entity.full` is `overflow: hidden`
    # and the surface's own padding is what keeps the ring inside it.
    assert got["outline"] == "2px solid", got["outline"]
    assert got["clippers"] == [], (
        f"the focus ring is clipped away by {got['clippers']}"
    )

    # Pressed, on a page with no server behind it: it says so and goes nowhere.
    assert "no server to ask" in got["said"], (
        f"the switch pressed on a saved copy of the page said {got['said']!r}"
    )
    assert got["checkedAfter"] == got["checked"], (
        "the switch flipped itself over a page that is not going to change"
    )
    assert got["busyAfter"] is None, "it claims to be fetching a page it refused to fetch"

    # At rest the knob is at one end or the other; waiting, it is between them,
    # because between them is what is true — this page will never be the page with
    # the other editor in it and the one that is has not arrived.
    assert got["knobAtRest"] == (14 if on else 2), got["knobAtRest"]
    assert 2 < got["knobWaiting"] < 14, got["knobWaiting"]
    assert float(got["waitingOpacity"]) < 1


def test_the_editor_switch_takes_a_focus_ring_that_is_actually_painted(
    client: TestClient, tmp_path: Path
):
    """The other half of the ring, and the half a resolved value cannot give.

    `outline: 2px solid` resolving on the element says nothing about paint — the
    frozen column's edge resolved to exactly the value every test asserted and
    Chrome drew no line at all. So: the same page twice, and the only difference
    is which element has focus.

    **What this does NOT catch, said rather than implied, because it was measured
    while writing it:** clipping. `overflow: hidden` on `.editbar` throws the ring
    away above and below the switch and leaves the two ends of it, and the two
    screenshots still differ — so this passes over a ring that is two thirds
    gone. That is the sibling test's job, and it does it by asking which ancestors
    would crop the ring's rectangle rather than by counting pixels. The two are
    kept apart because they fail for different reasons and a merged one would be
    weaker than either.
    """
    from browser import screenshot

    browser = chrome()
    page = client.get(f"/detail/{TASK}{PLAIN}").text

    def shot(name: str, focus: str) -> bytes:
        html = tmp_path / f"ring-{name}.html"
        html.write_text(page.replace(
            "</body>",
            "<script>setTimeout(() => {"
            "  document.getElementById('toggle').click();"
            "  document.getElementById('view-both').click();"
            f" {focus}"
            "}, 900);</script></body>",
        ))
        return screenshot(browser, html, tmp_path / f"ring-{name}.png", 1400, 900)

    dark = shot("off", "")
    lit = shot("on", "document.getElementById('editorswitch')"
                     ".focus({focusVisible: true});")
    assert dark != lit, (
        "focusing the editor switch changed not one pixel, so the ring the shell "
        "draws for it is being clipped away or is not being drawn at all"
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "failed.html", 1400,
        _A_FAILED_PREVIEW, patience=2800,
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
// Counted as well as refused. The count is what tells a throttle that gave up
// from a throttle that never engaged: both leave the receipt saying the same
// thing, and only one of them reaches the store on every character.
window.__reached = 0;
Object.defineProperty(window, 'localStorage', {
  get() { window.__reached++; throw new DOMException('denied', 'SecurityError'); },
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "status.html", 1400,
        _STATUS, patience=4800,
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "long.html", 1400,
        _LONG % (MAX_BODY_BYTES // 2, MAX_BODY_BYTES + 1000), patience=4800,
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
const after = {held: held(), receipt: receipt()};

// And the burst that follows starts its own leading edge. Forgetting the draft
// forgets both clocks: the one that says when a draft last landed, which the
// receipt counts from, and the one the throttle measures the interval against.
// Leaving the second set would hold the first character typed after a cancel
// back by up to a whole interval, against a write that has nothing to do with it.
document.getElementById('toggle').click();
type('written after the cancel');
const restarted = held();
return {first, throttled, flushed, after, restarted,
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
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % '{"indent": 2, "autosave": 10}'
        ),
        tmp_path / "draft.html", 1400, _DRAFTING, patience=4800,
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
    assert got["restarted"] == "written after the cancel", (
        "the first keystroke after a cancel was throttled against the write "
        "before it, so a tab closed a second later holds nothing again — "
        f"{got['restarted']!r}"
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

// And then a burst, which is the case the throttle exists for and the case a
// refusing store used to turn into a loop. The interval is two seconds by
// default, so twenty characters typed inside it are one write and nineteen
// nothings — unless the throttle is reading a clock that a refusal zeroes, in
// which case every one of them is a synchronous `setItem`, a throw and a catch
// on the main thread. Counted at the store rather than timed, because a slow
// machine makes a timing assertion say the wrong thing.
const before = window.__reached;
for (let i = 0; i < 20; i++) {
  area.value += 'x';
  area.dispatchEvent(new Event('input'));
}
const reached = window.__reached - before;
return {
  errors: window.__errors,
  labels: [...bar.children].map(child => child.textContent),
  indent: INDENT.length,
  view: VIEW,
  editor: JSON.parse(JSON.stringify(EDITOR)),
  receipt: document.getElementById('draftsaved').textContent,
  said: document.getElementById('state').textContent,
  reached,
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
    page = client.get(f"/detail/{TASK}{PLAIN}").text

    # One key, versioned, and every read and write of it through `remembered`.
    assert page.count("const EDITOR_KEY = 'openproj:editor:1';") == 1
    assert "remembered.map(EDITOR_KEY)" in page
    # Named fields and not "whatever is on the object": `EDITOR` also carries
    # what is true of this LOAD — which editor the address asked for — and a
    # preference store that quietly grows a field is one nothing ever forgets.
    assert "remembered.set(EDITOR_KEY," in page
    assert "EDITOR_KEPT.map(k => [k, EDITOR[k]])" in page
    # Which editor a person chose is still kept — but it is written on a condition
    # and is therefore NOT one of the unconditional names, and that is the whole
    # point of it since Ace became the default on 2026-08-20. `EDITOR.editor`
    # resolves to `ace` for everybody who has said nothing, so storing it beside
    # the others would make the next load read the default back as a decision —
    # and `chosen` is what `bodySurface` reads to decide whether a page that
    # cannot honour a decision should say so out loud. One `rememberEditor({mode})`
    # from choosing a view would otherwise have signed every reader up to be told,
    # on every record, that a library they never asked for is missing.
    assert not re.search(r"const EDITOR_KEPT = \[[^\]]*'editor'[^\]]*\];", page), (
        "the resolved editor is stored unconditionally, so the default is written "
        "down as though somebody had chosen it"
    )
    assert "if (EDITOR.chosen) kept.editor = EDITOR.editor;" in page, (
        "which editor a person chose is a preference and has to be kept when it IS "
        "a choice"
    )
    assert not re.search(r"localStorage\.\w+\('openproj:editor", page), (
        "a bare localStorage call for the preference"
    )

    got = measured_in(
        chrome(), _before_the_page_runs(page, _NO_STORE), tmp_path / "denied.html",
        1400, _REFUSED, patience=4800,
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
    # The throttle still throttles when the store says no. It kept two clocks in
    # one variable: `draftWritten` has to be zeroed on a refusal, because
    # `sayDraft` counts from it and a receipt over a write that did not happen is
    # the lie this whole branch exists to stop — and the `input` handler then read
    # that same zero as "the last write was in 1970", so `wait` was hugely
    # negative and every keystroke went straight back into `remembered.set`.
    assert got["reached"] <= 2, (
        f"twenty characters reached the refusing store {got['reached']} times: the "
        "throttle is re-entering the write it was added to bound, synchronously, "
        "in the one browser where that costs something"
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
        tmp_path / "sticky.html", 1400, _STICKY, patience=4800,
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
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "face.html", 1400,
        _ONE_FACE, patience=2800,
    )

    assert "mono" in got["box"].lower(), (
        f"the box resolved to {got['box']!r} — the sans face won, so `--gutter` is "
        "one width in the column and another in the box's own padding"
    )
    assert got["box"] == got["gutter"], f"{got['box']!r} beside {got['gutter']!r}"
    assert got["size"][0] == got["size"][1], got["size"]
    assert got["height"][0] == got["height"][1], got["height"]


_WATCH_THE_NETWORK = """
window.__violations = [];
window.__injected = [];
document.addEventListener('securitypolicyviolation', event => {
  window.__violations.push(event.effectiveDirective + ' <- ' + String(event.blockedURI));
});
// The one signal a blocked script leaves: an `error` event with an empty
// message. No exception, no console warning, nothing a Python test could see.
window.__errors = [];
addEventListener('error', event => window.__errors.push(String(event.message)));
const append = Element.prototype.appendChild;
Element.prototype.appendChild = function (node) {
  if (node && node.tagName === 'SCRIPT' && node.src) window.__injected.push(node.src.slice(-24));
  return append.call(this, node);
};
"""

_KEYMAP_FETCHES = r"""
  document.getElementById('toggle').click();
  await new Promise(r => setTimeout(r, 300));
  const editor = SURFACE.editor;
  const table = editor.commands.commands;
  const gone = ['find', 'replace', 'showSettingsMenu', 'goToNextError', 'goToPreviousError']
    .filter(name => name in table);
  // Exercised, not merely absent: `exec` on a command that is not there answers
  // false and does nothing, which is what pressing the key now does.
  const ran = ['find', 'replace', 'showSettingsMenu', 'goToNextError', 'goToPreviousError']
    .filter(name => editor.commands.exec(name, editor));
  await new Promise(r => setTimeout(r, 200));
  const quiet = {
    gone, ran,
    injected: window.__injected.slice(),
    violations: window.__violations.slice(),
    scripts: [...document.querySelectorAll('script[src]')].length,
    errors: window.__errors.slice(),
  };
  // **The forced failure**, so the zeros above are evidence rather than a check
  // that could only pass. This is the call the five commands used to make.
  ace.config.loadModule('ace/ext/searchbox', () => {});
  await new Promise(r => setTimeout(r, 400));
  return {quiet, control: {
    injected: window.__injected.slice(),
    violations: window.__violations.slice(),
    errors: window.__errors.slice(),
  }};
"""


def test_no_editor_asks_for_a_script_after_the_page_has_loaded(
    client: TestClient, tmp_path: Path
):
    """The half of the network rule that a source grep structurally cannot see.

    `test_no_page_reaches_the_network` scans the rendered text for
    `<script[^>]+src=`. Ace's default command table calls `config.loadModule`,
    which is `createElement('script'); i.src = e; head.appendChild(i)` — an
    element that exists only at runtime, in a page whose source has no `src=` in
    it anywhere. Five commands reach it: `find` (Cmd-F), `replace` (Ctrl-H),
    `showSettingsMenu` (Cmd-,), and the two error markers (Alt-E, Alt-Shift-E).

    Measured before they were removed: Cmd-F gives `defaultPrevented=true`, one
    injected `ext-searchbox.js`, a `script-src-elem` violation, no searchbox in
    the DOM, and an EMPTY `window.error`. Ace takes Cmd-F away from the browser
    and gives back nothing, in silence — which is why this is asked of Chrome and
    why the control below matters more than the assertion above it: a blocked
    script throws nothing, logs nothing and returns normally, so a test with no
    forced failure beside it is a test that cannot fail.
    """
    page = _before_the_page_runs(
        client.get(f"/detail/{TASK}?editor=ace").text, _WATCH_THE_NETWORK
    )
    got = measured_in(chrome(), page, tmp_path / "keymap.html", 1400, _KEYMAP_FETCHES,
                      query="?editor=ace", patience=6800)

    quiet, control = got["quiet"], got["control"]
    assert quiet["gone"] == [], f"these still reach config.loadModule: {quiet['gone']}"
    assert quiet["ran"] == [], f"these still ran: {quiet['ran']}"
    assert quiet["injected"] == [], f"the editor fetched {quiet['injected']}"
    # Scoped to script directives, and the scoping is not a loosening: this page
    # is opened from a `file://` URL, where the room's own WebSocket is refused by
    # `connect-src 'self'` before it can open. That refusal is the policy working
    # and is the ordinary case a `file://` copy is designed to survive; what this
    # test is about is a SCRIPT arriving from somewhere.
    scripty = [one for one in quiet["violations"] if one.startswith("script-")]
    assert scripty == [], f"the policy refused a script: {scripty}"
    assert quiet["scripts"] == 0, "a script[src] appeared in a page that inlines everything"
    assert quiet["errors"] == [], quiet["errors"]

    # And the control. If this does not fire, the four assertions above are
    # asserting that a detector nobody proved works found nothing.
    assert [one.endswith("ext-searchbox.js") for one in control["injected"]] == [True], (
        "the forced failure injected nothing, so the detection above proves nothing"
    )
    assert any("script-src" in one for one in control["violations"]), (
        f"the policy did not refuse the injected script: {control['violations']}"
    )
    assert control["errors"] == [""] or control["errors"] == [], (
        "a blocked script is an `error` event with an empty message, and this is the "
        f"shape the test's own docstring rests on: {control['errors']}"
    )


_PASTED_CRLF = r"""
  document.getElementById('toggle').click();
  await new Promise(r => setTimeout(r, 300));
  // ONE line, which is the state Ace re-detects the newline sequence in:
  // `Document.insert` is `this.getLength() <= 1 && this.$detectNewLine(text)`.
  // A new entity starts here, and so does any document somebody has just
  // selected all of and deleted.
  SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, 'first line'));
  const at = SURFACE.text().length;
  SURFACE.setCaret(at);
  // A paste out of an editor on Windows, through the same `splice` a paste goes
  // through. What is under test is not the pasted run — it is the whole document
  // afterwards.
  // The run STARTS with the carriage return, because `$detectNewLine` takes the
  // first ending it finds and a leading `\n` would answer the question for it —
  // which is a test that passes on the mutation it is written for.
  SURFACE.splice(at, at, '\r\npasted\r\nfrom\r\nelsewhere\r\n');
  await new Promise(r => setTimeout(r, 50));
  const text = SURFACE.text();
  return {carriage: text.indexOf('\r'), lines: text.split('\n').length, text};
"""


def test_the_second_surface_holds_one_line_ending_whatever_is_pasted_into_it(
    client: TestClient, tmp_path: Path
):
    """The half of hazard 1 that the room's own normalisation does not cover.

    `coedit.one_newline` makes the room hold LF, so a surface opening on it never
    sees a carriage return — and that is why deleting `setNewLineMode('unix')`
    leaves the two-editors convergence test green. It is not why the line is
    there.

    Ace's `Document.insert` is `this.getLength() <= 1 && this.$detectNewLine(t)`:
    on a document of one line — a new entity, or one somebody has just cleared —
    inserting text whose first ending is CRLF sets `$autoNewLine`, and
    `getValue()` then rejoins EVERY line with it. The document that comes back
    out is a different string from the one that went in, at the same line count,
    which is the shape no index or length check can see; a `<textarea>` in the
    same room cannot hold it, and the two never settle.

    Pinned as "whatever is pasted, one ending comes back", because that is the
    property, and it is asked of Chrome because `$detectNewLine` is Ace's and
    only Ace can answer for it.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text, tmp_path / "crlf.html",
        1400, _PASTED_CRLF, query="?editor=ace", patience=4800,
    )
    assert got["carriage"] == -1, (
        "a carriage return came back out of the second editor at offset "
        f"{got['carriage']}: {got['text'][:60]!r}"
    )
    assert got["lines"] == 5, got["text"]


_VIM_ON = r"""
  document.getElementById('toggle').click();
  await new Promise(r => setTimeout(r, 300));
  const editor = SURFACE.editor;
  const keymap = [...document.querySelectorAll('#statusbar button')]
    .find(b => b.textContent.startsWith('Keymap'));
  if (!keymap) return {noPicker: true};
  keymap.click();
  await new Promise(r => setTimeout(r, 100));
  const out = {label: keymap.textContent, handler: String(editor.getKeyboardHandler().$id),
               said: document.getElementById('state').textContent, marks: []};
  // NORMAL mode. Every mark in the bar, over the same selection each time, with
  // the document put back between them so one mark cannot mask another.
  const started = SURFACE.text();
  for (const button of document.querySelectorAll('#marks .mark')) {
    if (button.title === 'Image') continue;   // opens a file picker, writes nothing
    // Undo and redo write no markdown at all — they move a stack. Excluded here
    // rather than asserted as "wrote something", which they would pass by taking
    // back the mark before them and would therefore say nothing.
    if (button.classList.contains('hist')) continue;
    SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, started));
    SURFACE.setCaret(0, 5);
    button.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
    await new Promise(r => setTimeout(r, 10));
    out.marks.push([button.title, SURFACE.text() !== started]);
  }
  // The record: this is the call that silently does nothing under vim in a
  // textarea, which is what made asks 2 and 6 destroy each other on that path.
  SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, started));
  editor.focus();
  out.execCommand = document.execCommand('insertText', false, 'X');
  // Tab, dispatched at Ace's own input where a keystroke really arrives.
  SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, 'abc\ndef\n'));
  SURFACE.setCaret(0, 0);
  // A listener beside the page's own, on the same element, so what it records is
  // what the page's handler saw. `keyCode` in the init dict because that is what
  // Ace reads — `keyBinding.onCommandKey(e, hashId, e.keyCode)` — and Chrome
  // gives a synthesised event a `keyCode` of 0 unless it is asked for, which
  // would leave Ace's own Tab command never running and this measuring nothing.
  out.reached = [];
  SURFACE.el.addEventListener('keydown', e => out.reached.push(e.key));
  const input = SURFACE.el.querySelector('textarea');
  const press = (key, code, keyCode, extra) => input.dispatchEvent(new KeyboardEvent(
    'keydown', Object.assign({key, code, keyCode, which: keyCode,
                              bubbles: true, cancelable: true}, extra || {})));
  press('Tab', 'Tab', 9);
  await new Promise(r => setTimeout(r, 30));
  out.afterTab = SURFACE.text().slice(0, 8);
  press('Escape', 'Escape', 27);
  press('s', 'KeyS', 83, {metaKey: true});
  await new Promise(r => setTimeout(r, 30));
  out.scripts = document.querySelectorAll('script[src]').length;
  out.gutters = document.querySelectorAll('.gutter').length;
  out.aceGutter = document.querySelectorAll('.ace_gutter').length;
  return out;
"""


def test_the_toolbar_and_the_keymap_do_not_cancel_each_other(
    client: TestClient, tmp_path: Path
):
    """Ask 2 and ask 6 destroyed each other on the path this does not take.

    Measured, and it is the reason the toolbar had to move behind the surface
    before vim could be bought: `document.execCommand('insertText')` **silently
    no-ops under vim NORMAL mode** — A/B'd in one page, it returns `true`, throws
    nothing, and leaves the document unchanged. Every toolbar button and the
    image-paste placeholder-then-replace go through `replaceRange`, which is that
    call, so with vim on they would all have done nothing at all, in silence, on
    a bar of sixteen buttons.

    On the second surface the toolbar goes through `splice`, which is
    `Document.remove` and `Document.insert` — the same two calls Ace makes for a
    keystroke — so the mode the keyboard is in has nothing to do with it. This
    asserts the whole bar, one mark at a time, with the document put back between
    them so one mark cannot pass by masking another.

    And Tab, in the same run, because the arbitration that lets vim have Escape is
    the same line that lets Ace have Tab: `if (event.defaultPrevented) return;` at
    the top of the page's own keydown handler. Without it Ace's soft tab and the
    page's `indentLines` both fire and one press indents twice.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text, tmp_path / "vim.html",
        1400, _VIM_ON, query="?editor=ace", patience=6800,
    )
    assert not got.get("noPicker"), "the second editor carries no keymap control"
    assert got["label"] == "Keymap: vim"
    assert got["handler"] == "ace/keyboard/vim"
    # Nothing is announced. The sentence that was here explained what vim mode
    # takes from the keyboard to somebody who had just turned vim mode on, and
    # jcanton asked for it to go — 2026-08-21, "we don't need [it], can be
    # completely removed". The control's own label says which keymap is on, which
    # is asserted two lines up.
    assert "Vim keys are on" not in got["said"], (
        f"the removed announcement is back: {got['said']!r}"
    )

    inert = [title for title, wrote in got["marks"] if not wrote]
    assert inert == [], f"these toolbar buttons do nothing with vim on: {inert}"
    # Thirteen: the sixteen in the shot, less Image, less the two history buttons,
    # which are not marks and are asserted where the stack they move is.
    assert len(got["marks"]) == 13, got["marks"]

    # The record, asserted rather than described: this is the call that would have
    # been used, and Chrome answers `true` for it whether or not anything happened.
    assert got["execCommand"] is True

    assert got["afterTab"].startswith("  abc"), (
        f"Tab did not indent once: {got['afterTab']!r} — two indents means both the "
        "editor's own soft tab and the page's `indentLines` fired on one press"
    )
    # And WHY it indented once, which is the part a character count cannot say.
    # Ace's `stopEvent` does `stopPropagation` as well as `preventDefault`, so a
    # key its command table handled never reaches the page's own keydown listener
    # — that, and not a `defaultPrevented` check, is what stops `indentLines`
    # firing on top of Ace's soft tab. The two keys the page still has to get are
    # here beside it: Escape leaves the full-page view and Cmd+S saves, and both
    # arrive.
    assert "Tab" not in got["reached"], (
        "Tab reached the page's own handler, so `indentLines` ran on top of the "
        "editor's soft tab — this is one press indenting twice"
    )
    assert got["reached"] == ["Escape", "s"], (
        f"the keys the page still needs did not arrive: {got['reached']}"
    )
    assert got["scripts"] == 0, "the keymap fetched something"

    # One gutter and it is the editor's own. `attachGutter` draws line numbers
    # through a mirror of a `<textarea>`, and on this page the textarea is hidden
    # and stale — a mirror of a box with no layout wraps the whole document one
    # character per row and answers with numbers that mean nothing, beside a
    # column of numbers that mean something.
    assert got["gutters"] == 0, "the page drew a second gutter over the editor's own"
    assert got["aceGutter"] == 1, "the editor's own gutter is not there either"


_KEYMAP_KEPT = r"""
  document.getElementById('toggle').click();
  await new Promise(r => setTimeout(r, 300));
  return {handler: String(SURFACE.editor.getKeyboardHandler().$id),
          label: [...document.querySelectorAll('#statusbar button')]
            .map(b => b.textContent).find(t => t.startsWith('Keymap'))};
"""


def test_the_keymap_a_person_chose_is_the_one_the_next_session_opens_in(
    client: TestClient, tmp_path: Path
):
    """The preference, and the whole of what "keep both editors" asked for.

    One key, one object, the version in the name — `openproj:editor:1` — and
    `keymap` is a field in it beside `mode`, `indent`, `autosave` and `editor`
    rather than a key of its own, so the shape that grows a sixth field forgets
    the fifth by bumping one name.

    Checked against what the control offers, because `{"keymap": "emacs"}` is one
    hand-edit away and `setKeyboardHandler` with a name that is not already
    defined goes through `config.loadModule`, which is the network path the five
    default commands were removed for.
    """
    page = client.get(f"/detail/{TASK}?editor=ace").text

    kept = measured_in(
        chrome(), _before_the_page_runs(page, _SEED % '{"keymap": "vim"}'),
        tmp_path / "keymap-kept.html", 1400, _KEYMAP_KEPT, query="?editor=ace", patience=6800,
    )
    assert kept["handler"] == "ace/keyboard/vim", "the remembered keymap did not open"
    assert kept["label"] == "Keymap: vim"

    made_up = measured_in(
        chrome(), _before_the_page_runs(page, _SEED % '{"keymap": "emacs"}'),
        tmp_path / "keymap-junk.html", 1400, _KEYMAP_KEPT, query="?editor=ace", patience=6800,
    )
    assert made_up["label"] == "Keymap: default", (
        "a keymap this control does not offer was taken from the store and handed to "
        "`setKeyboardHandler`, which would fetch it"
    )


_STICKY_EDITOR = r"""
  return {search: location.search, editor: EDITOR.editor,
          surface: SURFACE.onSplice ? 'ace' : 'textarea',
          // `?? null`, or `JSON.stringify` drops the key entirely and the case
          // that asks for nothing to have been stored reads as a broken report.
          kept: remembered.map('openproj:editor:1').editor ?? null,
          said: document.getElementById('state').textContent};
"""


def test_the_editor_a_person_chose_is_carried_back_into_the_address(
    client: TestClient, tmp_path: Path
):
    """The preference is `localStorage` and the server cannot read it, so the
    thing that decides which bytes render is the query string. Sticky therefore
    means one specific thing: the page puts the remembered choice back into the
    address and asks the server again.

    Only over http(s). A page saved to a file is the case where the parameter can
    never work — there is no server to render the other bytes — so it says so
    instead of reloading a file to add a parameter to it, which is the branch this
    drives: `measured_in` opens a `file://` URL.

    Three cases, and the third is the one the 2026-08-20 flip created: with Ace on
    the default side of the parameter, the preference that now has to be carried
    back into the address is the one for the PLAIN box, on a page that already
    arrived carrying the library.
    """
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % '{"editor": "ace"}'
        ),
        tmp_path / "sticky-editor.html", 1400, _STICKY_EDITOR, patience=4800,
    )
    assert got["editor"] == "ace", "the remembered choice was not read"
    assert got["surface"] == "textarea", "a page with no library in it mounted one"
    assert "does not carry the second editor" in got["said"], (
        f"the page quietly handed back the other editor: {got['said']!r}"
    )
    # And the choice is kept, because this page was never asked: a `file://` copy
    # has no server, so forgetting here would clear somebody's preference because
    # they opened an export. The other case — the address DID ask and the server
    # sent no library — forgets, so a reader who once typed it does not pay a
    # redirect on every page for ever.
    assert got["kept"] == "ace", (
        "opening a saved copy of a page forgot which editor this browser prefers"
    )
    # The other case, driven as itself: the address DID carry the request and the
    # page came back without the library — which on the server is a reader
    # `may_write` refuses, and here is the same page opened at `?editor=ace`.
    refused = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % '{"editor": "ace"}'
        ),
        tmp_path / "sticky-refused.html", 1400, _STICKY_EDITOR, query="?editor=ace",
        patience=4800,
    )
    assert refused["surface"] == "textarea"
    assert "does not carry the second editor" in refused["said"]
    assert refused["kept"] == "plain", (
        "the address asked, the answer was no, and this browser will go on asking — "
        "one redirect a page, for ever, for something it cannot have"
    )
    # The third: the library IS in the page, because that is what a writer who says
    # nothing gets now, and this browser has chosen the plain box. The reload that
    # would fetch the smaller page cannot happen over `file://`, so what is being
    # asked here is the half that survives without it — the choice is still
    # honoured, and the 594 KB sitting in the document is not mounted on the
    # strength of being there.
    opted_out = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}").text, _SEED % '{"editor": "plain"}'
        ),
        tmp_path / "sticky-plain.html", 1400, _STICKY_EDITOR, patience=6800,
    )
    assert opted_out["editor"] == "plain"
    assert opted_out["surface"] == "textarea", (
        "the second editor mounted itself over somebody who had chosen the box, "
        "because its bytes happened to be in the page"
    )
    assert opted_out["said"] == "", (
        "the plain box is what this browser asked for and getting it is not news: "
        f"{opted_out['said']!r}"
    )
    # The fourth, and it is the one the flip made necessary rather than merely
    # changed. `ace` is the fallback now, so a browser that has never said
    # anything resolves to it — and this page has no library, because `may_write`
    # or the address said so. Without `EDITOR.chosen` telling a decision that
    # cannot be honoured apart from a default that was never going to be, the
    # sentence above would be read out to every signed-out reader on every record,
    # about a thing they never asked for, and the choice they never made would be
    # written down as `plain`.
    never_asked = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "sticky-silent.html", 1400, _STICKY_EDITOR, patience=4800,
    )
    assert never_asked["surface"] == "textarea"
    assert never_asked["said"] == "", (
        "a page nobody asked anything of announced the absence of a library: "
        f"{never_asked['said']!r}"
    )
    assert never_asked["kept"] is None, (
        "saying nothing was written down as a choice, so the next page that cannot "
        "honour it will say so out loud"
    )

    # And the source of the half that only a server can show: the navigation is a
    # `replace` on an http(s) URL, and a preference carried forward is not a place
    # the back button should return to.
    page = client.get(f"/detail/{TASK}").text
    sticky = re.search(r"function stickyEditor\(\) \{.*?\n\}", page, re.S)
    assert sticky, "the page no longer carries the preference back into the address"
    assert "location.protocol.startsWith('http')" in sticky.group(0)
    assert "location.replace(url)" in sticky.group(0)
    assert "url.searchParams.set('editor', EDITOR.editor)" in sticky.group(0)


# The document is the row with the height in it, and the facts are the row below.
# Both halves are measured because either alone leaves the surface unusable: with
# only the floor on the row, the facts drew as a 59px box with fifteen fields
# scrolling inside it; with only the reorder, the document got the 60px of free
# space the facts' auto row left over.
_NARROW_FULL_PAGE = """
const article = document.querySelector('article.entity');
const area = document.querySelector('textarea[name=body]');
const panes = document.querySelector('.panes');
const facts = document.querySelector('.facts');
const main = document.querySelector('.main');
const pane = document.getElementById('body-preview');
const rows = element => {
  const box = element.getBoundingClientRect();
  return Math.round(box.height / parseFloat(getComputedStyle(area).lineHeight));
};
const state = () => ({
  rows: rows(area),
  documentFirst: main.getBoundingClientRect().top < facts.getBoundingClientRect().top,
  factsWhole: Math.round(facts.getBoundingClientRect().height) >= facts.scrollHeight - 1,
  factsReachable: panes.scrollHeight > panes.clientHeight
                  || facts.getBoundingClientRect().bottom <= panes.getBoundingClientRect().bottom,
});

// The create form is always editing and has no way in, so it has no `#toggle`.
const into = document.getElementById('toggle');
if (into) into.click();
const out = {};
// The session already starts in `edit`, and pressing the lit segment leaves full
// page — so this presses it only when something else is lit.
const press = id => {
  const seg = document.getElementById(id);
  if (seg.getAttribute('aria-pressed') !== 'true') seg.click();
};
press('view-edit');
out.write = state();
press('view-both');
out.split = state();
out.paneRows = Math.round(
  pane.getBoundingClientRect().height / parseFloat(getComputedStyle(area).lineHeight));
press('preview');
out.read = {
  paneRows: Math.round(
    pane.getBoundingClientRect().height / parseFloat(getComputedStyle(area).lineHeight)),
  documentFirst: main.getBoundingClientRect().top < facts.getBoundingClientRect().top,
};
out.width = innerWidth;
out.fixed = getComputedStyle(article).position;
return out;
"""


@pytest.mark.parametrize("where", ["detail", "new"])
def test_the_full_page_surface_is_a_writing_surface_at_a_window_that_is_not_wide(
    client: TestClient, tmp_path: Path, where: str
):
    """A 900px window is a laptop with the window not maximised, and full page is
    the feature this branch exists for.

    The container query stacks the facts above the document below 56rem of
    column, and in full page the explicit `minmax(0, 1fr)` row then landed on the
    facts — because `.facts` comes first in the markup — while the document got
    the implicit `auto` one. A `height: 100%` box in an auto track is a box the
    size of its `rows` attribute: measured at every width from 900px down, in all
    three views and on both surfaces, the writing box was 50px. Two lines, under
    six hundred pixels of metadata, with no way to make it bigger.

    Asked of Chrome and not of `tests/cascade.py`, and the reason is written into
    that module: it skips at-rules bodies and all, so it resolves the wide
    two-column page and cannot see the stacked one at all. This is a question
    about which track a box ended up in, which is layout.
    """
    page = client.get(
        f"/detail/{TASK}{PLAIN}" if where == "detail" else f"/new{PLAIN}"
    ).text
    got = measured_in(chrome(), page, tmp_path / f"narrow-{where}.html", 900, _NARROW_FULL_PAGE)

    assert got["width"] == 900 and got["fixed"] == "fixed"
    for view in ("write", "split"):
        assert got[view]["rows"] >= 12, (
            f"the {view} view gives the document {got[view]['rows']} lines at a 900px window"
        )
        assert got[view]["documentFirst"], (
            "the facts are above the document in the surface that exists to be written in"
        )
        assert got[view]["factsWhole"], (
            "the facts pane is scrolling inside itself: the row it is in has no height, "
            "so fifteen fields are in a box a few lines tall"
        )
        assert got[view]["factsReachable"], "and there is no way to scroll down to them"
    assert got["paneRows"] >= 12, "the rendered half of the split is not readable either"
    assert got["read"]["paneRows"] >= 12
    assert got["read"]["documentFirst"]


_TEMPLATE_SWAP = """
const picker = document.getElementById('template');
const numbers = () => document.querySelectorAll('.lineno').length;
const bar = document.getElementById('statusbar');
const said = () => bar.textContent.replace(/\\s+/g, ' ').trim();
const state = () => ({length: SURFACE.text().length, numbers: numbers(), said: said()});
const choose = async name => {
  picker.value = name;
  picker.dispatchEvent(new Event('change', {bubbles: true}));
  await new Promise(go => setTimeout(go, 250));
  return state();
};
const out = {start: state()};
out.blank = await choose('blank');
out.project = await choose('project');
return out;
"""


def test_choosing_a_template_leaves_the_numbers_and_the_length_telling_the_truth(
    client: TestClient, tmp_path: Path
):
    """The picker replaces the whole document through `apply`, which fires no
    `input` — and the gutter and the status bar are both drawn off one.

    Measured before this: choosing `blank` on the create form emptied the box and
    left twenty-one line numbers painted down the side of an empty textarea, with
    `21 Lines — Length: 661` underneath it. Both values had resolved correctly
    once, for a document that no longer existed, which is why nothing in the
    suite noticed: every assertion about either was made at load.

    This is the same hazard `reflect()` names in `_COEDIT` — the page changing
    the text without typing it — and it is answered the same way, with one
    `openproj:editing` from the one place that did it.
    """
    got = measured_in(
        chrome(), client.get(f"/new{PLAIN}").text, tmp_path / "template.html", 1400, _TEMPLATE_SWAP
    )

    assert got["start"]["numbers"] > 1 and got["start"]["length"] > 0, (
        "the create form did not open on a template, so there is nothing to swap away from"
    )
    assert got["blank"]["length"] == 0, "the picker did not empty the box"
    assert got["blank"]["numbers"] == 1, (
        f"an empty box has {got['blank']['numbers']} line numbers beside it"
    )
    # Singular, and spelled out here rather than left as a substring: an empty
    # document is the first thing anybody sees on this page, and `1 Lines` is
    # what it opened with.
    assert "— 1 Line" in got["blank"]["said"] and "1 Lines" not in got["blank"]["said"] and (
        "Length: 0" in got["blank"]["said"]
    ), (
        f"the status bar is still describing the document before it: {got['blank']['said']}"
    )
    assert got["project"]["length"] > 0, "and it did not put the next template in"
    lines = int(got["project"]["said"].split(" Lines")[0].split("\u2014 ")[-1].replace(",", ""))
    assert got["project"]["numbers"] == lines, (
        "the gutter and the status bar do not agree on how long the document is"
    )
    assert f"Length: {got['project']['length']:,}" in got["project"]["said"]


_HISTORY_WITH_NO_ROOM = r"""
document.getElementById('toggle').click();
const area = document.querySelector('textarea[name=body]');
const of = word => [...document.querySelectorAll('#marks .hist')]
  .find(one => one.title.startsWith(word));
const undo = of('Undo'), redo = of('Redo');
if (!undo || !redo) return {missing: true};
// The two most-pressed buttons on the bar are drawings, because every arrow
// anybody would type is outside the vendored latin subset. An SVG nothing sizes
// lays out at 0x0, and this application has shipped that twice.
const drawn = [undo, redo].map(one => {
  const art = one.querySelector('svg');
  if (!art) return null;
  const seen = art.getBoundingClientRect();
  return {w: Math.round(seen.width), h: Math.round(seen.height),
          paths: art.querySelectorAll('path').length,
          ink: getComputedStyle(art).stroke};
});
// No socket has ever welcomed this page — it is a `file://` URL with no server
// behind it — so this is the ordinary state the export and every signed-out
// reader are in, and the browser's own stack is the whole of the history here.
const live = typeof COEDIT === 'undefined' ? null : COEDIT.live();
const roomOwns = COEDIT_HISTORY !== null;

const atRest = {undo: undo.disabled, redo: redo.disabled};
area.focus();
area.setSelectionRange(area.value.length, area.value.length);
document.execCommand('insertText', false, ' a sentence');
const typed = {text: area.value, undo: undo.disabled, redo: redo.disabled};

// The key is the browser's here and stays the browser's: its own binding
// restores the selection the edit was made with, and `execCommand('undo')` does
// not. `defaultPrevented` false is the assertion that the page kept its hands off.
const key = new KeyboardEvent('keydown', {key: 'z', code: 'KeyZ', ctrlKey: true,
                                          bubbles: true, cancelable: true});
area.dispatchEvent(key);
const tookTheKey = key.defaultPrevented;

undo.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
await new Promise(go => setTimeout(go, 50));
const undone = {text: area.value, undo: undo.disabled, redo: redo.disabled};
// From the keyboard, which is the channel thirteen of fourteen buttons on this
// bar did not answer.
redo.focus();
redo.click();
await new Promise(go => setTimeout(go, 50));
const redone = {text: area.value, undo: undo.disabled, redo: redo.disabled};
return {drawn, live, roomOwns, atRest, typed, tookTheKey, undone, redone,
        named: [undo.getAttribute('aria-label'), redo.getAttribute('aria-label')]};
"""


def test_the_history_buttons_use_the_browsers_own_stack_when_there_is_no_room(
    client: TestClient, tmp_path: Path
):
    """The third of the three states the two buttons have to serve, and the one
    everybody is in most of the time: a page with no socket at all.

    The static export over `file://`, a proxy that drops the upgrade, a reader
    who is not signed in — none of them has a room, nothing ever assigns `.value`
    behind the box, and the browser's own undo stack is therefore complete and
    honest. So the page uses it and does not take ⌘Z off the browser: the native
    binding restores the *selection* the edit was made with, and
    `execCommand('undo')` does not. A page that intercepted here would be trading
    a better undo for a worse one, and `tookTheKey` is that promise.

    The drawings are asserted in the same run because they are the same claim
    about the same two controls. Every arrow anybody would type — U+21B6, U+21B7,
    U+27F2, U+27F3, U+2190, U+2192, U+21A9, U+21AA, U+238C — is outside the 230
    codepoints of the vendored latin subset, so a typed one is two tofu boxes on
    any machine without a font that has it; and an SVG that nothing sizes lays
    out at 0x0, which this application has already shipped twice. Both are
    questions about pixels and both are asked of Chrome.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "history.html",
        1400, _HISTORY_WITH_NO_ROOM,
    )

    assert not got.get("missing"), "the toolbar carries no history buttons"
    for seen in got["drawn"]:
        assert seen, "a history button holds no drawing, so it holds nothing at all"
        assert (seen["w"], seen["h"]) == (13, 13), (
            f"the drawing laid out at {seen['w']}x{seen['h']} — an SVG nothing sizes is 0x0"
        )
        assert seen["paths"] == 2, "the arrow is a head and a shaft"
        assert seen["ink"] != "none", "drawn in `currentColor`, so it follows the theme"
    assert got["named"] == ["Undo", "Redo"], (
        "an icon-only control with no accessible name is a button nobody can find"
    )

    assert got["live"] is False and got["roomOwns"] is False, (
        "this page has a room after all, so it is not measuring the state it says it is"
    )
    assert got["atRest"] == {"undo": True, "redo": True}, (
        "a document nobody has typed in offers an undo, which is a button that does nothing"
    )
    assert got["typed"]["text"].endswith(" a sentence")
    assert got["typed"]["undo"] is False, "the browser's own stack was not asked"
    assert got["tookTheKey"] is False, (
        "the page took ⌘Z off a browser whose own undo is complete and better than "
        "the one this page could give back"
    )
    assert not got["undone"]["text"].endswith(" a sentence"), (
        f"the undo button gave nothing back: {got['undone']['text']!r}"
    )
    assert got["redone"]["text"].endswith(" a sentence"), (
        f"redo did not answer a keyboard press: {got['redone']['text']!r}"
    )


_HISTORY_ON_ACE = r"""
document.getElementById('toggle').click();
await new Promise(go => setTimeout(go, 300));
const editor = SURFACE.editor;
const of = word => [...document.querySelectorAll('#marks .hist')]
  .find(one => one.title.startsWith(word));
const undo = of('Undo'), redo = of('Redo');
if (!undo || !redo || !editor) return {missing: true};
// Seeded with `setValue(seeded, -1)`, which resets Ace's history: the document
// as it opened is the ground state and there is nothing behind it.
const atRest = {undo: undo.disabled, redo: redo.disabled};
const lengthWas = SURFACE.text().length;
if (!undo.disabled) {
  undo.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
  await new Promise(go => setTimeout(go, 100));
}
const lengthAfterAnUndoAtRest = SURFACE.text().length;

// Whose history this surface's buttons reach, asked of the decision itself and
// not inferred from what happened. Ace keeps its own across a remote change —
// `aceSurface` taught the manager to ignore deltas this tab did not make — and
// Ace's command table owns Ctrl+Z before this page can see it, so button and key
// have to arrive at the same stack.
const ownsItself = historyOf(SURFACE) === SURFACE.history;

editor.focus();
editor.selection.moveTo(0, 0);
editor.insert('ACE ');
await new Promise(go => setTimeout(go, 100));
const typed = {head: SURFACE.text().slice(0, 4), undo: undo.disabled, redo: redo.disabled};

undo.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
await new Promise(go => setTimeout(go, 100));
const undone = {head: SURFACE.text().slice(0, 4), undo: undo.disabled, redo: redo.disabled};
redo.focus();
redo.click();
await new Promise(go => setTimeout(go, 100));
return {atRest, lengthWas, lengthAfterAnUndoAtRest, ownsItself, typed, undone,
        redone: SURFACE.text().slice(0, 4)};
"""


def test_the_history_buttons_reach_the_second_editors_own_stack(
    client: TestClient, tmp_path: Path
):
    """The fourth state, and the one where the answer is "not this page's".

    `f7bde59` taught Ace's own `UndoManager` to ignore the deltas this tab did
    not make, which is the half that stops one press of Ctrl+Z deleting somebody
    else's sentence for everybody. That manager is also what Ace's own command
    table reaches, and it reaches it before this page's keydown listener sees the
    key at all — `stopEvent` does `stopPropagation` as well as `preventDefault`.
    So the toolbar is pointed at the same stack rather than at the room's: two
    histories over one document, with the key going to one and the button to the
    other, is worse than either.

    `provides.history` is what says so, and `ownsItself` asks the decision rather
    than inferring it from an outcome — an outcome the room's manager would
    produce too, on this document, in this order.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text, tmp_path / "ace-history.html",
        1400, _HISTORY_ON_ACE, query="?editor=ace", patience=6800,
    )

    assert not got.get("missing"), "the second editor carries no history buttons"
    assert got["ownsItself"], (
        "the toolbar is asking the room for a history Ace keeps itself, which leaves "
        "the button and Ctrl+Z pointed at two different stacks"
    )
    assert got["atRest"] == {"undo": True, "redo": True}, (
        "a freshly seeded document offers an undo, and there is nothing behind the seed "
        "to give anybody back"
    )
    # And what that button did before it was disabled, kept as the measurement
    # rather than as a sentence: `editor.setValue` is `session.doc.setValue`,
    # which is an ordinary insert to the undo manager, while it is
    # `session.setValue` that calls `reset()`. One press at rest took the
    # document from 119 characters to 0 — and in a room that goes out as an
    # update frame and is committed.
    assert got["lengthWas"] > 0, "nothing was seeded, so this measures nothing"
    assert got["lengthAfterAnUndoAtRest"] == got["lengthWas"], (
        f"one undo on a freshly opened document took it from {got['lengthWas']} "
        f"characters to {got['lengthAfterAnUndoAtRest']}"
    )
    assert got["typed"] == {"head": "ACE ", "undo": False, "redo": True}
    assert got["undone"]["head"] != "ACE ", (
        f"the undo button did not reach Ace's stack: {got['undone']['head']!r}"
    )
    assert got["undone"]["redo"] is False, "and nothing was offered back the other way"
    assert got["redone"] == "ACE ", "redo did not answer a keyboard press"


_CONNECTION_GONE = """
const area = document.querySelector('textarea[name=body]');
const status = document.getElementById('upload');
const region = document.getElementById('state');
const loose = [];
addEventListener('unhandledrejection', event => {
  loose.push(String(event.reason));
  event.preventDefault();
});
document.getElementById('toggle').click();
const real = window.fetch;
const set = text => {
  area.value = text;
  area.dispatchEvent(new Event('input', {bubbles: true}));
  area.focus();
  area.setSelectionRange(text.length, text.length);
};
const pasteImage = name => {
  const data = new DataTransfer();
  data.items.add(new File(['x'], name, {type: 'image/png'}));
  area.focus();
  area.dispatchEvent(new ClipboardEvent(
    'paste', {clipboardData: data, bubbles: true, cancelable: true}));
};
const settle = ms => new Promise(go => setTimeout(go, ms));

// 1. The upload, with the connection going while the request is in the air.
set('before\\n');
window.fetch = async () => { throw new TypeError('Failed to fetch'); };
pasteImage('diagram.png');
await settle(200);
const dropped = {body: area.value, status: status.textContent, said: region.textContent};
// And one press of undo still reaches the paragraph, so taking the placeholder
// away did not cost the stack the placeholder was pushed onto.
document.execCommand('undo');
const afterUndo = area.value;

// 2. The upload lands, and the placeholder is not there any more — undone, typed
// over, or replaced wholesale by a restored draft while it was in the air.
set('before\\n');
let release;
window.fetch = async () => {
  await new Promise(go => { release = go; });
  return {ok: true, status: 200,
          json: async () => ({path: 'assets/abc.png', fresh: true, commit: 'c0ffee'})};
};
pasteImage('diagram.png');
await settle(60);
const waiting = area.value;
set('somebody typed over the whole thing\\n');
release();
await settle(120);
const orphaned = {body: area.value, status: status.textContent, said: region.textContent};

// 3. Save, on the same dead connection. The one everybody presses.
set('a different paragraph\\n');
region.textContent = '';
window.fetch = async () => { throw new TypeError('Failed to fetch'); };
let threw = null;
try { await save(); } catch (error) { threw = String(error); }
await settle(60);
const saving = {said: region.textContent, enabled: !document.getElementById('save').disabled};

window.fetch = real;
return {dropped, afterUndo, waiting, orphaned, threw, saving, loose};
"""


def test_a_connection_that_drops_leaves_no_placeholder_and_no_sentence_that_is_still_true(
    client: TestClient, tmp_path: Path
):
    """Both `await fetch` sites on this page were `try`/`finally` with no `catch`.

    A rejection escapes a `finally`. It runs the block and carries on unwinding,
    so the two lines that take a "still happening" sentence back down were never
    reached and the page was left asserting something that had stopped being true:
    the upload with `![uploading diagram.png…]()` sitting in the document under a
    bar reading `uploading diagram.png…`, and Save with the live region reading
    `saving…` for ever and the button still enabled.

    Fixed together in one commit on purpose. A `catch` on the uploader alone
    would have left the strictly worse silence on the path everybody walks — an
    image paste is a gesture some people never make, and Save is the button the
    whole form exists for.

    Neither sentence guesses. A fetch rejects when the answer is lost as readily
    as when the request never left, so Save says what to do rather than what
    happened, and the compare-and-swap is what settles it on the next press.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "dropped.html", 1200,
        _CONNECTION_GONE, patience=4800,
    )

    assert got["loose"] == [], f"a rejection still escapes: {got['loose']}"
    assert got["threw"] is None, f"and `save()` rejects at its caller: {got['threw']}"

    assert got["dropped"]["body"] == "before\n", (
        "the placeholder is still in the document over a connection that is gone: "
        f"{got['dropped']['body']!r}"
    )
    assert "diagram.png" in got["dropped"]["status"] and (
        "not uploaded" in got["dropped"]["status"]
    ), f"the bar still says the upload is happening: {got['dropped']['status']!r}"
    assert got["dropped"]["said"] == got["dropped"]["status"], (
        "the sentence is on the screen and nowhere a screen reader will find it"
    )
    # Taking the token away is an edit like any other, so it is one undo step and
    # not a `.value` write — which would have wiped whatever was typed before it.
    assert got["afterUndo"] != "before\n", "removing the placeholder cost the undo stack"

    assert got["waiting"] == "before\n![uploading diagram.png…]()", (
        f"the placeholder was never inserted, so step 2 asks nothing: {got['waiting']!r}"
    )
    assert got["orphaned"]["body"] == "somebody typed over the whole thing\n", (
        "the upload wrote its markdown over text that is not the placeholder"
    )
    assert "assets/abc.png" in got["orphaned"]["status"], got["orphaned"]["status"]
    assert "uploaded" != got["orphaned"]["status"], got["orphaned"]["status"]
    assert "type ![diagram](assets/abc.png)" in got["orphaned"]["status"], (
        "the blob was committed and the line that reaches it was not handed over, "
        f"so the upload is unreachable: {got['orphaned']['status']!r}"
    )
    assert got["orphaned"]["said"] == got["orphaned"]["status"]

    assert "saving" not in got["saving"]["said"], (
        f"the live region is still saying the save is happening: {got['saving']['said']!r}"
    )
    assert "not saved" in got["saving"]["said"] and (
        "Press Save again" in got["saving"]["said"]
    ), got["saving"]["said"]
    assert got["saving"]["enabled"], "the way out of a dropped connection is the same button"


_PREVIEW_ONLY_BARS = _STUB_RENDER + r"""
const article = document.querySelector('article.entity');
const shows = what => getComputedStyle(document.querySelector(what)).display;
const seatbar = document.getElementById('seatbar');
document.getElementById('toggle').click();
const empty = seatbar.getBoundingClientRect().height;
document.getElementById('preview').click();
await new Promise(go => setTimeout(go, 200));
// Somebody else is in the document, which is when this bar has anything to say.
document.getElementById('together').textContent = 'Also here: Ann';
return {
  view: VIEW,
  full: article.classList.contains('full'),
  box: shows('.bodywrap'),
  markbar: shows('.markbar'),
  statusbar: shows('.statusbar'),
  seatbar: shows('#seatbar'),
  emptyHeight: empty,
  occupiedHeight: seatbar.getBoundingClientRect().height,
};
"""


def test_preview_only_takes_away_the_controls_and_keeps_the_one_live_fact(
    client: TestClient, tmp_path: Path
):
    """The hide list is a rule about what a bar IS, not a count of them.

    It enumerated `.bodywrap`, `.statusbar` and `.markbar` under a comment saying
    "the two bars", on a surface that has four — and the fourth, `#seatbar`, is a
    `.bodybar` that neither name reaches, so `.entity.editing .bodybar` went on
    winning. That was found as a leak. It is kept as a decision, and this test is
    where the decision lives so the next person does not quietly flip it.

    The two that go are CONTROLS for a box that is not on the screen: a toolbar
    over no box writes into nothing, and a caret position is about a caret nobody
    can see. The seat bar is not a control. It is a fact about the document, the
    document is still on the screen, and it is the only live signal left in this
    view — the room goes on applying somebody else's keystrokes to the text under
    the rendered pane, and a preview changing under a reader with nothing to say
    why is the worse silence. It costs no space while nobody else is here.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "previewbars.html",
        1400, _PREVIEW_ONLY_BARS, patience=4800,
    )

    assert got["view"] == "view" and got["full"], (
        f"the page is not in preview-only, so this asks nothing: {got}"
    )
    assert got["box"] == "none", "there is still an editing surface under the preview"
    assert got["markbar"] == "none", "sixteen buttons over a box that is not there"
    assert got["statusbar"] == "none", "a caret position for a caret nobody can see"
    assert got["seatbar"] != "none", (
        "who else is in the document went away with the controls — the room is "
        "still live and the text under the preview is still moving"
    )
    assert got["emptyHeight"] == 0, (
        "an empty room costs a line above the toolbar, which is why this bar "
        f"carries no margin of its own: {got['emptyHeight']}"
    )
    assert got["occupiedHeight"] > 0, "and somebody arriving is not drawn at all"


_TOOLBAR_AT_A_WIDTH = _STUB_RENDER + r"""
// The detail page opens read-only and the create forms open editing, so this
// asks for the surface rather than assuming which page it is on.
if (typeof flipEditing === 'function') {
  flipEditing();
  await new Promise(go => setTimeout(go, 150));
}
const marks = document.getElementById('marks');
const article = document.querySelector('article.entity');
const buttons = [...marks.querySelectorAll('button.mark')];
const edge = article.getBoundingClientRect().right;
return {
  width: innerWidth,
  buttons: buttons.length,
  rows: new Set(buttons.map(b => Math.round(b.getBoundingClientRect().top))).size,
  // How far the rightmost button reaches past the surface it is drawn on.
  // Negative is inside.
  past: Math.round(Math.max(...buttons.map(b => b.getBoundingClientRect().right)) - edge),
  // And whether the toolbar is what pushes the page sideways. Compared against
  // the same page's own width rather than against a fixed number: at 390px this
  // application already overflows from the nav shell alone, on every page,
  // including ones with no editor at all.
  scrollW: document.documentElement.scrollWidth,
  flex: getComputedStyle(marks).flex + ' | ' + getComputedStyle(marks).minWidth,
};
"""


@pytest.mark.parametrize("where", ["detail", "note"])
@pytest.mark.parametrize("width", [500, 1000])
def test_every_button_on_the_toolbar_can_be_reached_at_a_window_that_is_not_wide(
    client: TestClient, tmp_path: Path, where: str, width: int
):
    """`.marks { flex: none }` is `0 0 auto` with the default `min-width: auto`,
    which pins the bar at its max-content width whatever the window — so the
    `flex-wrap: wrap` on the same rule, credited in the comment above it as "the
    answer to a window narrower than the toolbar itself", could never engage.

    Measured in Chrome at 500px, on this page and on the create forms: the Link,
    Image, Table and Horizontal-rule buttons sat 101px past the right edge of
    `article.entity`, and the document scrolled sideways to 581px to hold them.
    Four of sixteen controls off the surface, on every page that has an editor.

    Two things this asks that a stylesheet cannot answer, and one it must not.
    Where a button ENDS UP is layout, and `tests/cascade.py` skips at-rule
    bodies, so it resolves the wide page and cannot see this one at all. And the
    comparison is button-right against article-right and never
    `scrollWidth <= innerWidth`: at 390px every page in this application already
    overflows from the nav shell, with no editor on it, so a test written that
    way would be measuring something else and failing for a reason it did not
    name.

    A media query and not a container query. The file's only
    `container-type: inline-size` is on `article.entity` inside `_DETAIL_STYLE`,
    and the note and issue pages ship `_RECORD_STYLE + _SUGGEST_STYLE` and never
    load it — which is why this is parametrised over both surfaces. A container
    query was patched in and measured byte-identical to no fix at all here.
    """
    page = (
        client.get(f"/detail/{TASK}").text if where == "detail" else client.get("/note/new").text
    )
    got = measured_in(
        chrome(), page, tmp_path / f"bar-{where}-{width}.html", width, _TOOLBAR_AT_A_WIDTH,
        patience=4800,
    )

    assert got["width"] == width and got["buttons"] == 16, got
    assert got["past"] < 0, (
        f"at {width}px the toolbar reaches {got['past']}px past the edge of the surface "
        f"it is drawn on, so the buttons on the end cannot be pressed: {got['flex']}"
    )
    assert got["scrollW"] == width, (
        f"the toolbar is pushing the whole page sideways at {width}px: "
        f"{got['scrollW']} against a {width}px window"
    )
    if width >= 1000:
        # And the row it has been on since the marks shipped. `flex: none` is
        # what keeps it there when there IS room: the bar shares a flex line with
        # a status message up to 97 characters long, and without it the marks
        # shrink and wrap with the break falling inside a group.
        assert got["rows"] == 1, (
            f"the toolbar wrapped at {width}px, where it fits: {got['rows']} rows"
        )


_ACE_CARET_MOVES = r"""
document.getElementById('toggle').click();
await new Promise(go => setTimeout(go, 300));
const editor = SURFACE.editor;
const bar = document.getElementById('statusbar');
if (!editor || !bar) return {missing: true};
const where = () =>
  [...bar.children].map(one => one.textContent).find(text => text.startsWith('Line'));

// A document with room to move about in, put there through the surface so the
// seeding path is the one everything else uses.
editor.focus();
editor.selection.selectAll();
SURFACE.splice(0, SURFACE.text().length, 'alpha\nbeta\ngamma\ndelta\n');
await new Promise(go => setTimeout(go, 120));
const seeded = where();

// Three ways a caret moves with the document standing still, and none of them
// is an edit: a jump, an arrow key and a click in the text.
editor.gotoLine(3, 4);
await new Promise(go => setTimeout(go, 80));
const afterJump = where();
editor.navigateUp(1);
await new Promise(go => setTimeout(go, 80));
const afterArrow = where();
editor.selection.moveTo(0, 2);
await new Promise(go => setTimeout(go, 80));
const afterClick = where();

// And the caret this tab would tell a room about, which hangs off the same
// event and is the reason this is not only a readout.
const seats = [];
SURFACE.onCaret(() => seats.push(SURFACE.caret().from));
editor.selection.moveTo(3, 1);
await new Promise(go => setTimeout(go, 80));
return {seeded, afterJump, afterArrow, afterClick, seats,
        at: SURFACE.caret().from};
"""


def test_the_second_editors_caret_is_reported_when_it_moves_and_not_when_it_types(
    client: TestClient, tmp_path: Path
):
    """`drain` was the only thing on this surface that fired `caret`.

    `drain` runs off a document change, so an arrow key, a click in the text, a
    jump and a fold each moved the caret and told nobody. Measured in Chrome
    before this: `gotoLine(3, 4)` and then one line up left the status bar
    reading `Line 1, Column 1`, and it corrected itself at the next keystroke —
    so ask 5's caret readout was showing where you last typed, which is the one
    position it is never useful to know.

    The second subscriber is `sit()`, which is why this is not only a readout: on
    the second surface this tab's seat went up the socket once per burst of
    typing and never on the move in between, so everybody else in the room drew
    a band where this person last typed. `provides.seats` is false here, so Ace
    does not draw anybody else's — but it still sends its own, and a textarea at
    the other end draws it.

    `changeCursor` rather than `changeSelection`, coalesced onto a microtask for
    the reason `drain` coalesces: a substitution moves the cursor once per
    replacement and `attachStatus`'s refresh splits the whole document.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text, tmp_path / "ace-caret.html",
        1400, _ACE_CARET_MOVES, query="?editor=ace", patience=6800,
    )

    assert not got.get("missing"), "the second editor did not mount, or carries no status bar"
    assert got["seeded"].startswith("Line 5, Column 1"), (
        f"the document was not seeded where this expects: {got['seeded']!r}"
    )
    assert got["afterJump"].startswith("Line 3, Column 5"), (
        f"a jump moved the caret and the bar went on describing the last edit: "
        f"{got['afterJump']!r}"
    )
    assert got["afterArrow"].startswith("Line 2, Column 5"), (
        f"an arrow key moved the caret and nothing said so: {got['afterArrow']!r}"
    )
    assert got["afterClick"].startswith("Line 1, Column 3"), (
        f"a click in the text moved the caret and nothing said so: {got['afterClick']!r}"
    )
    assert got["seats"] and got["seats"][-1] == got["at"], (
        "the caret this tab would send to a room was not offered when it moved, so "
        f"everybody else's band stays where this person last typed: {got['seats']}"
    )
