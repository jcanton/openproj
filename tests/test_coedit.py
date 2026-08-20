"""Two people typing in one shaping document, and the commit it ends in.

Every claim here is asked in the medium where its answer lives. Convergence is
asked of a real socket carrying real Yjs updates. Whether the seed the server
writes is the seed the browser writes is asked of node running the bytes this
repository actually inlines — not of pycrdt alone, which would only prove pycrdt
agrees with itself, and that equality is what the whole restart story rests on.
Degrading is asked of the page's own script with no `WebSocket` in scope, which
is the reader on `file://`, behind a proxy that drops the upgrade, or signed out.

The one claim that cannot be asked here is whether a browser lets the socket
through `connect-src 'self'`. That is a fact about browsers, so it is asked of
Chrome in `test_the_browser_opens_the_socket_under_this_policy` below.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import gc
import json
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

import pygit2
import pytest
from browser import chrome, measured_in
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_injection import run_js
from test_store import commit_directly
from test_web import PATH, SECRET, SEED, TASK, git_head

from openproj import coedit
from openproj import web as web_module
from openproj.auth import User, sign_session
from openproj.index import build_index
from openproj.model import load_repo, split_front_matter
from openproj.render import _yjs
from openproj.store import Store, StoreDiverged, StoreLocked
from openproj.web import (
    MAX_BODY_BYTES,
    MAX_UPDATE_BYTES,
    SESSION_COOKIE,
    create_app,
)

# --------------------------------------------------------------------------- #
# The repository, read without taking the writer's lock
# --------------------------------------------------------------------------- #


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    repo = tmp_path / "plan.git"
    pygit2.init_repository(str(repo), bare=True, initial_head="main")
    commit_directly(repo, SEED, "seed the corpus")
    return repo


@pytest.fixture
def client(plan: Path):
    """Signed out, deliberately.

    Every socket below carries its own session, because dev auth hands an
    unauthenticated request the login `dev` — and a test where both people are
    called `dev` cannot tell an author from a co-author.
    """
    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as made:
        yield made


def stored(plan: Path, path: str = PATH) -> str:
    """The file at the branch tip, read with pygit2 rather than through `Store`.

    `Store.__init__` takes an exclusive flock and the server under test is
    holding it: single-writer is a correctness invariant, so a second `Store` on
    the same repository is a `StoreLocked`, not a reader.
    """
    repo = pygit2.Repository(str(plan))
    tip = repo[repo.references["refs/heads/main"].target]
    return (tip.tree / path).data.decode("utf-8")


def stored_body(plan: Path) -> str:
    return split_front_matter(stored(plan))[1]


def log_of(plan: Path) -> list[tuple[str, str]]:
    """(author, message) for every commit, newest first."""
    repo = pygit2.Repository(str(plan))
    return [
        (one.author.name, one.message)
        for one in repo.walk(repo.references["refs/heads/main"].target)
    ]


# --------------------------------------------------------------------------- #
# A room, driven over a real socket
# --------------------------------------------------------------------------- #


def open_room(client: TestClient, login: str, entity_id: str = TASK):
    """One browser's socket, signed in as this person.

    The session travels as a header rather than on the client, because the point
    of most of these tests is that two sockets are two different people.
    """
    token = sign_session(User(login=login, member=True), SECRET)
    return client.websocket_connect(
        f"/api/coedit/{entity_id}", headers={"cookie": f"{SESSION_COOKIE}={token}"}
    )


class Session:
    """One browser in a room, with a Yjs document made of pycrdt.

    A test client and not a browser: what is under test here is convergence and
    the commit, and both are decided by the update bytes rather than by the DOM.
    The browser's half — that the socket opens at all under this policy — is
    asked of Chrome at the bottom of this file.
    """

    def __init__(self, socket, login: str, seed: str | None = None) -> None:
        self.socket = socket
        self.login = login
        # Never `coedit.SEED`. The seed's client id belongs to the seed, and a
        # second writer sharing it is indistinguishable from it; the page moves
        # off zero for exactly the same reason.
        self.doc = coedit.Doc(client_id=abs(hash(login)) % 100000 + 1)
        self.doc[coedit.BODY] = coedit.Text()
        self.text = self.doc[coedit.BODY]
        self.seed = seed
        self.welcome: dict = {}
        self.heard: list[dict] = []

    def hello(self) -> dict:
        self.socket.send_json(
            {
                "t": "hello",
                "seed": self.seed,
                "sv": base64.b64encode(self.doc.get_state()).decode(),
            }
        )
        message = self.take("welcome", "reload")
        if message["t"] == "welcome":
            self.welcome = message
            self.seed = message["seed"]
            if message["update"]:
                self.doc.apply_update(base64.b64decode(message["update"]))
            self.send(self.doc.get_update(base64.b64decode(message["sv"])))
        return message

    def send(self, update: bytes) -> None:
        self.socket.send_json({"t": "update", "u": base64.b64encode(update).decode()})

    def type(self, at: int, what: str) -> None:
        before = self.doc.get_state()
        self.text.insert(at, what)
        self.send(self.doc.get_update(before))

    def save(self, fields: dict | None = None) -> None:
        self.socket.send_json({"t": "save", "fields": fields or {}})

    def take(self, *kinds: str, most: int = 40) -> dict:
        """The next message of one of these kinds, applying every update on the way."""
        for _ in range(most):
            message = self.socket.receive_json()
            self.heard.append(message)
            if message["t"] == "update":
                self.doc.apply_update(base64.b64decode(message["u"]))
            if message["t"] == "saved" and message["update"]:
                self.doc.apply_update(base64.b64decode(message["update"]))
            if message["t"] in kinds:
                return message
            # A refusal ends the exchange the same way a save does, so waiting
            # past one is waiting for a frame that is never coming — a test that
            # hangs instead of a test that says what the server answered.
            if message["t"] in ("refused", "reload"):
                raise AssertionError(f"{self.login} was refused: {message['why']}")
        raise AssertionError(f"{self.login} never heard {kinds}: {self.heard}")

    def until(self, marker: str, most: int = 40) -> None:
        """Read until this text is in the document.

        The condition is the text and not a frame count: joining a room sends an
        update of its own, so "the next update" is somebody arriving as often as
        it is somebody typing, and a test built on that is a test of whichever
        happened first.
        """
        for _ in range(most):
            if marker in self.body():
                return
            self.take("update", "saved", most=most)
        raise AssertionError(f"{self.login} never saw {marker!r}: {self.heard}")

    def body(self) -> str:
        return str(self.text)


def test_two_sessions_converge_on_the_same_text(client: TestClient):
    """The whole feature, stated as the one property it has to have.

    Ann types at the top and Bo types at the bottom, neither having seen the
    other's keystroke when they made it. A CRDT's promise is that the order the
    updates arrive in cannot change where the characters end up.
    """
    with open_room(client, "ann") as one, open_room(client, "bo") as two:
        ann, bo = Session(one, "ann"), Session(two, "bo")
        ann.hello()
        bo.hello()
        assert ann.body() == bo.body()
        start = ann.body()
        assert start, "the room is seeded from the file, not from an empty document"

        ann.type(0, "ANN AT THE TOP\n")
        bo.type(len(bo.body()), "BO AT THE BOTTOM\n")
        ann.until("BO AT THE BOTTOM")
        bo.until("ANN AT THE TOP")

        assert ann.body() == bo.body()
        assert ann.body() == "ANN AT THE TOP\n" + start + "BO AT THE BOTTOM\n"


def test_a_room_opens_holding_exactly_what_the_page_is_showing(client: TestClient):
    """Or the editor is one character different from the room the moment it opens.

    `parse_text` drops the blank line after the closing `---` and the page
    renders what it returned, so a room seeded from the raw bytes after the
    frontmatter starts out disagreeing with the textarea it is drawn beside — the
    bar says "1 unsaved change" over text nobody has touched, and the quiet
    window commits that character.
    """
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        assert ann.body() == shown


def test_a_second_tab_of_the_same_person_is_one_person(client: TestClient):
    """Presence is a set of people, not a count of sockets."""
    with open_room(client, "ann") as one, open_room(client, "ann") as two:
        first, second = Session(one, "ann"), Session(two, "ann")
        first.hello()
        second.hello()
        assert second.take("who")["people"] == ["ann"]


def test_the_presence_list_names_everybody_in_the_room(client: TestClient):
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        assert ann.take("who")["people"] == ["ann"]
        with open_room(client, "bo") as two:
            Session(two, "bo").hello()
            assert ann.take("who")["people"] == ["ann", "bo"]
        # And says so again when somebody leaves, or the list is a list of
        # everybody who has ever been here.
        assert ann.take("who")["people"] == ["ann"]


def test_a_save_lands_as_one_commit_authored_by_whoever_wrote_the_most(
    client: TestClient, plan: Path
):
    """The author is computed, not declared.

    Ann writes a paragraph and Bo fixes a character in it; Bo presses Save. The
    commit is Ann's, because she wrote it, and Bo is on it because he touched it
    — which is the ordinary shape of two people in one shaping document, and the
    reason this is not simply "whoever pressed the button".
    """
    before = len(log_of(plan))
    with open_room(client, "ann") as one, open_room(client, "bo") as two:
        ann, bo = Session(one, "ann"), Session(two, "bo")
        ann.hello()
        bo.hello()
        ann.type(0, "A whole paragraph typed by ann, which is most of the characters.\n")
        bo.until("typed by ann")
        bo.type(0, "x")
        ann.until("xA whole")

        bo.save()
        saved = bo.take("saved")

    assert saved["outcome"] in ("committed", "retried")
    assert len(log_of(plan)) == before + 1, "one Save is one commit"
    author, message = log_of(plan)[0]
    assert author == "ann", "the author is whoever inserted the most, not whoever pressed Save"
    assert "Co-authored-by: bo <bo@users.noreply.github.com>" in message
    assert message.splitlines()[0] == f"{TASK}: body"
    assert "A whole paragraph typed by ann" in stored_body(plan)


def test_a_save_carries_the_fields_from_the_form_and_the_body_from_the_room(
    client: TestClient, plan: Path
):
    """One commit, not two, and no CRDT deciding what `status` is."""
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "New opening line.\n")
        ann.save({"status": "in_progress"})
        ann.take("saved")

    author, message = log_of(plan)[0]
    assert author == "ann"
    assert message.splitlines()[0] == f"{TASK}: status"
    assert stored_body(plan).startswith("New opening line.\n")
    assert "status: in_progress" in stored(plan)


def test_a_room_will_not_write_somebody_elses_name_into_its_own_trailers(
    client: TestClient, plan: Path
):
    """The room's message was `', '.join(fields)` like every other write path.

    Here it is worse than it is on the PATCH route beside it, because this is the
    branch that makes `Co-authored-by:` mean something: it is how two people
    writing one shaping document both end up on the commit. A field name that can
    add a third is a trail that can be written by anybody who can open the
    editor, and a forgeable trail is worse than none.

    The trailers are read with libgit2's parser rather than matched with a regex,
    because the claim is about what git reads and not about what this file thinks
    a trailer looks like.
    """
    with open_room(client, "ann") as one, open_room(client, "bo") as two:
        ann, bo = Session(one, "ann"), Session(two, "bo")
        ann.hello()
        bo.hello()
        ann.type(0, "a line ann wrote\n")
        bo.until("ann wrote")
        bo.type(0, "x")
        ann.until("xa line")
        bo.save({"notes\n\nCo-authored-by: Mallory <mallory@users.noreply.github.com>": "hi"})
        ann.take("saved")

    written = pygit2.Repository(str(plan))[
        pygit2.Repository(str(plan)).references["refs/heads/main"].target
    ]
    credited = sorted(
        value for name, value in written.message_trailers.items() if name == "Co-authored-by"
    )
    assert credited == ["bo <bo@users.noreply.github.com>"], (
        f"the room credited somebody nobody put in it: {written.message!r}"
    )
    # And the trailers it does write are still there, because a fix that emptied
    # them would pass the line above and lose the feature.
    assert written.author.name == "ann"


def test_the_timer_survives_a_failure_the_tuple_does_not_name(
    client: TestClient, plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """`WRITE_FAILURES` is a five-class denylist, and `_watch` had no try at all.

    So a bare `RuntimeError` out of `store.write` on a tick killed the timer
    task, and a dead timer has exactly one symptom: nothing is committed any
    more, for as long as somebody has the tab open, with `/healthz` answering 200
    throughout. The tuple is right for the failures it can name — "another writer
    has the lock" is a sentence a person can act on — and wrong as the only net.

    A `RuntimeError` and not a subclass of anything named, raised once, and then
    the same room has to commit on a later tick without anybody reconnecting.
    """
    monkeypatch.setattr(coedit, "QUIET_SECONDS", 0.0)
    failed = []
    real = Store.write

    def write(self, **asked):
        if not failed:
            failed.append(asked)
            raise RuntimeError("something nobody has seen before")
        return real(self, **asked)

    monkeypatch.setattr(Store, "write", write)

    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "typed into a room whose write is about to explode\n")
        until(lambda: bool(failed), "the quiet window never tried to write")
        assert len(log_of(plan)) == before, "a failed write commits nothing"
        until(
            lambda: len(log_of(plan)) > before,
            "the quiet window never came back: the timer died on a failure the "
            "tuple did not name, and nothing anywhere said so",
        )
        # `saved` is in the list on purpose. The commit above proves the timer
        # lived; without it here, a version that survived in silence would leave
        # this waiting on a frame that is never coming — a test that hangs
        # instead of a test that says what the server answered.
        why = waited_for(ann, "refused", "saved")
        assert why["t"] == "refused", (
            "a failure nobody had named went past without a word, so the only "
            "thing in front of a person was a save that never happened"
        )
        assert "RuntimeError" in why["why"], (
            f"a failure nobody named still has to be said out loud: {why['why']!r}"
        )
    assert "about to explode" in stored_body(plan)


def test_a_refused_room_tries_again_on_the_next_window(
    client: TestClient, plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """A `StoreLocked` is another writer, which is ordinary and over in a moment.

    Only `Room.apply` cleared `refusal`, and `_watch` would not commit while one
    was set — so a transient refusal stopped the quiet window until somebody
    typed again. A room whose typists had stopped for the evening therefore never
    got its text into git at all, and the design's own promise is a retry on the
    next window. Nobody types here after the refusal: that is the whole test.
    """
    monkeypatch.setattr(coedit, "QUIET_SECONDS", 0.5)
    failed = []
    real = Store.write

    def write(self, **asked):
        if not failed:
            failed.append(asked)
            raise StoreLocked("another writer has the lock")
        return real(self, **asked)

    monkeypatch.setattr(Store, "write", write)

    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "a sentence written just as somebody else took the lock\n")
        until(lambda: bool(failed), "the quiet window never tried to write")
        until(
            lambda: len(log_of(plan)) > before,
            "the room stayed refused until somebody typed again, so a lock held "
            "for one second cost the whole document until the next keystroke",
        )
    assert "just as somebody else took the lock" in stored_body(plan)


def test_a_commit_never_deletes_what_was_typed_during_it_by_construction():
    """The other half of the real-socket test at the bottom of this file.

    That one drives it; this one holds the shape that makes it true. Between the
    snapshot `_commit_room` takes and `room.settled`, there must be no `await` at
    all — an `await` there is a place another socket's handler can put a
    keystroke into the room that `absorb` then takes back out, which is exactly
    how a sentence typed during a save was deleted from every open document and
    from `localStorage` behind it. Read as syntax, because "there happens to be
    no suspension point today" is the kind of claim that is true until somebody
    adds a line, and the test that would notice takes twenty seconds and three
    sockets to run.
    """
    from openproj import web

    tree = ast.parse(Path(web.__file__).read_text(encoding="utf-8"))
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_commit_room"
    ]
    assert len(found) == 1, "there is no _commit_room to read any more"

    snapshot = [
        node.lineno
        for node in ast.walk(found[0])
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "body" for t in node.targets)
    ]
    settled = [
        node.lineno
        for node in ast.walk(found[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "settled"
    ]
    assert snapshot and settled, "the snapshot and the settle have been renamed"
    suspensions = [
        node.lineno
        for node in ast.walk(found[0])
        if isinstance(node, ast.Await) and min(snapshot) < node.lineno < max(settled)
    ]
    assert not suspensions, (
        f"`_commit_room` suspends at line(s) {suspensions} between the snapshot it "
        f"writes (line {min(snapshot)}) and `room.settled` (line {max(settled)}). "
        "Anything typed while it is suspended there is in the room and not in the "
        "snapshot, and is then deleted from every open document by the absorb."
    )


def test_a_save_the_model_could_not_read_back_is_refused_and_writes_nothing(
    client: TestClient, plan: Path
):
    """The same gate the PATCH route stands behind. A record that will not load
    takes every page down for everybody, on a branch where the commit cannot be
    force-pushed away."""
    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "x")
        ann.save({"person_weeks": "a fortnight"})
        refused = ann.take("refused")
        assert "person_weeks" in refused["why"]
        # Inside the room, because leaving it commits the body — which is the
        # right thing to do with text that is only refused as a *field*.
        assert len(log_of(plan)) == before, "a refusal writes nothing"


def test_a_commit_made_in_git_arrives_in_the_room_as_text(client: TestClient, plan: Path):
    """The existing conflict machinery is not regressed, it is fed.

    Somebody edits the same file in git while a room is open. The room's write is
    a compare-and-swap against its own base, so `_merge` folds their change in —
    and what came back is applied into the document, so the room ends up holding
    their paragraph rather than diverging from the file for ever.
    """
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        # `split_front_matter` hands back the block without its closing
        # delimiter *or* the newline before it, while everything that writes a
        # file puts both back — so the newline is this test's to add, and
        # forgetting it produces `prs: []---`, which is one line of frontmatter
        # and a conflict on every save.
        front, body = split_front_matter(stored(plan))
        commit_directly(
            plan,
            {**SEED, PATH: f"---\n{front}\n---\n{body}\nA LINE COMMITTED IN GIT\n"},
            "a person with a terminal",
            author="cy",
        )

        ann.type(0, "A LINE TYPED IN THE ROOM\n")
        ann.save()
        saved = ann.take("saved")
        assert saved["outcome"] == "merged", "a non-overlapping outside edit is a merge"
        assert "A LINE COMMITTED IN GIT" in ann.body(), (
            "their paragraph has to arrive in the room as text, or the next save reverts it"
        )
        assert "A LINE TYPED IN THE ROOM" in ann.body()

    assert "A LINE COMMITTED IN GIT" in stored_body(plan)
    assert "A LINE TYPED IN THE ROOM" in stored_body(plan)


def test_a_commit_made_in_git_arrives_whole_in_a_body_written_in_house_style(
    client: TestClient, plan: Path
):
    """The same fold as the test above, on the body this corpus actually has.

    That one passes on an ASCII record and would pass with the splice computed
    in any index space at all. Put one em dash in the line above the change —
    which is how fifteen of the twenty-one records in `seed/` are written — and
    the fold rewrote the wrong span: the room ended up holding a
    document neither person typed, and committed it twenty seconds later.

    A code-point offset and a UTF-8 byte offset are both ints, so the two spaces
    could be mixed without a word from anything, and the corpus is where the
    difference between them lives.
    """
    front, _ = split_front_matter(stored(plan))
    house = (
        "The artefact shows up on the equator only — and only with two ranks.\n"
        "It is not visible in the serialbox reference data.\n"
    )
    commit_directly(
        plan, {**SEED, PATH: f"---\n{front}\n---\n\n{house}"}, "the way people write", author="ann"
    )

    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        assert ann.body() == house, "the room did not open on the file"

        theirs = house.replace("reference data.", "reference data — yet.")
        commit_directly(
            plan,
            {**SEED, PATH: f"---\n{front}\n---\n\n{theirs}"},
            "a person with a terminal",
            author="cy",
        )

        ann.type(0, "A LINE TYPED IN THE ROOM\n")
        ann.save()
        saved = ann.take("saved")
        assert saved["outcome"] == "merged", "a non-overlapping outside edit is a merge"
        # Whole, and equal — not `in`. The corruption left every marker a
        # substring test would look for still present somewhere in the document.
        assert ann.body() == "A LINE TYPED IN THE ROOM\n" + theirs, (
            f"the room is holding a document nobody typed: {ann.body()!r}"
        )

    assert stored_body(plan).strip() == ("A LINE TYPED IN THE ROOM\n" + theirs).strip()


def test_an_overlap_is_still_the_same_refusal_it_has_always_been(
    client: TestClient, plan: Path
):
    """A genuine overlap comes back as the conflict report, shown to the room and
    never pasted into the editing surface."""
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        # The same line, changed two ways. `_merge_body` refuses an overlap and
        # says what both sides wrote; anything short of the same lines merges,
        # which is the case the test above covers.
        front, body = split_front_matter(stored(plan))
        line = "The artefact shows up on the equator only, and only with two ranks.\n"
        assert line in body
        at = body.index(line)
        commit_directly(
            plan,
            {**SEED, PATH: f"---\n{front}\n---\n" + body.replace(line, "THEIRS\n")},
            "a person with a terminal",
            author="cy",
        )

        before = ann.doc.get_state()
        del ann.text[at : at + len(line) - 1]
        ann.text.insert(at, "MY VERSION OF THAT LINE")
        ann.send(ann.doc.get_update(before))
        ann.save()
        refused = ann.take("refused", "saved")
        assert refused["t"] == "refused", refused

    assert "<<<<<<<" not in refused["why"], "a marker that reaches a textarea is saved back"
    assert "somebody changed this before you" in refused["why"]
    assert "MY VERSION OF THAT LINE" not in stored_body(plan)


def until(true_of_the_world, complaint: str, seconds: float = 12.0) -> None:
    """Poll rather than block, for the claims a broken server answers with silence.

    The failure this exists for is a timer task that died: nothing arrives, so a
    test that waits on a frame waits for ever. A deadline turns that into a
    sentence.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if true_of_the_world():
            return
        time.sleep(0.05)
    raise AssertionError(complaint)


