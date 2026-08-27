#!/usr/bin/env python3
"""Does HackMD's API let openproj edit a note without eating what somebody is typing?

Everything in the HackMD-as-backend design rests on one unknown: `PATCH` replaces
a note's whole `content`, there is no etag and no if-match, and the OpenAPI spec
ships empty response schemas — so what actually happens when that PATCH lands
mid-sentence is not a thing anybody can read off the documentation. This answers
it with evidence.

It never touches a note it did not create. Every phase names the note id it is
working on, and `clean` deletes it.

    export HACKMD_TOKEN=...            # hackmd.io → settings → API → new token
    python hackmd_probe.py inspect  <team>
    python hackmd_probe.py create   <team>
    python hackmd_probe.py clobber  <team> <noteId>
    python hackmd_probe.py verify   <team> <noteId>
    python hackmd_probe.py clean    <team> <noteId>

`create` prints a URL. Open it, and have somebody type in the body — then run
`clobber` WHILE they are typing. That is the whole experiment.
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

API = "https://api.hackmd.io/v1"
FIELD_BEFORE, FIELD_AFTER = "ready", "in_progress"

SCRATCH = f"""---
title: openproj probe — safe to delete
tags: [openproj, probe]
kind: pitch
status: {FIELD_BEFORE}
owner: probe
person_weeks: 1.0
---

# Type in this paragraph

Somebody should be typing here, in this line, while `clobber` runs. Add words to
the end of this sentence and do not stop: HERE >>>
"""


def client() -> httpx.Client:
    token = os.environ.get("HACKMD_TOKEN", "").strip()
    if not token:
        sys.exit("HACKMD_TOKEN is not set. hackmd.io → settings → API → new token.")
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30.0,
    )


def show(label: str, response: httpx.Response) -> dict | list | None:
    """Every call prints its status and the rate-limit headers, because neither is
    in the spec and both decide whether a polling reader is viable at all."""
    limits = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower()}
    print(f"  {label:34} {response.status_code}  {limits or ''}")
    try:
        return response.json()
    except ValueError:
        if response.text.strip():
            print(f"    body: {response.text[:200]}")
        return None


def inspect(team: str) -> None:
    """What the API really returns, since the spec's response schemas are empty."""
    with client() as api:
        me = show("GET /me", api.get("/me"))
        if isinstance(me, dict):
            print(f"    signed in as: {me.get('name')} ({me.get('email')})")
        teams = show("GET /teams", api.get("/teams"))
        if isinstance(teams, list):
            for one in teams:
                print(f"    team: path={one.get('path')!r} name={one.get('name')!r}")
        notes = show(f"GET /teams/{team}/notes", api.get(f"/teams/{team}/notes"))
        if isinstance(notes, list) and notes:
            print(f"    {len(notes)} notes. One note's keys — the shape we must code against:")
            for key in sorted(notes[0]):
                print(f"      {key}: {json.dumps(notes[0][key])[:70]}")
            print("\n    Does a note carry a change timestamp we can use as a version?")
            for key in ("lastChangedAt", "updatedAt", "createdAt", "publishedAt"):
                print(f"      {key:14} {'yes' if key in notes[0] else 'NO'}")


def create(team: str) -> None:
    with client() as api:
        made = show(
            f"POST /teams/{team}/notes",
            api.post(
                f"/teams/{team}/notes",
                json={
                    "title": "openproj probe — safe to delete",
                    "content": SCRATCH,
                    "readPermission": "signed_in",
                    "writePermission": "signed_in",
                },
            ),
        )
        if not isinstance(made, dict):
            sys.exit("could not create the scratch note; nothing else will work")
        note_id = made.get("id")
        print(f"\n  noteId: {note_id}")
        print(f"  open:   https://hackmd.io/{made.get('shortId') or note_id}")
        print(f"  tags as created: {made.get('tags')}")
        print("    ^ did the frontmatter `tags:` line become the note's own tags?")
        print("\n  Now open that URL, put the cursor at the end of the HERE >>> line,")
        print("  and start typing. While you are typing, run:\n")
        print(f"      python {sys.argv[0]} clobber {team} {note_id}\n")


def clobber(team: str, note_id: str) -> None:
    """The experiment. Read, change one frontmatter field, write it back — exactly
    what openproj would do when somebody ticks a row on the betting table."""
    with client() as api:
        path = f"/teams/{team}/notes/{note_id}"

        first = show("GET (read for the edit)", api.get(path))
        if not isinstance(first, dict):
            sys.exit("could not read the note")
        base = first.get("content") or ""
        stamp = first.get("lastChangedAt")
        print(f"    lastChangedAt: {stamp}")
        print(f"    body tail now: ...{base.strip()[-60:]!r}")

        edited = base.replace(f"status: {FIELD_BEFORE}", f"status: {FIELD_AFTER}", 1)
        if edited == base:
            print("    ! the status line was not found — was this note already clobbered?")

        again = show("GET (the CAS check)", api.get(path))
        moved = isinstance(again, dict) and again.get("lastChangedAt") != stamp
        print(
            f"    lastChangedAt moved between the two reads: {moved}"
            f"  <- if False while somebody types, it is useless as a version"
        )

        print("\n  PATCHing the whole content back, mid-sentence:")
        show("PATCH content", api.patch(path, json={"content": edited}))

        for wait in (1, 3, 8):
            time.sleep(wait)
            after = api.get(path).json()
            body = after.get("content") or ""
            landed = f"status: {FIELD_AFTER}" in body
            kept = base.strip()[-40:] in body
            print(
                f"    +{wait:>2}s  our field landed: {str(landed):5}   "
                f"their text still there: {kept}"
            )
        print(f"\n  body tail after: ...{(body or '').strip()[-60:]!r}")
        print("\n  Ask the person typing: did their editor jump, lose characters, or")
        print("  carry on as if nothing happened? That answer is the design decision.")


def verify(team: str, note_id: str) -> None:
    with client() as api:
        note = show("GET", api.get(f"/teams/{team}/notes/{note_id}"))
        if isinstance(note, dict):
            print(f"    tags:          {note.get('tags')}")
            print(f"    lastChangedAt: {note.get('lastChangedAt')}")
            print("\n--- content ---")
            print(note.get("content"))


def clean(team: str, note_id: str) -> None:
    with client() as api:
        show("DELETE", api.delete(f"/teams/{team}/notes/{note_id}"))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    phase, team, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    phases = {
        "inspect": inspect,
        "create": create,
        "clobber": clobber,
        "verify": verify,
        "clean": clean,
    }
    if phase not in phases:
        sys.exit(__doc__)
    phases[phase](team, *rest)
