"""Three kinds of simulated person, one thread each, all genuinely at once.

READER      opens the landing, a filtered view, the table and a record page, in
            a loop, with a pause between pages.
FORM WRITER opens a record page, changes a field AND appends a line to the
            shaping document, and PATCHes it — which is what the page does.
CO-EDITOR   opens the record's websocket, seeds a document, and types real CRDT
            updates at a human rate, applying everybody else's.

**Threads, not asyncio.** The co-editor already needs one — `tests/wsclient.py`
is a blocking socket and `room.Member` reads it on a thread — and a driver that
was half a loop and half a pool is a driver whose own scheduling is part of
every number it prints. Everything here is I/O bound, so the GIL is not the
ceiling; the one exception is the co-editor's `apply`, which is real CPU in this
process and is why `room.py` says the driver must stay cheap.

**Every write leaves a marker that survives into git, or it is not a
measurement.** The markers are designed first and the rest follows:

* a form writer appends `- [ ] LM<seed>.<w>.<n> …` to the body it was shown.
  Append-only, so a later save cannot legitimately erase an earlier one, which
  is what makes "committed, or explicitly refused, or LOST" a decidable
  question. It is also, deliberately, the commonest co-editing shape there is:
  two people adding a bullet under the same heading.
* a co-editor first inserts a home token `[CM<seed>.<k>]` and thereafter types
  one character at a time immediately after its own last character, so its
  contribution is one contiguous run in the document and "is every character
  present" is a substring test rather than a guess.

Everything typed is ASCII on purpose. The document is addressed in UTF-8 bytes
(`coedit.byte_offset`) and the browser's half of the same splice counts UTF-16
code units — that mismatch is a real defect and it has its own probe,
`tests/load/probe_emoji.py`. Mixing it in here would make every lost character
ambiguous between two findings.
"""

from __future__ import annotations

import base64
import json
import random
import string
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import harness
import httpx
import room
from measure import Action, Ledger

from openproj import coedit

# The characters a co-editor types, rotated per person so two of them typing at
# once cannot produce a run that reads as either one's.
ALPHABET = string.ascii_lowercase + string.digits

# Five characters a second, and a pause at the end of every line. Composing
# prose, not pasting: the effective rate is about 4.4/s, which is the middle of
# the 4-6 the brief asks for and is a number two runs can be compared on.
CHARS_PER_SECOND = 5.0
LINE_LENGTH = 40


