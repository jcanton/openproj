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
import time
from pathlib import Path

import httpx
import pygit2
import pytest
from browser import _devtools, _evaluated, chrome, in_a_live_page, measured_in
from fastapi.testclient import TestClient
from pages import elements
from test_store import commit_directly
from test_web import (
    ANN,
    DONE,
    OTHER,
    PATH,
    PNG,
    SECRET,
    SEED,
    TASK,
    file_at,
    git_head,
    head,
    live_server,
    save,
)

from openproj.auth import sign_session
from openproj.web import MAX_ASSET_BYTES, SESSION_COOKIE, create_app

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
    stored = client.get("/api/index.json").json()["plan"][TASK]["body"]
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


def test_the_way_in_is_at_the_top_and_what_you_do_with_it_is_beside_it(page: str):
    """All three in one place, at the top — jcanton, 2026-08-20.

    They were split: Edit at the head of the record and Save and Cancel in a
    sticky bar at its foot. Both halves were argued for and both arguments were
    about reachability, which the stickiness had already settled — what the split
    actually decided was that the control which begins an edit and the ones which
    commit or undo it were in two places, a shaping document apart. (Cancel became
    Reset on 2026-08-25 and stopped being a way out at all; the ways out are the
    view switcher on the same row and Escape.)

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
    assert 'id="save"' in bar and 'id="reset"' in bar
    # The way in is the view switcher, and it is not one of the ways out: the
    # segments live on the editbar above the commit bar, never inside it.
    assert 'id="views"' not in bar, "the way in is one of the ways out"
    assert page.index('id="views"') < page.index('id="commitbar"')
    assert page.index('id="views"') < page.index('<dl id="facts">')
    assert 'id="toggle"' not in page, (
        "a second door into the session, one control's width from the switcher"
    )


def test_the_bar_says_how_much_is_unsaved(page: str):
    """A button that looks the same whether or not anything has been typed is a
    button you press to find out. The count is of changed fields plus the body,
    because those are exactly what a save would send."""
    assert 'id="unsaved"' in page
    assert "BAR.classList.toggle('dirty', count > 0)" in page
    assert re.search(r"unsaved change\$\{count === 1 \? '' : 's'\}", page)
    assert ".commitbar.dirty { border-color: var(--warn); }" in page


def test_reset_puts_the_record_back_and_stays_in_the_editor(
    client: TestClient, tmp_path: Path
):
    """Reset undoes, and it is the only thing it does.

    jcanton, 2026-08-25: "the 'Cancel' button exits editing and goes to preview,
    even if there's no edit to cancel. maybe we should change its function: call
    it 'reset' and it undoes unsaved changes but doesn't change view to preview?"

    Cancel named an ending and did two things — put the fields back AND leave the
    session — so the only control that undid an edit was also the only control
    that closed the box. This asserts they are separated: the field goes back,
    the document goes back, the bar stops counting, and the article is still
    editing when it is over.

    The document is the half Cancel deliberately did not touch, and the reason it
    does now is the name: a Reset that leaves the longest thing on the page
    exactly as it was is a button that lies. It goes back through
    `SURFACE.splice`, so it is one undo step away — see the comment on
    `resetEdits`, and `test_reset_puts_the_base_back_with_the_text` for the
    commit that has to go with it.

    Asked of the browser rather than of the source, because what went wrong was a
    value left in a box and a box is a thing only a browser has — and of the
    PLAIN box, because this one types into the document as well as into a field,
    and on Ace the `<textarea>` is a hidden element nothing reads.
    """
    plain = client.get(f"/detail/{TASK}{PLAIN}").text
    found = measured_in(
        chrome(), plain, tmp_path / "reset.html", 1100,
        """
        const bar = document.getElementById('commitbar');
        const owner = document.querySelector('[name=owner]');
        const body = document.querySelector('[name=body]');
        const article = document.querySelector('article.record');
        flipEditing();
        await new Promise(settled => setTimeout(settled, 40));
        const was = {owner: owner.value, body: body.value};
        const quiet = document.getElementById('reset').disabled;
        owner.value = 'somebody-else';
        owner.dispatchEvent(new Event('input', {bubbles: true}));
        body.value = body.value + '\\nA paragraph nobody committed.';
        body.dispatchEvent(new Event('input', {bubbles: true}));
        const typed = {said: document.getElementById('unsaved').textContent,
                       hidden: bar.hidden,
                       disabled: document.getElementById('reset').disabled};
        document.getElementById('reset').click();
        await new Promise(settled => setTimeout(settled, 60));
        return {was, quiet, typed, owner: owner.value, body: body.value,
                editing: article.classList.contains('editing'),
                view: [...article.classList].filter(c => c.startsWith('view-')),
                disabled: document.getElementById('reset').disabled,
                said: document.getElementById('unsaved').textContent,
                announced: document.getElementById('state').textContent};
        """,
        height=1200, patience=2500,
    )
    # Nothing typed yet, so there is nothing to undo and the control says so.
    assert found["quiet"] is True, "Reset is pressable over a record nobody has typed into"
    # The changes were real and counted while they were being made.
    assert found["typed"] == {
        "said": "2 unsaved changes", "hidden": False, "disabled": False,
    }
    # And are gone afterwards, from the boxes as well as from the bar.
    assert found["owner"] == found["was"]["owner"], "Reset left the typed value in the control"
    assert found["body"] == found["was"]["body"], "Reset left the typed paragraph in the box"
    assert found["said"] == "Nothing changed yet"
    assert found["disabled"] is True, "Reset is still pressable with nothing left to undo"
    # And the whole of what jcanton asked for: it did not throw you out.
    assert found["editing"], "Reset ended the editing session it was asked to leave alone"
    assert found["view"] == ["view-edit"], (
        f"Reset changed which view the editor is in: {found['view']}"
    )
    # Said out loud. The three worst rounds this repository has had each destroyed
    # somebody's writing without a word, and discarding an edit is that shape — the
    # difference has to be that this one says what it did.
    assert found["announced"] == "Reset, 2 unsaved changes discarded"


def test_reset_puts_the_base_back_with_the_text(client: TestClient, tmp_path: Path):
    """The commit a restored draft moved backwards goes forward again with it.

    A draft written against an older commit moves `BASE.value` back to that
    commit, and what justifies the move is that the older TEXT is in the box.
    Reset puts the server's text back — so leaving the base behind would leave
    the page holding today's document against yesterday's commit, which is the
    exact mismatch compare-and-swap exists to catch, arranged by the button that
    was supposed to tidy up.

    In Chrome and not in the node shim, although the shim can seed a draft: the
    document goes back through `SURFACE.splice`, which routes a person's edit
    through `execCommand` and a selection, and the shim has neither. It answered
    that the reset had happened while leaving the draft's paragraph in the box —
    a harness saying yes to a question about an editor it does not have.
    """
    first = head(client)
    save(client, TASK, {}, body="Somebody else's paragraph.\n")
    second = head(client)
    assert first != second

    reopened = client.get(f"/detail/{TASK}{PLAIN}").text
    assert f'name="base_commit" value="{second}"' in reopened
    key = f"openproj:draft:2:{TASK}"
    draft = {"base": first, "text": "Half a paragraph, written before the other one.\n"}
    seeded = _before_the_page_runs(
        reopened,
        f"try {{ localStorage.setItem({json.dumps(key)}, "
        f"{json.dumps(json.dumps(draft))}); }} catch (e) {{}}",
    )
    got = measured_in(
        chrome(), seeded, tmp_path / "base.html", 1100,
        """
        const base = () => document.querySelector('[name=base_commit]').value;
        const body = () => document.querySelector('[name=body]').value;
        await new Promise(settled => setTimeout(settled, 60));
        const restored = {base: base(), body: body()};
        document.getElementById('reset').click();
        await new Promise(settled => setTimeout(settled, 60));
        return {restored, base: base(), body: body(),
                held: localStorage.getItem(""" + json.dumps(key) + """)};
        """,
        height=1200, patience=2500,
    )

    assert got["restored"]["base"] == first, (
        "the draft did not move the base back to begin with, so this test is "
        f"asking nothing: {got['restored']}"
    )
    assert draft["text"] in got["restored"]["body"], "the draft was never restored"
    assert got["base"] == second, (
        "Reset put the server's text back and left the draft's older commit under "
        "it, so the page is holding today's document against yesterday's base"
    )
    assert draft["text"] not in got["body"], "Reset left the draft's text in the box"
    assert got["held"] is None, "Reset left the draft in storage"


def test_resetting_an_edit_nobody_made_is_refused_rather_than_silent(
    page: str, tmp_path: Path
):
    """Opening an edit and pressing Reset is not an event — and it is not a
    press either.

    This used to be a Cancel that quietly closed the editor, which is what
    jcanton reported: "it exits editing and goes to preview, even if there's no
    edit to cancel". The control is disabled while there is nothing to undo, so
    the press cannot happen; the announcement below is what it says if anything
    ever calls the handler anyway, because a control that answers by doing
    nothing is indistinguishable from one that is broken.
    """
    found = measured_in(
        chrome(), page, tmp_path / "quiet.html", 1100,
        """
        flipEditing();
        await new Promise(settled => setTimeout(settled, 40));
        const button = document.getElementById('reset');
        const disabled = button.disabled;
        resetEdits();
        await new Promise(settled => setTimeout(settled, 40));
        return {disabled, announced: document.getElementById('state').textContent,
                editing: document.querySelector('article.record')
                  .classList.contains('editing')};
        """,
        height=1200, patience=2500,
    )
    assert found["disabled"] is True
    assert found["announced"] == "Nothing to reset"
    assert found["editing"], "a reset of nothing still ended the session"


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


def test_a_date_box_is_the_only_copy_of_the_day_it_holds(page: str):
    """No echo beside a date box, and nothing on the page repeating its value.

    This asserted the opposite for most of 2026-08-25. Every `<input type=date>`
    was followed by a `.iso` span reprinting the value in dd.mm.YYYY, because the
    box is drawn in the READER's locale and 2026-09-01 reads as 01/09 at one desk
    and 09/01 at the next. jcanton, having used it: "the date pickers in the
    cycle are still mm/dd/yyyy and on their right is the date reprinted as
    dd.mm.yyy ... delete the echo: it's confusing to have both formats."

    The ambiguity it settled is back for anybody whose browser draws a month
    first — Chrome and Safari honour the document's `lang` and already draw
    25.08.2026, Firefox follows the operating system. That is the trade, it was
    put to him in those words, and this test is where the next person meets it.

    `readDate` stays and is still asserted elsewhere: it is the browser's half of
    one format written in two languages, and
    `test_both_halves_of_the_app_write_a_date_the_same_way` drives it against
    `_read_date` whether or not anything on a page calls it today.
    """
    assert 'type="date"' in control(page, "assigned_on")
    assert "insertAdjacentElement('afterend', echo)" not in page
    assert "'iso field' : 'iso'" not in page
    # And no stylesheet still dresses a span nothing inserts.
    assert not re.search(r"^\.iso \{", page, re.M)


def test_the_facts_read_as_a_column_beside_the_document(page: str):
    """One `<article>` still — the sidebar is a pane inside the record, not a
    second record — and the prose keeps the measure while the facts take the
    space that was empty to the right of it.

    The measure is on `.panes` and not on the article: since 2026-08-24 the
    article is the page's own width, so that the header above the panes is level
    with the nav in all three views instead of riding the split's extra body."""
    assert page.count("<article") == 1
    assert '<aside class="facts">' in page
    assert page.index('<aside class="facts">') < page.index('<div class="main">')
    assert re.search(r"\.panes \{[^}]*width: var\(--measure", page, re.S)
    assert not re.search(r"article\.record \{[^}]*width:", page, re.S)


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def base_of(page: str) -> str:
    return re.search(r'name="base_commit"[^>]*value="([0-9a-f]{40})"', page).group(1)


def test_a_save_changes_one_line_and_leaves_the_file_alone(
    client: TestClient, repo_path: Path, page: str
):
    response = client.patch(
        f"/api/record/{TASK}",
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
        f"/api/record/{TASK}",
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
        f"/api/record/{TASK}",
        json={"base_commit": stale, "fields": {"owner": "bo"}, "body": None},
    )
    response = client.patch(
        f"/api/record/{TASK}",
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

    records, config, _ = load_repo(Path("seed"))
    render_static(build_index(records, config, date(2026, 8, 17)), tmp_path)

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

    **Parsed, not searched.** This asked `page.index("<h1>")` until 2026-08-24,
    which is a claim about a string and not about the document: a stylesheet
    comment on this page explains what pressing Write used to do to the `<h1>`,
    and the four characters in that sentence sorted before the heading itself.
    The page holds four literal `<h1>` and exactly one `<h1>` ELEMENT. A
    substring cannot tell markup from prose about markup; `elements` can, and
    the question here was always "in what order does the document put these".
    """
    def order(page: str, *wanted: str) -> list[int]:
        """Where each of these sits in document order, by name."""
        found = {}
        for at, element in enumerate(elements(page)):
            classes = element.attrs.get("class", "").split()
            for name in wanted:
                if name in found:
                    continue
                if name == "heading" and element.tag == "h1":
                    found[name] = at
                elif name != "heading" and name in classes and element.tag in ("p", "div"):
                    found[name] = at
        missing = [name for name in wanted if name not in found]
        assert not missing, f"the page has no {missing}"
        return [found[name] for name in wanted]

    detail = client.get(f"/detail/{TASK}").text
    back, kind, heading, meta = order(detail, "back", "eyebrow", "heading", "meta")
    assert back < kind < heading < meta, (
        "the header does not read back link, kind, name, id — it reads "
        f"{sorted(zip((back, kind, heading, meta), ('back', 'kind', 'name', 'id'), strict=True))}"
    )
    said = [e for e in elements(detail) if "kind-" in e.attrs.get("class", "")]
    assert len(said) == 1, f"the kind is said {len(said)} times, not once"
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
    assert facts < detail.index('data-hill="record"') < detail.index("</dl>", facts)

    # The create form is the same document in another mode, so the picker that
    # decides the kind sits where the kind chip sits.
    new = client.get("/new").text
    back, picker, heading = order(new, "back", "eyebrow", "heading")
    assert back < picker < heading, "the kind picker is not where the kind chip is"
    assert any(
        "kindpick" in e.attrs.get("class", "") for e in elements(new)
    ), "the eyebrow on the create form is not the picker that decides the kind"

    # The cycle page has no eyebrow on purpose: its heading is "Cycle 37", so the
    # kind is already the first word of the name and a chip above it would be the
    # restatement the id column's kind chip was. What it does share is the shape.
    cycle = client.get("/cycle/37").text
    assert '<p class="back"><a href="/cycles">' in cycle
    back, heading, meta = order(cycle, "back", "heading", "meta")
    assert back < heading < meta, "the cycle page does not share the header's shape"
    assert not [e for e in elements(cycle) if "eyebrow" in e.attrs.get("class", "")]


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


_BETS_ONE_KEY = """
const box = document.querySelector('#bets input.live[data-field="assignees"]');
const key = name => box.dispatchEvent(
  new KeyboardEvent('keydown', {key: name, bubbles: true, cancelable: true}));
box.focus();
box.value = 'b';
box.dispatchEvent(new Event('input', {bubbles: true}));
const list = document.getElementById(box.getAttribute('aria-controls'));
const wasOpen = !list.hidden;
key('Enter');
const picked = {value: box.value, focused: document.activeElement === box,
                staged: PENDING.size};
// An input with a trailing separator reopens the list on the names still free.
box.dispatchEvent(new Event('input', {bubbles: true}));
const reopened = !list.hidden;
key('Escape');
const first = {listShut: list.hidden, value: box.value,
               focused: document.activeElement === box, staged: PENDING.size};
key('Escape');
return {wasOpen, picked, reopened, first,
        after: {value: box.value, focused: document.activeElement === box,
                staged: PENDING.size}};
"""


def test_one_key_does_one_thing_at_the_betting_table(client: TestClient, tmp_path: Path):
    """The betting cells are the third surface where the suggestion list and a
    second listener answer the same key — and the copy here did not honour the
    mark the widget sets. One Enter picked a name AND blurred, staging the list
    half-finished; one Escape closed the list AND reverted the typing it was
    completing.

    Writing this test found a second defect underneath: the page attached the
    widget to every suggest box a second time — the combobox sweep had already
    reached the served markup — so two lists answered together and one Enter
    picked a name from EACH: choosing `bo` wrote `bo, ann, `. The `picked` value
    below pins the single widget; the focus and staging pins hold the guard.
    Driven with real key events, like the gate panel's and the cell editor's
    tests, because both collisions live between listeners on one input and no
    grep of any of them can see it.
    """
    page = client.get("/cycle/37").text
    got = measured_in(chrome(), page, tmp_path / "bets-keys.html", 1400, _BETS_ONE_KEY,
                      height=900)

    assert got["wasOpen"], "the list never opened, so nothing here was asked"
    # Enter with the list open picks the name, completes the token, and leaves
    # the box open for the next one — nothing staged, nothing blurred.
    assert got["picked"]["value"] == "bo, ", "the pick replaced the value instead"
    assert got["picked"]["focused"] is True, "Enter blurred the box with the pick"
    assert got["picked"]["staged"] == 0, "Enter staged the half-finished list"
    assert got["reopened"], "the list did not reopen, so the Escape below asks nothing"
    # Escape with the list open closes the list and only the list.
    assert got["first"]["listShut"] is True
    assert got["first"]["value"] == "bo, ", "closing the list took the typing with it"
    assert got["first"]["focused"] is True, "one Escape dismissed the list AND the edit"
    assert got["first"]["staged"] == 0
    # The second Escape meets no list and is the cell's: reverted, blurred, unstaged.
    assert got["after"]["value"] == ""
    assert got["after"]["focused"] is False
    assert got["after"]["staged"] == 0


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

    assert page.count("dispatchEvent(new Event('openproj:writing'));") == 4, (
        "the cycle record, each record in the batch, and the asset upload and the "
        "drawing save the shared editor helpers carry onto this page — the source "
        "for both of the latter two ships here whether or not this page ever wires "
        "`attachDrawing` to a surface"
    )
    assert page.count("dispatchEvent(new CustomEvent('openproj:wrote'") == 4
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
    with the record's — the static export puts every record in one file, and
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
    table = client.get("/table").text
    assert '<div id="row-conflict" role="status" aria-live="polite" hidden>' in table


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
    refused = client.patch(f"/api/record/{TASK}", json=written)
    assert refused.status_code == 409
    report = refused.json()["conflict"]
    assert PATH in report and "somebody changed this before you" in report
    assert "by bo" in report and "by ann" in report, report
    assert git_head(repo_path) == second, "refused, and yet something was committed"

    # The defect itself, one line, so this test cannot pass for the wrong reason:
    # the same body against the page's fresh commit is taken without a murmur and
    # Bo's paragraph is gone from the file.
    silent = client.patch(f"/api/record/{TASK}", json={**written, "base_commit": second})
    assert silent.status_code == 200
    assert "by bo" not in file_at(repo_path, git_head(repo_path), PATH)


def test_leaving_a_session_keeps_the_draft_and_the_commit_it_was_written_against(
    client: TestClient,
):
    """Leaving the editor discards nothing at all.

    Until 2026-08-25 one of the three doors out — the Cancel button — put the
    fields back and dropped the stored draft on its way, while Escape and the
    view switcher left everything alone. One gesture with two meanings depending
    on which door you used. Undoing is `resetEdits` now and it is a button that
    says so; leaving is this, and what it leaves is everything: the text in the
    box, the draft in storage, and the older commit that draft was written on top
    of.

    That last one is the invariant this test has always been about, and it did
    not move. A page holding work written against an older commit has to go on
    saying so, or `store.write` compares the two things that agree and commits a
    body that silently throws away whoever saved in between.
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
        "(() => { flipEditing();"
        "  return [document.querySelector('[name=base_commit]').value,"
        "          document.querySelector('[name=body]').value,"
        "          document.querySelector('article.record')"
        "            .classList.contains('editing')]; })()",
        page=True,
        storage={key: json.dumps(draft)},
    )
    base, body, editing = after["value"]

    assert not editing, "the door did not close"
    assert key in after["stored"], "leaving the editor threw away the unsaved draft"
    assert body == draft["text"], "the text leaving the editor keeps in the box"
    assert base == first, "leaving put the page's own commit back under older text"
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
    "SURFACE.seats.draw(",                                       # drawSeats
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
                       "onCaret(", "seats:"):
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


