"""Fifteen people typing in ONE room at once, and what git has at the end.

`tests/load/probe_fanout.py` asks part of this already, with a single loop that
types a character for every member in turn at offset 0. That measures the wire
and nothing else: nobody has an identity, nothing is verified against git, and a
document everybody writes to position 0 of is not a document anybody could read.

This is the same question asked so that the ANSWER IS DECIDABLE:

* fifteen `users.CoEditor` threads, each typing at a rate, each at ITS OWN
  anchor, so every person's contribution is one contiguous run and "did every
  character survive" is a substring test rather than a guess;
* one of them typing astral characters, combining marks, a ZWJ sequence and a
  regional-indicator pair, because `coedit.byte_offset` converts code points to
  UTF-8 bytes and `AGENTS.md` records a shipped defect in the *other* half of
  that same splice;
* a propagation marker `§<who>.<seq>§` every `MARK_EVERY` keystrokes, timestamped
  at the keypress and again when the bytes left the driver, and timestamped a
  third time by every other member's reader thread — so the keystroke-to-receipt
  latency is measured on the same clock at both ends;
* and `tests/load/verify.py` over the bare repository afterwards, always,
  because a propagation percentile with no integrity check is half an answer.

**The two questions this exists for.**

1. `Room.apply` restarts `_quiet_since` on every update and `_watch` commits at
   `quiet_for() >= QUIET_SECONDS` (20 s). Fifteen people typing is an update
   every ~13 ms, so the prediction is that the room NEVER commits while anybody
   is typing. What that costs is measured rather than asserted: the characters
   typed and not committed at the moment typing stops are the text this process
   would lose if it died there, and `--min-instances 0` plus `--timeout 300`
   mean this process ends often.
2. Whether the commit, when it finally comes, has everything.

Then the same run again with one person pressing Save mid-storm — which is the
one path that commits while fourteen other people are typing into the snapshot
it is taking — and a third, shorter run with a 600 ms push charged inside
pygit2, because `_commit_room` does its `store.write` on the event loop on
purpose and that is where a room's commit becomes everybody's latency.

**Two things the instrument had to be taught, both of which it got wrong first.**

*Silence is not a stall.* The stall is measured as a gap between two consecutive
updates applied at ONE socket, and a gap only counts when other people put
updates on the wire during it (`others_sent_meanwhile`). Without that test the
first pass reported a 971 ms outage at t=8.19 in a run with a 0 ms push and in a
run with a 600 ms one: it was fifteen typists taking their end-of-line pause
together, because they all start at once and all type at the same rate. The
pauses and the propagation markers are both staggered per person now, and a gap
with nothing sent into it is reported separately from a stall.

*A keystroke is two frames, not one.* `render.py:sit()` sends `{"t":"at"}`
whenever the caret lands somewhere new, which while typing is every character,
and the server answers each one with a `who` frame — the whole roster and every
caret — to everybody else. `--carets` sends them. It roughly doubles the frames
and multiplies the bytes by seventeen, so every byte-per-second number taken
without it is a floor and not a measurement.

Bounded: `--seconds` of typing per run and nothing longer. Shape, not soak.
"""

from __future__ import annotations

import argparse
import bisect
import json
import resource
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness  # noqa: E402  - sets sys.path for `openproj` and names the secret
import measure  # noqa: E402
import users  # noqa: E402
import verify  # noqa: E402

ROOT = harness.ROOT

# Fifteen distinct logins. Not six cycled: a room credits its commit from the
# characters each SOCKET typed, and two sockets sharing a login would make the
# attribution half of that unreadable while changing none of the timings.
LOGINS = harness.PEOPLE + [
    "havogt", "samkellerhals", "tehrengruber", "ninaburg", "stubbiali",
    "cponder", "dropd", "ckuehnlein", "philip-paul-mueller",
]

# One propagation marker every this many keystrokes, on a residue that differs
# per person: at 4.4 characters a second that is a marker every ~3.4 s each, and
# with fifteen people on fifteen residues they are spread evenly rather than
# arriving all together — ~4.4 markers and ~62 arrival samples a second.
MARK_EVERY = 15