def waited_for(session: Session, *kinds: str, most: int = 40) -> dict:
    """The next frame of one of these kinds, without `take`'s refusal to wait.

    `take` treats `refused` and `reload` as the end of the exchange, which is
    right everywhere it is used and wrong here: these are the tests about what a
    refusal says.
    """
    for _ in range(most):
        message = session.socket.receive_json()
        session.heard.append(message)
        if message["t"] in kinds:
            return message
    raise AssertionError(f"{session.login} never heard {kinds}: {session.heard}")


def test_a_save_with_nothing_to_commit_is_answered(client: TestClient, plan: Path):
    """Or the page never stops saving, and the shell never draws a banner again.

    `COEDIT.save()` always sends `save` and always says "saving…", and this
    answered nothing at all when there was nothing to write: `saving` stayed
    true, `openproj:wrote` never fired, and the shell's counter — which holds
    every "somebody else changed this" until the write it is paired with lands —
    stayed above zero for the life of the page. `onclose` puts it back in five
    minutes on Cloud Run and never on a server with no request deadline.

    The path with no room says "nothing changed" and stops. This is the same
    sentence, said down the socket.
    """
    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.save()
        # And a second Save that certainly does answer, so that a room which has
        # gone quiet fails this test rather than hanging it.
        ann.save({"status": "in_progress"})
        first = waited_for(ann, "nothing", "saving", "saved", "refused")
        assert first["t"] == "nothing", (
            "the first Save was never answered, so the page is still saving"
        )
        ann.take("saved")
    assert len(log_of(plan)) == before + 1, "one of the two Saves had something to write"


def test_the_page_stops_saving_when_the_room_says_there_was_nothing_to_save(
    client: TestClient, plan: Path
):
    """The other half, in the browser, because the jam is the browser's.

    The shell counts `openproj:writing` against `openproj:wrote` and queues every
    banner in between. What matters is not that a frame arrives but that the
    counter comes back to zero when it does — so that is what is read, out of the
    shell's own script, on the page that ships it.
    """
    page = client.get(f"/detail/{TASK}").text
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }
    answer = run_js(
        page,
        "(async () => {"
        "  __socket.opened();"
        f" __socket.hear({json.dumps(welcome)});"
        "  if (!COEDIT.live()) return 'the room never came up';"
        "  await save();"
        "  const saving = movedWriting;"
        "  __socket.hear({t: 'nothing'});"
        "  return saving + ' then ' + movedWriting;"
        "})()",
        page=True,
        socket=True,
    )
    assert not answer["errors"], answer["errors"]
    assert answer["value"] == "1 then 0", (
        "the shell is still holding every banner back, so nobody is told the plan "
        f"moved again for the life of this page: {answer['value']}"
    )


def test_the_last_person_out_commits(client: TestClient, plan: Path):
    """Leaving is a commit, so a room nobody comes back to has already put its
    work in git. The twenty-second window is the floor for a crash, not for
    closing a tab."""
    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "Typed and never saved by hand.\n")
    assert len(log_of(plan)) == before + 1
    assert "Typed and never saved by hand." in stored_body(plan)
    assert log_of(plan)[0][0] == "ann"


def test_a_paste_the_api_would_accept_fits_down_the_socket(client: TestClient, plan: Path):
    """The transport ceiling has to sit above the policy one, or it decides policy.

    `MAX_UPDATE_BYTES` and `MAX_BODY_BYTES` were both 262144, and a Yjs update is
    always larger than the text it carries — so a body that `PATCH` would have
    accepted could never be pasted into a live room. The frame was dropped in
    silence, the quiet window committed the text from before the paste, and
    pasting an export out of HackMD is the migration this whole feature exists
    for.
    """
    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        # An export pasted over the whole document, one byte under the ceiling
        # `PATCH` holds a body to — so this is a body the API would accept.
        paste = "P" * (MAX_BODY_BYTES - 1)
        was = ann.doc.get_state()
        del ann.text[0 : len(ann.body().encode("utf-8"))]
        ann.text.insert(0, paste)
        update = ann.doc.get_update(was)
        assert len(update) > MAX_BODY_BYTES, (
            "the premise of this test: an update is larger than the text in it, so "
            "one ceiling for both is a transport that decides policy"
        )
        assert len(update) <= MAX_UPDATE_BYTES, "and the transport bound has room for it"
        ann.send(update)
        ann.save()
        assert ann.take("saved")["outcome"] in ("committed", "retried")

    assert len(log_of(plan)) == before + 1
    assert stored_body(plan).startswith(paste), "the paste is not what was committed"


def test_a_frame_the_room_cannot_take_is_said_out_loud(client: TestClient):
    """It was dropped with `continue`, which is the worst of the three answers.

    An update the room did not apply is an edit this tab made and the room did
    not, so the two can never converge again — and nothing was sent back: no
    refusal, no reload, nothing. A Save beside it then answered `saved`, moved
    `ORIGINAL_BODY` to the room's stale text and dropped the draft, so the work
    existed in one textarea and died with the tab.
    """
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.socket.send_json(
            {"t": "update", "u": base64.b64encode(b"\x00" * (MAX_UPDATE_BYTES + 1)).decode()}
        )
        # A Save behind it, which is always answered — so a room that says
        # nothing about the frame fails this test instead of hanging it.
        ann.save()
        answer = waited_for(ann, "reload", "refused", "saved", "nothing")
    assert answer["t"] == "reload", answer
    assert "could not take" in answer["why"]
    # And says what still works, because the page it is talking to has the only
    # copy of whatever was just typed.
    assert "Save" in answer["why"]


def test_a_write_that_fails_is_a_refusal_and_not_an_escape(
    client: TestClient, plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """`store.write` raises three things this never caught.

    `StoreLocked` and `StoreDiverged` are `RuntimeError`s and `_commit` goes
    through pygit2, which raises `GitError`; the net was `(HTTPException,
    ValueError)`. An escape took the socket with it here and the timer task in
    `_watch`, which has no try of its own — and a dead timer has one symptom,
    which is that nothing is committed any more.

    Driven with the quiet window set to nothing, so the second half is the timer
    itself: the write fails on the tick, and the tick after it has to still be
    running.
    """
    monkeypatch.setattr(coedit, "QUIET_SECONDS", 0.0)
    failed = []
    real = Store.write

    def write(self, **asked):
        if not failed:
            failed.append(asked)
            raise StoreDiverged("local 1234567 and remote 89abcde have both moved")
        return real(self, **asked)

    monkeypatch.setattr(Store, "write", write)

    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "typed while the remote had moved\n")
        # Waited for in git and not on the socket: a `_watch` that died says
        # nothing at all, and a test that reads a frame it will never be sent
        # hangs instead of failing.
        until(lambda: bool(failed), "the quiet window never tried to write")
        assert len(log_of(plan)) == before, "a failed write commits nothing"

        # The timer has to have survived it. Typing again clears the refusal, so
        # the next quiet window is allowed to try — and this time the write works.
        ann.type(0, "and typed again once it had stopped\n")
        until(
            lambda: len(log_of(plan)) > before,
            "the quiet window never came back: the timer died with the failed write",
        )
        # And the reason reached the room. Read after the fact, from frames that
        # are already queued, so this cannot wait on anything either.
        why = waited_for(ann, "refused")
        assert "have both moved" in why["why"], "the reason has to reach the room"

    assert "typed while the remote had moved" in stored_body(plan)


def test_a_room_whose_record_is_gone_says_to_copy_the_document_out(
    client: TestClient, plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """The refusal is right and the sentence was not.

    A room's text lives in no `localStorage` but the typist's own: everybody
    else's copy arrived over the socket and was never an `input` event, so
    "there is nothing to write this against" with no instruction beside it is a
    message that ends with the document being lost. It repeats every quiet
    window until somebody acts on it, so it has to say what to do.
    """
    monkeypatch.setattr(Store, "read", lambda self, commit, path: None)
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "a paragraph two people wrote\n")
        ann.save()
        why = waited_for(ann, "refused", "saved")
    assert why["t"] == "refused", why
    assert "not in the plan any more" in why["why"]
    assert "Copy the document out of the editor" in why["why"], why["why"]


def test_nothing_reaches_a_socket_before_its_welcome(client: TestClient):
    """A frame that arrives first lands on a document that has not been seeded.

    This socket was in `sockets` from the moment it was accepted, so a second tab
    could be handed somebody else's `update` before its own welcome. The update
    went into an empty document, and the welcome then compared what the room held
    against what the server had rendered into the page — which is the test a
    restored draft is judged by, so a clean merge came back as the conflict
    report instead.

    `cy` is here to make the order a fact rather than a hope: what she has heard
    is proof the server processed ann's keystroke before bo said hello.
    """
    with open_room(client, "ann") as one, open_room(client, "cy") as three:
        ann, cy = Session(one, "ann"), Session(three, "cy")
        ann.hello()
        cy.hello()
        with open_room(client, "bo") as two:
            ann.type(0, "ANN TYPED BEFORE BO SAID HELLO\n")
            cy.until("ANN TYPED BEFORE BO SAID HELLO")

            bo = Session(two, "bo")
            two.send_json({"t": "hello", "seed": None, "sv": None})
            first = two.receive_json()
            assert first["t"] == "welcome", (
                f"bo was handed a {first['t']} before being told what document this is"
            )
            bo.doc.apply_update(base64.b64decode(first["update"]))
            assert "ANN TYPED BEFORE BO SAID HELLO" in bo.body(), (
                "nothing may be lost by waiting: the welcome carries everything the "
                "room had when it was composed"
            )


def test_a_restart_loses_nothing_that_was_committed(plan: Path):
    """The room is a cache. A process that dies takes the room with it and
    nothing else: what was committed is in git, and a client that comes back gets
    a document rebuilt from that commit.

    Two servers over one repository, one at a time — `Store` holds an exclusive
    flock because single-writer is a correctness invariant, so the first one has
    to be collected before the second can open.
    """
    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as first:
        with open_room(first, "ann") as one:
            ann = Session(one, "ann")
            ann.hello()
            ann.type(0, "Committed before the restart.\n")
            ann.save()
            ann.take("saved")
            held = ann.body()
    del first
    gc.collect()

    assert "Committed before the restart." in stored_body(plan)

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as second:
        with open_room(second, "ann") as one:
            back = Session(one, "ann")
            back.hello()
            assert back.body() == held, "the rebuilt room is the text that was committed"


def test_a_reconnection_to_a_room_seeded_at_the_same_commit_is_silent(client: TestClient):
    """Cloud Run closes every socket at five minutes, so reconnection is the
    normal case rather than the exception. A room is kept warm across it, and a
    tab that comes back with the seed it left on is not asked to reload."""
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        ann.type(0, "typed before the socket went\n")
        seed, doc = ann.seed, ann.doc

    with open_room(client, "ann") as one:
        back = Session(one, "ann", seed=seed)
        back.doc, back.text = doc, doc[coedit.BODY]
        answer = back.hello()
    assert answer["t"] == "welcome", answer
    assert "typed before the socket went" in back.body()
    # And exactly once. Two documents built independently from one text merge
    # into that text twice, which is the failure this seed exists to prevent.
    assert back.body().count("typed before the socket went") == 1


def test_a_client_seeded_at_another_commit_is_told_to_reload(client: TestClient):
    """Two documents built independently from the same text share no history and
    merge into that text *twice* — the whole document, doubled, with no conflict
    anywhere. The only honest answer is to start again from the file."""
    with open_room(client, "ann") as one:
        answer = Session(one, "ann", seed="0" * 40).hello()
    assert answer["t"] == "reload"
    assert "reload" in answer["why"]