def test_the_drawing_menu_lists_what_the_body_embeds_in_the_order_it_embeds_them(
    client: TestClient, tmp_path: Path
):
    """By id and in embed order — jcanton, 2026-08-26. Match order over the raw
    markdown IS embed order, which is why this needs no index and no state.

    Driven through the real page's own `drawingsIn`, not a Python reimplementation
    of the regex — the two would drift the day one of them changed alone.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "drawings.html", 1200,
        """
        const body = "![two](drawings/draw-bbbbbb.png)\\n"
          + "![one](drawings/draw-aaaaaa.png){width=60}\\n"
          + "![again](drawings/draw-bbbbbb.png)\\n"
          + "![a picture](assets/0123456789abcdef.png)\\n"
          + "![nope](drawings/notadrawing.png)\\n";
        return drawingsIn(body);
        """,
    )
    assert [d["id"] for d in got] == ["draw-bbbbbb", "draw-aaaaaa"], (
        "deduped keeping the first occurrence, in match order — not sorted, not "
        "deduped keeping the last, and the assets and non-drawing arms excluded"
    )
    # The FIRST span, not a search for the id that would have landed on
    # whichever occurrence `indexOf` found — proven by the span pointing at the
    # first `draw-bbbbbb`, three lines before the "again" that repeats it.
    assert got[0] == {
        "id": "draw-bbbbbb", "path": "drawings/draw-bbbbbb.png", "alt": "two",
        "from": 0, "to": 32,
    }
    assert got[1] == {
        "id": "draw-aaaaaa", "path": "drawings/draw-aaaaaa.png", "alt": "one",
        "from": 33, "to": 65,
    }


def test_the_drawing_button_opens_a_menu_and_a_press_says_what_was_pressed(
    client: TestClient, tmp_path: Path
):
    """The control and the menu, and now the real listener behind a press —
    `attachDrawing`'s own comment. A press dispatches `openproj:draw` on
    `surface.el` carrying the entry (or `null` for "+ drawing"), which
    `openDrawing` hears and answers by opening the popup; `measured_in` cannot
    drive that mount to completion (see `docs/drawings.md`, "Five helpers, not
    one"), so what is asserted here is the SYNCHRONOUS half: the popup appears
    and the status strip says the bundle is loading, both true the instant the
    press returns and neither dependent on the fetch this page's `file://`
    origin cannot make.

    Also closes Task 7's coverage gap: Escape closing the menu and returning
    focus to the button, and a second press of `#drawing` closing it again,
    were both verified by hand in headless Chrome and neither was asserted.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "drawmenu.html", 1200,
        """
        const area = document.querySelector('textarea[name=body]');
        area.value = 'before\\n![mine](drawings/draw-123abc.png)\\nafter';
        const button = document.getElementById('drawing');
        const namedForReaders = {
          label: button.getAttribute('aria-label'), title: button.title,
        };
        const outsideMarks = document.querySelectorAll('#marks button').length;

        // Escape closes the menu and hands the keyboard back to the button
        // that opened it — Task 7's own comment on this listener, unasserted
        // until now.
        button.click();
        const menu = document.querySelector('.drawmenu');
        menu.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        const closedByEscape = menu.hidden;
        const focusedAfterEscape = document.activeElement === button;

        // A second press of the button while its own menu is open closes it —
        // also Task 7's, also unasserted until now.
        button.click();
        const openBeforeSecondPress = !menu.hidden;
        button.click();
        const closedBySecondPress = menu.hidden;
        const expandedAfterSecondPress = button.getAttribute('aria-expanded');

        button.click();
        const openRows = [...menu.querySelectorAll('button')].map(b => b.textContent);
        const expandedOpen = button.getAttribute('aria-expanded');

        // A mousedown ON the button, or anywhere INSIDE the menu, must not
        // close it out from under a press that is about to choose something —
        // only somewhere else does.
        button.dispatchEvent(new Event('mousedown', {bubbles: true}));
        const openAfterOwnMousedown = !menu.hidden;
        menu.dispatchEvent(new Event('mousedown', {bubbles: true}));
        const openAfterInsideMousedown = !menu.hidden;
        document.body.dispatchEvent(new Event('mousedown', {bubbles: true}));
        const closedByOutsideMousedown = menu.hidden;

        button.click();
        const menu2 = document.querySelector('.drawmenu');
        let heard = 'unset';
        area.addEventListener('openproj:draw', event => { heard = event.detail; });
        // The second row: "+ drawing" is first, the one embedded drawing second.
        menu2.querySelectorAll('button')[1].click();
        const afterPress = {
          hidden: menu2.hidden, expanded: button.getAttribute('aria-expanded'),
          heard, status: document.getElementById('upload').textContent,
          // The real listener now answers a press by opening the popup —
          // `openDrawing` appends it before it ever awaits the bundle, so
          // this is true before the fetch this `file://` page cannot make
          // has even been attempted.
          popupOpened: !!document.querySelector('.drawpopup'),
        };

        button.click();
        let heardNew = 'unset';
        area.addEventListener('openproj:draw', event => { heardNew = event.detail; });
        document.querySelector('.drawmenu button').click();

        return {namedForReaders, outsideMarks, openRows, expandedOpen,
                closedByEscape, focusedAfterEscape,
                openBeforeSecondPress, closedBySecondPress, expandedAfterSecondPress,
                openAfterOwnMousedown, openAfterInsideMousedown, closedByOutsideMousedown,
                afterPress, heardNew};
        """,
    )
    assert got["namedForReaders"] == {"label": "Drawings", "title": "Drawings"}, (
        "an icon with no words is a mystery glyph to a reader who cannot see it"
    )
    assert got["outsideMarks"] == 16, "the menu is page chrome, not a seventeenth FORMATS mark"
    assert got["closedByEscape"], "Escape did not close the menu"
    assert got["focusedAfterEscape"], "Escape closed the menu but did not give the button back"
    assert got["openBeforeSecondPress"], "the first of the pair did not even open it"
    assert got["closedBySecondPress"], "a second press over an open menu did not close it"
    assert got["expandedAfterSecondPress"] == "false"
    assert got["openRows"] == ["+ drawing", "draw-123abc"], "+ drawing leads, the id follows"
    assert got["expandedOpen"] == "true"
    assert got["openAfterOwnMousedown"], "pressing the button that opened it closed it again"
    assert got["openAfterInsideMousedown"], "a press inside the menu closed it before it chose"
    assert got["closedByOutsideMousedown"], "a press outside the button and the menu left it open"
    assert got["afterPress"] == {
        "hidden": True, "expanded": "false",
        "heard": {
            "id": "draw-123abc", "path": "drawings/draw-123abc.png", "alt": "mine",
            "from": 7, "to": 40,
        },
        "status": "loading the drawing editor…",
        "popupOpened": True,
    }, "pressing a row closed the menu, named exactly what was pressed, and opened the popup"
    assert got["heardNew"] is None, '"+ drawing" is a new drawing, and null says so'


def test_no_page_echoes_the_dates_it_is_asking_for(page: str):
    """The create form was the first page to lose the ISO echo, on the grounds
    that its two date boxes are the only dates on screen and had nothing to be
    disambiguated against. On 2026-08-25 every other page followed, by jcanton's
    ruling that two formats on one line is a question rather than an answer — so
    the carve-out this test was written for is now the rule, and the `#create`
    special case it asserted has nothing left to be special about.

    See `test_a_date_box_is_the_only_copy_of_the_day_it_holds` for the trade.
    """
    assert "box.closest('#create')" not in page, "the carve-out outlived the rule"
    assert "insertAdjacentElement('afterend', echo)" not in page


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
                       "goal": "Ship the core solver port"},
            "body": "Throughflow was left out: no reviewer free.\n",
        },
    )
    page = client.get("/cycle/51").text

    goal, bet, notes = (page.index(f"<h2>{h}</h2>") for h in ("Goal", "The bet", "Notes"))
    assert goal < bet < notes
    assert 'id="goal"' in page and 'id="notes"' in page
    assert "Ship the core solver port" in page
    assert "Throughflow was left out" in page
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
flipEditing();

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

return {swallowed, indented, still, back, odd, even, nested, wrote, undone};
"""


def test_tab_indents_the_lines_the_selection_touches(client: TestClient, tmp_path: Path):
    """Tab is the fifth ask, and taking Tab away is how an editor traps somebody
    who has no pointer. The other half — the Escape hatch that gives Tab back —
    lives in the test below, on the page where the box is on the ordinary page:
    here Escape leaves the session and takes the box with it."""
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


def test_escape_still_arms_the_tab_hatch_where_the_box_is_on_the_page(
    client: TestClient, tmp_path: Path
):
    """The hatch's home moved with the null state: on a record page Escape now
    leaves the session (taking the box with it), so the place a first press
    has nothing to leave — and must therefore give Tab back — is the create
    form's ordinary page, which has no landing and keeps the surface-off
    state."""
    got = measured_in(
        chrome(), client.get(f"/new{PLAIN}").text, tmp_path / "hatch.html", 1200,
        _STUB_PREVIEW + """
        const area = document.querySelector('textarea[name=body]');
        // Out of the session views first: the create form's pressed segment
        // goes to the old surface-off state and the box stays on the page.
        const lit = ['view-edit', 'view-both', 'preview']
          .map(id => document.getElementById(id))
          .find(seg => seg.getAttribute('aria-pressed') === 'true');
        if (lit) lit.click();
        const press = key => { area.focus(); return area.dispatchEvent(new KeyboardEvent(
          'keydown', {key, bubbles: true, cancelable: true})); };
        area.value = 'alpha — β';
        area.dispatchEvent(new Event('input', {bubbles: true}));
        press('Escape');
        const said = document.getElementById('state').textContent;
        const passed = press('Tab');
        return {said, passed, value: area.value};
        """,
        patience=2400,
    )
    assert "Tab" in got["said"], "the hatch opened silently or not at all"
    assert got["passed"], "Escape did not give the next Tab back to the browser"
    assert got["value"] == "alpha — β", "the armed Tab indented instead of leaving"


# The four marks the renderer learnt in the same commit, and the two pastes.
# Driven in Chrome rather than read out of the page, because every one of these
# is a claim about a selection: which characters were chosen when the button was
# pressed, and which are chosen afterwards.
_MARKING = """
const area = document.querySelector('textarea[name=body]');
flipEditing();
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
# --- three views of one page, and the two panes ------------------------------
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
const article = document.querySelector('article.record');
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const marks = document.getElementById('marks');
const doc = article.querySelector('.doc.read');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
const drawn = element => element.getClientRects().length > 0;
const state = () => ({
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  pressed: ['edit', 'both', 'view'].filter(
    n => seg(n).getAttribute('aria-pressed') === 'true'),
  editing: article.classList.contains('editing'),
  box: drawn(area),
  pane: drawn(pane),
  marks: drawn(marks),
  doc: drawn(doc),
  position: getComputedStyle(article).position,
});

const atLoad = state();
// The segment IS the door in: there is no Edit button beside a switcher that
// opens the same session.
seg('edit').click();
const editing = state();
// Enough lines that the box has something to scroll — and not ASCII, because
// no test drives this editor with ASCII alone.
area.value = Array.from({length: 200},
  (_, i) => `Zeile ${i + 1} — ` + 'w'.repeat(88)).join('\\n');
area.dispatchEvent(new Event('input', {bubbles: true}));
await new Promise(go => setTimeout(go, 80));

// Every view change has to tell the seat layer the box moved; a change that
// crosses the session boundary says it twice — once from `showEditing`, once
// from `showView` — which the count below spells out.
let told = 0;
addEventListener('openproj:editing', () => { told++; });

seg('both').click();
const both = state();
await new Promise(go => setTimeout(go, 400));
const split = {
  sideBySide: area.getBoundingClientRect().right <= pane.getBoundingClientRect().left + 1,
  // One height for the pair: the box is pinned to `--writing` and the pane
  // takes the same number, so the two read as one surface with a join.
  sameHeight: Math.abs(area.getBoundingClientRect().height
                       - pane.getBoundingClientRect().height) <= 2,
  boxScrolls: area.scrollHeight > area.clientHeight + 1,
  paneScrolls: pane.scrollHeight > pane.clientHeight + 1,
  pageScrolls: document.documentElement.scrollHeight > innerHeight + 1,
};

seg('view').click();
const viewing = state();
seg('edit').click();
const writing = state();
// Pressing the pressed segment is the way back out with a pointer — to the
// landing, which ends the session.
seg('edit').click();
const out = state();

const chord = code => dispatchEvent(new KeyboardEvent(
  'keydown', {ctrlKey: true, shiftKey: true, code, key: '@', bubbles: true}));
chord('Digit2');
const chorded = state();
chord('Digit2');
const unchorded = state();

// And AltGr does not reach it — the euro sign on the Swiss-German layout half
// this team types on arrives as ctrl+alt, exactly as dispatched here.
dispatchEvent(new KeyboardEvent('keydown', {
  ctrlKey: true, altKey: true, modifierAltGraph: true, code: 'KeyE', key: '€',
  bubbles: true, cancelable: true,
}));
const afterEuro = state();

seg('both').click();
area.focus();
area.dispatchEvent(new KeyboardEvent(
  'keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const escaped = state();

return {atLoad, editing, both, split, viewing, writing, out, chorded, unchorded,
        afterEuro, escaped, told, asked: window.asked.length};
"""


def test_the_three_views_are_one_of_three_and_each_pane_scrolls_on_its_own(
    client: TestClient, tmp_path: Path
):
    """Three states, and the landing one is `view`.

    `view` is the ordinary page — the server-rendered document, the facts
    column — and it is where every session ends. `edit` and `both` are
    sessions: the SAME page, still `position: relative`, still one column of
    prose at the reader's own measure, with the box in the document's column —
    jcanton, 2026-08-24, the ask this branch is for. ("Centred" until later the
    same day, when the header took the page's width and the column under it was
    pinned to the page's left edge rather than indented from its own title.)
    The `full` in each expected class list below is asserted absent by
    equality: a session that grew a full-page surface again fails every one of
    these.

    The fourth, unnamed state is gone: exactly one segment is always pressed,
    the pressed segment and the chord and Escape all land on the landing, and
    landing ends the session — without discarding anything, because the text
    stays in the surface and only Cancel restores fields.
    """
    LANDED = {
        "classes": ["view-view"], "pressed": ["view"], "editing": False,
        "box": False, "pane": False, "marks": False, "doc": True,
        "position": "relative",
    }
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "views.html",
        1400, _VIEWING, patience=4800,
    )

    assert got["atLoad"] == LANDED, f"the page did not load on the landing: {got['atLoad']}"
    assert got["editing"] == {
        "classes": ["view-edit"], "pressed": ["edit"], "editing": True,
        "box": True, "pane": False, "marks": True, "doc": False, "position": "relative",
    }, "pressing Write did not open a session in the edit view, on the same page"

    assert got["both"]["classes"] == ["view-both"]
    assert got["both"]["pressed"] == ["both"], "two segments pressed is not a choice of three"
    assert got["both"]["position"] == "relative" and got["both"]["editing"]
    assert got["both"]["box"] and got["both"]["pane"]

    # `pageScrolls: True` is the new design, stated rather than tolerated: the
    # split is a region of an ordinary page, each pane scrolls inside itself,
    # and the page underneath goes on scrolling to the facts and the promote
    # bar. Under full page this was False because `body.fullpage` cut the
    # page's own scrollbar off — that surface is gone.
    assert got["split"] == {
        "sideBySide": True, "sameHeight": True,
        "boxScrolls": True, "paneScrolls": True, "pageScrolls": True,
    }, "the two panes do not sit beside each other and scroll on their own"

    assert got["viewing"] == LANDED, (
        "the eye did not land on the sessionless read page — a live pane, a "
        f"surface, or a session survived: {got['viewing']}"
    )
    assert got["writing"]["classes"] == ["view-edit"] and got["writing"]["editing"]
    assert got["out"] == LANDED, "the pressed segment did not land on the landing"

    assert got["chorded"]["pressed"] == ["both"], "Ctrl+Shift+2 was not read off event.code"
    assert got["unchorded"] == LANDED, "the same chord did not come back to the landing"
    assert got["afterEuro"] == LANDED, (
        "AltGr+E moved the view: the chord swallows a character people type"
    )
    assert got["escaped"] == LANDED, "Escape did not land on the landing"

    # One `openproj:editing` per view change, and a second per session
    # boundary (from `showEditing`): both(1) + view(2) + edit(2) + edit(2)
    # + chord(2) + chord(2) + euro(0) + both(2) + escape(2).
    assert got["told"] == 15, f"a view change the seat layer was not told about: {got['told']}"
    assert got["asked"] >= 1, "the preview was never asked for"


_DEEP_LINK = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
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

    assert got["classes"] == ["view-both"]
    assert got["pressed"] == ["view-both"]
    assert got["editing"], "a link into a writing view that does not open the writing view"

    plain = measured_in(chrome(), page, tmp_path / "plain.html", 1400, _DEEP_LINK)
    assert plain["classes"] == ["view-view"] and plain["pressed"] == ["preview"]
    assert not plain["editing"], "no link, and the page opened a session anyway"


# The socket, counted and timestamped: `bodyAtConnect` is what the surface held
# at the instant the room was joined, which is the fact the restore-before-
# connect ordering is pinned by.
_SOCKETS = """
window.__sockets = [];
class CountingSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url) {
    window.__sockets.push(this);
    this.url = url;
    this.readyState = 1;
    const body = document.querySelector('textarea[name=body]');
    this.bodyAtConnect = body ? body.value : '';
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(data) {}
  close() { this.readyState = 3; setTimeout(() => this.onclose && this.onclose({}), 0); }
  hear(message) { this.onmessage && this.onmessage({data: JSON.stringify(message)}); }
}
window.WebSocket = CountingSocket;
"""

# No `_STUB_PREVIEW` prefix here, deliberately: `measured_in` runs this script
# at SETTLE (1200ms), AFTER the page's load-time behaviour. A fetch counter
# installed here would miss every /api/preview the page asked at load — the
# very thing `asked` pins — so the stub goes into the <head> beside `_SOCKETS`
# and counts from t=0.
_LINKED = """
const article = document.querySelector('article.record');
const doc = article.querySelector('.doc.read');
return {
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  editing: article.classList.contains('editing'),
  pressed: ['view-edit', 'view-both', 'preview'].filter(
    id => document.getElementById(id).getAttribute('aria-pressed') === 'true'),
  fullpage: document.body.classList.contains('fullpage'),
  navInert: !!document.querySelector('body > nav').inert,
  docShown: doc.getClientRects().length > 0,
  paneHidden: document.getElementById('body-preview').hidden,
  sockets: window.__sockets.length,
  asked: window.asked.length,
};
"""


def test_a_view_link_is_sessionless_and_a_both_link_opens_a_session(
    client: TestClient, tmp_path: Path
):
    """Spec test 6, both halves in one place so a regression of either shows.

    `?view` used to open a session — `showView` forced `showEditing(true)` —
    so there was no way to hand somebody a link to LOOK at a rendered record.
    It is the sessionless read page now: no full page, nav alive, the
    server-rendered document on screen, no seat taken, and no `/api/preview`
    round trip for bytes the server already rendered into the page. `?both` is
    unchanged: a view of a session opens the session it is a view of.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text.replace(
        "<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1
    )

    viewed = measured_in(chrome(), page, tmp_path / "viewlink.html", 1400, _LINKED,
                         query="?view=")
    assert viewed["classes"] == ["view-view"] and viewed["pressed"] == ["preview"]
    assert not viewed["editing"], "?view opened a session"
    assert not viewed["fullpage"] and not viewed["navInert"]
    assert viewed["docShown"], "the server-rendered document is not on the screen"
    assert viewed["paneHidden"], "the landing is drawn in the preview pane, not the page"
    assert viewed["sockets"] == 0, "?view took a co-editing seat"
    assert viewed["asked"] == 0, (
        "the landing asked /api/preview to redraw bytes the server already rendered"
    )

    both = measured_in(chrome(), page, tmp_path / "bothlink.html", 1400, _LINKED,
                       query="?both=")
    assert both["classes"] == ["view-both"] and both["pressed"] == ["view-both"]
    assert both["editing"], "?both did not open the session it is a view of"
    # A session is the same page now: nothing full, nothing inert, the nav
    # alive on both sides of the link — jcanton, 2026-08-24.
    assert not both["fullpage"] and not both["navInert"]
    assert both["sockets"] == 1, "a session opened and no seat was taken"
    assert both["asked"] >= 1, "the live pane never asked for its rendering"


# The stub lives in the <head> here too (same reason as `_LINKED`), so the
# input-driven refreshPreview below hits a working fetch from the first event.
_DIVERGED = """
const article = document.querySelector('article.record');
const area = document.querySelector('textarea[name=body]');
const doc = article.querySelector('.doc.read');
// Non-ASCII on purpose: no test drives this editor with plain ASCII alone —
// the last three shipped defects each hid behind a corpus that did.
const marker = ' — verworfen, aber aufgehoben ✎';
document.getElementById('view-edit').click();
area.value = area.value + marker;
area.dispatchEvent(new Event('input', {bubbles: true}));
await new Promise(go => setTimeout(go, 80));
flipEditing();
await new Promise(go => setTimeout(go, 80));
return {
  landed: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  editing: article.classList.contains('editing'),
  docShown: doc.getClientRects().length > 0,
  docHoldsDraft: doc.textContent.includes(marker),
  boxHoldsDraft: area.value.includes(marker),
  paneHidden: document.getElementById('body-preview').hidden,
};
"""


def test_cancel_with_a_divergent_draft_lands_on_the_stored_commit(
    client: TestClient, tmp_path: Path
):
    """Spec test 7: the landing always renders the stored commit, never the
    live surface.

    Cancel deliberately leaves draft text in the box — the three worst rounds
    this repository has had each destroyed somebody's writing without a word —
    so the page Cancel lands on holds two truths at once: the box still has
    the draft, and the document on screen is what git has. A landing wired to
    the live surface would show uncommitted text as though it were the record.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text.replace(
        "<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1
    )
    got = measured_in(chrome(), page, tmp_path / "diverged.html", 1400, _DIVERGED,
                      patience=2400)

    assert got["landed"] == ["view-view"] and not got["editing"]
    assert got["docShown"], "no document on the page Cancel landed on"
    assert not got["docHoldsDraft"], (
        "the landing shows the live surface: uncommitted text drawn as the record"
    )
    assert got["boxHoldsDraft"], "Cancel destroyed the draft instead of keeping it in the box"
    assert got["paneHidden"]


def test_a_draft_at_load_forces_a_session_and_the_room_refusal_still_fires(
    client: TestClient, tmp_path: Path
):
    """Spec test 8: the one exception to sessionless landing, and why.

    The stored-draft restore stays at page load and keeps forcing a session.
    Deferred to the Write press, the draft would be spliced in AFTER the room
    has bound, leave as ordinary typing, and bypass the draft-versus-moved-
    room refusal. Restore-before-connect is the ordering that keeps the
    refusal alive: the surface holds the draft when the room is joined, so
    `welcomed` sees two histories and refuses to guess.
    """
    key = f"openproj:draft:2:{TASK}"
    draft = {"base": "1" * 40, "text": "Größer als geplant — ein Entwurf №8\n"}
    seed = (
        f"try {{ localStorage.setItem({json.dumps(key)}, "
        f"{json.dumps(json.dumps(draft))}); }} catch (e) {{}}"
    )
    page = _before_the_page_runs(client.get(f"/detail/{TASK}{PLAIN}").text, seed)
    page = page.replace("<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1)

    got = measured_in(
        chrome(), page, tmp_path / "draftload.html", 1400,
        """
        const article = document.querySelector('article.record');
        const area = document.querySelector('textarea[name=body]');
        const socket = window.__sockets[0] || null;
        const forced = {editing: article.classList.contains('editing'),
                        connected: window.__sockets.length,
                        heldAtConnect: socket ? socket.bodyAtConnect : '',
                        base: document.querySelector('[name=base_commit]').value};
        // The room answers with a document that is not what this page was
        // rendered from — an empty seed, which is what a moved room looks
        // like to a page holding hour-old text.
        if (socket) socket.hear({t: 'welcome', seed: 'a'.repeat(40),
                                 base: 'a'.repeat(40), you: 'ann', sv: 'AA==',
                                 update: '', people: ['ann']});
        await new Promise(go => setTimeout(go, 80));
        const box = document.getElementById('conflict');
        return {forced, refused: socket ? !box.hidden : null,
                report: box.textContent, boxNow: area.value};
        """,
        patience=2400,
    )

    marker = draft["text"].strip()
    assert got["forced"]["editing"], "a stored draft no longer forces a session at load"
    assert got["forced"]["connected"] == 1, "the forced session joined no room"
    assert got["forced"]["base"] == draft["base"], (
        "the restore did not move base_commit back under the draft"
    )
    assert marker in got["forced"]["heldAtConnect"], (
        "the room was joined before the draft was in the surface — from here "
        "the draft leaves as ordinary typing and the refusal below never fires"
    )
    assert got["refused"], "two histories, no common base, and nothing refused to guess"
    assert marker in got["report"], "the refusal does not carry the draft back to its author"
    assert marker not in got["boxNow"], (
        "the draft is still in the box after the refusal said the room's text is"
    )


def test_a_stored_legacy_view_mode_opens_the_next_session_in_edit(
    client: TestClient, tmp_path: Path
):
    """The stored word `view` meant "open sessions in preview-only" yesterday
    and names the sessionless landing today. A session cannot open
    sessionless, so a legacy value migrates to `edit` on read rather than
    being trusted into a state that no longer exists — risk 5's empty
    full-page grid."""
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % '{"mode": "view"}'
        ),
        tmp_path / "legacy.html", 1400,
        _STUB_PREVIEW + """
        flipEditing();
        const article = document.querySelector('article.record');
        return {view: VIEW, editing: article.classList.contains('editing'),
                full: article.classList.contains('full')};
        """,
        patience=1800,
    )
    # `full: False` is load-bearing since 2026-08-24: a session is the ordinary
    # page, and the class this reads would mean the surface had come back.
    assert got == {"view": "edit", "editing": True, "full": False}, (
        f"a legacy stored mode landed a session somewhere that is not one: {got}"
    )


_GRIPPING = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
// `.panes` and not the article, since 2026-08-24: the article is the width of
// the page in every view — that is what stops the header moving — and a handle
// on ITS edge is the handle parked against the window this test exists about.
// The measure is the column's, so the column is what is measured.
const pane = article.querySelector('.panes');
const grip = document.getElementById('grip');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
// Against the pane's own right edge, and how far that is from the window's — a
// handle parked at the edge of the screen is the bug this is about, and it is
// the one arrangement that looks deliberate.
const where = () => ({
  hidden: grip.hidden,
  onEdge: Math.abs(parseFloat(grip.style.left || '0')
                   - pane.getBoundingClientRect().right) < 1,
  spare: Math.round(innerWidth - pane.getBoundingClientRect().right),
});

const reading = where();
// Entered through the loop itself: pressing the pressed segment would land
// back on the landing, so no segment is pressed twice.
const inView = {};
for (const name of ['edit', 'both']) { seg(name).click(); inView[name] = where(); }
seg('view').click();               // the landing: session over
const back = where();
return {reading, inView, back};
"""


def test_the_width_handle_finds_the_pane_in_every_view(client: TestClient, tmp_path: Path):
    """`place` exists because a handle measured against a hidden element parks
    itself against the left edge of the page, and that shipped once.

    Since a session is the same page (2026-08-24), the handle stays through
    `edit` too: the column's edge IS the measure there, so dragging it means
    what it means on the landing.

    **And through the split, since 2026-08-25.** It was hidden there because the
    split's column is one measure plus one body wide, so "a grip on that edge
    would move the measure twice the drag". That was arithmetic and it is done
    now: the drag divides the pointer's movement by however many measures the
    column is made of, and a hundred pixels of pointer is a hundred pixels of
    column in every view. jcanton, 2026-08-25, wanting to size the pair rather
    than only the join between them.

    The fear that two handles "are two controls nobody can tell apart" did not
    survive use either: `#splitter` moves the boundary BETWEEN the panes and this
    moves the outside edge of both, which is the pair every editor with a split
    has.

    The column is `.panes` and not `article.record` since the header took the
    page's width: the article's right edge is now the window's, `spare` would be
    the body's own padding at every width, and this test would go on passing
    while the handle sat against the edge of the screen — the exact defect it
    was written for."""
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}").text, tmp_path / "grip.html", 1400, _GRIPPING
    )

    for mode in ("reading",):
        assert not got[mode]["hidden"], f"no handle while {mode}"
        assert got[mode]["onEdge"], f"the handle is not on the column's edge while {mode}"
        assert got[mode]["spare"] > 20, f"the handle is against the window edge while {mode}"

    edit = got["inView"]["edit"]
    assert not edit["hidden"], "no width handle in the edit view, whose width is the measure"
    assert edit["onEdge"] and edit["spare"] > 20, edit

    both = got["inView"]["both"]
    assert not both["hidden"], "no width handle in the split view"
    # `>= 20` here and `> 20` above, and the difference is the split's own shape
    # rather than a slacker test: `.panes` carries `max-width: 100%`, and the
    # split asks for one measure plus one body, which at this window is more than
    # there is. So the column sits AT the article's edge and the spare is exactly
    # the body's padding. What the number is guarding against is the handle
    # parking against the edge of the SCREEN, which is what it did when it was
    # measured against a hidden element — that reads 0, not 20.
    assert both["onEdge"] and both["spare"] >= 20, both

    assert not got["back"]["hidden"] and got["back"]["onEdge"], (
        "the handle did not come back with the column"
    )


