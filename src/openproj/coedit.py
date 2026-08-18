"""One shaping document, typed in by several people, arriving at one commit.

A room is a `Y.Text` of the markdown body and nothing else. The frontmatter
stays on the form: the fields are typed, `validate_all` decides requiredness in
one place and `_merge_frontmatter` already merges them per key, so a CRDT over
them would make the merge algorithm the authority on values whose invariant
lives somewhere else — and it would converge happily on `title: 5`. The body is
the half with no structure and no validator, where a line merge refuses honestly
rather than merging well.

Three things in here are load-bearing and none of them is obvious.

**The seed has a fixed client id.** Two documents built independently from the
same text share no history, so merging them inserts that text *twice* — the
whole document, doubled, with no conflict anywhere. A room is therefore seeded
once from a commit's body with client id `SEED`, which makes the seed a pure
function of the commit: a browser that seeds itself the same way produces
byte-identical update bytes, so a server restart is answered by exchanging state
vectors rather than by merging two histories. `tests/test_coedit.py` pins that
equality against the vendored Yjs build, because it is the one property the
whole restart story rests on.

**Characters are attributed to the socket they arrived on, never to the client
id inside the update.** Yjs records a client id per item and the design said to
bind that id to a login at connect; binding the *connection* is the same idea
with the client taken out of it entirely. A client chooses its own id and can
write any id it likes into an update, so an id read out of the payload is a
signature nobody checked. What arrived on Ann's socket is Ann's, and that is not
forgeable from the page.

**A room is a cache, not a store.** Nothing here is persisted: git holds the
text, and a CRDT blob the tool cannot read back is not a source of truth. The
floor under a lost room is the twenty-second quiet window, and under that the
draft the page already keeps in `localStorage`.

**The document is addressed in bytes and this file is written in strings.** See
`byte_offset`: the two index spaces are not the same, mixing them raises
nothing, and what it costs is somebody's sentence.
"""

from __future__ import annotations

import time

from pycrdt import Doc, Text

# The one shared value. Named rather than spelled twice: the browser has to ask
# for the same key or it gets an empty document with no error anywhere.
BODY = "body"

# The client id every seed is written with, on both sides. Zero because it has
# to be a constant and any constant will do — what matters is that the server
# and the browser agree, so that seeding from the same commit produces the same
# bytes and the two documents are the same document rather than two of them.
SEED = 0

# How long a room waits for the typing to stop before it commits. Twenty seconds
# is short enough that a crash costs a sentence and long enough that a paragraph
# is one commit rather than forty. A save commits at once and does not wait.
QUIET_SECONDS = 20.0

# How long an empty room is kept before it is dropped. Cloud Run closes every
# socket at five minutes (`--timeout 300`), so *everybody* dropping at once is
# the normal case and not a signal that the room is over. Re-seeding a room in
# that gap would hand every returning tab a document with a different seed, and
# the only honest answer to that is "reload" — a forced page reload every five
# minutes, for a disconnection nobody noticed. Kept longer than the teardown, so
# a reconnection lands in the room it left.
LINGER_SECONDS = 420.0

# The frame size a socket may carry is deliberately not here. It is a transport
# bound and this file has nothing to say about transport — and it only means
# anything beside the bound on what may be committed, which is `web.py`'s. The
# two were separately-written copies of one number, which is how the transport
# came to refuse a body the policy would have accepted.


