"""Seats, presence, and what an abrupt disconnect leaves behind.

Cloud Run's `--timeout 300` closes every socket at five minutes, so a room with
fifteen people in it churns fifteen connections every five minutes for as long as
anybody is editing. Departure is therefore the common path, not the rare one, and
half of those departures are not polite: a closed lid, a tunnel, a laptop asleep
and a tab killed all end in an RST or in nothing at all.

`Room.leave` (`coedit.py:279`) pops the member and the seat together, and the
socket's `finally` (`web.py:2963`) is what calls it. This asks whether that
`finally` really runs for a socket that was reset rather than closed, by resetting
sockets and reading the roster off a survivor — `where` is one entry per LOGIN
(`coedit.py:304`), so a leaked connection shows up as a name that will not go
away or a band that will not move.

It also drives the reconnection cycle the five-minute teardown makes ordinary:
type, drop, reconnect with the same seed, and ask whether the room and the
returning document still agree.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from room import Member, Server, plan_at  # noqa: E402

from openproj import coedit  # noqa: E402

TASK = "task-000000"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
CHURN = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def roster(watcher: Member) -> tuple[list[str], list[dict]]:
    whos = [f for f in watcher.told if f["t"] == "who"]
    if not whos:
        return [], []
    return whos[-1]["people"], whos[-1].get("where", [])


def main(where: Path) -> dict:
    repo, _ = plan_at(where / "plan.git", pitches=4, tasks_each=2)
    report: dict = {"rounds": ROUNDS, "churn": CHURN}
    with Server(repo) as server:
        watcher = Member(server.port, "watcher", TASK, 500001, applies=True)
        watcher.sit(3)

        # --- abrupt departures ------------------------------------------------
        peak_people = 0
        peak_seats = 0
        for round_ in range(ROUNDS):
            crowd = [
                Member(server.port, f"gone{n:02d}", TASK, 510000 + round_ * 100 + n)
                for n in range(CHURN)
            ]
            for n, one in enumerate(crowd):
                one.sit(n * 7)
            time.sleep(0.6)
            people, seats = roster(watcher)
            peak_people = max(peak_people, len(people))
            peak_seats = max(peak_seats, len(seats))
            # Half reset, half close politely, so the two are compared in one run.
            for n, one in enumerate(crowd):
                one.close(rude=(n % 2 == 0))
            time.sleep(1.2)
        time.sleep(2.0)
        people, seats = roster(watcher)
        report["peak_people_in_roster"] = peak_people
        report["peak_seats_in_roster"] = peak_seats
        report["people_after_churn"] = people
        report["seats_after_churn"] = seats
        report["leaked"] = [name for name in people if name != "watcher"]
        report["rss_mb_after_churn"] = round(server.rss_mb(), 1)

        # --- the five-minute teardown, played at speed -------------------------
        # A tab types, its socket is reset (which is what a teardown looks like
        # from the tab's side), and it comes back with the seed it had and the
        # state vector of the document it kept.
        ann = Member(server.port, "ann", TASK, 520001, applies=True)
        ann.type(0, "BEFORE-THE-DROP\n")
        time.sleep(0.4)
        kept = ann.doc
        seed = ann.welcome["seed"]
        ann.close(rude=True)
        # Typed while there is no socket at all: the browser's document takes it
        # and `doc.on('update')` cannot send it (`render.py:14370`), so it rides
        # the reconnection or it does not exist.
        kept[coedit.BODY].insert(0, "DURING-THE-DROP\n")
        time.sleep(0.5)

        back = Member(server.port, "ann", TASK, 520002, applies=True)
        report["reconnect_seed_matches"] = back.welcome["seed"] == seed
        report["reconnect_was_reloaded"] = any(f["t"] == "reload" for f in back.told)
        report["room_kept_before_the_drop"] = "BEFORE-THE-DROP" in back.body()
        report["room_kept_during_the_drop_before_resend"] = "DURING-THE-DROP" in back.body()
        # What the page does on `welcome`: send everything the room has not seen.
        offer = kept.get_update(base64.b64decode(back.welcome["sv"]))
        back.client.send_json({"t": "update", "u": base64.b64encode(offer).decode()})
        time.sleep(0.8)
        watcher.told.clear()
        watcher.type(0, "")
        time.sleep(0.5)
        report["room_took_the_offline_text"] = "DURING-THE-DROP" in watcher.body()
        report["watcher_sees_before"] = "BEFORE-THE-DROP" in watcher.body()

        # And the roster after a reconnection: one person, one seat, not two.
        back.sit(11)
        time.sleep(0.6)
        people, seats = roster(watcher)
        report["people_after_reconnect"] = people
        report["seats_after_reconnect"] = seats

        watcher.close()
        back.close()
    return report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(main(Path(tmp)), indent=2))
