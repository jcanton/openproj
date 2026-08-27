#!/usr/bin/env python
"""Connection churn: twenty co-editors, five rooms, and sockets that keep dying.

    uv run python tests/load/churn.py --rtt-ms 300 --out design/probes/load/coedit-churn.json

The other scenarios in this directory ask what happens while everybody is
typing. This one asks what happens at the edges of a session, which on Cloud Run
is not an edge case at all: `--timeout 300` closes **every** websocket every five
minutes, so for a person who edits for half an hour, reconnection is six ordinary
events, not an incident. Three shapes, in one server, in order:

**A — the socket dies without a close frame.** A laptop lid, a tunnel, a tab
killed by the OS. The TCP connection is reset (`SO_LINGER 0`) mid-keystroke and
the same person comes back a second or two later. Two questions: does the seat
and presence bookkeeping let go of them, and do the characters typed in the
seconds around the drop reach the plan.

**B — the five-minute wall.** Every socket in every room closed on a timer and
everybody reconnecting at once, which is what the deployment does to itself.
The question the reading phase named is whether a reconnection can re-seed from
a commit that does not yet hold what was just typed.

**C — a reconnection that lands in the middle of a commit.** `_commit_room`
calls `store.write` without a thread, deliberately (`web.py` says why: there
must be no `await` between the snapshot and `room.settled`, or a keystroke that
arrives during the write is deleted by the absorb). So a push blocks the event
loop, and a socket that is between `store.head()` and `await socket.accept()`
when that happens resumes holding a commit that is now one behind. What the join
path then does with a stale head is the thing this phase is built to catch.

**The client is modelled on the real one, and that mattered.** `render.py`'s
`_COEDIT` keeps its `Y.Doc` across a socket drop, reconnects with `{seed, sv}`,
applies the welcome update and then sends `encodeStateAsUpdate(doc, message.sv)`
— everything it typed while the socket was down. A driver that threw its
document away on every drop would have reported that as data loss and the cause
would have been the driver. `Peer` below keeps the document and sends that
delta, which is why it does not subclass `room.Member` (whose `hello` is
`{seed: None, sv: None}` and whose document is built once per socket).

Nothing in `src/openproj/` is touched. Everything is read out of the bare plan
with pygit2, because `Store` holds an exclusive flock while the server is up.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import socket as socketlib
import struct
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import harness  # noqa: E402
import httpx  # noqa: E402
import measure  # noqa: E402
import pygit2  # noqa: E402
import verify  # noqa: E402
from users import Typed  # noqa: E402
from wsclient import Client  # noqa: E402

from openproj import coedit  # noqa: E402
from openproj.auth import User, sign_session  # noqa: E402
from openproj.web import SESSION_COOKIE  # noqa: E402

# The stream each person types. Distinct per person only in where it starts, so
# a run of it is recognisable as theirs and a missing middle is visible as a
# break rather than as a shorter string.
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
CHARS_PER_SECOND = 5.0


# -- one person, one document, many sockets ---------------------------------


class Peer:
    """One tab: a document that outlives its socket.

    The document, the anchor and the count of what has been typed all belong to
    the person. The socket does not — it is opened, killed and opened again
    underneath them, exactly as a browser's is.
    """

    def __init__(self, port: int, login: str, record: str, client_id: int, anchor: str) -> None:
        self.port = port
        self.login = login
        self.record = record
        self.anchor = anchor
        self.stream = ALPHABET[client_id % len(ALPHABET) :] + ALPHABET
        self.doc = coedit.Doc(client_id=client_id)
        self.doc[coedit.BODY] = coedit.Text()
        self.text = self.doc[coedit.BODY]
        self.lock = threading.Lock()
        self.client: Client | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.seed: str | None = None
        self.base: str | None = None
        self.typed = 0
        self.connected = False
        self.connects = 0
        self.gone: str | None = None
        self.told: list[dict] = []  # every non-update frame, timestamped
        self.trouble: list[str] = []
        self.reloads: list[dict] = []
        # Nobody in this run ever deletes anything. So a document that gets
        # SHORTER is the server taking text back out of it, and catching that in
        # the reader thread — rather than in a sampler twice a second — is what
        # makes a rewind that heals itself on the next join still visible.
        self.length = 0
        self.shrinks: list[dict] = []

    # -- the socket ---------------------------------------------------------

    def connect(self, ledger: measure.Ledger | None = None, note: str = "") -> str:
        """Open a socket for this document. Returns 'welcome' or 'reload'.

        The handshake is done on the calling thread and the reader started after
        it, so a room that answers a reconnection with `reload` is seen here
        rather than in a background thread that nobody is reading.
        """
        began = time.monotonic()
        token = sign_session(User(login=self.login, member=True), harness.SECRET)
        try:
            client = Client(
                "127.0.0.1", self.port, f"/api/coedit/{self.record}",
                cookie=f"{SESSION_COOKIE}={token}",
            )
        except Exception as error:  # noqa: BLE001 - a handshake fails in many ways
            # Reported and not raised: a socket that would not open is a fact
            # about the server under this load, and a driver that died of it
            # would report nothing at all about the other nineteen people.
            self.trouble.append(f"connect failed: {type(error).__name__}: {error}")
            self.connected = False
            if ledger is not None:
                ledger.record(measure.Action(
                    who=self.login, kind="WS connect", began=began,
                    ms=(time.monotonic() - began) * 1000,
                    status=f"!{type(error).__name__}", record=self.record, note=note))
            return "failed"
        with self.lock:
            mine = self.doc.get_state()
        client.send_json(
            {"t": "hello", "seed": self.seed, "sv": base64.b64encode(mine).decode()}
        )
        frame = client.receive_json()
        outcome = str(frame.get("t"))
        if outcome != "welcome":
            # What the browser does with this is `stop(why)`: the room is over
            # for this page and only a reload gets back in.
            self.reloads.append({"why": frame.get("why"), "at": time.monotonic()})
            client.close()
            self.connected = False
            if ledger is not None:
                ledger.record(measure.Action(
                    who=self.login, kind="WS connect", began=began,
                    ms=(time.monotonic() - began) * 1000, status=outcome,
                    record=self.record, note=note))
            return outcome
        self.seed = frame.get("seed")
        self.base = frame.get("base")
        with self.lock:
            if frame.get("update"):
                self.doc.apply_update(base64.b64decode(frame["update"]))
            # Everything this tab has that the room has not seen. On a first
            # connection that is nothing; on a reconnection it is every
            # keystroke made while the socket was down — including the ones the
            # reset threw away in flight. This line is `_COEDIT`'s last line of
            # `welcomed` and it is the whole reconnection story.
            catchup = self.doc.get_update(base64.b64decode(frame["sv"]))
        client.send_json({"t": "update", "u": base64.b64encode(catchup).decode()})
        with self.lock:
            self.length = len(str(self.text))
        client._socket.settimeout(None)
        self.client = client
        self.connected = True
        self.connects += 1
        self.gone = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._read, args=(client, self._stop), daemon=True)
        self.thread.start()
        if ledger is not None:
            ledger.record(measure.Action(
                who=self.login, kind="WS connect", began=began,
                ms=(time.monotonic() - began) * 1000, status="welcome",
                record=self.record, commit=self.base, note=note))
        return "welcome"

    def _read(self, client: Client, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                frame = client.receive_json()
                kind = frame.get("t")
                if kind == "update":
                    with self.lock:
                        self.doc.apply_update(base64.b64decode(frame["u"]))
                        self._measure("update")
                    continue
                self.told.append(dict(frame, at_=time.monotonic()))
                if kind == "saved" and frame.get("update"):
                    with self.lock:
                        self.doc.apply_update(base64.b64decode(frame["update"]))
                        self._measure("saved")
                if kind == "reload":
                    self.reloads.append({"why": frame.get("why"), "at": time.monotonic()})
                    self.connected = False
                    self.gone = "reload"
                    return
        except Exception as error:  # noqa: BLE001 - a socket ends in many ways
            if not stop.is_set():
                self.gone = f"!{type(error).__name__}"
                self.connected = False

    def _measure(self, why: str) -> None:
        """Called with the lock held, after every update this document applies."""
        now = len(str(self.text))
        if self.length and now < self.length:
            self.shrinks.append({
                "at": time.monotonic(), "why": why, "was": self.length, "now": now,
                "lost": self.length - now, "run": self.run_length(str(self.text)),
                "counted": self.typed,
            })
        self.length = now

    def drop(self, rude: bool) -> None:
        """Leave. `rude` is an RST: no close frame, and whatever was still in the
        send buffer is thrown away by the kernel — which is the half of a real
        disconnection a polite close never models."""
        self._stop.set()
        self.connected = False
        client, self.client = self.client, None
        if client is None:
            return
        try:
            if rude:
                client._socket.setsockopt(
                    socketlib.SOL_SOCKET, socketlib.SO_LINGER, struct.pack("ii", 1, 0)
                )
                client._socket.close()
            else:
                client.close()
        except Exception:  # noqa: BLE001 - closing a closed socket
            pass

    # -- what the person does -----------------------------------------------

    def press(self) -> str:
        """One character, at this person's own place in the document."""
        with self.lock:
            body = str(self.text)
            at = body.find(self.anchor)
            if at < 0:
                return "anchor-gone"
            where = at + len(self.anchor) + self.typed
            if where > len(body):
                return "anchor-short"
            character = self.stream[self.typed % len(self.stream)]
            before = self.doc.get_state()
            self.text.insert(coedit.byte_offset(body, where), character)
            update = self.doc.get_update(before)
            self.typed += 1
        client = self.client
        if client is None:
            # Typed while the socket is down. The character is in this tab's
            # document and `connect` will carry it over; this is the browser's
            # ordinary behaviour and not an error.
            return "offline"
        try:
            client.send_json({"t": "update", "u": base64.b64encode(update).decode()})
        except Exception as error:  # noqa: BLE001
            self.connected = False
            self.gone = f"!{type(error).__name__}"
            return "send-failed"
        return "typed"

    def plant(self) -> None:
        """Put this person's anchor at the end of the document."""
        with self.lock:
            body = str(self.text)
            before = self.doc.get_state()
            self.text.insert(coedit.byte_offset(body, len(body)), "\n" + self.anchor)
            update = self.doc.get_update(before)
        if self.client is not None:
            self.client.send_json({"t": "update", "u": base64.b64encode(update).decode()})

    def sit(self, at: int) -> None:
        client = self.client
        if client is None:
            return
        try:
            client.send_json({"t": "at", "at": at})
        except Exception:  # noqa: BLE001
            self.connected = False

    def save(self, timeout: float = 90.0) -> dict:
        client = self.client
        if client is None:
            return {"t": "offline"}
        seen = len(self.told)
        began = time.monotonic()
        try:
            client.send_json({"t": "save", "fields": {}})
        except Exception as error:  # noqa: BLE001
            return {"t": f"!{type(error).__name__}"}
        while time.monotonic() - began < timeout:
            for frame in self.told[seen:]:
                if frame.get("t") in ("saved", "refused", "nothing"):
                    return {**frame, "ms": round((time.monotonic() - began) * 1000, 1)}
            if self.gone:
                return {"t": "socket-gone", "ms": round((time.monotonic() - began) * 1000, 1)}
            time.sleep(0.02)
        return {"t": "no answer", "ms": round((time.monotonic() - began) * 1000, 1)}

    def body(self) -> str:
        with self.lock:
            return str(self.text)

    def run_length(self, text: str | None = None) -> int:
        """How many of this person's characters stand behind their anchor.

        A contiguous run, so a missing middle reads as a short run rather than as
        a string that happens to differ somewhere.
        """
        body = self.body() if text is None else text
        at = body.find(self.anchor)
        if at < 0:
            return -1
        tail = body[at + len(self.anchor) :]
        n = 0
        while n < len(tail) and tail[n] == self.stream[n % len(self.stream)]:
            n += 1
        return n


