"""What fifteen people typing in ONE room cost, and whether the room ever commits.

Two questions in one run, because they are the same run:

1. **Fan-out.** Every keystroke is one update broadcast to every other socket, so
   fifteen typists at five characters a second is 15x14 = 210 outbound frames a
   second on one vCPU in Python. This measures the server's CPU seconds per wall
   second, which is the headroom against `--cpu 1`, and the time between one
   person's keystroke leaving their socket and arriving at somebody else's.

2. **The quiet window.** `Room.apply` restarts `_quiet_since` on every update
   (`coedit.py:228`), and `_watch` commits only at `quiet_for() >= 20.0`
   (`web.py:2719`). So this also answers whether a busy room ever commits at all,
   by counting the commits git has at the end.

Bounded: `SECONDS` of load and nothing longer. This measures shape, not soak.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from room import Member, Server, commits, percentiles, plan_at  # noqa: E402

TASK = "task-000000"
PATH = "tasks/task-000000--task-1.md"
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
TYPISTS = int(sys.argv[2]) if len(sys.argv) > 2 else 15
RATE = 5.0  # characters a second, per person


def main(where: Path) -> dict:
    repo, _ = plan_at(where / "plan.git")
    report: dict = {"typists": TYPISTS, "seconds": SECONDS, "rate": RATE}
    with Server(repo) as server:
        before_cpu = server.cpu_seconds()
        members: list[Member] = []
        # The measurer applies every update, so it can timestamp a marker's
        # arrival. The pinger writes them. Everybody else drains and drops.
        measurer = Member(server.port, "measurer", TASK, 900001, applies=True)
        pinger = Member(server.port, "pinger", TASK, 900002, applies=True)
        members += [measurer, pinger]
        for n in range(TYPISTS - 2):
            members.append(Member(server.port, f"typist{n:02d}", TASK, 910000 + n))
        joined = time.monotonic()
        report["join_seconds"] = round(joined - joined, 3)

        sent: dict[str, float] = {}
        started = time.monotonic()
        gap = 1.0 / RATE
        seq = 0
        next_ping = started + 1.0
        while time.monotonic() - started < SECONDS:
            round_began = time.monotonic()
            for member in members:
                if member.gone:
                    continue
                if member is pinger and time.monotonic() >= next_ping:
                    seq += 1
                    token = f"{seq:04d}"
                    sent[token] = time.monotonic()
                    member.type(0, f"§{token}§")
                    next_ping += 1.0
                    continue
                member.type(0, random.choice("abcdefghij"))
            slept = gap - (time.monotonic() - round_began)
            if slept > 0:
                time.sleep(slept)
        report["typed_wall"] = round(time.monotonic() - started, 2)
        report["cpu_seconds"] = round(server.cpu_seconds() - before_cpu, 2)
        report["cpu_per_wall"] = round(report["cpu_seconds"] / report["typed_wall"], 3)
        report["rss_mb"] = round(server.rss_mb(), 1)

        # Give the wire a moment to settle before reading the marks, so the
        # last few in flight are not counted as lost.
        time.sleep(2.0)
        latencies = [
            measurer.marks[token] - when for token, when in sent.items() if token in measurer.marks
        ]
        report["propagation_ms"] = percentiles(latencies)
        report["markers_sent"] = len(sent)
        report["markers_seen"] = len(latencies)
        report["frames_each"] = sorted(m.frames for m in members)[-3:]
        report["evicted"] = [m.login for m in members if m.gone]
        report["commits_while_typing"] = len(commits(repo)) - 1
        report["room_chars"] = len(measurer.body())

        # Now stop typing and watch the quiet window fire.
        quiet_began = time.monotonic()
        while time.monotonic() - quiet_began < 30 and len(commits(repo)) == 1:
            time.sleep(0.5)
        report["commit_after_quiet_seconds"] = round(time.monotonic() - quiet_began, 1)
        report["commits_after_quiet"] = len(commits(repo)) - 1
        for member in members:
            member.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