def test_a_joiner_who_is_told_to_reload_does_not_swallow_a_commit_made_in_git(
    client: TestClient, plan: Path
):
    """The fold a join triggers belongs to the room, not to the joiner.

    `room.absorb(_body_at(head, path))` runs on the join path *before* the hello
    is read and was broadcast after it, so a tab with a stale seed — correctly
    answered `reload` and correctly gone — took a colleague's `git push` with it
    on the way out. Nothing corrects it afterwards: the room is `settled` at that
    commit, so the next write sees `landed == body` and broadcasts nothing, and
    the room quietly commits a line no client has ever been shown. Measured
    before the fix: `in git: True, on ann's screen after a commit: False` — the
    room and the person reading it disagreeing permanently, with nothing said.

    Asked through the save, because that is what makes it permanent rather than
    merely late: the assertion is about ann's *document* after a commit has come
    and gone.
    """
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        front, body = split_front_matter(stored(plan))
        commit_directly(
            plan,
            {**SEED, PATH: f"---\n{front}\n---\n{body}\nA LINE COMMITTED IN GIT\n"},
            "a person with a terminal",
            author="cy",
        )

        # A second tab whose document was built in a process that has since
        # restarted. It is told to reload and goes away, which is right — and the
        # fold its arrival triggered is everybody else's news.
        with open_room(client, "bo") as two:
            assert Session(two, "bo", seed="0" * 40).hello()["t"] == "reload"

        ann.type(0, "A LINE TYPED IN THE ROOM\n")
        ann.save()
        ann.take("saved")
        assert "A LINE COMMITTED IN GIT" in ann.body(), (
            "cy's line is in git and in the room and has never been on ann's screen: "
            "a joiner who was refused took the update that says so with it, and the "
            f"room has since committed a line ann does not have. She holds {ann.body()!r}"
        )
        assert "A LINE TYPED IN THE ROOM" in ann.body()

    assert "A LINE COMMITTED IN GIT" in stored_body(plan)


def test_a_stranger_is_refused_the_socket(plan: Path):
    """And is therefore handed exactly today's editor. Refusal has to be a
    handshake that does not complete rather than a room that quietly does
    nothing, or the page cannot tell that it is on its own."""
    app = create_app(plan, auth="github", secret=SECRET, client_id="x", client_secret="y")
    with TestClient(app) as signed_out:
        with pytest.raises(WebSocketDisconnect):
            with signed_out.websocket_connect(f"/api/coedit/{TASK}"):
                pass


def test_a_socket_re_reads_the_session_it_was_opened_with(
    plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """`writer(socket)` ran once, at the handshake, and never again.

    So a session that stopped being good went on writing commits under that login
    for as long as the tab stayed open. Membership is already baked into the
    cookie for 24 hours on the HTTP side, which is a decision this makes no worse;
    what a socket adds is that it outlives even that, and a laptop left open over
    a weekend is a room committing under a session that expired on Friday.

    Driven with the real signer, the real cookie and the real expiry rule, run
    sooner: `read_session` is asked for a window of two seconds instead of
    twenty-four hours, exactly as `impatient` above asks for a shorter quiet
    window. Nothing about the check is stubbed — the token is genuinely past its
    own timestamp by the time the socket looks again.

    The wait is four seconds against a window of two, and not two and a half,
    because `itsdangerous` stamps and compares whole seconds: an age measured as
    `int(now) - int(then)` over a gap of 2.5s is 2 as often as it is 3, and `2 >
    2` is false. That is a test that passes most of the time, which is worse than
    one that fails.
    """
    import functools

    from openproj import auth as auth_module

    monkeypatch.setattr(web_module, "RECHECK_SECONDS", 0.0)
    monkeypatch.setattr(
        web_module, "read_session", functools.partial(auth_module.read_session, max_age=2)
    )
    app = create_app(plan, auth="github", secret=SECRET, client_id="x", client_secret="y")
    token = sign_session(User(login="ann", member=True), SECRET)
    before = len(log_of(plan))
    with TestClient(app) as signed_in:
        with signed_in.websocket_connect(
            f"/api/coedit/{TASK}", headers={"cookie": f"{SESSION_COOKIE}={token}"}
        ) as socket:
            ann = Session(socket, "ann")
            ann.hello()
            ann.type(0, "typed while the session was still good\n")
            time.sleep(4)
            # The next frame is the one that finds out. Nothing about it is
            # special: the point is that a live socket asks again at all.
            ann.type(0, "typed after it had expired\n")
            answer = waited_for(ann, "reload", "saved")

    assert answer["t"] == "reload", answer
    assert "typed after it had expired" not in stored_body(plan), (
        "a socket went on taking writes under a session that had stopped being "
        f"good. git holds {stored_body(plan)!r}"
    )
    # And what was typed while it *was* good is still committed. Refusing that
    # would answer one way of losing somebody's writing with another: they wrote
    # it, they were signed in, and the room is the only place it exists.
    assert "typed while the session was still good" in stored_body(plan)
    assert len(log_of(plan)) == before + 1


def test_a_room_for_an_entity_that_is_not_there_never_opens(client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with open_room(client, "ann", entity_id="task-ffffff"):
            pass


# --------------------------------------------------------------------------- #
# The attribution, without a socket
# --------------------------------------------------------------------------- #


def test_characters_are_credited_to_the_socket_they_arrived_on():
    """And never to the client id inside the update.

    A client chooses its own id and can write any id it likes into an update, so
    an id read out of a payload is a signature nobody checked. Here Bo sends an
    update whose items claim an id that is not his; the room credits Bo, because
    Bo is whose socket it came in on.
    """
    room = coedit.Room(TASK, PATH, "0" * 40, "start\n")
    forger = coedit.Doc(client_id=4242)
    forger[coedit.BODY] = coedit.Text()
    forger.apply_update(room.doc.get_update())
    forger[coedit.BODY].insert(0, "a forged sentence.\n")

    room.apply(forger.get_update(room.state()), "bo")
    assert room.typed == {"bo": len("a forged sentence.\n")}
    assert room.credits() == ("bo", [])


def test_the_author_is_whoever_inserted_the_most_and_everyone_else_is_credited():
    room = coedit.Room(TASK, PATH, "0" * 40, "")
    for login, many in (("cy", 3), ("ann", 30), ("bo", 10)):
        writer = coedit.Doc(client_id=abs(hash(login)) % 9999 + 1)
        writer[coedit.BODY] = coedit.Text()
        writer.apply_update(room.doc.get_update())
        writer[coedit.BODY].insert(0, "x" * many)
        room.apply(writer.get_update(room.state()), login)
    assert room.credits() == ("ann", ["bo", "cy"])
    # Whoever pressed Save is in the commit having typed nothing: they may have
    # changed a field, and they are the reason it exists.
    assert room.credits(presser="dee") == ("ann", ["bo", "cy", "dee"])
    # And is the author when nobody typed at all.
    assert coedit.Room(TASK, PATH, "0" * 40, "").credits(presser="dee") == ("dee", [])


def test_an_empty_room_is_kept_warm_and_then_dropped():
    """Cloud Run closes every socket at five minutes, so everybody dropping at
    once is the normal case and not a signal that the room is over. Re-seeding in
    that gap would hand every returning tab a document with a different seed, and
    the only honest answer to that is "reload" — a forced page reload every five
    minutes, for a disconnection nobody noticed."""
    rooms = coedit.Rooms()
    room = rooms.add(coedit.Room(TASK, PATH, "0" * 40, "a body\n"))
    rooms.enter(room, 1, "ann")
    assert rooms.sweep() == []
    rooms.exit(room, 1)
    assert rooms.sweep() == [], "an empty room is kept, not dropped"
    assert rooms.get(TASK) is room

    was, coedit.LINGER_SECONDS = coedit.LINGER_SECONDS, 0.0
    try:
        assert rooms.sweep() == [room]
    finally:
        coedit.LINGER_SECONDS = was
    assert rooms.get(TASK) is None


def test_a_room_with_nothing_in_it_has_nobody_to_attribute_a_commit_to():
    room = coedit.Room(TASK, PATH, "0" * 40, "a body\n")
    assert room.credits() == ("", [])
    assert not room.pending()


def test_folding_in_somebody_elses_commit_credits_nobody():
    """It is already attributed, in the commit it came from."""
    room = coedit.Room(TASK, PATH, "0" * 40, "one\ntwo\n")
    assert room.absorb("one\nTWO\nthree\n") is not None
    assert room.body() == "one\nTWO\nthree\n"
    assert room.typed == {}
    assert room.absorb("one\nTWO\nthree\n") is None


def test_absorbing_keeps_the_untouched_half_of_the_document():
    """A minimal splice, so a reader whose caret is in the second half does not
    have it thrown to the end because somebody fixed a typo in the first line."""
    room = coedit.Room(TASK, PATH, "0" * 40, "first\nmiddle\nlast\n")
    before = room.doc.get_state()
    room.absorb("FIRST\nmiddle\nlast\n")
    # The update carries the one line that changed, not the file.
    assert len(room.doc.get_update(before)) < 60


# --------------------------------------------------------------------------- #
# The two index spaces
# --------------------------------------------------------------------------- #


def test_a_string_offset_is_not_a_document_offset():
    """The fact the splice above stands on, stated on its own.

    `pycrdt.Text` is addressed in UTF-8 bytes and a Python string is counted in
    code points, and nothing anywhere raises when the two are swapped. Pinned
    here so that a version of pycrdt that changed its mind about this breaks one
    small test with a name that says what happened, rather than the room.
    """
    doc = coedit.seeded("a—b")
    assert len(str(doc[coedit.BODY])) == 3, "a Python string counts characters"
    assert len(doc[coedit.BODY]) == 5, "the document counts UTF-8 bytes"
    assert [coedit.byte_offset("a—b", at) for at in range(4)] == [0, 1, 4, 5]
    # Empty, an offset past the end, and a character outside the basic plane:
    # the conversion is the whole encoded prefix and has no cases of its own.
    assert coedit.byte_offset("", 0) == 0
    assert coedit.byte_offset("a—b", 99) == 5
    assert coedit.byte_offset("🎉x", 1) == 4


def test_a_body_with_an_em_dash_is_absorbed_exactly():
    """The ordinary record, not a contrived one.

    Em dashes are this corpus's house style — fifteen of the twenty-one records
    in `seed/` carry one — so a body with a character before the splice point is
    the normal case and not the edge. Computing the splice
    in code points and applying it in bytes rewrote the wrong span and appended
    what was left of it to the end of the document, silently, and then the room
    committed it. Reproduced: `contraction-off run.` came back as
    `contraction-oun.` with a stray `un.` at the bottom of the file.

    It compounds, which is the second half of this: the next `absorb` — the one
    a reconnection makes — starts from the mangled text and mangles it again.
    """
    body = (
        "The artefact shows up on the equator only — and only with two ranks.\n"
        "\n"
        "We are still on the contraction-off run.\n"
    )
    room = coedit.Room(TASK, PATH, "0" * 40, body)

    landed = body.replace("contraction-off run.", "contraction-on run.")
    room.absorb(landed)
    assert room.body() == landed, "a fix after an em dash rewrote the wrong span"

    again = landed.replace("two ranks", "two ranks exactly")
    room.absorb(again)
    assert room.body() == again, "and the second absorb mangled what the first left"


def test_absorbing_holds_for_every_shape_of_edit_in_a_body_that_is_not_ascii():
    """Insert, delete, replace and clear, at the top, in the middle and at the
    end, on a body carrying an em dash, an accent, an ellipsis and an emoji.

    A splice is four numbers and a slice, and the defect was visible in exactly
    one of the four combinations, so each is asked rather than the one that
    happened to be reported. The emoji is here because it is the case where the
    two spaces differ by three rather than by two.
    """
    body = "Ann — who ran it — says…\nthe 🎉 case is fine.\nAnd the last line.\n"
    room = coedit.Room(TASK, PATH, "0" * 40, body)
    for landed in (
        "PREPENDED\n" + body,                                    # at the top
        body.replace("the 🎉 case", "the 🎉 CASE"),              # in the middle
        body + "APPENDED\n",                                     # at the end
        body.replace("\nthe 🎉 case is fine.", ""),              # a line taken out
        body.replace("says…", "says… and then said it again"),   # after the ellipsis
        "",                                                      # cleared
        body,                                                    # and back again
    ):
        room.absorb(landed)
        assert room.body() == landed, f"absorbing {landed!r} left {room.body()!r}"


def test_every_index_into_the_document_is_converted():
    """`byte_offset` is the boundary, and this is what keeps it the only one.

    The defect was not that the arithmetic was hard — it was that a Python
    string offset and a document offset are both `int`, so nothing about the
    call site says which one is being handed over and no checker can be asked.
    So the module is read as syntax and every index into the text has to come
    from the conversion by name. Written the way
    `test_no_page_is_assembled_by_substitution` is, and for the same reason: a
    rule a person has to remember is a rule that comes back.
    """
    source = Path(coedit.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    indexes: list[ast.expr] = []
    for node in ast.walk(tree):
        # `del self.text[a:b]`
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and "text" in ast.unparse(target.value):
                    piece = target.slice
                    parts = [piece.lower, piece.upper] if isinstance(piece, ast.Slice) else [piece]
                    indexes.extend(part for part in parts if part is not None)
        # `self.text.insert(at, ...)`, and any sibling of it that grows here.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("insert", "delete")
            and "text" in ast.unparse(node.func.value)
            and node.args
        ):
            indexes.append(node.args[0])

    assert len(indexes) >= 3, "this stopped finding the splice it was written to guard"
    for index in indexes:
        assert (
            isinstance(index, ast.Call)
            and isinstance(index.func, ast.Name)
            and index.func.id == "byte_offset"
        ), (
            f"coedit.py:{index.lineno}: `{ast.unparse(index)}` indexes the document with "
            "something that did not come from `byte_offset`. A Python string offset and a "
            "UTF-8 byte offset are both ints and differ on every body with an em dash in it."
        )


def _document_indexes(script: str) -> list[str]:
    """Every first argument handed to any `.delete(` / `.insert(` in a script.

    A regex finds the call and then the parentheses are balanced by hand, because
    the index is itself a call with a comma in it and `[^,]+` stops in the middle
    of it. There is no JavaScript parser here and adding one would mean npm.

    **The receiver is not named, and that is the widening this needed.** It was
    `\btext\.(?:insert|delete)\(`, which is blind to `ytext.insert`,
    `shared.insert` and `doc.getText('body').insert` — so the one guard holding
    every index into the shared document to `units(` was dodgeable by renaming a
    variable. Measured on the shipped scripts, the two calls below are the only
    `.insert(`/`.delete(` in any of them, so the widening costs nothing today and
    catches the rename it was blind to.
    """
    found = []
    for match in re.finditer(r"\.(?:insert|delete)\(", script):
        depth, at = 0, match.end()
        while at < len(script):
            letter = script[at]
            if letter in "([{":
                depth += 1
            elif letter in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif letter == "," and depth == 0:
                break
            at += 1
        found.append(script[match.end() : at].strip())
    return found


def typed_in_the_page(client: TestClient, shown: str, edits: list[str]) -> coedit.Room:
    """Type each of these into the shipped editor, and hand the room what it sent.

    The page's own script, driven through its own `input` handler, over a socket
    the test moves frame by frame — because the claim is about what the browser
    puts on the wire and what the server's document makes of it, and that
    crosses two implementations. A copy of `typed()` written here would only
    prove this file agrees with itself.
    """
    page = client.get(f"/detail/{TASK}").text
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }
    answer = run_js(
        page,
        "(() => {"
        "  __socket.opened();"
        f" __socket.hear({json.dumps(welcome)});"
        "  const box = document.querySelector('[name=body]');"
        "  const opened = box.value;"
        f" for (const value of {json.dumps(edits)}) {{"
        "    box.value = value;"
        "    box.dispatchEvent(new Event('input'));"
        "  }"
        "  return {opened, sent: __socket.sent()};"
        "})()",
        page=True,
        socket=True,
    )
    assert not answer["errors"], answer["errors"]
    assert answer["value"]["opened"] == shown, (
        "the welcome did not reach the editing surface, so nothing below was driven"
    )
    for frame in answer["value"]["sent"]:
        if frame["t"] == "update":
            room.apply(base64.b64decode(frame["u"]), "ann")
    return room


@pytest.mark.parametrize(
    ("was", "now"),
    [
        # Replacing one emoji with another: they share a leading half, so the
        # common prefix ends *between* the two halves of the pair.
        ("\N{THUMBS UP SIGN} done\n", "\N{THUMBS DOWN SIGN} done\n"),
        # Backspacing the first of two adjacent emoji: both boundaries land
        # inside a pair at once.
        ("\U0001f600\U0001f601 ok\n", "\U0001f601 ok\n"),
        # A flag is two regional indicators, so it is two pairs and the boundary
        # falls inside the second one.
        ("\U0001f1e9\U0001f1ea\n", "\U0001f1e9\U0001f1eb\n"),
        # The two below are the controls, and they are here to say what the case
        # actually is: both have an emoji in them, neither puts a splice boundary
        # inside one, and both passed with the defect in place. A corpus that
        # merely contains an emoji proves nothing — this repository's own
        # mandated footer, edited after the robot rather than through it, is the
        # shape that always worked.
        ("\U0001f916 written by an agent\n", "\U0001f916 written by somebody\n"),
        # And an emoji typed in from the picker, which lands whole between two
        # characters that are not halves of anything.
        ("a fine result\n", "a fine \U0001f389 result\n"),
    ],
)
def test_an_edit_across_an_emoji_reaches_the_room_as_the_character_it_was(
    client: TestClient, plan: Path, was: str, now: str
):
    """The splice the browser makes, asked of the browser and of the room at once.

    `typed()` found the common prefix and suffix a UTF-16 code unit at a time and
    handed those to `Y.Text`, which is counted the same way — so nothing was
    converted and nothing looked wrong. But a character can be two code units,
    and two emoji that share a leading half stop that scan between them: the
    splice then deleted and inserted half a character at each end. A thumb up
    edited to a thumb down left this document holding one thing and the room
    holding another, silently, because a lone surrogate cannot be encoded and
    the update carried a replacement character in its place. Committed twenty
    seconds later, and `PATCH` — which sends the whole body — could never have
    done it, so the socket made emoji strictly worse than no socket at all.

    Asserted as equality on both sides. A substring test would have passed on
    every one of these: the corruption is one character wide.
    """
    front, _ = split_front_matter(stored(plan))
    commit_directly(
        plan, {**SEED, PATH: f"---\n{front}\n---\n\n{was}"}, "a body with an emoji in it"
    )
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert shown == was, "the page is not showing the body this test is about"

    room = typed_in_the_page(client, shown, [now])
    assert room.body() == now, (
        f"the browser typed {now!r} and the room ended up holding {room.body()!r}"
    )


# --------------------------------------------------------------------------- #
# The surface adapter, driven in Chrome against a real room
# --------------------------------------------------------------------------- #
#
# `typed_in_the_page` above drives the page's script under `tests/js/drive.js`,
# which has no layout, no selection and — the reason these tests exist — no HTML
# parser. A `<textarea>`'s value is not the text between its tags: the parser
# folds `\r\n` to `\n` on the way in and the API folds it again on the way out,
# and the shim does neither. So the questions below are asked of Chrome, with a
# real `openproj.coedit.Room` on the other end of a socket that goes nowhere.

# A socket that never leaves the page. Every frame the editor writes is kept for
# the test to hand to the room, and every frame the test wants to deliver goes in
# through `onmessage`, so the two halves are the real ones and only the wire
# between them is not.
#
# `fetch` is stubbed for the same reason every other Chrome test here stubs it:
# a `file://` page cannot reach `/api/preview`, and an editing session opens one.
_ROOM_STUB = """
window.__errors = [];
addEventListener('error', event => window.__errors.push(String(event.message)));
window.fetch = async () => ({ok: true, json: async () => (
  {html: '<p data-startline="1">rendered</p>'})});
window.__sent = [];
function FakeSocket() {
  this.readyState = 1;
  window.__room = this;
  setTimeout(() => { if (this.onopen) this.onopen(); }, 0);
}
FakeSocket.OPEN = 1;
FakeSocket.prototype.send = function (data) { window.__sent.push(JSON.parse(data)); };
FakeSocket.prototype.close = function () { this.readyState = 3; };
window.WebSocket = FakeSocket;
"""


def _welcome(room: coedit.Room) -> dict:
    return {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }


def in_chrome_room(
    client: TestClient,
    where: Path,
    room: coedit.Room,
    welcome: dict,
    script: str,
    editor: str = "",
) -> dict:
    """Open the shipped detail page in Chrome, welcome it into a real room, run
    `script`, and hand everything it sent back to the room.

    The welcome is delivered from inside the question rather than from the stub,
    because it has to arrive after the page's own scripts have run — which is
    exactly the ordering the room's `bound` flag is about. It is built by the
    caller for the same reason: a test that wants somebody else to type has to
    take the snapshot before they do.
    """
    # `editor` goes on the request AND on the file URL, and it has to go on both:
    # the server decides from it whether 594 KB of second editor is in the bytes,
    # and the page decides from `location.search` which surface to mount on them.
    # A test that set only one would be asking a page carrying Ace to run the
    # textarea, which is a configuration nobody ships.
    query = f"?editor={editor}" if editor else ""
    page = client.get(f"/detail/{TASK}{query}").text
    seeded = page.replace(
        '<link rel="icon"', f'<script>{_ROOM_STUB}</script><link rel="icon"', 1
    )
    answer = measured_in(
        chrome(), seeded, where, 1400,
        f"window.__room.onmessage({{data: {json.dumps(json.dumps(welcome))}}});\n" + script,
        budget=8000, query=query,
    )
    assert answer["errors"] == [], f"the page threw: {answer['errors']}"
    for frame in answer.get("sent", []):
        if frame["t"] == "update":
            room.apply(base64.b64decode(frame["u"]), "ann")
    return answer


_TYPED_IN_CHROME = r"""
const area = document.querySelector('textarea[name=body]');
const opened = area.value;
area.value = NEXT;
area.dispatchEvent(new Event('input'));
return {errors: window.__errors, sent: window.__sent, opened, box: area.value};
"""


@pytest.mark.parametrize(
    ("was", "now"),
    [
        # The same five bodies `test_an_edit_across_an_emoji_reaches_the_room_as_
        # the_character_it_was` uses, asked again through the adapter and of a
        # real browser rather than the shim. Two of them are controls that passed
        # with the defect in place, and they are here for the same reason.
        ("\N{THUMBS UP SIGN} done\n", "\N{THUMBS DOWN SIGN} done\n"),
        ("\U0001f600\U0001f601 ok\n", "\U0001f601 ok\n"),
        ("\U0001f1e9\U0001f1ea\n", "\U0001f1e9\U0001f1eb\n"),
        ("\U0001f916 written by an agent\n", "\U0001f916 written by somebody\n"),
        ("a fine result\n", "a fine \U0001f389 result\n"),
    ],
)
def test_an_edit_across_an_emoji_reaches_the_room_through_the_adapter(
    client: TestClient, plan: Path, tmp_path: Path, was: str, now: str
):
    """S6's claim, in one sentence: the same convergence, through the boundary.

    The splice is recovered from a surface's `text()` now rather than from a
    box's `.value`, and it is applied through a `splice(from, to, put)` that is
    specified in UTF-16 code units. Neither of those is allowed to have moved a
    single index, and an emoji is where an index moving is visible: a character
    can be two code units, and two emoji that share a leading half stop a
    unit-at-a-time scan *between* the halves of a surrogate pair.

    Asked in Chrome and not under the shim, because the shim has no HTML parser
    and this stage's whole risk is a surface whose idea of the document differs
    from the page's.
    """
    front, _ = split_front_matter(stored(plan))
    commit_directly(
        plan, {**SEED, PATH: f"---\n{front}\n---\n\n{was}"}, "a body with an emoji in it"
    )
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert shown == was, "the page is not showing the body this test is about"

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "emoji.html", room, _welcome(room),
        _TYPED_IN_CHROME.replace("NEXT", json.dumps(now)),
    )
    assert answer["opened"] == was, (
        "the welcome did not reach the editing surface, so nothing below was driven"
    )
    assert room.body() == now, (
        f"the browser typed {now!r} and the room ended up holding {room.body()!r}"
    )


