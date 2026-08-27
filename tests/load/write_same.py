"""Twelve people saving ONE record through the form, three ways.

    uv run python tests/load/write_same.py --variant all --writers 12 --seconds 50

This is the compare-and-swap under genuine overlap. `run.py --scenario same`
already puts form writers and co-editors on one record; what it does not do is
separate the three shapes the store treats differently, and the whole point of
`_merge_frontmatter` merging per KEY and `_merge_body` merging per HUNK is that
two of those three shapes are supposed to merge and one is supposed to refuse.

  fields  every writer owns a DIFFERENT frontmatter key. Twelve keys, twelve
          people, no two of them touching the same one. Per-key merge says this
          all lands. Expectation: ~0 conflicts, many `merged`.
  field   every writer moves the SAME key (`person_weeks`) to a value only they
          send. Per-key merge says this refuses. Expectation: many 409s, and —
          the thing actually being hunted — a final value that is one somebody
          sent, never an invention, and never a 200 whose value vanished.
  body    every writer inserts a line into a DIFFERENT paragraph of the shaping
          document. Per-hunk merge says this all lands. Expectation: ~0
          conflicts, every marker present, every marker under its OWN heading.

WHY THE MARKERS ARE SHAPED THE WAY THEY ARE

`verify.form_changes` decides "committed / refused / LOST" by asking whether a
save's marker is in the final file. That question is only decidable for an
APPEND-ONLY edit: a save that legitimately overwrites an earlier one would look
like a loss. So the writers here are split in two, and each half is judged by the
check that fits it:

* **accumulate** lanes append to a LIST field (`tags`, `prs`, `assignees`,
  `reviewers`, `depends_on`) or insert a line into the body. Every accepted
  marker must survive to the tip, and `verify.form_changes` judges them.
* **latest** lanes are last-writer-wins scalars (`title`, `owner`,
  `person_weeks`, `assigned_on`, `priority`, `review_waived`, `status`). Only one
  writer ever touches each, so the final value must equal that writer's last
  ACCEPTED value — checked here, in `latest_values`, because nothing in
  `verify.py` can express it.

Both checks are necessary and neither is sufficient. A marker present says
nothing about whether the rest of the document survived, which is why
`nothing_vanished` asserts that every line of the seeded body and every
frontmatter key present before the run is still present after it. **A silent
merge that produces a document neither person wrote is the finding this file
exists to hunt**, and a substring test alone would walk straight past it.

Every field chosen here is safe for the validator on purpose: the two statuses
used (`shaping`, `shelved`) carry no gates, so a run cannot manufacture a
blocker and then report its own choice of value as damage. `cycle` is
deliberately absent for the same reason — a cycle number no `cycles.yaml`
declares is a question about the scheduler, not about the store.

Bounded like everything else here: `--seconds` is a wall clock, four runs of
fifty seconds is the shape, and ten minutes is the same shape with a bigger bill
on a laptop somebody else is using.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
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

from openproj.model import parse_text, split_front_matter  # noqa: E402

VARIANTS = ("fields", "field", "body")

# The twelve lanes of `--variant fields`, in the order writers take them.
#
# `accumulate` appends to a list and its marker must survive for ever;
# `latest` overwrites a scalar and only its LAST accepted value must survive.
# Nothing here can add a validation blocker: `shaping` and `shelved` are the two
# statuses `_status_problems` returns early on, so the junk logins the owner and
# assignee lanes write are warnings about `config/people.yaml` and never gates.
LANES: tuple[tuple[str, str], ...] = (
    ("tags", "accumulate"),
    ("prs", "accumulate"),
    ("assignees", "accumulate"),
    ("reviewers", "accumulate"),
    ("depends_on", "accumulate"),
    ("title", "latest"),
    ("owner", "latest"),
    ("person_weeks", "latest"),
    ("assigned_on", "latest"),
    ("priority", "latest"),
    ("review_waived", "latest"),
    ("status", "latest"),
)

PRIORITIES = ("very_high", "high", "medium", "low", "very_low")
# Both carry no status gate at all, so flipping between them cannot make the
# validator fire about a field some other lane happens to be writing junk into.
STATUSES = ("shaping", "shelved")

# How many paragraphs `--variant body` splits the shaping document into. One per
# writer, each far enough from its neighbours that two insertions can never land
# on the same line index — which is the only way two pure insertions can be
# called a conflict by `_merge_body`.
LANE_HEADING = "### Lane {:02d}"


def seeded_body(original: str, lanes: int) -> str:
    """The shaping document with `lanes` separately-editable paragraphs in it.

    Appended to the corpus's own body rather than replacing it, so the merge is
    still running over a document of a realistic length and shape.
    """
    out = [original.rstrip("\n"), "", "## Lanes", ""]
    for i in range(lanes):
        out += [LANE_HEADING.format(i), "", f"- [ ] lane {i:02d} as it was seeded", ""]
    return "\n".join(out) + "\n"


@dataclass
class Save:
    """One form save. Shaped so `verify.py`'s own checks can read it.

    `who`/`record`/`marker`/`status`/`outcome`/`commit`/`person_weeks`/`base` are
    the fields `verify.form_changes` and `verify.fields_are_values_somebody_sent`
    require; `field`/`value`/`lane` are this file's own.
    """

    who: str
    record: str
    marker: str
    status: str
    outcome: str | None
    commit: str | None
    person_weeks: float | None
    base: str
    field: str | None
    value: object
    lane: str


class SameRecordWriter(users.FormWriter):
    """A form writer aimed at one record, editing one thing nobody else edits.

    The request sequence is `FormWriter`'s and is the browser's: open the record
    page, ask `/api/health` for the commit it was drawn at, read the source at
    that commit out of the bare repository, PATCH. Only the payload differs, and
    it differs in exactly the way the variant is named for.
    """

    def __init__(self, *args, variant: str, index: int, path: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.variant = variant
        self.index = index
        self.path = path
        self.field, self.lane = LANES[index % len(LANES)]
        if variant == "field":
            self.field, self.lane = "person_weeks", "latest"
        elif variant == "body":
            self.field, self.lane = None, "body"
        self.saves: list[Save] = []

    # -- what this person sends ---------------------------------------------

    def marker(self, n: int) -> str:
        return f"WS{self.index:02d}.{n:04d}"

    def payload_for(self, source: str, n: int) -> tuple[dict, str, object]:
        """`(json payload, marker, the value sent)` for this save.

        The marker of an `accumulate` lane is the string the save actually
        ADDS to the list, not this writer's serial number, and the difference is
        not cosmetic: `verify.form_changes` decides "committed or LOST" by
        looking for the marker in the final file, so a marker the save never
        wrote reports every one of that writer's saves as lost data. The
        `depends_on` lane appends a real record id — an edge to a record that
        does not exist is dropped from the index — and judging it by `WS04.0007`
        called 13 honest merges a loss on the first run of this file.
        """
        marker = self.marker(n)
        record = parse_text(source, self.path)
        if self.variant == "body":
            _, body = split_front_matter(source)
            return ({"fields": {}, "body": self.with_line(body, marker)}, marker, None)
        value = self.value_for(record, marker, n)
        if self.lane == "accumulate":
            marker = str(value[-1])
        return ({"fields": {self.field: value}}, marker, value)

    def value_for(self, record, marker: str, n: int) -> object:
        field = self.field
        if self.variant == "field":
            # Distinct per (writer, save) and finite, so a final value names the
            # save that wrote it. `_reject_bad_types` refuses NaN and Infinity at
            # the door, which is why this is an ordinary two-decimal number.
            return round(10 + self.index + n / 100.0, 2)
        if field in ("tags", "prs", "assignees", "reviewers", "depends_on"):
            was = list(getattr(record, field) or [])
            if field == "depends_on":
                # Real ids, because an edge to a record that does not exist is
                # dropped from the index and would make the marker unfindable.
                return was + [self.dependency(n)]
            if field == "prs":
                return was + [f"C2SM/icon4py#{marker}"]
            return was + [marker]
        if field == "title":
            return f"Task under twelve hands {marker}"
        if field == "owner":
            return marker.lower()
        if field == "person_weeks":
            return round(1.0 + n / 100.0, 2)
        if field == "assigned_on":
            return (date(2026, 1, 1) + timedelta(days=n % 300)).isoformat()
        if field == "priority":
            return PRIORITIES[n % len(PRIORITIES)]
        if field == "review_waived":
            return bool(n % 2)
        if field == "status":
            return STATUSES[n % len(STATUSES)]
        raise AssertionError(f"no value rule for {field!r}")

    def dependency(self, n: int) -> str:
        """A real task id this record does not already wait on."""
        return self.pool[(self.index * 97 + n) % len(self.pool)]

    def with_line(self, body: str, marker: str) -> str:
        """One line inserted into THIS writer's own paragraph, and nowhere else.

        Found by heading text rather than by line number: every other writer is
        inserting at the same time, so a number read one request ago names a
        different line by the time this one is built.
        """
        lines = body.rstrip("\n").split("\n")
        heading = LANE_HEADING.format(self.index)
        try:
            at = lines.index(heading)
        except ValueError:
            return body
        lines.insert(at + 2, f"- [ ] {marker} by {self.login}")
        return "\n".join(lines) + "\n"

    # -- the save itself -----------------------------------------------------

    def save(self, base: str, source: str, n: int) -> None:
        payload, marker, value = self.payload_for(source, n)
        payload["base_commit"] = base
        try:
            record = parse_text(source, self.path)
            seen_weeks = record.person_weeks
        except ValueError:
            seen_weeks = None
        weeks = value if self.field == "person_weeks" else seen_weeks
        begun = time.monotonic()
        status, outcome, commit = "", None, None
        try:
            answer = self.client.patch(f"/api/record/{self.record}", json=payload)
            status = str(answer.status_code)
            if answer.status_code in (200, 409):
                got = answer.json()
                outcome, commit = got.get("outcome"), got.get("commit")
        except Exception as error:  # noqa: BLE001 - a driver thread may not take the run down
            status = type(error).__name__
        self.note(
            kind="PATCH",
            ms=(time.monotonic() - begun) * 1000,
            status=status,
            outcome=outcome,
            commit=commit,
            record=self.record,
            marker=marker,
        )
        self.saves.append(
            Save(
                self.who,
                self.record,
                marker,
                status,
                outcome,
                commit,
                weeks if isinstance(weeks, int | float) else None,
                base,
                self.field,
                value,
                self.lane,
            )
        )


# -- the checks this file adds, beyond the six `verify.py` already asks ------


def _norm(value: object) -> object:
    """One spelling for two representations of one value.

    A date comes back off the tip as a `datetime.date` and went out as a string;
    a list of tags comes back in file order. Compared as strings so that "the
    value that was sent" and "the value that is stored" are the same question.
    """
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value)


def latest_values(
    verdict: verify.Verdict, plan: Path, head: str, path: str, saves: list[Save]
) -> None:
    """Every last-writer-wins field holds its own writer's last ACCEPTED value.

    One writer per field, and a writer is one thread saving in sequence, so
    "last accepted" is unambiguous without consulting the commit graph: it is
    simply the last row that writer got a 200 for.

    This is the check that makes `--variant fields` mean anything. Marker
    presence cannot see a scalar being reverted, because a reverted scalar looks
    exactly like a scalar somebody else legitimately moved.
    """
    text = harness.read_blob(plan, head, path) or ""
    rows, wrong = [], []
    try:
        record = parse_text(text, path)
    except ValueError as error:
        verdict.say(verify.BROKEN, f"{path} no longer parses: {error}")
        verdict.checks["latest_fields"] = {"parsed": False}
        return
    by_writer: dict[str, list[Save]] = {}
    for one in saves:
        if one.lane == "latest":
            by_writer.setdefault(one.who, []).append(one)
    for who, sent in sorted(by_writer.items()):
        accepted = [
            s for s in sent if s.status == "200" and s.outcome in ("committed", "merged", "retried")
        ]
        if not accepted:
            rows.append({"who": who, "field": sent[0].field, "accepted": 0})
            continue
        last = accepted[-1]
        final = getattr(record, last.field, None)
        row = {
            "who": who,
            "field": last.field,
            "accepted": len(accepted),
            "last_sent": _norm(last.value),
            "final": _norm(final),
            "agrees": _norm(final) == _norm(last.value),
            "commit": last.commit,
        }
        rows.append(row)
        if not row["agrees"]:
            wrong.append(row)
    verdict.checks["latest_fields"] = rows
    if wrong:
        verdict.say(
            verify.LOST,
            f"{len(wrong)} fields do not hold the last value their only writer was "
            "answered 200 for",
            wrong,
        )


def one_value_sent(
    verdict: verify.Verdict, plan: Path, head: str, path: str, saves: list[Save]
) -> None:
    """The contended field holds a value SOMEBODY sent, and the right one.

    `--variant field` only. Twelve people move one key; the store must either
    refuse or take one of the twelve values whole. A value that is neither — an
    average, a base value nobody re-sent, an earlier save resurrected — is a
    merge inventing content, which is the worst outcome in this whole audit and
    the one no marker test can reach.

    "The right one" is the value carried by the newest accepted commit, read off
    the commit graph rather than off wall-clock order: twelve threads' 200s do
    not arrive in the order the store committed them.
    """
    import pygit2  # noqa: PLC0415

    text = harness.read_blob(plan, head, path) or ""
    try:
        record = parse_text(text, path)
    except ValueError as error:
        verdict.say(verify.BROKEN, f"{path} no longer parses: {error}")
        return
    final = record.person_weeks
    accepted = {
        s.commit: s
        for s in saves
        if s.status == "200" and s.outcome in ("committed", "merged", "retried") and s.commit
    }
    sent = {_norm(s.value) for s in saves if s.field == "person_weeks"}
    git = pygit2.Repository(str(plan))
    newest = None
    for commit in git.walk(git[head].id):
        match = accepted.get(str(commit.id)) or accepted.get(str(commit.id)[:10])
        if match is not None:
            newest = match
            break
    row = {
        "final": _norm(final),
        "in_sent_values": _norm(final) in sent,
        "distinct_values_sent": len(sent),
        "accepted": len(accepted),
        "newest_accepted_commit": newest.commit if newest else None,
        "newest_accepted_value": _norm(newest.value) if newest else None,
        "agrees_with_newest": (newest is not None and _norm(final) == _norm(newest.value)),
    }
    verdict.checks["contended_field"] = row
    if accepted and not row["in_sent_values"]:
        verdict.say(verify.LOST, "the contended field holds a value nobody sent", row)
    elif newest is not None and not row["agrees_with_newest"]:
        verdict.say(
            verify.LOST,
            "the contended field does not hold the value of the newest accepted commit",
            row,
        )


def lane_placement(
    verdict: verify.Verdict, plan: Path, head: str, path: str, saves: list[Save], lanes: int
) -> None:
    """Every inserted line is under the heading its author aimed at.

    `--variant body` only, and this is the sharp end of the whole exercise. A
    marker being SOMEWHERE in the file is not the same claim as the document
    still saying what its authors wrote: `_merge_body` assembles the union of
    both sides' spans with a single cursor, and a line that lands in the wrong
    paragraph is a document neither person wrote. A substring test cannot see it;
    this can.
    """
    text = harness.read_blob(plan, head, path) or ""
    _, body = split_front_matter(text)
    lines = body.split("\n")
    where: dict[str, int] = {}
    lane_now = -1
    for line in lines:
        for i in range(lanes):
            if line.strip() == LANE_HEADING.format(i):
                lane_now = i
        for token in line.split():
            if token.startswith("WS") and "." in token:
                where[token] = lane_now
    misplaced, missing = [], []
    for one in saves:
        if one.status != "200" or one.outcome not in ("committed", "merged", "retried"):
            continue
        found = where.get(one.marker)
        if found is None:
            missing.append({"who": one.who, "marker": one.marker, "commit": one.commit})
        elif found != one.index_of_lane:
            misplaced.append(
                {
                    "who": one.who,
                    "marker": one.marker,
                    "wanted_lane": one.index_of_lane,
                    "found_in_lane": found,
                }
            )
    verdict.checks["lane_placement"] = {
        "markers_in_file": len(where),
        "misplaced": misplaced[:10],
        "missing": len(missing),
    }
    if misplaced:
        verdict.say(
            verify.LOST,
            f"{len(misplaced)} committed lines are under a heading their author did not "
            "aim at — the merged document is one neither person wrote",
            misplaced[:10],
        )


def nothing_vanished(
    verdict: verify.Verdict, plan: Path, head: str, path: str, before_text: str
) -> None:
    """Every line and every frontmatter key that was there before is there now.

    Every edit any variant makes is additive — a list grows, a scalar moves, a
    line is inserted — so nothing that existed when the run started may be gone
    when it ends. This is the check that catches a merge silently DROPPING a
    hunk, which is the failure `_merge_body`'s single-cursor assembly can produce
    and which no marker test would notice, because the marker it drops belongs to
    the writer whose own save it is answering 200 to.
    """
    after_text = harness.read_blob(plan, head, path) or ""
    before_front, before_body = split_front_matter(before_text)
    after_front, after_body = split_front_matter(after_text)
    have = set(after_body.split("\n"))
    gone = [line for line in before_body.split("\n") if line.strip() and line not in have]

    def keys(front: str) -> set[str]:
        return {
            line.split(":", 1)[0].strip()
            for line in front.split("\n")
            if ":" in line and not line.startswith((" ", "-", "#"))
        }

    lost_keys = sorted(keys(before_front) - keys(after_front))
    verdict.checks["nothing_vanished"] = {
        "body_lines_before": len(before_body.split("\n")),
        "body_lines_after": len(after_body.split("\n")),
        "body_lines_gone": gone[:10],
        "frontmatter_keys_gone": lost_keys,
    }
    if gone:
        verdict.say(
            verify.LOST,
            f"{len(gone)} lines that were in the document before the run are not in it "
            "after — a merge dropped a hunk nobody edited",
            gone[:10],
        )
    if lost_keys:
        verdict.say(
            verify.LOST,
            f"{len(lost_keys)} frontmatter keys are gone from a record nobody deleted a key from",
            lost_keys,
        )


# -- one variant, end to end -------------------------------------------------


def run_one(variant: str, args: argparse.Namespace) -> dict:
    ledger = measure.Ledger()
    with harness.Harness(
        seed=args.seed,
        rtt_ms=args.rtt_ms,
        corpus="corpus",
        size=args.size,
        port=args.port,
        keep=False,
        remote=True,
    ) as world:
        ids = world.record_ids("task-")
        target = ids[0]
        head = harness.head_of(world.plan)
        path = harness.record_paths(world.plan, head)[target]

        if variant == "body":
            head = seed_the_lanes(world, target, path, head, args.writers)

        before = verify.snapshot(world.plan)
        before_text = harness.read_blob(world.plan, head, path) or ""
        started_at = head

        zero = time.monotonic()
        people: list[SameRecordWriter] = []
        for i in range(args.writers):
            person = SameRecordWriter(
                f"writer-{i}",
                harness.PEOPLE[i % len(harness.PEOPLE)],
                world,
                ledger,
                args.seed,
                0.0,
                zero,
                record=target,
                gap=args.gap,
                gap_max=args.gap_max,
                variant=variant,
                index=i,
                path=path,
            )
            person.pool = [x for x in ids if x != target][:400]
            person.index_of_lane = i
            people.append(person)

        began = time.monotonic()
        deadline = began + args.seconds
        for person in people:
            person.begin(deadline)
            person.start()
        for person in people:
            person.join(timeout=args.seconds + 240)
        elapsed = time.monotonic() - began

        driver_cpu = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_utime
            + resource.getrusage(resource.RUSAGE_SELF).ru_stime,
            2,
        )
        cpu, rss = world.cpu_seconds(), world.rss_mb()
        described = world.describe()
        log_tail = "\n".join(world.server_log().splitlines()[-10:])
        world.stop()

        saves = [row for person in people for row in person.saves]
        for one in saves:
            one.index_of_lane = int(one.who.split("-")[1])
        verdict = verify.Verdict()
        head = harness.head_of(world.plan)
        verdict.checks["head"] = head[:10]
        # `verify.py`'s own six, asked of the rows they can answer for. Only the
        # append-only lanes go to `form_changes`: a last-writer-wins scalar whose
        # marker is absent is not a loss, it is the next save.
        verify.form_changes(
            verdict, world.plan, head, [s for s in saves if s.lane in ("accumulate", "body")]
        )
        verify.conflict_markers(verdict, world.plan)
        verify.pushed(verdict, world.plan, world.origin)
        verify.fsck(verdict, world.plan, world.origin)
        verify.parses(verdict, world.plan, before)
        verify.authorship(verdict, world.plan, {p.login for p in people})
        verify.fields_are_values_somebody_sent(verdict, world.plan, head, saves)
        # And the four this file adds.
        nothing_vanished(verdict, world.plan, head, path, before_text)
        if variant == "fields":
            latest_values(verdict, world.plan, head, path, saves)
        if variant == "field":
            one_value_sent(verdict, world.plan, head, path, saves)
        if variant == "body":
            lane_placement(verdict, world.plan, head, path, saves, args.writers)

        commits = users.commit_log(world.plan)
        made = commits
        for n, one in enumerate(commits):
            if one["sha"] == started_at[:10]:
                made = commits[:n]
                break
        report = ledger.report(elapsed)
        patch_queue = queueing.concurrency(ledger.actions, "PATCH")
        return {
            "variant": variant,
            "config": {
                "writers": args.writers,
                "seconds": args.seconds,
                "gap": args.gap,
                "gap_max": args.gap_max,
                "rtt_ms": args.rtt_ms,
                "seed": args.seed,
                "target": target,
                "path": path,
            },
            "world": described,
            "measured": report,
            "attempted_saves": len(saves),
            "outcomes_by_lane": _by_lane(saves),
            "queueing": {
                "patch": patch_queue,
                "littles_law": queueing.littles_law(
                    patch_queue,
                    report["latency_ms"].get("PATCH", {}),
                    len([a for a in ledger.actions if a.kind == "PATCH"]) / elapsed,
                ),
            },
            "server": {"cpu_seconds": cpu, "rss_mb": rss, "driver_cpu_seconds": driver_cpu},
            "commits": {
                "made_by_this_run": len(made),
                "by_author": _tally(c["author"] for c in made),
            },
            "verification": verdict.as_dict(),
            "driver_failures": {p.who: p.failed for p in people if p.failed},
            "server_log_tail": log_tail,
            "strays": harness.strays(),
        }


def seed_the_lanes(world: harness.Harness, target: str, path: str, head: str, lanes: int) -> str:
    """Give the record one separately-editable paragraph per writer.

    Through the application's own PATCH rather than by rewriting the repository:
    a run that seeded its own git history would be measuring a plan the server
    never agreed to.
    """
    source = harness.read_blob(world.plan, head, path) or ""
    _, body = split_front_matter(source)
    answer = httpx.patch(
        f"{world.base}/api/record/{target}",
        json={"base_commit": head, "fields": {}, "body": seeded_body(body, lanes)},
        headers={"cookie": harness.cookie_for("jcanton")},
        timeout=60.0,
    )
    if answer.status_code != 200:
        raise RuntimeError(f"could not seed the lanes: {answer.status_code} {answer.text[:200]}")
    return harness.head_of(world.plan)


def _by_lane(saves: list[Save]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for one in saves:
        key = f"{one.lane}:{one.field or 'body'}"
        bucket = out.setdefault(key, {})
        name = one.outcome or one.status
        bucket[name] = bucket.get(name, 0) + 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def _tally(things) -> dict:
    out: dict[str, int] = {}
    for thing in things:
        out[thing] = out.get(thing, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# -- the CLI -----------------------------------------------------------------


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="write_same.py", description=__doc__.splitlines()[0])
    p.add_argument("--variant", default="all", choices=(*VARIANTS, "all"))
    p.add_argument("--writers", type=int, default=12)
    p.add_argument("--seconds", type=float, default=50.0)
    p.add_argument("--gap", type=float, default=0.8)
    p.add_argument("--gap-max", type=float, default=2.5)
    p.add_argument("--rtt-ms", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--size", choices=("small", "medium", "large"), default="medium")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--label", default=None, help="a name for this run in the JSON")
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    wanted = VARIANTS if args.variant == "all" else (args.variant,)
    runs = []
    for variant in wanted:
        run = run_one(variant, args)
        run["label"] = args.label or variant
        runs.append(run)
        _print(run)
    out = args.out or (ROOT / "docs" / "probes" / "load" / "write-same.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        try:
            existing = json.loads(out.read_text())
        except json.JSONDecodeError:
            existing = {"runs": []}
        merged = {r["label"]: r for r in existing.get("runs", [])}
    else:
        merged = {}
    for run in runs:
        merged[run["label"]] = run
    out.write_text(
        json.dumps({"runs": list(merged.values())}, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(f"\nwritten to {out}")
    return 0 if all(r["verification"]["ok"] and not r["driver_failures"] for r in runs) else 1


def _print(run: dict) -> None:
    c, w = run["config"], run["world"]
    print(
        f"\n=== write-same · {run['variant']} · {c['writers']} form writers on "
        f"{c['target']} for {c['seconds']}s ==="
    )
    print(
        f"plan: {w['records']} records ({w['corpus']}/{w['size']}), remote {w['remote']}, "
        f"push rtt {w['rtt_ms']} ms, port {w['port']}, gap {c['gap']}-{c['gap_max']}s"
    )
    print("\n-- latency (ms) --")
    print(measure.table(run["measured"]))
    print("\n-- answers --")
    for kind, statuses in run["measured"]["statuses"].items():
        print(f"  {kind:<24}{statuses}")
    if run["measured"]["errors"]:
        print(f"  errors: {run['measured']['errors']}")
    print("\n-- writes --")
    print(f"  attempted:      {run['attempted_saves']}")
    print(f"  store outcomes: {run['measured']['write_outcomes'] or '{}'}")
    print(f"  by lane:        {json.dumps(run['outcomes_by_lane'])}")
    print(f"  throughput:     {run['measured']['throughput']}")
    print(f"  commits:        {run['commits']['made_by_this_run']} made by this run")
    print(
        f"  server:         {run['server']['cpu_seconds']}s CPU, "
        f"{run['server']['rss_mb']} MB RSS (driver {run['server']['driver_cpu_seconds']}s)"
    )
    queue = run["queueing"]["patch"]
    if queue.get("n"):
        depth = queue["depth_at_start"]
        print(
            f"  queue at the writer lock: p50 {depth['p50']:.0f}  p90 {depth['p90']:.0f}  "
            f"max {depth['max']:.0f}  (peak {queue['peak_in_flight']}, "
            f"time-weighted mean {queue['mean_in_flight']})"
        )
    print("\n-- verification --")
    print(verify.summary(run["verification"]))
    for name in (
        "form_writes",
        "latest_fields",
        "contended_field",
        "lane_placement",
        "nothing_vanished",
        "push",
        "parses",
    ):
        if name in run["verification"]["checks"]:
            print(f"  {name}: {json.dumps(run['verification']['checks'][name], default=str)[:420]}")
    if run["driver_failures"]:
        print(f"\n!! the driver itself failed: {run['driver_failures']}")
    if run["strays"]:
        print(f"\n!! processes left behind: {run['strays']}")


if __name__ == "__main__":
    raise SystemExit(main())