# What the handle drags, and what answers to it. The window is wide throughout
# and only the measure moves, which is the one arrangement that can tell a
# container query on the column from a media query on the window — and, since
# 2026-08-24, a container on `.panes` from one left behind on a full-width
# `article.record`.
_DRAGGED_NARROW = _STUB_PREVIEW + """
const facts = document.querySelector('.panes > .facts');
const main = document.querySelector('.panes > .main');
const grip = document.getElementById('grip');
const stacked = () => {
  const f = facts.getBoundingClientRect(), m = main.getBoundingClientRect();
  return {beside: f.left >= m.right - 1, factsTop: Math.round(f.top),
          mainTop: Math.round(m.top), factsLeft: Math.round(f.left),
          mainLeft: Math.round(m.left)};
};
// The grip, driven the way a hand drives it: the drag is what writes
// `--measure`, so a test that set the property itself would be asking the
// stylesheet a question the control never asks it.
//
// Asked for a WIDTH, and the pointer worked out from the box — not a screen x
// written down here. The column is centred, so a pixel of pointer is two of
// width; it was left-pinned for one afternoon on 2026-08-24 and a pixel was a
// pixel. A test that hard-codes the screen x is a test that encodes whichever
// of those was true the day it was written, and this one exists to ask about
// the container query rather than about the drag's arithmetic — when the two
// targets stopped meaning 620px and 1044px of column, it failed for a reason
// that had nothing to do with what it checks.
const drag = width => {
  const box = document.querySelector('article.record').getBoundingClientRect();
  // The column is pinned left, so the pointer x that asks for a width IS that
  // width from the article's left edge. This read `box.left + box.width / 2 +
  // width / 2` — the centred-box arithmetic the drag used until 2026-08-25 —
  // and the comment above was already written about exactly this: a helper that
  // encodes the drag's maths asks about the drag, and this test is about the
  // container query. When the maths were corrected, 620 and 1024 stopped
  // meaning 620px and 1024px of column and the query looked broken.
  //
  // So the helper now CHECKS what it achieved rather than assuming it. A drag
  // that lands somewhere else fails here, loudly, instead of surfacing three
  // assertions later as a container query that appears to be answering about
  // the window.
  const to = box.left + width;
  grip.dispatchEvent(new PointerEvent('pointerdown', {
    bubbles: true, pointerId: 1, clientX: grip.getBoundingClientRect().left, clientY: 400}));
  dispatchEvent(new PointerEvent('pointermove', {bubbles: true, pointerId: 1, clientX: to}));
  dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerId: 1}));
  const landed = document.querySelector('.panes').getBoundingClientRect().width;
  return {...stacked(), asked: width, landed: Math.round(landed)};
};
const wide = stacked();
// Either side of the 56rem (896px) the query names, and not close to it: 620
// stacks, 1024 does not, and neither is within a rounding of the boundary.
const narrow = drag(620);
const back = drag(1024);
return {wide, narrow, back, width: innerWidth,
        measure: getComputedStyle(document.documentElement)
                   .getPropertyValue('--measure').trim()};
"""


def test_the_facts_answer_to_the_column_the_reader_drags_and_not_to_the_window(
    client: TestClient, tmp_path: Path
):
    """The facts sit beside the document or stack above it, and the width that
    decides which is the COLUMN's — the one the reader sets with the grip — not
    the window's. A window breakpoint would put a 20rem sidebar beside a document
    dragged down to 10rem.

    This is asked at one wide window on purpose. Every other pixel test here
    changes the window, and at a narrow window a container query on the column
    and a media query on the window give the same answer — so none of them can
    see the failure this is for: the measure moved to `.panes` on 2026-08-24 and
    a `container-type` left behind on the now full-width `article.record` would
    be measuring the window under both names, silently, with every existing test
    still green.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "column.html",
        1400, _DRAGGED_NARROW, patience=2000,
    )

    assert got["width"] == 1400, "the window moved, so this is not asking about the column"
    # The drag has to have landed where it was asked to, or nothing below is
    # about the container query. One pointer pixel is one width pixel; a couple
    # of pixels of border and rounding is the whole tolerance.
    for name in ("narrow", "back"):
        assert abs(got[name]["landed"] - got[name]["asked"]) <= 4, (
            f"the {name} drag asked for {got[name]['asked']}px of column and landed at "
            f"{got[name]['landed']}px, so this is measuring the drag and not the query: {got}"
        )
    assert got["wide"]["beside"], f"the facts are not beside the document to start with: {got}"
    assert not got["narrow"]["beside"], (
        "the facts kept their column beside a document dragged narrower than the "
        f"56rem the query names, so the query is answering about the window: {got}"
    )
    assert got["narrow"]["mainTop"] > got["narrow"]["factsTop"], (
        f"and they did not stack above it either: {got['narrow']}"
    )
    assert got["back"]["beside"], f"dragging back did not give the column back: {got}"


# The handle between the two panes, driven the way a hand drives it. Everything
# here is geometry, selection and keys, so all of it is asked of Chrome and none
# of it of `tests/js/drive.js`, where `getClientRects()` answers `[]` for every
# element and the one question this feature turns on — is there a handle drawn —
# would answer "no" for ever.
_DIVIDING = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
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

    # Both handles are on screen, and that is the arrangement now rather than the
    # thing this line refused. `#splitter` moves the boundary BETWEEN the two
    # panes and `#grip` moves the outside edge of both — the pair every editor
    # with a split has, and what jcanton asked for on 2026-08-25: "I can only
    # resize the edit pane wrt the preview pane but not all together".
    #
    # What kept them apart was arithmetic, not confusion: the split's column is
    # one measure plus one body wide, so the grip used to move the measure twice
    # the drag. It divides by that factor now. `got["grip"]` reports the grip
    # HIDDEN, so this asserts it is not.
    assert not got["grip"], "the width grip left the page when the split opened"


@pytest.mark.parametrize("where", ["/detail/{task}", "/new?kind=issue", "/new?kind=note", "/new"])
def test_every_surface_that_splits_carries_the_same_handle(client: TestClient, where: str):
    """One control, one template — the argument `_VIEW_SEGMENTS` is one constant
    for, applied to the thing between the panes.

    The four parametrised URLs all draw that template's one emission, and a
    second copy of a separator would be a second place for its role, its name and
    its position in the markup to drift. Position is what this reads: the handle has
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
const article = document.querySelector('article.record');
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
const article = document.querySelector('article.record');
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
seg('view').click();               // out of the session altogether
const outside = drawn();
return {inTheSplit, elsewhere, outside, win: innerWidth};
"""


@pytest.mark.parametrize("width", [1400, 936, 934, 700])
def test_there_is_no_handle_where_there_is_nothing_to_divide(
    client: TestClient, tmp_path: Path, width: int
):
    """Only where it means something: the split view, and only while the facts are
    still a column on the right.

    The handle's off switch is a `@container (width < 56rem)` block against the
    same container `.panes` reads, so the two flip at the same pixel by
    construction. At these window widths that container crosses 56rem between
    934 and 936: the shell gives `main` `1.25rem` of padding a side, so the
    article has `window - 40px` to be wide in, and 936 - 40 is exactly 896.
    (The old `@media (width < 58.5rem)` reached the same boundary by viewport
    arithmetic for a full-page surface that no longer exists; the boundary
    survived the surface because both were derived from the same 56rem.) Below
    it there is no fixed column on the right to hold still, which is the whole
    of what the handle is for.

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
const article = document.querySelector('article.record');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
const split = article.querySelector('.bodysplit');
flipEditing();
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
    `overflow: hidden` ancestor throws it away with every assertion about it
    still passing. The full-page surface was one such ancestor and is gone; any
    ancestor a later rule clips is the same trap, and this handle is full
    height inside several candidates.

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
const article = document.querySelector('article.record');
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
const article = document.querySelector('article.record');
const handle = article.querySelector('#splitter');
const box = article.querySelector('.bodywrap');
const pane = article.querySelector('#body-preview');
flipEditing();
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

    The measure is seeded wide for the 3440 case, and that is a consequence of
    the article no longer being the window (2026-08-24): the split view is
    `2·measure − 21rem` wide, so at the default measure the panes never see
    2,160px between them however wide the screen — the fence only engages for
    somebody who has also dragged the measure out, which is exactly who owns an
    ultrawide.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text
    if width == 3440:
        page = _before_the_page_runs(
            page,
            "try { localStorage.setItem('openproj:measure', '1900px'); } catch (e) {}",
        )
    first = measured_in(
        chrome(), page,
        tmp_path / f"end-{width}.html", width, _SPLIT_TO_THE_END, patience=4800,
    )
    # It went somewhere, and the separator says it is at the end of its own range.
    assert first["box"] > first["pane"] and first["now"] == first["most"], first
    if width == 3440:
        # The fence, pinned: `End` under an engaged `SPLIT_RANGE` stores exactly
        # 8. Without this the seeded measure could silently fail to apply — at
        # the default measure the floor is the tighter bound at ANY window
        # width, every assertion here passes identically, and this leg degrades
        # to a second copy of the 1400 control that stays green with the fence
        # deleted. A broken seed now fails loudly instead.
        assert json.loads(first["stored"])["split"] == 8, (
            f"the drag stored {first['stored']}, so the outer fence never engaged "
            "and this leg is not testing it — did the measure seed apply?"
        )

    # The same measure on the second load: the panes' width is a function of it
    # now, and a round trip that changes the room changes what any ratio draws.
    seed = _SEED % first["stored"]
    if width == 3440:
        seed += " try { localStorage.setItem('openproj:measure', '1900px'); } catch (e) {}"
    again = measured_in(
        chrome(),
        _before_the_page_runs(client.get(f"/detail/{TASK}{PLAIN}").text, seed),
        tmp_path / f"back-{width}.html", width, _SPLIT_AS_FOUND, patience=4800,
    )
    assert again["view"] == "both", "the remembered view did not open"
    assert (again["box"], again["pane"]) == (first["box"], first["pane"]), (
        f"a split of {json.loads(first['stored'])['split']} chosen at {width}px came back "
        f"as {again['box']} to {again['pane']} instead of {first['box']} to {first['pane']} "
        "— the value the drag wrote is one the next load will not read"
    )


_CANCELLED_DRAG = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
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
const article = document.querySelector('article.record');
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

flipEditing();
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
// Nothing positions `#body-preview`, so the offset parent of every block in it
// is `article.record` (`position: relative`), and `offsetTop` is therefore a
// distance from the top of the article while `scrollTop`, which is what this
// number is compared against, is a distance inside the pane. The two differ by
// a constant — the pane's own top within the article, a header of bars and a
// heading tall. The page used to make the same mistake, so the test agreed
// with it and both were wrong together; this arithmetic is the pane's own
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
    `offsetTop`, and the two agreed with each other about a number that was in
    the wrong coordinate space. Nothing positions `#body-preview`, so the offset
    parent is the article, and a distance from the article's top is not a
    distance inside the pane. Both sides are rects against the scroller now, and
    `whereIsIt` is the assertion that needs neither: after the sync, line 82's
    block is at the top of the pane.
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

flipEditing();
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
flipEditing();
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

flipEditing();
// The sweep drives the box's own container instead of `--measure`: an inline
// width on `.bodywrap` is what actually rewraps the box whatever the view's
// own width rules say, and the mirror-agreement claim is about widths,
// wherever they come from. (Under the old full page, driving `--measure` here
// moved nothing at all — see the sweep guards in `test_seats.py`.)
const wrap = document.querySelector('.bodywrap');
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
  wrap.style.width = measure + 'px';
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

return {answers};
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
        where = f"at a pane width of {answer['measure']}px (box {answer['boxWidth']}px)"
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


_LEAVING = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
const nav = document.querySelector('body > nav');
const link = nav.querySelector('a');
// Whether a pointer aimed at the middle of the first nav link would actually
// reach it. The defect this file spent a branch on was a surface painting over
// the nav, so a class name is not the question — `elementFromPoint` is.
//
// Asked as `is it that link`, not as `is it an <a>`: an `<a>` under the point
// could as easily be the article's own back link.
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
for (const [name, id] of [['edit', 'view-edit'], ['both', 'view-both']]) {
  // The segment is the door: pressing it opens the session in that view.
  document.getElementById(id).click();
  const inside = shape();
  flipEditing();
  answers[name] = {inside, after: shape()};
}
return answers;
"""


def test_a_session_never_takes_the_page_away_and_cancel_lands_on_the_landing(
    client: TestClient, tmp_path: Path
):
    """The worst thing the full-page era shipped was on the main path: press a
    view, decide not to save, press Cancel — and `flipEditing` dropped
    `.editing` while `.full` and `body.fullpage` stayed, leaving the reader
    inside an opaque fixed article with the switcher gone and the nav inert.

    The structural fix (2026-08-24) is that there is no surface to be left
    inside: a session is the ordinary page, so the nav is reachable and never
    inert IN a session, not merely after one — which is what `inside` asserts,
    per view, with `elementFromPoint`. Ending the session lands on the landing,
    and `switcher: True` there is what keeps the way back drawn on both sides
    of the boundary.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "leave.html", 1400,
        _LEAVING, patience=1800,
    )

    for name, answer in got.items():
        assert answer["inside"]["classes"] == [f"view-{name}"], name
        assert not answer["inside"]["fullpage"] and not answer["inside"]["navInert"], (
            f"{name}: a session made the page a surface again: {answer['inside']}"
        )
        assert answer["inside"]["over"], (
            f"{name}: a pointer aimed at the nav does not reach it inside a session"
        )
        assert answer["after"] == {
            "classes": ["view-view"], "fullpage": False, "navInert": False, "over": True,
            "switcher": True, "editing": False,
        }, (
            f"Cancel from the {name} view did not land on the landing: {answer['after']}"
        )


# The same question as `_LEAVING`, asked at the door Cancel is not: a bare
# `showEditing(false)`, the call every door out of a session ends in. The
# room's own save reloads nowadays — the test above pins that — so what this
# drives is the shared ending itself, not a door invented for a test.
_SAVED_IN_A_ROOM = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
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
  // The corner used to be MOVED into the session's own bar and handed back on
  // the way out. It never leaves the nav now, and this asks so on both sides
  // of the boundary: a `showView` that grew the move again fails here first.
  cornerInNav: corner.parentElement === nav,
});