def test_a_carriage_return_in_a_room_is_a_thing_the_box_cannot_hold(
    client: TestClient, plan: Path, tmp_path: Path
):
    """The case the shim structurally cannot ask, written down as what it is.

    A `\\r` can genuinely be in a room's `Y.Text`: `parse_text` keeps `\\r\\n` in
    the body, `store.py` decodes the blob with no newline translation, and there
    is no `.gitattributes text=auto` — so the room is seeded with the carriage
    returns the file holds and the server's copy has them.

    **The browser's copy cannot.** A `<textarea>` normalises `\\r\\n` to `\\n`
    twice over — once in the HTML parser on the way in and once in the `value`
    getter — so the box holds LF whatever it is given. That is a fact about the
    surface, not about this code, and it is the reason `docs/EDITOR.md` records
    that the two editors this decision keeps normalise in OPPOSITE directions.

    What this pins is that the two copies still CONVERGE, which is the invariant
    that matters: the first thing anybody types makes the room agree with the box
    exactly, carriage returns and all. It is asserted rather than assumed because
    the alternative — the splice recovering a `\\r` at one end and not the other —
    is a document held differently on each side, silently, which is what the
    emoji defect was. The `\\r` going is a change to line endings that shows up in
    a diff; a half-converged document does not.

    **And the cost is written down rather than left to be rediscovered**, because
    it is not free and this stage does not fix it. `reflect()` cannot make the
    box hold a `\\r`, so the two copies stay one character apart for as long as
    nobody types; the moment somebody does, `typed()` finds the common prefix
    ending at the FIRST carriage return and the common suffix ending just after
    the last one, and splices everything between them. On a document whose first
    line ends `\\r\\n` that is one keystroke rewriting the whole body, credited
    to whoever typed it. A textarea normalises unconditionally in both
    directions, so there is nothing to do about it on this side of the wire; the
    fix, if one is wanted, is the server not seeding a room with endings no
    surface can hold.
    """
    front, _ = split_front_matter(stored(plan))
    body = "Ann says\r\nand then\nlast line\r\n"
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "CRLF in the body")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert "\r\n" in shown, "the carriage returns did not survive the parse"

    typed = "Ann says\nand then\nlast line and more\n"
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "crlf.html", room, _welcome(room),
        _TYPED_IN_CHROME.replace("NEXT", json.dumps(typed)),
    )
    assert answer["opened"] == shown.replace("\r\n", "\n"), (
        f"the box did not normalise the endings it was given: {answer['opened']!r}"
    )
    assert room.body() == typed, (
        "the room and the box hold different documents after one keystroke: "
        f"{room.body()!r} against {typed!r}"
    )
    assert "\r" not in room.body(), (
        "a carriage return survived on one side of a surface that cannot hold one"
    )


_REFLECTED = r"""
const area = document.querySelector('textarea[name=body]');
// In an editing session and focused, because that is the tab this is about: a
// reader with the box closed has no caret to lose, and `reflect` deliberately
// leaves an unfocused box alone rather than calling `setSelectionRange` on it,
// which would also scroll it.
document.getElementById('toggle').click();
area.focus();
area.setSelectionRange(2, 2);
const caretWas = area.selectionStart;
const before = window.__sent.filter(frame => frame.t === 'update').length;
window.__room.onmessage({data: JSON.stringify({t: 'update', u: REMOTE})});
const after = window.__sent.filter(frame => frame.t === 'update').length;
// Read here and not at the end: the flag experiment below deliberately takes the
// whole document out and puts it back, which is the one gesture that does move a
// caret, and reading afterwards would be reading about that instead.
const caretNow = area.selectionStart;
const reflected = area.value;

// And the flag, asked directly, because a textarea will never ask it by itself.
// Every other surface fires its change event for its OWN edits and for the
// page's alike — `session.setValue`, `session.replace` and a hand-written delta
// applier all do — so this is that event, made by hand, at the one moment the
// page is writing. Without the flag it reaches `typed()`, which recovers the
// whole document as a local splice and pushes it up the socket under this tab's
// name: measured at 6,700x amplification on a 97,890-character body.
let heard = 0;
SURFACE.onInput(() => heard++);
const outside = SURFACE.applying();
let inside = null;
SURFACE.apply(() => {
  inside = SURFACE.applying();
  const whole = SURFACE.text();
  // What every measured "set the text" actually is, reproduced by hand:
  // remove-all-then-insert-all, TWO change events with an EMPTY DOCUMENT
  // between them. `session.setValue` of a document onto itself measured
  // deleted=1532, inserted=1532, and `session.replace(Range, text)` — the API
  // recommended as "splices in place" — does the same. The first of the two
  // events is the dangerous one: a handler reading the document there sees
  // nothing at all and splices that into the `Y.Text` as a local delete.
  SURFACE.splice(0, whole.length, '');
  area.dispatchEvent(new Event('input'));
  SURFACE.splice(0, 0, whole);
  area.dispatchEvent(new Event('input'));
});
const gated = heard;
const sentUnderApply = window.__sent.filter(frame => frame.t === 'update').length;
// The same event with the flag down, so the gate above is a gate and not a
// subscriber that never fires.
area.dispatchEvent(new Event('input'));
return {
  errors: window.__errors, sent: window.__sent, box: area.value, reflected,
  before, after, caretWas, caretNow,
  outside, inside, restored: SURFACE.applying(), gated, open: heard,
  sentUnderApply, sentAfter: window.__sent.filter(frame => frame.t === 'update').length,
};
"""


def test_somebody_elses_keystroke_is_reflected_and_never_sent_back(
    client: TestClient, plan: Path, tmp_path: Path
):
    """The credit invariant, and the flag that will keep it when the surface changes.

    `Room._count` credits every inserted character to the socket it arrived on,
    and `Room.credits` turns that into "one Save is one commit authored by
    whoever typed the most". It rests entirely on a passive tab staying passive:
    measured on the editor this boundary exists to make possible, one remote
    four-character keystroke reflected as a set-the-text made a tab that had
    typed nothing push 97,890 characters back up the socket and take the
    authorship of the whole document — 6,700x wire amplification, three frames to
    fill `MAX_OUTBOX_BYTES`.

    A textarea cannot do that, because assigning `.value` fires no `input` event.
    That is measured, it is the reason this application has never carried a
    re-entrancy guard, and it is exactly why the guard is added HERE rather than
    with the surface that needs it: a flag introduced alongside the boundary has
    a written reason, and one introduced alongside a bug is a patch.

    So both halves are asked. The room half is the real invariant against a real
    `Room`. The flag half synthesises the change event a textarea will not fire,
    and it is not vacuous: the same event with the flag down does reach the
    subscriber and does put a frame on the wire.
    """
    front, _ = split_front_matter(stored(plan))
    commit_directly(
        plan, {**SEED, PATH: f"---\n{front}\n---\n\nthe body ann is reading\n"}, "a body"
    )
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]

    # Ann's room, and the welcome taken BEFORE anybody else types into it.
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = _welcome(room)

    # Bob's five characters, made in a second copy of the same document — same
    # body, same seed, so the update it produces is one Ann's room and Ann's
    # browser can both apply. Then it is applied to Ann's room as Bob's, which
    # is what the server does when it relays.
    bob = coedit.Room(TASK, PATH, "0" * 40, shown)
    update = bob.absorb(shown.replace("the body", "the long body"))
    assert update, "the second copy produced no update"
    room.apply(update, "bob")

    answer = in_chrome_room(
        client, tmp_path / "reflect.html", room, welcome,
        _REFLECTED.replace("REMOTE", json.dumps(base64.b64encode(update).decode())),
    )

    assert answer["reflected"] == bob.body(), (
        f"the remote keystroke did not reach the box: {answer['reflected']!r}"
    )
    assert answer["after"] == answer["before"], (
        f"a passive tab put {answer['after'] - answer['before']} update frame(s) on the "
        "wire because somebody else typed — that is the credit invariant gone"
    )
    assert answer["caretNow"] == answer["caretWas"], (
        "reflecting somebody else's keystroke moved this tab's caret"
    )
    assert answer["outside"] is False and answer["inside"] is True, (
        f"the flag is not a flag: {answer['outside']} then {answer['inside']}"
    )
    assert answer["restored"] is False, "the flag was left up after `apply` returned"
    assert answer["gated"] == 0, (
        "a change event fired while the page was writing reached the input "
        "subscribers, so a surface that fires one would push the document back"
    )
    assert answer["sentUnderApply"] == answer["after"], (
        "and it reached the room: the empty document between the two change "
        "events went up the socket as a delete of everything, which is the "
        "amplification measured at 6,700x"
    )
    assert answer["box"] == bob.body(), (
        "the page's own write left the box holding something other than the room's text"
    )
    assert room.typed.get("ann", 0) == 0, (
        f"a tab that typed nothing was credited {room.typed.get('ann')} characters — "
        "one Save is one commit authored by whoever typed the most, and this is how "
        "that becomes authored by whoever reflected last"
    )
    assert answer["open"] == 1, (
        "the same event with the flag down reached nobody either, so the "
        "assertion above proves nothing"
    )
    assert room.body() == bob.body(), "the two copies did not converge"


def test_the_browser_splices_on_a_whole_character():
    """`test_every_index_into_the_document_is_converted`, on the other side.

    The same invariant is written twice, once per language, and it was guarded
    once — which is the failure this file's own rule names. A JS string and
    `Y.Text` are both counted in UTF-16 code units while a character can be two
    of them, so an index taken from a code-unit scan is a different index space
    from the characters it was measured against, exactly as a code point offset
    was a different space from a UTF-8 byte.

    So the shipped script is read and every index handed to the document has to
    come from `units` by name.

    **Re-pointed at the surface adapter rather than deleted.** The splice lives
    behind a boundary now, and this test read one module constant — so an adapter
    that took `typed()` with it into another constant would have left the guard
    passing over a file with no splice in it at all. Both constants are read, and
    the count below is what says the splice is still somewhere in them.
    """
    from openproj.render import _ACE_SURFACE, _COEDIT, _COMBOBOX

    shipped = str(_COEDIT) + _COMBOBOX + str(_ACE_SURFACE)
    # Every place that knows what a surface is, so the guard follows the code it
    # guards. If one of these banners moves, this test moves with it rather than
    # quietly passing over a file the splice has left.
    for banner in ("// --- the textarea, as a surface ---", "// --- Ace, as the same surface ---"):
        assert banner in shipped, f"{banner} is in none of the constants this reads"

    # **Two producers of an index now, and each is named with its argument.** The
    # rule has never been "spell it `units(`" — it is "an index handed to the
    # document is in UTF-16 code units, and it got there through one conversion
    # at one boundary". There are two boundaries because there are two surfaces,
    # and they are different shapes:
    #
    # * `units(` is the textarea's. It scans the document a CHARACTER at a time —
    #   it has to, or a splice stops between the halves of a surrogate pair — so
    #   the count it produces is code points and this is what turns it into code
    #   units. It is the browser's `coedit.byte_offset`.
    # * `run.from` is Ace's, and there is nothing to convert. The index came out
    #   of `Document.positionToIndex` inside the Ace surface, which counts code
    #   units already; wrapping it in `units(` would convert a number that is
    #   in the target space into one that is not, which is the defect this test
    #   is named for, spelled the other way round.
    # * `positionOf(` is the same boundary read the other way — `indexToPosition`,
    #   turning a code-unit index back into an Ace `{row, column}` — and it is
    #   here because this scan asks about ANY document, not only the shared one.
    #   The surface's own writes go through it, and an index reaching Ace from a
    #   character count would cut a surrogate pair exactly as one reaching a
    #   `Y.Text` would.
    #
    # So the allowlist is two entries and each one is argued, rather than one
    # entry and a hole. A third would have to be argued here too.
    converts = ("units(", "positionOf(")
    already = {"run.from"}
    indexes = _document_indexes(shipped)
    assert len(indexes) >= 4, "this stopped finding the splices it was written to guard"
    for index in indexes:
        assert index.startswith(converts) or index in already, (
            f"`.insert/.delete({index}, …)` in the shipped editor indexes the document "
            "with something that came from no named conversion. A count of characters and "
            "a count of UTF-16 code units are both numbers, and they differ on every emoji."
        )
    # And the second entry earns its place only while it really is Ace's own
    # index: `run.from` is built in one line, from one call, and this is what
    # says so. A `run.from` computed from `[...text].length` would pass the loop
    # above and be exactly the defect.
    assert "const at = indexOf(delta.start);" in str(_ACE_SURFACE)
    assert "const indexOf = position => document_.positionToIndex(position);" in str(
        _ACE_SURFACE
    ), "the second surface stopped taking its indexes from Ace's own position conversion"