def byte_offset(text: str, at: int) -> int:
    """Where an offset into a Python string lands in the document's index space.

    They are two index spaces and they are not the same one. A Python string is
    counted in code points; `pycrdt.Text` is addressed in UTF-8 bytes —
    `len(Text("a—b"))` is 5 where `len("a—b")` is 3 — and nothing raises when
    the two are mixed. An index that falls *inside* a character is not an error
    either: `insert` silently puts the text at the end of the document instead.

    So a splice computed on the string and applied to the document rewrote a
    word somewhere it was not, dropped part of it and left the rest stranded at
    the bottom of the file, and the room committed that, and the next `absorb`
    on reconnection mangled what was left. `contraction-off run.` came back as
    `contraction-oun.` with a stray `un.` at the end of the document.

    This is not an edge case, it is the ordinary document: em dashes are this
    corpus's house style — fifteen of the twenty-one records in `seed/` carry
    one, counted on 2026-08-18 — so most real bodies have a character before the
    splice point that makes the two numbers differ.

    One conversion, at the one boundary, rather than arithmetic at each call
    site: `test_every_index_into_the_document_is_converted` reads this module as
    syntax and holds every index handed to `pycrdt` to coming from here.
    """
    return len(text[:at].encode("utf-8"))


def seeded(body: str) -> Doc:
    """A document holding exactly this text, written by `SEED`.

    Deterministic in the text, which is the whole point — see the module note.
    """
    doc = Doc(client_id=SEED)
    doc[BODY] = Text()
    if body:
        with doc.transaction():
            doc[BODY] += body
    return doc


class Room:
    """One entity's body, live, with everyone currently typing in it."""

    def __init__(self, entity_id: str, path: str, commit: str, body: str) -> None:
        self.entity_id = entity_id
        self.path = path
        # What the document was built from, and what a returning client is asked
        # to match. It does not move when the room commits: the history is still
        # the same history, so a client seeded alongside it stays compatible.
        self.seed = commit
        # What the next write is compared against. This one does move.
        self.base = commit
        self.committed = body
        self.doc = seeded(body)
        self.text: Text = self.doc[BODY]
        # login -> characters inserted since the last commit. Present with a
        # count of zero for somebody who only deleted, so a commit still names
        # them: taking a paragraph out is authorship too.
        self.typed: dict[str, int] = {}
        self.members: dict[int, str] = {}
        self.refusal: str | None = None
        self._quiet_since = time.monotonic()
        self._who: str | None = None
        # Held on the room, or the subscription is collected and the counting
        # stops silently — the commits would still land, attributed to nobody.
        self._counting = self.text.observe(self._count)

    # -- the text -----------------------------------------------------------

    def body(self) -> str:
        return str(self.text)

    def pending(self) -> bool:
        """Whether there is anything a commit would write."""
        return self.body() != self.committed

    def quiet_for(self) -> float:
        return time.monotonic() - self._quiet_since

    def state(self) -> bytes:
        return self.doc.get_state()

    def since(self, state_vector: bytes | None) -> bytes:
        return self.doc.get_update(state_vector) if state_vector else self.doc.get_update()

    def _count(self, event) -> None:
        """Characters inserted, credited to whoever's socket carried them.

        `_who` is None for a change this server made — folding in somebody's git
        commit — and that is deliberately not attributed to anyone in the room:
        it is already attributed, in the commit it came from.
        """
        if self._who is None:
            return
        # Characters, deliberately not the bytes the document is addressed in:
        # an em dash is one thing a person typed, not three, and this number is
        # only ever compared against another person's.
        inserted = sum(len(part["insert"]) for part in event.delta if "insert" in part)
        self.typed[self._who] = self.typed.get(self._who, 0) + inserted

    def apply(self, update: bytes, login: str) -> None:
        """One client's update, attributed to that client's login."""
        self._who = login
        try:
            self.doc.apply_update(update)
        finally:
            self._who = None
        self._quiet_since = time.monotonic()
        # Whatever was refused was refused about text that has now changed, so
        # the next quiet window is allowed to try again.
        self.refusal = None

    def absorb(self, body: str) -> bytes | None:
        """Make the room's text this text, and hand back the update that did it.

        The update has to go back to every client: a document the server changed
        and nobody was told about is a document that diverges at the next
        keystroke. Returns None when there was nothing to change.

        A minimal splice rather than clear-and-reinsert, because a reader whose
        caret is in the second half of the document should not have it thrown to
        the end because somebody fixed a typo in the first line.

        The prefix and the suffix are found in the string, where the text is;
        the splice is made in bytes, where the document is. `byte_offset` is
        that boundary and the only place the two spaces meet.
        """
        was, now = self.body(), body
        if was == now:
            return None
        before = self.doc.get_state()
        head = 0
        while head < len(was) and head < len(now) and was[head] == now[head]:
            head += 1
        tail = 0
        while (
            tail < len(was) - head and tail < len(now) - head and was[-1 - tail] == now[-1 - tail]
        ):
            tail += 1
        with self.doc.transaction():
            if len(was) - head - tail:
                del self.text[byte_offset(was, head) : byte_offset(was, len(was) - tail)]
            if len(now) - head - tail:
                # `was[:head] == now[:head]` by construction, so converting
                # against either string gives the same byte — and the deletion
                # above started at it, so it is still where the insert goes.
                self.text.insert(byte_offset(now, head), now[head : len(now) - tail])
        return self.doc.get_update(before)

    # -- who is in it -------------------------------------------------------

    def join(self, connection: int, login: str) -> None:
        self.members[connection] = login

    def leave(self, connection: int) -> None:
        self.members.pop(connection, None)

    def empty(self) -> bool:
        return not self.members

    def people(self) -> list[str]:
        """Who is in the room, each named once however many tabs they have open."""
        return sorted(set(self.members.values()))

    # -- the commit ---------------------------------------------------------

    def credits(self, presser: str = "") -> tuple[str, list[str]]:
        """Who authors the commit, and who is credited beside them.

        Whoever inserted the most characters since the last commit authors it —
        deterministic, and right in the ordinary case of one person writing a
        section and another fixing a sentence in it. Everybody else in the same
        diff gets a `Co-authored-by:`, so `git log --format='%an'` keeps the
        per-person trail it has today and `git shortlog` sees both halves.

        `presser` is whoever pressed Save, if anybody did. They are in the commit
        even when they typed nothing in the body — they are the reason it exists,
        and on a save they may have changed a field.
        """
        ranked = sorted(self.typed.items(), key=lambda pair: (-pair[1], pair[0]))
        order = [login for login, _ in ranked]
        if presser and presser not in order:
            order.append(presser)
        if not order:
            return "", []
        return order[0], order[1:]

    def settled(self, commit: str, body: str) -> None:
        """The write landed. This is now the ground the next one stands on."""
        self.base = commit
        self.committed = body
        self.typed.clear()
        self.refusal = None