class Person(threading.Thread):
    """One simulated human. Runs until the deadline, records everything."""

    def __init__(
        self,
        who: str,
        login: str,
        world: harness.Harness,
        ledger: Ledger,
        seed: int,
        deadline: float,
        zero: float,
    ) -> None:
        super().__init__(name=who, daemon=True)
        self.who = who
        self.login = login
        self.world = world
        self.ledger = ledger
        self.deadline = deadline
        self.zero = zero
        self.rng = random.Random(f"{seed}:{who}")
        self.failed: str | None = None

    def note(self, **kwargs) -> None:
        self.ledger.record(Action(who=self.who, began=round(time.monotonic() - self.zero, 3),
                                  **kwargs))

    def run(self) -> None:
        try:
            self.work()
        except Exception as error:  # noqa: BLE001 - a driver thread may not take the run down
            self.failed = f"{type(error).__name__}: {error}"

    def work(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def begin(self, deadline: float) -> None:
        """Set the wall clock, after everybody has connected.

        Separate from `__init__` because opening twenty websockets takes time
        that is setup and not load: counted into the window it would make the
        first second of every run a connection storm nobody asked for.
        """
        self.deadline = deadline

    def more(self) -> bool:
        return time.monotonic() < self.deadline


class Reader(Person):
    """Somebody with the plan open who is not editing it.

    The rotation is the four routes a person actually moves between, and it
    includes `/detail/<id>` deliberately: that page is 240 ms of pure Python on a
    561-record plan and it is the page every co-editor is sitting on, so a read
    floor measured on `/` alone is a floor nobody stands on.
    """

    PAGES = ("/", "/table", "/issues")

    # Every page a person can be sitting on that is drawn from the index. Used by
    # `tests/load/readload.py`, which is measuring the read path's ceiling and so
    # may not leave the two most expensive renderers out of the rotation: `/graph`
    # and `/timeline` are drawn from the same `index_now()` and are the two the
    # three-route default never touches.
    ALL_PAGES = ("/", "/issues", "/table", "/graph", "/timeline")

    def __init__(self, *args, ids: list[str], think: float = 0.4,
                 pages: tuple[str, ...] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ids = ids
        self.think = think
        if pages:
            self.PAGES = tuple(pages)
        self.client = httpx.Client(
            base_url=self.world.base,
            timeout=30.0,
            headers={"cookie": harness.cookie_for(self.login)},
        )

    def work(self) -> None:
        with self.client:
            turn = self.rng.randrange(len(self.ids))
            while self.more():
                page = self.PAGES[turn % len(self.PAGES)]
                self.fetch(page, f"GET {page}")
                if not self.more():
                    return
                entity = self.ids[turn % len(self.ids)]
                self.fetch(f"/detail/{entity}", "GET /detail/<id>", entity)
                turn += 1

    def fetch(self, path: str, kind: str, entity: str | None = None) -> None:
        begun = time.monotonic()
        try:
            answer = self.client.get(path)
            status = str(answer.status_code)
        except Exception as error:  # noqa: BLE001
            status = type(error).__name__
        self.note(kind=kind, ms=(time.monotonic() - begun) * 1000, status=status, entity=entity)
        time.sleep(self.think)


@dataclass
class Sent:
    """One form save, as the harness knows it — the row `verify.py` judges."""

    who: str
    entity: str
    marker: str
    status: str
    outcome: str | None
    commit: str | None
    person_weeks: float
    base: str


class FormWriter(Person):
    """Somebody editing a record through the page and pressing Save.

    The sequence is the browser's: open the record (`GET /detail/<id>` — the
    240 ms the person waits), then PATCH with the body they were shown plus one
    new line, and one changed field.

    The body itself is read out of the plan repository at the same commit
    `/api/health` reported, rather than through an API. There is no route that
    hands a script a record's markdown source — the page carries it in the
    textarea — and a harness that fetched `/api/index.json` for it would be
    pulling every body in the plan (about 750 kB on the medium corpus) on every
    save, which is a cost no browser pays and which would dominate the very
    numbers this is for.

    `stale=True` never re-reads the base commit: that is a tab left open, which
    is the case the compare-and-swap exists for and the one that refuses.
    """

    # Where the two contending edits are made in `mixed`, by heading rather than
    # by line number: the corpus's bodies are shaping documents and the heading
    # is what a person aims at. Falls back to line 1 on a body that has none.
    ANCHOR = "## Rabbit holes"

    def __init__(self, *args, entity: str, gap: float = 2.0, gap_max: float | None = None,
                 stale: bool = False, style: str = "append", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.gap = gap
        # A range, not a constant. Twenty people who all pause for exactly the
        # same number of seconds are twenty people who arrive at the writer lock
        # in lockstep, and the convoy that produces is the harness's, not the
        # application's. `gap_max=None` keeps the old fixed pause so that every
        # scenario measured before this flag existed still means what it did.
        self.gap_max = gap_max
        self.stale = stale
        self.style = style
        self.sent: list[Sent] = []
        self.held: str | None = None
        self.client = httpx.Client(
            base_url=self.world.base, timeout=120.0,
            headers={"cookie": harness.cookie_for(self.login)},
        )

    def work(self) -> None:
        paths = harness.record_paths(self.world.plan, harness.head_of(self.world.plan))
        path = paths[self.entity]
        n = 0
        with self.client:
            while self.more():
                n += 1
                self.open_page()
                if not self.more():
                    return
                base = self.base_commit()
                if base is None:
                    continue
                body = harness.read_blob(self.world.plan, base, path)
                if body is None:
                    self.note(kind="PATCH", ms=0.0, status="no-such-blob", entity=self.entity)
                    continue
                self.save(base, body, n)
                time.sleep(self.pause())

    def pause(self) -> float:
        """How long this person sits before saving again.

        Drawn from this person's own seeded `Random`, so two runs with the same
        flags issue the same cadence and can be compared.
        """
        if self.gap_max is None or self.gap_max <= self.gap:
            return self.gap
        return self.rng.uniform(self.gap, self.gap_max)

    def open_page(self) -> None:
        begun = time.monotonic()
        try:
            answer = self.client.get(f"/detail/{self.entity}")
            status = str(answer.status_code)
        except Exception as error:  # noqa: BLE001
            status = type(error).__name__
        self.note(kind="GET /detail/<id>", ms=(time.monotonic() - begun) * 1000,
                  status=status, entity=self.entity)

    def base_commit(self) -> str | None:
        if self.stale and self.held:
            return self.held
        begun = time.monotonic()
        try:
            answer = self.client.get("/api/health")
            head = answer.json().get("head")
            self.note(kind="GET /api/health", ms=(time.monotonic() - begun) * 1000,
                      status=str(answer.status_code))
            self.held = head
            return head
        except Exception as error:  # noqa: BLE001
            self.note(kind="GET /api/health", ms=(time.monotonic() - begun) * 1000,
                      status=type(error).__name__)
            return None

    def save(self, base: str, source: str, n: int) -> None:
        from openproj.model import split_front_matter  # noqa: PLC0415

        _, body = split_front_matter(source)
        marker = self.marker(n)
        # `person_weeks` moves as well, so the frontmatter merge runs on every
        # save and not only the body merge. It is last-writer-wins by design and
        # is checked as "a value somebody actually sent", never as a marker.
        weeks = round(1.0 + (n % 7) * 0.5, 1)
        payload = {
            "base_commit": base,
            "fields": {"person_weeks": weeks},
            "body": self.edited(body, marker),
        }
        begun = time.monotonic()
        status, outcome, commit = "", None, None
        try:
            answer = self.client.patch(f"/api/entity/{self.entity}", json=payload)
            status = str(answer.status_code)
            if answer.status_code in (200, 409):
                got = answer.json()
                outcome, commit = got.get("outcome"), got.get("commit")
        except Exception as error:  # noqa: BLE001
            status = type(error).__name__
        self.note(kind="PATCH", ms=(time.monotonic() - begun) * 1000, status=status,
                  outcome=outcome, commit=commit, entity=self.entity, marker=marker)
        self.sent.append(Sent(self.who, self.entity, marker, status, outcome, commit, weeks, base))

    def marker(self, n: int) -> str:
        return f"LM{self.who.replace('-', '')}.{n:04d}"

    def edited(self, body: str, marker: str) -> str:
        """The body this person is about to send, with exactly one edit in it.

        Three styles, and the two that are not `append` exist to put two
        different people's edits at the SAME line of the same document — which
        is the shape `store._merge_body` gets wrong. It calls two edits a
        conflict only where their spans OVERLAP by a half-open test, and an
        insertion has an EMPTY span, so an insertion at line N and a replacement
        starting at line N satisfy neither arm and are merged silently; the
        assembly loop below then walks the union of both sides' spans with one
        cursor and drops whichever of the two the set happens to yield second.

        `replace` therefore rewrites two lines into one **without discarding
        their text** — it joins them and adds its marker. If it deleted them, a
        marker somebody else had legitimately inserted into that range would
        vanish for an honest reason and `verify.py` would report a loss the
        application had not caused. Every style here is append-only in the sense
        that matters: no accepted save may ever remove another accepted save's
        marker.
        """
        lines = body.rstrip("\n").split("\n")
        if self.style == "append" or len(lines) < 4:
            lines.append(f"- [ ] {marker} appended by {self.login}")
            return "\n".join(lines) + "\n"
        try:
            at = lines.index(self.ANCHOR)
        except ValueError:
            at = 0
        if self.style == "insert":
            lines.insert(at + 1, f"- [ ] {marker} inserted by {self.login}")
        else:
            taken = lines[at + 1 : at + 3] or [""]
            lines[at + 1 : at + 3] = [" ".join(x.strip() for x in taken) + f" <RW {marker}>"]
        return "\n".join(lines) + "\n"


class Typist(room.Member):
    """A `room.Member` that types where its own last character is.

    The find and the insert have to be one step, and `Member.type` computes no
    offset — so this takes the member's own lock around both. Without it a
    remote update applied between the two moves the anchor and the character
    lands inside somebody else's sentence, which would be the harness inventing
    the defect it is looking for.
    """

    def type_after(self, anchor: str, typed: int, what: str) -> str:
        with self._lock:
            body = str(self.text)
            at = body.find(anchor)
            if at < 0:
                return "anchor-gone"
            where = at + len(anchor) + typed
            if where > len(body):
                return "anchor-short"
            before = self.doc.get_state()
            # The document is addressed in UTF-8 bytes and this offset is a
            # Python one. `coedit.byte_offset` is the app's own conversion, used
            # rather than restated: the two spaces are both `int` and mixing them
            # raises nothing at all.
            self.text.insert(coedit.byte_offset(body, where), what)
            update = self.doc.get_update(before)
        self.client.send_json({"t": "update", "u": base64.b64encode(update).decode()})
        return "typed"


@dataclass
class Typed:
    """What one co-editor put in the document, as the harness knows it."""

    who: str
    login: str
    entity: str
    anchor: str
    expected: str = ""
    saves: list[dict] = field(default_factory=list)
    joined: bool = False
    trouble: list[str] = field(default_factory=list)


class CoEditor(Person):
    """Somebody typing into the shaping document over the websocket.

    4-6 characters a second with a pause every dozen or so, which is what a
    person composing a sentence looks like, and — importantly — never twenty
    seconds of silence. `QUIET_SECONDS` is reset on every update, so a room with
    anybody typing in it never reaches its own commit window; that is finding 1
    of the co-edit reading and this driver is shaped so that a run reproduces it
    rather than accidentally avoiding it.

    `save_every` forces an explicit Save on a clock (0 = never during the run).
    `save_at_end` presses Save once when the window closes, which is what makes
    "was every character committed" answerable at all — without it the honest
    answer for every run is "no, and the reason is that nobody saved".
    """

    # The class `connect` opens. A scenario that needs the socket instrumented —
    # timestamping every applied update, say — subclasses `Typist` and names it
    # here rather than reimplementing the join. Default is exactly what it was.
    TYPIST = Typist

    def plant_at(self, body: str) -> int:
        """Where in the document this person starts, as a code-point index.

        The end of the document by default, which is what this always did and
        what every scenario written before this hook existed still measures.
        `tests/load/adversarial.py` overrides it to put people under a heading in
        the MIDDLE of a shaping document, because where they sit decides what
        they collide with: a room whose every line is the last line of the file
        conflicts with any append anybody makes, and that would make one merge
        shape look like the whole merge story.
        """
        return len(body)

    def planted(self) -> str:
        """What this person writes into the document the moment they arrive.

        A hook and not a literal, because `tests/load/adversarial.py` needs two
        people typing on either side of ONE character: the left-hand person
        plants the emoji and both anchors in a single insert, and the right-hand
        person plants nothing and waits for its anchor to arrive. Two anchors
        appended independently would be ordered by whichever broadcast landed
        first, which is the harness deciding the thing being measured.

        Returning "" means "plant nothing". Everything else is unchanged: the
        default is exactly the newline-and-anchor this always wrote.
        """
        return "\n" + self.anchor

    def __init__(
        self,
        *args,
        entity: str,
        client_id: int,
        seed: int,
        save_every: float = 0.0,
        save_at_end: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.client_id = client_id
        self.save_every = save_every
        self.save_at_end = save_at_end
        self.anchor = f"[CM{seed}.{client_id - 1000}]"
        self.stream = ALPHABET[(client_id - 1000) % len(ALPHABET) :] + ALPHABET
        self.typed = 0
        self.member: Typist | None = None
        self.result = Typed(self.who, self.login, entity, self.anchor)

    # -- joining, before the clock starts -----------------------------------

    def connect(self) -> None:
        """Open the socket and plant the anchor.

        Not called `join`: this is a `threading.Thread`, and `Thread.join` means
        the opposite of joining a room.

        Done from the main thread before the window opens, so that connecting
        twenty sockets is not measured as typing latency and so that a room that
        refuses the handshake fails the run rather than quietly producing a
        person who typed nothing.
        """
        begun = time.monotonic()
        self.member = self.TYPIST(
            self.world.port, self.login, self.entity, self.client_id, applies=True
        )
        self.note(kind="WS join", ms=(time.monotonic() - begun) * 1000, status="joined",
                  entity=self.entity)
        self.result.joined = True
        planting = self.planted()
        if not planting:
            return
        with self.member._lock:
            body = str(self.member.text)
            before = self.member.doc.get_state()
            self.member.text.insert(coedit.byte_offset(body, self.plant_at(body)), planting)
            update = self.member.doc.get_update(before)
        self.member.client.send_json(
            {"t": "update", "u": base64.b64encode(update).decode()}
        )

    def work(self) -> None:
        assert self.member is not None
        next_save = time.monotonic() + self.save_every if self.save_every else None
        while self.more():
            begun = time.monotonic()
            character = self.stream[self.typed % len(self.stream)]
            answer = self.member.type_after(self.anchor, self.typed, character)
            if answer == "typed":
                self.typed += 1
            else:
                self.result.trouble.append(f"{answer} at {self.typed} typed")
            self.note(kind="WS keystroke", ms=(time.monotonic() - begun) * 1000,
                      status=answer, entity=self.entity)
            if self.member.gone:
                self.result.trouble.append(f"socket gone: {self.member.gone}")
                return
            if next_save and time.monotonic() >= next_save:
                self.press_save()
                next_save = time.monotonic() + self.save_every
            # A rate, and a pause at the end of a line rather than a coin toss
            # per character. The coin toss was here first and it is a worse
            # model twice over: a person does not stop mid-word, and a 8%
            # chance of up to two seconds gave one seeded run three pauses in
            # ten keystrokes — 1.8 characters a second where the docstring
            # promised four to six. A rate you can state is a rate two runs can
            # be compared on.
            time.sleep(self.rng.uniform(0.9, 1.1) / CHARS_PER_SECOND)
            if self.typed and self.typed % LINE_LENGTH == 0:
                time.sleep(self.rng.uniform(0.8, 1.6))

    # -- saving and leaving, after the clock stops --------------------------

    def press_save(self, timeout: float = 60.0) -> dict:
        """Press Save and wait for the room's answer.

        The answer matters more than the latency: `saved` is the ONE frame in the
        whole application that carries `WriteResult.pushed`, so this is the only
        place a harness can see whether a commit reached the remote.
        """
        assert self.member is not None
        seen = len(self.member.told)
        begun = time.monotonic()
        self.member.save({})
        answer: dict = {"t": "no answer"}
        while time.monotonic() - begun < timeout:
            fresh = self.member.told[seen:]
            for frame in fresh:
                if frame.get("t") in ("saved", "refused", "nothing"):
                    answer = frame
                    break
            if answer["t"] != "no answer":
                break
            time.sleep(0.05)
        ms = (time.monotonic() - begun) * 1000
        self.note(
            kind="WS save",
            ms=ms,
            status=str(answer.get("t")),
            outcome=answer.get("outcome"),
            commit=answer.get("commit"),
            pushed=answer.get("pushed"),
            entity=self.entity,
            note=answer.get("why"),
        )
        record = {"t": answer.get("t"), "outcome": answer.get("outcome"),
                  "commit": answer.get("commit"), "pushed": answer.get("pushed"),
                  "why": answer.get("why"), "typed_by_then": self.typed, "ms": round(ms, 1)}
        self.result.saves.append(record)
        return record

    def finish(self) -> Typed:
        self.result.expected = self.anchor + "".join(
            self.stream[i % len(self.stream)] for i in range(self.typed)
        )
        if self.member is not None:
            if self.save_at_end and not self.member.gone:
                self.press_save()
            self.member.close()
        return self.result


def commit_log(plan: Path) -> list[dict]:
    """Who committed what, for the report. `store._commit` puts the writer in the
    author field, so this is the attribution the plan will show."""
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(plan))
    return [
        {"sha": str(one.id)[:10], "author": one.author.name,
         "subject": one.message.splitlines()[0]}
        for one in git.walk(git.references["refs/heads/main"].target)
    ]


def dump(thing) -> str:
    return json.dumps(thing, indent=2, sort_keys=True, default=str)