# --------------------------------------------------------------------------- #
# The vendored library
# --------------------------------------------------------------------------- #

DRIVER = Path(__file__).parent / "js" / "yjs-seed.js"


def node_or_skip() -> str:
    found = shutil.which("node")
    if found is None:  # pragma: no cover - depends on the machine, not on the code
        pytest.skip("node is not installed, so the vendored Yjs cannot be run")
    return found


def in_node(asked: dict) -> dict:
    done = subprocess.run(
        [node_or_skip(), str(DRIVER)],
        input=json.dumps({"script": str(_yjs()), "seed": coedit.SEED, **asked}),
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_yjs_bundle_inlines_as_a_classic_script():
    """The one vendored library that cannot be inlined verbatim.

    esm.sh's is the only published artifact with lib0 built in, and it is still a
    module: one `import` at the top, one `export{…}` at the bottom, and a page
    made of inlined `<script>` blocks has no module graph to hand either to. So
    those two lines are rewritten at inline time, and what has to be true of the
    result is that nothing module-shaped survives — a stray `import` is a
    SyntaxError that throws the whole block away, silently, in the console.
    """
    script = str(_yjs())
    assert not re.search(r"(^|[^.\w$])import[\s({]", script), "an import survived the inlining"
    assert not re.search(r"(^|[^.\w$])export[\s{]", script), "an export survived the inlining"
    assert "const YJS = (() => {" in script
    # `YJS` and not `Y`: lib0 uses `Y` for `Array.from` inside the closure, and a
    # second top-level `const` of one name on a page is a SyntaxError for the
    # whole document rather than for one line.
    assert not re.search(r"^const Y = ", script, re.M)
    # And the bytes in git stay upstream's: only those two lines differ.
    source = (Path(__file__).resolve().parents[1] / "static" / "yjs.bundle.mjs").read_text()
    assert len(script) > 90_000 and abs(len(script) - len(source)) < 4000


def test_the_vendored_yjs_and_the_server_write_the_same_seed():
    """Two implementations, one document, byte for byte.

    A room is seeded from a commit's body with a fixed client id, which is what
    makes the seed a pure function of the commit: a server that restarts rebuilds
    the *same* document rather than one that merely reads the same, so a client
    reconnecting into it exchanges state vectors instead of merging two histories
    and inserting the whole file twice. That determinism is pycrdt's alone —
    clients never seed, they are handed the seed — but it is worth nothing if the
    two libraries do not agree about the encoding, and every update in this
    feature crosses between them.

    So the strongest available statement of that agreement: the same operations,
    on both sides, produce identical bytes. Asked of node running the script this
    page actually inlines, because pycrdt agreeing with pycrdt says nothing about
    the browser. Seeding with any other id gives different bytes, which is what
    makes this an assertion rather than a tautology.
    """
    body = "# A shaping document\n\nWith two paragraphs.\n\nAnd a second one.\n"
    theirs = in_node({"body": body})
    ours = base64.b64encode(coedit.seeded(body).get_update()).decode()
    assert theirs["text"] == body
    assert theirs["seed"] == ours, "the browser and the server seed different documents"


def test_the_two_implementations_agree_about_a_body_that_is_not_ascii():
    """The three tests around this one all use ASCII bodies, and that is the gap.

    A Python string is counted in code points, a `pycrdt.Text` in UTF-8 bytes, a
    JS string and a `Y.Text` in UTF-16 code units — four counts that are the same
    number for every character in `one\\ntwo\\n` and different for every character
    that matters here. So the seed equality above proves the two libraries agree
    about ASCII and nothing more, while this corpus is em dashes, ellipses, and
    now the robot this repository signs its own commits with.

    Both directions, because the bytes cross both ways on every keystroke.
    """
    body = "An em dash — a flag \U0001f1e9\U0001f1ea, the robot \U0001f916 and an ellipsis…\n"
    theirs = in_node({"body": body})
    ours = base64.b64encode(coedit.seeded(body).get_update()).decode()
    assert theirs["text"] == body, "the browser did not read back what it was seeded with"
    assert theirs["seed"] == ours, (
        "the browser and the server seed different documents for a body with an "
        "astral character in it, so every update between them is a guess"
    )

    # And an edit made in the browser lands where it was meant to. The offset is
    # written out in UTF-16 code units rather than as `len(body) - 1`, because
    # `Y.Text` is addressed that way and a Python length is not — which is this
    # test's whole subject, and worth stepping on once here rather than in a room.
    before_the_newline = len(body.encode("utf-16-le")) // 2 - 1
    answer = in_node({"body": body, "insert": {"at": before_the_newline, "what": " and more."}})
    server = coedit.seeded(body)
    server.apply_update(base64.b64decode(answer["update"]))
    assert str(server[coedit.BODY]) == body[:-1] + " and more.\n"


def test_an_update_from_the_vendored_yjs_lands_in_the_servers_document():
    """And the bytes go both ways, so the assertion is about the library the page
    ships rather than about the binding the server imports."""
    body = "one\ntwo\n"
    server = coedit.seeded(body)
    answer = in_node({"body": body, "insert": {"at": 0, "what": "typed in the browser\n"}})
    server.apply_update(base64.b64decode(answer["update"]))
    assert str(server[coedit.BODY]) == "typed in the browser\none\ntwo\n"


def test_the_servers_update_lands_in_the_vendored_yjs():
    body = "one\ntwo\n"
    server = coedit.seeded(body)
    server[coedit.BODY].insert(0, "typed on the server\n")
    answer = in_node(
        {"body": body, "apply": base64.b64encode(server.get_update()).decode()}
    )
    assert answer["text"] == "typed on the server\none\ntwo\n"


# --------------------------------------------------------------------------- #
# The harness itself
# --------------------------------------------------------------------------- #


def test_the_parsed_editing_surface_answers_the_body_the_server_rendered(
    client: TestClient, plan: Path
):
    """Is the harness lying? — asked of the one value this feature turns on.

    A `<textarea>`'s value IS its content: there is no `value` attribute to
    reflect, so `drive.js` copying the parsed text into `textContent` alone left
    `.value` answering `''` where a browser answers the record's body. In page
    mode `ORIGINAL_BODY` was therefore always empty, and `ORIGINAL_BODY` is the
    only marker `welcomed()` has of whether anything in the box is unsent work.

    Equality against what the server actually rendered, and with a body carrying
    the characters an escaper rewrites — an apostrophe, an ampersand, angle
    brackets — because the second half of the same lie is that a parser hands
    back `Ann&#39;s note` where a browser hands back `Ann's note`. Both sides of
    that comparison are compared for equality against the room's text, which has
    never been escaped, so an undecoded shim is a shim that reports a conflict
    for every body containing a quote. This corpus's prose is full of them.
    """
    front, _ = split_front_matter(stored(plan))
    body = "Ann's note <b> & \"quoted\" — done.\n"
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "escapes")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert shown == body, "the record under test is not the one the page is showing"

    page = client.get(f"/detail/{TASK}").text
    answer = run_js(page, "document.querySelector('[name=body]').value", page=True)
    assert not answer["errors"], answer["errors"]
    assert answer["value"] == body, (
        "the parsed editing surface answers something a browser does not, so every "
        "page-mode test of this editor was driven against the wrong document"
    )


def test_a_draft_in_the_box_is_offered_to_a_room_that_has_not_moved(client: TestClient):
    """The branch the broken shim made unreachable, driven through the shipped page.

    Three answers hang off `mine`/`theirs` at the welcome, and this is the one
    that keeps somebody's unsaved writing: a draft in the box, a room still
    holding what the server rendered, so there is nothing to reconcile and the
    draft goes up to the room as text. With `.value` answering `''` the page saw
    `mine && theirs` instead — two edits and no common base — and took the
    refusal: the room's copy went into the box and the draft went into the
    conflict report. A harness that can only ever reach the refusal cannot tell
    a working editor from one that throws away every restored draft.
    """
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    page = client.get(f"/detail/{TASK}").text
    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = {
        "t": "welcome",
        "seed": room.seed,
        "base": room.base,
        "you": "ann",
        "sv": base64.b64encode(room.state()).decode(),
        "update": base64.b64encode(room.since(None)).decode(),
    }
    draft = f"A SENTENCE NOBODY HAS SAVED YET\n{shown}"
    answer = run_js(
        page,
        "(() => {"
        "  const box = document.querySelector('[name=body]');"
        f" box.value = {json.dumps(draft)};"
        "  __socket.opened();"
        f" __socket.hear({json.dumps(welcome)});"
        "  const said = document.getElementById('conflict');"
        "  return {box: box.value, refused: !said.hidden, sent: __socket.sent()};"
        "})()",
        page=True,
        socket=True,
    )
    assert not answer["errors"], answer["errors"]
    assert not answer["value"]["refused"], (
        "a draft against a room that has not moved was reported as a conflict"
    )
    assert answer["value"]["box"] == draft, (
        f"the welcome overwrote the draft in the box: {answer['value']['box']!r}"
    )
    for frame in answer["value"]["sent"]:
        if frame["t"] == "update":
            room.apply(base64.b64decode(frame["u"]), "ann")
    assert room.body() == draft, (
        "the draft stayed in the box and never reached the room, so the next commit "
        f"would have written the file back over it. The room holds {room.body()!r}"
    )


# --------------------------------------------------------------------------- #
# The floor: no socket at all
# --------------------------------------------------------------------------- #


def test_the_page_degrades_to_todays_editor_when_the_socket_never_opens(client: TestClient):
    """`file://` has an opaque origin and no server; a proxy may drop the upgrade;
    a reader who may not write is refused the handshake. All three arrive at the
    page as a browser with no room, and the page then has to be exactly what it
    was before any of this existed.

    Driven with no `WebSocket` in scope — which `tests/js/drive.js` deliberately
    does not provide — so this is the shipped script answering, not a flag.
    """
    page = client.get(f"/detail/{TASK}").text
    answer = run_js(
        page,
        "(async () => { document.querySelector('[name=body]').value = 'typed offline\\n';"
        " await save(); return COEDIT.live(); })()",
        page=True,
        # A 409, so the page takes its refusal branch and stops rather than
        # reloading — the request it made on the way is what this test is about.
        replies=[{"status": 409, "json": {"conflict": "scripted, so that save() returns"}}],
    )
    assert not answer["errors"], answer["errors"]
    assert answer["value"] is False
    sent = [call for call in answer["calls"] if "/api/entity/" in call["url"]]
    assert len(sent) == 1, answer["calls"]
    # The body goes over PATCH, against the commit this page was rendered at,
    # exactly as it did before.
    asked = json.loads(sent[0]["body"])
    assert asked["body"] == "typed offline\n"
    assert len(asked["base_commit"]) == 40


def test_the_static_export_carries_no_socket(tmp_path: Path):
    """`openproj render` writes files opened over `file://`, where there is no
    origin to connect to and no server to connect to it. A page that shipped the
    room script would retry a socket to nothing for ever in somebody's console —
    and would ship 93 KB of Yjs in order to do it."""
    from openproj.render import render_static

    root = tmp_path / "corpus"
    root.mkdir()
    for path, content in SEED.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content, encoding="utf-8")
    entities, config, unreadable = load_repo(root)
    index = build_index(entities, config, date(2026, 8, 18), unreadable)

    out = tmp_path / "out"
    for name in render_static(index, out):
        page = (out / name).read_text(encoding="utf-8")
        assert "const YJS" not in page, name
        assert "const COEDIT" not in page, name
        assert "/api/coedit/" not in page, name
        assert "WebSocket" not in page, name


def test_the_served_detail_page_carries_the_room_and_no_other_page_does(client: TestClient):
    """One page has an editor, so one page carries the library."""
    detail = client.get(f"/detail/{TASK}").text
    assert "const YJS = (() => {" in detail
    assert "const COEDIT = (() => {" in detail
    assert "/api/coedit/" in detail
    for route in ("/", "/graph", "/timeline", "/cycles", "/people", "/issues", "/detail"):
        page = client.get(route).text
        assert "const YJS" not in page, route
        assert "/api/coedit/" not in page, route


def test_the_policy_did_not_have_to_move_for_the_socket():
    """`connect-src 'self'` already covers a `ws`/`wss` to this page's own origin
    under CSP 3, so nothing was weakened to make a socket possible. Written down
    because "we had to loosen the CSP a bit" is the sentence this asserts was
    never true; whether a browser agrees is the test below."""
    from openproj.render import CSP

    assert "connect-src 'self'" in CSP
    assert "default-src 'none'" in CSP
    assert "ws:" not in CSP and "wss:" not in CSP


@pytest.fixture
def serving(plan: Path):
    """This application, on a real port, spoken to over real TCP.

    uvicorn and not `TestClient`, because the two facts under test are uvicorn's:
    it answers every upgrade with 403 unless a websocket implementation is
    installed — `pyproject.toml` pinned plain `uvicorn` and `uv.lock` had neither
    `websockets` nor `wsproto` — and the handshake a browser makes is an HTTP
    request that `TestClient` never performs.
    """
    import socket as sockets
    import threading

    import uvicorn

    with sockets.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    app = create_app(plan, auth="dev", secret=SECRET)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the server never came up"
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(10)


# --------------------------------------------------------------------------- #
# One member who stops reading, over real sockets
#
# Everything below needs a real transport and could not be asked any other way.
# `TestClient` speaks ASGI directly: its send never blocks, so a member who
# stops draining is a member who is simply slower, and the whole defect is that
# uvicorn's is not — `WSProtocol.send` begins `await self.writable.wait()`, and
# asyncio clears that event when a transport's buffer fills. A harness with no
# kernel in it cannot have that event, and a suite that only had one reported a
# healthy room for a process that had stopped committing.
# --------------------------------------------------------------------------- #


@pytest.fixture
def impatient(monkeypatch: pytest.MonkeyPatch):
    """The two waits these tests are not about, shortened.

    The claims under test are that the timer still fires and that a member who
    has stopped reading is let go of — not how long either waits. `_watch` reads
    `coedit.QUIET_SECONDS` on every tick and `Outbox.offer` reads
    `STALL_SECONDS` on every frame, so both are the real rules on the real
    server, running sooner.
    """
    monkeypatch.setattr(coedit, "QUIET_SECONDS", 2.0)
    monkeypatch.setattr(web_module, "STALL_SECONDS", 1.0)