# What the fifteenth person types. Every entry is one "keystroke" and several of
# them are more than one code point, which is the whole point: the document is
# addressed in UTF-8 BYTES (`pycrdt.Text`), the driver's offsets are Python CODE
# POINTS, and the browser that is not in this test counts UTF-16 CODE UNITS.
# Byte lengths are written down because they are what the middle space uses.
MULTIBYTE = [
    "\U0001f44d",                                   # 👍  1 cp, 4 bytes, 2 UTF-16 units
    "a",                                            #     1 cp, 1 byte
    "é",                                      # é   2 cp, 3 bytes (combining acute)
    "—",                                       # —   1 cp, 3 bytes
    "\U0001f916",                                   # 🤖  1 cp, 4 bytes, surrogate pair
    "b",
    "\U0001f1ee\U0001f1f9",                         # 🇮🇹  2 cp, 8 bytes, two regional indicators
    "ñ",                                      # ñ   2 cp, 3 bytes (combining tilde)
    "\U0001f468‍\U0001f469‍\U0001f467",   # 👨‍👩‍👧 5 cp, 18 bytes, two ZWJs
    "c",
]

# The characters this run looks for when it asks whether anything was mangled.
REPLACEMENT = "�"
ZWJ = "‍"


@dataclass
class Ping:
    """One marker, and the two moments it can honestly be measured from.

    `pressed` is when the simulated finger came down — it includes the driver's
    own `str(Y.Text)`, the local insert and the base64, which are the browser's
    costs in production and are NOT the server's. `wire` is when `send_json`
    returned, which is the last instant this process owned the bytes. Both are
    reported; the difference between them is how much of a number is the
    harness.
    """

    token: str
    who: str
    pressed: float
    wire: float


class GapTypist(users.Typist):
    """A `Typist` that timestamps every update it applies.

    This is the instrument for the stall, and it does not depend on a marker
    happening to be in flight. Fifteen people typing is an update arriving at
    each socket about every 15 ms; `_commit_room` does its `store.write` — push
    included — synchronously on the event loop, so while it runs nothing is read
    off any socket and nothing is drained to any socket. The length of that is
    therefore exactly the largest gap between two consecutive arrivals, measured
    by somebody who is not the person saving.

    The first pass of this run measured the stall with propagation markers and
    could not see it: all fifteen typists start together at the same rate, so
    their markers cluster, and the save at t=20.1 fell in the gap between two
    clusters. A measurement that only fires when something happens to be in
    flight is not a measurement of silence.
    """

    def __init__(self, *args, **kwargs) -> None:
        # Before `super().__init__`, which starts the reader thread that writes
        # to this list.
        self.arrivals: list[float] = []
        super().__init__(*args, **kwargs)

    def _mark(self) -> None:
        self.arrivals.append(time.monotonic())
        super()._mark()