const answers = {};
for (const [name, id] of [['edit', 'view-edit'], ['both', 'view-both']]) {
  // The segment is the door: pressing it opens the session in that view.
  document.getElementById(id).click();
  const inside = shape();
  // Ending the session and nothing else — the call every door makes. It lands
  // on the landing, so the next pass starts from the page.
  showEditing(false);
  answers[name] = {inside, after: shape()};
}
return answers;
"""


# A save made from the split view, driven through the page's own `save()`. The
# body is changed first because `save()` answers "nothing changed" and returns
# without writing anything otherwise — a green run over a save that never
# happened is exactly the vacuous pass this file keeps finding.
_SAVING_FROM_A_VIEW = """
(async () => {
  chooseView('both');
  const box = document.querySelector('[name=body]');
  box.value = 'A paragraph typed in the split view.\\n';
  box.dispatchEvent(new Event('input', {bubbles: true}));
  await save();
  return {view: VIEW, reloads: __reloads()};
})()
"""

# What the page does with the word the save before it left behind. Through `VIEW`
# and `classList.contains`, which is what the page itself writes and reads: the
# shim has no `click()` on an element and its `classList` is not iterable, and a
# test that needs either is a test about the harness.
_WHERE_IT_LANDS = """
(() => {
  const article = document.querySelector('article.record');
  return {view: VIEW, editing: article.classList.contains('editing'),
          split: article.classList.contains('view-both')};
})()
"""


def test_saving_keeps_the_view_it_was_saved_from(client: TestClient):
    """jcanton, 2026-08-25: "currently clicking save in the editor exits edit
    mode and sends you back to preview, let's change that and stay in whatever
    mode the user is in (edit or side-by-side)".

    The reload itself is not the thing to remove — the read view under the box is
    HTML the server rendered at the commit the page loaded at, and a save that
    does not reload leaves the document and the facts as they were. What the
    reload threw away was the mode, and this drives both halves of carrying it
    across: the save writes the word, and the page that comes up reads it.

    Driven rather than read off the source, because the two halves are in two
    script blocks that never run in the same order they are written in, and a
    grep for `keepView` would pass on a page where nothing calls it.

    `chooseView` rather than a click on the segment: the node shim has no
    `click()` on an element, and the segment is not what this is about —
    `test_opening_a_session_moves_nothing_above_the_document` drives the buttons
    in a real browser. What this needs is a live session in a named view, which
    is what the function the button calls does.
    """
    from test_injection import run_js

    page = client.get(f"/detail/{TASK}{PLAIN}").text

    saving = run_js(
        page, _SAVING_FROM_A_VIEW, page=True,
        replies=[{"status": 200, "json": {"commit": "0" * 40}}],
    )
    assert not saving["errors"], saving["errors"]
    assert saving["value"]["reloads"] == 1, (
        f"the save did not reload, so this test drove nothing: {saving['value']}"
    )
    assert saving["tabbed"].get("openproj:resumed") == "both", (
        "a save from the split view left nothing behind saying so, so the page "
        f"it reloads into cannot come back to it: {saving['tabbed']}"
    )

    # And the page that comes up. Not the same run — a reload is a new document
    # with a new script, which is the whole reason this goes through the tab's
    # own store rather than through a variable.
    landed = run_js(
        page, _WHERE_IT_LANDS, page=True, session={"openproj:resumed": "both"}
    )
    assert not landed["errors"], landed["errors"]
    assert landed["value"] == {"view": "both", "editing": True, "split": True}, (
        f"the reloaded page did not come back into the split: {landed['value']}"
    )
    assert "openproj:resumed" not in landed["tabbed"], (
        "the word survived the page that read it, so the next record this tab "
        "opens will open as an editor"
    )

    # The control, and it is what every load that did not just save gets: no
    # word, no session, the landing. Without this the test above passes on a
    # page that opens the split for everybody.
    ordinary = run_js(page, _WHERE_IT_LANDS, page=True)
    assert ordinary["value"] == {"view": "view", "editing": False, "split": False}, (
        f"a page nobody saved from opened in a session: {ordinary['value']}"
    )


def test_a_link_beats_the_view_a_save_left_behind_and_still_spends_it(
    client: TestClient,
):
    """The one-shot is read before the branch that might not want it.

    `?view` is somebody handing you a way of looking at this document and it wins
    — that rule is older than this key. What the rule cannot be allowed to do is
    leave the word in the tab: a save whose landing was overruled by a link would
    otherwise open an editor over the NEXT record this tab visits, which is the
    sticky-at-load behaviour the load branch is written to avoid.
    """
    from test_injection import run_js

    page = client.get(f"/detail/{TASK}{PLAIN}").text
    got = run_js(
        page, _WHERE_IT_LANDS, page=True,
        session={"openproj:resumed": "both"}, here=f"/detail/{TASK}?view",
    )
    assert not got["errors"], got["errors"]
    assert got["value"] == {"view": "view", "editing": False, "split": False}, (
        f"the link did not win the argument with the saved view: {got['value']}"
    )
    assert "openproj:resumed" not in got["tabbed"], (
        "the saved view lost the argument and stayed in the tab anyway"
    )


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

    Since 2026-08-25 the reload is no longer how the session ENDS: `keepView`
    carries the mode across it, so a save from the split view comes back into the
    split (`test_saving_keeps_the_view_it_was_saved_from`). What this test says is
    narrower than its name and always was — the branch reloads, and it does not
    grow a fourth copy of leaving the surface — and both are still true.
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
    the session with a bare `showEditing(false)` and did not reload, leaving the
    reader inside the full-page surface of the day. (It reloads now, for a
    different defect — see the test above — so the door driven here is the one
    Cancel and the view toggle use.) The surface itself is gone since
    2026-08-24, which retires the trap structurally; what this still pins is
    that the one `openproj:session` listener answers a door no click opened —
    end a session any way at all, and the page lands on the landing with its
    chrome where it always was.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "roomsave.html",
        1400, _SAVED_IN_A_ROOM, patience=1800,
    )

    for name, answer in got.items():
        assert answer["inside"]["classes"] == [f"view-{name}"], name
        assert not answer["inside"]["fullpage"] and not answer["inside"]["navInert"], (
            f"{name}: a session made the page a surface again: {answer['inside']}"
        )
        assert answer["inside"]["over"] and answer["inside"]["cornerInNav"], (
            f"{name}: the nav is not whole inside a session: {answer['inside']}"
        )
        assert answer["after"] == {
            "classes": ["view-view"], "fullpage": False, "navInert": False, "over": True,
            "switcher": True, "editing": False, "cornerInNav": True,
        }, (
            f"a room's save from the {name} view did not land on the landing: "
            f"{answer['after']}"
        )


# The two page-chrome controls, watched through a session.
#
# `#who` is filled by the shell's own `/api/me` fetch, which cannot answer over
# `file://` — so it is filled here with exactly what that script builds for a
# stranger. What is being asked is that the control never LEAVES and stays
# reachable by a pointer, not whether a fetch succeeded.
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

const article = document.querySelector('article.record');
// What a pointer aimed at the middle of a control would actually hit. A class
// name cannot answer this: the defect the full-page era shipped was an opaque
// fixed surface painted over these two, and `elementFromPoint` is the question
// that would have caught it.
const reaches = el => {
  const box = el.getBoundingClientRect();
  return document.elementFromPoint(
    box.left + box.width / 2, box.top + box.height / 2) === el;
};
const shape = () => ({
  parent: corner.parentElement.tagName,
  inNav: nav.contains(corner),
  onArticle: article.contains(corner),
  navInert: !!nav.inert,
  themeReachable: reaches(theme),
  themeNamed: theme.getAttribute('aria-label'),
  signInReachable: reaches(link),
});

const before = shape();
flipEditing();
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 300));
const inside = shape();
// The controls never moved, so this is the same node with the same listeners:
// pressing the toggle still changes the theme and still relabels itself.
const was = document.documentElement.dataset.theme || '';
theme.click();
const themed = {
  was, now: document.documentElement.dataset.theme,
  named: theme.getAttribute('aria-label'),
};
flipEditing();
await new Promise(go => setTimeout(go, 200));
return {before, inside, themed, after: shape()};
"""


def test_the_theme_toggle_and_the_way_in_never_leave_the_corner(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-20: "the light/dark mode toggle and sign in button seem
    to have disappeared from the edit view, bring those back please".

    The cause was the full-page surface: an opaque fixed article painted over
    the nav, the nav was (rightly, then) made `inert`, and the two controls
    were physically MOVED onto the surface and handed back on the way out —
    machinery this file spent three tests keeping honest. Since 2026-08-24 a
    session is the ordinary page, so the machinery is deleted rather than
    exercised: nothing covers the nav, nothing inerts it, and the controls stay
    where every other page in the app keeps them. jcanton's own acceptance
    sentence — page elements do not move or appear or disappear when switching
    views — is asserted here of exactly the two elements that used to.

    Still asked with `elementFromPoint`, because "reachable by a pointer at the
    place it is drawn" is the claim the original defect falsified, and a class
    check cannot see paint.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "corner.html",
        1400, _THE_CORNER, patience=2400,
    )

    assert got["before"]["parent"] == "NAV" and got["before"]["inNav"]
    assert got["before"]["themeReachable"] and got["before"]["signInReachable"]
    assert got["before"]["themeNamed"] in ("Dark mode", "Light mode")

    inside = got["inside"]
    assert inside == got["before"], (
        f"opening the split view changed the nav's corner: {inside} "
        f"against {got['before']}"
    )
    assert not inside["onArticle"], "the corner was moved onto the record"
    assert not inside["navInert"], "the nav went inert for a session on the same page"
    assert inside["themeReachable"] and inside["signInReachable"], (
        "a session painted something over the corner"
    )

    assert got["themed"]["now"] != got["themed"]["was"], (
        "the theme toggle stopped working inside a session"
    )
    assert got["themed"]["named"] != inside["themeNamed"], (
        "it switched the theme and went on calling itself what it was"
    )

    # And unchanged after the session, which under the old machinery was the
    # move-back branch and is now simply nothing happening.
    assert got["after"]["parent"] == "NAV" and got["after"]["inNav"]
    assert not got["after"]["navInert"]
    assert got["after"]["themeReachable"] and got["after"]["signInReachable"]


# Every box above the document, watched through all three views. `facts` is
# top and left only, deliberately: its CONTENT changes with the mode — read
# values swap for controls, which is the point of a session — so its height is
# the one measurement here that is supposed to move.
#
# `width` is measured since 2026-08-24, and `back` is here for the same reason:
# the header is the six boxes above the line jcanton drew under the meta line,
# and "full width, so they stay left aligned like the nav" is a claim about
# every one of them and about their right edges as well as their left.
_THE_HEADER_STAYS = _STUB_PREVIEW + """
const box = sel => {
  const b = document.querySelector(sel).getBoundingClientRect();
  return {top: Math.round(b.top), height: Math.round(b.height),
          left: Math.round(b.left), width: Math.round(b.width)};
};
// The six above the line, in the order they are drawn. The nav is beside them
// as the thing they are level with, and not as one of them.
const HEADER = ['.back', '.editbar', '#commitbar', '.eyebrow',
                'article.record h1', 'article.record .meta'];
// And the CONTROLS inside one of those six, because a box that holds while its
// contents slide is what the six alone cannot see. `.editbar` is the page's
// width in every view and was so before this list existed; the three segments
// jcanton named by name were still at x=91 while reading and x=21 in a session,
// because Delete stood in front of them and left the bar the moment a session
// began. `#views` is the segmented control's own box, which starts where the
// nav starts; `#view-edit` starts one pixel in, on `#views`'s border.
const SWITCHER = ['#views', '#view-edit', '#view-both', '#preview'];
// Whichever control the row actually begins with, asked of the DOM rather than
// named. It was `#views` and is the Slide button since the play icon moved to
// the left of the trio; the property the test is about — the controls begin
// where the nav begins — is the same either way, and a selector written down
// here would have to be edited every time one of them moves.
const header = () => ({
  nav: box('body > nav'),
  ...Object.fromEntries(HEADER.map(sel => [sel, box(sel)])),
  ...Object.fromEntries(SWITCHER.map(sel => [sel, box(sel)])),
  'editbar-first': (el => {
    const first = el && el.firstElementChild;
    const r = first.getBoundingClientRect();
    return {top: Math.round(r.top), height: Math.round(r.height),
            left: Math.round(r.left), width: Math.round(r.width)};
  })(document.querySelector('.editbar')),
  facts: (({top, left}) => ({top, left}))(box('.panes > .facts')),
});
const landing = header();
document.getElementById('view-edit').click();
await new Promise(go => setTimeout(go, 150));
const writing = header();
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 150));
const split = header();
document.getElementById('preview').click();
await new Promise(go => setTimeout(go, 150));
return {landing, writing, split, back: header(), header: HEADER, switcher: SWITCHER};
"""


def test_opening_a_session_moves_nothing_above_the_document(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-24: "ideally page elements should not move or appear or
    disappear when switching views in this page" — measured at the two places
    the sentence was still false after the full-page surface went.

    Pressing Write used to move the heading from y=146 to y=190 and everything
    under it — the meta line, the facts column, the document — by two mechanisms
    at once: the commit bar unhid (38px plus its gap), and the `<h1>` grew 36px
    to 44px as the read span swapped for a title input carrying its own padding,
    border and margin. So two rules now hold what this asserts: the bar's box is
    reserved (`article.record .editbar + .commitbar[hidden]` keeps `display:
    flex` and hides with `visibility`), and the title input in the heading takes
    the read span's metrics, wearing its border in negative margins.

    The split used to be allowed one change of its own — it widened by one body
    and recentred, so `left` was free to move there — and that exemption is what
    jcanton came back about on 2026-08-24: "I'd make the ←Table,
    edit/side-by-side/preview buttons and 'nothing saved yet' banner full width,
    so they stay left aligned like the nav and don't move anymore at all (they
    are still jumping between side-by-side and the other views)". So there is no
    exemption left above the line: the six boxes hold every number in all three
    views, and the measure that does change between them lives on `.panes`,
    below it.

    The facts column is the one box here that may still move sideways in the
    split, because it is below the line and rides the measure — only its `top`
    is asserted there.

    And the switcher's own three segments, not only the row they sit on. He
    named those buttons: "the ←Table, edit/side-by-side/preview buttons and
    'nothing saved yet' banner ... stay left aligned like the nav and don't move
    anymore at all". Measured in Chrome at 1400x900 with the row already at the
    page's width and Delete still in front of them: `#view-edit` at x=91 while
    reading and x=21 in both session views, so his sentence was still false in
    the one place a comparison of the six boxes cannot look — the row holds
    while its contents slide. Delete is after the switcher now, so it leaves
    from the end and moves nothing.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "still.html",
        1400, _THE_HEADER_STAYS, patience=3000,
    )
    landing = got["landing"]

    assert got["writing"] == landing, (
        f"opening a session moved the header: {got['writing']} against {landing}"
    )
    assert got["back"] == landing, (
        f"leaving the session did not put the page back: {got['back']} against {landing}"
    )
    for name in got["header"] + got["switcher"]:
        assert got["split"][name] == landing[name], (
            f"the split view moved {name}: {got['split'][name]} against {landing[name]}"
        )
    assert got["split"]["facts"]["top"] == landing["facts"]["top"], (
        "the split view moved the facts column up or down the page"
    )

    # And where the header sits, which is the half of his sentence that a
    # comparison between views cannot see: three views that agree on a box in
    # the wrong place agree just as well. Level with the nav and as wide as it,
    # in every view, which is what "full width, like the nav" is.
    for view in ("landing", "writing", "split"):
        nav = got[view]["nav"]
        for name in got["header"]:
            spot = got[view][name]
            assert (spot["left"], spot["width"]) == (nav["left"], nav["width"]), (
                f"in the {view} view {name} is not the page's width beside the "
                f"nav: {spot} against {nav}"
            )
        # The controls are a handful of buttons and not a full-width row, so
        # only the leftmost one's edge is the nav's. That control is the SLIDE
        # button since 2026-08-25 — jcanton: "move the slide play button/icon to
        # the left of the trio with edit/side-by-side/preview" — and it was the
        # switcher before it. What the sentence behind this test asks for is that
        # the row of controls begins where the nav begins, so the assertion
        # follows whichever control begins it rather than naming one.
        #
        # Read off the bar rather than listed here, so moving a control within
        # the row is a change to the markup and not to a test: a list written
        # down is a list that goes stale, and going stale here means asserting
        # the alignment of something that is no longer first.
        edge = got[view]["editbar-first"]
        assert edge["left"] == nav["left"], (
            f"in the {view} view the controls do not start where the nav "
            f"starts: {edge} against {nav}"
        )


# Where the column STARTS, which every test above this one is blind to: they
# compare a box against itself in three views, and a box that is in the same
# wrong place in all three passes every one of them. The header moved to the
# page's left padding on 2026-08-24 and the document below it stayed centred,
# which is the shape jcanton looked at on 2026-08-25 — "you were right that left
# aligning the edit header and centering the body and fields looks awkward. let's
# left align everything in the editor".
_THE_COLUMN_STARTS_LEFT = _STUB_PREVIEW + """
const box = sel => {
  const b = document.querySelector(sel).getBoundingClientRect();
  return {left: Math.round(b.left), width: Math.round(b.width)};
};
// The document's own column and the box inside it: `.panes` is the measure and
// `.panes > .main` is the document that rides it.
const COLUMN = ['.panes', '.panes > .main'];
const seen = () => ({
  nav: box('body > nav'),
  h1: box('article.record h1'),
  ...Object.fromEntries(COLUMN.map(sel => [sel, box(sel)])),
});
// Measured on the landing alone, because `.record.editing #promote` takes the
// bar off the page for the whole of a session — a rect of zeroes in the other
// two views would be a measurement of nothing dressed as a failure.
const landing = {...seen(), promote: box('#promote')};
document.getElementById('view-edit').click();
await new Promise(go => setTimeout(go, 150));
const writing = seen();
document.getElementById('view-both').click();
await new Promise(go => setTimeout(go, 150));
const split = seen();
return {landing, writing, split, column: COLUMN};
"""


def test_the_document_starts_where_its_own_title_starts(
    client: TestClient, tmp_path: Path
):
    """One left edge for the whole page, in all three views.

    The measure below the line is unchanged — the column is still `--measure`
    wide and still grows by one body in the split — and only where it begins has
    moved. Centred, it began 168px in from the title above it at 1400px, and it
    began somewhere different in the split, because a centred box whose width
    changes has a left edge that changes with it: opening side-by-side slid the
    document's first character half a body width left while the header it sits
    under held still. Both are the same defect and this asserts them as one
    number.

    Asked on a NOTE and through the write path for the reason
    `test_the_promotion_bar_keeps_the_column_it_sits_under` is: `#promote` is
    drawn on a promotable record and a task is not one, and it is the third box
    that has to share this edge — on the landing, which is the only view it is
    on the page in.

    1400px, because it is the window where the column and the page are different
    widths — at 700 the measure is capped by `max-width: 100%` and every box
    here starts at the same place whatever the rule says, which is a green test
    that has looked at nothing.
    """
    made = client.post("/api/record", json={
        "base_commit": head(client),
        "body": "The seam is not where we thought it was.",
        "fields": {"kind": "note", "title": "A note whose column starts left"},
    })
    assert made.status_code == 201, made.text
    page = client.get(f"/detail/{made.json()['id']}{PLAIN}").text
    assert '<div id="promote">' in page, "the note's page has no promotion bar to measure"

    got = measured_in(
        chrome(), page, tmp_path / "column-left.html", 1400,
        _THE_COLUMN_STARTS_LEFT, patience=3000,
    )
    assert got["landing"][".panes"]["width"] < got["landing"]["nav"]["width"], (
        "the column is already the page's width at 1400px, so this test cannot "
        f"tell left from centred: {got['landing']}"
    )
    for view in ("landing", "writing", "split"):
        nav = got[view]["nav"]
        assert got[view]["h1"]["left"] == nav["left"], (
            f"in the {view} view the title is not at the page's left edge: "
            f"{got[view]['h1']} against {nav}"
        )
        for name in got["column"]:
            assert got[view][name]["left"] == nav["left"], (
                f"in the {view} view {name} does not start where the title and "
                f"the nav start: {got[view][name]} against {nav}"
            )
    assert got["landing"]["promote"]["left"] == got["landing"]["nav"]["left"], (
        "the promotion bar under the document does not start where the document "
        f"does: {got['landing']['promote']} against {got['landing']['nav']}"
    )


# The other side of the line jcanton drew, and the box that is not `.panes`.
# `#promote` is the second and last direct child of the article below it, and
# the only element on the page whose width was the article's by inheritance
# rather than by a rule of its own.
_THE_BAR_UNDER_THE_COLUMN = _STUB_PREVIEW + """
const box = sel => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const b = el.getBoundingClientRect();
  return {left: Math.round(b.left), right: Math.round(b.right),
          width: Math.round(b.width)};
};
return {nav: box('body > nav'), panes: box('.panes'), promote: box('#promote'),
        hint: box('#promote .hint'),
        overflow: document.documentElement.scrollWidth, window: innerWidth};
"""


def test_the_promotion_bar_keeps_the_column_it_sits_under(
    client: TestClient, tmp_path: Path
):
    """Below the line is the column's width, and the promotion bar is below the
    line. jcanton, 2026-08-24: everything above the line he drew under the meta
    row is the page's width, "and only the body and fields below it keep the
    current horizontal sizing".

    `#promote` is the failure that move can have: it is a direct child of
    `article.record` like the six header boxes, it sits BELOW `.panes`, and it
    had no width of its own — it simply took the article's, which was the
    measure until the measure moved down to the panes. Measured in Chrome at
    1400x900 on a note's page before the fix: the bar 1360px wide against
    `.panes`'s 1024, so its `border-top` ran 336px past the right edge of the
    facts column and stopped in empty space, and the 12px sentence under it set
    at 1360px instead of at the reader's measure.

    Asked on a NOTE, and asked through the write path, because the corpus every
    other pixel test here runs on is a task and a task is not promotable
    (`PROMOTABLE`) — so `#promote` is on none of the pages the rest of this file
    looks at, which is exactly why nothing caught this.

    Two windows. 1400 is the only one where "the column" and "the page" are
    different answers, so the equality means something; 700 is narrower than the
    measure, where `max-width: 100%` decides the width instead and the question
    is whether the bar overflows the page.
    """
    made = client.post("/api/record", json={
        "base_commit": head(client),
        "body": "The seam is not where we thought it was.",
        "fields": {"kind": "note", "title": "A note somebody may promote"},
    })
    assert made.status_code == 201, made.text
    page = client.get(f"/detail/{made.json()['id']}{PLAIN}").text
    # The guard against this going quietly vacuous: no bar, no measurement, and
    # every assertion below would pass on a `null` this file would rather see.
    assert '<div id="promote">' in page, "the note's page has no promotion bar to measure"

    wide = measured_in(
        chrome(), page, tmp_path / "promote-wide.html", 1400, _THE_BAR_UNDER_THE_COLUMN
    )
    narrow = measured_in(
        chrome(), page, tmp_path / "promote-narrow.html", 700, _THE_BAR_UNDER_THE_COLUMN
    )

    assert wide["panes"]["width"] < wide["nav"]["width"], (
        "the column is already the page's width at 1400px, so this test cannot "
        f"tell the two apart: {wide}"
    )
    for window, got in (("1400px", wide), ("700px", narrow)):
        assert (got["promote"]["left"], got["promote"]["width"]) == (
            got["panes"]["left"], got["panes"]["width"]
        ), (
            f"at {window} the promotion bar is not the column it sits under: "
            f"{got['promote']} against {got['panes']}"
        )
        assert got["hint"]["width"] == got["panes"]["width"], (
            f"at {window} the sentence inside it sets at another width: {got}"
        )
        assert got["overflow"] == got["window"], (
            f"at {window} the page scrolls sideways: {got}"
        )