def test_a_member_who_is_behind_but_still_reading_is_not_given_up_on(
    monkeypatch: pytest.MonkeyPatch,
):
    """Behind and not draining are different things, and only one is a reason.

    Found with three real tabs, against the first version of this: a byte ceiling
    on its own threw out the tab that was *working*. Applying a burst of
    whole-document updates puts a browser a megabyte behind for a moment, and it
    catches up completely — so a rule written only in bytes evicted the person
    typing beside the person whose laptop was shut, and the room emptied and
    committed nothing. Evicting somebody for being busy is a worse failure than
    the one the queue was written to fix.

    Asked of `Outbox` directly, which is where the rule lives, and with a wire
    that answers so the queue really does go down. The transport half — that one
    member cannot block another at all — is the real-socket test above.
    """
    monkeypatch.setattr(web_module, "STALL_SECONDS", 0.2)

    async def go() -> None:
        sent: list[str] = []

        class Wire:
            async def send_text(self, frame: str) -> None:
                sent.append(frame)

        outbox = web_module.Outbox(Wire())
        posting = asyncio.create_task(outbox.drain())
        big = "x" * (web_module.MAX_OUTBOX_BYTES // 2 + 1)
        try:
            # Twice the ceiling at once: behind, and the clock starts.
            assert outbox.offer(big)
            assert outbox.offer(big)
            assert not outbox.overrun
            # The wire takes them, and then more than a whole stall window
            # passes. A rule that only ever looked at the clock would give up
            # here on somebody who is completely caught up.
            await asyncio.sleep(0.4)
            assert len(sent) == 2, sent
            assert outbox.offer(big)
            assert outbox.offer(big)
            assert not outbox.overrun, (
                "a member who drained everything it was sent was given up on for "
                "having once been behind"
            )
        finally:
            posting.cancel()

    asyncio.run(go())


def test_a_member_who_never_reads_is_given_up_on(monkeypatch: pytest.MonkeyPatch):
    """The other half of the same rule, and the one it was written for.

    Nothing is taken off this wire, so the queue only grows: past the ceiling and
    still past it a stall window later, the member is replaced by a `reload`
    rather than caught up. A Yjs stream is applied in order or not at all, so a
    tab that has missed part of one has nothing useful to be sent."""
    monkeypatch.setattr(web_module, "STALL_SECONDS", 0.2)

    async def go() -> None:
        class Wire:
            async def send_text(self, frame: str) -> None:
                await asyncio.Event().wait()  # a socket that never accepts a write

        outbox = web_module.Outbox(Wire())
        posting = asyncio.create_task(outbox.drain())
        big = "x" * (web_module.MAX_OUTBOX_BYTES // 2 + 1)
        try:
            assert outbox.offer(big)
            assert outbox.offer(big)
            assert outbox.offer(big)
            assert not outbox.overrun, "given up on before the stall window had passed"
            await asyncio.sleep(0.3)
            assert not outbox.offer(big)
            assert outbox.overrun
            # And what is left waiting for them is the one frame that helps.
            assert json.loads(outbox._frames[0])["t"] == "reload"
            assert len(outbox._frames) == 1, "the queue they cannot use was kept"
        finally:
            posting.cancel()

    asyncio.run(go())


class Listening:
    """One member, drained by a thread, so a slow room cannot be mistaken for a
    slow test.

    Every frame is kept as well as queued. `until` consumes from the queue, and a
    version that only queued therefore threw away the frames it walked past — so
    a test that waited for `saved` and then rebuilt this member's document from
    "what arrived" rebuilt it from what arrived *after* the interesting frame,
    and the deletion the whole test is about was never applied to anything.
    """

    def __init__(self, client, name: str) -> None:
        self.client, self.name = client, name
        self.heard: queue.Queue = queue.Queue()
        self.everything: list[dict] = []
        client._socket.settimeout(None)
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        try:
            while True:
                frame = self.client.receive_json()
                self.everything.append(frame)
                self.heard.put(frame)
        except Exception as error:  # noqa: BLE001 - a closed socket ends this thread
            self.heard.put({"t": "!gone", "why": type(error).__name__})

    def until(self, wanted: str, seconds: float = 20.0) -> dict | None:
        """The next frame of this kind, or None if none arrives in time."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                frame = self.heard.get(timeout=0.2)
            except queue.Empty:
                continue
            if frame["t"] == wanted:
                return frame
        return None

    def document(self, doc: coedit.Doc) -> coedit.Doc:
        """This member's document, with everything the room has said applied.

        `saved` carries an update too, and it is the one that matters here: it is
        how a commit puts back into every open document whatever the write
        changed, and how a commit that forced the room to the file deleted
        somebody's sentence out of the screen in front of them.
        """
        for frame in list(self.everything):
            carried = frame.get("u") if frame["t"] == "update" else frame.get("update")
            if carried:
                doc.apply_update(base64.b64decode(carried))
        return doc


def in_the_room(port: int, login: str, **how: object):
    """One real socket, signed in as this person, welcomed."""
    from wsclient import Client

    token = sign_session(User(login=login, member=True), SECRET)
    client = Client(
        "127.0.0.1", port, f"/api/coedit/{TASK}", cookie=f"{SESSION_COOKIE}={token}", **how
    )
    client.send_json({"t": "hello", "seed": None, "sv": None})
    welcome = client.receive_json()
    assert welcome["t"] == "welcome", welcome
    return client, welcome


def a_document_from(welcome: dict, client_id: int) -> coedit.Doc:
    """One participant's Yjs document, seeded from their welcome.

    `client_id` is per person and never shared. Yjs names every character by
    (client, clock), so two documents built with one id are one client that has
    forked: the room already knows that client up to some clock, and the second
    person's insert is silently taken as an item it has already seen. Nothing
    raises, nobody's text arrives, and the test then reports a defect in the
    server that is entirely its own.
    """
    doc = coedit.Doc(client_id=client_id)
    doc[coedit.BODY] = coedit.Text()
    doc.apply_update(base64.b64decode(welcome["update"]))
    return doc


def typing(client, doc: coedit.Doc, text: str, at: int = 0) -> None:
    """Type into this document and put what changed on the wire."""
    before = doc.get_state()
    doc[coedit.BODY].insert(at, text)
    client.send_json({"t": "update", "u": base64.b64encode(doc.get_update(before)).decode()})


def flooding(client, doc: coedit.Doc, frames: int) -> None:
    """Push bytes at everybody else in the room without growing the document.

    One update, then that same update again and again: the server broadcasts
    what it was handed, and a Yjs update that is already applied changes nothing
    when it is applied twice. So this fills a stalled member's pipe with
    megabytes while the room's text — and therefore what a commit would write —
    grows by one line. A flood that grew the document would hit `MAX_BODY_BYTES`
    and the commit under test would be refused for a reason that is not the one
    being asked about.
    """
    before = doc.get_state()
    doc[coedit.BODY].insert(0, "x" * 30000 + "\n")
    frame = {"t": "update", "u": base64.b64encode(doc.get_update(before)).decode()}
    # A send that will not complete is the defect arriving early rather than a
    # broken test: a server suspended in a broadcast has stopped reading *every*
    # socket, so this one fills too. Swallowed here so the assertions below get
    # to say what actually went wrong, in the words of the thing being tested.
    with contextlib.suppress(OSError):
        for _ in range(frames):
            client.send_json(frame)


def test_one_member_who_stops_reading_freezes_nobody(serving: int, plan: Path, impatient):
    """A closed lid must cost that lid and nothing else.

    `_to_room` awaited `socket.send_json` per member in turn, with no timeout and
    no isolation, and uvicorn's send begins `await self.writable.wait()`. So the
    broadcast — and with it every other member's update handler and the `_watch`
    timer, which reaches the same line through `_commit_room` — suspended on
    whoever was slowest. Measured here with three real sockets before the fix:
    once ann's socket stopped accepting writes, cy received **0** further frames,
    the room's commit count stayed where it was, ann's own sentence reached
    neither cy's document nor git, and the last-person-out commit did not fire
    either. `/healthz` and every page answered 200 throughout, so nothing
    anywhere said the room had stopped.

    Ann is a real client on a real socket with a small receive window who simply
    stops calling `recv`. Dave is the one who fills it: the flood has to come
    from somebody the test is finished with, because under the defect the sender's
    own handler is the second thing to seize.
    """
    ann, _ = in_the_room(serving, "ann", receive_buffer=2048)  # and never reads again
    dave, dave_welcome = in_the_room(serving, "dave")
    bo, bo_welcome = in_the_room(serving, "bo")
    cy, cy_welcome = in_the_room(serving, "cy")
    listening = Listening(cy, "cy")
    Listening(bo, "bo")
    dave_doc = a_document_from(dave_welcome, client_id=4)
    bo_doc = a_document_from(bo_welcome, client_id=2)
    cy_doc = a_document_from(cy_welcome, client_id=3)
    was = git_head(plan)

    # Enough to be a whole document behind: `MAX_OUTBOX_BYTES` past whatever the
    # kernel and the transport hold on the way, which is the operating system's
    # number rather than this application's — 664 kB on the machine this was
    # written on, and rather less on a Linux runner, where asking for a small
    # `SO_RCVBUF` switches auto-tuning off instead of being a hint.
    flooding(dave, dave_doc, frames=120)

    # Ann is out. Bo keeps typing while we wait, and that is not decoration: the
    # ceiling starts a clock and it is the *next frame after the stall window*
    # that ends her membership, so a test that stopped broadcasting and then
    # waited would be waiting for a decision nothing is going to ask for.
    for _ in range(60):
        typing(bo, bo_doc, ".")
        time.sleep(0.5)
        roster = [one for one in listening.everything if one["t"] == "who"]
        if roster and "ann" not in roster[-1]["people"]:
            break
    else:  # pragma: no cover - only reached when the fix is not in place
        raise AssertionError(
            f"ann was never dropped, so the room is still waiting on her: "
            f"{[one for one in listening.everything if one['t'] == 'who'][-1:]}"
        )

    # And now the two claims that matter: the others still hear each other, and
    # the room still commits. Cy's own document and not "a frame arrived",
    # because the question is whether bo's sentence reached the person he is
    # writing it with.
    typing(bo, bo_doc, "BO KEPT TYPING\n")
    for _ in range(40):
        if "BO KEPT TYPING" in str(listening.document(cy_doc)[coedit.BODY]):
            break
        time.sleep(0.5)
    assert "BO KEPT TYPING" in str(cy_doc[coedit.BODY]), (
        "bo typed and it never reached cy: one member who stopped reading stopped "
        f"the room. Cy's document holds {str(cy_doc[coedit.BODY])!r}"
    )
    for _ in range(60):
        if git_head(plan) != was:
            break
        time.sleep(0.5)
    assert git_head(plan) != was, (
        "the quiet window never fired: the timer reached the same await the "
        "broadcast did, so a stalled member stopped every commit in the room"
    )
    assert "BO KEPT TYPING" in stored_body(plan), stored_body(plan)

    for one in (ann, dave, bo, cy):
        with contextlib.suppress(Exception):
            one.close()


def test_a_commit_never_deletes_what_was_typed_during_it(serving: int, plan: Path, impatient):
    """The keystroke that lands while a save is in the air.

    `_commit_room` snapshotted `body = room.body()`, then suspended at
    `await _to_room(room, {"t": "saving"})` — the same await as above — wrote the
    snapshot, and then `room.absorb(landed)` forced the room back to the file and
    broadcast that as a deletion. The client's `saved` handler then moved
    `ORIGINAL_BODY` and called `remembered.forget(DRAFT)`, so the `localStorage`
    copy went with it. A sentence typed during a commit was deleted from every
    open document and from the one place it could have been got back.

    Reproduced by forcing that suspension the way a person would: ann stops
    reading and dave fills her pipe, so the broadcast in the middle of bo's save
    genuinely suspends. Cy types into the gap.
    """
    ann, _ = in_the_room(serving, "ann", receive_buffer=2048)
    dave, dave_welcome = in_the_room(serving, "dave")
    bo, bo_welcome = in_the_room(serving, "bo")
    cy, cy_welcome = in_the_room(serving, "cy")
    dave_doc = a_document_from(dave_welcome, client_id=4)
    bo_doc = a_document_from(bo_welcome, client_id=2)
    cy_doc = a_document_from(cy_welcome, client_id=3)
    watching_bo = Listening(bo, "bo")
    listening = Listening(cy, "cy")

    typing(bo, bo_doc, "BO WROTE A PARAGRAPH\n")
    flooding(dave, dave_doc, frames=120)
    time.sleep(1)

    # Bo saves. Under the defect this suspends inside `_commit_room`, holding a
    # snapshot that does not have the next line in it.
    bo.send_json({"t": "save", "fields": {}})
    time.sleep(0.5)
    # And cy types into that gap. `room.apply` runs before the broadcast that
    # blocks, so this keystroke IS in the room while the write is in the air —
    # which is exactly the sentence `absorb` then took back out.
    typing(cy, cy_doc, "CY TYPED THIS DURING THE SAVE\n")

    # Ann starts reading again, so everything that was suspended completes.
    ann._socket.settimeout(2)
    with contextlib.suppress(Exception):
        while True:
            ann.receive_json()

    assert listening.until("saved", seconds=30) is not None, "the save never landed"
    for _ in range(60):
        if "CY TYPED THIS DURING THE SAVE" in stored_body(plan):
            break
        time.sleep(0.5)

    # Both halves of the same loss, because they are not the same claim. The
    # document is what a person is looking at; git is what survives the tab.
    assert "CY TYPED THIS DURING THE SAVE" in str(watching_bo.document(bo_doc)[coedit.BODY]), (
        "the commit broadcast a deletion of a keystroke that landed while it was "
        "running, so it went off somebody else's screen while they were reading it. "
        f"Bo's document holds {str(bo_doc[coedit.BODY])!r}"
    )
    assert "CY TYPED THIS DURING THE SAVE" in str(listening.document(cy_doc)[coedit.BODY]), (
        "a commit deleted a keystroke that landed while it was running, out of the "
        f"document of the person who typed it. It holds {str(cy_doc[coedit.BODY])!r}"
    )
    assert "CY TYPED THIS DURING THE SAVE" in stored_body(plan), (
        "the sentence typed during the save never reached git, so the room believed "
        f"it had committed text it had not. git holds {stored_body(plan)!r}"
    )

    for one in (ann, dave, bo, cy):
        with contextlib.suppress(Exception):
            one.close()


@pytest.fixture
def peak_held(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The most this process ever held for one member, watched from outside.

    `Outbox.offer` on the real server, wrapped rather than replaced: the rule
    under test is the one running, and this only reads the queue it is being
    handed a frame for. Read *before* the call, so the number is the bytes that
    are about to be held including this frame — which is the peak, and is the
    thing that is or is not bounded.

    Nothing else can answer this. The outboxes live in a closure inside
    `create_app` and there is no route that reports them; asking the process for
    its RSS instead would be measuring the allocator as much as the queue.
    """
    peak = {"bytes": 0, "frames": 0}
    real = web_module.Outbox.offer

    def watched(self, frame: str) -> bool:
        holding = self._held + len(frame)
        if holding > peak["bytes"]:
            peak["bytes"], peak["frames"] = holding, len(self._frames) + 1
        return real(self, frame)

    monkeypatch.setattr(web_module.Outbox, "offer", watched)
    return peak


def test_what_is_held_for_a_member_who_never_reads_is_bounded(
    serving: int, plan: Path, peak_held: dict
):
    """The ceiling starts a clock. Something else has to decide what is held.

    Past `MAX_OUTBOX_BYTES` this returned True for *every* frame until
    `STALL_SECONDS` had elapsed, so the queue in front of one wedged member was
    unbounded for the whole stall window — whatever the room could broadcast in
    ten seconds, which is a room, not a constant. Measured against this server
    with one wedged member and one member pasting ordinary documents: **1.3 GB
    queued for one member in 3917 frames**, 1245x the ceiling, and the process
    went from 82 MB RSS to 1519 MB. `gcloud_deploy.sh` runs `--memory 512Mi
    --max-instances 1`, so what round four turned into "the room stops
    committing" this turned into "the process is OOM-killed and every room's
    uncommitted text dies with it" — worse, from the same trigger, and the
    comment above `STALL_SECONDS` stated the bound as a fact.

    Sixty-six megabytes of legitimate frames, which is the volume rather than the
    duration: a test that flooded for ten seconds would measure this machine's
    loopback throughput and would hold a gigabyte on the runner to do it.
    """
    ann, _ = in_the_room(serving, "ann", receive_buffer=2048)  # and never reads again
    dave, dave_welcome = in_the_room(serving, "dave")
    dave_doc = a_document_from(dave_welcome, client_id=4)

    # An ordinary document, pasted — under `MAX_BODY_BYTES`, so nothing here is
    # refused and none of it grows the room's text. This is what somebody working
    # sends, not an attack.
    before = dave_doc.get_state()
    dave_doc[coedit.BODY].insert(0, "x" * 250_000 + "\n")
    frame = {"t": "update", "u": base64.b64encode(dave_doc.get_update(before)).decode()}
    with contextlib.suppress(OSError):
        for _ in range(200):
            dave.send_json(frame)
    time.sleep(2)

    # One frame of slack, because the cap is read after the frame is appended:
    # `MAX_UPDATE_BYTES` of update is about 1.37 MiB of base64 JSON.
    allowed = web_module.MAX_HELD_BYTES + 2 * MAX_UPDATE_BYTES
    assert 0 < peak_held["bytes"] <= allowed, (
        f"one member who stopped reading had {peak_held['bytes']:,} bytes queued for "
        f"them in {peak_held['frames']} frames — "
        f"{peak_held['bytes'] / web_module.MAX_OUTBOX_BYTES:.0f}x the ceiling. The "
        f"ceiling decides when the clock starts, not what is held, so this process "
        f"holds whatever the room broadcasts in a stall window and is OOM-killed on "
        f"512Mi with every room's uncommitted text in it."
    )

    for one in (ann, dave):
        with contextlib.suppress(Exception):
            one.close()


def test_a_room_emptied_by_an_eviction_is_still_committed(
    serving: int, plan: Path, monkeypatch: pytest.MonkeyPatch
):
    """Every route to an empty room commits, including the one nobody's `finally`
    is standing on.

    The leaving member's `finally` asks `room.empty()` and *then* broadcasts the
    roster — and that broadcast is what evicts a member who has stopped reading.
    So the room empties one line after the last-person-out commit was skipped,
    `_watch` fell out of `while room.members:` without committing, and
    `rooms.sweep()` dropped the room seven minutes later with the text still in
    it. Measured here before the fix: nothing was committed at 90 seconds, and
    nothing was ever going to be — uvicorn cannot get a keepalive ping down a
    wedged socket either, so the 40-second ping timeout never fires.

    `QUIET_SECONDS` is left alone deliberately, and bo leaves well inside it: a
    shortened quiet window would commit this on the ordinary timer and the test
    would pass without the fix. Only the eviction clock is shortened, and it is
    still the real rule on the real server.
    """
    monkeypatch.setattr(web_module, "STALL_SECONDS", 1.0)
    ann, _ = in_the_room(serving, "ann", receive_buffer=2048)  # and never reads again
    bo, bo_welcome = in_the_room(serving, "bo")
    bo_doc = a_document_from(bo_welcome, client_id=2)
    was = git_head(plan)

    typing(bo, bo_doc, "BO TYPED THIS AND THEN LEFT\n")
    flooding(bo, bo_doc, frames=150)
    # Past the stall window, so the next frame offered to ann ends her
    # membership — and the next frame offered to ann is the roster that bo's own
    # departure broadcasts, from inside the `finally` that has already decided
    # the room was not empty.
    time.sleep(3)
    bo.close()

    for _ in range(24):
        if git_head(plan) != was:
            break
        time.sleep(0.5)
    assert git_head(plan) != was, (
        "the last typist left, the eviction his departure triggered emptied the "
        "room, and nothing committed it: the text was acknowledged and then "
        "silently discarded"
    )
    assert "BO TYPED THIS AND THEN LEFT" in stored_body(plan), stored_body(plan)

    with contextlib.suppress(Exception):
        ann.close()


def test_a_real_browser_opens_the_socket_under_this_policy_and_draws_the_room(
    serving: int, tmp_path: Path
):
    """The claim CSP 3 makes, asked of Chrome instead of asserted in a comment.

    `connect-src 'self'` is a host-source, and whether it covers `ws://` to the
    same authority is a decision browsers make — one this whole feature stands
    on, and one no Python test can reach. The first attempt at this asked it of a
    `file://` page carrying the same policy, and Chrome refused the socket, by
    directive, in the console: `'self'` cannot match anything from an opaque
    origin. Which is the right answer, and exactly why the static export ships no
    socket at all — but it is not this question.

    So: the real page, from the real server, in a real browser. Bo is already in
    the room over a real connection, so what proves the socket opened is the
    thing on the page that can only be drawn after a welcome — his name, in the
    presence list, beside the editor.
    """
    from browser import chrome, in_a_live_page
    from wsclient import Client

    token = sign_session(User(login="bo", member=True), SECRET)
    with Client("127.0.0.1", serving, f"/api/coedit/{TASK}",
                cookie=f"{SESSION_COOKIE}={token}") as bo:
        bo.send_json({"t": "hello", "seed": None, "sv": None})
        assert bo.receive_json()["t"] == "welcome"

        drawn, said = in_a_live_page(
            chrome(),
            f"http://127.0.0.1:{serving}/detail/{TASK}",
            # The presence list, and the unsaved counter beside it. The second
            # half is not decoration: the room was first seeded from the bytes
            # after the frontmatter while the page renders what `parse_text`
            # returned, which differ by the blank line a closing `---` leaves —
            # so every editor opened saying "1 unsaved change" over text nobody
            # had touched, and committed that character twenty seconds later.
            #
            # Empty until the welcome lands, because this is asked again every
            # quarter second until it answers something — and a version that
            # returned the counter alone was answering truthfully, immediately,
            # about a page that had not connected yet. Idempotent for the same
            # reason: it must not toggle edit mode off again on the second ask.
            "(() => {"
            " const one = document.querySelector('article.entity');"
            " if (!one.classList.contains('editing'))"
            "   document.getElementById('toggle').click();"
            " const who = document.getElementById('together').textContent;"
            " return who"
            "   ? who + ' | ' + document.getElementById('unsaved').textContent : '';"
            "})()",
            tmp_path / "profile",
        )

    assert drawn == "also editing: bo | Nothing changed yet", (
        f"the browser never got a welcome, or got a different document: {drawn!r}, {said}"
    )
    # And said nothing about the policy on the way. A refusal is a console line
    # naming the directive, and nothing else on this page can produce one.
    assert not [line for line in said if "Content Security Policy" in line], said


def test_a_restored_draft_survives_the_welcome_and_is_offered_to_the_room(
    serving: int, tmp_path: Path
):
    """The one thing git cannot get back, asked of the browser that holds it.

    A draft in `localStorage` is somebody's unsaved writing after a crash or a
    closed tab, and the page restores it into the textarea before this script
    runs. Then the welcome arrives carrying the room's whole text, `applyUpdate`
    fires the observer, and an unconditional reflect wrote the room over that
    draft — so `BODY.value !== ORIGINAL_BODY` a line later was reading the value
    it had just been overwritten with, was false, and the branch written for
    exactly this case could never be reached. The draft was gone from the box,
    and gone from `localStorage` at the room's next commit, with nothing said.

    Asked here and not in node, because the sequence is the defect: a stored
    draft, a page load that restores it, and a socket welcome landing on top of
    it. Only a browser has all three, and any harness that stands one of them up
    by hand is a harness that decides the order the bug is about.

    `bo` is in the room first so that the welcome carries a document and a
    presence list — the presence list is what says the welcome has landed, and
    `bo`'s copy of the document is what says the draft was *offered* rather than
    merely left sitting in the box.
    """
    from browser import chrome, in_a_live_page
    from wsclient import Client

    token = sign_session(User(login="bo", member=True), SECRET)
    with Client("127.0.0.1", serving, f"/api/coedit/{TASK}",
                cookie=f"{SESSION_COOKIE}={token}") as bo:
        bo.send_json({"t": "hello", "seed": None, "sv": None})
        welcome = bo.receive_json()
        assert welcome["t"] == "welcome"
        # Bo reads the room the way the page does: a document, not a string.
        his = coedit.Doc(client_id=7)
        his[coedit.BODY] = coedit.Text()
        his.apply_update(base64.b64decode(welcome["update"]))

        mark = "A SENTENCE NOBODY HAS SAVED YET"
        drawn, said = in_a_live_page(
            chrome(),
            f"http://127.0.0.1:{serving}/detail/{TASK}",
            # Two loads in one expression, because a draft has to be in storage
            # *before* the page that restores it starts. The first pass writes
            # one and asks for a reload; `window.__staged` marks the document on
            # its way out, so the poll that lands between the two answers about
            # neither. The second pass waits for the presence list — the one
            # thing on this page that cannot be drawn before a welcome — and
            # then reports what is in the editing surface after it.
            "(() => {"
            "  if (window.__staged) return '';"
            f" const key = 'openproj:draft:2:{TASK}';"
            "  const box = document.querySelector('[name=body]');"
            "  if (!localStorage.getItem(key)) {"
            "    localStorage.setItem(key, JSON.stringify({"
            "      base: document.querySelector('[name=base_commit]').value,"
            f"     text: {mark!r} + '\\n' + box.value}}));"
            "    window.__staged = true;"
            "    setTimeout(() => location.reload(), 0);"
            "    return '';"
            "  }"
            "  if (!document.getElementById('together').textContent) return '';"
            "  return box.value;"
            "})()",
            tmp_path / "profile",
        )

        assert drawn.startswith(mark), (
            "the welcome overwrote a restored draft: somebody's unsaved writing was "
            f"replaced by the room's copy of the file. The box holds {drawn!r}"
        )
        assert not [line for line in said if "Content Security Policy" in line], said

        # And offered, not merely survived. The draft has to reach the room, or
        # the next commit writes the file back over it from the other side.
        for _ in range(60):
            if mark in str(his[coedit.BODY]):
                break
            message = bo.receive_json()
            if message["t"] == "update":
                his.apply_update(base64.b64decode(message["u"]))
        assert mark in str(his[coedit.BODY]), (
            "the draft stayed in the box and never reached the room, so the next "
            "commit would have written the file back over it"
        )


def test_a_draft_against_a_room_that_has_moved_is_reported_and_not_thrown_away(
    serving: int, tmp_path: Path
):
    """The other half of the same branch, which was just as unreachable.

    A draft written offline against a document somebody else has since changed
    has no common base to merge from, so the page refuses to guess: the room's
    text is what goes in the editing surface and the draft goes in the conflict
    report, to be pasted back by the person who wrote it. That branch is chosen
    by the same `mine` the welcome used to overwrite, so it could never be taken
    either — the page fell through to the same silent reflect.

    Bo types before the browser arrives, so the room and the page's rendered
    body genuinely differ. Nothing is committed here: the claim is only about
    what the page does with two edits and no ground between them.
    """
    from browser import chrome, in_a_live_page
    from wsclient import Client

    token = sign_session(User(login="bo", member=True), SECRET)
    with Client("127.0.0.1", serving, f"/api/coedit/{TASK}",
                cookie=f"{SESSION_COOKIE}={token}") as bo:
        bo.send_json({"t": "hello", "seed": None, "sv": None})
        welcome = bo.receive_json()
        assert welcome["t"] == "welcome"
        his = coedit.Doc(client_id=7)
        his[coedit.BODY] = coedit.Text()
        his.apply_update(base64.b64decode(welcome["update"]))
        before = his.get_state()
        his[coedit.BODY].insert(0, "BO WROTE THIS WHILE YOU WERE AWAY\n")
        bo.send_json(
            {"t": "update", "u": base64.b64encode(his.get_update(before)).decode()}
        )

        mark = "MY DRAFT FROM THE TRAIN"
        drawn, said = in_a_live_page(
            chrome(),
            f"http://127.0.0.1:{serving}/detail/{TASK}",
            # Staged and reloaded exactly as above. What is reported is the two
            # surfaces at once, joined, because the point is that they hold
            # different things: the room in the box, the draft in the report.
            "(() => {"
            "  if (window.__staged) return '';"
            f" const key = 'openproj:draft:2:{TASK}';"
            "  const box = document.querySelector('[name=body]');"
            "  if (!localStorage.getItem(key)) {"
            "    localStorage.setItem(key, JSON.stringify({"
            "      base: document.querySelector('[name=base_commit]').value,"
            f"     text: {mark!r} + '\\n' + box.value}}));"
            "    window.__staged = true;"
            "    setTimeout(() => location.reload(), 0);"
            "    return '';"
            "  }"
            "  if (!document.getElementById('together').textContent) return '';"
            "  const said = document.getElementById('conflict');"
            "  if (said.hidden) return '';"
            "  return JSON.stringify({box: box.value, said: said.textContent});"
            "})()",
            tmp_path / "profile",
        )

    answer = json.loads(drawn)
    assert answer["box"].startswith("BO WROTE THIS WHILE YOU WERE AWAY"), (
        f"the box should hold the room, and holds {answer['box']!r}"
    )
    assert mark in answer["said"], (
        f"the draft was neither kept nor reported, only lost: {answer['said']!r}"
    )
    assert mark not in answer["box"], (
        "a draft pasted into the editing surface is a draft somebody saves back "
        "over the document it could not be merged with"
    )
    assert not [line for line in said if "Content Security Policy" in line], said


def test_a_commit_the_room_made_is_not_somebody_else_changing_it(client):
    """The banner that says "this was just changed by somebody else", over a
    document that had just been synced letter by letter.

    Every commit comes back down `/api/events`, including the ones this tab
    caused — the shell already knows that and keeps a set of its own. What it did
    not know is that a commit made by SOMEBODY ELSE in your co-editing room is
    also not news: the text it holds is in the box in front of you already, which
    is the whole of what a room is. Reported by jcanton from the deployed
    service, where two people were editing one document.

    Asked of the source, because the claim is about which listener hears which
    event: driving it would need two browsers, a real socket and a real stream,
    and `tests/test_coedit.py`'s live fixture proves the socket rather than the
    banner.
    """
    page_for_one = client.get(f"/detail/{TASK}").text
    assert "addEventListener('openproj:ours'" in page_for_one, (
        "the shell does not listen for the room's own commits"
    )
    assert "dispatchEvent(new CustomEvent('openproj:ours'" in page_for_one, (
        "the room does not tell the shell about the commit it just made"
    )
    # And it is not `openproj:wrote`, which every tab in the room would then owe
    # the counter — only the one that pressed Save owes that.
    room = page_for_one.split("if (message.t === 'saved')")[1].split("if (message.t ===")[0]
    assert "openproj:ours" in room
    assert "openproj:wrote" not in room, (
        "every tab in the room answers a writing that only one of them started"
    )


# --------------------------------------------------------------------------- #
# Where everybody is
# --------------------------------------------------------------------------- #


def test_the_room_relays_where_each_person_is_sitting(client: TestClient):
    """Presence was a list of names. A name says somebody else is in the
    document; it does not say which paragraph they are in, and in a shaping
    document that is the thing you need in order not to rewrite the sentence
    somebody is halfway through.

    The number is an index into the text and this server never reads it — it
    carries it. The two ends that use it are both browsers and they already agree
    on what it counts: UTF-16 code units, which is what `selectionStart` counts
    and what a Yjs text is made of in a browser. Converting here would be a third
    index space in the one module whose note is about exactly that mistake.
    """
    with open_room(client, "ann") as one, open_room(client, "bo") as two:
        ann, bo = Session(one, "ann"), Session(two, "bo")
        ann.hello()
        bo.hello()
        one.send_json({"t": "at", "at": 421})
        heard = bo.take("who")
        while not heard["where"]:
            heard = bo.take("who")

    assert heard["people"] == ["ann", "bo"]
    assert heard["where"] == [{"login": "ann", "at": 421}]


def test_a_seat_goes_when_its_person_does(client: TestClient):
    """A band drawn for somebody who closed the tab is a colour under a name that
    is no longer in the list beside it."""
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        with open_room(client, "bo") as two:
            bo = Session(two, "bo")
            bo.hello()
            two.send_json({"t": "at", "at": 12})
            heard = ann.take("who")
            while not heard["where"]:
                heard = ann.take("who")
            assert heard["where"] == [{"login": "bo", "at": 12}]

        left = ann.take("who")

    assert left["people"] == ["ann"]
    assert left["where"] == [], "the room kept a seat for somebody who has gone"


def test_a_seat_that_is_not_a_number_is_not_a_seat(client: TestClient):
    """It arrives off a socket and is drawn into a position: a float would be a
    NaN in somebody else's arithmetic and an unbounded one is a band measured a
    million lines down. Neither closes the socket — this is presence, and a
    malformed frame about where somebody is sitting is not a reason to throw
    them out of the document."""
    with open_room(client, "ann") as one, open_room(client, "bo") as two:
        ann, bo = Session(one, "ann"), Session(two, "bo")
        ann.hello()
        bo.hello()
        for nonsense in ({"t": "at", "at": "here"}, {"t": "at", "at": -3},
                         {"t": "at", "at": 10 ** 9}, {"t": "at"}):
            one.send_json(nonsense)
        # Still a room, still speaking: a real seat after the nonsense arrives.
        one.send_json({"t": "at", "at": 7})
        heard = bo.take("who")
        while not heard["where"]:
            heard = bo.take("who")

    assert heard["where"] == [{"login": "ann", "at": 7}]


# --- the second surface, in a real room -------------------------------------
#
# Everything below drives Ace rather than the box, against the same real
# `openproj.coedit.Room` the tests above use. It is asked of Chrome because an
# editor is layout, selection and key handling, and `tests/js/drive.js` has no
# HTML parser, no Ace and no way to tell either of those from a string.

_ACE_RETYPED = r"""
const editor = SURFACE.editor;
const opened = SURFACE.text();
// The smallest edit that turns one into the other, selected and retyped —
// which is what a person does, and which is where an index in the wrong space
// shows: `[...text]` walks CHARACTERS and the surface counts UTF-16 CODE UNITS,
// so a boundary computed in one and applied in the other lands between the two
// halves of a surrogate pair.
const was = [...opened], now = [...NEXT];
let head = 0;
while (head < was.length && head < now.length && was[head] === now[head]) head++;
let tail = 0;
while (tail < was.length - head && tail < now.length - head
       && was[was.length - 1 - tail] === now[now.length - 1 - tail]) tail++;
const units = (chars, at) => chars.slice(0, at).join('').length;
SURFACE.setCaret(units(was, head), units(was, was.length - tail));
const put = now.slice(head, now.length - tail).join('');
// Ace's own editing commands and not the surface's `splice`, so the delta the
// binding consumes is one Ace made rather than one this test made.
if (put) editor.insert(put); else editor.remove('left');
await new Promise(r => setTimeout(r, 60));
return {errors: window.__errors, sent: window.__sent, opened, box: SURFACE.text(),
        surface: SURFACE.onSplice ? 'ace' : 'textarea'};
"""


@pytest.mark.parametrize(
    ("was", "now"),
    [
        # The same five bodies, a third time: once under the shim, once through
        # the adapter in Chrome over a textarea, and now through Ace. Two of them
        # are controls that passed with the original defect in place and they are
        # here for exactly that reason — a corpus without the one string that
        # matters proves nothing, and "has an emoji in it" is not that string.
        ("\N{THUMBS UP SIGN} done\n", "\N{THUMBS DOWN SIGN} done\n"),
        ("\U0001f600\U0001f601 ok\n", "\U0001f601 ok\n"),
        ("\U0001f1e9\U0001f1ea\n", "\U0001f1e9\U0001f1eb\n"),
        ("\U0001f916 written by an agent\n", "\U0001f916 written by somebody\n"),
        ("a fine result\n", "a fine \U0001f389 result\n"),
    ],
)
def test_an_edit_in_the_second_surface_reaches_the_room_as_the_character_it_was(
    client: TestClient, plan: Path, tmp_path: Path, was: str, now: str
):
    """The gating case for the second editor, and it is the case this repository
    already knows catches the defect rather than the one that sounds like it.

    Ace's `positionToIndex` counts UTF-16 code units and its clamping is
    EMERGENT — it falls out of `moveCursorBy`'s screen-coordinate round trip and
    not out of any guard, so `indexToPosition(1)` on a leading emoji answers
    `{row: 0, column: 1}`, unclipped, between the halves of a surrogate pair.
    Nothing in `Document`, `Anchor` or `applyDelta` clips. So the binding's whole
    correctness rests on every index it hands the `Y.Text` having been produced
    by Ace's own delta rather than by arithmetic over characters.
    """
    front, _ = split_front_matter(stored(plan))
    commit_directly(
        plan, {**SEED, PATH: f"---\n{front}\n---\n\n{was}"}, "a body with an emoji in it"
    )
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert shown == was, "the page is not showing the body this test is about"

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "ace-emoji.html", room, _welcome(room),
        _ACE_RETYPED.replace("NEXT", json.dumps(now)), editor="ace",
    )
    assert answer["surface"] == "ace", "the page mounted the box, so nothing here was driven"
    assert answer["opened"] == was, (
        "the welcome did not reach the second surface, so nothing below was driven"
    )
    assert answer["box"] == now, f"Ace ended up holding {answer['box']!r}"
    assert room.body() == now, (
        f"Ace typed {now!r} and the room ended up holding {room.body()!r}"
    )


_ACE_BACKSPACED = r"""
const editor = SURFACE.editor;
const opened = SURFACE.text();
// The caret immediately after the last character of the first line, and then
// Ace's own backspace — an EMPTY selection, so how much comes out is Ace's
// decision and not this test's. That is the point: the clamping is emergent.
const firstLine = opened.split('\n')[0];
SURFACE.setCaret(firstLine.length);
editor.remove('left');
await new Promise(r => setTimeout(r, 60));
return {errors: window.__errors, sent: window.__sent, opened, box: SURFACE.text(),
        surface: SURFACE.onSplice ? 'ace' : 'textarea'};
"""


@pytest.mark.parametrize(
    "body",
    [
        # An astral emoji: one character, two UTF-16 code units.
        "one \U0001f600\n",
        # A ZWJ sequence: a family, seven code points and eleven code units, which
        # a person sees and deletes as one glyph.
        "one \U0001f469‍\U0001f469‍\U0001f467\n",
        # A flag: two regional indicators, four code units, and the case where
        # taking half is a DIFFERENT flag rather than a broken character.
        "one \U0001f1e9\U0001f1ea\n",
    ],
)
def test_backspacing_a_whole_glyph_in_the_second_surface_leaves_both_copies_agreeing(
    client: TestClient, plan: Path, tmp_path: Path, body: str
):
    """Hazard 2, asked the way a person asks it: put the caret after the glyph
    and press backspace.

    What this does NOT assert is how much Ace takes. It takes a code point on an
    astral emoji and a code point on a ZWJ sequence, which is not what a person
    means by one glyph — and that is Ace's behaviour, not this binding's, and
    pinning it here would be pinning somebody else's decision. What must hold, and
    what the whole binding is for, is that whatever Ace decided to remove is what
    the room removes: the browser and the server end up holding the same string,
    with no lone surrogate and no replacement character between them.

    A lone surrogate cannot be encoded, so the failure has a signature: the update
    carries `\\ufffd` where the half was and the two copies never converge again.
    """
    front, _ = split_front_matter(stored(plan))
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "a glyph")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "ace-back.html", room, _welcome(room), _ACE_BACKSPACED,
        editor="ace",
    )
    assert answer["surface"] == "ace"
    assert answer["opened"] == body
    assert len(answer["box"]) < len(body), "backspace removed nothing at all"
    assert "�" not in room.body(), (
        "a surrogate half reached the room, which is the defect this test is for"
    )
    assert room.body() == answer["box"], (
        f"the browser holds {answer['box']!r} and the room holds {room.body()!r}"
    )