def _tally(things) -> dict:
    out: dict[str, int] = {}
    for thing in things:
        out[str(thing)] = out.get(str(thing), 0) + 1
    return dict(sorted(out.items()))


# -- what the run saw -------------------------------------------------------


@dataclass
class Event:
    """Something worth reporting, with the second it happened in."""

    at: float
    phase: str
    kind: str
    what: str
    detail: dict = field(default_factory=dict)


class Watcher:
    """Git and the live documents, sampled together, twice a second.

    The invariant it holds is one sentence: **a person's own editor is never
    behind git about their own text.** Their document is where the characters
    were born, so it can be ahead of the commit and must never be behind it. It
    going backwards at all is text disappearing out of an open editor, and it
    falling behind git is text that was committed and then removed from the
    editor it was written in.
    """

    def __init__(self, plan: Path, peers: list[Peer], events: list[Event], zero: float) -> None:
        self.plan = plan
        self.peers = peers
        self.events = events
        self.zero = zero
        self.phase = "setup"
        self.high_git = {p.login: 0 for p in peers}
        self.high_doc = {p.login: 0 for p in peers}
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.thread.join(timeout=5)

    def _bodies(self) -> tuple[str, dict[str, str]]:
        git = pygit2.Repository(str(self.plan))
        head = str(git.references["refs/heads/main"].target)
        paths = harness.record_paths(self.plan, head)
        out = {}
        for record in {p.record for p in self.peers}:
            path = paths.get(record)
            out[record] = harness.read_blob(self.plan, head, path) or "" if path else ""
        return head, out

    def sample(self) -> None:
        # The documents first and git second, so a run that reads long in git is
        # never an artefact of the order: anything committed between the two
        # reads was already in the document when the document was read.
        docs = {p.login: p.body() for p in self.peers}
        head, files = self._bodies()
        for peer in self.peers:
            doc_run = peer.run_length(docs[peer.login])
            git_run = peer.run_length(files.get(peer.record, ""))
            was_doc, was_git = self.high_doc[peer.login], self.high_git[peer.login]
            if doc_run >= 0 and doc_run < was_doc:
                self.events.append(Event(
                    round(time.monotonic() - self.zero, 2), self.phase, "DOC WENT BACK",
                    f"{peer.login}'s own editor lost {was_doc - doc_run} characters it had typed",
                    {"record": peer.record, "was": was_doc, "now": doc_run,
                     "git": git_run, "head": head[:10]}))
            if git_run >= 0 and git_run < was_git:
                self.events.append(Event(
                    round(time.monotonic() - self.zero, 2), self.phase, "GIT WENT BACK",
                    f"{peer.login}'s committed run shrank by {was_git - git_run} characters",
                    {"record": peer.record, "was": was_git, "now": git_run, "head": head[:10]}))
            if doc_run >= 0 and git_run > doc_run:
                self.events.append(Event(
                    round(time.monotonic() - self.zero, 2), self.phase, "EDITOR BEHIND GIT",
                    f"{peer.login}'s editor holds {doc_run} of their characters and the "
                    f"plan holds {git_run}",
                    {"record": peer.record, "doc": doc_run, "git": git_run, "head": head[:10]}))
            self.high_doc[peer.login] = max(was_doc, doc_run)
            self.high_git[peer.login] = max(was_git, git_run)
        self.samples.append({
            "at": round(time.monotonic() - self.zero, 2), "phase": self.phase,
            "head": head[:10],
            "doc": sum(max(0, p.run_length(docs[p.login])) for p in self.peers),
            "git": sum(max(0, p.run_length(files.get(p.record, ""))) for p in self.peers),
        })

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample()
            except Exception as error:  # noqa: BLE001 - a sampler may never be the failure
                self.events.append(Event(
                    round(time.monotonic() - self.zero, 2), self.phase, "sampler",
                    f"{type(error).__name__}: {error}"))
            self._stop.wait(0.5)