class Rooms:
    """Every live room on this process, and the ones still warm.

    A dict, because `--max-instances 1` is what makes the writer lock mean
    anything and one process is therefore the whole world. Nothing here survives
    a restart and nothing here needs to.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._emptied: dict[str, float] = {}

    def get(self, entity_id: str) -> Room | None:
        return self._rooms.get(entity_id)

    def add(self, room: Room) -> Room:
        self._rooms[room.entity_id] = room
        return room

    def all(self) -> list[Room]:
        return list(self._rooms.values())

    def enter(self, room: Room, connection: int, login: str) -> None:
        room.join(connection, login)
        self._emptied.pop(room.entity_id, None)

    def exit(self, room: Room, connection: int) -> None:
        room.leave(connection)
        if room.empty():
            self._emptied[room.entity_id] = time.monotonic()

    def sweep(self) -> list[Room]:
        """Drop the rooms nobody came back to. Returns the ones dropped."""
        gone = []
        for entity_id, when in list(self._emptied.items()):
            room = self._rooms.get(entity_id)
            if room is None or room.members:
                self._emptied.pop(entity_id, None)
                continue
            if time.monotonic() - when >= LINGER_SECONDS:
                self._emptied.pop(entity_id, None)
                gone.append(self._rooms.pop(entity_id))
        return gone