_ACE_OPENED = r"""
return {errors: window.__errors, sent: window.__sent,
        opened: SURFACE.text(), original: ORIGINAL_BODY,
        surface: SURFACE.onSplice ? 'ace' : 'textarea',
        updates: window.__sent.filter(f => f.t === 'update').length,
        dirty: document.getElementById('unsaved').textContent};
"""


def test_opening_the_second_surface_changes_no_byte_of_the_document(
    client: TestClient, plan: Path, tmp_path: Path
):
    """A surface must not rewrite the document merely by opening on it.

    Measured before this binding existed, on a 15,897-byte body whose first line
    ending is CRLF and whose other four hundred are LF: opening Ace produced a cut
    of 15,852 and a put of 16,252 and a 16,288-byte Yjs update **before anybody
    typed**. `Document.$detectNewLine` picks one sequence from the first ending it
    sees and `getValue()` rejoins every line with it, and a `<textarea>` normalises
    CRLF to LF unconditionally — so the two surfaces normalise in OPPOSITE
    directions and one of them rewrites the file on sight.

    `setNewLineMode('unix')` is the one boundary that decides, and this is what
    holds it there. The body below carries a CRLF on its first line and LF on the
    rest, which is the exact shape that produced the measurement above.
    """
    body = "first line\r\nsecond line\nthird line\nfourth line\n"
    front, _ = split_front_matter(stored(plan))
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "mixed endings")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "ace-open.html", room, _welcome(room), _ACE_OPENED, editor="ace",
    )
    assert answer["surface"] == "ace"
    # Counted in CHARACTERS CREDITED and not in frames, and the difference is the
    # point. Every tab sends exactly one update on joining — "whatever I have that
    # the room has not seen" — and on a surface that changed nothing it is empty.
    # `in_chrome_room` has already applied every frame this tab sent, as this
    # tab's login, so `Room.typed` is the room's own answer to "how much did they
    # write", which is the number `Room.credits` puts a name on a commit with.
    assert room.typed.get("ann", 0) == 0, (
        f"opening the second surface credited this tab {room.typed.get('ann')} characters "
        "before anybody typed — that is the whole document rewritten on sight"
    )
    assert answer["opened"] == answer["original"], (
        "the surface holds a different document from the one the page was rendered with"
    )
    assert answer["dirty"] == "Nothing to save", (
        f"opening the editor made the page think there was a change: {answer['dirty']!r}"
    )
    # Against the room's own normalisation and not against the file: the room
    # holds one line ending by construction now — `coedit.one_newline`, and the
    # argument for putting the rule there rather than in either surface is on
    # that function. What must not have happened is a MOVE: nothing between the
    # welcome and this line changed a character.
    assert room.body() == coedit.one_newline(shown), (
        "the room's copy moved without anybody typing"
    )
    assert "\r" in shown and "\r" not in room.body(), (
        "the fixture is not the mixed-ending body this test is about"
    )