class Pulse:
    """`GET /api/health` twice a second, from its own thread.

    The cheapest page in the application, so what it measures is not the page: it
    is how long the event loop was unavailable. Every room commit blocks that
    loop for the length of a push, and this is what the nineteen people who are
    not saving experience while it does.
    """

    def __init__(self, base: str, ledger: measure.Ledger, zero: float) -> None:
        self.base = base
        self.ledger = ledger
        self.zero = zero
        self.phase = "setup"
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.thread.join(timeout=5)

    def _loop(self) -> None:
        with httpx.Client(timeout=30.0) as http:
            while not self._stop.is_set():
                began = time.monotonic()
                try:
                    answer = http.get(f"{self.base}/api/health")
                    status = str(answer.status_code)
                except Exception as error:  # noqa: BLE001
                    status = type(error).__name__
                self.ledger.record(measure.Action(
                    who="pulse", kind=f"GET /api/health [{self.phase}]", began=began - self.zero,
                    ms=(time.monotonic() - began) * 1000, status=status))
                self._stop.wait(0.5)


# -- the phases -------------------------------------------------------------


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.rng = random.Random(args.seed)
        self.events: list[Event] = []
        self.ledger = measure.Ledger()
        self.phases: dict[str, dict] = {}
        # record -> the monotonic instant its room may type again.
        self.quiet_until: dict[str, float] = {}
        self.drained: dict[str, int] = {}
        self.browsable: list[str] = []
        self.sent_forms: list = []

    def deletions(self, phase: str, peers: list[Peer]) -> None:
        """Every shrink any document took during the phase, as an event.

        Nobody in this run deletes anything, so the server is the only thing that
        can shorten a document: `Room.absorb`, which is reached on a join and
        after a write that landed as something other than what was sent.
        """
        for peer in peers:
            for shrink in peer.shrinks[self.drained.get(peer.login, 0):]:
                self.events.append(Event(
                    round(shrink["at"] - self.zero, 2), phase, "TEXT DELETED FROM A DOCUMENT",
                    f"{peer.login}'s open document lost {shrink['lost']} characters on a "
                    f"{shrink['why']} frame; their own run is now {shrink['run']} of the "
                    f"{shrink['counted']} they typed",
                    {"record": peer.record, **{k: v for k, v in shrink.items() if k != "at"}}))
            self.drained[peer.login] = len(peer.shrinks)

    def note(self, phase: str, kind: str, what: str, detail: dict | None = None) -> None:
        self.events.append(Event(round(time.monotonic() - self.zero, 2), phase, kind, what,
                                 detail or {}))

    # -- typing, shared by every phase --------------------------------------

    def typing(self, phase: str, peers: list[Peer], until: float) -> list[threading.Thread]:
        """Every peer types at ~5 characters a second until `until`."""
        threads = [threading.Thread(target=self._type_one, args=(phase, p, until), daemon=True)
                   for p in peers]
        for one in threads:
            one.start()
        return threads

    def _type_one(self, phase: str, peer: Peer, until: float) -> None:
        pace = 1.0 / CHARS_PER_SECOND
        while time.monotonic() < until:
            # Nobody types while a save they can see is in the air. This is what
            # a person does — press Save, watch for it to land — and it is also
            # the only thing that leaves a room settled long enough for the join
            # path's `elif not room.pending()` to be reached at all. See
            # `phase_c`: without it the probe cannot even get to the branch it
            # is aimed at, and a run would report "not reachable" about a gate it
            # never opened.
            while time.monotonic() < self.quiet_until.get(peer.record, 0.0):
                time.sleep(0.02)
                if time.monotonic() >= until:
                    return
            began = time.monotonic()
            answer = peer.press()
            self.ledger.record(measure.Action(
                who=peer.login, kind="WS keystroke", began=began - self.zero,
                ms=(time.monotonic() - began) * 1000, status=answer, record=peer.record))
            if answer in ("anchor-gone", "anchor-short"):
                # The document moved under this person: their run is shorter than
                # their own count of it, which is only possible if characters they
                # typed were taken back out. Recorded, then resynchronised on
                # what the document actually holds so the phase keeps running —
                # a peer stuck at `anchor-short` types nothing for the rest of
                # the run and would look like a quiet person rather than a defect.
                run = peer.run_length()
                self.note(phase, "TYPING BLOCKED",
                          f"{peer.login} could not type: {answer}; counted {peer.typed}, "
                          f"the document holds {run}",
                          {"record": peer.record, "counted": peer.typed, "in_document": run})
                peer.trouble.append(f"{answer}: counted {peer.typed}, document holds {run}")
                if run >= 0:
                    peer.typed = run
                else:
                    return
            if self.rng.random() < 0.06:
                peer.sit(self.rng.randrange(0, 400))
            time.sleep(self.rng.uniform(0.85, 1.15) * pace)

    def browsers(self, phase: str, until: float, ids: list[str], how_many: int
                 ) -> list[threading.Thread]:
        """People reading records while everybody else types.

        `GET /detail` is the expensive page — the earlier phase of this audit
        measured it at 876 ms p50 on this corpus — and it is CPU inside the event
        loop. It is here for what it does to the SCHEDULING and not for its own
        latency: the join path's stale-head window is exactly as wide as the
        delay between a coroutine yielding at `await socket.accept()` and being
        resumed, and on a loop with a render queued in front of it that delay is
        not microseconds. This is the shape of the deployment — one core, twenty
        people, some of them only reading — rather than an amplifier invented
        for the probe.
        """
        def read_pages(n: int) -> None:
            rng = random.Random(self.args.seed + 900 + n)
            with httpx.Client(timeout=60.0) as http:
                while time.monotonic() < until:
                    record = rng.choice(ids)
                    began = time.monotonic()
                    try:
                        answer = http.get(f"{self.world.base}/detail/{record}",
                                          headers={"Cookie": harness.cookie_for("reader")})
                        status = str(answer.status_code)
                    except Exception as error:  # noqa: BLE001
                        status = type(error).__name__
                    self.ledger.record(measure.Action(
                        who=f"reader-{n}", kind=f"GET /detail [{phase}]",
                        began=began - self.zero, ms=(time.monotonic() - began) * 1000,
                        status=status, record=record))
                    time.sleep(rng.uniform(0.2, 0.6))

        threads = [threading.Thread(target=read_pages, args=(n,), daemon=True)
                   for n in range(how_many)]
        for one in threads:
            one.start()
        return threads

    # -- A: sockets that die without a close frame --------------------------

    def phase_a(self, peers: list[Peer], seconds: float) -> None:
        phase = "A-abrupt"
        self.watcher.phase = self.pulse.phase = phase
        # One person per room is never dropped, so there is always somebody in
        # the room to receive the presence frames that say the dropped person has
        # gone. Without them the room empties and the question cannot be asked.
        keep = {peers[i].login for i in range(0, len(peers), self.args.per_room)}
        droppable = [p for p in peers if p.login not in keep]
        watchers = {p.record: p for p in peers if p.login in keep}
        until = time.monotonic() + seconds
        threads = self.typing(phase, peers, until)
        drops: list[dict] = []
        while time.monotonic() < until - 4:
            time.sleep(self.args.drop_every)
            victim = self.rng.choice(droppable)
            if not victim.connected:
                continue
            watcher = watchers[victim.record]
            before_run = victim.run_length()
            before_frames = len(watcher.told)
            at = time.monotonic()
            victim.drop(rude=True)
            self.ledger.record(measure.Action(
                who=victim.login, kind="WS drop (RST)", began=at - self.zero, ms=0.0,
                status="reset", record=victim.record))
            # How long the rest of the room went on being told this person was
            # in it. Read off the roster frames the undropped member receives.
            lag = self._presence_lag(watcher, victim.login, before_frames, 6.0)
            away = self.rng.uniform(*self.args.away)
            time.sleep(max(0.0, away - (time.monotonic() - at)))
            outcome = victim.connect(self.ledger, note="after RST")
            drops.append({
                "at": round(at - self.zero, 2), "who": victim.login, "record": victim.record,
                "away_s": round(time.monotonic() - at, 2),
                "presence_lag_s": lag, "reconnect": outcome,
                "run_before": before_run, "run_after": victim.run_length(),
            })
            if outcome != "welcome":
                self.note(phase, "RECONNECT REFUSED",
                          f"{victim.login} was answered {outcome} on reconnection",
                          {"record": victim.record})
        for one in threads:
            one.join(timeout=20)
        self.phases[phase] = {
            "seconds": seconds, "drops": drops,
            "presence_lag_s": measure.percentiles(
                [d["presence_lag_s"] for d in drops if d["presence_lag_s"] is not None]),
            "never_forgotten": [d for d in drops if d["presence_lag_s"] is None],
        }

    def _presence_lag(self, watcher: Peer, login: str, seen: int, timeout: float) -> float | None:
        """Seconds from the reset to the roster frame that stops naming `login`."""
        began = time.monotonic()
        while time.monotonic() - began < timeout:
            for frame in watcher.told[seen:]:
                if frame.get("t") != "who":
                    continue
                if login not in (frame.get("people") or []):
                    return round(frame["at_"] - began, 2)
            time.sleep(0.05)
        return None

    # -- B: the five-minute wall --------------------------------------------

    def phase_b(self, peers: list[Peer], seconds: float, every: float) -> None:
        phase = "B-wall"
        self.watcher.phase = self.pulse.phase = phase
        until = time.monotonic() + seconds
        threads = self.typing(phase, peers, until)
        cycles: list[dict] = []
        while time.monotonic() < until - every / 2:
            time.sleep(every)
            at = time.monotonic()
            runs_before = {p.login: p.run_length() for p in peers}
            git_before = self._git_runs(peers)
            # Every socket, all at once, which is what `--timeout 300` does. Half
            # the rooms politely (a proxy that closes) and half by reset (a proxy
            # that vanishes), because the last-person-out commit lives in a
            # `finally` and both routes have to reach it.
            for n, peer in enumerate(peers):
                peer.drop(rude=(n % 2 == 1))
            self.ledger.record(measure.Action(
                who="wall", kind="WS wall (all sockets closed)", began=at - self.zero,
                ms=0.0, status="closed"))
            time.sleep(self.args.wall_gap)
            back = {"welcome": 0, "reload": 0, "other": 0}
            for peer in peers:
                outcome = peer.connect(self.ledger, note="after the wall")
                back[outcome if outcome in back else "other"] += 1
            time.sleep(1.5)
            git_after = self._git_runs(peers)
            behind = {
                p.login: {"typed_before_wall": runs_before[p.login],
                          "in_git_before": git_before.get(p.login),
                          "in_git_after": git_after.get(p.login),
                          "in_editor_after": p.run_length()}
                for p in peers
                if p.run_length() < runs_before[p.login]
            }
            cycles.append({
                "at": round(at - self.zero, 2), "reconnects": back,
                "committed_by_the_teardown": {
                    p.login: git_after.get(p.login, 0) - git_before.get(p.login, 0)
                    for p in peers},
                "editors_that_lost_text": behind,
            })
            if behind:
                self.note(phase, "TEXT LOST AT THE WALL",
                          f"{len(behind)} editors hold fewer of their own characters after "
                          "the teardown than before it", behind)
        for one in threads:
            one.join(timeout=20)
        self.phases[phase] = {"seconds": seconds, "every": every, "cycles": cycles}

    def _git_runs(self, peers: list[Peer]) -> dict[str, int]:
        git = pygit2.Repository(str(self.world.plan))
        head = str(git.references["refs/heads/main"].target)
        paths = harness.record_paths(self.world.plan, head)
        bodies = {
            record: (harness.read_blob(self.world.plan, head, paths[record]) or "")
            for record in {p.record for p in peers} if record in paths
        }
        return {p.login: p.run_length(bodies.get(p.record, "")) for p in peers}

    # -- C: reconnecting into the middle of a commit -------------------------

    def phase_c(self, peers: list[Peer], seconds: float) -> None:
        """The window `web.py`'s join path leaves open, aimed at deliberately.

        `coedit_socket` reads `store.head()` before `await socket.accept()` and
        uses that same commit AFTER it, in `room.absorb(_body_at(head, path))`
        and `room.settled(head, ...)`. The only thing between the two is the
        accept, so the window is one suspension wide — and `_commit_room` blocks
        the event loop for the length of a push, so a commit that becomes
        runnable while a joiner is inside that suspension is exactly the shape
        that makes the head stale.

        This phase is a PROBE and not a model of a working day: five threads open
        a socket to their room several times a second, read the `base` their
        welcome carries and leave. Nobody browses like that. The rate is there to
        put enough joins beside enough commits to answer whether the window is
        reachable at all, and the report says which of the two it is.
        """
        phase = "C-midcommit"
        self.watcher.phase = self.pulse.phase = phase
        until = time.monotonic() + seconds
        threads = self.typing(phase, peers, until)
        threads += self.browsers(phase, until, self.browsable, self.args.browsers)
        pressers = [peers[i] for i in range(0, len(peers), self.args.per_room)]
        saves: list[dict] = []
        stop = threading.Event()

        def presses(peer: Peer, offset: float) -> None:
            stop.wait(offset)
            while not stop.is_set() and time.monotonic() < until:
                # Everybody in this room stops typing, and the probe is told to
                # start opening its socket now — a few hundred microseconds
                # before the `save` frame goes down the wire, so the probe's
                # handler is inside `await socket.accept()` when the commit
                # begins. This is the aim; `--aim-ms` is how far ahead of the
                # save the socket is opened.
                self.quiet_until[peer.record] = time.monotonic() + self.args.quiet_for
                aims[peer.record].set()
                time.sleep(self.rng.uniform(0.0, self.args.aim_ms) / 1000.0)
                began = time.monotonic()
                answer = peer.save()
                self.ledger.record(measure.Action(
                    who=peer.login, kind="WS save", began=began - self.zero,
                    ms=answer.get("ms", 0.0), status=str(answer.get("t")),
                    outcome=answer.get("outcome"), commit=answer.get("commit"),
                    pushed=answer.get("pushed"), record=peer.record))
                saves.append({"at": round(began - self.zero, 2), "who": peer.login,
                              "record": peer.record, **{k: answer.get(k) for k in
                              ("t", "outcome", "commit", "pushed", "ms")}})
                stop.wait(self.args.save_every)

        stagger = self.args.save_every / max(1, len(pressers))
        pressing = [
            threading.Thread(target=presses, args=(peer, n * stagger), daemon=True)
            for n, peer in enumerate(pressers)
        ]
        bases: dict[str, list[dict]] = {p.record: [] for p in peers}
        aims = {record: threading.Event() for record in bases}
        joins = {"aimed": 0, "blind": 0, "other": 0}

        def probes(record: str) -> None:
            """A tab opening the record, reading the room's base, and closing.

            Aimed when the room says a save is about to go out, blind otherwise.
            """
            login = f"probe-{record[-2:]}"
            token = sign_session(User(login=login, member=True), harness.SECRET)
            while not stop.is_set() and time.monotonic() < until:
                aimed = aims[record].wait(self.args.probe_every)
                if aimed:
                    aims[record].clear()
                began = time.monotonic()
                try:
                    client = Client("127.0.0.1", self.world.port,
                                    f"/api/coedit/{record}",
                                    cookie=f"{SESSION_COOKIE}={token}")
                    client.send_json({"t": "hello", "seed": None, "sv": None})
                    frame = client.receive_json()
                    client.close()
                except Exception as error:  # noqa: BLE001 - a probe never fails a run
                    self.ledger.record(measure.Action(
                        who=login, kind="WS probe join", began=began - self.zero,
                        ms=(time.monotonic() - began) * 1000,
                        status=f"!{type(error).__name__}", record=record))
                    continue
                self.ledger.record(measure.Action(
                    who=login, kind=f"WS probe join [{'aimed' if aimed else 'blind'}]",
                    began=began - self.zero, ms=(time.monotonic() - began) * 1000,
                    status=str(frame.get("t")), record=record))
                if frame.get("t") == "welcome":
                    joins["aimed" if aimed else "blind"] += 1
                    bases[record].append({"at": round(time.monotonic() - self.zero, 2),
                                          "who": login, "aimed": aimed,
                                          "base": frame.get("base")})
                else:
                    joins["other"] += 1

        probing = [threading.Thread(target=probes, args=(record,), daemon=True)
                   for record in sorted(bases)]
        for one in pressing + probing:
            one.start()
        # And the ordinary churn from phase A, still running underneath.
        churn = [p for p in peers if p not in pressers]
        reconnects = 0
        while time.monotonic() < until - 3:
            time.sleep(self.args.reconnect_every)
            peer = self.rng.choice(churn)
            if not peer.connected:
                continue
            peer.drop(rude=self.rng.random() < 0.5)
            time.sleep(self.rng.uniform(0.05, 0.25))
            if peer.connect(self.ledger, note="mid-commit churn") == "welcome":
                reconnects += 1
                bases[peer.record].append(
                    {"at": round(time.monotonic() - self.zero, 2), "who": peer.login,
                     "base": peer.base})
        stop.set()
        for one in pressing + probing:
            one.join(timeout=90)
        for one in threads:
            one.join(timeout=20)
        rewinds = self._rewinds(bases, {p.record for p in peers})
        self.phases[phase] = {
            "seconds": seconds, "saves": saves, "reconnects": reconnects,
            "probe_joins": joins,
            "rewound_bases": rewinds,
            "rewinds_that_moved_this_record": [r for r in rewinds if r["file_differs"]],
            "bases": bases,
            # Evidence that the branch under test is entered at all. A room's
            # `base` is its own to move only when it commits — so if a room
            # reports more distinct bases than it made commits, the extra ones
            # came from `room.settled(head, ...)` on the join path, which is the
            # line this phase is about. Without this number "no rewinds" would be
            # a claim about a gate that might never have opened.
            "base_moved_on_join": {
                record: {
                    "joins": len(seen),
                    "distinct_bases": len({one["base"] for one in seen if one["base"]}),
                    "own_commits": len({s["commit"] for s in saves
                                        if s["record"] == record and s.get("commit")}),
                }
                for record, seen in bases.items()
            },
        }

    def _rewinds(self, bases: dict[str, list[dict]], records: set[str]) -> list[dict]:
        """A welcome whose `base` is an ancestor of one an earlier welcome carried.

        `room.base` moves forward when the room commits and is never otherwise
        the room's to move. A join that reports an older one has moved it
        backwards, which is the join path writing `room.settled(head, ...)` with
        a `head` it read before a commit landed.

        Classified by whether THIS record's file differs between the two, because
        the two cases cost different things. If it does not, the rewind is a base
        pointing at a commit that touched somebody else's record: the next write
        reads `was == stored`, retries silently and nothing is lost. If it does,
        the same join also ran `room.absorb` against the older text — which
        deletes the newer text from every open document in the room and
        broadcasts the deletion.
        """
        git = pygit2.Repository(str(self.world.plan))
        out = []
        for record, seen in bases.items():
            paths = None
            best = None
            for one in seen:
                base = one.get("base")
                if not base:
                    continue
                if best is not None and base != best:
                    try:
                        older = git.descendant_of(best, base)
                    except (KeyError, ValueError):
                        older = False
                    if older:
                        if paths is None:
                            paths = harness.record_paths(self.world.plan, best)
                        path = paths.get(record)
                        differs = bool(path) and (
                            harness.read_blob(self.world.plan, base, path)
                            != harness.read_blob(self.world.plan, best, path)
                        )
                        out.append({"record": record, "at": one["at"], "who": one["who"],
                                    "base_now": base[:10], "base_before": best[:10],
                                    "file_differs": differs})
                        self.note("C-midcommit",
                                  "ROOM BASE REWOUND (this record moved)" if differs
                                  else "room base rewound (another record moved)",
                                  f"{one['who']} joined {record} and the room reported base "
                                  f"{base[:10]}, an ancestor of {best[:10]} which an earlier "
                                  "join reported", {"record": record, "file_differs": differs})
                        continue
                if best is None or git.descendant_of(base, best):
                    best = base
        return out

    # -- D: a settled room, a commit from outside it, two people opening it ----

    def phase_d(self, peers: list[Peer], seconds: float) -> None:
        """The join path's stale head, reached the way it is actually reachable.

        Phase C aims at the window from the inside — a room commit, and a joiner
        suspended across it — and that window is one `await socket.accept()`
        wide. This is the same defect approached from where it is wide open:

        * The room is SETTLED. Everybody has the record open and nobody is
          typing this second, which is most seconds of most documents. That is
          the only state in which `elif not room.pending()` is entered at all.
        * The record is being written from OUTSIDE the room — a form save, a
          second tab, the API. `PATCH /api/record` runs its `store.write` on a
          worker thread, so it lands whenever it lands and does not block the
          loop the joiners are on.
        * TWO people open the record at once. That is what makes the head one of
          them read stale: the other one's absorb moves the room forward in
          between, and the first one resumes and puts it back.

        The signature is a document getting SHORTER while nobody deletes
        anything, caught in the reader thread by `Peer._measure`.
        """
        phase = "D-settled"
        self.watcher.phase = self.pulse.phase = phase
        until = time.monotonic() + seconds
        stop = threading.Event()
        threads = self.browsers(phase, until, self.browsable, self.args.browsers)
        # Settle every room first: a room still holding uncommitted keystrokes
        # from phase C answers `pending()` yes and the branch is never entered.
        for peer in [peers[i] for i in range(0, len(peers), self.args.per_room)]:
            if peer.connected:
                peer.save()
        records = sorted({p.record for p in peers})
        bases: dict[str, list[dict]] = {record: [] for record in records}
        joins = {"welcome": 0, "other": 0}
        sent: list = []
        lock = threading.Lock()

        def patcher(record: str, offset: float) -> None:
            """Somebody saving this record through the form, not through the room."""
            from users import Sent  # noqa: PLC0415

            from openproj.model import split_front_matter  # noqa: PLC0415

            login = f"form-{record[-2:]}"
            stop.wait(offset)
            n = 0
            with httpx.Client(base_url=self.world.base, timeout=120.0,
                              headers={"cookie": harness.cookie_for(login)}) as http:
                while not stop.is_set() and time.monotonic() < until:
                    n += 1
                    began = time.monotonic()
                    try:
                        head = http.get("/api/health").json().get("head")
                        paths = harness.record_paths(self.world.plan, head)
                        source = harness.read_blob(self.world.plan, head, paths[record])
                        marker = f"PD{record[-2:]}.{n:04d}"
                        weeks = round(1.0 + (n % 7) * 0.5, 1)
                        body = split_front_matter(source)[1].rstrip("\n")
                        answer = http.patch(f"/api/record/{record}", json={
                            "base_commit": head, "fields": {"person_weeks": weeks},
                            "body": f"{body}\n- {marker}\n"})
                        status = str(answer.status_code)
                        got = answer.json() if answer.status_code in (200, 409) else {}
                    except Exception as error:  # noqa: BLE001
                        status, got, marker, weeks, head = (
                            type(error).__name__, {}, f"PD{record[-2:]}.{n:04d}", None, None)
                    self.ledger.record(measure.Action(
                        who=login, kind="PATCH", began=began - self.zero,
                        ms=(time.monotonic() - began) * 1000, status=status,
                        outcome=got.get("outcome"), commit=got.get("commit"),
                        record=record, marker=marker))
                    with lock:
                        sent.append(Sent(login, record, marker, status, got.get("outcome"),
                                         got.get("commit"), weeks, head))
                    stop.wait(self.args.patch_every)

        def opener(record: str, which: int) -> None:
            """Somebody opening the record. Several at once, on purpose."""
            login = f"open-{record[-2:]}-{which}"
            token = sign_session(User(login=login, member=True), harness.SECRET)
            rng = random.Random(self.args.seed + which)
            while not stop.is_set() and time.monotonic() < until:
                began = time.monotonic()
                try:
                    client = Client("127.0.0.1", self.world.port, f"/api/coedit/{record}",
                                    cookie=f"{SESSION_COOKIE}={token}")
                    client.send_json({"t": "hello", "seed": None, "sv": None})
                    frame = client.receive_json()
                    client.close()
                except Exception as error:  # noqa: BLE001
                    self.ledger.record(measure.Action(
                        who=login, kind="WS open", began=began - self.zero,
                        ms=(time.monotonic() - began) * 1000,
                        status=f"!{type(error).__name__}", record=record))
                    stop.wait(0.2)
                    continue
                self.ledger.record(measure.Action(
                    who=login, kind="WS open", began=began - self.zero,
                    ms=(time.monotonic() - began) * 1000, status=str(frame.get("t")),
                    record=record))
                with lock:
                    if frame.get("t") == "welcome":
                        joins["welcome"] += 1
                        bases[record].append({"at": round(time.monotonic() - self.zero, 2),
                                              "who": login, "base": frame.get("base")})
                    else:
                        joins["other"] += 1
                stop.wait(rng.uniform(*self.args.open_every))

        workers = [threading.Thread(target=patcher, args=(record, n * 0.1), daemon=True)
                   for n, record in enumerate(records)]
        workers += [threading.Thread(target=opener, args=(record, which), daemon=True)
                    for record in records for which in range(self.args.openers)]
        for one in workers:
            one.start()
        stop.wait(seconds)
        stop.set()
        for one in workers + threads:
            one.join(timeout=90)
        rewinds = self._rewinds(bases, set(records))
        self.sent_forms = sent
        self.phases[phase] = {
            "seconds": seconds, "opens": joins, "patches": len(sent),
            "patch_statuses": _tally(one.status for one in sent),
            "rewound_bases": rewinds,
            "rewinds_that_moved_this_record": [r for r in rewinds if r["file_differs"]],
            "base_moved_on_join": {
                record: {"joins": len(seen),
                         "distinct_bases": len({one["base"] for one in seen if one["base"]})}
                for record, seen in bases.items()
            },
        }

    # -- the census, between phases ------------------------------------------

    def census(self, records: list[str], label: str) -> dict:
        """Who the server thinks is in each room when nobody is.

        Every peer is disconnected before this runs, so the only honest answer is
        one name: the census socket's own. Anything else is a seat or a member
        the bookkeeping did not let go of.
        """
        out = {}
        for record in records:
            login = f"census-{label}"
            token = sign_session(User(login=login, member=True), harness.SECRET)
            client = Client("127.0.0.1", self.world.port, f"/api/coedit/{record}",
                            cookie=f"{SESSION_COOKIE}={token}")
            try:
                client.send_json({"t": "hello", "seed": None, "sv": None})
                people, where = None, None
                began = time.monotonic()
                while time.monotonic() - began < 10:
                    frame = client.receive_json()
                    if frame.get("t") == "who":
                        people, where = frame.get("people"), frame.get("where")
                        break
                out[record] = {"people": people, "where": where}
                ghosts = [p for p in (people or []) if p != login]
                if ghosts:
                    self.note("census", "PRESENCE LEAK",
                              f"{record} still names {ghosts} with nobody connected",
                              {"record": record, "where": where})
                seats = [s for s in (where or []) if s.get("login") != login]
                if seats:
                    self.note("census", "SEAT LEAK",
                              f"{record} still draws seats for {[s['login'] for s in seats]}",
                              {"record": record})
            finally:
                client.close()
        return out

    # -- the whole run --------------------------------------------------------

    def go(self) -> int:
        args = self.args
        env = {"LOAD_ACCEPT_YIELD": str(args.accept_yield)} if args.accept_yield >= 0 else {}
        with harness.Harness(seed=args.seed, rtt_ms=args.rtt_ms, corpus="corpus",
                             size=args.size, keep=args.keep, env=env) as world:
            self.world = world
            self.zero = time.monotonic()
            before = verify.snapshot(world.plan)
            every_id = world.record_ids("task-")
            records = every_id[: args.rooms]
            # Records nobody in this run is editing, so a page read is a page
            # read and not a second writer.
            self.browsable = every_id[args.rooms : args.rooms + 40] or every_id
            if len(records) < args.rooms:
                raise RuntimeError(f"only {len(records)} records to put rooms on")
            logins = [f"ed{n:02d}" for n in range(1, args.users + 1)]
            peers = [
                Peer(world.port, logins[n], records[n // args.per_room], 2000 + n,
                     f"[CH{args.seed}.{n:02d}]")
                for n in range(args.users)
            ]
            print(f"=== coedit-churn · seed {args.seed} ===")
            print(f"{args.users} co-editors over {args.rooms} rooms "
                  f"({args.per_room} each), push rtt {args.rtt_ms} ms")
            print(f"plan: {world.corpus.records} records ({args.corpus_note}), port {world.port}")
            print(f"rooms: {', '.join(records)}\n")

            self.watcher = Watcher(world.plan, peers, self.events, self.zero)
            self.pulse = Pulse(world.base, self.ledger, self.zero)
            for peer in peers:
                if peer.connect(self.ledger, note="first") != "welcome":
                    raise RuntimeError(f"{peer.login} was not welcomed")
                peer.plant()
            time.sleep(1.0)
            self.watcher.sample()  # a floor, before anything is dropped
            self.watcher.start()
            self.pulse.start()

            began = time.monotonic()
            if "a" in args.phases:
                self.phase_a(peers, args.phase_a)
                self.deletions("A-abrupt", peers)
                print(f"-- A done at {time.monotonic() - self.zero:.0f}s")
            if "b" in args.phases:
                self.phase_b(peers, args.phase_b, args.wall_every)
                self.deletions("B-wall", peers)
                print(f"-- B done at {time.monotonic() - self.zero:.0f}s")
            if "c" in args.phases:
                self.phase_c(peers, args.phase_c)
                self.deletions("C-midcommit", peers)
                print(f"-- C done at {time.monotonic() - self.zero:.0f}s")
            if "d" in args.phases:
                self.phase_d(peers, args.phase_d)
                self.deletions("D-settled", peers)
                print(f"-- D done at {time.monotonic() - self.zero:.0f}s")
            load_seconds = time.monotonic() - began

            # Everybody presses Save and leaves, which is what makes "is every
            # character in the plan" answerable at all.
            for peer in peers:
                if peer.connected:
                    answer = peer.save()
                    self.ledger.record(measure.Action(
                        who=peer.login, kind="WS save [final]", began=time.monotonic() - self.zero,
                        ms=answer.get("ms", 0.0), status=str(answer.get("t")),
                        outcome=answer.get("outcome"), commit=answer.get("commit"),
                        pushed=answer.get("pushed"), record=peer.record))
            self.watcher.sample()
            for peer in peers:
                peer.drop(rude=False)
            time.sleep(3.0)
            self.watcher.stop()
            self.pulse.stop()
            census = self.census(records, "after")
            time.sleep(1.0)

            cpu, rss = world.cpu_seconds(), world.rss_mb()
            typed = [
                Typed(who=p.login, login=p.login, record=p.record, anchor=p.anchor,
                      expected=p.anchor + "".join(p.stream[i % len(p.stream)]
                                                  for i in range(p.typed)),
                      saves=[], joined=True, trouble=p.trouble)
                for p in peers
            ]
            world.stop()
            simulated = set(logins) | {"census-after", "reader"}
            simulated |= {f"probe-{record[-2:]}" for record in records}
            simulated |= {f"form-{record[-2:]}" for record in records}
            simulated |= {f"open-{record[-2:]}-{n}" for record in records
                          for n in range(args.openers)}
            verdict = verify.verify(world.plan, world.origin, typed, self.sent_forms,
                                    logins=simulated, before=before)
            blob = self._blob(world, peers, records, load_seconds, cpu, rss, census, verdict)
            self._print(blob, verdict)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str))
            print(f"\nwritten to {out}")
            return 0 if not verdict["findings"] or not any(
                f["severity"] in (verify.LOST, verify.DIVERGED) for f in verdict["findings"]) else 1

    def _blob(self, world, peers, records, load_seconds, cpu, rss, census, verdict) -> dict:
        return {
            "scenario": "coedit-churn",
            "args": vars(self.args),
            "world": world.describe(),
            "rooms": records,
            "seconds_of_load": round(load_seconds, 1),
            "server": {"cpu_seconds": cpu, "rss_mb": rss,
                       "cpu_fraction_of_one_core": round(cpu / load_seconds, 2)},
            "report": self.ledger.report(load_seconds),
            "phases": self.phases,
            "peers": [
                {"login": p.login, "record": p.record, "typed": p.typed,
                 "connects": p.connects, "run_in_editor": p.run_length(),
                 "reloads": p.reloads, "trouble": p.trouble, "shrinks": p.shrinks}
                for p in peers
            ],
            "events": [asdict(e) for e in self.events],
            "census_after": census,
            "samples": self.watcher.samples,
            "verify": verdict,
        }

    def _print(self, blob: dict, verdict: dict) -> None:
        print(measure.table(blob["report"]))
        print(f"\n  statuses: {blob['report']['statuses']}")
        print(f"  outcomes: {blob['report']['write_outcomes']}")
        print(f"  pushed:   {blob['report']['pushed']}")
        print(f"  server:   {blob['server']}")
        for phase, detail in self.phases.items():
            if phase == "A-abrupt":
                print(f"\n  [A] {len(detail['drops'])} abrupt resets; presence lag "
                      f"{detail['presence_lag_s']}; never forgotten: "
                      f"{len(detail['never_forgotten'])}")
            if phase == "B-wall":
                for cycle in detail["cycles"]:
                    print(f"  [B] wall at {cycle['at']}s: reconnects {cycle['reconnects']}, "
                          f"editors that lost text {len(cycle['editors_that_lost_text'])}")
            if phase == "D-settled":
                print(f"  [D] {detail['opens']} opens and {detail['patches']} form saves "
                      f"{detail['patch_statuses']}; rewound bases "
                      f"{len(detail['rewound_bases'])}, of which "
                      f"{len(detail['rewinds_that_moved_this_record'])} moved this record")
                print(f"      base moved on join: {detail['base_moved_on_join']}")
            if phase == "C-midcommit":
                print(f"      base moved on join: {detail['base_moved_on_join']}")
                print(f"  [C] {detail['reconnects']} reconnections and "
                      f"{detail['probe_joins']} probe joins against "
                      f"{len(detail['saves'])} saves; rewound bases "
                      f"{len(detail['rewound_bases'])}, of which "
                      f"{len(detail['rewinds_that_moved_this_record'])} moved this record")
        print("\n-- events --")
        interesting = [e for e in self.events if e.kind != "sampler"]
        for event in interesting[:40]:
            print(f"  [{event.at:>6.1f}s {event.phase}] {event.kind}: {event.what}")
        if not interesting:
            print("  none")
        if len(interesting) > 40:
            print(f"  ... and {len(interesting) - 40} more")
        print("\n-- verification --")
        print(verify.summary(verdict))
        print(f"  coeditors committed: "
              f"{sum(r['committed'] for r in verdict['checks']['coeditors'])} of "
              f"{sum(r['typed'] for r in verdict['checks']['coeditors'])} characters")
        print(f"  push: {json.dumps(verdict['checks']['push'])}")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--users", type=int, default=20)
    p.add_argument("--rooms", type=int, default=5)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--size", default="medium")
    p.add_argument("--rtt-ms", type=float, default=300.0)
    p.add_argument("--phase-a", type=float, default=75.0)
    p.add_argument("--phase-b", type=float, default=75.0)
    p.add_argument("--phase-c", type=float, default=60.0)
    p.add_argument("--drop-every", type=float, default=2.0)
    p.add_argument("--away", type=float, nargs=2, default=(0.6, 3.0))
    p.add_argument("--wall-every", type=float, default=25.0)
    p.add_argument("--wall-gap", type=float, default=0.5)
    p.add_argument("--save-every", type=float, default=5.0)
    p.add_argument("--reconnect-every", type=float, default=1.2)
    p.add_argument("--probe-every", type=float, default=0.25)
    p.add_argument("--aim-ms", type=float, default=2.0)
    p.add_argument("--quiet-for", type=float, default=0.8)
    p.add_argument("--browsers", type=int, default=4)
    p.add_argument("--phases", default="abcd")
    # Milliseconds of suspension charged to `await socket.accept()`. -1 leaves
    # it alone, which is what the wsproto implementation this project depends
    # on actually does; 0 is one loop pass, which is the least the
    # `websockets` implementation can cost. See `serve_load.charge_accept`.
    p.add_argument("--accept-yield", type=float, default=-1.0)
    p.add_argument("--phase-d", type=float, default=45.0)
    p.add_argument("--patch-every", type=float, default=0.8)
    p.add_argument("--openers", type=int, default=3)
    p.add_argument("--open-every", type=float, nargs=2, default=(0.1, 0.4))
    p.add_argument("--keep", action="store_true")
    p.add_argument("--out", default="design/probes/load/coedit-churn.json")
    args = p.parse_args(argv)
    args.per_room = max(1, args.users // args.rooms)
    args.corpus_note = f"corpus/{args.size}"
    return args


def main(argv: list[str] | None = None) -> int:
    return Run(parse(argv)).go()


if __name__ == "__main__":
    raise SystemExit(main())
