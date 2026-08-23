"""Twenty people in twenty different records, and the commit burst they make.

The interesting moment is not the typing. It is the twenty seconds after
everybody stops: every room's `_watch` reaches `quiet_for() >= 20.0` in the same
second, and `_commit_room` is the ONE writer in this application that does not
run on a thread (`web.py:2591-2605`, deliberately, so nothing typed during a
commit can be deleted by the absorb that follows it). So twenty rooms going
quiet together is twenty `store.write` calls, each holding the event loop for a
whole commit, in a row.

This measures what that costs the person who is still typing in a
twenty-first room, and what it costs a page load — because a commit also moves
HEAD, and HEAD moving empties the single-entry index cache (`web.py:1119-1128`),
so the next page request rebuilds the whole index on the same event loop.

Arguments: seconds-of-typing, rooms, [--pages].
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from room import Member, Server, commits, percentiles, plan_at  # noqa: E402

TYPE_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
ROOMS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
PAGES = "--pages" in sys.argv


class Pages(threading.Thread):
    """Somebody with the plan open, reloading. One request at a time."""

    def __init__(self, port: int, where: str = "/") -> None:
        super().__init__(daemon=True)
        self.port, self.where = port, where
        self.times: list[float] = []
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            began = time.monotonic()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}{self.where}", timeout=30
                ) as answer:
                    answer.read()
                self.times.append(time.monotonic() - began)
            except Exception:  # noqa: BLE001 - a slow page is the measurement
                self.times.append(time.monotonic() - began)
            time.sleep(0.25)


def main(where: Path) -> dict:
    big = "--big" in sys.argv
    repo, _ = plan_at(
        where / "plan.git", pitches=(60 if big else 20), tasks_each=(8 if big else 4)
    )
    report_corpus = 60 * 8 if big else 20 * 4
    report: dict = {"rooms": ROOMS, "type_seconds": TYPE_SECONDS, "pages": PAGES,
                    "tasks_in_corpus": report_corpus}
    with Server(repo) as server:
        pages = Pages(server.port) if PAGES else None
        if pages:
            pages.start()
            time.sleep(3)
            report["page_seconds_idle"] = percentiles(list(pages.times))
            pages.times.clear()

        # The control room: two people who go on typing throughout, so their
        # propagation latency is a live readout of the event loop.
        control_id, control_path = "task-000000", "tasks/task-000000--task-1.md"
        measurer = Member(server.port, "measurer", control_id, 800001, applies=True)
        pinger = Member(server.port, "pinger", control_id, 800002, applies=True)

        # One person in each of `ROOMS` other records.
        others = []
        began_join = time.monotonic()
        for n in range(1, ROOMS + 1):
            others.append(Member(server.port, f"writer{n:02d}", f"task-{n:06x}", 810000 + n))
        report["join_seconds_for_all_rooms"] = round(time.monotonic() - began_join, 2)
        report["join_ms_each"] = round(
            (time.monotonic() - began_join) / max(1, ROOMS) * 1000, 1
        )

        sent: dict[str, float] = {}
        seq = 0

        def ping() -> None:
            nonlocal seq
            seq += 1
            token = f"{seq:04d}"
            sent[token] = time.monotonic()
            pinger.type(0, f"§{token}§")

        # Everybody types for a while, then everybody in the other rooms stops
        # at the same moment. The control room keeps going.
        started = time.monotonic()
        while time.monotonic() - started < TYPE_SECONDS:
            ping()
            for one in others:
                one.type(0, "z")
            time.sleep(0.2)
        stopped = time.monotonic()
        report["marks_before"] = len(sent)
        quiet_marks = set(sent)

        # Now only the control room types. Twenty seconds from here, twenty
        # rooms commit at once.
        while time.monotonic() - stopped < 40:
            ping()
            time.sleep(0.2)
        time.sleep(2)

        after = {t: w for t, w in sent.items() if t not in quiet_marks}
        during = [
            measurer.marks[t] - w
            for t, w in after.items()
            if t in measurer.marks and 18 <= w - stopped <= 30
        ]
        calm = [
            measurer.marks[t] - w
            for t, w in after.items()
            if t in measurer.marks and w - stopped < 15
        ]
        report["propagation_ms_calm"] = percentiles(calm)
        report["propagation_ms_during_commit_burst"] = percentiles(during)
        report["commits"] = len(commits(repo)) - 1
        report["control_room_committed"] = any(
            control_path.split("/")[-1].split("--")[0] in message
            for _, message in commits(repo)
        )
        report["evicted"] = [m.login for m in [measurer, pinger, *others] if m.gone]
        if pages:
            pages.stop.set()
            report["page_seconds_under_load"] = percentiles(list(pages.times))
            report["page_seconds_worst"] = round(max(pages.times), 2)
            report["page_seconds_mean"] = round(statistics.mean(pages.times), 2)
        report["rss_mb"] = round(server.rss_mb(), 1)
        report["cpu_seconds_total"] = round(server.cpu_seconds(), 2)
        for one in [measurer, pinger, *others]:
            one.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
