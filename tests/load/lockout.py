"""Does a refused room commit ever recover, and what exactly triggers it?

This settles the single most consequential claim in the audit — `adversarial`'s
finding A: *"a colleague's `git push` onto a line a room is typing on locks that
room out of the plan, permanently."* That claim was made from one 60-second run
with a terminal push in it, plus a reading of `store._merge_body`. It is the only
place in six scenarios where writing that people typed and watched appear in
three browsers never reached git — so whether it is really permanent, and how
narrow the trigger really is, decides whether there is a bug to fix at all.

Four cells, deliberately: the room typing at the END of the body against an
outside write at the END, and each of those two crossed with the other's control
(room in the MIDDLE, outside write in the MIDDLE). One cell reproducing and three
not is the difference between a defect and an ambient hazard.

**The outside write is an HTTP `PATCH`, not a `git push`.** That is on purpose
and it is the harder version of the claim. A terminal push has to be fetched
before the instance sees it, so a sceptic can say the lockout is really about
`_absorb_remote` and the retry path; a `PATCH` lands in the same repository
through the same serialised writer with no remote anywhere. If the lockout
reproduces through this door as well then the trigger is not "somebody with a
terminal" — it is *any* write to that file that lands while a room holds text,
which includes the record page's own Save button pressed in a second tab and
every inline edit on `/table`.

Nothing here is a soak. Each cell is one server, three sockets and about 25
seconds, and every server is killed by process group in a `finally`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
import room as roommod  # noqa: E402

from openproj.auth import User, sign_session  # noqa: E402
from openproj.web import SESSION_COOKIE  # noqa: E402

SAVE_ROUNDS = 5
SAVE_GAP = 3.0


def cookie(login: str) -> str:
    token = sign_session(User(login=login, member=True), roommod.SECRET)
    return f"{SESSION_COOKIE}={token}"


def blob_at_head(repo: Path, path: str) -> str:
    out = subprocess.run(
        ["git", "--git-dir", str(repo), "show", f"HEAD:{path}"],
        capture_output=True,
        text=True,
    )
    return out.stdout


def commits_touching(repo: Path, path: str) -> list[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(repo), "log", "--format=%h %s", "--", path],
        capture_output=True,
        text=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def split_body(text: str) -> str:
    if not text.startswith("---"):
        return text
    _, _, rest = text.partition("---\n")
    _, sep, body = rest.partition("\n---\n")
    return body if sep else text


def anchor_for(body: str, where: str) -> int:
    """Byte offset into the room's document for `end` or `middle`.

    `middle` is the start of a line about halfway down, so the two placements
    differ in which line of the FILE they touch and in nothing else.
    """
    if where == "end":
        return len(body.encode("utf-8"))
    lines = body.splitlines(True)
    half = "".join(lines[: max(1, len(lines) // 2)])
    return len(half.encode("utf-8"))


def outside_write(base_url: str, record: str, repo: Path, path: str, where: str) -> dict:
    """One save by somebody who is not in the room, through the ordinary API."""
    stored = blob_at_head(repo, path)
    body = split_body(stored)
    line = f"- [ ] added by somebody outside the room ({where})\n"
    if where == "end":
        fresh = body if body.endswith("\n") else body + "\n"
        fresh = fresh + line
    else:
        lines = body.splitlines(True)
        cut = max(1, len(lines) // 2)
        fresh = "".join(lines[:cut]) + line + "".join(lines[cut:])
    # The FULL sha off the repository, not the ten characters `/api/health`
    # reports: `_base_in` compares against `store.has` and a short sha is a 422
    # that this probe would otherwise have read as "the outsider wrote". It did,
    # on the first run — four cells of nothing happening, reported as four cells
    # of the claim not reproducing.
    head = subprocess.run(
        ["git", "--git-dir", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    answer = httpx.patch(
        f"{base_url}/api/entity/{record}",
        json={"base_commit": head, "body": fresh},
        headers={"Cookie": cookie("outsider")},
        timeout=60,
    )
    payload = answer.json()
    if answer.status_code != 200:
        raise RuntimeError(f"the outsider's save was refused {answer.status_code}: {payload}")
    return {"status": answer.status_code, "body": payload, "line": line.strip()}


def cell(room_where: str, write_where: str, keep: bool) -> dict:
    work = Path(tempfile.mkdtemp(prefix="openproj-lockout-"))
    result: dict = {"room_types": room_where, "outside_writes": write_where}
    members: list[roommod.Member] = []
    try:
        repo, _ = roommod.plan_at(work / "plan.git", pitches=6, tasks_each=2)
        port = roommod.free_port()
        with roommod.Server(repo, port=port):
            base_url = f"http://127.0.0.1:{port}"
            for _ in range(200):
                try:
                    httpx.get(f"{base_url}/api/health", timeout=5)
                    break
                except Exception:  # noqa: BLE001 - still binding
                    time.sleep(0.1)
            record = "task-000000"
            path = None
            # The path off the tree rather than guessed: the corpus names files
            # `tasks/<id>--<slug>.md` and a guessed slug is a probe that measures
            # a 404.
            listing = subprocess.run(
                ["git", "--git-dir", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.split()
            for name in listing:
                if name.startswith(f"tasks/{record}"):
                    path = name
                    break
            if path is None:
                raise RuntimeError("no record file for task-000000")
            result["path"] = path

            for index, login in enumerate(("ann", "bob", "cat")):
                members.append(
                    roommod.Member(port, login, record, client_id=100 + index, applies=True)
                )
            time.sleep(0.5)
            body = members[0].body()
            at = anchor_for(body, room_where)
            result["body_lines_at_start"] = len(body.splitlines())

            # 1. Everybody types, then one Save, so the room has a base of its
            #    own and the rest of the cell is about a room that HAS committed.
            for index, member in enumerate(members):
                member.type(at, f"[first-{index}] a sentence typed before anything went wrong. ")
            time.sleep(0.4)
            members[0].save()
            time.sleep(2.0)
            result["first_save"] = [
                {k: v for k, v in frame.items() if k != "update"}
                for frame in members[0].told
                if frame.get("t") in ("saved", "refused", "nothing")
            ]
            settled = blob_at_head(repo, path)
            result["first_save_reached_git"] = "[first-0]" in settled

            # 2. Somebody outside the room saves the same file.
            result["outside"] = outside_write(base_url, record, repo, path, write_where)
            time.sleep(1.0)

            # 3. Type more and press Save, over and over. If the claim is right
            #    nothing here ever lands; if it is wrong, one of these does.
            rounds = []
            for attempt in range(SAVE_ROUNDS):
                before = len(members[0].told)
                fresh = members[0].body()
                at_now = anchor_for(fresh, room_where)
                for index, member in enumerate(members):
                    # A newline in the middle of it on purpose: the tail run's
                    # typists never pressed Enter, so "the room is editing the
                    # last line" was true by construction there. A person who
                    # starts a new line and types on THAT is the case that would
                    # let a room out, if anything did.
                    member.type(at_now, f"\n[round{attempt}-{index}] more writing. ")
                time.sleep(0.4)
                members[0].save()
                time.sleep(SAVE_GAP)
                said = [
                    {k: v for k, v in frame.items() if k not in ("update", "why")}
                    | ({"why": (frame.get("why") or "")[:120]} if frame.get("why") else {})
                    for frame in members[0].told[before:]
                    if frame.get("t") in ("saved", "refused", "nothing")
                ]
                rounds.append({"attempt": attempt, "said": said})
            result["rounds"] = rounds

            # 4. Where is the room's base now? A fresh socket is told it.
            watcher = roommod.Member(port, "dee", record, client_id=900, applies=True)
            members.append(watcher)
            result["room_base_after"] = watcher.welcome["base"]
            result["room_seed"] = watcher.welcome["seed"]

            # 5. Everybody leaves. The last-person-out commit is the design's
            #    final backstop, and whether it lands is what decides whether the
            #    text is merely late or actually gone.
            for member in members:
                member.close()
            time.sleep(4.0)

            final = blob_at_head(repo, path)
            typed_markers = [
                f"[round{attempt}-{index}]"
                for attempt in range(SAVE_ROUNDS)
                for index in range(3)
            ]
            result["markers_typed"] = len(typed_markers)
            result["markers_in_git"] = sum(1 for m in typed_markers if m in final)
            result["outside_line_in_git"] = result["outside"]["line"] in final
            result["commits_touching_record"] = commits_touching(repo, path)
            result["final_body_lines"] = len(split_body(final).splitlines())
    finally:
        for member in members:
            try:
                member.close()
            except Exception:  # noqa: BLE001 - already closed
                pass
        if keep:
            result["kept"] = str(work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "docs/probes/load/lockout.json"))
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    cells = []
    for room_where in ("end", "middle"):
        for write_where in ("end", "middle"):
            print(f"-- room types at {room_where}, outsider writes at {write_where}", flush=True)
            found = cell(room_where, write_where, args.keep)
            print(
                f"   markers in git: {found['markers_in_git']}/{found['markers_typed']}"
                f"   commits: {len(found['commits_touching_record'])}",
                flush=True,
            )
            cells.append(found)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"probe": "lockout", "cells": cells}, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
