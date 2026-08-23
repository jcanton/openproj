"""One bounded load run, end to end.

    uv run python tests/load/run.py --scenario mixed --users 3 --seconds 20

Builds a plan and a bare `origin`, starts one server on a loopback port in
8900-8999, drives it with N genuinely simultaneous people of each kind, stops
everything, and then asks the repository what actually happened. Prints a
report and writes `docs/probes/load/<scenario>.json`.

Scenarios — the difference between them is only WHO IS AIMED AT WHAT, which is
the question jcanton asked:

  read     readers only. The floor everything else is measured against.
  spread   twenty people on twenty different records. Contention is the writer
           lock and the GIL, never the merge.
  same     everybody on ONE record: form writers and co-editors both. The merge,
           the compare-and-swap and the room-versus-PATCH race, all at once.
  mixed    the realistic shape: readers browsing, form writers each on their own
           record, and the co-editors together in one room. `--overlap` puts one
           form writer into the co-editors' record as well.

Determinism: `--seed` seeds every simulated person's own `random.Random`, and
the corpus generator takes it too. Two runs with the same flags issue the same
requests in the same order to the same records; what differs between them is
the scheduling, which is the thing being measured.

Bounded: `--seconds` is a wall clock and every thread reads it. Nothing here
soaks — 60 to 120 seconds is a shape, and ten minutes is the same shape with a
bigger bill on a laptop somebody else is using.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import harness  # noqa: E402
import measure  # noqa: E402
import users  # noqa: E402
import verify  # noqa: E402

SCENARIOS = ("read", "spread", "same", "mixed")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="run.py", description=__doc__.splitlines()[0])
    p.add_argument("--scenario", choices=SCENARIOS, default="mixed")
    p.add_argument("--users", type=int, default=3, help="how many of EACH kind")
    p.add_argument("--readers", type=int, default=None)
    p.add_argument("--writers", type=int, default=None)
    p.add_argument("--coeditors", type=int, default=None)
    p.add_argument("--seconds", type=float, default=60.0, help="the load window")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--rtt-ms",
        type=float,
        default=0.0,
        help="charge every push and fetch this much, in pygit2, outside the app. "
        "store.py prices a GitHub round trip at about 600 ms",
    )
    p.add_argument("--gap", type=float, default=2.0, help="seconds between a form writer's saves")
    p.add_argument("--think", type=float, default=0.4, help="seconds between a reader's pages")
    p.add_argument("--stale", action="store_true",
                   help="form writers keep their first base_commit: a tab left open")
    p.add_argument("--body-edit", choices=("append", "mixed"), default="append",
                   help="'mixed' makes half the writers insert and half replace at one heading")
    p.add_argument("--overlap", action="store_true",
                   help="put one form writer on the co-editors' record as well")
    p.add_argument("--coedit-save-every", type=float, default=0.0,
                   help="force a room Save on this clock (0 = only at the end)")
    p.add_argument("--no-coedit-save", action="store_true",
                   help="never press Save: measures the twenty-second quiet window alone")
    p.add_argument("--corpus", choices=("corpus", "plans"), default="corpus")
    p.add_argument("--size", choices=("small", "medium", "large"), default="medium")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-remote", action="store_true",
                   help="run with no origin at all — measures the store without the push")
    p.add_argument("--keep", action="store_true", help="leave the temporary plan on disk")
    p.add_argument("--rows", action="store_true", help="put every single action in the JSON")
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def counts(args: argparse.Namespace) -> tuple[int, int, int]:
    readers = args.users if args.readers is None else args.readers
    writers = args.users if args.writers is None else args.writers
    editors = args.users if args.coeditors is None else args.coeditors
    if args.scenario == "read":
        return readers, 0, 0
    return readers, writers, editors


def targets(scenario: str, ids: list[str], writers: int, editors: int, overlap: bool):
    """Which record each person is aimed at.

    Sorted ids and modular arithmetic, never a random draw, so two runs with the
    same flags contend over the same files.
    """
    if scenario == "same":
        room = ids[0]
        return [room] * writers, [room] * editors
    room = ids[0]
    # Form writers start past the room unless asked to collide with it, so that
    # `mixed` and `spread` measure one contention at a time.
    offset = 0 if overlap else 1
    each = [ids[(offset + i) % len(ids)] for i in range(writers)]
    if scenario == "spread":
        rooms = [ids[(offset + writers + i) % len(ids)] for i in range(editors)]
    else:
        rooms = [room] * editors
    if overlap and writers:
        each[0] = room
    return each, rooms


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    readers, writers, editors = counts(args)
    ledger = measure.Ledger()
    people: list[users.Person] = []
    coeditors: list[users.CoEditor] = []
    formwriters: list[users.FormWriter] = []

    with harness.Harness(
        seed=args.seed,
        rtt_ms=args.rtt_ms,
        corpus=args.corpus,
        size=args.size,
        port=args.port,
        keep=args.keep,
        remote=not args.no_remote,
    ) as world:
        ids = world.entity_ids("task-")
        if len(ids) < 2:
            raise SystemExit("the corpus has no tasks to aim at")
        # What the plan looked like before anybody touched it. A generated corpus
        # arrives with warnings of its own, and the only honest question after a
        # run is what CHANGED.
        before = verify.snapshot(world.plan)
        started_at = harness.head_of(world.plan)
        writer_ids, room_ids = targets(args.scenario, ids, writers, editors, args.overlap)

        zero = time.monotonic()
        # Logins are handed out to the co-editors first: a room draws a presence
        # list and credits a commit, so that is where identity is visible.
        nth = 0

        def login() -> str:
            nonlocal nth
            name = harness.PEOPLE[nth % len(harness.PEOPLE)]
            nth += 1
            return name

        for i in range(editors):
            person = users.CoEditor(
                f"coeditor-{i}", login(), world, ledger, args.seed, 0.0, zero,
                entity=room_ids[i],
                client_id=1000 + i,
                seed=args.seed,
                save_every=args.coedit_save_every,
                save_at_end=not args.no_coedit_save,
            )
            coeditors.append(person)
            people.append(person)
        for i in range(writers):
            style = "append"
            if args.body_edit == "mixed":
                style = "insert" if i % 2 == 0 else "replace"
            person = users.FormWriter(
                f"writer-{i}", login(), world, ledger, args.seed, 0.0, zero,
                entity=writer_ids[i], gap=args.gap, stale=args.stale, style=style,
            )
            formwriters.append(person)
            people.append(person)
        for i in range(readers):
            people.append(
                users.Reader(
                    f"reader-{i}", login(), world, ledger, args.seed, 0.0, zero,
                    ids=ids, think=args.think,
                )
            )

        # Connect every socket before the clock starts. Twenty websockets is
        # setup, not load; inside the window it would be a connection storm in
        # the first second of every run and would show up as the room being slow.
        for person in coeditors:
            person.connect()

        began = time.monotonic()
        deadline = began + args.seconds
        for person in people:
            person.begin(deadline)
            person.start()
        for person in people:
            person.join(timeout=args.seconds + 180)
        elapsed = time.monotonic() - began

        # Typing has stopped everywhere before anybody presses Save, so a save
        # made by one person carries everybody's text and "is every character
        # committed" is a question with one answer.
        for person in coeditors:
            person.finish()
        # The last socket out triggers a commit that nobody waits for. A second
        # and a half is more than a `file://` push and less than a coffee.
        time.sleep(1.5)

        cpu, rss = world.cpu_seconds(), world.rss_mb()
        described = world.describe()
        log_tail = "\n".join(world.server_log().splitlines()[-12:])
        world.stop()

        sent = [row for person in formwriters for row in person.sent]
        typed = [person.result for person in coeditors]
        verdict = verify.verify(
            world.plan,
            world.origin if not args.no_remote else None,
            typed,
            sent,
            logins={person.login for person in people},
            before=before,
        )
        commits = users.commit_log(world.plan)
        made = [c for c in commits]
        for n, one in enumerate(commits):
            if one["sha"] == started_at[:10]:
                made = commits[:n]
                break

    report = ledger.report(elapsed)
    blob = {
        "scenario": args.scenario,
        "seed": args.seed,
        "config": {
            "readers": readers, "writers": writers, "coeditors": editors,
            "seconds": args.seconds, "gap": args.gap, "think": args.think,
            "stale": args.stale, "body_edit": args.body_edit, "overlap": args.overlap,
            "coedit_save_every": args.coedit_save_every,
            "coedit_save_at_end": not args.no_coedit_save,
        },
        "world": described,
        "measured": report,
        "server": {"cpu_seconds": cpu, "rss_mb": rss},
        "commits": {"total": len(commits), "made_by_this_run": len(made),
                    "by_author": _tally(c["author"] for c in made)},
        "verification": verdict,
        "driver_failures": {p.who: p.failed for p in people if p.failed},
        "server_log_tail": log_tail,
        "strays": harness.strays(),
    }
    if args.rows:
        blob["actions"] = ledger.rows()

    out = args.out or (ROOT / "docs" / "probes" / "load" / f"{args.scenario}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str) + "\n")
    _print(blob, report, verdict, out)
    return 0 if verdict["ok"] and not blob["driver_failures"] else 1


def _tally(things) -> dict:
    out: dict[str, int] = {}
    for thing in things:
        out[thing] = out.get(thing, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _print(blob: dict, report: dict, verdict: dict, out: Path) -> None:
    c, w = blob["config"], blob["world"]
    print(f"\n=== {blob['scenario']} · seed {blob['seed']} ===")
    print(
        f"{c['readers']} readers, {c['writers']} form writers, {c['coeditors']} co-editors "
        f"for {c['seconds']}s\n"
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
    print(f"  commits:        {blob['commits']['made_by_this_run']} made by this run, "
          f"by {blob['commits']['by_author']}")
    print(f"  server:         {blob['server']['cpu_seconds']}s CPU, "
          f"{blob['server']['rss_mb']} MB RSS")
    print("\n-- verification --")
    print(verify.summary(verdict))
    for name in ("coeditors", "form_writes", "push", "parses"):
        if name in verdict["checks"]:
            print(f"  {name}: {json.dumps(verdict['checks'][name], default=str)[:400]}")
    if blob["driver_failures"]:
        print(f"\n!! the driver itself failed: {blob['driver_failures']}")
    if blob["strays"]:
        print(f"\n!! processes left behind: {blob['strays']}")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    raise SystemExit(main())