class RoomTypist(users.CoEditor):
    """A `CoEditor` whose keystrokes may be more than one code point.

    `CoEditor` rebuilds its expectation from `stream` at the end, which is only
    true while every keystroke is exactly one character of a fixed rotation.
    Here a keystroke can be a marker or a five-code-point family emoji, so what
    was typed is RECORDED as it is typed and the expectation is the record.
    """

    TYPIST = GapTypist

    def __init__(self, *args, pieces: list[str], pings: list, pings_lock,
                 save_after: float | None = None, carets: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Every person emits a marker on a different residue of the cadence.
        # Without this all fifteen emit on the same step, they all started
        # together and they all type at the same rate, so the markers arrive in
        # bursts with three seconds of nothing between them — and an event that
        # falls in one of those gaps is invisible to every percentile here.
        self.mark_phase = (self.client_id - 1000) % MARK_EVERY
        # And a different point in the line to pause at. All fifteen start
        # together and type at the same rate, so an unstaggered pause is fifteen
        # people falling silent at the same instant — which the first
        # instrumented pass duly reported as a 971 ms server stall at t=8.19 in
        # both a 0 ms and a 600 ms run. It was step 40 of the typing loop.
        self.line_phase = self.rng.randrange(users.LINE_LENGTH)
        self.pieces = pieces
        self.pings = pings
        self.pings_lock = pings_lock
        self.save_after = save_after      # seconds into the window, or None
        # `{"t":"at"}` after every keystroke, the way the real editor does it.
        # `render.py:sit()` sends the caret whenever it lands somewhere new and
        # dedupes only against the last position it sent, so typing sends one
        # per character — and the server answers each one with a `who` frame,
        # roster and all, to everybody else. That is a SECOND fan-out of the
        # same size as the update fan-out and a much larger frame, and leaving
        # it out makes every byte-per-second number here a floor.
        self.carets = carets
        self.caret_frames = 0
        self.written: list[str] = []
        self.after = 0                    # code points typed after the anchor
        self.step = 0
        self.marks_sent = 0
        self.save_pressed_at: float | None = None
        self.save_answer: dict | None = None

    def work(self) -> None:
        assert self.member is not None
        began = time.monotonic()
        save_at = began + self.save_after if self.save_after is not None else None
        while self.more():
            self.step += 1
            if self.step % MARK_EVERY == self.mark_phase:
                self.marks_sent += 1
                token = f"{self.client_id - 1000:02d}.{self.marks_sent:03d}"
                piece = f"§{token}§"
            else:
                token = None
                piece = self.pieces[self.step % len(self.pieces)]
            pressed = time.monotonic()
            answer = self.member.type_after(self.anchor, self.after, piece)
            wire = time.monotonic()
            if answer == "typed":
                self.written.append(piece)
                self.after += len(piece)
                self.typed = self.after
                if self.carets:
                    self.member.sit(self.after + 1000 * (self.client_id - 1000))
                    self.caret_frames += 1
                if token is not None:
                    with self.pings_lock:
                        self.pings.append(Ping(token, self.who, pressed, wire))
            else:
                self.result.trouble.append(f"{answer} after {self.after} code points")
            self.note(kind="WS keystroke", ms=(wire - pressed) * 1000, status=answer,
                      entity=self.entity)
            if self.member.gone:
                self.result.trouble.append(f"socket gone: {self.member.gone}")
                return
            if save_at is not None and self.save_pressed_at is None and time.monotonic() >= save_at:
                # Mid-storm, from this thread, exactly the way the button works:
                # the person who pressed it stops typing until the room answers.
                self.save_pressed_at = time.monotonic()
                self.save_answer = self.press_save()
            time.sleep(self.rng.uniform(0.9, 1.1) / users.CHARS_PER_SECOND)
            if (self.step + self.line_phase) % users.LINE_LENGTH == 0:
                time.sleep(self.rng.uniform(0.8, 1.6))

    def finish(self) -> users.Typed:
        self.result.expected = self.anchor + "".join(self.written)
        if self.member is not None:
            if self.save_at_end and not self.member.gone:
                self.press_save()
            self.member.close()
        return self.result


class CommitWatch(threading.Thread):
    """Every commit the plan gained, and when, sampled from outside the server.

    A thread and not a check at the end, because "did the room ever commit while
    people were typing" is a question about the MIDDLE of the window and the
    final head cannot answer it.
    """

    def __init__(self, plan: Path, zero: float, every: float = 0.4) -> None:
        super().__init__(daemon=True)
        self.plan = plan
        self.zero = zero
        self.every = every
        self.seen: list[dict] = []
        # `_halt` and not `_stop`: `Thread._stop` is a method CPython calls from
        # `join`, and shadowing it with an Event makes join raise "'Event' object
        # is not callable" AFTER the measurement and before the verification.
        self._halt = threading.Event()
        self._head = harness.head_of(plan)

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                head = harness.head_of(self.plan)
            except Exception:  # noqa: BLE001 - a repository mid-write
                head = self._head
            if head != self._head:
                self._head = head
                self.seen.append({"at": round(time.monotonic() - self.zero, 2),
                                  "head": head[:10]})
            self._halt.wait(self.every)

    def stop(self) -> list[dict]:
        self._halt.set()
        self.join(timeout=5)
        return self.seen


def raw_blob(plan: Path, commit: str, path: str) -> bytes:
    """The file's bytes, undecoded. The decoded reader cannot see mojibake."""
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(plan))
    tree = git[git[commit].tree_id]
    entry = tree
    for part in path.split("/"):
        entry = entry / part
    return bytes(entry.data)


def _body_of(text: str, path: str) -> str:
    """The body a room is holding, read the way `_body_at` reads it."""
    from openproj.model import parse_text, split_front_matter  # noqa: PLC0415

    try:
        return parse_text(text, path).body
    except ValueError:
        return split_front_matter(text)[1]


