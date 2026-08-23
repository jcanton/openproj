"""The read path's ceiling: twenty people with the plan open and nobody typing.

    uv run python tests/load/readload.py --readers 20 --seconds 60

`run.py --scenario read` measures readers against three routes and one ledger.
This measures the thing the deployment actually is — **one uvicorn process on
one throttled vCPU** — and it separates the three conditions that answer
different questions:

  serial   one client, no contention, a fresh server. Prices each route once
           COLD (the index cache empty) and then WARM, so the index build shows
           up as a subtraction rather than as a guess. Two fresh servers, one
           where the first request is `/` and one where it is `/detail/<id>`,
           because the cache is shared and whoever arrives first pays for it.
  warm-1   twenty readers for `--seconds`, against a server whose index cache is
           empty at t=0. Its first twenty requests are the thundering herd:
           `index_now()` takes no lock, so N concurrent readers on a cold key
           build N indexes.
  warm-2   the same twenty readers, the same server, THE SAME COMMIT. Nothing
           has been written, so every request is a cache hit. warm-1 versus
           warm-2 is the cache's whole contribution at the aggregate.
  writer   nineteen readers and ONE writer committing on a five-second clock.
           Every commit moves `store.head()` and so retires the `(commit, today)`
           key: this is what invalidation costs the other nineteen.

warm-1, warm-2 and writer run against ONE server so that the only difference
between them is what the load is, and in that order so that warm-1 and warm-2
share a commit.

The reader is `users.Reader` with `pages=Reader.ALL_PAGES`: `/`, `/issues`,
`/table`, `/graph`, `/timeline`, each followed by a `/detail/<id>`. Leaving
`/graph` and `/timeline` out would be measuring the read path with its two most
expensive renderers removed.

The writer is a `Committer` — `users.FormWriter` with the page read taken out
and a fixed cadence put in. A form writer that opens `/detail/<id>` first would
add read load to the phase that is supposed to isolate write-invalidation, and
its commit interval would be the queue's rather than five seconds.

Bounded on purpose: three sixty-second phases and two single-client probes is
about three and a half minutes of load, which is a shape. `--seconds` shortens
it; nothing here soaks.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import harness  # noqa: E402
import httpx  # noqa: E402
import measure  # noqa: E402
import users  # noqa: E402
import verify  # noqa: E402


class Committer(users.FormWriter):
    """One writer on a wall clock, so "a commit every five seconds" is true.

    `FormWriter.work` opens `/detail/<id>` before every save, which is what a
    browser does and is right for `run.py`. Here it is wrong twice: it puts a
    twenty-first reader into a phase whose whole point is to isolate what a
    WRITE costs the readers, and on a saturated server that page read is itself
    several seconds, so the commit cadence would be the queue's and not the
    clock's. The base commit still comes from `/api/health` — one cheap call
    that reads `store.head()` and never builds an index — and the body still
    comes out of the bare repository at that commit, exactly as `FormWriter`
    documents.
    """

    def work(self) -> None:
        paths = harness.record_paths(self.world.plan, harness.head_of(self.world.plan))
        path = paths[self.record]
        n = 0
        with self.client:
            while self.more():
                due = time.monotonic() + self.gap
                n += 1
                base = self.base_commit()
                if base is None:
                    continue
                body = harness.read_blob(self.world.plan, base, path)
                if body is None:
                    self.note(kind="PATCH", ms=0.0, status="no-such-blob", record=self.record)
                else:
                    self.save(base, body, n)
                nap = due - time.monotonic()
                if nap > 0:
                    time.sleep(nap)


# -- what the machine was doing --------------------------------------------


def loadavg() -> list[float]:
    out = subprocess.run(["sysctl", "-n", "vm.loadavg"], capture_output=True, text=True).stdout
    return [float(x) for x in out.strip().strip("{} ").split()]


def machine() -> dict:
    def sysctl(name: str) -> str:
        return subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True
        ).stdout.strip()

    return {
        "model": sysctl("hw.model"),
        "cores": int(sysctl("hw.ncpu")),
        "memory_gb": round(int(sysctl("hw.memsize")) / 1024**3, 1),
        "kernel": subprocess.run(["uname", "-sr"], capture_output=True, text=True).stdout.strip(),
    }


def driver_cpu() -> float:
    me = resource.getrusage(resource.RUSAGE_SELF)
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return me.ru_utime + me.ru_stime + kids.ru_utime + kids.ru_stime


# -- the ids, without touching the server ----------------------------------


def task_ids(world: harness.Harness) -> list[str]:
    """Record ids read straight out of the bare repository.

    `Harness.record_ids` asks `/api/index.json`, and that route calls
    `index_now()` — which would build and cache the index before the cold
    measurement had been taken. The cold number can only be taken once per
    server, so nothing here may warm it by accident.
    """
    paths = harness.record_paths(world.plan, harness.head_of(world.plan))
    return sorted(i for i in paths if i.startswith("task-"))


# -- what an idle instance costs the first person back ----------------------


def cold_start(args: argparse.Namespace, world_args: dict) -> dict:
    """Start a server from nothing and time the first page out of it.

    `--min-instances 0` is in `gcloud_deploy.sh`, so this is not an edge case: a
    few idle minutes and the instance is gone, and the next person to open the
    plan pays for it. What is timed here is process start, import, the history
    walk `serve_load.py` runs before uvicorn binds, and then one `GET /` on an
    empty index cache. What is NOT timed is Cloud Run's own container start and
    the clone of the plan from GitHub — neither is on this laptop — so the real
    number is this one plus those, never less.

    RSS is sampled at three points because the deploy line says `--memory
    512Mi` and the index is held in the process for as long as the commit
    stands.
    """
    out: list[dict] = []
    described: dict = {}
    for _ in range(args.cold_starts):
        with harness.Harness(**world_args) as world:
            idle = world.rss_mb()
            client = httpx.Client(
                base_url=world.base, timeout=120.0,
                headers={"cookie": harness.cookie_for(harness.PEOPLE[0])},
            )
            with client:
                begun = time.monotonic()
                answer = client.get("/")
                first = round((time.monotonic() - begun) * 1000, 1)
                held = world.rss_mb()
                begun = time.monotonic()
                client.get("/")
                second = round((time.monotonic() - begun) * 1000, 1)
            out.append({
                "startup_seconds": world.describe()["startup_seconds"],
                "first_page_ms": first,
                "second_page_ms": second,
                "status": answer.status_code,
                "rss_mb_idle": idle,
                "rss_mb_with_index": held,
                "records": world.describe()["records"],
            })
            described = world.describe()
    return {"runs": out, "world": described}


# -- one client, no contention ---------------------------------------------


def serial(world: harness.Harness, ids: list[str], first: str, passes: int = 3) -> dict:
    """Walk every route `passes` times with one client and nothing else running.

    Pass 1 is COLD only in its first request: `index_now()` caches on
    `(commit, today)` and every route in this file is drawn from that one index,
    so whichever request arrives first pays the build and the rest of pass 1 is
    already warm. That is exactly why `first` is a parameter — the person who
    pays is whoever happens to click first, and it is worth knowing whether that
    can be somebody following a link straight to a record.
    """
    detail = f"/detail/{ids[0]}"
    routes = [r for r in (*users.Reader.ALL_PAGES, detail) if r != first]
    routes.insert(0, first)
    client = httpx.Client(
        base_url=world.base, timeout=120.0,
        headers={"cookie": harness.cookie_for(harness.PEOPLE[0])},
    )
    seen: dict[str, list[float]] = {}
    # The bytes matter as much as the milliseconds here. `render.py` INLINES the
    # Ace bundle into the detail page rather than serving it from a cacheable
    # URL, so `/detail/<id>` is not only the slowest render, it is also the
    # largest response and it is uncacheable — over loopback that is free and
    # over the internet it is not.
    size: dict[str, int] = {}
    with client:
        for _ in range(passes):
            for route in routes:
                begun = time.monotonic()
                answer = client.get(route)
                took = (time.monotonic() - begun) * 1000
                name = "/detail/<id>" if route == detail else route
                seen.setdefault(name, []).append(round(took, 1))
                size[name] = len(answer.content)
                if answer.status_code != 200:
                    seen.setdefault(f"{name} !status", []).append(answer.status_code)
    return {
        "first_request_was": "/detail/<id>" if first == detail else first,
        "cold_ms": {k: v[0] for k, v in seen.items() if not k.endswith("!status")},
        "warm_ms": {
            k: round(sum(v[1:]) / len(v[1:]), 1)
            for k, v in seen.items()
            if not k.endswith("!status") and len(v) > 1
        },
        "every_ms": {k: v for k, v in seen.items() if not k.endswith("!status")},
        "bytes": size,
        "bad_statuses": {k: v for k, v in seen.items() if k.endswith("!status")},
    }


# -- one phase of concurrent load ------------------------------------------


def phase(
    name: str,
    world: harness.Harness,
    ids: list[str],
    readers: int,
    seconds: float,
    think: float,
    seed: int,
    writer_gap: float = 0.0,
) -> tuple[dict, Committer | None]:
    """`readers` readers (and optionally one committer) for `seconds`."""
    ledger = measure.Ledger()
    zero = time.monotonic()
    people: list[users.Person] = []
    committer: Committer | None = None
    nth = 0

    def login() -> str:
        nonlocal nth
        nth += 1
        return harness.PEOPLE[(nth - 1) % len(harness.PEOPLE)]

    if writer_gap:
        committer = Committer(
            "writer-0", login(), world, ledger, seed, 0.0, zero,
            record=ids[0], gap=writer_gap, stale=False, style="append",
        )
        people.append(committer)
    for i in range(readers):
        people.append(
            users.Reader(
                f"reader-{i}", login(), world, ledger, seed, 0.0, zero,
                ids=ids, think=think, pages=users.Reader.ALL_PAGES,
            )
        )

    cpu_before, driver_before, load_before = world.cpu_seconds(), driver_cpu(), loadavg()
    began = time.monotonic()
    deadline = began + seconds
    for person in people:
        person.begin(deadline)
        person.start()
    for person in people:
        person.join(timeout=seconds + 300)
    elapsed = time.monotonic() - began
    cpu = world.cpu_seconds() - cpu_before
    driver = driver_cpu() - driver_before

    reads = measure.Ledger(actions=[a for a in ledger.actions if a.who.startswith("reader")])
    out = {
        "phase": name,
        "readers": readers,
        "writer_gap_seconds": writer_gap or None,
        "seconds": round(elapsed, 1),
        "readers_only": reads.report(elapsed),
        "everything": ledger.report(elapsed),
        "herd": herd(ledger),
        "server_cpu_seconds": round(cpu, 1),
        "server_cores_used": round(cpu / elapsed, 2),
        "driver_cpu_seconds": round(driver, 1),
        "driver_cores_used": round(driver / elapsed, 2),
        "server_rss_mb": world.rss_mb(),
        "loadavg_before": load_before,
        "loadavg_after": loadavg(),
        "driver_failures": {p.who: p.failed for p in people if p.failed},
    }
    if committer is not None:
        out["commits_attempted"] = len(committer.sent)
        out["seconds_per_commit"] = (
            round(elapsed / len(committer.sent), 1) if committer.sent else None
        )
        out["sent"] = [vars(s) for s in committer.sent]
    return out, committer


def herd(ledger: measure.Ledger) -> dict:
    """The first request each reader made, which on a cold server is the herd.

    `index_now()` reads and writes `held` without a lock — deliberately, and the
    reasoning is written out in `web.py` — so on a cold key twenty concurrent
    readers do not queue behind one build, they each do their own. This is the
    row that shows it.
    """
    firsts: dict[str, measure.Action] = {}
    for one in ledger.actions:
        if not one.who.startswith("reader") or not one.kind.startswith("GET "):
            continue
        if one.who not in firsts or one.began < firsts[one.who].began:
            firsts[one.who] = one
    values = [a.ms for a in firsts.values()]
    return {
        "n": len(values),
        **{k: v for k, v in measure.percentiles(values).items() if k != "n"},
        "routes": sorted({a.kind for a in firsts.values()}),
    }


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="readload.py", description=__doc__.splitlines()[0])
    p.add_argument("--readers", type=int, default=20)
    p.add_argument("--seconds", type=float, default=60.0, help="per phase")
    p.add_argument("--think", type=float, default=0.5,
                   help="a reader's pause between pages. Small on purpose: this "
                        "measures a ceiling, not a comfortable afternoon")
    p.add_argument("--writer-gap", type=float, default=5.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--size", choices=("small", "medium", "large"), default="medium")
    p.add_argument("--corpus", choices=("corpus", "plans"), default="corpus")
    p.add_argument("--rtt-ms", type=float, default=0.0)
    p.add_argument("--cold-starts", type=int, default=3,
                   help="how many times to start a server from nothing and time the "
                        "first page. --min-instances 0 makes this a real page view")
    p.add_argument("--no-serial", action="store_true", help="skip the two serial probes")
    p.add_argument("--no-phases", action="store_true", help="skip the concurrent phases")
    p.add_argument("--rows", action="store_true")
    p.add_argument("--out", type=Path,
                   default=ROOT / "docs" / "probes" / "load" / "read-load.json")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    blob: dict = {
        "probe": "read-load",
        "seed": args.seed,
        "machine": machine(),
        "config": vars(args) | {"out": str(args.out)},
        "cold_start": None,
        "serial": [],
        "phases": [],
    }

    def world_args() -> dict:
        return dict(seed=args.seed, rtt_ms=args.rtt_ms, corpus=args.corpus,
                    size=args.size, remote=True)

    # -- what an idle instance costs the first person back ------------------
    if args.cold_starts:
        blob["cold_start"] = cold_start(args, world_args())
        blob["world"] = blob["cold_start"]["world"]
        print(f"  {args.cold_starts} cold starts done")

    # -- the two serial probes, each on its own fresh server ----------------
    if not args.no_serial:
        for which in ("landing", "detail"):
            with harness.Harness(**world_args()) as world:
                ids = task_ids(world)
                first = "/" if which == "landing" else f"/detail/{ids[0]}"
                blob["serial"].append(serial(world, ids, first))
                blob["world"] = world.describe()
            print(f"  cold probe ({which}) done")

    if args.no_phases:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str) + "\n")
        report(blob)
        print(f"\nwritten to {args.out}")
        return 0

    # -- one server, three phases, warm-1 and warm-2 on the same commit ------
    with harness.Harness(**world_args()) as world:
        blob["world"] = world.describe()
        ids = task_ids(world)
        before = verify.snapshot(world.plan)
        started_at = harness.head_of(world.plan)

        one, _ = phase("warm-1 (index cache empty at t=0)", world, ids,
                       args.readers, args.seconds, args.think, args.seed)
        blob["phases"].append(one)
        mid = harness.head_of(world.plan)
        print(f"  warm-1 done, head {mid[:10]}")

        two, _ = phase("warm-2 (same commit, cache hot)", world, ids,
                       args.readers, args.seconds, args.think, args.seed)
        blob["phases"].append(two)
        print(f"  warm-2 done, head {harness.head_of(world.plan)[:10]}")
        blob["same_commit"] = {
            "before_warm1": started_at[:10],
            "after_warm1": mid[:10],
            "after_warm2": harness.head_of(world.plan)[:10],
            "unchanged": started_at == mid == harness.head_of(world.plan),
        }

        three, committer = phase(
            f"writer (one commit every {args.writer_gap}s)", world, ids,
            args.readers - 1, args.seconds, args.think, args.seed,
            writer_gap=args.writer_gap,
        )
        blob["phases"].append(three)
        print("  writer phase done")

        cpu_total, rss = world.cpu_seconds(), world.rss_mb()
        log_tail = "\n".join(world.server_log().splitlines()[-15:])
        world.stop()

        sent = list(committer.sent) if committer else []
        blob["verification"] = verify.verify(
            world.plan, world.origin, [], sent,
            logins=set(harness.PEOPLE), before=before,
        )
        blob["commits"] = {
            "head_at_start": started_at[:10],
            "head_at_end": harness.head_of(world.plan)[:10],
            "made_by_the_writer_phase": len(sent),
        }
        blob["server"] = {"cpu_seconds_total": cpu_total, "rss_mb": rss}
        blob["server_log_tail"] = log_tail

    blob["strays"] = harness.strays()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str) + "\n")
    report(blob)
    print(f"\nwritten to {args.out}")
    return 0 if blob["verification"]["ok"] else 1


def report(blob: dict) -> None:
    m = blob["machine"]
    w = blob.get("world", {})
    print(f"\n=== read-load · seed {blob['seed']} ===")
    print(f"{m['model']}, {m['cores']} cores, {m['memory_gb']} GB, {m['kernel']}")
    print(f"plan: {w.get('records')} records ({w.get('corpus')}/{w.get('size')}), "
          f"remote {w.get('remote')}, port {w.get('port')}")

    if blob.get("cold_start"):
        print("\n-- a server started from nothing, first page on an empty index cache --")
        print(f"{'startup s':>11}{'1st page ms':>13}{'2nd page ms':>13}"
              f"{'RSS idle':>11}{'RSS+index':>11}")
        for one in blob["cold_start"]["runs"]:
            print(f"{one['startup_seconds']:>11}{one['first_page_ms']:>13}"
                  f"{one['second_page_ms']:>13}{one['rss_mb_idle']:>11}"
                  f"{one['rss_mb_with_index']:>11}")

    for probe in blob["serial"]:
        print(f"\n-- one client, nothing else running · first request "
              f"{probe['first_request_was']} --")
        print(f"{'route':<22}{'cold ms':>10}{'warm ms':>10}{'build ms':>10}{'KB':>10}")
        for route, cold in probe["cold_ms"].items():
            warm = probe["warm_ms"].get(route)
            build = f"{cold - warm:>10.1f}" if warm is not None else " " * 10
            kb = probe.get("bytes", {}).get(route, 0) / 1024
            print(f"{route:<22}{cold:>10.1f}{(warm if warm is not None else 0):>10.1f}"
                  f"{build}{kb:>10.1f}")
        if probe["bad_statuses"]:
            print(f"  !! non-200: {probe['bad_statuses']}")

    for ph in blob["phases"]:
        print(f"\n-- {ph['phase']} · {ph['readers']} readers · {ph['seconds']}s --")
        print(measure.table(ph["readers_only"]))
        t = ph["readers_only"]["throughput"]
        print(f"  reader pages/s: {t.get('pages_per_second')}   "
              f"server {ph['server_cpu_seconds']}s CPU = {ph['server_cores_used']} cores   "
              f"driver {ph['driver_cores_used']} cores   RSS {ph['server_rss_mb']} MB")
        print(f"  first request per reader (the herd): {ph['herd']}")
        if ph["readers_only"]["errors"]:
            print(f"  !! errors: {ph['readers_only']['errors']}")
        if ph.get("commits_attempted") is not None:
            print(f"  writer: {ph['commits_attempted']} PATCHes, one every "
                  f"{ph['seconds_per_commit']}s, outcomes "
                  f"{ph['everything']['write_outcomes']}")
        if ph["driver_failures"]:
            print(f"  !! driver threads failed: {ph['driver_failures']}")

    if not blob["phases"]:
        return
    print(f"\n-- same commit across warm-1 and warm-2: {blob.get('same_commit')} --")
    print("\n-- verification --")
    print(verify.summary(blob["verification"]))
    for name in ("form_writes", "push", "parses", "conflict_markers"):
        if name in blob["verification"]["checks"]:
            print(f"  {name}: "
                  f"{json.dumps(blob['verification']['checks'][name], default=str)[:400]}")
    if blob["strays"]:
        print(f"\n!! processes left behind: {blob['strays']}")


if __name__ == "__main__":
    raise SystemExit(main())