_ACE_WATCHED = r"""
// Somebody else types, and this tab is only watching. Sent through the room, so
// what arrives is a real Yjs update over a real socket frame.
window.__room.onmessage({data: JSON.stringify({t: 'update', u: REMOTE})});
await new Promise(r => setTimeout(r, 80));
return {errors: window.__errors, sent: window.__sent,
        box: SURFACE.text(), caret: SURFACE.caret(),
        surface: SURFACE.onSplice ? 'ace' : 'textarea',
        updates: window.__sent.filter(f => f.t === 'update').length};
"""


def test_a_tab_that_is_only_watching_the_second_surface_is_credited_zero_characters(
    client: TestClient, plan: Path, tmp_path: Path
):
    """One Save is one commit, authored by whoever typed the most — and the
    characters are credited to the socket they arrived on.

    Measured with the naive adapter this binding replaces: one remote four-character
    keystroke reflected through `session.setValue` made a PASSIVE tab push the whole
    document back up the socket and take the credit for it — 97,892 characters on a
    97,890-character body, 6,700x amplification, `MAX_OUTBOX_BYTES` full in three
    frames and the eviction path firing as a forced reload. `Room.credits` becomes
    "authored by whoever reflected last".

    So this asserts all three halves of what must be true instead: zero frames go
    up, the caret does not move, and `Room.typed` credits this tab nothing.
    """
    body = "a line\nanother line\n"
    front, _ = split_front_matter(stored(plan))
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "a body")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    welcome = _welcome(room)

    # Bob's five characters, made in a second copy of the same document — same
    # body, same seed, so the update is one this room and this browser can both
    # apply — then applied here as Bob's, which is what the server does when it
    # relays. The welcome above was taken first, so the browser joins a room Bob
    # has not typed into yet and hears him afterwards.
    bob = coedit.Room(TASK, PATH, "0" * 40, shown)
    update = bob.absorb(shown.replace("a line", "a line here"))
    assert update, "the second copy produced no update"
    room.apply(update, "bob")
    remote = base64.b64encode(update).decode()

    answer = in_chrome_room(
        client, tmp_path / "ace-watch.html", room, welcome,
        _ACE_WATCHED.replace("REMOTE", json.dumps(remote)), editor="ace",
    )
    assert answer["surface"] == "ace"
    assert answer["box"] == room.body(), "the remote keystroke did not reach the surface"
    # One frame, and it is the joining one — "whatever I have that the room has
    # not seen", sent before Bob was heard and empty because there was nothing.
    # Hearing him adds none: `doc.on('update')` refuses to send anything whose
    # origin is `remote`, and the binding refuses to hear its own write.
    assert answer["updates"] == 1, (
        f"a watching tab put {answer['updates']} update frames on the wire, not the one "
        "it sends on joining"
    )
    assert answer["caret"] == {"from": 0, "to": 0}, (
        f"somebody else's keystroke moved this tab's caret to {answer['caret']}"
    )
    assert room.typed.get("ann", 0) == 0, (
        f"a tab that only watched was credited {room.typed.get('ann')} characters"
    )
    assert room.typed.get("bob", 0) == 5


_TWO_EDITORS = r"""
const opened = SURFACE.text();
SURFACE.setCaret(opened.indexOf('\n'));
if (SURFACE.editor) SURFACE.editor.insert(' EDIT'); else {
  SURFACE.splice(opened.indexOf('\n'), opened.indexOf('\n'), ' EDIT');
}
await new Promise(r => setTimeout(r, 60));
return {errors: window.__errors, sent: window.__sent, opened, box: SURFACE.text(),
        surface: SURFACE.onSplice ? 'ace' : 'textarea'};
"""


def test_two_editors_in_one_room_over_a_body_with_crlf_in_it_settle_on_one_document(
    client: TestClient, plan: Path, tmp_path: Path
):
    """Hazard 1, asked as the thing that actually goes wrong: not one editor and a
    line ending, but TWO editors normalising in opposite directions.

    A `<textarea>` turns CRLF into LF unconditionally, in the HTML parser on the
    way in and in the `value` getter on the way out. Ace's `Document` autodetects
    one sequence from the first ending it sees and `getValue()` rejoins every line
    with it — so left alone, one of them writes LF into the room and the other
    writes CRLF back, for ever, and the measured case that no length or index
    check can see is `"a\\nb\\rc\\nd"`: same length, different bytes.

    Normalised at ONE boundary — `setNewLineMode('unix')` where Ace is built — and
    this is the test that would fail if that line went. Both tabs are driven over
    the same seeded room, each types into it, and the two must end up holding the
    same string as the room and as each other.
    """
    body = "first line\r\nsecond line\r\nthird line\n"
    front, _ = split_front_matter(stored(plan))
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "crlf")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert "\r" in shown, "the fixture lost its carriage returns before the test began"

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    # The box first, then Ace, into the SAME room — each welcomed with the state
    # the room is in when it joins, which is what a second tab really gets.
    box = in_chrome_room(
        client, tmp_path / "two-box.html", room, _welcome(room), _TWO_EDITORS,
    )
    assert box["surface"] == "textarea"
    ace = in_chrome_room(
        client, tmp_path / "two-ace.html", room, _welcome(room), _TWO_EDITORS, editor="ace",
    )
    assert ace["surface"] == "ace"

    # Both surfaces opened on the same string, which is the normalisation claim
    # itself: the box could not have held a `\r` whatever it was given, and Ace
    # was pinned to `unix` so that it could not put one back.
    assert box["opened"] == ace["opened"].replace(" EDIT", ""), (
        f"the box opened on {box['opened']!r} and the second editor on {ace['opened']!r}"
    )
    assert "\r" not in box["opened"] and "\r" not in ace["opened"]
    # And the room after both of them, which is the thing that would ping-pong: a
    # surface rejoining every line with CRLF rewrites the whole document on its
    # first keystroke, and the other one rewrites it back on its next.
    assert room.body() == ace["box"], (
        f"the room holds {room.body()!r} and the second editor holds {ace['box']!r}"
    )
    assert "\r" not in room.body(), (
        "a carriage return went back into the room, and the other surface cannot hold "
        "it — which is the pair that never settles"
    )
    # Two edits, one from each surface, and both survived. A whole-document
    # rewrite by either would have taken the other's with it.
    assert room.body().count("EDIT") == 2, (
        f"one of the two edits was rewritten away: {room.body()!r}"
    )


_SUBSTITUTED = r"""
const editor = SURFACE.editor;
const keymap = [...document.querySelectorAll('#statusbar button')]
  .find(b => b.textContent.startsWith('Keymap'));
keymap.click();
await new Promise(r => setTimeout(r, 60));
const Vim = ace.require('ace/keyboard/vim').CodeMirror.Vim;
const opened = SURFACE.text();
// The ex line, through vim's own handler — which is what typing `:%s/…/…/g` and
// pressing Enter reaches. Driven this way rather than by synthesising thirteen
// keystrokes, because what is under test is the gesture's effect on the room and
// not vim's own command parser.
Vim.handleEx(editor.state.cm, '%s/cycle/bet/g');
await new Promise(r => setTimeout(r, 250));
return {errors: window.__errors, sent: window.__sent, opened, box: SURFACE.text(),
        said: document.getElementById('state').textContent,
        handler: String(editor.getKeyboardHandler().$id),
        updates: window.__sent.filter(f => f.t === 'update').length};
"""


def test_a_substitution_over_a_whole_document_is_announced_before_it_is_sent(
    client: TestClient, plan: Path, tmp_path: Path
):
    """S9.4. One keypress, the whole document, and everybody in it.

    `:%s/cycle/bet/g` is one gesture and hundreds of deltas. Three things have to
    be true about it and none of them is free:

    * **It converges.** The runs are applied to the `Y.Text` in the order they
      happened, each index into the document as it stood after the one before —
      which is what applying them in order to a copy that started in step
      reproduces. A single whole-document write instead would be
      remove-all-then-insert-all and the room would credit this tab with the
      entire body.
    * **It is one frame.** Batched into one `doc.transact`, so a substitution is
      one update on the wire rather than one per replacement. Measured before the
      batching: 722 change events, and `typed()` materialising two full code-point
      arrays per call is 1.90ms on a 250 KB body — about 1.4s of blocked main
      thread for one Replace All.
    * **It is announced.** Not refused: it is a legitimate thing to do to your own
      document. But a thousand characters changing at one keypress, in a document
      somebody else is also typing in, is a thing this application has to say out
      loud — three of its shipped defects were branches that decided something in
      silence.
    """
    body = ("A cycle is six weeks and a cycle is what a bet is made for.\n"
            "Every cycle has a cool-down, and the cycle after it starts cold.\n") * 12
    front, _ = split_front_matter(stored(plan))
    commit_directly(plan, {**SEED, PATH: f"---\n{front}\n---\n\n{body}"}, "cycles")
    shown = client.get("/api/index.json").json()["entities"][TASK]["body"]
    assert shown.count("cycle") >= 40, "the fixture is not the bulk gesture this is about"

    room = coedit.Room(TASK, PATH, "0" * 40, shown)
    answer = in_chrome_room(
        client, tmp_path / "ace-subst.html", room, _welcome(room), _SUBSTITUTED, editor="ace",
    )
    assert answer["handler"] == "ace/keyboard/vim", "the keymap did not come on"
    assert answer["opened"] == shown
    assert "cycle" not in answer["box"] and answer["box"].count("bet") >= 48, (
        f"the substitution did not run: {answer['box'][:80]!r}"
    )
    assert room.body() == answer["box"], (
        "the room and the editor disagree after a substitution over the whole document"
    )
    # One gesture, one frame. Two, counting the empty one every tab sends on
    # joining — which is what makes the number here 2 rather than 1.
    assert answer["updates"] == 2, (
        f"a substitution went out as {answer['updates'] - 1} update frames, not one"
    )
    assert "characters changed at once" in answer["said"], (
        f"a whole-document change went to everybody and the page said {answer['said']!r}"
    )
    # And the credit: the characters belong to whoever pressed the key.
    assert room.typed.get("ann", 0) >= 100, (
        f"the substitution was credited {room.typed.get('ann')} characters"
    )
