"""Twenty people, two rooms, and three things that go wrong on purpose.

    uv run python tests/load/adversarial.py --seconds 120

The mixed hostile run — the one shaped like a Tuesday rather than like a
benchmark. Twenty simultaneous people: eight readers browsing, five form writers
each on their own record, one tab changing a FIELD on a record somebody else is
co-editing, and six co-editors split over two rooms. On top of that, three
injections, each of which is a thing this deployment will really see:

**1. A human with a terminal.** `store.py`'s own module docstring says somebody
will commit to this repository in week one. So a 21st participant clones the
bare `origin`, appends a line to a record, commits and pushes — four times,
while the run is going. Three questions come out of it and each is measured
rather than argued about: does the instance NOTICE (nothing in this application
polls the remote — `store.head()` reads the local ref and `fetch` happens only
on the retry path, so a human's push is invisible until the next write loses a
push race); does anything DIVERGE; and does anybody's write get lost while
`_absorb_remote` reconciles.

**2. A form Save carrying a stale body, on a record with a live room in it.**
This is not a contrived shape. `render.py` line 13769 is
`if (COEDIT.live()) { COEDIT.save(fields); return; }` — the record page routes
Save through the socket *while the socket is up*, and down the plain
`PATCH /api/record` road with `SURFACE.text()` as the body when it is not. Cloud
Run's `--timeout 300` closes every websocket every five minutes, so "my socket
is gone and my textarea still holds what I could see" is the ordinary state of
one tab in the room several times an hour. `saved` frames move that tab's
`base_commit` forward, so the tab holds a FRESH base and a STALE body — and the
compare-and-swap compares COMMITS, not bodies. So the run does exactly that: one
co-editor's socket is killed rudely mid-run, and a while later that tab presses
Save with the text it was holding when it died.

The control sits beside it: the same collision on the OTHER room, made with a
field-only PATCH (`body: null`), which is what `/table`'s inline edit and the
drag-to-refile both send. If one of those is safe and the other is not, the
difference is the finding.

**3. Two people typing either side of one emoji, at the same moment.** The
document is addressed in UTF-8 bytes, `Room.absorb`'s prefix/suffix scan counts
Python code points, and `byte_offset` is the one conversion between them — the
defect that shipped here twice. The left-hand person plants
`[CM.k]<emoji>[CM.k+1]` in a single insert so the ordering is not the harness's
choice, then the two of them grow contiguous runs on either side of that one
character while a terminal push forces `landed != body` and makes the room
splice across it.

Everything else — the plan, the bare remote, the one server on a loopback port
in 8900-8999, the kill in a `finally` — is `tests/load/harness.py`, and the
integrity questions at the end are `tests/load/verify.py` unchanged. What is
added here is the accounting: every write this run made is one of COMMITTED,
REFUSED or LOST, and the three numbers are printed with the sum beside them.
A number that does not add up is the finding.

Bounded on purpose: `--seconds` is a wall clock every thread reads, the four
terminal pushes are placed as fractions of it, and nothing here soaks.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
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
import queueing  # noqa: E402
import users  # noqa: E402
import verify  # noqa: E402

# One code point, four UTF-8 bytes, two UTF-16 code units. Every index space this
# system uses disagrees about it, which is the whole reason it is here.
EMOJI = "\U0001f44d"

# Not a login the plan knows, deliberately. `verify.authorship` reports commits
# by logins the run did not simulate, and a terminal commit SHOULD show up there:
# a checker that could not see an outside commit could not see this injection.
TERMINAL = "terminal-human"


# -- injection 1: somebody with a terminal ----------------------------------


def _git(*args: str, cwd: Path | None = None, check: bool = True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, check=check,
    )


def _reachable(repo: Path, sha: str) -> bool:
    """Whether this repository's `main` already contains that commit.

    Asked of the repository rather than of the app, and swallowing everything:
    the server is rewriting these refs underneath, and an object that has not
    been fetched yet makes `descendant_of` raise rather than answer False.
    """
    import pygit2  # noqa: PLC0415

    try:
        git = pygit2.Repository(str(repo))
        head = str(git.references["refs/heads/main"].target)
        if head == sha:
            return True
        return bool(git.descendant_of(head, sha))
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Push:
    """One `git push` made by a person, and what the running service did about it."""

    at_second: float
    record: str
    marker: str
    sha: str | None
    attempts: int
    pushed_ok: bool
    origin_head_after: str | None = None
    # Seconds from the push landing on `origin` until the instance's own `main`
    # contains it. None means it never did, inside the watch window.
    absorbed_after_s: float | None = None
    on_the_page_after_s: float | None = None
    served_head_when_seen: str | None = None
    note: str = ""


class Terminal(threading.Thread):
    """A person with a shell, pushing straight to the plan's remote.

    A real clone and real `git` on a real working tree — not a pygit2 write into
    the bare repo — because the thing being modelled is a colleague, and a
    colleague's commit arrives through the same door GitHub's does. The clone is
    made before the clock starts so the run does not measure it.
    """

    def __init__(
        self,
        origin: Path,
        plan: Path,
        clone: Path,
        base_url: str,
        schedule: list[tuple[float, str]],
        zero: float,
        watch_seconds: float = 45.0,
    ) -> None:
        super().__init__(name="terminal", daemon=True)
        self.origin = origin
        self.plan = plan
        self.clone = clone
        self.base_url = base_url
        self.schedule = schedule
        self.zero = zero
        self.watch_seconds = watch_seconds
        self.pushes: list[Push] = []
        self.failed: str | None = None

    def prepare(self) -> None:
        _git("clone", "--quiet", str(self.origin), str(self.clone))
        _git("config", "user.name", TERMINAL, cwd=self.clone)
        _git("config", "user.email", f"{TERMINAL}@users.noreply.github.com", cwd=self.clone)

    def run(self) -> None:
        try:
            client = httpx.Client(base_url=self.base_url, timeout=60.0)
            with client:
                for n, (at, record) in enumerate(self.schedule, start=1):
                    wait = (self.zero + at) - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    marker = f"TM{n:02d}"
                    record = self._push(at, record, marker)
                    self.pushes.append(record)
                    if record.sha:
                        self._watch(record, client)
        except Exception as error:  # noqa: BLE001 - an injector may not take the run down
            self.failed = f"{type(error).__name__}: {error}"

    def _push(self, at: float, record: str, marker: str) -> Push:
        """Fetch, edit, commit, push. Retried, because five other writers are
        pushing to the same ref and a person would just run it again."""
        last = ""
        for attempt in range(4):
            _git("fetch", "--quiet", "origin", "main", cwd=self.clone)
            _git("reset", "--hard", "--quiet", "FETCH_HEAD", cwd=self.clone)
            paths = harness.record_paths(self.origin, harness.head_of(self.origin))
            where = self.clone / paths[record]
            text = where.read_text(encoding="utf-8")
            # At the very end of the file, which is where a person adds a
            # checklist item — and which is the same line a form writer's append
            # and a co-editor's anchor both land on. That overlap is the point:
            # it is the commonest three-way collision this tool can have.
            where.write_text(
                text.rstrip("\n") + f"\n- [ ] {marker} committed from a terminal\n",
                encoding="utf-8",
            )
            _git("add", "-A", cwd=self.clone)
            _git("commit", "-q", "-m", f"{record}: {marker} from a terminal", cwd=self.clone)
            sha = _git("rev-parse", "HEAD", cwd=self.clone).stdout.strip()
            done = _git("push", "--quiet", "origin", "HEAD:main", cwd=self.clone, check=False)
            if done.returncode == 0:
                return Push(
                    at_second=round(time.monotonic() - self.zero, 2),
                    record=record, marker=marker, sha=sha, attempts=attempt + 1,
                    pushed_ok=True, origin_head_after=harness.head_of(self.origin)[:10],
                )
            last = (done.stdout + done.stderr).strip()[:200]
        return Push(
            at_second=round(time.monotonic() - self.zero, 2),
            record=record, marker=marker, sha=None, attempts=4, pushed_ok=False, note=last,
        )

    def _watch(self, record: Push, client: httpx.Client) -> None:
        """How long the instance served a plan that did not have this commit in it.

        The local ref every 100 ms, because that is what `store.head()` reads and
        therefore what every page and every `base_commit` is drawn from. The page
        itself once, when the ref has moved, to prove the two agree — polling
        `/detail` at 100 ms would be a 21st reader on the most expensive route on
        the site and would show up in everybody else's latency.
        """
        began = time.monotonic()
        while time.monotonic() - began < self.watch_seconds:
            if _reachable(self.plan, record.sha or ""):
                record.absorbed_after_s = round(time.monotonic() - began, 2)
                break
            time.sleep(0.1)
        if record.absorbed_after_s is None:
            return
        try:
            record.served_head_when_seen = client.get("/api/health").json().get("head", "")[:10]
            answer = client.get(f"/detail/{record.record}")
            if record.marker in answer.text:
                record.on_the_page_after_s = round(time.monotonic() - began, 2)
        except Exception as error:  # noqa: BLE001
            record.note = f"page check: {type(error).__name__}: {error}"


class RefWatch(threading.Thread):
    """Local `main` against `origin` `main`, classified, throughout the run.

    Not `queueing.RemoteLag`, which counts any inequality as the instance being
    ahead. With a person pushing into `origin` the interesting states are three
    and they mean opposite things: the instance holding a commit the remote does
    not have is a commit that dies with the container, the remote holding one the
    instance does not have is a colleague's work the app is not showing anybody,
    and neither-contains-the-other is `StoreDiverged` and the end of writing.
    """

    def __init__(self, plan: Path, origin: Path, every: float = 0.2) -> None:
        super().__init__(name="refwatch", daemon=True)
        self.plan = plan
        self.origin = origin
        self.every = every
        self.tally = {"same": 0, "instance_ahead": 0, "remote_ahead": 0, "forked": 0, "error": 0}
        self.max_remote_ahead_s = 0.0
        self._remote_ahead_since: float | None = None
        self._halt = threading.Event()

    def run(self) -> None:
        import pygit2  # noqa: PLC0415

        while not self._halt.is_set():
            try:
                local = pygit2.Repository(str(self.plan))
                remote = pygit2.Repository(str(self.origin))
                here = str(local.references["refs/heads/main"].target)
                there = str(remote.references["refs/heads/main"].target)
                if here == there:
                    state = "same"
                elif local.get(there) is not None and local.descendant_of(here, there):
                    state = "instance_ahead"
                elif local.get(there) is None or local.descendant_of(there, here):
                    state = "remote_ahead"
                else:
                    state = "forked"
                self.tally[state] += 1
                now = time.monotonic()
                if state == "remote_ahead":
                    self._remote_ahead_since = self._remote_ahead_since or now
                    self.max_remote_ahead_s = max(
                        self.max_remote_ahead_s, now - self._remote_ahead_since
                    )
                else:
                    self._remote_ahead_since = None
            except Exception:  # noqa: BLE001 - a ref caught mid-update is ordinary
                self.tally["error"] += 1
            self._halt.wait(self.every)

    def stop(self) -> dict:
        self._halt.set()
        self.join(timeout=5.0)
        total = sum(self.tally.values()) or 1
        return {
            "samples": total,
            "every_seconds": self.every,
            **self.tally,
            "fraction_instance_ahead": round(self.tally["instance_ahead"] / total, 4),
            "fraction_remote_ahead": round(self.tally["remote_ahead"] / total, 4),
            "longest_remote_ahead_seconds": round(self.max_remote_ahead_s, 2),
        }


# -- where the people in these rooms sit -------------------------------------

# The heading a person composing a shaping document types under. Everybody in
# both rooms plants here rather than at the end of the file, and the reason is
# the measurement: a room whose text is the LAST line of the file collides with
# every append anybody makes anywhere, so a single merge shape would stand in
# for the whole merge story. Under a heading, an end-of-file append by a person
# with a terminal and a paragraph being typed in the room are edits to different
# lines — which is the case `_merge_body` is written to keep, and the case a
# measurement has to be able to tell from the one it refuses.
UNDER = "## Progress\n"

# Which of the two seats this run uses. A module name and not a constructor
# argument because it is one decision for every person in the run and threading
# it through six constructions would put the same word in six places — and this
# file's own rule about that is `AGENTS.md`'s. Set once, in `main`, off `--seat`.
#
#   heading  everybody types under `## Progress`, in the middle of a shaping
#            document. This is what a person composing a pitch does, and it is
#            the default.
#   tail     everybody types at the very end of the file, which is also where a
#            form writer's new checklist item and a terminal's `git commit` land.
#            Not a fault injection: "two people add a bullet at the bottom" is
#            the commonest collision this tool has. It is separated from the
#            default because it makes EVERY outside edit collide with the room,
#            and a run in which one merge shape stands for all of them is a run
#            that cannot tell which shape did the damage.
SEAT = "heading"


class Composing(users.CoEditor):
    """A co-editor who sits where `--seat` says, rather than always at the end."""

    def plant_at(self, body: str) -> int:
        if SEAT == "tail":
            return len(body)
        at = body.find(UNDER)
        return len(body) if at < 0 else at + len(UNDER)


# -- injection 2: the tab whose socket died, and the field-only control -------


@dataclass
class TabSave:
    """One save made outside the room it was made about."""

    who: str
    record: str
    kind: str  # "body" or "fields-only"
    at_second: float
    base_commit: str | None
    head_before: str | None
    status: str
    outcome: str | None
    commit: str | None
    person_weeks: float
    body_bytes: int | None = None
    typed_by_room_at_save: dict[str, int] = field(default_factory=dict)
    # Per co-editor: how much of their run was in the plan immediately before
    # this save and immediately after it. `after < before` is the thing the whole
    # injection is about — a save answered 200 that took text out of git — and
    # `after > before` is the opposite and just as worth seeing, because a tab
    # holding text the room never committed writes it in.
    removed_from_plan: dict[str, dict] = field(default_factory=dict)


class DroppedTab(Composing):
    """A co-editor whose socket dies, and who presses Save afterwards.

    Cloud Run closes every websocket at five minutes, so this tab is not a
    fault — it is one editor in the room, several times an hour, every hour.
    `close(rude=True)` is an RST and not a close frame, which is what a lid
    closing or a tunnel dropping actually looks like.

    What it holds when it dies is what the page holds: `SURFACE.text()`, which
    is the room's document as of that instant, and `BASE.value`, which the
    `saved` handler moved forward on the room's last commit. A fresh base and a
    stale body is the exact pair the compare-and-swap cannot see, because it
    compares commits.
    """

    def __init__(self, *args, drop_at: float, save_at: float, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.drop_at = drop_at
        self.save_at = save_at
        self.body_at_drop: str | None = None
        self.base_at_drop: str | None = None
        self.tab_save: TabSave | None = None
        self.room_typed_at_save: dict[str, int] = {}
        self.watching: list[users.CoEditor] = []
        self.client = httpx.Client(
            base_url=self.world.base, timeout=120.0,
            headers={"cookie": harness.cookie_for(self.login)},
        )

    def work(self) -> None:
        assert self.member is not None
        stop_typing = self.zero + self.drop_at
        while time.monotonic() < stop_typing and self.more():
            self.keystroke()
            if self.member.gone:
                break
        # What this tab is holding at the moment its socket dies.
        self.body_at_drop = self.member.body()
        self.base_at_drop = self.last_base()
        self.member.close(rude=True)
        while time.monotonic() < self.zero + self.save_at and self.more():
            time.sleep(0.1)
        self.press_patch()

    def keystroke(self) -> None:
        assert self.member is not None
        begun = time.monotonic()
        character = self.stream[self.typed % len(self.stream)]
        answer = self.member.type_after(self.anchor, self.typed, character)
        if answer == "typed":
            self.typed += 1
        else:
            self.result.trouble.append(f"{answer} at {self.typed} typed")
        self.note(kind="WS keystroke", ms=(time.monotonic() - begun) * 1000,
                  status=answer, record=self.record)
        time.sleep(self.rng.uniform(0.9, 1.1) / users.CHARS_PER_SECOND)
        if self.typed and self.typed % users.LINE_LENGTH == 0:
            time.sleep(self.rng.uniform(0.8, 1.6))

    def last_base(self) -> str | None:
        """`BASE.value`, as the page would hold it: the room's welcome, moved
        forward by every `saved` frame this tab has been sent."""
        assert self.member is not None
        base = self.member.welcome.get("base")
        for frame in list(self.member.told):
            if frame.get("t") == "saved" and frame.get("commit"):
                base = frame["commit"]
        return base

    def press_patch(self) -> None:
        head_before = None
        try:
            head_before = self.client.get("/api/health").json().get("head")
        except Exception:  # noqa: BLE001
            pass
        self.room_typed_at_save = {p.anchor: p.typed for p in self.watching}
        weeks = 2.5
        payload = {
            "base_commit": self.base_at_drop,
            "fields": {"person_weeks": weeks},
            "body": self.body_at_drop,
        }
        begun = time.monotonic()
        status, outcome, commit = "", None, None
        try:
            answer = self.client.patch(f"/api/record/{self.record}", json=payload)
            status = str(answer.status_code)
            if answer.status_code in (200, 409):
                got = answer.json()
                outcome, commit = got.get("outcome"), got.get("commit")
        except Exception as error:  # noqa: BLE001
            status = type(error).__name__
        self.note(kind="PATCH (dropped tab)", ms=(time.monotonic() - begun) * 1000,
                  status=status, outcome=outcome, commit=commit, record=self.record)
        self.client.close()
        self.tab_save = TabSave(
            who=self.who, record=self.record, kind="body",
            at_second=round(begun - self.zero, 2),
            base_commit=(self.base_at_drop or "")[:10],
            head_before=(head_before or "")[:10],
            status=status, outcome=outcome, commit=commit, person_weeks=weeks,
            body_bytes=len((self.body_at_drop or "").encode("utf-8")),
            typed_by_room_at_save=dict(self.room_typed_at_save),
        )

    def finish(self) -> users.Typed:
        """No Save and no close: this tab's socket is already gone, and its Save
        has already happened through the other door."""
        self.result.expected = self.anchor + "".join(
            self.stream[i % len(self.stream)] for i in range(self.typed)
        )
        return self.result


class FieldTab(users.Person):
    """Somebody changing a FIELD on a record other people are co-editing.

    `body: null`, which is what `/table`'s inline edit, the drag-to-refile and
    the people page all send — three of the four write paths in the browser. The
    control for the injection above, and the reason it is a control is that
    `patch_text` leaves the body alone: the room's text is never in this request
    at all.
    """

    def __init__(self, *args, record: str, at: list[float], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.record = record
        self.at = at
        self.saves: list[TabSave] = []
        self.client = httpx.Client(
            base_url=self.world.base, timeout=120.0,
            headers={"cookie": harness.cookie_for(self.login)},
        )

    def work(self) -> None:
        with self.client:
            for n, when in enumerate(self.at, start=1):
                wait = (self.zero + when) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                if not self.more():
                    return
                self.save(n)

    def save(self, n: int) -> None:
        begun = time.monotonic()
        head = None
        try:
            head = self.client.get("/api/health").json().get("head")
        except Exception:  # noqa: BLE001
            pass
        weeks = round(3.0 + n, 1)
        status, outcome, commit = "", None, None
        try:
            answer = self.client.patch(
                f"/api/record/{self.record}",
                json={"base_commit": head, "fields": {"person_weeks": weeks}, "body": None},
            )
            status = str(answer.status_code)
            if answer.status_code in (200, 409):
                got = answer.json()
                outcome, commit = got.get("outcome"), got.get("commit")
        except Exception as error:  # noqa: BLE001
            status = type(error).__name__
        self.note(kind="PATCH (fields only)", ms=(time.monotonic() - begun) * 1000,
                  status=status, outcome=outcome, commit=commit, record=self.record)
        self.saves.append(TabSave(
            who=self.who, record=self.record, kind="fields-only",
            at_second=round(begun - self.zero, 2),
            base_commit=(head or "")[:10], head_before=(head or "")[:10],
            status=status, outcome=outcome, commit=commit, person_weeks=weeks,
        ))


# -- injection 3: two people, one emoji --------------------------------------


class EmojiLeft(Composing):
    """Plants `\\n[CM.k]<emoji>[CM.k+1]` in ONE insert, then types before the emoji.

    One insert and not two people appending, because two independent appends are
    ordered by whichever broadcast arrived first — the harness deciding the shape
    of the thing it is measuring. This way the two anchors are adjacent to one
    character by construction, and what is measured is what happens when both of
    them grow at once.
    """

    def __init__(self, *args, partner_anchor: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.partner_anchor = partner_anchor

    def planted(self) -> str:
        return "\n" + self.anchor + EMOJI + self.partner_anchor


class EmojiRight(Composing):
    """Types immediately after the emoji the left-hand person planted.

    Plants nothing; waits for its own anchor to arrive over the socket. The wait
    is bounded and its failure is recorded rather than raised — a run in which
    the anchor never arrived measured nothing about emoji and should say so.
    """

    def planted(self) -> str:
        return ""

    def connect(self) -> None:
        super().connect()
        assert self.member is not None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.anchor in self.member.body():
                return
            time.sleep(0.05)
        self.result.trouble.append("the partner's anchor never arrived")


# -- the run -----------------------------------------------------------------


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="adversarial.py", description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=120.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--readers", type=int, default=8)
    p.add_argument("--writers", type=int, default=5, help="form writers on their own records")
    p.add_argument("--rtt-ms", type=float, default=0.0)
    p.add_argument("--gap", type=float, default=3.0)
    p.add_argument("--gap-max", type=float, default=8.0)
    p.add_argument("--think", type=float, default=0.4)
    p.add_argument("--corpus", choices=("corpus", "plans"), default="corpus")
    p.add_argument("--size", choices=("small", "medium", "large"), default="medium")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--seat", choices=("heading", "tail"), default="heading",
                   help="where in the document the co-editors type: under a heading "
                        "(what a person composing a pitch does) or at the end of the "
                        "file, which is where every outside append also lands")
    p.add_argument("--no-terminal", action="store_true", help="drop injection 1")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--rows", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def run_after(text: str, anchor: str) -> int:
    """How many of this person's characters are in this text.

    Their contribution is one contiguous run of `users.ALPHABET` immediately
    behind their anchor — that is the property `users.py` is built around — so
    this is a scan and not a guess.
    """
    at = text.find(anchor)
    if at < 0:
        return 0
    n, tail = 0, text[at + len(anchor):]
    while n < len(tail) and tail[n] in users.ALPHABET:
        n += 1
    return n


def _tally(things) -> dict:
    out: dict[str, int] = {}
    for thing in things:
        out[thing] = out.get(thing, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one run, read top to bottom
    global SEAT  # noqa: PLW0603 - see the note on SEAT: one decision, one name
    args = parse(argv)
    SEAT = args.seat
    ledger = measure.Ledger()
    window = args.seconds

    with harness.Harness(
        seed=args.seed, rtt_ms=args.rtt_ms, corpus=args.corpus, size=args.size,
        port=args.port, keep=args.keep, remote=True,
    ) as world:
        ids = world.record_ids("task-")
        if len(ids) < 12:
            raise SystemExit("the corpus is too small for this scenario")
        room_a, room_b = ids[0], ids[1]
        writer_ids = ids[2 : 2 + args.writers]
        before = verify.snapshot(world.plan)
        started_at = harness.head_of(world.plan)

        zero = time.monotonic()
        nth = 0

        def login() -> str:
            nonlocal nth
            name = harness.PEOPLE[nth % len(harness.PEOPLE)]
            nth += 1
            return name

        people: list[users.Person] = []
        coeditors: list[users.CoEditor] = []
        formwriters: list[users.FormWriter] = []

        def person(cls, who, **kwargs):
            return cls(who, login(), world, ledger, args.seed, 0.0, zero, **kwargs)

        # Room A: three people, one of whom presses Save on a clock and one of
        # whom loses their socket and saves through the form afterwards.
        save_every = round(window / 4.0, 1)
        a0 = person(Composing, "coeditor-a0", record=room_a, client_id=1000,
                    seed=args.seed, save_every=save_every, save_at_end=True)
        a1 = person(DroppedTab, "coeditor-a1", record=room_a, client_id=1001,
                    seed=args.seed, save_every=0.0, save_at_end=False,
                    # Straddling a room commit on purpose: room A saves every
                    # `window/4`, so the save at the halfway mark lands between
                    # this tab dying and this tab pressing Save. That is the
                    # ordering that makes its body genuinely older than the file,
                    # rather than merely older than the room.
                    drop_at=round(window * 0.30, 1), save_at=round(window * 0.55, 1))
        a2 = person(Composing, "coeditor-a2", record=room_a, client_id=1002,
                    seed=args.seed, save_every=0.0, save_at_end=True)
        a1.watching = [a0, a2]

        # Room B: the emoji pair, and one person pressing Save on a clock.
        b0 = person(EmojiLeft, "coeditor-b0", record=room_b, client_id=1003,
                    seed=args.seed, save_every=save_every, save_at_end=True,
                    partner_anchor=f"[CM{args.seed}.4]")
        b1 = person(EmojiRight, "coeditor-b1", record=room_b, client_id=1004,
                    seed=args.seed, save_every=0.0, save_at_end=True)
        b2 = person(Composing, "coeditor-b2", record=room_b, client_id=1005,
                    seed=args.seed, save_every=0.0, save_at_end=True)
        coeditors = [a0, a1, a2, b0, b1, b2]
        people += coeditors

        for i in range(args.writers):
            one = person(users.FormWriter, f"writer-{i}", record=writer_ids[i],
                         gap=args.gap, gap_max=args.gap_max, stale=False, style="append")
            formwriters.append(one)
            people.append(one)

        fields_only = person(FieldTab, "fieldtab", record=room_b,
                             at=[round(window * 0.33, 1), round(window * 0.71, 1)])
        people.append(fields_only)

        for i in range(args.readers):
            people.append(person(users.Reader, f"reader-{i}", ids=ids, think=args.think))

        # Every socket open before the clock starts, and in this order: the
        # left-hand emoji person plants both anchors, so the right-hand one has
        # something to wait for.
        for one in (a0, a1, a2, b0, b1, b2):
            one.connect()

        terminal = None
        if not args.no_terminal:
            terminal = Terminal(
                origin=world.origin, plan=world.plan, clone=world.work / "terminal",
                base_url=world.base, zero=zero,
                schedule=[
                    # A record nobody in this run touches: the pure question, is
                    # a colleague's commit visible at all.
                    (round(window * 0.17, 1), "note-000000"),
                    # A form writer's record: the terminal's append and the
                    # writer's append are the same line of the same file.
                    (round(window * 0.37, 1), writer_ids[0]),
                    # The emoji room's record: forces `landed != body` at the
                    # room's next commit, which is the one path that makes
                    # `Room.absorb` splice across a multi-byte character.
                    (round(window * 0.58, 1), room_b),
                    (round(window * 0.79, 1), "issue-000000"),
                ],
                watch_seconds=min(45.0, window * 0.5),
            )
            terminal.prepare()

        refs = RefWatch(world.plan, world.origin)
        refs.start()

        began = time.monotonic()
        deadline = began + window
        for one in people:
            one.begin(deadline)
            one.start()
        if terminal is not None:
            terminal.start()
        for one in people:
            one.join(timeout=window + 240)
        if terminal is not None:
            terminal.join(timeout=120)
        elapsed = time.monotonic() - began
        ref_report = refs.stop()
        driver_cpu = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_utime
            + resource.getrusage(resource.RUSAGE_SELF).ru_stime, 2,
        )

        # Typing has stopped everywhere before anybody presses Save, so a save
        # carries everybody's text and "is every character committed" has one
        # answer.
        for one in coeditors:
            one.finish()
        time.sleep(2.0)

        cpu, rss = world.cpu_seconds(), world.rss_mb()
        described = world.describe()
        log_tail = "\n".join(world.server_log().splitlines()[-15:])
        world.stop()

        head = harness.head_of(world.plan)
        sent = [row for one in formwriters for row in one.sent]
        typed = [one.result for one in coeditors]
        verdict = verify.verify(
            world.plan, world.origin, typed, sent,
            logins={one.login for one in people}, before=before,
        )
        commits = users.commit_log(world.plan)
        made = commits
        for n, one in enumerate(commits):
            if one["sha"] == started_at[:10]:
                made = commits[:n]
                break

        # -- the accounting -------------------------------------------------
        paths_now = harness.record_paths(world.plan, head)
        final_a = harness.read_blob(world.plan, head, paths_now[room_a]) or ""
        final_b = harness.read_blob(world.plan, head, paths_now[room_b]) or ""

        # What the dropped tab's save took out of the plan. Measured against the
        # commit that was head immediately before it, so the number is "text that
        # was in git and then was not" and never "text that was only in a room".
        tab = a1.tab_save
        if tab and tab.commit and tab.head_before:
            was = harness.read_blob(world.plan, tab.head_before, paths_now[room_a]) or ""
            now = harness.read_blob(world.plan, tab.commit, paths_now[room_a]) or ""
            for other in (a0, a1, a2):
                tab.removed_from_plan[other.who] = {
                    "in_the_plan_before": run_after(was, other.anchor),
                    "in_the_plan_after": run_after(now, other.anchor),
                    "typed_by_then": other.typed,
                }

        emoji_check = {
            "in_the_final_file": final_b.count(EMOJI),
            "left_run_in_file": run_after(final_b, b0.anchor),
            "left_typed": b0.typed,
            "right_run_in_file": run_after(final_b, b1.anchor),
            "right_typed": b1.typed,
            # The shape the injection is about, asked of the committed bytes:
            # the left person's run ends exactly at the emoji and the right
            # person's anchor begins exactly after it. A splice measured in the
            # wrong index space breaks one of the two and neither raises.
            "left_run_ends_at_the_emoji": (
                b0.anchor + final_b[
                    final_b.find(b0.anchor) + len(b0.anchor):
                ][: run_after(final_b, b0.anchor)] + EMOJI
            ) in final_b,
            "right_anchor_begins_after_the_emoji": (EMOJI + b1.anchor) in final_b,
            "left_document_at_end": None,
            "right_document_at_end": None,
        }
        for name, one in (("left_document_at_end", b0), ("right_document_at_end", b1)):
            if one.member is not None:
                doc = one.member.body()
                emoji_check[name] = {
                    "emoji": doc.count(EMOJI),
                    "own_run": run_after(doc, one.anchor),
                }

        rooms_report = []
        for name, members, path_id, text in (
            ("room A", (a0, a1, a2), room_a, final_a),
            ("room B", (b0, b1, b2), room_b, final_b),
        ):
            rooms_report.append({
                "room": name,
                "record": path_id,
                "path": paths_now[path_id],
                "members": [
                    {"who": m.who, "login": m.login, "typed": m.typed,
                     "in_the_plan": run_after(text, m.anchor),
                     "saves": m.result.saves, "trouble": m.result.trouble}
                    for m in members
                ],
                "typed_total": sum(m.typed for m in members),
                "in_the_plan_total": sum(run_after(text, m.anchor) for m in members),
            })

        form = verdict["checks"]["form_writes"]
        char_committed = sum(r["in_the_plan_total"] for r in rooms_report)
        char_typed = sum(r["typed_total"] for r in rooms_report)
        room_refusals = [
            {"who": m.who, "room": r["room"], **s}
            for r, ms in zip(rooms_report, ((a0, a1, a2), (b0, b1, b2)), strict=True)
            for m in ms for s in m.result.saves if s.get("t") != "saved"
        ]
        accounting = {
            "form_saves": {
                "sent": len(sent),
                "committed": form["committed"],
                "refused_409": form["refused"],
                "lost": form["lost"],
                "ambiguous": form["ambiguous_present"] + form["ambiguous_absent"],
                "adds_up": (
                    form["committed"] + form["refused"] + form["lost"]
                    + form["ambiguous_present"] + form["ambiguous_absent"] == len(sent)
                ),
            },
            "field_only_saves": [asdict(s) for s in fields_only.saves],
            "dropped_tab_save": asdict(tab) if tab else None,
            "coedit_characters": {
                "typed": char_typed,
                "in_the_plan": char_committed,
                "not_in_the_plan": char_typed - char_committed,
                "room_saves_refused": room_refusals,
            },
            "terminal_pushes": [asdict(p) for p in terminal.pushes] if terminal else [],
            "terminal_markers_in_the_plan": {
                p.marker: (p.marker in (harness.read_blob(
                    world.plan, head, paths_now.get(p.record, "")) or ""))
                for p in (terminal.pushes if terminal else [])
                if p.record in paths_now
            },
        }

    report = ledger.report(elapsed)
    blob = {
        "scenario": "adversarial",
        "seed": args.seed,
        "config": {
            "seconds": window, "readers": args.readers, "form_writers": args.writers,
            "field_only_tabs": 1, "coeditors": 6, "rooms": 2,
            "seat": args.seat,
            "gap": args.gap, "gap_max": args.gap_max, "think": args.think,
            "coedit_save_every": save_every, "terminal": not args.no_terminal,
            "room_a": room_a, "room_b": room_b, "writer_records": writer_ids,
        },
        "world": described,
        "measured": report,
        "queueing": {
            "patch": queueing.concurrency(ledger.actions, "PATCH"),
            "refs": ref_report,
        },
        "server": {"cpu_seconds": cpu, "rss_mb": rss, "driver_cpu_seconds": driver_cpu},
        "commits": {"total": len(commits), "made_by_this_run": len(made),
                    "by_author": _tally(c["author"] for c in made)},
        "accounting": accounting,
        "rooms": rooms_report,
        "emoji": emoji_check,
        "verification": verdict,
        "driver_failures": {
            **{p.who: p.failed for p in people if p.failed},
            **({"terminal": terminal.failed} if terminal and terminal.failed else {}),
        },
        "server_log_tail": log_tail,
        "strays": harness.strays(),
    }
    if args.rows:
        blob["actions"] = ledger.rows()

    out = args.out or (ROOT / "docs" / "probes" / "load" / "adversarial.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str) + "\n")
    _print(blob, report, verdict, out)
    return 0


def _print(blob: dict, report: dict, verdict: dict, out: Path) -> None:
    c, w = blob["config"], blob["world"]
    print(f"\n=== adversarial · seed {blob['seed']} ===")
    print(
        f"{c['readers']} readers, {c['form_writers']} form writers, 1 field-only tab, "
        f"{c['coeditors']} co-editors in {c['rooms']} rooms seated at "
        f"{c['seat']!r}, for {c['seconds']}s\n"
        f"plan: {w['records']} records ({w['corpus']}/{w['size']}), remote {w['remote']}, "
        f"push rtt {w['rtt_ms']} ms, port {w['port']}"
    )
    print("\n-- latency (ms) --")
    print(measure.table(report))
    print("\n-- answers --")
    for kind, statuses in report["statuses"].items():
        print(f"  {kind:<24}{statuses}")
    if report["errors"]:
        print("\n-- errors --")
        for what, n in report["errors"].items():
            print(f"  {what}: {n}")
    print("\n-- writes --")
    print(f"  store outcomes: {report['write_outcomes'] or '{}'}")
    print(f"  pushed:         {report['pushed']}")
    print(f"  throughput:     {report['throughput']}")
    print(f"  commits:        {blob['commits']['made_by_this_run']} by "
          f"{blob['commits']['by_author']}")
    print(f"  server:         {blob['server']['cpu_seconds']}s CPU, "
          f"{blob['server']['rss_mb']} MB RSS "
          f"(driver {blob['server']['driver_cpu_seconds']}s)")
    print(f"  refs:           {blob['queueing']['refs']}")

    a = blob["accounting"]
    print("\n-- injection 1: a human with a terminal --")
    for push in a["terminal_pushes"]:
        print(f"  t+{push['at_second']:>6.1f}s  {push['marker']} -> {push['record']:<14} "
              f"pushed={push['pushed_ok']} attempts={push['attempts']} "
              f"instance saw it after {push['absorbed_after_s']}s "
              f"(page {push['on_the_page_after_s']}s)")
    print(f"  markers in the final plan: {a['terminal_markers_in_the_plan']}")

    print("\n-- injection 2: a save from outside the room --")
    print(f"  dropped tab:  {json.dumps(a['dropped_tab_save'], default=str)}")
    for one in a["field_only_saves"]:
        print(f"  fields only:  {json.dumps(one, default=str)}")

    print("\n-- injection 3: two people, one emoji --")
    print(f"  {json.dumps(blob['emoji'], default=str)}")

    print("\n-- the rooms --")
    for room in blob["rooms"]:
        print(f"  {room['room']} ({room['record']}): typed {room['typed_total']}, "
              f"in the plan {room['in_the_plan_total']}")
        for m in room["members"]:
            print(f"    {m['who']:<14} {m['login']:<14} typed {m['typed']:>4}  "
                  f"in the plan {m['in_the_plan']:>4}  saves {m['saves']}")

    print("\n-- every write, accounted --")
    f = a["form_saves"]
    print(f"  form saves:   {f['sent']} sent = {f['committed']} committed + "
          f"{f['refused_409']} refused(409) + {f['lost']} LOST + {f['ambiguous']} ambiguous "
          f"[adds up: {f['adds_up']}]")
    ch = a["coedit_characters"]
    print(f"  co-edit chars:{ch['typed']} typed, {ch['in_the_plan']} in the plan, "
          f"{ch['not_in_the_plan']} not")
    for refusal in ch["room_saves_refused"]:
        print(f"    room save refused: {json.dumps(refusal, default=str)[:300]}")

    print("\n-- verification --")
    print(verify.summary(verdict))
    for name in ("coeditors", "form_writes", "push", "parses", "conflict_markers", "authors"):
        if name in verdict["checks"]:
            print(f"  {name}: {json.dumps(verdict['checks'][name], default=str)[:400]}")
    if blob["driver_failures"]:
        print(f"\n!! the driver itself failed: {blob['driver_failures']}")
    if blob["strays"]:
        print(f"\n!! processes left behind: {blob['strays']}")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    raise SystemExit(main())