_A_FAILED_PREVIEW = """
window.asked = 0;
window.fetch = async () => { window.asked++; return {ok: false, status: 500,
  json: async () => ({detail: 'the body could not be rendered'})}; };
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const said = () => document.getElementById('state').textContent;
const settle = ms => new Promise(go => setTimeout(go, ms));

flipEditing();
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
flipEditing();

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
flipEditing();
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
const type = what => { area.value = what;
  area.dispatchEvent(new Event('input', {bubbles: true})); };
flipEditing();
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

// A draft that is committed or reset stops existing, and the receipt stops
// claiming it.
document.getElementById('reset').click();
const after = {held: held(), receipt: receipt()};

// And the burst that follows starts its own leading edge. Forgetting the draft
// forgets both clocks: the one that says when a draft last landed, which the
// receipt counts from, and the one the throttle measures the interval against.
// Leaving the second set would hold the first character typed after a reset
// back by up to a whole interval, against a write that has nothing to do with it.
type('written after the reset');
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
    assert got["after"]["held"] is None, "resetting left the draft in storage"
    assert got["after"]["receipt"] == "", (
        f"the receipt still claims a draft that no longer exists: "
        f"{got['after']['receipt']!r}"
    )
    assert got["restarted"] == "written after the reset", (
        "the first keystroke after a reset was throttled against the write "
        "before it, so a tab closed a second later holds nothing again — "
        f"{got['restarted']!r}"
    )


_REFUSED = _STUB_RENDER + r"""
const bar = document.getElementById('statusbar');
const area = document.querySelector('textarea[name=body]');
flipEditing();
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
    # Which editor somebody is in is NOT among them, and since 2026-08-24 it is
    # not written anywhere at all — the toggle went and the stickiness went with
    # it, so the address is the whole mechanism and applies to the page it is on.
    # This assertion used to be "not unconditional, but written when `chosen`";
    # both halves are now the same half.
    #
    # `EDITOR_KEPT` being the whole of what is written is also what clears a value
    # stored before that change: the map is rebuilt rather than merged into.
    assert not re.search(r"const EDITOR_KEPT = \[[^\]]*'editor'[^\]]*\];", page), (
        "the resolved editor is stored, so a parameter typed once decides every "
        "later page from a store nothing on the page can show or unset"
    )
    assert "kept.editor" not in page, (
        "the editor is written into the preference map on some condition, which is "
        "the stickiness that was removed with the control that revealed it"
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
const article = document.querySelector('article.record');
const mode = () => VIEW;
const atLoad = {view: mode(), full: article.classList.contains('full'),
                editing: article.classList.contains('editing')};
flipEditing();
const afterEdit = {view: mode(), full: article.classList.contains('full')};
flipEditing();
const afterCancel = {view: mode(), stored: JSON.parse(localStorage.getItem('openproj:editor:1'))};
flipEditing();
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

    assert got["atLoad"] == {"view": "view", "full": False, "editing": False}, (
        f"a remembered mode opened a record somebody came to read as an "
        f"editor: {got['atLoad']}"
    )
    # `full: False` in a session too, since 2026-08-24: the split opens on the
    # page it was asked from, and the class would mean the surface came back.
    assert got["afterEdit"] == {"view": "both", "full": False}, (
        f"starting a session did not restore the remembered view: {got['afterEdit']}"
    )
    assert got["afterCancel"]["view"] == "view"
    assert got["afterCancel"]["stored"]["mode"] == "both", (
        "Cancel was read as a preference for no surface, so using the split once "
        "and cancelling takes it away"
    )
    assert got["chosen"] == "edit", "pressing a segment did not remember it"


_ONE_FACE = """
const area = document.querySelector('textarea[name=body]');
const gutter = document.querySelector('.gutter');
flipEditing();
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
    declaration is in `_EDITING_STYLE` now, which is concatenated after the one
    stylesheet that carries it, and on the detail page that ORDER is the
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
  if (node && node.tagName === 'SCRIPT') {
    // A `src` names the twenty-four characters that end it. An inline script
    // — one whose body was set with `.textContent`, the way `attachDrawing`'s
    // fetch-and-inject loader builds one — has no `src` at all, so the
    // original version of this hook never saw it: it passed the LETTER of
    // "no script is injected at runtime" while missing the one this page now
    // deliberately does inject. `dataset.injectedBundle` is that loader's own
    // marker on the one script it is allowed to inject, read back here so an
    // unmarked inline script — the one this hook could not previously have
    // told apart from it — still shows up as itself.
    window.__injected.push(
      node.src ? node.src.slice(-24) : `inline:${node.dataset.injectedBundle || '(unmarked)'}`
    );
  }
  return append.call(this, node);
};
"""

_KEYMAP_FETCHES = r"""
  flipEditing();
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
  flipEditing();
  await new Promise(r => setTimeout(r, 300));
  // ONE line, which is the state Ace re-detects the newline sequence in:
  // `Document.insert` is `this.getLength() <= 1 && this.$detectNewLine(text)`.
  // A new record starts here, and so does any document somebody has just
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
    on a document of one line — a new record, or one somebody has just cleared —
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
  flipEditing();
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
    // Opens a file picker and writes nothing. Skipped by CLASS: this read
    // `button.title === 'Image'`, and the day that title grew a hint about
    // sizing figures the match stopped holding — so the run opened a file
    // dialog and then reported the button as one that does nothing.
    if (button.classList.contains('upload')) continue;
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
    # here beside it: Escape leaves the session and Cmd+S saves, and both
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
  flipEditing();
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


_EDITOR_FORGOTTEN = r"""
const key = 'openproj:editor:1';
const before = remembered.map(key).editor ?? null;
// Anything at all that this browser remembers about the editor. The indent width
// is the cheapest: `rememberEditor` rebuilds the whole stored map either way.
rememberEditor({indent: 4});
return {before, after: remembered.map(key).editor ?? null};
"""


def test_the_editor_is_chosen_by_the_address_and_by_nothing_else(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-24: "should we disable the plain editor then? remove the
    toggle, have ace as default for everybody. don't delete the plain editor but
    make it only accessible by /?editor=plain".

    So the parameter is the whole mechanism now. It was sticky — typing it wrote a
    preference, and `stickyEditor` put that preference back into the address on
    every later page, because the server cannot read `localStorage` and the
    address is the only part of this it can see. That machinery is gone with the
    control that made it discoverable: a preference nothing on the page can show
    you or unset is the trap this file's own comments named, and one that also
    costs a redirect on every record is the expensive kind.

    What survives is `chosen`, and it survives for the same reason it was built:
    a request the page cannot honour has to say so, and a default that was never
    going to be honoured must not. It just means one thing now instead of two —
    the ADDRESS asked — where it used to mean the address or the store.
    """
    # 1. A choice made before this change is not a choice any more. Somebody who
    #    typed `?editor=plain` last week has it in `localStorage`; a bare address
    #    is Ace for them, like it is for everybody.
    stale = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}").text, _SEED % '{"editor": "plain"}'
        ),
        tmp_path / "editor-stale.html", 1400, _STICKY_EDITOR, patience=6800,
    )
    assert stale["editor"] == "ace", (
        "a preference stored before the toggle was removed is still deciding which "
        "editor somebody gets, from a store nothing on the page can show them"
    )
    assert stale["surface"] == "ace", "the library is in the page and did not mount"
    assert stale["said"] == "", f"getting the default was announced: {stale['said']!r}"

    # 2. The escape hatch, doing the whole of its job: the address asks, the
    #    server sends no library, and the box is what mounts. Silently — this is
    #    what was asked for.
    asked = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "editor-plain.html", 1400, _STICKY_EDITOR, query="?editor=plain",
        patience=4800,
    )
    assert asked["editor"] == "plain", "the address asked for the box and was not read"
    assert asked["surface"] == "textarea"
    assert asked["said"] == "", (
        f"the box is what this address asked for and getting it is not news: "
        f"{asked['said']!r}"
    )

    # 3. And nothing is written down. This is the assertion the whole change is:
    #    the parameter applies to the page it is on and to no other.
    assert asked["kept"] is None, (
        "typing the parameter wrote it into the preference store — so it is sticky "
        "again, and there is no control left to unstick it"
    )

    # 3b. The stale value is IGNORED, not migrated — case 1 is that assertion —
    #     and it goes the first time anything else is remembered, because the map
    #     is rebuilt from `EDITOR_KEPT` rather than merged into. Driven rather
    #     than reasoned about: a store that only shrinks in theory is one people
    #     carry a dead key in for years.
    cleared = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}").text, _SEED % '{"editor": "plain"}'
        ),
        tmp_path / "editor-cleared.html", 1400, _EDITOR_FORGOTTEN, patience=6800,
    )
    assert cleared["before"] == "plain", "the seed did not take, so this asks nothing"
    assert cleared["after"] is None, (
        "a choice stored before the toggle was removed survived the next thing this "
        "browser remembered, so it stays in the store for ever"
    )

    # 4. The address asked for Ace and the answer was no — a reader the server
    #    would refuse a save from, or a copy of the page saved to a file. That is
    #    still news, and it is the branch `chosen` exists for.
    refused = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "editor-refused.html", 1400, _STICKY_EDITOR, query="?editor=ace",
        patience=4800,
    )
    assert refused["surface"] == "textarea"
    assert "does not carry the second editor" in refused["said"], (
        f"the page was asked for an editor it does not have and said nothing: "
        f"{refused['said']!r}"
    )
    assert refused["kept"] is None, "a refusal was written down as a preference"

    # 5. The other half of `chosen`, and the reason it is not simply "did Ace
    #    mount": a reader who said nothing gets no library either, and telling
    #    every signed-out reader on every record about a thing they never asked
    #    for is the noise this guard exists to prevent.
    silent = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text,
        tmp_path / "editor-silent.html", 1400, _STICKY_EDITOR, patience=4800,
    )
    assert silent["surface"] == "textarea"
    assert silent["said"] == "", (
        f"a page nobody asked anything of announced the absence of a library: "
        f"{silent['said']!r}"
    )

    # 6. And the machinery is gone rather than merely unreached. A redirect that
    #    still ships is one a later change re-enables by accident.
    page = client.get(f"/detail/{TASK}").text
    assert "stickyEditor" not in page, (
        "the page still carries the redirect that made the choice sticky"
    )
    assert 'id="editorswitch"' not in page, "the switch is still rendered"
    assert "editorName" not in page, (
        "`editorName` is still on the surfaces, and its own comment says it exists "
        "for exactly one consumer — the switch, which is gone"
    )


# The writing box measured against the row grid, at a window narrow enough that
# the facts stack over the document. The 50px box this section was first written
# for came out of the full-page grid (a `height: 100%` box in an `auto` track);
# the surface is gone, and what is measured now is that the ordinary page keeps
# the box a document tall and keeps everything reachable by scrolling.
#
# `_STUB_PREVIEW`, because over `file://` there is no server: without it the
# pane holds one line of refusal, and the create form's preview — which sizes
# to its content, exactly as the landing document does — would be measured
# holding nothing.
_NARROW_WRITING = _STUB_PREVIEW + """
const article = document.querySelector('article.record');
const area = document.querySelector('textarea[name=body]');
const facts = document.querySelector('.facts');
const pane = document.getElementById('body-preview');
const rows = element => {
  const box = element.getBoundingClientRect();
  return Math.round(box.height / parseFloat(getComputedStyle(area).lineHeight));
};
const state = () => ({
  rows: rows(area),
  factsWhole: Math.round(facts.getBoundingClientRect().height) >= facts.scrollHeight - 1,
  factsReachable: facts.getBoundingClientRect().bottom + scrollY
                  <= document.documentElement.scrollHeight + 1,
});

// The create form is always editing; the record page opens a session here.
if (typeof flipEditing === 'function') flipEditing();
const out = {};
// Pressing the lit segment would leave the session, so a segment is pressed
// only when something else is lit.
const press = id => {
  const seg = document.getElementById(id);
  if (seg.getAttribute('aria-pressed') !== 'true') seg.click();
};
press('view-edit');
out.write = state();
press('view-both');
await new Promise(go => setTimeout(go, 200));
out.split = state();
out.position = getComputedStyle(article).position;
out.sideways = document.documentElement.scrollWidth > innerWidth;
out.paneRows = Math.round(
  pane.getBoundingClientRect().height / parseFloat(getComputedStyle(area).lineHeight));
press('preview');
await new Promise(go => setTimeout(go, 200));
const doc = document.querySelector('article.record .doc.read');
out.read = {
  paneRows: Math.round(
    pane.getBoundingClientRect().height / parseFloat(getComputedStyle(area).lineHeight)),
  landed: doc ? doc.getClientRects().length > 0 : false,
};
out.width = innerWidth;
return out;
"""


@pytest.mark.parametrize("where", ["detail", "new"])
def test_the_writing_views_are_usable_at_a_window_that_is_not_wide(
    client: TestClient, tmp_path: Path, where: str
):
    """A 900px window is a laptop with the window not maximised.

    Under the old full-page grid this was where the writing box measured 50px —
    a `height: 100%` box in an `auto` track, under six hundred pixels of
    metadata. The surface is gone; what holds the box open now is the one
    `--writing` height it has at every width, and what keeps the facts usable
    is that they are ordinary page content the page scrolls to. The article
    must stay in the page's own flow (`position: relative`) and must not force
    a sideways scrollbar — the split's grown width has `max-width: 100%` to
    answer to.

    Asked of Chrome and not of `tests/cascade.py`, because the stacked layout
    lives behind a container query, which that engine skips by construction.
    """
    page = client.get(
        f"/detail/{TASK}{PLAIN}" if where == "detail" else f"/new{PLAIN}"
    ).text
    got = measured_in(chrome(), page, tmp_path / f"narrow-{where}.html", 900, _NARROW_WRITING)

    assert got["width"] == 900 and got["position"] == "relative"
    assert not got["sideways"], "the page scrolls sideways at 900px"
    for view in ("write", "split"):
        assert got[view]["rows"] >= 12, (
            f"the {view} view gives the document {got[view]['rows']} lines at a 900px window"
        )
        assert got[view]["factsWhole"], (
            "the facts grew a scrollbar of their own: fifteen fields in a box a "
            "few lines tall"
        )
        assert got[view]["factsReachable"], "and there is no way to scroll down to them"
    assert got["paneRows"] >= 12, "the rendered half of the split is not readable either"
    if where == "new":
        assert got["read"]["paneRows"] >= 12, "the create form's preview is not readable"
    else:
        assert got["read"]["landed"], (
            "pressing the eye did not land on the record's own read page"
        )


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
flipEditing();
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
flipEditing();
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
flipEditing();
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


