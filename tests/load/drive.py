"""Twenty people at once, against a running openproj, for a bounded window.

    .venv/bin/python tests/load/drive.py <base-url> <scenario> <seconds> [writers] [readers] [gap_s]

Scenarios:

  read        readers only — the floor, and what everything else is measured against
  spread      writers each own one record; readers browse throughout
  same        every writer PATCHes the SAME record — the merge and conflict path
  mixed       spread, plus every writer holding an /api/events stream open

Every writer re-reads its record's `base_commit` from `/api/index.json` before
each save, which is what a browser does: the page is drawn at a commit and the
save is compared against it. A writer that always sent HEAD would never collide
and would measure nothing.

Prints one JSON object. No file is written and no state is kept, so a run that
is killed leaves nothing behind but the server the caller started.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx


def pct(samples, q):
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


class Tally:
    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = {}
        self.outcome: dict[str, int] = {}

    def hit(self, what: str, ms: float, outcome: str | None = None) -> None:
        self.latency.setdefault(what, []).append(ms)
        if outcome:
            self.outcome[outcome] = self.outcome.get(outcome, 0) + 1

    def report(self) -> dict:
        return {
            "latency_ms": {
                what: {
                    "n": len(v),
                    "p50": pct(v, 0.5),
                    "p95": pct(v, 0.95),
                    "max": round(max(v), 1),
                }
                for what, v in sorted(self.latency.items())
            },
            "outcomes": self.outcome,
        }


async def reader(client, base, deadline, tally, page="/"):
    while time.monotonic() < deadline:
        begun = time.monotonic()
        try:
            r = await client.get(base + page)
            tally.hit(f"GET {page}", (time.monotonic() - begun) * 1000, f"read {r.status_code}")
        except Exception as error:  # noqa: BLE001
            tally.hit(
                f"GET {page}",
                (time.monotonic() - begun) * 1000,
                f"read {type(error).__name__}",
            )
        await asyncio.sleep(0.2)


async def head_commit(client, base):
    r = await client.get(base + "/api/health")
    return r.json().get("head")


async def writer(client, base, deadline, tally, record_id, gap, stale):
    """One person saving one record, over and over.

    `stale` keeps the base_commit from the FIRST read for the whole run, which
    is a browser tab left open — the case the compare-and-swap exists for.
    """
    held = None
    n = 0
    while time.monotonic() < deadline:
        if held is None or not stale:
            held = await head_commit(client, base)
        n += 1
        begun = time.monotonic()
        try:
            r = await client.patch(
                f"{base}/api/record/{record_id}",
                json={
                    "base_commit": held,
                    "fields": {"person_weeks": 1.0 + (n % 7) * 0.5},
                    "body": None,
                },
            )
            ms = (time.monotonic() - begun) * 1000
            if r.status_code in (200, 409):
                tally.hit("PATCH", ms, f"{r.status_code} {r.json().get('outcome')}")
            else:
                tally.hit("PATCH", ms, f"{r.status_code}")
        except Exception as error:  # noqa: BLE001
            tally.hit("PATCH", (time.monotonic() - begun) * 1000, type(error).__name__)
        await asyncio.sleep(gap)


async def stream(client, base, deadline):
    try:
        async with client.stream("GET", base + "/api/events", timeout=None) as response:
            async for _ in response.aiter_lines():
                if time.monotonic() > deadline:
                    return
    except Exception:  # noqa: BLE001
        return


async def main():
    base = sys.argv[1].rstrip("/")
    scenario = sys.argv[2]
    seconds = float(sys.argv[3])
    writers = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    readers = int(sys.argv[5]) if len(sys.argv) > 5 else 10
    gap = float(sys.argv[6]) if len(sys.argv) > 6 else 2.0
    stale = scenario.endswith("-stale")
    scenario = scenario.removesuffix("-stale")

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(timeout=60.0, limits=limits) as client:
        index = (await client.get(base + "/api/index.json")).json()
        ids = sorted(i for i in index["records"] if i.startswith("task-"))
        deadline = time.monotonic() + seconds
        tally = Tally()
        jobs = []
        if scenario == "read":
            jobs += [reader(client, base, deadline, tally) for _ in range(readers)]
            jobs += [reader(client, base, deadline, tally, "/table") for _ in range(readers)]
        elif scenario in ("spread", "mixed"):
            jobs += [
                writer(client, base, deadline, tally, ids[i % len(ids)], gap, stale)
                for i in range(writers)
            ]
            jobs += [reader(client, base, deadline, tally) for _ in range(readers)]
            if scenario == "mixed":
                jobs += [stream(client, base, deadline) for _ in range(writers)]
        elif scenario == "same":
            jobs += [
                writer(client, base, deadline, tally, ids[0], gap, stale) for _ in range(writers)
            ]
            jobs += [reader(client, base, deadline, tally) for _ in range(readers)]
        else:
            raise SystemExit(f"unknown scenario {scenario!r}")

        begun = time.monotonic()
        await asyncio.gather(*jobs)
        elapsed = time.monotonic() - begun

    out = tally.report()
    saves = sum(n for k, n in tally.outcome.items() if k.startswith("200 "))
    out["seconds"] = round(elapsed, 1)
    out["scenario"] = scenario + ("-stale" if stale else "")
    out["writers"] = writers
    out["readers"] = readers
    out["gap_s"] = gap
    out["saves_per_second"] = round(saves / elapsed, 2) if elapsed else 0
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
