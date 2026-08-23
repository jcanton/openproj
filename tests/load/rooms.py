"""What a room commit costs everybody else.

    .venv/bin/python tests/load/rooms.py <host> <port> <n rooms> <seconds>

`_commit_room` is the one writer in this application that is NOT handed to
`asyncio.to_thread` — web.py says so at length and a test holds it there, because
the room must not suspend between the snapshot it commits and the absorb that
follows. The consequence is that the whole of `store.write`, push included, runs
on the event loop.

This measures that consequence from outside: N sockets each press Save on their
own record, while one thread times `GET /api/health` — the cheapest route in the
application, which does one `store.head()` and nothing else. Anything that route
waits for is the loop being held.

The sockets are `tests/wsclient.Client`, which is what the browser test already
uses, so this speaks the real protocol against a real server.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wsclient import Client  # noqa: E402


def health_prober(host, port, deadline, out, stop):
    url = f"http://{host}:{port}/api/health"
    while time.monotonic() < deadline and not stop.is_set():
        begun = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                response.read()
            out.append((time.monotonic() - begun) * 1000)
        except Exception:  # noqa: BLE001
            out.append(float("nan"))
        time.sleep(0.05)


def presser(host, port, entity_id, deadline, gap, results, stop):
    try:
        client = Client(host, port, f"/api/coedit/{entity_id}")
    except Exception as error:  # noqa: BLE001
        results.append(("open-failed", str(error)))
        return
    try:
        client.send_json({})
        client.receive_json()  # welcome
        n = 0
        while time.monotonic() < deadline and not stop.is_set():
            n += 1
            begun = time.monotonic()
            client.send_json({"t": "save", "fields": {"person_weeks": 1.0 + (n % 5) * 0.5}})
            outcome = None
            while outcome is None:
                frame = client.receive_json()
                if frame.get("t") in ("saved", "refused", "nothing"):
                    outcome = frame
            results.append((round((time.monotonic() - begun) * 1000, 1), outcome))
            time.sleep(gap)
    except Exception as error:  # noqa: BLE001
        results.append(("died", f"{type(error).__name__}: {error}"))
    finally:
        client.close()


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    n_rooms, seconds = int(sys.argv[3]), float(sys.argv[4])
    gap = float(sys.argv[5]) if len(sys.argv) > 5 else 3.0

    with urllib.request.urlopen(f"http://{host}:{port}/api/index.json", timeout=30) as r:
        index = json.load(r)
    ids = sorted(i for i in index["entities"] if i.startswith("task-"))[:n_rooms]

    stop = threading.Event()
    deadline = time.monotonic() + seconds
    health: list[float] = []
    results: list = []
    threads = [threading.Thread(target=health_prober, args=(host, port, deadline, health, stop))]
    threads += [
        threading.Thread(target=presser, args=(host, port, i, deadline, gap, results, stop))
        for i in ids
    ]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        stop.set()
        raise

    saves = [ms for ms, _ in results if isinstance(ms, (int, float))]
    kinds: dict[str, int] = {}
    for _, outcome in results:
        key = outcome.get("t", "?") if isinstance(outcome, dict) else str(outcome)[:40]
        if isinstance(outcome, dict) and outcome.get("t") == "saved":
            key = f"saved pushed={outcome.get('pushed')} {outcome.get('outcome')}"
        kinds[key] = kinds.get(key, 0) + 1
    good = [x for x in health if x == x]
    good.sort()
    print(
        json.dumps(
            {
                "rooms": n_rooms,
                "gap_s": gap,
                "saves": len(saves),
                "save_ms": {
                    "p50": round(statistics.median(saves), 1) if saves else None,
                    "p95": round(good and sorted(saves)[int(0.95 * (len(saves) - 1))] or 0, 1)
                    if saves
                    else None,
                    "max": round(max(saves), 1) if saves else None,
                },
                "save_outcomes": kinds,
                "health_ms": {
                    "n": len(good),
                    "p50": round(statistics.median(good), 1) if good else None,
                    "p95": round(good[int(0.95 * (len(good) - 1))], 1) if good else None,
                    "max": round(max(good), 1) if good else None,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