_TOOLBAR_AT_A_WIDTH = _STUB_RENDER + r"""
// The detail page opens read-only and the create forms open editing, so this
// asks for the surface rather than assuming which page it is on.
if (typeof flipEditing === 'function') {
  flipEditing();
  await new Promise(go => setTimeout(go, 150));
}
const marks = document.getElementById('marks');
// The surface the toolbar is drawn on is the column, not the article: since
// 2026-08-24 the article is the page's width and everything fits inside it by
// construction, which would make `past` below the same negative number at every
// window — a measurement that has stopped asking anything.
const surface = document.querySelector('article.record .panes');
const buttons = [...marks.querySelectorAll('button.mark')];
const edge = surface.getBoundingClientRect().right;
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
    `article.record`, and the document scrolled sideways to 581px to hold them.
    Four of sixteen controls off the surface, on every page that has an editor.

    Two things this asks that a stylesheet cannot answer, and one it must not.
    Where a button ENDS UP is layout, and `tests/cascade.py` skips at-rule
    bodies, so it resolves the wide page and cannot see this one at all. And the
    comparison is button-right against article-right and never
    `scrollWidth <= innerWidth`: at 390px every page in this application already
    overflows from the nav shell, with no editor on it, so a test written that
    way would be measuring something else and failing for a reason it did not
    name.

    A media query and not a container query, proved in the days when the note
    and issue pages shipped a stylesheet with no `container-type` in it — a
    container query was patched in and measured byte-identical to no fix at all
    there. Both parametrised URLs now draw the one merged surface, so the
    parametrisation survives as reading against creating rather than page
    against page.
    """
    page = (
        client.get(f"/detail/{TASK}").text
        if where == "detail"
        else client.get("/new?kind=note").text
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
flipEditing();
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


# --------------------------------------------------------------------------- #
# A splice boundary inside a character
#
# `AGENTS.md` names the defect this section is written for, and names why a green
# suite shipped it: **no test drove the editor with anything but ASCII**, and for
# ASCII the three index spaces this application counts in are one number. They
# are not one number on anything else:
#
#   * a Python `str`, and `[...text]` in the browser, count CODE POINTS;
#   * `pycrdt.Text` counts UTF-8 BYTES;
#   * a JavaScript string, `Y.Text`, `selectionStart` and every index the two
#     surfaces trade count UTF-16 CODE UNITS, and an emoji is two of them.
#
# What is asked below is the browser's half, which is this file's half: what the
# SURFACE does when a boundary lands between the halves of a surrogate pair.
# `tests/test_coedit.py` asks the other half — whether a real `openproj.coedit`
# room and a real browser converge — and that is a stronger claim about a
# narrower path. The room here is the page's own Yjs on both ends of a socket
# that goes nowhere, because these questions are about `reflect()`, about
# `SURFACE.splice` and about the deltas Ace reports, none of which needs a
# server, and because a `Room` and a uvicorn per body is a large bill for an
# answer the browser is already holding.
#
# Every literal below is spelled with explicit escapes and never with characters
# typed into an editor. Composing this corpus on macOS silently produced NFD for
# `cafe` + U+0301 — which happened to be the case wanted, and would have been an
# invisible change of meaning if it had gone the other way.
# --------------------------------------------------------------------------- #

# The other end of the wire, in this page. Every frame the editor writes is kept
# for the script to hand to the room, and every frame the script wants to deliver
# goes in through `onmessage` — so the two halves are the real ones and only the
# wire between them is not. `fetch` is stubbed for the reason every Chrome test
# here stubs it: a `file://` page cannot reach `/api/preview`, and a session opens
# one.
_ONE_PAGE_ROOM = """
window.__errors = [];
addEventListener('error', event => window.__errors.push(String(event.message)));
window.fetch = async () => ({ok: true, json: async () => (
  {html: '<p data-startline="1">rendered</p>'})});
window.__sent = [];
function FakeSocket() {
  this.readyState = 1;
  window.__socket = this;
  setTimeout(() => { if (this.onopen) this.onopen(); }, 0);
}
FakeSocket.OPEN = 1;
FakeSocket.prototype.send = function (data) { window.__sent.push(JSON.parse(data)); };
FakeSocket.prototype.close = function () { this.readyState = 3; };
window.WebSocket = FakeSocket;
"""

# What the three scripts below share: base64 both ways, a session, somebody
# else's copy of the document on the other end of the socket, and the server's
# whole job — putting what this tab sent into that copy.
#
# `half` is the extra signature the reflect cases need, and it is needed because
# equality alone cannot see this one. A lone surrogate cannot be encoded, so on
# the server side it comes back as U+FFFD and the strings differ — but a half
# parked in an Ace row does NOT travel with the next delta, so at the instant the
# two copies are compared there is nothing on the wire to see. This looks at the
# surface itself.
_A_ROOM_IN_THE_PAGE = r"""
const b64 = bytes => {
  let out = '';
  for (let at = 0; at < bytes.length; at += 0x8000)
    out += String.fromCharCode.apply(null, bytes.subarray(at, at + 0x8000));
  return btoa(out);
};
const raw = held => Uint8Array.from(atob(held), letter => letter.charCodeAt(0));
const half = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const tick = ms => new Promise(go => setTimeout(go, ms));

if (!document.querySelector('article.record').classList.contains('editing')) flipEditing();
await tick(300);
const socket = window.__socket;
if (!socket) return {missing: 'the session opened no socket'};

// Somebody else's copy, built out of the bundle the page itself ships rather
// than out of a shim: `tests/js/drive.js` handing its own realm's `String` into
// a vm context is how a harness last lied to this repository, and the library
// here cannot be a different one because it IS the page's.
const room = new YJS.Doc();
const shared = room.getText('body');
shared.insert(0, ORIGINAL_BODY);
const tell = () => socket.onmessage({data: JSON.stringify({
  t: 'update', u: b64(YJS.encodeStateAsUpdate(room))})});
socket.onmessage({data: JSON.stringify({
  t: 'welcome', seed: 'a-seed', base: '0'.repeat(40), you: 'ann',
  sv: b64(YJS.encodeStateVector(room)),
  update: b64(YJS.encodeStateAsUpdate(room))})});
await tick(80);

let frames = 0;
const heard = () => {
  for (const frame of window.__sent.splice(0)) {
    if (frame.t !== 'update') continue;
    frames++;
    YJS.applyUpdate(room, raw(frame.u), 'ann');
  }
};
heard();
frames = 0;

const remote = async want => {
  shared.delete(0, shared.length);
  shared.insert(0, want);
  tell();
  await tick(80);
};
"""


# Every pair was measured rather than reasoned about, and each row says which
# confusion it can see. What decides a case is where the boundary falls relative
# to the differing character — not that there is an emoji in it somewhere — so
# each row carries the cut in two spaces.
_REFLECTED = (
    # A1. The named case, in the one direction nobody drives. The two thumbs
    # differ only in their SECOND code unit, so the code-unit scan `reflect()`
    # runs stops at head 1 — between D83D and DC4D, inside a character. It is
    # right today because everything downstream of that index counts code units
    # too; a scan over characters would say cut [0,1) and hand a 0 and a 1 to a
    # `splice` that reads them as units. 7 code points, 10 bytes, 8 code units.
    ("\N{THUMBS UP SIGN} done\n", "\N{THUMBS DOWN SIGN} done\n"),
    # C2. A ZWJ family whose first member changes. U+1F469 and U+1F468 share
    # their high surrogate, so the scan stops at head 1 — inside a pair and
    # inside a grapheme cluster at once. Nothing in `src/` counts graphemes,
    # which is why what this asserts is the document and never one-press-one-glyph.
    ("\U0001f469\u200d\U0001f469\u200d\U0001f467 crew\n",
     "\U0001f468\u200d\U0001f469\u200d\U0001f467 crew\n"),
    # A3, in the reflect direction. Two regional indicators; the boundary falls
    # inside the SECOND pair, at head 3. Half a flag is a valid DIFFERENT flag
    # rather than a broken character, so a corpus that only looked for U+FFFD
    # would let a shifted boundary through here.
    ("\U0001f1e9\U0001f1ea\n", "\U0001f1e9\U0001f1eb\n"),
    # F1. The robot, and the row that says a control has to be declared per
    # DIRECTION as well as per confusion. It is recorded as the control for the
    # surrogate confusion and it is one in the direction the shipped defect took:
    # a code-unit scan stops at head 14, no boundary falls inside a pair, and the
    # answer comes out right. It is NOT a control in the other direction, which
    # is the one `reflect()` could take — a code-point scan stops at 13, the
    # splice consuming it counts units, and a character on the boundary is eaten.
    # Measured, with that scan in place: `'\U0001f916 written bysomebody\n'`.
    # Nor is it a control for the byte confusion, where code points [13,21) are
    # bytes [16,24).
    ("\U0001f916 written by an agent\n", "\U0001f916 written by somebody\n"),
    # F2. A control for both confusions AT THE REFLECT, and a live case on `ace`
    # one line later. The cut is [7,7) in every one of the three spaces, so no
    # scan can move it and the reflect itself is right under either break. What
    # is not a control is what this test does next: the trailing keystroke goes in
    # at the END of a document that now carries an astral character, so on Ace
    # `run.from` counted in code points reports 16 where the surface spliced at
    # 17. Measured under that break: surface and room BOTH hold
    # `'a fine \U0001f389 resultZ\n'`, the Z one place early, in perfect
    # agreement — `reflect()` rewrites the editor to match the run it just sent.
    # It stays a control on `plain`, which does not use Ace's index at all.
    #
    # So F2 is a control for the reflect and F3 is the only one of the six that
    # is a control end to end. A control has to be declared against a named
    # confusion, a direction AND a surface, and this is the row that pays for
    # that sentence.
    ("a fine result\n", "a fine \U0001f389 result\n"),
    # F3. A control for both, and the byte family's analogue of F2 — the em dash
    # is present and sits AFTER both boundaries, so code points [1,5) are bytes
    # [1,5). This is what lets the suite say that "has an em dash in it
    # somewhere" is not the case either. The byte family has never had one.
    ("hello \u2014 world\n", "hi \u2014 world\n"),
)

_REFLECTING = _A_ROOM_IN_THE_PAGE + r"""
const answers = [];
for (const [was, now] of CASES) {
  await remote(was);
  const opened = SURFACE.text();
  await remote(now);
  const after = SURFACE.text();
  // And then one character typed by this tab, at the end of the document. On the
  // box `typed()` diffs the whole value, so a half left parked in `.value` is
  // pushed up the wire by the next keystroke; on Ace only the delta run travels
  // and a half stays in the row for ever, which is the other reason `loose` is
  // asked of the surface directly.
  const at = after.length;
  SURFACE.setCaret(at, at);
  SURFACE.splice(at, at, 'Z');
  await tick(80);
  heard();
  answers.push({opened, after, loose: half.test(after),
                surface: SURFACE.text(), room: shared.toString()});
}
return {errors: window.__errors, answers, frames,
        surface: SURFACE.onSplice ? 'ace' : 'textarea'};
"""


@pytest.mark.parametrize("editor", ["ace", "plain"])
def test_a_remote_keystroke_between_the_halves_of_a_pair_reaches_the_surface_whole(
    client: TestClient, tmp_path: Path, editor: str
):
    """Somebody else types, and the boundary lands inside a character.

    `reflect()` is the one hand-off in this direction: it scans a common prefix
    and suffix in UTF-16 code units and gives the two ends straight to
    `SURFACE.splice`, whose `positionOf` is `indexToPosition`, which clips to
    `[0, line.length]` and never to a character boundary. On the thumbs-up pair
    that scan stops at 1 — between D83D and DC4D — and the whole of why the page
    is right today is that the index and everything downstream of it are counted
    in the SAME space. Nothing said so: every test of this direction was ASCII,
    and for ASCII code points and code units are one number.

    The failure has two shapes and only equality catches both. A boundary applied
    from a character count leaves the surface holding a lone low surrogate, which
    the room's copy cannot encode — so the two documents differ permanently and
    U+FFFD appears in one of them. A boundary shifted the other way produces a
    perfectly well-formed string that is simply wrong, which is the shape the em
    dash and the flag have. So this asserts the string, never a substring, and
    scans the surface for a surrogate with no partner besides.

    Both surfaces, because this is the invariant written in two languages and
    guarding one copy of it is how the browser's half shipped in the first place:
    `textareaSurface.splice` is `was.slice(0, from) + put + was.slice(to)` and
    Ace's is `Document.remove` and `Document.insert`, and the index arrives at
    both of them from the same line of `reflect()`.

    The controls are counted per surface, because measured they are not the same
    set on both. On `plain`, two of the six pass with either confusion in place.
    On `ace` only F3 does: F2's reflect is right under both, and the keystroke
    this test makes after it is not, because by then the document carries an
    astral character and Ace's own index is what carries the run. F1 is a control
    in one DIRECTION only and is measured failing in the other. Each row says
    which, above its literal — and the reason each says it rather than the corpus
    saying it once is that "control" is a claim about a confusion, a direction
    and a surface together, and no one of the three implies the others.
    """
    page = client.get(f"/detail/{TASK}?editor={editor}").text.replace(
        '<link rel="icon"', f'<script>{_ONE_PAGE_ROOM}</script><link rel="icon"', 1
    )
    got = measured_in(
        chrome(), page, tmp_path / f"reflect-{editor}.html", 1400,
        _REFLECTING.replace("CASES", json.dumps([list(pair) for pair in _REFLECTED])),
        query=f"?editor={editor}", patience=9000,
    )

    assert not got.get("missing"), got.get("missing")
    assert got["errors"] == [], f"the page threw: {got['errors']}"
    assert got["surface"] == ("ace" if editor == "ace" else "textarea"), (
        f"the page mounted {got['surface']}, so nothing here was driven"
    )
    for (was, now), answer in zip(_REFLECTED, got["answers"], strict=True):
        assert answer["opened"] == was, (
            f"the room's {was!r} never reached the surface, so nothing below it was "
            f"driven: the surface holds {answer['opened']!r}"
        )
        assert answer["after"] == now, (
            f"somebody else edited {was!r} into {now!r} and this surface ended up "
            f"holding {answer['after']!r}"
        )
        assert not answer["loose"], (
            f"a surrogate with no partner is parked in the surface: {answer['after']!r}"
        )
        assert answer["surface"] == answer["room"] == now + "Z", (
            f"one character typed after the reflect left the surface holding "
            f"{answer['surface']!r} and the room holding {answer['room']!r}"
        )
    # One frame per keystroke this tab made, and not one more. A reflect writes
    # under `apply`, so it must put nothing on the wire at all — the naive
    # adapter this replaced made a PASSIVE tab push the whole document back up
    # the socket under its own name, 97,892 characters for a four-character
    # remote keystroke.
    assert got["frames"] == len(_REFLECTED), (
        f"{len(_REFLECTED)} keystrokes were made in this tab and {got['frames']} update "
        "frames went up the wire: somebody else's typing is being sent back as this "
        "tab's own"
    )


# Ace's own gestures, and what the surface says it changed. The runs are the
# thing under test: `spliced()` hands `run.from` and `run.to - run.from` to the
# `Y.Text` with no conversion at all, which is correct ONLY while they came out
# of `positionToIndex` — code units already. A count of characters anywhere on
# that path splits a pair or shortens a run.
_GESTURES = (
    # C1. `cafe` + U+0301 and `pre` + U+0302 — a decomposed e-acute, and a
    # backspace that takes the accent. A CONTROL FOR BOTH BROWSER CONFUSIONS,
    # measured: 19 code points and 19 code units, so no index on this line can
    # move between the two spaces a browser counts in. Its live arm is the third
    # space — 21 bytes, with the deleted run ending inside a two-byte character,
    # which is `Room.absorb` and belongs to `tests/test_coedit.py`. What this
    # must NOT assert is that one glyph vanished: nothing in `src/` counts
    # graphemes, Ace's `moveCursorLeft` is `moveCursorBy(0, -1)`, and measured it
    # removes U+0301 alone and leaves `cafe`. That is Ace's decision, and what
    # must hold is that whatever Ace removed is what the room removed.
    {"was": "le cafe\u0301 est pre\u0302t\n", "at": "le cafe\u0301", "select": "",
     "put": "", "now": None},
    # E1. A selection whose ends are both on whole characters and whose LENGTH is
    # not: the run `"— the "` is 6 code points, 8 bytes and 6 code units. A
    # CONTROL FOR BOTH BROWSER CONFUSIONS for the reason C1 is — an em dash is
    # one of each — and a live case for the byte one, where those 6 are 8 and
    # the wrong answer is `'six weeks e appetite\n'`.
    {"was": "six weeks \u2014 the appetite\n", "at": "six weeks ",
     "select": "\u2014 the ", "put": "", "now": "six weeks appetite\n"},
    # E2. A replacement spanning an astral emoji. Both boundaries are on whole
    # characters, so no scan can fail — what this tests is the LENGTH, which is
    # 8 code points, 11 bytes and 9 code units for the one run.
    {"was": "ship \U0001f680 on friday\n", "at": "ship ",
     "select": "\U0001f680 on friday", "put": "today", "now": "ship today\n"},
    # And the shape none of the three above has: an edit that is only MOVED by
    # what sits in front of it. Every other `at` here is an all-ASCII prefix, so
    # the caret's index is the same number in both browser spaces and a `run.from`
    # counted in code points would go unnoticed — measured, all three pass with
    # that defect in place. The rocket is one code point and two code units, so
    # this one is 10 in the space Ace reports and 9 in the other. It is the
    # browser's analogue of the em-dash run on the server's side of the wire.
    {"was": "\U0001f680 ship it\n", "at": "\U0001f680 ship it", "select": "",
     "put": "", "now": "\U0001f680 ship i\n"},
)

_ACE_GESTURED = _A_ROOM_IN_THE_PAGE + r"""
const editor = SURFACE.editor;
if (!editor) return {missing: 'the page mounted the box, so nothing here was driven'};
let said = [];
SURFACE.onSplice(runs => { for (const run of runs) said.push([run.from, run.to, run.put]); });

const answers = [];
for (const one of CASES) {
  // Seeded through the surface as an ordinary edit, so the room hears it the way
  // it hears typing — and at 0 and the whole length, which is the same index in
  // all three spaces and therefore cannot be the thing that fails below.
  SURFACE.splice(0, SURFACE.text().length, one.was);
  await tick(90);
  heard();
  const opened = SURFACE.text(), seeded = shared.toString();
  said = [];
  const start = one.at ? one.was.indexOf(one.at) + one.at.length : 0;
  SURFACE.setCaret(start, start + one.select.length);
  // Ace's own editing commands and never the surface's `splice`, so the delta
  // the binding consumes is one Ace made rather than one this test made.
  if (one.put) editor.insert(one.put); else editor.remove('left');
  await tick(90);
  heard();
  // Snapshotted, not handed over: `said` is rebound at the top of the next turn
  // of this loop, and an array handed over by reference goes on collecting the
  // NEXT case's seeding runs into the answer for this one.
  answers.push({opened, seeded, runs: said.slice(), surface: SURFACE.text(),
                room: shared.toString(), loose: half.test(SURFACE.text())});
}
return {errors: window.__errors, answers, frames,
        surface: SURFACE.onSplice ? 'ace' : 'textarea'};
"""


def test_what_the_second_surface_says_it_changed_is_what_the_room_changes(
    client: TestClient, tmp_path: Path
):
    """The outgoing half, on three gestures nothing drives with a character that
    is more than one of anything.

    Ace reports its own deltas — a position and the lines — and the binding turns
    the position into an index with `positionToIndex`, which counts UTF-16 code
    units, and the length with `lines.join('\\n').length`, which counts them too.
    That is the whole correctness argument, and it is why
    `test_the_browser_splices_on_a_whole_character` allowlists `run.from` by name
    while every other index into the document has to come from a named
    conversion. Nothing drove that allowlist. Each body below has a character
    that is more than one code unit, more than one byte, or both, and each one
    puts a boundary or a length across it.

    What this refuses to assert is how much a gesture removes. Ace's backspace
    takes a code point, so `cafe` + U+0301 loses the accent and keeps the
    `e` — Ace's decision, not this binding's, and pinning it here would pin
    somebody else's behaviour. What must hold is that whatever the surface says
    it changed is what the room changed, and that no surrogate is left without a
    partner at either end.

    Both halves of that are needed and neither is enough, because a wrong run
    corrupts BOTH copies: `spliced()` writes it into the document, the document
    is what `reflect()` reads, and one turn later the editor has been rewritten
    to agree with it. Measured under a run length counted in code points, E2
    leaves the surface AND the room holding `'ship todayy\n'`. So the outcome is
    asserted beside the agreement wherever the gesture has one outcome; where it
    does not — C1, whose answer is Ace's — the agreement is all there is, and
    that case is a control here and a live case in the room.
    """
    page = client.get(f"/detail/{TASK}?editor=ace").text.replace(
        '<link rel="icon"', f'<script>{_ONE_PAGE_ROOM}</script><link rel="icon"', 1
    )
    got = measured_in(
        chrome(), page, tmp_path / "ace-gestures.html", 1400,
        _ACE_GESTURED.replace("CASES", json.dumps(list(_GESTURES))),
        query="?editor=ace", patience=9000,
    )

    assert not got.get("missing"), got.get("missing")
    assert got["errors"] == [], f"the page threw: {got['errors']}"
    for case, answer in zip(_GESTURES, got["answers"], strict=True):
        assert answer["opened"] == case["was"] == answer["seeded"], (
            f"the surface opened on {answer['opened']!r} and the room on "
            f"{answer['seeded']!r}, so nothing below was driven"
        )
        assert answer["runs"], "the surface reported no change at all"
        assert answer["surface"] != case["was"], "the gesture changed nothing"
        assert not answer["loose"], (
            f"a surrogate with no partner is parked in the surface: {answer['surface']!r}"
        )
        assert answer["room"] == answer["surface"], (
            f"the surface holds {answer['surface']!r} and the room holds "
            f"{answer['room']!r} — the runs it reported were {answer['runs']}"
        )
        if case["now"] is not None:
            assert answer["surface"] == case["now"], (
                f"the gesture should have left {case['now']!r} and left "
                f"{answer['surface']!r}"
            )


# 1,500 characters, every one of them ASCII on purpose: the find side stays
# `cycle` so that vim's own regex is not the variable, and the character worth
# two code units goes in the REPLACEMENT. That is what makes the document grow
# apart from itself as the gesture runs — by the last replacement the same place
# is 1,331 in code units and 1,284 in code points, a drift of 47 — and it is why
# the mechanical three-length check has to be applied to the intermediate
# document here and not to the endpoints, which would reject this case for being
# ASCII on the way in.
_BULK = ("A cycle is six weeks and a cycle is what a bet is made for.\n"
         "Every cycle has a cool-down, and the cycle after it starts cold.\n") * 12

_SUBSTITUTED_ASTRAL = _A_ROOM_IN_THE_PAGE + r"""
const editor = SURFACE.editor;
if (!editor) return {missing: 'the page mounted the box, so nothing here was driven'};
const keymap = [...document.querySelectorAll('#statusbar button')]
  .find(b => b.textContent.startsWith('Keymap'));
if (!keymap) return {missing: 'the second editor carries no keymap control'};
keymap.click();
await tick(80);
SURFACE.splice(0, SURFACE.text().length, CORPUS);
await tick(150);
heard();
const opened = SURFACE.text(), seeded = shared.toString();
frames = 0;
let places = 0, touched = 0;
SURFACE.onSplice(runs => {
  places += runs.length;
  for (const run of runs) touched += (run.to - run.from) + run.put.length;
});
// The ex line through vim's own handler, which is what typing it and pressing
// Enter reaches. What is under test is the gesture's effect on the room and not
// vim's command parser, so it is driven here rather than as thirteen keystrokes.
const Vim = ace.require('ace/keyboard/vim').CodeMirror.Vim;
Vim.handleEx(editor.state.cm, '%s/cycle/\u{1F3AF}/g');
await tick(400);
heard();
return {errors: window.__errors, opened, seeded, frames, places, touched,
        surface: SURFACE.text(), room: shared.toString(), loose: half.test(SURFACE.text()),
        said: document.getElementById('state').textContent,
        handler: String(editor.getKeyboardHandler().$id)};
"""


def test_a_substitution_that_types_an_emoji_keeps_every_later_run_where_it_belongs(
    client: TestClient, tmp_path: Path
):
    """One keypress, forty-eight replacements, and a document that grows apart
    from itself while they are applied.

    `test_a_substitution_over_a_whole_document_is_announced_before_it_is_sent`
    drives this gesture already, with `cycle` to `bet`. Both are ASCII and the
    same length, so the drift between a code-point index and a code-unit one over
    the whole gesture is exactly **0**, and that test cannot see this class of
    failure at all. Replacing with U+1F3AF makes each replacement one code point
    and two code units, so the two spaces come apart by one per run: the last
    one's index is 1,331 in code units and 1,284 in code points. Applied one
    space out, the measured result is the document shredded — `A [dart] is six
    weeks and a[dart]e is what a bet is made for.` and on down the file — with no
    U+FFFD anywhere in it, which is why the assertion here is equality and not a
    signature.

    And the number the page says out loud, in the same browser because it is the
    same confusion moved into the copy: `touched` is
    `(run.to - run.from) + run.put.length`, so 48 replacements are 240 code units
    out and 96 in and the sentence must say 336. The same gesture is 288 in code
    points, which is the number a reader would get if that sum ever counted what
    the sentence calls "characters".
    """
    page = client.get(f"/detail/{TASK}?editor=ace").text.replace(
        '<link rel="icon"', f'<script>{_ONE_PAGE_ROOM}</script><link rel="icon"', 1
    )
    got = measured_in(
        chrome(), page, tmp_path / "ace-subst.html", 1400,
        _SUBSTITUTED_ASTRAL.replace("CORPUS", json.dumps(_BULK)),
        query="?editor=ace", patience=9000,
    )

    assert not got.get("missing"), got.get("missing")
    assert got["errors"] == [], f"the page threw: {got['errors']}"
    assert got["handler"] == "ace/keyboard/vim", "the keymap did not come on"
    assert got["opened"] == _BULK == got["seeded"], (
        "the surface and the room did not open on the same document"
    )
    assert got["surface"].count("\U0001f3af") == 48, (
        f"the substitution did not run: {got['surface'][:80]!r}"
    )
    assert "cycle" not in got["surface"]
    assert not got["loose"], "a surrogate with no partner is parked in the surface"
    assert got["room"] == got["surface"], (
        "the room and the editor disagree after a substitution that types a character "
        f"worth two code units: the room holds {got['room'][:120]!r}"
    )
    # One gesture, one frame — the batching this would otherwise not notice
    # going: 48 replacements sent one at a time fill the room's outbox.
    assert got["frames"] == 1, f"the gesture went out as {got['frames']} update frames"
    # The sentence, and not this test's own sum over the same runs, which would
    # be the test agreeing with itself. `places` and `touched` come back only to
    # make the failure readable.
    assert "336 characters changed at once" in got["said"], (
        f"the gesture changed 336 code units in {got['places']} places, which this "
        f"tab's own runs add up to {got['touched']}, and the page said {got['said']!r} "
        "— 288 is the same gesture counted in code points"
    )


_LONG_AND_NOT_ASCII = _STUB_RENDER + r"""
const size = document.getElementById('statusbar').lastElementChild;
const area = document.querySelector('textarea[name=body]');
flipEditing();
area.value = '\u9031'.repeat(CHARACTERS);
area.dispatchEvent(new Event('input'));
return {text: size.textContent, over: size.classList.contains('over'),
        said: document.getElementById('state').textContent, units: area.value.length};
"""


def test_the_length_and_the_ceiling_are_not_the_same_number_on_a_document_that_is_not_ascii(
    client: TestClient, tmp_path: Path
):
    """The other half of `test_the_length_says_the_ceiling_before_a_save_is_refused`.

    That test fills the box with `'x'.repeat(n)`. For ASCII a code unit IS a
    byte, so it passes unchanged over a bar that reads the ceiling off
    `text.length` — the byte-against-something-else confusion this branch is
    about, in the browser, on the one readout whose whole job is to say "this
    will be refused" BEFORE the writing is done and the tab is closed.

    A CJK character is one code unit and three bytes, so 90,000 of them are
    comfortably under 262,144 as a number and half again over it as a document.
    The bar has to say both, and say them as two different things: `Length` in
    code units, because that is what the editor this is modelled on counts, and
    the ceiling in bytes, because that is what the server refuses.
    """
    from openproj.model import MAX_BODY_BYTES

    characters = 90_000
    assert characters < MAX_BODY_BYTES < characters * 3, (
        "this is only a fixture while it is under the ceiling as a number and over "
        "it as a document"
    )
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "long-cjk.html",
        1400, _LONG_AND_NOT_ASCII.replace("CHARACTERS", str(characters)), patience=4800,
    )

    assert got["units"] == characters, "the box is not holding the document this is about"
    assert got["text"].startswith(f"Length: {characters:,}"), (
        f"the length is counted in something other than code units: {got['text']!r}"
    )
    assert f"{characters * 3:,} of {MAX_BODY_BYTES:,} bytes" in got["text"], (
        f"a document half again over the ceiling was drawn as {got['text']!r} — the "
        "ceiling is UTF-8 bytes and this is reading it off a count of code units"
    )
    assert got["over"], "a document that cannot be saved is not marked as such"
    assert "too long to save" in got["text"], got["text"]
    assert "cannot be saved" in got["said"], (
        f"and nobody was told before they pressed Save: {got['said']!r}"
    )


# --------------------------------------------------------------------------- #
# The room's save and the pusher's verdict
#
# The push happens behind the answer now (docs/deferred-push.md, "Confirmation
# cannot be 'my sha is on main'"), so every `saved` frame carries
# `pushed: false` and the state a save is in is one of three — in flight,
# landed, stranded — never a boolean.
# --------------------------------------------------------------------------- #


def test_a_room_save_is_quiet_and_the_alarm_is_kept_for_a_parked_commit(client: TestClient):
    """A warning that fires on every save is wallpaper.

    "saved here, not yet pushed" hung on `message.pushed === false`, which was
    the exceptional answer when it was written and is EVERY answer since
    v0.22.0 — so the ordinary save and the state the warning existed for read
    identically, and the one save that deserved the alarm no longer stood out.
    In flight is the quiet 'saved' now; a landing confirms in silence, because
    the shell's pile banner owns that news; and the alarm survives only for the
    save the pusher PARKED on a branch — answered 200 long ago, on GitHub but
    not on main, and resolved by nothing in this room.

    The verdict frame parks the FIRST save and re-mints the SECOND at once,
    because that is what a recovery pass announces, and the order the page
    handles it in is load-bearing: cleared as "everything up to the re-minted
    sha" first, the parked commit would be swept out silently instead of
    announced. And a parked sha this room never saved must say nothing —
    every record page hears every frame, and a stranger's stranded save is
    the banner's news, not this document's.
    """
    import base64

    from test_injection import run_js

    from openproj import coedit

    page = client.get(f"/detail/{TASK}{PLAIN}").text
    shown = client.get("/api/index.json").json()["plan"][TASK]["body"]
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }
    first, second = "a" * 40, "b" * 40
    saves = [
        {"t": "saved", "commit": first, "outcome": "committed", "pushed": False},
        {"t": "saved", "commit": second, "outcome": "committed", "pushed": False},
    ]
    stranger = {"t": "landed", "landed": "d" * 40, "remapped": {},
                "parked": [["9" * 40, "openproj/stranded-" + "9" * 40]]}
    verdict = {"t": "landed", "landed": "e" * 40, "remapped": {second: "e" * 40},
               "parked": [[first, f"openproj/stranded-{first}"]]}
    answer = run_js(
        page,
        "(async () => {"
        "  flipEditing();"
        "  __socket.opened();"
        f" __socket.hear({json.dumps(welcome)});"
        "  if (!COEDIT.live()) return 'the room never came up';"
        f" __socket.hear({json.dumps(saves[0])});"
        "  const afterSave = document.getElementById('state').textContent;"
        f" __socket.hear({json.dumps(saves[1])});"
        f" dispatchEvent(new CustomEvent('openproj:landed', {{detail: {json.dumps(stranger)}}}));"
        "  const afterStranger = document.getElementById('state').textContent;"
        f" dispatchEvent(new CustomEvent('openproj:landed', {{detail: {json.dumps(verdict)}}}));"
        "  const afterParked = document.getElementById('state').textContent;"
        "  return {afterSave, afterStranger, afterParked, reloads: __reloads()};"
        "})()",
        page=True,
        socket=True,
    )
    assert not answer["errors"], answer["errors"]
    got = answer["value"]
    assert got != "the room never came up", got

    assert got["afterSave"] == "saved", (
        f"an ordinary save was announced as {got['afterSave']!r} — every save answers "
        "pushed: false now, so a warning here fires every time, and a warning that "
        "fires every time warns nobody"
    )
    assert "stranded-999" not in got["afterStranger"], (
        f"a parked sha this room never saved raised this document's alarm: "
        f"{got['afterStranger']!r}"
    )
    assert "could not land" in got["afterParked"], (
        f"the pusher parked this room's save and the page said {got['afterParked']!r} — "
        "the one state the old warning existed for is the one nobody is told about"
    )
    assert verdict["parked"][0][1] in got["afterParked"], (
        f"the alarm does not say where the commit went: {got['afterParked']!r}"
    )
    assert got["reloads"] == 0, (
        "nobody here pressed Save, so no frame above may tear the page down"
    )


