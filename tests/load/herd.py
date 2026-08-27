"""Does one write make ONE index rebuild, or one per reader in flight?

    .venv/bin/python tests/load/herd.py <host> <port> [readers]

`index_now` (web.py:1119-1128) reads the memo, tests the commit, and on a miss
calls `_build_index_at` and stores the result. There is no lock and no
in-flight marker, so every reader that misses builds its own copy. Under the
GIL those builds do not overlap, they queue — so the cost of one write is
`build_index` once per reader that was in flight, not once.

Measured from outside, with no instrumentation in the application: fire N
simultaneous `GET /api/index.json` against a warm cache, then invalidate the
cache with one PATCH and fire the same N again. The difference is what the
write cost the readers.

`/api/index.json` and not a page, because it is `index_now()` plus a JSON dump
and nothing else — a page would add its own rendering to both halves.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request


def get(url, out):
    begun = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            response.read()
        out.append((time.monotonic() - begun) * 1000)
    except Exception as error:  # noqa: BLE001
        out.append(float("nan"))
        print("  request failed:", error, file=sys.stderr)


def burst(url, n):
    """N requests started as close to simultaneously as threads allow."""
    out: list[float] = []
    gate = threading.Barrier(n)

    def one():
        gate.wait()
        get(url, out)

    threads = [threading.Thread(target=one) for _ in range(n)]
    begun = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.monotonic() - begun) * 1000
    good = sorted(x for x in out if x == x)
    return wall, good


def patch(base, record_id, head, weeks):
    body = json.dumps(
        {"base_commit": head, "fields": {"person_weeks": weeks}, "body": None}
    ).encode()
    request = urllib.request.Request(
        f"{base}/api/record/{record_id}",
        data=body,
        method="PATCH",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    base = f"http://{host}:{port}"
    url = f"{base}/api/index.json"

    with urllib.request.urlopen(url, timeout=120) as response:
        index = json.load(response)
    record_id = sorted(i for i in index["records"] if i.startswith("task-"))[0]

    rounds = []
    for k in range(4):
        get(url, [])  # warm the memo
        warm_wall, warm = burst(url, n)
        head = json.load(urllib.request.urlopen(f"{base}/api/health", timeout=30))["head"]
        patch(base, record_id, head, 1.0 + k * 0.5)
        cold_wall, cold = burst(url, n)
        rounds.append(
            {
                "warm_burst_wall_ms": round(warm_wall, 1),
                "warm_p50_ms": round(statistics.median(warm), 1),
                "cold_burst_wall_ms": round(cold_wall, 1),
                "cold_p50_ms": round(statistics.median(cold), 1),
                "extra_wall_ms": round(cold_wall - warm_wall, 1),
            }
        )

    print(json.dumps({"readers": n, "rounds": rounds}, indent=2))
    extra = statistics.median(r["extra_wall_ms"] for r in rounds)
    print(
        f"\nOne write cost {n} in-flight readers {extra:.0f} ms of extra wall time.\n"
        "Compare against one `build_index` on this corpus (tests/load/micro.py).\n"
        "One rebuild shared => about one build. One rebuild each => about N builds."
    )


if __name__ == "__main__":
    main()
