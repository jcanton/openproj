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


def one_newline(text: str) -> str:
    """Every line ending the room holds, as the one ending a browser can hold.

    **This is where the rule lives, and it exists because there is now more than
    one editing surface.** A `<textarea>` turns CRLF into LF unconditionally — in the
    HTML parser on the way in and in the `value` getter on the way out — so it
    can never hold a carriage return whatever it is given. Ace's `Document`
    autodetects one sequence from the first line ending it sees and rejoins every
    line with it, and inserting a lone `\r` into it produces a LINE BREAK: the
    document grows a row. So the two surfaces normalise in opposite directions,
    and a room seeded from a file with CRLF in it sat between them — the box
    dropped the carriage returns and the room put them back, once per keystroke,
    for ever, with the two copies a different LENGTH each time.

    `store.py` decodes the blob with no newline translation and there is no
    `.gitattributes text=auto`, so a room really can be seeded with them: it is
    one `git commit` made on Windows away. Normalising here rather than in either
    surface is what makes it one rule instead of two that disagree — and it is
    here rather than in `store.py` because what a file holds is the file's
    business, while what a room holds has to be a thing every client can hold.

    It is not the only line about line endings — `aceSurface` pins
    `setNewLineMode('unix')` as well — and the two answer different doors: this
    one is what the room holds, that one is what a paste into a one-line document
    can make Ace re-detect. Each has a test that fails without it.

    The cost, stated: saving a document whose file had CRLF endings writes LF
    endings back. That was already true the moment anybody typed in it — the box
    could not hold them and the first keystroke spliced them out — and it is now
    true on the first save instead of the first keystroke.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
    """One record's body, live, with everyone currently typing in it."""

    def __init__(self, record_id: str, path: str, commit: str, body: str) -> None:
        self.record_id = record_id
        self.path = path
        # What the document was built from, and what a returning client is asked
        # to match. It does not move when the room commits: the history is still
        # the same history, so a client seeded alongside it stays compatible.
        self.seed = commit
        # What the next write is compared against. This one does move.
        self.base = commit
        # Through `one_newline` before anything else touches it, so `committed`
        # and the document are the same string and `pending()` does not answer
        # yes on a room nobody has typed in.
        body = one_newline(body)
        self.committed = body
        self.doc = seeded(body)
        self.text: Text = self.doc[BODY]
        # login -> characters inserted since the last commit. Present with a
        # count of zero for somebody who only deleted, so a commit still names
        # them: taking a paragraph out is authorship too.
        self.typed: dict[str, int] = {}
        self.members: dict[int, str] = {}
        # Where each socket's caret is. Presence is a name and a place: the name
        # says who else is in the document and the place says which line they are
        # working on, which is the difference between knowing somebody is here
        # and knowing not to rewrite the paragraph they are in.
        self.seats: dict[int, int] = {}
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
        # The same boundary on the way in from git: a commit made elsewhere can
        # carry CRLF, and a room that took it would put back exactly what the
        # seed was normalised out of.
        was, now = self.body(), one_newline(body)
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
        # And their seat, or the room draws a band for somebody who closed the
        # tab — a colour under a name that is no longer in the list beside it.
        self.seats.pop(connection, None)

    def empty(self) -> bool:
        return not self.members

    def people(self) -> list[str]:
        """Who is in the room, each named once however many tabs they have open."""
        return sorted(set(self.members.values()))

    def sits(self, connection: int, at: int) -> None:
        """Where one member's caret is, as an index into the document.

        Relayed and never read: this server does not interpret the number, it
        carries it. Which matters, because the index space is the browser's —
        UTF-16 code units, the only thing a `<textarea>`'s `selectionStart` and a
        Yjs text in JavaScript agree on — and this module measures in UTF-8 bytes
        for the splices it applies itself. Converting here would be a third index
        space in a file whose module note is about exactly that mistake; the two
        ends that use this one are both browsers, and they already agree.
        """
        self.seats[connection] = at

    def where(self) -> list[dict]:
        """Each member, once, and where they are sitting.

        One entry per LOGIN and not per socket: two tabs of one person are one
        person, the same way `people` counts them, and two bands in two places
        under one name is a room saying somebody is in two rooms at once. The
        newest of their sockets wins, which is the tab they are typing in.
        """
        seats: dict[str, int] = {}
        for connection, login in self.members.items():
            at = self.seats.get(connection)
            if at is not None:
                seats[login] = at
        return [{"login": login, "at": at} for login, at in sorted(seats.items())]

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

    def tried(self) -> None:
        """A commit was attempted. The next quiet window starts here.

        A refusal used to be cleared by `apply` alone, so a `StoreLocked` — which
        is what an ordinary second writer looks like, and is over in a moment —
        stopped the quiet window until somebody typed again. A room whose typists
        had all stopped never committed at all, and nothing said so. The window
        retries now, and this is what keeps that a retry per window rather than a
        retry per second: the clock the window is measured against restarts when
        the attempt is made, exactly as it does when a keystroke arrives.
        """
        self._quiet_since = time.monotonic()

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

    def get(self, record_id: str) -> Room | None:
        return self._rooms.get(record_id)

    def add(self, room: Room) -> Room:
        self._rooms[room.record_id] = room
        return room

    def all(self) -> list[Room]:
        return list(self._rooms.values())

    def enter(self, room: Room, connection: int, login: str) -> None:
        room.join(connection, login)
        self._emptied.pop(room.record_id, None)

    def exit(self, room: Room, connection: int) -> None:
        room.leave(connection)
        if room.empty():
            self._emptied[room.record_id] = time.monotonic()

    def sweep(self) -> list[Room]:
        """Drop the rooms nobody came back to. Returns the ones dropped."""
        gone = []
        for record_id, when in list(self._emptied.items()):
            room = self._rooms.get(record_id)
            if room is None or room.members:
                self._emptied.pop(record_id, None)
                continue
            if time.monotonic() - when >= LINGER_SECONDS:
                self._emptied.pop(record_id, None)
                gone.append(self._rooms.pop(record_id))
        return gone