def test_a_stranded_save_raises_the_alarm_on_a_tab_that_missed_every_frame(client: TestClient):
    """The alarm above travelled only on the live landed frame, and the spec
    says in as many words that frames are dropped routinely: Cloud Run recycles
    the event stream every 300 seconds and it has NO replay
    (docs/deferred-push.md, "Confirmation cannot be 'my sha is on main'"). A
    verdict only a frame can deliver is an alarm that fires only if the tab
    happened to be listening at the right moment — and the parked save is
    precisely the one state a person must hear about, because their 200 went
    out long ago and nothing in the room resolves it.

    While a save is unconfirmed the room polls the same route the table's marks
    poll, `/api/table.json`, whose payload already carries the pusher's verdict
    — `landed`, `unpushed` and the parked (sha, branch) pairs — so the editor
    and the table cannot drift into disagreeing about what parked means. The
    payload here is the exact shape a parked recovery leaves behind: the pile
    honestly drained (`unpushed: 0` — the sha left main for a branch), with
    only the parked pairs to say what happened, so a poll that read the pile's
    arithmetic alone would clear the one save that had to become the alarm.
    NO frame is delivered anywhere in this test.
    """
    import base64

    from test_injection import run_js

    from openproj import coedit

    page = client.get(f"/detail/{TASK}{PLAIN}").text
    shown = client.get("/api/index.json").json()["plan"][TASK]["body"]
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }
    committed = "a" * 40
    branch = f"openproj/stranded-{committed}"
    saved = {"t": "saved", "commit": committed, "outcome": "committed", "pushed": False}
    fresh = {"landed": "f" * 40, "unpushed": 0, "parked": [[committed, branch]]}
    answer = run_js(
        page,
        "(async () => {"
        "  flipEditing();"
        "  __socket.opened();"
        f" __socket.hear({json.dumps(welcome)});"
        "  if (!COEDIT.live()) return 'the room never came up';"
        f" __socket.hear({json.dumps(saved)});"
        "  const armed = __pending();"
        "  __tick();"
        "  for (let i = 0; i < 50; i++) await Promise.resolve();"
        "  const said = document.getElementById('state').textContent;"
        "  return {armed, said, waiting: __pending(), reloads: __reloads()};"
        "})()",
        page=True,
        socket=True,
        replies=[{"status": 200, "json": fresh}],
    )
    assert not answer["errors"], answer["errors"]
    got = answer["value"]
    assert got != "the room never came up", got

    assert got["armed"] >= 1, (
        "no poll is armed while a save is unconfirmed — a tab that misses the "
        "frame can never hear the verdict, and the stream drops frames by design"
    )
    assert any(call["url"] == "/api/table.json" for call in answer["calls"]), (
        f"the poll did not ask the route that carries the verdict; asked: {answer['calls']!r}"
    )
    assert "could not land" in got["said"], (
        f"the pusher parked this room's save, no frame arrived, and the page said "
        f"{got['said']!r} — the alarm the poll exists to deliver never fired"
    )
    assert branch in got["said"], (
        f"the alarm does not say where the commit went: {got['said']!r}"
    )
    assert got["waiting"] == 0, (
        "nothing is unconfirmed any more, so nothing should keep polling"
    )
    assert got["reloads"] == 0, (
        "nobody here pressed Save, so nothing above may tear the page down"
    )


# --- linking one record from another's document ------------------------------


# The two pure functions the completion is decided by, driven where they live.
# Neither reaches the surface, so neither needs Ace — and both are exactly where
# a wrong answer is silent: a popup that opens on a checklist's brackets, or a
# title that closes the handle it was written into.
_WHERE_A_LINK_OPENS = """
(() => {
  const asked = [
    // The ordinary case: a bracket on this line, with a name half typed.
    ['See [Port', 9],
    // Closed, so the caret is past the handle rather than inside it.
    ['See [Port]', 10],
    ['See [Port](task-0a1001) and more', 32],
    // An image is not a link and has nothing to offer.
    ['![a figure', 10],
    // A bracket on the line above is not one somebody is in the middle of
    // writing. A checklist body is full of these.
    ['- [x] shaped it\\nand now ', 24],
    // Nothing typed yet, which is the moment the popup should open on.
    ['[', 1],
  ];
  return {
    handles: asked.map(([text, at]) => {
      const found = openHandle(text, at);
      return found === null ? null : [found.open, found.typed];
    }),
    // A title is document text and the two characters that end a handle are
    // escaped rather than dropped.
    texts: [
      linkText({value: 'task-0a1001', label: 'Fix [the] bracket'}),
      linkText({value: 'task-0a1001', label: 'A back\\\\slash'}),
      linkText({value: 'task-0a1001', label: ''}),
    ],
    // And the other shape the body completes: a word with a slash or a hash in
    // it. Ordinary prose has neither, which is the whole of why the trigger can
    // be this cheap — and a word that has one and completes nothing closes the
    // popup on the next keystroke rather than being guarded against here.
    refs: [
      ['See gt4py', 9],
      ['See GridTools/', 14],
      ['See C2SM/icon4py#14', 19],
      ['a sentence ending in a full stop.', 33],
      // Two words back is not the word being typed.
      ['C2SM/icon4py#1403 and then', 26],
    ].map(([text, at]) => {
      const found = openRef(text, at);
      return found === null ? null : found.typed;
    }),
  };
})()
"""


def test_the_body_knows_which_reference_is_being_typed(client: TestClient):
    """Where the completion decides to open, and what it writes.

    Three one-line functions, all three silent when wrong. A popup that opened on
    any `[` would open on every point of every checklist — `- [x]` is what a
    pitch's Progress section is made of. A title carrying a `]` would close the
    handle early and leave the rest of somebody's record name as prose beside a
    broken link. And a PR trigger looser than "this word has a slash or a hash in
    it" would put a popup over ordinary writing.
    """
    from test_injection import run_js

    got = run_js(client.get(f"/detail/{TASK}{PLAIN}").text, _WHERE_A_LINK_OPENS, page=True)
    assert not got["errors"], got["errors"]
    assert got["value"]["handles"] == [
        [4, "Port"],
        None,
        None,
        None,
        None,
        [0, ""],
    ], got["value"]["handles"]
    assert got["value"]["texts"] == [
        "Fix \\[the\\] bracket",
        "A back\\\\slash",
        # No title at all: the id, because a link with no text is a link nobody
        # can see.
        "task-0a1001",
    ], got["value"]["texts"]
    assert got["value"]["refs"] == [
        None, "GridTools/", "C2SM/icon4py#14", None, None,
    ], got["value"]["refs"]


def test_only_a_page_with_a_document_carries_the_list_of_linkable_records(
    client: TestClient,
):
    """The widening jcanton asked for, and the two places it must not reach.

    He asked for it in `records`: "include all records in SUGGEST.records, put
    issues and notes in there too and use that". `records` is what completes
    `parent` and `depends_on` — offering an issue there offers an edge the model
    refuses, which the comment beside that key has said since it was written —
    and the same blob ships to /table, where an inbox id in the bytes is the leak
    `test_exclusion.py` exists to catch. So the widening is a second key in the
    same blob, built by the same function, and only the two pages that carry a
    document being written ask for it.
    """
    import json

    def blob(page: str) -> dict:
        found = re.search(
            r'<script id="suggest" type="application/json">(.*?)</script>', page, re.S
        )
        assert found, "the page carries no suggestion blob"
        return json.loads(found.group(1))

    # The corpus this file serves is five planned records and nothing else, so
    # the inbox half of the claim is seeded here rather than assumed — through
    # the write path, which is also what proves the list follows the plan rather
    # than a snapshot of it.
    made = client.post("/api/record", json={
        "base_commit": head(client),
        "body": "Somebody noticed this in a meeting.\n",
        "fields": {"kind": "note", "title": "A note worth citing", "written_by": "ann"},
    })
    assert made.status_code == 201, made.text
    noted = made.json()["id"]

    detail = blob(client.get(f"/detail/{TASK}").text)
    linkable = {value["value"] for value in detail["linkable"]}
    assert noted in linkable, (
        f"the link list holds no inbox record, so the widening did nothing: {sorted(linkable)}"
    )
    assert {value["value"] for value in detail["records"]} < linkable, (
        "the link list is not wider than the plan-only one it was widened from"
    )
    assert noted not in {value["value"] for value in detail["records"]}, (
        "an inbox record reached the list that completes `parent` and `depends_on`"
    )

    table = client.get("/table").text
    assert "linkable" not in blob(table), (
        "the table's blob carries the link list, so every inbox id it names is in "
        "the bytes of a plan page"
    )
    assert noted not in table, "an inbox id reached a plan page"


_COMPLETING_A_LINK = r"""
  flipEditing();
  await new Promise(r => setTimeout(r, 500));
  const editor = SURFACE.editor;
  const open = () => document.querySelector('ul.suggest:not([hidden])');
  const shown = () => { const list = open(); return list
    ? [...list.children].map(item => item.dataset.value) : null; };
  // Ace's own entry point for a key, one level under the DOM:
  // `keyBinding.onCommandKey` is what its `keydown` listener calls, and it
  // answers whether some handler in the chain took the key. It is asked here
  // rather than dispatching a `KeyboardEvent`, because `keyCode` is not
  // settable through `KeyboardEventInit` in Chrome and a test that has to
  // `defineProperty` its way past that is testing its own workaround.
  const key = code => !!editor.keyBinding.onCommandKey(
    {preventDefault() {}, stopPropagation() {}}, 0, code);

  editor.focus();
  editor.navigateFileEnd();
  // The scroll that moving to the end of the document causes, settled before
  // anything is typed — a person opens a popup in an editor that is already
  // sitting still, and this is the harness catching up with that rather than a
  // wait the product needs.
  editor.renderer.updateFull(true);
  await new Promise(r => setTimeout(r, 150));
  // Typed through the editor, so the popup opens the way it does for a person
  // rather than because a test called the function that draws it. The bracket
  // alone first: nothing typed yet is when the whole plan is on offer, and it is
  // what makes the narrowing below a comparison rather than a single number.
  editor.insert('\nSee [');
  await new Promise(r => setTimeout(r, 250));
  const opened = shown();
  // The frame the cursor layer is drawn on, forced — the same call
  // `tests/test_seats.py` makes for the same reason. Headless Chrome does not
  // reliably render Ace's cursor before a measurement: measured here at column
  // 5 with the element still drawn at column 0, which makes `.ace_cursor` an
  // oracle that answers about the frame before the keystroke. The popup's own
  // position does not come from the drawing — it comes from Ace's arithmetic,
  // which needs no frame — so this is the test catching up with the product
  // rather than the product waiting for the test.
  editor.renderer.updateFull(true);
  await new Promise(r => setTimeout(r, 150));
  const placed = (() => {
    const list = open();
    const caret = document.querySelector('.acebox .ace_cursor');
    if (!list || !caret) return null;
    const box = list.getBoundingClientRect(), at = caret.getBoundingClientRect();
    return {left: Math.round(box.left - at.left), under: Math.round(box.top - at.bottom)};
  })();
  // What the surface SAYS, against where Ace drew the caret. The popup's own
  // position is one subtraction away from this, so a disagreement here is the
  // first place it shows — and it is where a fallback answering about a
  // different box would be caught rather than being averaged into a placement
  // that looks nearly right.
  const agrees = (() => {
    const drawn = document.querySelector('.acebox .ace_cursor');
    if (!drawn) return null;
    const box = drawn.getBoundingClientRect(), said = SURFACE.caretBox();
    return {dx: Math.round(said.left - box.left), dy: Math.round(said.top - box.top)};
  })();

  // And then the title, which is what the completion is on.
  editor.insert('Verify');
  await new Promise(r => setTimeout(r, 250));
  const narrowed = shown();

  // Back to the whole plan, so the arrow below has more than one row to move
  // between whatever the corpus happens to hold.
  for (let i = 0; i < 6; i++) editor.remove('left');
  await new Promise(r => setTimeout(r, 250));

  // Down moves the highlight and the key does not reach the document.
  const wasLines = editor.session.getLength();
  const tookDown = key(40);
  await new Promise(r => setTimeout(r, 60));
  const highlighted = open()
    ? [...open().children].findIndex(item => item.classList.contains('on')) : -1;

  const tookReturn = key(13);
  await new Promise(r => setTimeout(r, 200));
  const written = SURFACE.text();
  const closed = shown();
  // And with nothing open, the same key is not claimed at all — which is the
  // half that says this sits in front of Ace's command table without taking a
  // single key away from writing.
  const tookWhenClosed = key(13);

  return {opened, narrowed, placed, agrees, highlighted, tookDown, tookReturn, closed,
          tookWhenClosed,
          lines: [wasLines, editor.session.getLength()],
          tail: written.slice(written.lastIndexOf('\nSee '))};
"""


def test_the_second_editor_completes_a_link_to_a_record(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-25: "I'd like to have links to other records in the body
    of a record, with autofill functioning when adding the link" — and, asked
    which surface, "only ace editor. autofill the title with autocompletion and
    then automatically place the (id)".

    So: the popup completes on the title, and what it writes is `[Title](id)`.

    In Chrome and not in the node shim, because every part of this is Ace's. The
    popup is placed against Ace's own drawn cursor — the shim answers `[]` for
    every `getClientRects` — and the keys are claimed through Ace's keyboard
    chain, which is the whole reason the capability exists: `attachEditing`'s own
    comment records that Ace's `stopEvent` calls `stopPropagation`, so Return and
    the arrows never reach a DOM listener on the host.

    `tookWhenClosed` is the assertion this feature could most easily be wrong in
    the invisible direction. A handler that claims Return whenever it is on the
    page takes the newline away from everybody writing, and nothing would say so
    except somebody trying to start a paragraph.

    The same popup completes a pull request reference — see
    `test_the_second_editor_completes_a_pull_request_in_the_body`. One widget,
    two things it recognises, and what it recognises them by is
    `test_the_body_knows_which_reference_is_being_typed`.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text,
        tmp_path / "linking.html", 1400, _COMPLETING_A_LINK,
        query="?editor=ace", patience=6800,
    )

    assert got["opened"] and len(got["opened"]) > 1, (
        f"typing `[` opened no list of records: {got}"
    )
    assert all(value.split("-")[0] in {"prod", "proj", "pitch", "task", "issue", "note"}
               for value in got["opened"]), got["opened"]
    # The completion is on the TITLE, which is the half of the ask that a list
    # of everything cannot show: `Verify` is a word in one record's name and in
    # no record's id.
    assert got["narrowed"] == ["pitch-b20000"], (
        f"typing a title did not narrow the list to the record it names: {got['narrowed']}"
    )
    assert got["placed"] and abs(got["placed"]["left"]) <= 2, (
        f"the list is not under the caret it completes: {got['placed']}"
    )
    assert 0 <= got["placed"]["under"] <= 8, (
        f"the list is not against the caret's line: {got['placed']}"
    )
    assert got["agrees"] and abs(got["agrees"]["dx"]) <= 1 and abs(got["agrees"]["dy"]) <= 1, (
        "the surface and the drawing disagree about where the caret is, which is "
        f"the placement above about to be wrong on some other machine: {got['agrees']}"
    )

    assert got["tookDown"] and got["highlighted"] == 1, (
        f"the arrow key did not move the highlight: {got}"
    )
    assert got["tookReturn"], "Return did not reach the popup"
    assert got["closed"] is None, "the list stayed open after inserting"
    assert got["lines"][0] == got["lines"][1], (
        f"a claimed key reached the document as well: {got['lines']}"
    )
    assert re.fullmatch(
        r"\nSee \[[^\]]+\]\((?:prod|proj|pitch|task|issue|note)-[0-9a-f]{6}\)",
        got["tail"],
    ), (
        f"what was written is not a title and an id: {got['tail']!r}"
    )
    assert not got["tookWhenClosed"], (
        "Return is claimed with no list open, so this popup has taken the newline "
        "away from everybody writing a paragraph"
    )


_COMPLETING_A_PULL_REQUEST = r"""
  flipEditing();
  await new Promise(r => setTimeout(r, 500));
  const editor = SURFACE.editor;
  const open = () => document.querySelector('ul.suggest:not([hidden])');
  const shown = () => { const list = open(); return list
    ? [...list.children].map(item => item.dataset.value) : null; };
  const key = code => !!editor.keyBinding.onCommandKey(
    {preventDefault() {}, stopPropagation() {}}, 0, code);
  const line = () => SURFACE.text().split('\n').pop();

  editor.focus();
  editor.navigateFileEnd();
  // A word with no slash and no hash in it: prose, and nothing to complete.
  editor.insert('\nSee gt4py');
  await new Promise(r => setTimeout(r, 250));
  const overProse = shown();

  // The repository, half typed. Both what is in it: the bare `org/repo#`, which
  // is the half nobody remembers, and the reference already cited in the plan.
  for (let i = 0; i < 5; i++) editor.remove('left');
  editor.insert('GridTools/');
  await new Promise(r => setTimeout(r, 250));
  const onRepo = shown();

  // Taking the bare one leaves the number to be typed, so the popup stays.
  const tookRepo = key(13);
  await new Promise(r => setTimeout(r, 250));
  const afterRepo = {line: line(), list: shown()};

  editor.insert('1877');
  await new Promise(r => setTimeout(r, 250));
  const narrowed = shown();
  const tookRef = key(13);
  await new Promise(r => setTimeout(r, 250));
  const afterRef = {line: line(), list: shown()};

  // And the other repository, reached from the half of the name that is not the
  // organisation — the list matches on the whole reference.
  editor.insert(' and icon4py#');
  await new Promise(r => setTimeout(r, 250));
  const other = shown();
  return {overProse, onRepo, tookRepo, afterRepo, narrowed, tookRef, afterRef, other};
"""


def test_the_second_editor_completes_a_pull_request_in_the_body(
    client: TestClient, tmp_path: Path
):
    """jcanton, 2026-08-25, asked whether the autofill reaches pull requests from
    the two repositories this plan is about — "ideally both in the PRs field as
    well as in the body".

    The field has completed them since `_suggestions` was written. The body
    completed nothing, although `_pr_refs` has rendered `org/repo#123` in prose
    as a link for just as long: the notation was readable and unwritable.

    **What it offers is what the plan already cites**, and that is the whole
    answer to "does it work for icon4py and gt4py". There is no live lookup —
    every page here is inlined and reaches no network, which is the rule
    `static/VENDOR.md` exists for — so a repository is offered once some record
    names a pull request in it, and the bare `org/repo#` for each of those comes
    with it. The two references below are put in through the write path rather
    than by editing a fixture, because the write path is what a person uses.

    `overProse` is the assertion this feature could most easily be wrong in the
    annoying direction: a trigger that fired on any word would put a popup over
    everybody's writing, and nothing but somebody complaining would say so.
    """
    for record, refs in (
        (OTHER, ["C2SM/icon4py#1403"]),
        (DONE, ["GridTools/gt4py#1877", "C2SM/icon4py#1521"]),
    ):
        written = client.patch(f"/api/record/{record}", json={
            "base_commit": head(client), "fields": {"prs": refs}, "body": None,
        })
        assert written.status_code == 200, written.text

    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?editor=ace").text,
        tmp_path / "prs.html", 1400, _COMPLETING_A_PULL_REQUEST,
        query="?editor=ace", patience=6800,
    )

    assert got["overProse"] is None, (
        f"a word with no slash and no hash in it opened a popup: {got['overProse']}"
    )
    assert got["onRepo"] == ["GridTools/gt4py#", "GridTools/gt4py#1877"], got["onRepo"]
    assert got["tookRepo"] and got["afterRepo"]["line"] == "See GridTools/gt4py#", (
        f"taking the bare repository wrote something else: {got['afterRepo']}"
    )
    assert got["afterRepo"]["list"], (
        "the popup closed on half a reference, so the number it left to be typed "
        "has to be remembered rather than chosen"
    )
    assert got["narrowed"] == ["GridTools/gt4py#1877"], got["narrowed"]
    assert got["tookRef"] and got["afterRef"] == {
        "line": "See GridTools/gt4py#1877", "list": None,
    }, got["afterRef"]
    # The bare `org/repo#` leads, because `icon4py#` is a substring of it too —
    # and it is the entry that is worth the most when the number is the part
    # nobody has memorised.
    assert got["other"] == [
        "C2SM/icon4py#", "C2SM/icon4py#1521", "C2SM/icon4py#1403",
    ], f"the other repository's references are not offered: {got['other']}"


_WIDENING = """
(async () => {
  const values = () => SUGGEST.prs.map(one => one.value);
  const before = values();
  widenPullRequests();
  // The fetch and its three `.then`s are microtasks; the shim's clock is not
  // involved, so draining the queue is what waiting means here.
  for (let i = 0; i < 30; i++) await Promise.resolve();
  const after = values();
  // And asking again asks nothing: one page, one call.
  widenPullRequests();
  for (let i = 0; i < 30; i++) await Promise.resolve();
  return {before, after, again: values(),
          labels: Object.fromEntries(SUGGEST.prs.map(one => [one.value, one.label])),
          live: SUGGEST.live};
})()
"""