def propagation(pings: list[Ping], people: list[RoomTypist], began: float) -> dict:
    """One client's keystroke to every other client's receipt.

    A sample per (marker, other member), not per marker: fan-out is the thing
    under measurement and a p99 over senders would hide the fourteenth recipient
    behind the first.

    A TIMELINE as well as percentiles, because the interesting event in two of
    these three runs happens at one instant — somebody presses Save and
    `_commit_room` does a synchronous `store.write` on the event loop — and a p99
    over ninety seconds is exactly the shape that hides a two-second stall.
    """
    end_to_end: list[float] = []
    from_wire: list[float] = []
    expected = missed = 0
    per_person: dict[str, list[float]] = {}
    timeline: list[dict] = []
    for ping in pings:
        landed: list[float] = []
        for person in people:
            if person.who == ping.who or person.member is None:
                continue
            expected += 1
            at = person.member.marks.get(ping.token)
            if at is None:
                missed += 1
                continue
            end_to_end.append((at - ping.pressed) * 1000)
            from_wire.append((at - ping.wire) * 1000)
            landed.append((at - ping.wire) * 1000)
            per_person.setdefault(person.who, []).append((at - ping.wire) * 1000)
        if landed:
            timeline.append({
                "at": round(ping.pressed - began, 2),
                "sender": ping.who,
                "recipients": len(landed),
                "p50_ms": round(sorted(landed)[len(landed) // 2], 2),
                "max_ms": round(max(landed), 2),
            })
    timeline.sort(key=lambda row: row["at"])
    worst = max(timeline, key=lambda row: row["max_ms"], default=None)
    return {
        "markers_sent": len(pings),
        "arrivals_expected": expected,
        "arrivals_seen": expected - missed,
        "arrivals_missing": missed,
        "keypress_to_receipt_ms": measure.percentiles(end_to_end),
        "wire_to_receipt_ms": measure.percentiles(from_wire),
        "per_recipient_p90_ms": {
            who: measure.percentiles(v)["p90"] for who, v in sorted(per_person.items())
        },
        "worst_marker": worst,
        "timeline": timeline,
    }


def encoding(plan: Path, head: str, path: str, multibyte_who: str,
             people: list[RoomTypist]) -> dict:
    """Did the astral characters survive the room, the merge and git?"""
    raw = raw_blob(plan, head, path)
    out: dict = {"path": path, "bytes": len(raw)}
    try:
        text = raw.decode("utf-8")
        out["decodes_as_strict_utf8"] = True
    except UnicodeDecodeError as bad:
        out["decodes_as_strict_utf8"] = False
        out["decode_error"] = str(bad)
        text = raw.decode("utf-8", "replace")
    out["replacement_characters"] = text.count(REPLACEMENT)
    out["lone_surrogates"] = sum(1 for ch in text if 0xD800 <= ord(ch) <= 0xDFFF)
    person = next((p for p in people if p.who == multibyte_who), None)
    typed_counts: dict[str, int] = {}
    for piece in person.written if person else []:
        typed_counts[piece] = typed_counts.get(piece, 0) + 1
    out["pieces"] = [
        {
            "piece": piece,
            "code_points": len(piece),
            "utf8_bytes": len(piece.encode("utf-8")),
            "utf16_units": len(piece.encode("utf-16-le")) // 2,
            "typed": typed_counts.get(piece, 0),
            "in_committed_body": text.count(piece),
        }
        for piece in MULTIBYTE
    ]
    # A ZWJ with nothing joined to it is what a splice through a family emoji
    # leaves behind, and it is invisible in a diff.
    family = "\U0001f468‍\U0001f469‍\U0001f467"
    out["zwj_total"] = text.count(ZWJ)
    out["zwj_accounted_for"] = text.count(family) * 2
    out["orphaned_zwj"] = out["zwj_total"] - out["zwj_accounted_for"]
    return out


def silence(people: list[RoomTypist], ledger: measure.Ledger, zero: float,
            began: float, saves: list[dict]) -> dict:
    """How long the room went completely quiet, per member, and when.

    A gap between two consecutive applied updates at ONE socket. With fifteen
    people typing an update lands roughly every 15 ms, so anything above ~200 ms
    is the event loop not running: `_commit_room` holds it for the length of
    `store.write`, push included, and `_watch`'s twenty-second commit holds it
    for the same reason with nobody having asked for it.

    Reported per member and not pooled, because the question is what ONE person
    experienced — a p99 over fifteen sockets divides the same stall by fifteen.
    """
    # Every keystroke this driver put on the wire, in the window's own clock. A
    # gap in ARRIVALS with no SENDS inside it is not a stall, it is a room where
    # nobody was typing — and that distinction is the whole instrument. The
    # first pass did not have it and reported fifteen typists taking their
    # end-of-line pause together as a 971 ms outage.
    sends = sorted(
        (zero + one.began - began, one.who)
        for one in ledger.actions
        if one.kind == "WS keystroke" and one.status == "typed"
    )
    when = [t for t, _ in sends]

    def sent_between(low: float, high: float, not_by: str) -> int:
        lo = bisect.bisect_right(when, low)
        hi = bisect.bisect_left(when, high)
        return sum(1 for _, who in sends[lo:hi] if who != not_by)

    rows = []
    for person in people:
        member = person.member
        if member is None or not isinstance(member, GapTypist):
            continue
        arrivals = [t for t in member.arrivals if t >= began]
        gaps = [
            {
                "began": round(a - began, 2),
                "ms": round((b - a) * 1000, 1),
                # Updates other people put on the wire while this socket heard
                # nothing. Zero means nobody was typing; several means the room
                # was not delivering.
                # Both sides of this comparison are in the window's clock.
                # `arrivals` are raw `monotonic`, `sends` are seconds since
                # `began`, and the first version of this line mixed the two —
                # which reads as "nobody sent anything, ever" and made every
                # gap look like a quiet room.
                "others_sent_meanwhile": sent_between(
                    a - began, b - began, person.who
                ),
            }
            for a, b in zip(arrivals, arrivals[1:], strict=False)
        ]
        stalls = [g for g in gaps if g["others_sent_meanwhile"] >= 2]
        widest = sorted(stalls, key=lambda g: -g["ms"])[:3]
        quiet = sorted(gaps, key=lambda g: -g["ms"])[:1]
        rows.append({
            "who": person.who,
            "updates_applied": len(arrivals),
            "median_gap_ms": (
                round(sorted(g["ms"] for g in gaps)[len(gaps) // 2], 1) if gaps else None
            ),
            "widest_stalls": widest,
            "widest_gap_of_any_kind": quiet,
        })
    saved_at = [s["pressed_at"] for s in saves]
    over = [
        {"who": r["who"], **g}
        for r in rows for g in r["widest_stalls"] if g["ms"] >= 200.0
    ]
    over.sort(key=lambda g: -g["ms"])
    return {
        "per_member": rows,
        "worst_stall_ms": max(
            (g["ms"] for r in rows for g in r["widest_stalls"]), default=None
        ),
        "worst_gap_of_any_kind_ms": max(
            (g["ms"] for r in rows for g in r["widest_gap_of_any_kind"]), default=None
        ),
        "stalls_over_200ms": over[:20],
        "save_pressed_at": saved_at,
        "note": "a stall is two consecutive updates at one socket with at least two "
                "updates from other people put on the wire in between; a gap with "
                "nothing sent into it is a room where nobody was typing",
    }


def one_run(name: str, *, args, seconds: float, save_after: float | None,
            rtt_ms: float, quiet_wait: float) -> dict:
    """One world, fifteen sockets, one room, `seconds` of typing, then git."""
    ledger = measure.Ledger()
    pings: list[Ping] = []
    pings_lock = threading.Lock()
    blob: dict = {
        "run": name,
        "config": {
            "coeditors": args.users, "seconds": seconds, "save_after": save_after,
            "carets": args.carets,
            "rtt_ms": rtt_ms, "quiet_wait": quiet_wait, "seed": args.seed,
            "size": args.size, "mark_every": MARK_EVERY,
            "chars_per_second": users.CHARS_PER_SECOND,
        },
    }
    rusage_before = resource.getrusage(resource.RUSAGE_SELF)

    with harness.Harness(seed=args.seed, rtt_ms=rtt_ms, corpus="corpus",
                         size=args.size, remote=True) as world:
        ids = world.entity_ids("task-")
        if not ids:
            raise SystemExit("the corpus has no tasks to aim at")
        target = ids[0]
        before = verify.snapshot(world.plan)
        started_at = harness.head_of(world.plan)
        blob["world"] = world.describe()
        blob["world"]["room"] = target

        zero = time.monotonic()
        people: list[RoomTypist] = []
        for i in range(args.users):
            multibyte = i == args.users - 1
            pieces = MULTIBYTE if multibyte else _ascii_stream(i)
            people.append(
                RoomTypist(
                    f"coeditor-{i:02d}", LOGINS[i % len(LOGINS)], world, ledger,
                    args.seed, 0.0, zero,
                    entity=target, client_id=1000 + i, seed=args.seed,
                    save_every=0.0, save_at_end=False,
                    pieces=pieces, pings=pings, pings_lock=pings_lock,
                    save_after=save_after if i == 0 else None,
                    carets=args.carets,
                )
            )
        blob["multibyte_typist"] = people[-1].who

        # Every socket open before the clock starts. Fifteen handshakes is setup;
        # inside the window it is a connection storm in the first second and
        # shows up as the room being slow.
        connect_began = time.monotonic()
        for person in people:
            person.connect()
        blob["connect_seconds"] = round(time.monotonic() - connect_began, 2)
        # Let fifteen anchors reach fifteen documents before anybody types after
        # one of them. Without this the first keystrokes race their own anchor.
        time.sleep(2.0)

        cpu_before = world.cpu_seconds()
        watch = CommitWatch(world.plan, zero)
        watch.start()

        began = time.monotonic()
        deadline = began + seconds
        for person in people:
            person.begin(deadline)
            person.start()
        for person in people:
            person.join(timeout=seconds + 180)
        stopped = time.monotonic()
        elapsed = stopped - began

        # --- the moment typing stops, before anybody saves -------------------
        head_at_stop = harness.head_of(world.plan)
        typed_code_points = sum(p.after for p in people)
        room_text = people[0].member.body() if people[0].member else ""
        path_now = harness.record_paths(world.plan, head_at_stop)[target]
        # The BODY, not the file. `read_blob` hands back frontmatter too, and a
        # subtraction that mixed the two would call forty lines of YAML "text
        # only in memory".
        stored = _body_of(harness.read_blob(world.plan, head_at_stop, path_now) or "", path_now)
        blob["at_the_moment_typing_stopped"] = {
            "head_moved_during_typing": head_at_stop != started_at,
            "commits_during_typing": len(watch.seen),
            "commit_times": list(watch.seen),
            "code_points_typed_by_everybody": typed_code_points,
            "anchors_planted": sum(len(p.anchor) + 1 for p in people),
            "room_document_chars": len(room_text),
            "room_document_utf8_bytes": len(room_text.encode("utf-8")),
            "committed_body_chars": len(stored),
            "chars_only_in_memory": len(room_text) - len(stored),
            "utf8_bytes_only_in_memory": (
                len(room_text.encode("utf-8")) - len(stored.encode("utf-8"))
            ),
            # A cross-check and not a second measurement: with no commit during
            # the window, everything anybody typed since the room opened is in
            # memory and nowhere else, so these two have to agree.
            "typed_plus_anchors": typed_code_points + sum(len(p.anchor) + 1 for p in people),
        }

        # --- now stop and watch the quiet window ------------------------------
        quiet_began = time.monotonic()
        while time.monotonic() - quiet_began < quiet_wait:
            if harness.head_of(world.plan) != head_at_stop:
                break
            time.sleep(0.25)
        head_after_quiet = harness.head_of(world.plan)
        blob["quiet_window"] = {
            "seconds_from_last_keystroke_to_commit": (
                round(time.monotonic() - stopped, 1) if head_after_quiet != head_at_stop else None
            ),
            "committed": head_after_quiet != head_at_stop,
            "quiet_seconds_setting": 20.0,
            "waited_seconds": round(time.monotonic() - quiet_began, 1),
        }
        # A moment for the `absorb` the commit broadcasts to reach the documents.
        time.sleep(1.5)

        bodies = [p.member.body() for p in people if p.member is not None]
        blob["convergence"] = {
            "documents": len(bodies),
            "all_identical": len(set(bodies)) == 1,
            "distinct_documents": len(set(bodies)),
            "lengths": sorted({len(b) for b in bodies}),
        }
        frames = [p.member.frames for p in people if p.member is not None]
        wire_bytes = [p.member.bytes for p in people if p.member is not None]
        blob["fanout"] = {
            "updates_sent_by_clients": sum(len(p.written) for p in people),
            "updates_per_second": round(sum(len(p.written) for p in people) / elapsed, 1),
            "frames_delivered_total": sum(frames),
            "frames_delivered_per_second": round(sum(frames) / elapsed, 1),
            "frames_per_member": {"min": min(frames), "max": max(frames)},
            "wire_bytes_total": sum(wire_bytes),
            "wire_kb_per_second": round(sum(wire_bytes) / elapsed / 1024, 1),
            "evicted": [p.who for p in people if p.member and p.member.gone],
            "caret_frames_sent_by_clients": sum(p.caret_frames for p in people),
            "carets": args.carets,
        }
        blob["saves_early"] = [
            {"who": p.who, "pressed_at": round(p.save_pressed_at - began, 1),
             "answer": p.save_answer}
            for p in people if p.save_pressed_at is not None
        ]
        blob["propagation"] = propagation(pings, people, began)
        blob["silence"] = silence(people, ledger, zero, began, blob["saves_early"])

        cpu = world.cpu_seconds()
        blob["server"] = {
            "cpu_seconds_during_window": round(cpu - cpu_before, 2),
            "cpu_per_wall_second": round((cpu - cpu_before) / elapsed, 3),
            "cpu_seconds_total": round(cpu, 2),
            "rss_mb": round(world.rss_mb(), 1),
        }
        after = resource.getrusage(resource.RUSAGE_SELF)
        driver_cpu = ((after.ru_utime + after.ru_stime)
                      - (rusage_before.ru_utime + rusage_before.ru_stime))
        blob["driver"] = {
            "cpu_seconds": round(driver_cpu, 2),
            "cpu_per_wall_second": round(driver_cpu / elapsed, 3),
            "note": "the harness applies every update in fifteen documents; the server "
                    "applies each update once. A driver above ~1.0 core-seconds per wall "
                    "second is the GIL, and every latency here would then be partly its own.",
        }
        blob["saves"] = blob["saves_early"]
        del blob["saves_early"]

        log_tail = "\n".join(world.server_log().splitlines()[-15:])
        watch.stop()
        typed = [p.finish() for p in people]
        # The last socket out commits whatever is left; nobody waits for it.
        time.sleep(2.0)
        world.stop()

        head = harness.head_of(world.plan)
        path = harness.record_paths(world.plan, head)[target]
        blob["encoding"] = encoding(world.plan, head, path, people[-1].who, people)
        verdict = verify.verify(
            world.plan, world.origin, typed, [],
            logins={p.login for p in people}, before=before,
        )
        blob["verification"] = verdict
        commits = users.commit_log(world.plan)
        made = commits
        for n, one in enumerate(commits):
            if one["sha"] == started_at[:10]:
                made = commits[:n]
                break
        blob["commits"] = {
            "total": len(commits),
            "made_by_this_run": len(made),
            "by_author": _tally(c["author"] for c in made),
            "subjects": [c["subject"] for c in made[:8]],
        }
        blob["measured"] = ledger.report(elapsed)
        blob["driver_failures"] = {p.who: p.failed for p in people if p.failed}
        blob["server_log_tail"] = log_tail
        blob["strays"] = harness.strays()
    return blob


def _ascii_stream(i: int) -> list[str]:
    """Ten characters, rotated per person, so no two runs read as each other's."""
    rotated = users.ALPHABET[i % len(users.ALPHABET):] + users.ALPHABET
    return list(rotated[:10])


def _tally(things) -> dict:
    out: dict[str, int] = {}
    for thing in things:
        out[thing] = out.get(thing, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def summarise(blob: dict) -> str:
    stop = blob["at_the_moment_typing_stopped"]
    prop = blob["propagation"]
    lines = [
        f"\n=== {blob['run']} · {blob['config']['coeditors']} co-editors, "
        f"{blob['config']['seconds']}s, rtt {blob['config']['rtt_ms']} ms ===",
        f"room {blob['world']['room']} in {blob['world']['records']} records",
        f"  carets           {blob['fanout']['caret_frames_sent_by_clients']} sent "
        f"(carets={blob['fanout']['carets']})",
        f"  fan-out          {blob['fanout']['updates_per_second']} updates/s in, "
        f"{blob['fanout']['frames_delivered_per_second']} frames/s out, "
        f"{blob['fanout']['wire_kb_per_second']} kB/s",
        f"  keypress->recv   p50 {prop['keypress_to_receipt_ms'].get('p50')} "
        f"p90 {prop['keypress_to_receipt_ms'].get('p90')} "
        f"p99 {prop['keypress_to_receipt_ms'].get('p99')} "
        f"max {prop['keypress_to_receipt_ms'].get('max')} ms "
        f"(n={prop['keypress_to_receipt_ms'].get('n')})",
        f"  wire->recv       p50 {prop['wire_to_receipt_ms'].get('p50')} "
        f"p90 {prop['wire_to_receipt_ms'].get('p90')} "
        f"p99 {prop['wire_to_receipt_ms'].get('p99')} "
        f"max {prop['wire_to_receipt_ms'].get('max')} ms",
        f"  server CPU       {blob['server']['cpu_per_wall_second']} core-seconds per wall "
        f"second, {blob['server']['rss_mb']} MB",
        f"  driver CPU       {blob['driver']['cpu_per_wall_second']} core-seconds per wall second",
        f"  while typing     {stop['commits_during_typing']} commits; "
        f"{stop['code_points_typed_by_everybody']} code points typed, "
        f"{stop['chars_only_in_memory']} chars / "
        f"{stop['utf8_bytes_only_in_memory']} UTF-8 bytes only in memory at the end "
        f"(cross-check {stop['typed_plus_anchors']})",
        f"  worst marker     {prop['worst_marker']}",
        f"  worst stall      {blob['silence']['worst_stall_ms']} ms "
        f"(widest gap of any kind {blob['silence']['worst_gap_of_any_kind_ms']} ms); "
        f"over 200 ms: {blob['silence']['stalls_over_200ms'][:6] or 'none'}",
        f"  quiet window     {blob['quiet_window']}",
        f"  convergence      {blob['convergence']}",
        f"  saves            {blob['saves'] or 'none'}",
        f"  commits          {blob['commits']['made_by_this_run']} by "
        f"{blob['commits']['by_author']}",
        "  encoding         " + json.dumps(
            {k: v for k, v in blob["encoding"].items() if k != "pieces"}, ensure_ascii=False
        ),
    ]
    for piece in blob["encoding"]["pieces"]:
        lines.append(
            f"    {piece['piece']!r:<40} {piece['code_points']} cp / {piece['utf8_bytes']} B / "
            f"{piece['utf16_units']} u16   typed {piece['typed']:>3}  in git "
            f"{piece['in_committed_body']:>3}"
        )
    lines.append("  -- verification --")
    lines.append(verify.summary(blob["verification"]))
    for row in blob["verification"]["checks"].get("coeditors", []):
        lines.append(
            f"    {row['who']:<12} typed {row['typed']:>4} committed {row['committed']:>4} "
            f"anchor {row['anchor_in_tree']} {row['trouble'] or ''}"
        )
    if blob["driver_failures"]:
        lines.append(f"  driver failures: {blob['driver_failures']}")
    return "\n".join(lines)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--users", type=int, default=15)
    p.add_argument("--seconds", type=float, default=90.0)
    p.add_argument("--rtt-seconds", type=float, default=40.0,
                   help="length of the third run, the one with a real push charged")
    p.add_argument("--rtt-ms", type=float, default=600.0,
                   help="push/fetch round trip charged inside pygit2 for the third run")
    p.add_argument("--quiet-wait", type=float, default=32.0)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--size", default="medium", choices=["small", "medium", "large"])
    p.add_argument("--only", default="", help="run just one of: storm, save, rtt")
    p.add_argument("--carets", action="store_true",
                   help="send {t:'at'} after every keystroke, the way the editor does — "
                        "each one costs a `who` broadcast to the whole room")
    p.add_argument("--out", type=Path,
                   default=ROOT / "docs" / "probes" / "load" / "coedit-same-room.json")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    plan = [
        ("storm", dict(seconds=args.seconds, save_after=None, rtt_ms=0.0,
                       quiet_wait=args.quiet_wait)),
        ("save-mid-storm", dict(seconds=args.seconds, save_after=args.seconds / 2,
                                rtt_ms=0.0, quiet_wait=args.quiet_wait)),
        ("save-mid-storm-rtt600", dict(seconds=args.rtt_seconds,
                                       save_after=args.rtt_seconds / 2,
                                       rtt_ms=args.rtt_ms, quiet_wait=args.quiet_wait)),
    ]
    if args.only:
        keep = {"storm": 0, "save": 1, "rtt": 2}[args.only]
        plan = [plan[keep]]

    runs = []
    for name, how in plan:
        blob = one_run(name, args=args, **how)
        runs.append(blob)
        print(summarise(blob), flush=True)

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"scenario": "coedit-same-room", "runs": runs}, indent=2,
                   sort_keys=True, default=str, ensure_ascii=False) + "\n"
    )
    print(f"\nwritten to {out}")
    bad = [r for r in runs if not r["verification"]["ok"] or r["driver_failures"]]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
