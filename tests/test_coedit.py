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

import base64
import gc
import json
import re
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_injection import run_js
from test_store import commit_directly
from test_web import PATH, SECRET, SEED, TASK

from openproj import coedit
from openproj.auth import User, sign_session
from openproj.index import build_index
from openproj.model import load_repo, split_front_matter
from openproj.render import _yjs
from openproj.web import SESSION_COOKIE, create_app

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


def test_a_stranger_is_refused_the_socket(plan: Path):
    """And is therefore handed exactly today's editor. Refusal has to be a
    handshake that does not complete rather than a room that quietly does
    nothing, or the page cannot tell that it is on its own."""
    app = create_app(plan, auth="github", secret=SECRET, client_id="x", client_secret="y")
    with TestClient(app) as signed_out:
        with pytest.raises(WebSocketDisconnect):
            with signed_out.websocket_connect(f"/api/coedit/{TASK}"):
                pass


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