def test_the_page_widens_its_pull_requests_with_what_is_open_now(client: TestClient):
    """jcanton, 2026-08-25: "would it be possible to have a page connect to the
    network to get the actual list of PRs from the repos?"

    The page still connects to nothing but this server — `/api/prs` is
    same-origin and the server is what talks to GitHub. What this asserts is the
    fold: the list the corpus gave the page grows, in place, so a popup opened
    before the answer landed reads the wider list on the next keystroke without
    being handed it.

    **Order is the argument.** A reference some record already cites is one this
    plan has a reason to mention again, so it keeps its place and only gains the
    title it never had; everything else is appended, and the filter runs over the
    whole list. And a bare `owner/repo#` is put at the front for a repository the
    corpus has never cited, because that is the half nobody has memorised.

    One call per page: the second ask returns without touching the network, which
    the single scripted reply is what proves — a second fetch would find none.
    """
    from test_injection import run_js

    cited = client.patch(f"/api/record/{TASK}", json={
        "base_commit": head(client), "fields": {"prs": ["C2SM/icon4py#1403"]}, "body": None,
    })
    assert cited.status_code == 200, cited.text

    got = run_js(
        client.get(f"/detail/{TASK}{PLAIN}").text, _WIDENING, page=True,
        replies=[{"status": 200, "json": {"prs": [
            {"value": "C2SM/icon4py#1403", "label": "The one already cited"},
            {"value": "C2SM/icon4py#1521", "label": "Open and never mentioned"},
            {"value": "GridTools/gt4py#1877", "label": "In a repository nobody cited"},
        ], "stale": False}}],
    )
    assert not got["errors"], got["errors"]
    answer = got["value"]

    assert answer["live"] is True, "the served page does not know it has a server"
    assert "C2SM/icon4py#1403" in answer["before"], "the corpus's own list is missing"
    assert "C2SM/icon4py#1521" not in answer["before"], (
        "this test cannot show a widening: the corpus already had the open one"
    )
    for value in ("C2SM/icon4py#1403", "C2SM/icon4py#1521", "GridTools/gt4py#1877"):
        assert value in answer["after"], f"{value} is not offered: {answer['after']}"
    # The cited one keeps its place at the front and gains the title it never had.
    assert answer["after"].index("C2SM/icon4py#1403") < answer["after"].index(
        "C2SM/icon4py#1521"
    ), answer["after"]
    assert answer["labels"]["C2SM/icon4py#1403"] == "The one already cited"
    # And the repository nobody cited is offered bare, so the number can be typed.
    assert "GridTools/gt4py#" in answer["after"], answer["after"]
    assert answer["labels"]["GridTools/gt4py#"] == "any pull request"
    assert answer["again"] == answer["after"], (
        "asking twice asked GitHub twice, or folded the same list in again"
    )


# --------------------------------------------------------------------------- #
# The slide editor's plain surface — `render_slide_editor`'s first test
# --------------------------------------------------------------------------- #

_SLIDE_TOOLBAR_AND_STATUS = _STUB_RENDER + r"""
const marks = document.getElementById('marks');
const bar = document.getElementById('statusbar');
return {
  buttons: marks.querySelectorAll('button.mark').length,
  said: bar.textContent,
};
"""


def test_the_plain_slide_editor_draws_a_toolbar_and_a_status_strip(
    client: TestClient, tmp_path: Path
):
    """`render_slide_editor` inlines the same five `attach*` calls the record
    page makes at `slides.py:795` — `attachUploads`, `attachDrawing`,
    `attachEditing`, `attachGutter`, `attachStatus` — all behind `if (SURFACE)`.

    `SURFACE` used to be built by calling `aceSurface` directly rather than
    through `bodySurface`, the function that falls back to the plain textarea
    surface when Ace is not on the page. So on `?editor=plain`,
    `window.aceSurface` is undefined, `SURFACE` was `null`, and the whole
    guarded block was skipped: no toolbar drawn into `#marks`, no upload
    wiring, no drawing button wired to its surface, no gutter and no caret
    readout in `#statusbar` at all. A person editing a slide with the plain
    editor got a bare `<textarea>` with nothing around it — and the new
    drawing button would have inherited exactly that hole, since it is wired
    on the same guarded `SURFACE`.
    """
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}?view=slide&editor=plain").text,
        tmp_path / "slide-plain.html", 1400, _SLIDE_TOOLBAR_AND_STATUS,
        query="?editor=plain",
    )
    assert got["buttons"] > 0, "the plain slide editor drew no toolbar at all"
    assert got["said"].strip(), "the plain slide editor drew no status strip at all"


_SLIDE_READER_SURFACE = r"""
return {
  hasBodySurface: typeof bodySurface !== 'undefined',
  marks: document.getElementById('marks').children.length,
  said: document.getElementById('statusbar').textContent,
};
"""


def test_a_reader_of_the_slide_editor_gets_no_surface_and_no_toolbar(repo_path: Path, tmp_path: Path):
    """The other half of the same fix, and the one that matters more: `MAY_WRITE`
    gates the call to `bodySurface` exactly as it gated the old call to
    `aceSurface`, so a reader the server would refuse a save from still gets
    `SURFACE === null` and none of the five `attach*` calls run. Giving a
    signed-out reader a toolbar would be a worse regression than the hole this
    commit closes.

    Driven directly against `render_slide_editor` with `may_write=False`,
    which is how `tests/test_render.py`'s
    `test_a_reader_who_may_not_write_is_sent_no_editor_library` asks the same
    question of the record page: `--auth dev` makes every request through the
    `client` fixture a writer, so the read/write split can only be asked of the
    renderer itself. The `Index` is built the same way the server builds its
    own, off the same bare repo `repo_path` already seeded — reading the
    server's private state through a running `client` would be reaching for
    something this suite already has a documented way to ask directly.
    """
    from datetime import date

    from openproj.index import build_index
    from openproj.render import render_slide_editor
    from openproj.render.shell import ROUTES
    from openproj.store import Store
    from openproj.web import _config_at, _records_at

    store = Store(repo_path)
    commit = store.head()
    config, _unreadable_config = _config_at(store, commit)
    records, _unreadable_records = _records_at(store, commit)
    index = build_index(records, config, date.today())

    page = render_slide_editor(
        index, TASK, ROUTES, base_commit=commit, may_write=False, editor="plain",
    )
    assert "bodySurface(PROSE)" in page, "the guard changed shape entirely"
    assert re.search(r"MAY_WRITE\s*\?\s*bodySurface\(PROSE\)\s*:\s*null", page), (
        "a reader must still resolve SURFACE to null"
    )

    got = measured_in(
        chrome(), page, tmp_path / "slide-reader.html", 1400, _SLIDE_READER_SURFACE,
        query="?editor=plain",
    )
    assert not got["hasBodySurface"], (
        "a reader was sent the editor toolkit that defines bodySurface at all"
    )
    assert got["marks"] == 0, "a reader was drawn a toolbar with nothing behind it"
    assert got["said"] == "", "a reader was drawn a status strip with nothing behind it"


# --- the drawing popup, mounted for real, over a real origin ----------------
#
# `measured_in` cannot drive this page at all: 0 of 6 runs completed mount
# plus two exports at its usual ~5000ms budget, 3 of 6 at 60000ms, all 6 only
# at 600000ms, and not cleanly monotonically along the way (`docs/drawings.md`,
# "Five helpers, not one"). So nothing below uses it. Every test here drives a
# real Chrome over DevTools against `live_server`'s real uvicorn — the same
# shape `tests/test_coedit.py` already uses three times — because that is the
# only mode that can actually fetch `/static/excalidraw.js`, mount it, and
# carry exported PNG bytes back out as something a Python test can read.


def test_the_client_side_drawing_ceiling_matches_the_servers(client: TestClient):
    """`MAX_DRAWING_BYTES` in the rendered page is a literal and not a template
    variable — `render/` cannot import `MAX_ASSET_BYTES` from `web.py`, because
    `web.py` imports `render` and the reverse import would be a cycle. The same
    trade `NO_VALUE` makes against `index.NO_VALUE`
    (`test_empty_is_spelled_the_same_on_both_sides_of_the_wire`), and the same
    risk: nothing but this test stops the two drifting, and a drift would let
    an oversized drawing through the client's own guard only for the server to
    answer it with a 413 after the strokes are already on their way there.
    """
    page = client.get(f"/detail/{TASK}").text
    assert "const MAX_DRAWING_BYTES = 2 * 1024 * 1024;" in page
    assert MAX_ASSET_BYTES == 2 * 1024 * 1024, (
        "web.py's own ceiling moved, and the client's literal was not updated with it"
    )


def _drag(call, x1: float, y1: float, x2: float, y2: float) -> None:
    """A real, trusted drag on the canvas: `Input.dispatchMouseEvent`, not a
    synthetic `pointerdown`/`pointerup` a script could dispatch on its own.
    Excalidraw's shape tools read a genuine pointer down, a genuine move and a
    genuine up — the same three DevTools already sends `pressed_in`'s single
    click through, extended to a drag because a shape needs two points and
    `pressed_in` only ever presses one."""
    for kind, x, y, buttons in (
        ("mousePressed", x1, y1, 1), ("mouseMoved", x2, y2, 1), ("mouseReleased", x2, y2, 0),
    ):
        call("Input.dispatchMouseEvent", {
            "type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1,
        })
        time.sleep(0.05)


def _until(call, expression: str, seconds: float = 20) -> object:
    """`expression`, asked again every quarter second until it answers
    something truthy — `in_a_live_page`'s own wait, pulled out here because
    these tests ask it of more than one condition over one page's life rather
    than once at the end of it."""
    deadline = time.monotonic() + seconds
    value = None
    while time.monotonic() < deadline:
        value = _evaluated(call, expression, patient=True)
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(f"never became true within {seconds}s: {expression}")


def _png_text_chunks(data: bytes) -> dict[bytes, bytes]:
    """Every `tEXt` chunk's key and value, read by walking the file's own
    chunk structure rather than trusted from a comment about what
    `exportToBlob` is supposed to write. The structural claim this backs is
    "the scene really is in the PNG, under this key" — never a byte count,
    because Excalidraw's roughness draws from a random seed and the same scene
    exported twice does not land on the same size (`docs/drawings.md`, "Five
    helpers, not one")."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG at all"
    chunks: dict[bytes, bytes] = {}
    pos = 8
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"tEXt":
            key, _, value = body.partition(b"\x00")
            chunks[key] = value
        pos += 8 + length + 4
    return chunks


_WATCH_INJECTIONS_AND_OPEN = r"""
(async () => {
  if (!window.__armed) {
    window.__violations = [];
    document.addEventListener('securitypolicyviolation', event => {
      window.__violations.push(event.effectiveDirective + ' <- ' + String(event.blockedURI));
    });
    // Widened the same way `_WATCH_THE_NETWORK` was widened, above: a `src`
    // is refused where the plain `.textContent` script this page injects is
    // not, so both have to be caught for the zero below to mean anything.
    window.__injected = [];
    const append = Element.prototype.appendChild;
    Element.prototype.appendChild = function (node) {
      if (node && node.tagName === 'SCRIPT') {
        window.__injected.push(
          node.src ? 'src' : `inline:${node.dataset.injectedBundle || '(unmarked)'}`
        );
      }
      return append.call(this, node);
    };
    document.getElementById('drawing').click();
    document.querySelector('.drawmenu button').click();
    window.__armed = true;
    return null;
  }
  if (!document.querySelector('.drawpopup .excalidraw')) return null;
  // A frame raced against a timeout rather than trusted alone: rAF is
  // unreliable on this exact page under a virtual clock, and this harness
  // has no virtual clock to race against — but the race costs nothing and
  // keeps this probe shaped the same way as the ones that do need it.
  await new Promise(resolve => {
    let settled = false;
    requestAnimationFrame(() => { if (!settled) { settled = true; resolve(); } });
    setTimeout(() => { if (!settled) { settled = true; resolve(); } }, 300);
  });
  const before = {
    violations: window.__violations.slice(), injected: window.__injected.slice(),
  };
  // The forced failure: a REAL `<script src>`, refused because `script-src`
  // grants no `'self'` for a fetched script to match — the same shape
  // `test_no_editor_asks_for_a_script_after_the_page_has_loaded` uses for Ace.
  const control = document.createElement('script');
  control.src = '/static/excalidraw.js';
  document.body.appendChild(control);
  await new Promise(r => setTimeout(r, 300));
  return {
    before,
    after: {violations: window.__violations.slice(), injected: window.__injected.slice()},
  };
})()
"""


def test_the_fetch_and_inject_delivery_is_clean_under_the_real_policy(
    live_server: str, tmp_path: Path
):
    """The spike proved fetch and inject are each individually allowed —
    `connect-src 'self'` grants the fetch that reads the bundle's text,
    `script-src 'unsafe-inline'` grants the inline injection — but never
    exercised the pair together: it inlined all 9.1MB into one `file://` page
    instead of fetching anything (`docs/drawings.md`, "The spike, which came
    first"). This is that pair, against a real origin, with the
    forced-failure control every CSP probe in this file carries: a real
    `<script src>` really is refused where the marked inline injection is not,
    so the zero violations below are evidence the probe could have failed and
    did not — not an assertion that could only ever pass.
    """
    drawn, said = in_a_live_page(
        chrome(), f"{live_server}/detail/{TASK}?editor=plain",
        _WATCH_INJECTIONS_AND_OPEN, tmp_path / "profile", seconds=30,
    )
    before, after = drawn["before"], drawn["after"]
    assert before["violations"] == [], (
        f"the real fetch-and-inject path tripped the policy: {before['violations']}"
    )
    assert before["injected"] == ["inline:excalidraw"], (
        "the only script injected at runtime by the time the popup mounted was not "
        f"exactly one, marked as the vendored bundle: {before['injected']}"
    )
    # The console is not asked for silence here the way the other CSP probes in
    # this file ask it: the forced-failure control a few lines down is a real
    # policy violation and prints a real console line about it, on purpose, in
    # this same session — the `securitypolicyviolation` event above already IS
    # the authoritative zero, over the window that matters.

    assert after["injected"] == before["injected"] + ["src"], (
        f"the forced-failure control was not even injected: {after['injected']}"
    )
    assert any("script-src" in line for line in after["violations"]), (
        f"the policy did not refuse the injected <script src>: {after['violations']}"
    )


def test_a_drawing_is_created_reopened_and_a_resave_touches_no_markdown(
    live_server: str, tmp_path: Path
):
    """The round trip `docs/drawings.md` says is testable today, driven
    exactly the way it says to drive it: a real Chrome over DevTools, real
    strokes, against a real origin. Three claims, told as one story because
    they are one story —

    1. a new drawing splices its markdown exactly once, at the caret, and
       nowhere else;
    2. the bytes the server now serves read back — through the app's own
       already-loaded `EXCALIDRAW.loadSceneOrLibraryFromBlob`, not a second
       implementation of the format — as the same elements that were drawn,
       structurally (a `tEXt` chunk under the right key, the right element
       count and types) and never by an exact byte count, which Excalidraw's
       own random seed makes meaningless;
    3. a re-save of that same drawing — after a reload, reopened through the
       menu, with a third shape added — changes the PNG and changes nothing
       else, because the whole point of a stable path is that the body never
       has to be found and edited again.
    """
    url = f"{live_server}/detail/{TASK}?editor=plain"
    with _devtools(chrome(), url, tmp_path / "profile") as (call, said):
        time.sleep(2)
        _evaluated(call, "document.getElementById('drawing').click()")
        _evaluated(call, "document.querySelector('.drawmenu button').click()")
        _until(call, "!!document.querySelector('.drawpopup .excalidraw')")

        _evaluated(call, "document.querySelector('[data-testid=\"toolbar-rectangle\"]').click()")
        _drag(call, 300, 300, 480, 430)
        _evaluated(call, "document.querySelector('[data-testid=\"toolbar-ellipse\"]').click()")
        _drag(call, 550, 300, 700, 430)
        time.sleep(0.2)

        original_body = _evaluated(call, "document.querySelector('[name=body]').value")
        assert "drawings/draw-" not in original_body, "the body already named a drawing"

        _evaluated(call, "document.getElementById('draw-save').click()")
        assert _until(call, "!document.querySelector('.drawpopup')"), (
            "the popup did not close itself after a successful save"
        )
        after_create = _evaluated(call, "document.querySelector('[name=body]').value")
        match = re.search(r"draw-[0-9a-f]{6}", after_create)
        assert match, f"no drawing id landed in the body: {after_create!r}"
        drawing_id = match.group(0)
        assert after_create == f"![](drawings/{drawing_id}.png){original_body}", (
            "the splice put something other than the bare embed in at the caret, or "
            "put it somewhere other than the caret"
        )

        served = httpx.get(f"{live_server}/drawings/{drawing_id}.png")
        assert served.status_code == 200
        assert set(_png_text_chunks(served.content)) == {b"application/vnd.excalidraw+json"}, (
            "the exported PNG carries no scene, or carries it under a different key"
        )
        round_trip = _evaluated(call, f"""
        (async () => {{
          const blob = await (await fetch('/drawings/{drawing_id}.png')).blob();
          const loaded = await EXCALIDRAW.loadSceneOrLibraryFromBlob(blob, null, null);
          return {{count: loaded.data.elements.length, types: loaded.data.elements.map(e => e.type)}};
        }})()
        """)
        assert round_trip == {"count": 2, "types": ["rectangle", "ellipse"]}, round_trip

        # Reload, and reopen the SAME drawing through the menu — not a fresh
        # popup addressed by hand, but the seam a person actually presses.
        call("Page.enable")
        call("Page.navigate", {"url": url})
        _until(call, "!!document.getElementById('drawing')")
        _evaluated(call, "document.getElementById('drawing').click()")
        rows = _until(
            call, "[...document.querySelectorAll('.drawmenu button')].map(b => b.textContent)"
        )
        assert rows == ["+ drawing", drawing_id], rows
        _evaluated(call, "document.querySelectorAll('.drawmenu button')[1].click()")
        _until(call, "!!document.querySelector('.drawpopup .excalidraw')")
        assert _until(
            call, f"document.getElementById('upload').textContent === 'editing {drawing_id}'"
        )

        _evaluated(call, "document.querySelector('[data-testid=\"toolbar-diamond\"]').click()")
        _drag(call, 300, 450, 480, 550)
        time.sleep(0.2)

        before_resave = _evaluated(call, "document.querySelector('[name=body]').value")
        _evaluated(call, "document.getElementById('draw-save').click()")
        assert _until(
            call,
            f"document.getElementById('upload').textContent === 'drawings/{drawing_id}.png saved'",
        )
        after_resave = _evaluated(call, "document.querySelector('[name=body]').value")
        assert after_resave == before_resave, (
            "a re-save touched the markdown — the whole reason a drawing lives at a "
            "stable path is that this never has to happen"
        )
        assert after_resave == after_create, "the body moved between the two saves, not just in one"

        resaved_round_trip = _evaluated(call, f"""
        (async () => {{
          const blob = await (await fetch('/drawings/{drawing_id}.png')).blob();
          const loaded = await EXCALIDRAW.loadSceneOrLibraryFromBlob(blob, null, null);
          return {{count: loaded.data.elements.length, types: loaded.data.elements.map(e => e.type)}};
        }})()
        """)
        assert resaved_round_trip == {
            "count": 3, "types": ["rectangle", "ellipse", "diamond"],
        }, resaved_round_trip
        assert not [line for line in said if "Content Security Policy" in line], said


def test_a_stale_save_is_refused_and_the_popup_keeps_the_work(live_server: str, tmp_path: Path):
    """"The loser is refused, in one sentence, and their strokes are gone" —
    from the file. `docs/drawings.md` is explicit that a conflict dialog which
    also throws away the work it refused is the worse of the two losses, so
    this is what "the popup stays open with the work still in it" means asked
    of a real save against a real conflict, not merely inferred from the code.

    An ordinary `httpx` client plays the somebody else: it changes the
    drawing, over the wire, between the moment the popup opens (and captures
    its etag) and the moment Save is pressed against it — the same window a
    second tab or a second person would occupy.
    """
    url = f"{live_server}/detail/{TASK}?editor=plain"
    with _devtools(chrome(), url, tmp_path / "profile") as (call, said):
        time.sleep(2)
        _evaluated(call, "document.getElementById('drawing').click()")
        _evaluated(call, "document.querySelector('.drawmenu button').click()")
        _until(call, "!!document.querySelector('.drawpopup .excalidraw')")
        _evaluated(call, "document.querySelector('[data-testid=\"toolbar-rectangle\"]').click()")
        _drag(call, 300, 300, 480, 430)
        time.sleep(0.2)
        _evaluated(call, "document.getElementById('draw-save').click()")
        assert _until(call, "!document.querySelector('.drawpopup')")

        body = _evaluated(call, "document.querySelector('[name=body]').value")
        drawing_id = re.search(r"draw-[0-9a-f]{6}", body).group(0)

        call("Page.enable")
        call("Page.navigate", {"url": url})
        _until(call, "!!document.getElementById('drawing')")
        _evaluated(call, "document.getElementById('drawing').click()")
        _evaluated(call, "document.querySelectorAll('.drawmenu button')[1].click()")
        _until(call, "!!document.querySelector('.drawpopup .excalidraw')")
        assert _until(
            call, f"document.getElementById('upload').textContent === 'editing {drawing_id}'"
        )

        # Somebody else changes the same drawing from outside this browser,
        # against the very etag the popup just captured.
        current = httpx.get(f"{live_server}/drawings/{drawing_id}.png")
        elsewhere = httpx.put(
            f"{live_server}/api/drawing/{drawing_id}",
            content=PNG + b"someone else's edit entirely",
            headers={"content-type": "image/png", "if-match": current.headers["etag"]},
        )
        assert elsewhere.status_code == 200, elsewhere.text

        _evaluated(call, "document.querySelector('[data-testid=\"toolbar-ellipse\"]').click()")
        _drag(call, 550, 300, 700, 430)
        time.sleep(0.2)
        before = _evaluated(call, "document.querySelector('[name=body]').value")
        _evaluated(call, "document.getElementById('draw-save').click()")

        expected = (
            f"drawings/{drawing_id}.png — somebody changed this drawing while you had it "
            "open, and a drawing has no merge. Reopen it."
        )
        assert _until(
            call, f"document.getElementById('upload').textContent === {expected!r}"
        ), _evaluated(call, "document.getElementById('upload').textContent")
        assert _evaluated(call, "!!document.querySelector('.drawpopup')"), (
            "the popup closed on a refusal — the strokes in it went with it"
        )
        after = _evaluated(call, "document.querySelector('[name=body]').value")
        assert after == before, "a refused save still touched the markdown"

