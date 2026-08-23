"""Notes, and the promotion that stops them being a second inbox nobody empties.

A note is the record for "we are thinking of creating something that does not
exist and our ideas are confused", where an issue is "we found something
existing that is broken". A note is now an `Entity` on a rung with
`planned=False`: what used to be kept true by a separate type — no place on the
table, the graph, the timeline or the people page — is enforced once in
`build_index`, guarded by the Index validator, and swept by the KINDS-derived
exclusion test. This file keeps what is true of notes and of nothing else: the
two-word vocabulary with its derived third state, the stamping the deleted
POST /api/note used to do, and the promotion trail.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, file_at, git_head

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import (
    NOTE_STATES,
    NOTE_STATUS,
    Config,
    Note,
    Task,
    is_bettable,
    load_repo,
    promoted_from,
    shaping_document,
    unread_fields,
    validate_all,
)
from openproj.render import PROMOTABLE
from openproj.web import SESSION_COOKIE, create_app


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


def written(client: TestClient, title: str, base: str, body: str = "", **fields) -> str:
    """A note through the one door every record uses now."""
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "note", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def opened_issue(client: TestClient, title: str, base: str, body: str = "",
                 **fields) -> str:
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "issue", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def promote(client: TestClient, source: str, kind: str, base: str):
    return client.post(
        "/api/promote", json={"source": source, "kind": kind, "base_commit": base}
    )


def entities(**by_id: str) -> dict[str, Task]:
    return {
        i: Task(id=i, kind="task", title=i, status=status) for i, status in by_id.items()
    }


# --------------------------------------------------------------------------- #
# What a note is allowed to be
# --------------------------------------------------------------------------- #


def test_a_note_has_two_statuses_and_the_third_state_is_derived():
    """Four would be an issue's four copied out of habit. There is no
    `in_progress` because nothing works on a note; no `ready` because "ready to be
    shaped" is a promise the Promote button keeps in one press; and no `done`
    because a note is not finished, it is answered — by `promoted`, which is read
    off the link rather than typed beside it."""
    world = entities(**{"pitch-aa0001": "shaping"})
    idea = Note(id="note-000001", kind="note", title="x")
    grown = Note(id="note-000002", kind="note", title="x", became=["pitch-aa0001"])

    assert NOTE_STATUS == ("thinking", "dropped")
    assert set(NOTE_STATES) - set(NOTE_STATUS) == {"promoted"}
    assert "shaping" not in NOTE_STATUS, "a shaped note is a pitch"
    assert idea.state(world) == "thinking"
    assert grown.state(world) == "promoted"


def test_a_promoted_note_does_not_track_what_it_became():
    """Whether that pitch ships is the pitch's business. A note reporting on it
    would be a second copy of the pitch's status, drawn on the one page with no
    reason to carry one — and the two disagree the first time somebody edits
    either end."""
    for status in ("shaping", "ready", "in_progress", "done", "shelved"):
        world = entities(**{"pitch-aa0001": status})
        note = Note(id="note-000001", kind="note", title="x", became=["pitch-aa0001"])

        assert note.state(world) == "promoted", status


def test_dropped_is_a_decision_that_a_link_does_not_reverse():
    """"We thought about this and we are not doing it" was said by a person.
    Somebody linking a record to it afterwards does not un-say it."""
    world = entities(**{"pitch-aa0001": "shaping"})
    dropped = Note(id="note-000001", kind="note", title="x", status="dropped",
                   became=["pitch-aa0001"])

    assert dropped.state(world) == "dropped"


def test_a_link_to_something_that_is_gone_is_a_warning_and_not_a_promotion():
    """A note outlives what it became. `note_problems` is gone; the rule lives
    in `_problems_for` beside every other record's rules, and still names the
    id that went, which is the part a person needs to repair it."""
    note = Note(id="note-000001", kind="note", title="x", became=["pitch-zzzzzz"])

    assert note.state({}) == "thinking"
    assert [(p.severity, p.field) for p in validate_all([note], Config())] == [
        ("warning", "became")
    ]


def test_a_note_reads_no_field_that_is_a_commitment():
    """An owner, a size, an appetite and a cycle are all things somebody agreed
    to, and the claim a note makes is that nobody has agreed to anything. As an
    Entity subclass the note now DECLARES those fields — that is what makes one
    page serve every kind — so the boundary moved from the type to the ladder:
    every one of them is unread on this rung, the editors decline to offer what
    is unread, and a hand edit that writes one in is reported, not obeyed."""
    for field in ("owner", "assignees", "reviewers", "assigned_on", "cycle",
                  "priority", "prs", "depends_on", "person_weeks"):
        assert field in unread_fields("note"), field

    carried = Note(id="note-000001", kind="note", title="x", owner="ann")
    assert any(
        p.field == "owner" and p.severity == "warning"
        for p in validate_all([carried], Config())
    ), "written in by hand, it is reported beside the record"


def test_a_status_that_is_not_one_is_refused_and_says_which_are(
    client: TestClient, repo_path: Path
):
    """`promoted` is a state the ball may stand at and no stop may set — it is
    derived from `became`, and typing it would be a second copy of the link.
    The refusal is the generic per-rung gate now; the sentence still names the
    ladder."""
    note_id = written(client, "x", git_head(repo_path))
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/entity/{note_id}",
        json={"base_commit": before, "fields": {"status": "promoted"}, "body": None},
    )

    assert refused.status_code == 422
    assert "thinking" in refused.text and "dropped" in refused.text
    assert git_head(repo_path) == before, "a refusal writes nothing"


# --------------------------------------------------------------------------- #
# Writing one down
# --------------------------------------------------------------------------- #


def test_writing_a_note_down_asks_for_a_title_and_nothing_else(
    client: TestClient, repo_path: Path
):
    """Somebody is in the middle of thinking. POST /api/note is deleted; the
    generic create stamps its defaults from the per-rung table, so a title is
    still the only thing a person supplies."""
    note_id = written(client, "Is the grid file the thing we cache?", git_head(repo_path))
    stored = file_at(repo_path, git_head(repo_path), f"notes/{note_id}.md")

    assert re.fullmatch(r"note-[0-9a-f]{6}", note_id)
    assert "title: Is the grid file the thing we cache?" in stored
    assert "status: thinking" in stored
    assert f"written_by: {ANN.login}" in stored
    assert re.search(r"written_on: '\d{4}-\d{2}-\d{2}'", stored)
    assert client.post(
        "/api/entity",
        json={"base_commit": git_head(repo_path),
              "fields": {"kind": "note", "title": "  "}},
    ).status_code == 422


def test_a_note_the_server_could_not_read_back_is_never_committed(
    client: TestClient, repo_path: Path
):
    note_id = written(client, "x", git_head(repo_path))
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/entity/{note_id}",
        json={"base_commit": before, "fields": {"tags": "not-a-list"}, "body": None},
    )

    assert refused.status_code == 422
    assert git_head(repo_path) == before


def test_the_retired_note_routes_redirect_to_the_shared_ones(
    client: TestClient, repo_path: Path
):
    note_id = written(client, "x", git_head(repo_path))

    # `/notes` is deliberately not in this list any more: it 301ed to `/` for
    # exactly one release and renders again now, as the landing held to
    # `kind:note` — test_records.py owns that page.
    for old, new in (
        ("/note/new", "/new?kind=note"),
        (f"/note/{note_id}", f"/detail/{note_id}"),
    ):
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 301, old
        assert moved.headers["location"] == new, old


# --------------------------------------------------------------------------- #
# Promotion
# --------------------------------------------------------------------------- #


def test_a_note_promotes_into_a_record_that_validates(client: TestClient, repo_path: Path):
    """`shaping` is the one status whose required-field gate is empty — an idea
    nobody has bet on has no owner and no size by definition — so a promotion
    always produces a record that passes the same validator CI runs, without
    inventing a commitment nobody made."""
    for kind, directory in (("pitch", "pitches"), ("task", "tasks"), ("project", "projects")):
        note_id = written(
            client, f"An idea that becomes a {kind}", git_head(repo_path),
            body="Half a thought.", tags=["grid"],
        )
        response = promote(client, note_id, kind, git_head(repo_path))

        assert response.status_code == 201, response.text
        new_id = response.json()["id"]
        stored = file_at(repo_path, git_head(repo_path), f"{directory}/{new_id}.md")
        assert f"kind: {kind}" in stored
        assert "status: shaping" in stored
        assert f"An idea that becomes a {kind}" in stored, "the title crosses"
        assert "- grid" in stored, "and the tags"
        assert "Half a thought." in stored, "and the body, certainly"
        for commitment in ("owner:", "person_weeks:", "cycle:", "assignees:", "shaped_by:"):
            assert commitment not in stored, commitment

    # Through the validator the CI gate runs, over the whole corpus, so nothing
    # about the promoted records is judged in isolation from what they landed in.
    entities_now, config, unreadable = load_repo_from(repo_path)
    assert not unreadable
    promoted = {e.id for e in entities_now if e.status == "shaping"}
    blockers = [
        p for p in validate_all(entities_now, config)
        if p.severity == "blocker" and p.entity_id in promoted
    ]
    assert promoted and not blockers, blockers


def test_a_promoted_record_says_where_it_came_from_in_its_own_document(
    client: TestClient, repo_path: Path
):
    """"Where did this pitch come from" has to be answerable from the pitch alone.
    Prose and not a field: a `from_note` on `Entity` would put a note id into the
    type every view of the plan is built from."""
    note_id = written(client, "Radiation still calls Fortran", git_head(repo_path))
    new_id = promote(client, note_id, "pitch", git_head(repo_path)).json()["id"]
    stored = file_at(repo_path, git_head(repo_path), f"pitches/{new_id}.md")

    assert f"> Promoted from {note_id} — a note by ann on " in stored
    assert "from_note" not in stored
    # Under the heading a note's text belongs under, with the rest of the team's
    # template below it and empty — which is the true state of a document promoted
    # five seconds ago, and what `_shaping_hints` will say about it.
    assert stored.index("## Problem") < stored.index("## Appetite")
    assert "## Rabbit holes" in stored and "## No-gos" in stored
    # And a reader sees it, rather than it being a comment the renderer strips.
    assert f"Promoted from {note_id}" in client.get(f"/detail/{new_id}").text


def test_the_note_stays_and_points_at_what_it_became(client: TestClient, repo_path: Path):
    """The note is the only record of the thinking that led to the bet. Deleted,
    "where did this come from" is answerable only by somebody who knows to go
    looking for a deletion."""
    note_id = written(client, "An idea", git_head(repo_path))
    new_id = promote(client, note_id, "pitch", git_head(repo_path)).json()["id"]
    note = file_at(repo_path, git_head(repo_path), f"notes/{note_id}.md")

    assert f"- {new_id}" in note
    assert client.get(f"/detail/{note_id}").status_code == 200
    page = client.get(f"/detail/{note_id}").text
    assert "hill-ball hill-promoted" in page, "the read display draws the DERIVED state's ball"
    assert "from what it became" in page, "the lock says why the control is off"


def test_a_promotion_is_one_commit(client: TestClient, repo_path: Path):
    """Two files, one decision. Written as two commits the second can fail after
    the first has landed, leaving a pitch in the plan and a note that does not
    know what it became — on a branch whose protection means the first cannot be
    taken back."""
    note_id = written(client, "An idea", git_head(repo_path))
    before = git_head(repo_path)
    repo = pygit2.Repository(str(repo_path))
    was = len(list(repo.walk(before)))

    new_id = promote(client, note_id, "pitch", before).json()["id"]
    after = git_head(repo_path)

    assert len(list(repo.walk(after))) == was + 1
    assert f"promoted from {note_id}" in repo[after].message
    # Both files, in that one commit: the record is there and the note names it.
    assert file_at(repo_path, after, f"pitches/{new_id}.md")
    assert new_id in file_at(repo_path, after, f"notes/{note_id}.md")
    # And nothing landed in the commit before it, which is what "one commit"
    # means and what a second `store.write` would have quietly broken.
    with pytest.raises(KeyError):
        repo[before].tree[f"pitches/{new_id}.md"]
    assert new_id not in file_at(repo_path, before, f"notes/{note_id}.md")


def test_the_trail_survives_a_round_trip_through_git(client: TestClient, tmp_path: Path,
                                                     repo_path: Path):
    """The point of a git-backed tracker: clone it, and both ends of the link are
    still there with no index, no server and no cache in the way."""
    note_id = written(client, "An idea worth a bet", git_head(repo_path), body="Confused.")
    new_id = promote(client, note_id, "pitch", git_head(repo_path)).json()["id"]

    clone = tmp_path / "clone"
    pygit2.clone_repository(str(repo_path), str(clone))
    entities_now, config, unreadable = load_repo(clone)

    assert not unreadable
    note = next(e for e in entities_now if e.id == note_id)
    pitch = next(e for e in entities_now if e.id == new_id)
    assert note.became == [new_id]
    assert note_id in pitch.body, "and the other end, in the document itself"
    assert "Confused." in pitch.body
    assert note.state({e.id: e for e in entities_now}) == "promoted"


def test_an_issue_promotes_into_a_pitch_or_a_task_and_nothing_else(
    client: TestClient, repo_path: Path
):
    """Two exits, because most of what is in an inbox is not worth a bet.

    This asserted one — "straight to a task would mint a chore nobody pitched" —
    and that argument is about a task UNDER a pitch, which is a piece of somebody
    else's bet. A parentless task is not that: `is_bettable` says one is bet in
    its own right and the betting table draws it beside the pitches. What the old
    rule cost was paid outside this tool: a broken symlink and a one-line fix had
    to be written up with an Appetite, Rabbit holes and No-gos to get out of the
    inbox, or it went round the side of it.

    A project is still refused, and that is the half of the rule worth keeping: a
    project is a container for bets, and "we found something broken" is not a
    milestone.
    """
    opened = opened_issue(client, "Halo drops a rank", git_head(repo_path),
                          body="Reproduced on 12 ranks.")

    refused = promote(client, opened, "project", git_head(repo_path))
    assert refused.status_code == 422
    # Built from `PROMOTABLE` rather than written out, so the sentence a person is
    # refused with cannot go stale the next time that tuple changes.
    assert "an issue becomes pitch or task" in refused.json()["detail"]

    for kind, directory in (("pitch", "pitches"), ("task", "tasks")):
        response = promote(client, opened, kind, git_head(repo_path))
        assert response.status_code == 201, response.text
        new_id = response.json()["id"]
        made = file_at(repo_path, git_head(repo_path), f"{directory}/{new_id}.md")
        issue = file_at(repo_path, git_head(repo_path), f"issues/{opened}.md")

        assert f"kind: {kind}" in made
        assert f"> Promoted from {opened} — an issue by ann on " in made
        assert "Reproduced on 12 ranks." in made
        assert f"- {new_id}" in issue, "pitched_into, which the issue already had"


def test_an_issue_promoted_into_a_task_lands_as_a_task_this_plan_can_read_back(
    client: TestClient, repo_path: Path
):
    """A task wants different things from a pitch, so "it validated as a pitch"
    says nothing about it.

    Two claims, and the second is the one a green route cannot make on its own:
    that the record is a TASK — parentless, which is what makes it a bet in its
    own right rather than an orphan piece of somebody else's — and that the
    validator CI runs finds no blocker on it, asked over the whole corpus it
    landed in rather than over the record alone. A promote path that writes a
    record `openproj check` refuses is a promote path that puts a blocker in the
    plan by pressing a button, on a protected branch.
    """
    opened = opened_issue(client, "Halo drops a rank", git_head(repo_path),
                          body="Reproduced on 12 ranks.", tags=["halo"])

    new_id = promote(client, opened, "task", git_head(repo_path)).json()["id"]
    stored = file_at(repo_path, git_head(repo_path), f"tasks/{new_id}.md")

    assert new_id.startswith("task-")
    assert "kind: task" in stored and "status: shaping" in stored
    assert "Halo drops a rank" in stored, "the title crosses"
    # None of these: an issue has no owner, no size and no cycle to give, and a
    # promotion that invented one would be this tool asserting a commitment
    # nobody made. `parent` is the one that decides what kind of thing this is.
    for commitment in ("owner:", "person_weeks:", "cycle:", "assignees:", "parent:"):
        assert commitment not in stored, commitment

    entities_now, config, unreadable = load_repo_from(repo_path)
    assert not unreadable
    made = next(entity for entity in entities_now if entity.id == new_id)

    assert made.kind == "task" and made.parent is None
    assert is_bettable(made), "which is the state the model already has a word for"
    assert not [
        p for p in validate_all(entities_now, config)
        if p.severity == "blocker" and p.entity_id == new_id
    ]
    # And the trail back, at both ends: the issue names it, and the record says
    # in its own document where it came from.
    issue = next(e for e in entities_now if e.id == opened)
    assert issue.pitched_into == [new_id]
    assert opened in made.body
    assert issue.state({e.id: e for e in entities_now}) == "in_progress", (
        "an issue that has been picked up says so, whichever kind picked it up"
    )


def test_a_source_that_is_not_a_note_or_an_issue_is_refused(client: TestClient, repo_path: Path):
    """The request carries two values and both are closed vocabularies. No path,
    no directory, no file name, no field."""
    base = git_head(repo_path)
    for hostile in ("../config/defaults", "task-c00001", "note-ZZZZZZ", "", "notes/x"):
        response = promote(client, hostile, "pitch", base)
        assert response.status_code in (400, 404), hostile
    assert promote(client, "note-a1b2c3", "pitch", base).status_code == 404, "well-formed, absent"
    note_id = written(client, "x", git_head(repo_path))
    assert promote(client, note_id, "cycle", git_head(repo_path)).status_code == 422
    assert git_head(repo_path) == pygit2.Repository(str(repo_path)).head.target.__str__()


def test_promoting_twice_is_two_records_and_the_note_names_both(
    client: TestClient, repo_path: Path
):
    """`became` is a list because a brainstorm that splits into two pitches is the
    normal case, not a mistake to be guarded against."""
    note_id = written(client, "Two things really", git_head(repo_path))
    first = promote(client, note_id, "pitch", git_head(repo_path)).json()["id"]
    second = promote(client, note_id, "pitch", git_head(repo_path)).json()["id"]
    note = file_at(repo_path, git_head(repo_path), f"notes/{note_id}.md")

    assert first != second
    assert f"- {first}" in note and f"- {second}" in note


def test_the_promote_control_is_not_offered_where_it_cannot_work(
    client: TestClient, repo_path: Path
):
    """A control whose only answer is a refusal is a dead end a person can only
    find by pressing it — the same defect as the cycle page that rendered every
    number and refused every Save."""
    note_id = written(client, "x", git_head(repo_path))

    assert 'id="promote-go"' not in client.get("/new?kind=note").text, (
        "nothing to promote yet"
    )
    assert 'id="promote-go"' in client.get(f"/detail/{note_id}").text
    # Three kinds on a note and two on an issue, each page offering exactly what
    # `PROMOTABLE` says and in its order — the picker used to be a note-only
    # control, because an issue had one destination and a `<select>` holding one
    # option is a control that cannot be used and looks exactly like one that can.
    opened = opened_issue(client, "Something broke", git_head(repo_path))
    for page, expected in (
        (f"/detail/{note_id}", list(PROMOTABLE["note"])),
        (f"/detail/{opened}", list(PROMOTABLE["issue"])),
    ):
        picker = re.search(r'<select id="into">.*?</select>', client.get(page).text, re.S).group(0)
        assert expected == re.findall(r'value="(\w+)"', picker), page

    assert ["pitch", "task", "project"] == list(PROMOTABLE["note"])
    assert ["pitch", "task"] == list(PROMOTABLE["issue"]), (
        "a project is not on offer from an issue: a milestone is a container for "
        "bets, and \"we found something broken\" is not one"
    )

    # And never for a reader. Reads are public, so most served page loads are
    # readers, and `base_commit` alone only says "there is a server" — Promote
    # asks `may_write` like Delete and the view switcher, or its one answer
    # for this person is a 401 dressed as a control. It escaped that sweep
    # because it lived on the two deleted inbox pages when the sweep ran.
    from openproj.render import ROUTES, render_detail

    thought = Note(id="note-0cc000", kind="note", title="A thought", status="thinking")
    index = build_index([thought], Config(), date(2026, 8, 17))
    reader = render_detail(index, ROUTES, only=thought.id,
                           base_commit="deadbee", may_write=False)
    writer = render_detail(index, ROUTES, only=thought.id,
                           base_commit="deadbee", may_write=True)
    assert 'id="promote-go"' not in reader, "a reader was offered a promote they cannot make"
    assert 'id="promote-go"' in writer


# --------------------------------------------------------------------------- #
# The pieces, on their own
# --------------------------------------------------------------------------- #


def test_the_arrival_document_puts_the_note_under_the_first_heading():
    """Split at the SECOND heading, so the note's text lands under the first one
    whatever it says, and a template with one heading or none still works."""
    template = "## Problem\n<!-- guidance -->\n\n## Appetite\n<!-- more -->\n"
    built = shaping_document(template, "> from somewhere.", "The idea.")

    assert built.index("> from somewhere.") < built.index("## Problem")
    assert built.index("<!-- guidance -->") < built.index("The idea.") < built.index("## Appetite")
    assert shaping_document("", "> from somewhere.", "The idea.") == (
        "> from somewhere.\n\nThe idea.\n"
    )
    assert shaping_document("## Only\n", "> cite.", "") == "> cite.\n\n## Only\n"


def test_the_citation_says_what_it_can_and_no_more():
    """A record somebody wrote by hand in git may carry neither a name nor a date,
    and "by None on None" is worse than a shorter line that is true."""
    when = date(2026, 8, 14)

    assert promoted_from("note-a1b2c3", "a note", "ann", when) == (
        "> Promoted from note-a1b2c3 — a note by ann on 2026-08-14."
    )
    assert promoted_from("note-a1b2c3", "a note", "ann", None).endswith("a note by ann.")
    assert promoted_from("note-a1b2c3", "a note", None, when).endswith("written on 2026-08-14.")
    assert promoted_from("note-a1b2c3", "a note", None, None).endswith("a note in this plan.")


def test_the_shipped_demo_carries_notes_that_load(demo_root: Path):
    entities_now, config, unreadable = load_repo(demo_root)
    assert not unreadable

    index = build_index(entities_now, config, date(2026, 8, 17))
    notes = {i: r for i, r in index.records.items() if r.kind == "note"}

    assert notes, "the demo corpus has notes"
    assert not set(notes) & set(index.entities), "and none of them is in the plan"
    assert not [
        p for p in index.problems if p.severity == "blocker" and p.entity_id in notes
    ]
    assert {n.state(index.entities) for n in notes.values()} == set(NOTE_STATES), (
        "all three states, because a demo that shows one teaches one"
    )
    promoted = next(n for n in notes.values() if n.state(index.entities) == "promoted")
    became = index.entities[promoted.became[0]]
    assert promoted.id in became.body, "the trail is drawn at both ends in the demo too"


def test_the_static_export_carries_every_note(demo_root: Path, tmp_path: Path):
    """A note reaches the export three times over — the Records landing, the
    notes view, and detail.html — with no way to write one there, because a
    static file has nowhere to post to."""
    from openproj.render import render_static

    entities_now, config, _ = load_repo(demo_root)
    written_files = render_static(
        build_index(entities_now, config, date(2026, 8, 17)), tmp_path
    )
    detail = (tmp_path / "detail.html").read_text(encoding="utf-8")

    assert "notes.html" in written_files
    assert "note-11aa22" in detail
    assert "note-11aa22" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "note-11aa22" in (tmp_path / "notes.html").read_text(encoding="utf-8")
    assert "promote-go" not in detail


def load_repo_from(repo_path: Path):
    """Everything at HEAD of a bare repository, through a throwaway clone.

    `load_repo` reads a working tree and the store keeps none, which is the whole
    point of it — so a test that wants to ask the CLI's question of a served
    repository has to make one.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        clone = Path(directory) / "clone"
        pygit2.clone_repository(str(repo_path), str(clone))
        return load_repo(clone)
