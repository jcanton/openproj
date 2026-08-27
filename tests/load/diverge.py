"""What it takes to stop this service writing, and whether it ever starts again.

    uv run python tests/load/diverge.py --seconds 30

Thirty seconds, two form writers, one small plan. Not a load run — a probe of
one sequence, and the sequence is the one `store.put_asset`'s docstring says has
already happened once in production:

    1. a push fails while the commit succeeds     (the remote is briefly unreachable)
    2. somebody pushes to the plan from a terminal (which `store.py` says will
       happen in week one)
    3. every write from then on

`Store._finish` catches everything a push can fail with that is not a rejection
and reports `pushed=False` — correctly, because the commit is real and local, and
refusing the write would mean the tracker stops working whenever GitHub does. But
`WriteResult.pushed` reaches exactly one caller in the whole application (the
co-editing socket's `saved` frame). `PATCH /api/record` drops it, so the browser
is answered 200 with a commit sha for a commit that is on an ephemeral disk and
nowhere else.

From there the two histories have forked, and `_absorb_remote` is explicitly and
correctly written never to guess which commits to discard — so it raises
`StoreDiverged`, for ever, and the question this probe answers is what a person
sees when it does.

The unreachable remote is made by taking the write bit off the bare `origin`
directory, which is outside `src/openproj/` and outside the server process: the
push really does fail in libgit2, the way it would against a GitHub that is
having an afternoon. Permissions are restored in a `finally` whatever happens,
because the directory is inside the harness's own temporary tree and a run that
left it unwritable would make its own cleanup fail.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import adversarial  # noqa: E402
import harness  # noqa: E402
import measure  # noqa: E402
import users  # noqa: E402
import verify  # noqa: E402


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="diverge.py", description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--writers", type=int, default=2)
    p.add_argument("--gap", type=float, default=1.5)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    ledger = measure.Ledger()
    window = args.seconds
    unreachable_at = round(window * 0.27, 1)
    reachable_at = round(window * 0.53, 1)

    with harness.Harness(
        seed=args.seed, corpus="corpus", size="small", port=args.port, remote=True
    ) as world:
        ids = world.record_ids("task-")
        before = verify.snapshot(world.plan)
        zero = time.monotonic()
        writers = [
            users.FormWriter(
                f"writer-{i}",
                harness.PEOPLE[i],
                world,
                ledger,
                args.seed,
                0.0,
                zero,
                record=ids[i],
                gap=args.gap,
                style="append",
            )
            for i in range(args.writers)
        ]
        # One reader, because half of what this probe is about is that nothing
        # a reader can see changes: every page is drawn from the LOCAL ref, so a
        # service that cannot write a single character still answers 200 on
        # every route and on `/api/health`. That is why nobody finds out.
        reader = users.Reader(
            "reader-0", harness.PEOPLE[3], world, ledger, args.seed, 0.0, zero, ids=ids, think=0.4
        )
        terminal = adversarial.Terminal(
            origin=world.origin,
            plan=world.plan,
            clone=world.work / "terminal",
            base_url=world.base,
            zero=zero,
            schedule=[],
            watch_seconds=10.0,
        )
        terminal.prepare()

        timeline: list[dict] = []
        began = time.monotonic()
        deadline = began + window
        for one in [*writers, reader]:
            one.begin(deadline)
            one.start()
        try:
            time.sleep(max(0.0, zero + unreachable_at - time.monotonic()))
            subprocess.run(["chmod", "-R", "a-w", str(world.origin)], check=True)
            timeline.append(
                {
                    "at": unreachable_at,
                    "what": "origin made unwritable: "
                    "every push from here fails while the commit succeeds",
                }
            )

            time.sleep(max(0.0, zero + reachable_at - time.monotonic()))
            subprocess.run(["chmod", "-R", "u+w", str(world.origin)], check=True)
            local, remote = harness.head_of(world.plan), harness.head_of(world.origin)
            push = terminal._push(reachable_at, ids[-1], "TD01")
            timeline.append(
                {
                    "at": reachable_at,
                    "what": "origin writable again, and a person pushed to it",
                    "instance_head": local[:10],
                    "origin_head_before": remote[:10],
                    "terminal_commit": (push.sha or "")[:10],
                    "pushed_ok": push.pushed_ok,
                    "instance_was_ahead_by": _ahead(world.plan, local, remote),
                }
            )
        finally:
            subprocess.run(["chmod", "-R", "u+w", str(world.origin)], check=False)

        for one in [*writers, reader]:
            one.join(timeout=window + 120)
        elapsed = time.monotonic() - began
        log_tail = "\n".join(world.server_log().splitlines()[-25:])
        world.stop()

        sent = [row for one in writers for row in one.sent]
        verdict = verify.verify(
            world.plan, world.origin, [], sent, logins={one.login for one in writers}, before=before
        )
        phases = _by_phase(ledger, unreachable_at, reachable_at)
        reading = _by_phase(ledger, unreachable_at, reachable_at, kind="GET /")
        head = harness.head_of(world.plan)
        final = {
            "instance_head": head[:10],
            "origin_head": harness.head_of(world.origin)[:10],
            "markers_on_the_instance_only": _instance_only(world, sent, head),
        }

    blob = {
        "probe": "diverge",
        "seed": args.seed,
        "config": {
            "seconds": window,
            "writers": args.writers,
            "gap": args.gap,
            "unreachable_at": unreachable_at,
            "reachable_at": reachable_at,
        },
        "world": world.describe(),
        "timeline": timeline,
        "by_phase": phases,
        "reads_by_phase": reading,
        "measured": ledger.report(elapsed),
        "final": final,
        "verification": verdict,
        "server_log_tail": log_tail,
        "strays": harness.strays(),
    }
    out = args.out or (ROOT / "docs" / "probes" / "load" / "diverge.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str) + "\n")

    print(f"\n=== diverge · seed {blob['seed']} ===")
    for line in timeline:
        print(f"  t+{line['at']:>5.1f}s  {json.dumps(line, default=str)}")
    print("\n-- what a save was answered, by phase --")
    for name, block in phases.items():
        print(f"  {name:<44}{block}")
    print("\n-- and what the landing page was answered, in the same phases --")
    for name, block in reading.items():
        print(f"  {name:<44}{block}")
    print(f"\n-- at the end --\n  {json.dumps(final, default=str)}")
    print("\n-- verification --")
    print(verify.summary(verdict))
    for name in ("form_writes", "push", "fsck", "parses"):
        if name in verdict["checks"]:
            print(f"  {name}: {json.dumps(verdict['checks'][name], default=str)[:300]}")
    if blob["strays"]:
        print(f"\n!! processes left behind: {blob['strays']}")
    print(f"\nwritten to {out}")
    return 0


def _ahead(plan: Path, local: str, remote: str) -> int:
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(plan))
    seen = {str(c.id) for c in git.walk(git[remote].id)}
    return sum(1 for c in git.walk(git[local].id) if str(c.id) not in seen)


def _by_phase(
    ledger: measure.Ledger, unreachable_at: float, reachable_at: float, kind: str = "PATCH"
) -> dict:
    """Every PATCH answer, in the phase it was answered in.

    The phases are the whole probe: `200` means one thing before the remote goes
    away and something quite different after it.
    """
    out: dict[str, dict[str, int]] = {
        "1 remote reachable": {},
        "2 remote unwritable (commits stay local)": {},
        "3 after somebody else pushed": {},
    }
    for action in ledger.actions:
        if action.kind != kind:
            continue
        if action.began < unreachable_at:
            name = "1 remote reachable"
        elif action.began < reachable_at:
            name = "2 remote unwritable (commits stay local)"
        else:
            name = "3 after somebody else pushed"
        out[name][action.status] = out[name].get(action.status, 0) + 1
    return out


def _instance_only(world: harness.Harness, sent: list, head: str) -> list[str]:
    """Markers a save was answered 200 for that are on the instance and not on
    the remote. On Cloud Run this list is what dies with the container."""
    paths_local = harness.record_paths(world.plan, head)
    origin_head = harness.head_of(world.origin)
    paths_remote = harness.record_paths(world.origin, origin_head)
    orphaned = []
    for one in sent:
        if one.status != "200":
            continue
        here = harness.read_blob(world.plan, head, paths_local.get(one.record, "")) or ""
        there = harness.read_blob(world.origin, origin_head, paths_remote.get(one.record, "")) or ""
        if one.marker in here and one.marker not in there:
            orphaned.append(one.marker)
    return orphaned


if __name__ == "__main__":
    raise SystemExit(main())
