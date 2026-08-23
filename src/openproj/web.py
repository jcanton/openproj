"""The server: the Phase 1 pages, plus the ability to change them.

Five decisions shape almost everything here.

**Reads are public, writes are not.** The content is public by decision, so every
GET answers an anonymous browser. The gate lives on the two write endpoints and is
checked *per request* from the signed session. A server that asks about membership
only at `/auth/callback` and then issues a cookie to whoever authenticated has
handed write access to every GitHub user on earth.

**The author is the session and only the session.** The author/committer split in
`store.py` is the team's only audit trail, and it is worth exactly as much as the
guarantee that nobody can name themselves in a request body.

**The writable surface is closed by construction.** An id is admitted against a
regex before anything is concatenated, and the directory comes from its prefix.
`<directory>/<id>.md` for every rung of the ladder — issues and notes included,
through the one pattern `KINDS` derives — is the shape of it, and every path
added since is admitted the same way and by nothing else: `cycles/<n>.md` by a
number, `assets/<sha>` by the hash of the bytes, and `people/<login>.md` by
`model.LOGIN_PATTERN` (see `PUT /api/icon`). No route takes a path, a directory
or a file name from a request — `POST /api/promote` writes two files and takes
neither of their names, because a record id and a kind decide both. This matters
more than usual because branch protection means a bad write cannot be
force-pushed away afterwards.

**A save preserves the file.** Only touched fields travel, and `patch_text` applies
them through a round-trip loader so comments, key order and list style survive.

**A refusal writes nothing.** A conflict is a 409 carrying a rendered report with
no conflict markers in it, because a marker that reaches the client reaches a
textarea and is then saved back.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import math
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import quote

import httpx
import pygit2
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from . import __version__, coedit, render
from .auth import (
    OAuthError,
    User,
    exchange_code,
    identify,
    login_url,
    read_session,
    sign_session,
)
from .index import Index, build_index, cascade_of
from .model import (
    CONFIG_FILES,
    ID_PATTERN,
    KINDS,
    MAX_BODY_BYTES,
    PEOPLE_DIR,
    RUNG,
    Config,
    Cycle,
    Person,
    Record,
    Unreadable,
    _an,
    edited_by_id,
    loop_made,
    parse_cycle_text,
    parse_person_text,
    parse_text,
    patch_text,
    person_path,
    promoted_from,
    read_config,
    readable,
    record_paths_in,
    shaping_document,
    split_front_matter,
    validate_all,
    what_json_can_carry,
    why_it_will_not_read,
)
from .store import Store, StoreDiverged, StoreLocked

# What a write can fail with, as one name so the two callers of `store.write`
# cannot disagree about it. `StoreLocked` and `StoreDiverged` are `RuntimeError`s
# and `_commit` goes through pygit2, which raises `GitError`; a net woven from
# `(HTTPException, ValueError)` alone therefore let three of the five past it. A
# tuple and not `Exception`, because `readable` (`model.py`) is the one place in
# this codebase that catches everything, and everywhere else the list of what has
# actually been seen is the honest one.
WRITE_FAILURES = (HTTPException, ValueError, StoreLocked, StoreDiverged, pygit2.GitError)

# Two names for one session, chosen by the scheme the request actually arrived
# on, because the `__Host-` prefix is not a hint — it is a rule the browser
# enforces before it stores anything. A `Set-Cookie` carrying that prefix without
# `Secure`, or with a `Domain`, or with a `Path` other than `/`, is not corrected
# and not warned about: it is dropped, and the response looks like it worked.
#
# Over plain HTTP `Secure` cannot be sent honestly, so the prefixed name is
# unstorable and every local sign-in ended where it started — GitHub redirected
# back, the callback set a cookie the browser threw away, and `/` drew signed
# out with nothing anywhere saying why. Found by trying it: a probe serving that
# exact header over http://127.0.0.1 stored nothing, and the same header with
# `Secure` added stored fine.
#
# So the deployment keeps the prefix and its guarantee — that cookie cannot have
# been set by a sibling host or over a downgraded connection — and a local run
# uses the bare name, which is the honest description of a cookie on a loopback
# port with no TLS. Both are read, so a session survives the day somebody puts a
# proxy in front of a local server.
SESSION_COOKIE = "__Host-openproj_session"
SESSION_COOKIE_INSECURE = "openproj_session"
STATE_COOKIE = "op_state"

# `ID_PATTERN` is imported from `model.py`, where its comment carries the whole
# argument: one KINDS-derived pattern for every rung, `\A`/`\Z` anchored so a
# trailing newline cannot ride an id into a path, judged identically by the
# validator and by this file's write doors. A second derivation here — which is
# what stood on this line — was two spellings of one rule, and they had already
# disagreed once about the anchors: `validate_all` blessed a trailing-newline id
# every API write refused.
#
# Off the ladder in `model.py`, so a rung added there is a directory here without
# anybody remembering to come and add one.
DIRECTORY = {rung.name: rung.directory for rung in KINDS}
# What a new id starts with, per kind — off the ladder, like `DIRECTORY` beside
# it. The SEVENTH copy, written out three lines under a map that was already
# derived: `POST /api/record` with `kind: product` got past the models and fell
# over here instead.
PREFIX = {rung.name: rung.prefix for rung in KINDS}
# And back again: the rung an id names, read off its prefix. The inverse of
# `PREFIX`, derived beside it, for the two questions a bare id has to answer —
# which directory its file lives in, and which status vocabulary judges a write
# to it.
KIND_OF_PREFIX = {rung.prefix: rung.name for rung in KINDS}


class Inbox(NamedTuple):
    """What the server owns when an inbox record is created, and the link a
    promotion writes on it. One row per unplanned rung, because these were the
    defaults of `POST /api/issue` and `POST /api/note` — the routes this table
    replaced — and losing them would make the shortest write paths in the tool
    ask for four fields instead of a title."""

    author: str  # defaults to the signed-in login; the form may say otherwise
    dated: str   # always the server's: when a record was made is not an opinion
    opens: str   # the status a fresh record starts in
    link: str    # what /api/promote appends the new record's id to


INBOXES = {
    "issue": Inbox("reported_by", "opened_on", "ready", "pitched_into"),
    "note": Inbox("written_by", "written_on", "thinking", "became"),
}

# `MAX_BODY_BYTES` is imported rather than declared: it moved to `model.py` when
# the editor's status bar gained a second reader for it, and it is re-exported
# here by that import so every `web.MAX_BODY_BYTES` in this file and in the tests
# still names the one object.
# The largest update one socket frame may carry, which is a different kind of
# bound and has to be derived from that one rather than written out beside it.
# `MAX_BODY_BYTES` is policy — what this tool will put in git for ever. This is
# transport — what the process will hold while it decides what a frame is. They
# were two spellings of 262144, and a Yjs update is always larger than the text
# it carries (an item header per run, and every character anybody has deleted
# still travelling as a tombstone until the room is rebuilt), so the transport
# bound bit first and a body a PATCH would have accepted could never be pasted
# into a live room. Four times, so a document sitting at the policy ceiling can
# still be sent whole — which is what a reconnection sends, and what a paste
# into an empty room sends — with its edit history on top of it. Past this the
# frame is refused out loud: a document that large could not be committed
# either way, and a frame dropped in silence is how a paste disappeared.
MAX_UPDATE_BYTES = 4 * MAX_BODY_BYTES
# How far behind one member of a room may fall before the room starts counting.
# Derived from the frame ceiling and not written out beside it, for the reason
# the paragraph above gives: this is "one whole document, queued and not yet on
# the wire", which is the largest single frame anybody can legitimately be owed.
#
# Approximately. `MAX_UPDATE_BYTES` bounds the *decoded* update — that is what
# `_raw` hands back and what the frame handler measures — while an outbox holds
# the frame the room broadcasts, which is that update base64'd into JSON at four
# characters per three bytes. So the largest single frame anybody can legitimately
# be owed is about 1.37 MiB against a ceiling of 1 MiB, and a member owed exactly
# one whole document is already over it. That is why this is a clock and not a
# verdict, and it is 1.333 and not a factor anybody chose.
MAX_OUTBOX_BYTES = MAX_UPDATE_BYTES
# And how long they may stay past it before the room gives up on them.
#
# Two conditions and not one, because *behind* and *not draining* are different
# things and only the second is a reason to end somebody's membership. Measured
# with three real tabs: with a byte ceiling alone, a tab applying a burst of
# whole-document updates went a megabyte behind for a moment — doing exactly its
# job, and it caught up completely — and was thrown out of the room beside the
# tab that was actually suspended. Evicting the person who was working is a worse
# failure than the one this was written to fix.
#
# So the ceiling starts a clock and staying over it stops the membership. A tab
# that gets back under, however briefly, has proved it is draining and the clock
# goes back to zero.
#
# The pair of them is a drain-rate floor, and the number is worth writing down
# because nobody chose it directly: a member has to take `MAX_OUTBOX_BYTES` off
# the wire every `STALL_SECONDS` to keep their membership, which is 105 kB/s.
# Measured with a real `Outbox` over a wire that accepts a fixed number of bytes a
# second, a burst of ordinary update frames putting it two ceilings behind, and
# somebody typing beside it throughout: 87 kB/s is evicted at 10.1 s, 105 kB/s
# recovers, 217 kB/s is completely caught up. That is a calibration and not a law,
# and it degrades honestly — a reader who cannot take 105 kB/s was not going to be
# able to edit collaboratively over that connection anyway — but it is a decision
# somebody made by writing two other numbers down, so here it is.
STALL_SECONDS = 10.0
# And the most this process will hold for one member under any circumstances,
# past which they are given up on at once rather than at the end of the clock.
#
# The clock alone was not a bound. Past the ceiling `offer` set `_behind` and
# then returned True for *every* frame until `STALL_SECONDS` had elapsed, so what
# was held for one wedged member was "whatever the room can broadcast in ten
# seconds" — which is a property of the room and of the machine, not a constant.
# Measured against a real server with one wedged member and one member pasting
# ordinary documents: **1.3 GB queued for one member in 3917 frames**, 1245x the
# ceiling, and the process went from 82 MB RSS to 1519 MB. `gcloud_deploy.sh`
# runs `--memory 512Mi --max-instances 1`, so the outcome was not "the room stops
# committing" but "the process is OOM-killed and every room's uncommitted text
# dies with it" — worse, from the same trigger.
#
# Six times the ceiling, so both facts stay true at once: the tolerance the clock
# was written for survives (the tab applying a burst of whole-document updates
# peaked at 1.7x and caught up) and the process is bounded at a few MB per member
# rather than by how fast anybody can type. It is a multiple of the ceiling and
# not a number of its own because it is the same quantity measured for a
# different purpose, and two constants that are the same number are the same
# defect.
MAX_HELD_BYTES = 6 * MAX_OUTBOX_BYTES
# How long a socket may hold its own handler open flushing what it still owes,
# after the room has already been left and the last commit already made. Short,
# because the only thing waiting on it is the person leaving.
FLUSH_SECONDS = 5.0
# How often a live socket re-reads the session it was opened with. Membership is
# already baked into a cookie for 24 hours over HTTP; what a socket adds is that
# it outlives even that, so a sign-out or a revoked membership went on committing
# under that login for as long as the tab stayed open. A minute, because the
# check is a signature verification against a cookie this process already has —
# there is no request to GitHub in it — and because a minute is short beside a
# tab somebody leaves open all afternoon.
RECHECK_SECONDS = 60.0
# A screenshot of a plot is well under this; a photograph pasted by accident is
# not. Every byte here is a byte in the plan repository forever — git keeps it
# after the markdown that referenced it is deleted.
MAX_ASSET_BYTES = 2 * 1024 * 1024
# No SVG: it is a document that can carry script, and these are served from the
# same origin as the editor.
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
ASSET_PATTERN = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")

_DEV_SECRETS = {"", "dev-secret", "change-me", "secret"}


CYCLE_DIR = "cycles"
# A cycle file is named by its number alone, zero-padded so that the order the
# store lists paths in is also the order a person means. Kept separate from
# ID_PATTERN rather than folded into it: the record id pattern is what keeps the
# writable surface closed by construction, and widening it to admit a fourth
# shape is how that property gets lost by degrees.
CYCLE_PATTERN = re.compile(r"^[0-9]{1,4}$")
# The longest a cycle may be, betting table to review meeting. It was a length in
# weeks with no bound at all, so `build_weeks: 500000` — three keystrokes and a
# confirmation — committed a cycle whose end date is past the end of the
# calendar, and every page that reads a cycle answered 500 to everybody,
# permanently, on a branch whose protection means the commit cannot be
# force-pushed away. The dates that replaced it can say the same thing with
# `reviews_on: 9999-12-31`, so the bound moved with them. Ten years is not a
# cycle by any reading; `Config.working_weeks` counts a week at a time anyway,
# for the file somebody writes by hand.
MAX_CYCLE_WEEKS = 520.0
# The goal is one or two sentences the room agreed on, drawn above the betting
# table. Long enough for a real one, short enough that nobody pastes a shaping
# document into a field whose whole value is being short — the notes below the
# table are where prose goes, and they are unbounded.
MAX_GOAL_CHARS = 400


def _cycle_message(fields: dict) -> str:
    """A cycle's own number is in the message already, so it is not one of the
    fields the message names."""
    rest = {name: value for name, value in fields.items() if name != "cycle"}
    return _named(rest, CYCLE_FIELDS) or "goal"


def _cycles_at(store: Store, commit: str) -> tuple[list[Cycle], list[Unreadable]]:
    return _read_records(store, commit, [CYCLE_DIR], parse_cycle_text)


def _cycle_path(number: int) -> str:
    return f"{CYCLE_DIR}/{number:04d}.md"


def _people_at(store: Store, commit: str) -> tuple[list[Person], list[Unreadable]]:
    """The person records at this commit, through the same door as everything else.

    One file per person, so a file somebody broke by hand costs that person's
    icon and nothing more. The arrangement this replaced kept every icon and the
    roster in one YAML file, where the same hand edit cost all of them and the
    roster check with them.

    `record_paths_in` and not a filter of its own. The filter here asked whether
    the FIRST segment of the path was `people`, which is true of
    `people/team/ann.md`, and `login_of` then read `ann` off the filename and
    handed back a second record for a login that already had one. Whichever of
    the two paths sorted last was the icon on the page, and it was the one the
    CLI could not see.
    """
    return _read_records(store, commit, [PEOPLE_DIR], parse_person_text)


def _person_or_why(text: str, path: str) -> tuple[Person | None, str]:
    """One person record, or one line saying why these bytes are not one.

    Through `readable` rather than a `try` of its own, and that is not ceremony:
    `readable` is the one place in this codebase that catches `Exception`, and it
    earns it because the ways a plan file fails are not one family — a ValueError
    from the split, a ruamel ParserError, a pydantic ValidationError, a
    UnicodeDecodeError. A tuple of the ones seen so far, written out here, would
    be a denylist, and the icon route is asked this question three times: about
    the file it is patching, about the candidate, and about what the commit
    actually landed.
    """
    people, refused = readable([path], lambda source: parse_person_text(text, source))
    return (people[0], "") if people else (None, refused[0].why)


def _config_at(store: Store, commit: str) -> tuple[Config, list[Unreadable]]:
    """The configuration at this commit, and every plan file that is not a record.

    `CONFIG_FILES` is the same list the CLI reads. Hardcoded here, it was missing
    people.yaml, so `known_people` was empty under `serve` and the roster check
    that rejects an unknown login was silently off in the browser and on in CI —
    and `read_config` is now shared with the CLI for the same reason, so a config
    file that will not scan costs the same thing in both.

    The reads all happen inside `read_config`'s guard: `store.read` decodes, and
    a config file somebody saved in latin-1 was a UnicodeDecodeError on every
    route before the YAML parser was ever reached.
    """
    present = set(store.paths(commit))
    config, refused = read_config(
        [path for name in CONFIG_FILES if (path := f"config/{name}") in present],
        lambda path: store.read(commit, path) or "",
    )
    # The cycle records last, so a record supersedes the dates in cycles.yaml the
    # same way it does under the CLI.
    plans, refused_plans = _cycles_at(store, commit)
    people, refused_people = _people_at(store, commit)
    return (
        config.with_plans(plans).with_people(people),
        [*refused, *refused_plans, *refused_people],
    )


# One parsed record per blob id, across every commit this process has read.
#
# A blob id is a hash of the file's contents, so a record parsed once is the same
# record at every commit that did not touch that file — and one edit touches one
# file. Measured on the plans in `tests/plans.py`: after a single save, 43 of 44
# blobs are unchanged at 31 records, 209 of 210 at 208, and 519 of 520 at 518. The
# read-and-parse those numbers make reusable was the largest cost in a request,
# 502 ms of a 941 ms PATCH at 518 records.
#
# Keyed on the blob AND the path, and the path is not decoration. `parse_text`
# stamps `record._source` with the file it came from, and `_source` is what
# `_identity_problems` reads to report the two blockers that matter most here:
# "another file claims this id too" and "its file is named for something else".
#
# Keyed on the blob alone — which is how this shipped, on the argument that a
# renamed file keeps its bytes and keeps its answer — two files with IDENTICAL
# bytes are one cached object carrying the first path's `_source`, and both
# blockers stop firing. Reproduced: two records, one object, no blockers, on a
# plan where the same record is committed under two names. The docstring of the
# check that stopped firing says a save otherwise "lands on the wrong file" and
# answers 200 with no warning, which is the failure a cache must never buy.
#
# What that costs is the reuse on a pure rename, where losing it is correct: the
# record's `_source` changed, so the answer genuinely is different.
#
# Pruned to the tree it just read, so the memory it holds is the size of the plan
# rather than the size of the plan's history. An instance that lives for a week
# would otherwise accumulate every version of every record anybody edited.
_PARSED: dict[tuple[str, str], object] = {}


def _read_records(store: Store, commit: str, where, parse):
    """Every record under `where` at this commit, parsed once per (blob, path).

    One function for every walk. It was written for the planned kinds alone, and
    the others — cycles, people, and the then-separate issue and note readers —
    went on doing a full tree walk plus a read and a parse of every file on
    EVERY request, warm or cold. That does not decay, and notes and issues are
    exactly what a betting table accumulates (measured on a plan with 300 of
    each, back when they had pages of their own: `/` 52 ms to 19 ms, `/notes`
    54 to 15, `/issues` 40 to 15 — they ride the record walk now).

    Every walk already funnelled through `readable`, so this is one shape
    rather than one per kind.
    """
    blobs = store.blobs(commit)
    paths, too_deep = record_paths_in(where, sorted(blobs))

    def parsed(path: str):
        key = (blobs[path], path)
        held = _PARSED.get(key)
        if held is not None:
            return held
        record = parse(store.read(commit, path), path)
        _PARSED[key] = record
        return record

    records, refused = readable(paths, parsed)
    # Pruned, but only once it has grown to several times the plan it just read.
    # Pruning to exactly that tree looks tidier and is worse: one process can
    # serve more than one plan — every test in this suite builds its own — and two
    # of them alternating would evict each other on every read, which turns a
    # cache into an overhead. A file that would not parse is not held at all: it
    # has no answer, and the next read has to produce the same refusal for the
    # banner to go on saying so.
    # Both numbers against the WHOLE tree, not the kind being read. Several
    # walks share this dict: a keep-set built from `paths` alone means reading
    # records evicts every person, and a threshold measured against `paths` means reading
    # cycles — of which a plan has two — prunes a six-hundred-entry cache on every
    # request. Measured with the threshold wrong, every page came out SLOWER than
    # with no cache at all: `/issues` 40 ms uncached, 91 ms with the bug, 15 ms
    # with it fixed.
    if len(_PARSED) > 3 * max(len(blobs), 1):
        keep = {(sha, path) for path, sha in blobs.items()}
        # `list(...)` before iterating and `pop(..., None)` rather than `del`:
        # this dict is a module global and 25 of this app's routes are sync `def`,
        # which Starlette dispatches through anyio's worker threads — so two
        # readers really do prune at once. Without both, that is
        # `RuntimeError: dictionary changed size during iteration` from the
        # comprehension and `KeyError` from the delete, as unhandled 500s on a
        # page route, and the window widens as the plan grows.
        for gone in [key for key in list(_PARSED) if key not in keep]:
            _PARSED.pop(gone, None)
    return records, [*refused, *too_deep]


def _records_at(store: Store, commit: str) -> tuple[list[Record], list[Unreadable]]:
    return _read_records(store, commit, DIRECTORY.values(), parse_text)


# A form returns strings, and `priority: soon` is valid YAML that parses fine and
# then breaks the scheduler on the next read.
def _reject_bad_cycle(fields: dict) -> None:
    """The one place that decides what a cycle field may hold.

    A form returns strings here too, and an availability of `"half"` is valid
    YAML that parses and then divides a date by a word. The boxes now send what
    was typed rather than a coerced number, because a refusal is only useful if
    it can quote the value — so this is where a word becomes a 422 instead of a
    date the record cannot hold.
    """
    # `in fields`, not `is not None`. Skipping a null let it through to the file,
    # and a null date is a ValidationError inside `parse_cycle_text` — an
    # unhandled 500 whose body is not even JSON, so the page could not say what
    # was wrong. Null still arrives from anything that coerces before it sends,
    # and this endpoint answers browsers it did not render.
    for name in ("starts_on", "reviews_on"):
        if name in fields:
            fields[name] = _as_iso_date(fields[name], name)
    # The review meeting is the day after the last day of build, so a cycle whose
    # review is on or before its betting table has no build in it at all — every
    # bet in it would overrun by definition, and its capacity would be zero.
    both = fields.get("starts_on"), fields.get("reviews_on")
    if all(both):
        opens, reviews = (date.fromisoformat(one) for one in both)
        if reviews <= opens:
            raise HTTPException(
                422, f"the review meeting is {reviews}, which is not after the betting "
                f"table on {opens} — a cycle needs at least one day of build"
            )
        if (reviews - opens).days > MAX_CYCLE_WEEKS * 7:
            raise HTTPException(
                422, f"{(reviews - opens).days // 7} weeks from the betting table to the "
                f"review meeting is not a cycle; the most this will hold is "
                f"{MAX_CYCLE_WEEKS:g} weeks"
            )
    # A sentence, and bounded — this reaches a `<h2>`-adjacent line on a page and
    # a line in a YAML file, and neither wants a pasted document. Coerced to a
    # string rather than refused for not being one, because a form sends what was
    # typed and a goal of `2026` is a person writing a year, not an error.
    if "goal" in fields:
        goal = "" if fields["goal"] is None else str(fields["goal"]).strip()
        if len(goal) > MAX_GOAL_CHARS:
            raise HTTPException(
                422, f"a cycle goal is {MAX_GOAL_CHARS} characters at most; that one is "
                f"{len(goal)}. The rest belongs in the notes under the betting table."
            )
        fields["goal"] = goal
    rates = fields.get("availability")
    if rates is not None:
        if not isinstance(rates, dict):
            raise HTTPException(422, "availability must be a map of login to fraction")
        fields["availability"] = {
            str(who): _as_positive(rate, f"availability of {who}") for who, rate in rates.items()
        }


def _as_iso_date(value: object, name: str) -> str:
    """A date the record can hold, spelled the way the corpus spells one.

    An empty date box posts `""`, which is not a refusal anywhere on the way in
    and is a ValidationError on the way back out — so clearing the date and
    pressing Save was a 500.
    """
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise HTTPException(422, f"{name} must be a date like 2026-09-01, not {value!r}")


def _as_positive(value: object, name: str, most: float = math.inf) -> float:
    # Said as "blank" rather than as `None`: null arrives here from a box
    # somebody emptied or typed a word into, and `None` is a word from this
    # language rather than from anything on their screen.
    if value is None:
        raise HTTPException(422, f"{name} must be a number, and this one is blank")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be a number, not {value!r}") from None
    # `float("inf")` is a number and passes every test below it, and a cycle
    # `.inf` weeks long is every date on every page gone. `nan` fails the
    # comparison, but says "not nan" rather than naming what was typed.
    if not math.isfinite(number):
        raise HTTPException(422, f"{name} must be an ordinary number, not {value!r}")
    if number <= 0:
        raise HTTPException(422, f"{name} must be greater than zero, not {number:g}")
    if number > most:
        raise HTTPException(422, f"{name} must be at most {most:g}, not {number:g}")
    return number


_NUMERIC = ("cycle", "person_weeks")
_LISTS = ("assignees", "reviewers", "tags", "prs", "depends_on", "shaped_by",
          "pitched_into", "became")


def _deletion_message(record_id: str, doomed: list[str], edited: list[str]) -> str:
    """One commit, one line, and the line says how far it reached.

    `git log --oneline` on a plan is the team's record of decisions, and "deleted"
    over a commit that removed five files and edited two is the wrong record of
    this one.
    """
    said = f"{record_id}: deleted"
    if doomed:
        said += f", with {len(doomed)} filed under it"
    if edited:
        said += f", freed {len(edited)}"
    return said


def _and_then(ids: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`. Sorted, because a list whose order comes out
    of a dictionary reads as though it means something by it."""
    names = sorted(ids)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _reject_bad_types(fields: dict) -> None:
    for name in _NUMERIC:
        value = fields.get(name)
        if value is not None and not isinstance(value, int | float) or isinstance(value, bool):
            if name in fields and fields[name] is not None:
                raise HTTPException(422, f"{name} must be a number, not {fields[name]!r}")
        # `Infinity` and `NaN` are valid JSON to Python's parser, so both arrive
        # here as ordinary floats and pass every check above. `person_weeks:
        # Infinity` committed, and then `math.ceil` raised inside the
        # scheduler's own end-of-calendar guard: every page 500, permanently.
        # The guard no longer raises; this stops the value at the door, the way
        # the cycle route already stops it.
        if isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, f"{name} must be an ordinary number, not {value!r}")
    for name in _LISTS:
        if name in fields and not isinstance(fields[name], list):
            raise HTTPException(422, f"{name} must be a list, not {fields[name]!r}")
    if "review_waived" in fields and not isinstance(fields["review_waived"], bool):
        raise HTTPException(422, "review_waived must be true or false")


def _reject_bad_status(kind: str, fields: dict) -> None:
    """A status outside this kind's vocabulary, refused before anything commits.

    Off the ladder, which is what makes one gate safe where the deleted
    bespoke note gate argued a shared gate is not: its fear was a parameter,
    then an `if`, then a word admitted to the wrong record — and a vocabulary
    that travels on the rung has no `if` to get wrong. This is the gate that
    stands in front of issues and notes now those routes are gone. A kind with
    `statuses=()` does not read the field at all, so a word there is unread
    rather than undefined: the validator already warns about it beside the
    record, and refusing it here would make the API door stricter than the
    hand-written file it must stay equal to.
    """
    status = fields.get("status")
    if status is None or not RUNG[kind].statuses:
        return
    if status not in RUNG[kind].statuses:
        raise HTTPException(
            422,
            f"status: {status!r} is not a status for {_an(kind)}: expected one of "
            f"{', '.join(RUNG[kind].statuses)}",
        )


async def _sent(request: Request) -> dict:
    """The JSON object a request carried, or a refusal that says so.

    Every route below reads keys off whatever `request.json()` hands back, and
    for four of them that was the first unguarded line in the handler. A
    truncated POST, a proxy that rewrote the body, `JSON.stringify` over the
    wrong variable — the first arrives as a JSONDecodeError and the others as a
    list or a string, and all three were an `AttributeError` under the router,
    which is a 500 with a `text/plain` body. That is the one answer the page
    cannot read back to say what happened, which is the whole reason the field
    checks below exist; the envelope those checks live inside had none.
    """
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "that request body is not JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "a request here is a JSON object, and this one is not")
    return payload


def _base_in(store: Store, payload: dict) -> str:
    """The commit the page was rendered at, checked before anything reads at it.

    Missing, not a string, and a sha this repository never had are one situation
    from the route's side: there is nothing to compare the save against. The
    record save learned it when a restored draft began carrying the commit it
    was drafted against — older than HEAD by design, and gone entirely after a
    re-clone of the plan. The cycle save beside it had the same four ways to
    fault and none of the guard, so the same stale tab was a 500 there.
    """
    base = payload.get("base_commit")
    if not isinstance(base, str) or not store.has(base):
        raise HTTPException(
            422,
            "this page was written against a commit that is not in the plan "
            "repository; copy anything unsaved, reload, and paste it back",
        )
    return base


def _body_in(payload: dict) -> str | None:
    """The body a save carries: text, absent, or a refusal — never a number.

    `len(body.encode(...))` is the size check, and it is also where a body that
    is not text stopped being a save and became an AttributeError.
    """
    body = payload.get("body")
    if body is None:
        return None
    if not isinstance(body, str):
        raise HTTPException(422, f"a body is text, not {body!r}")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise HTTPException(413, "that body is too large to commit")
    return body


def _fields_in(payload: dict) -> dict:
    """The touched fields, as a map. `.items()` on anything else was a 500."""
    fields = payload.get("fields")
    if fields is None:
        return {}
    if not isinstance(fields, dict):
        raise HTTPException(422, f"fields is a map of name to value, not {fields!r}")
    return dict(fields)


def _schema_names(*models: type[BaseModel]) -> tuple[str, ...]:
    """Every field these records declare, in the order they declare it.

    Read off the models rather than written out beside them, so a field added to
    a record is nameable in a commit message on the commit that adds it and a
    list nobody derives cannot go stale.
    """
    names: dict[str, None] = {}
    for model in models:
        names.update(dict.fromkeys(model.model_fields))
    return tuple(names)


# Every kind's fields, off the ladder rather than by naming three of the four:
# a rung added later brings whatever it declares with it, on the commit that adds
# it. (A `Product` has no field of its own today, so this list is unchanged by
# it — which is exactly why writing the kinds out here would have gone unnoticed.)
RECORD_FIELDS = _schema_names(*(rung.model for rung in KINDS))
CYCLE_FIELDS = _schema_names(Cycle)


def _named(fields: dict, known: tuple[str, ...]) -> str:
    """Which fields a save moved, said with names this server chose.

    Every write path here built that phrase as `', '.join(fields)` — the keys of
    a JSON object off the wire, verbatim, into a commit message. A field named

        "notes\\n\\nCo-authored-by: Mallory <mallory@users.noreply.github.com>"

    therefore committed exactly that trailer, and it is not decorative: git's own
    parser reads it, `git shortlog --group=trailer:co-authored-by` counts Mallory
    for it, and GitHub puts their avatar on the commit. This branch is what makes
    `Co-authored-by:` the record of who wrote a document, so a forgeable one is
    worse than none. Measured on the record PATCH and the cycle PUT, which are
    both on `main` today; the issue and note routes happened to be closed already
    because their own gates refuse a field name no model declares.

    An allowlist and not an escape. Stripping newlines would leave the next
    person to work out which characters git's trailer parser accepts, and there
    is no denylist of those that is ever finished — where the model's own field
    names are Python identifiers and cannot spell a trailer at all. Anything else
    the payload carried is counted rather than quoted, because a save that wrote
    something this cannot name is still a save that wrote something.

    In the model's declaration order, which is fixed here, and deliberately not
    in the order the payload arrived: the sender must not choose even the order
    of a line this server signs.
    """
    chosen = [name for name in known if name in fields]
    others = len(fields) - len(chosen)
    if others:
        # Counted in agreement with itself. "1 unnamed fields" was the subject
        # line of a real commit, and a commit message is the one thing this tool
        # writes that outlives the tool.
        plural = "fields" if others > 1 else "field"
        chosen.append(f"{others} more" if chosen else f"{others} unnamed {plural}")
    return ", ".join(chosen)


def _patched(original: str, fields: dict, body: str | None, path: str) -> str:
    """The file with those fields applied, or a refusal naming the file.

    About the file being edited, not about the edit. `patch_text` loads the
    frontmatter it is going to change, so a record somebody wrote in git whose
    YAML never closes raised a ruamel ParserError under the router — a 500 with a
    `text/plain` body, which is the one answer the editor cannot read back to say
    what happened. The page below it is already telling the reader that this file
    is not a record; this is what Save says when they try anyway.
    """
    try:
        return patch_text(original, fields, body)
    except Exception as error:  # noqa: BLE001 - a file in git can be anything
        raise HTTPException(
            422,
            f"{path} is not a record, so it cannot be saved from here: "
            f"{why_it_will_not_read(error, path)}. Fix it in git.",
        ) from None


def _kind_for(record_id: str) -> str:
    """The rung an id names, or a refusal. With `_directory_for` under it, the
    one place a bare id is trusted to mean anything."""
    if not ID_PATTERN.match(record_id):
        raise HTTPException(400, f"{record_id!r} is not a record id")
    return KIND_OF_PREFIX[record_id.split("-")[0]]


def _directory_for(record_id: str) -> str:
    """The directory an id belongs in, or a refusal. The one place an id becomes
    part of a path — everything else must come through here."""
    return DIRECTORY[_kind_for(record_id)]


def _path_for(store: Store, commit: str, record_id: str) -> str | None:
    """Where this record's file actually is, at this commit.

    Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    the path cannot be reconstructed from the id — it has to be found. Guessing
    `<id>.md` works on a corpus nobody has renamed and fails on every real one.
    """
    directory = _directory_for(record_id)
    # Through `record_paths_in`, like every other reader of the tree, so the
    # candidates are the files this directory actually keeps records in. Walking
    # it recursively made `tasks/task-a00001--notes/notes.md` a candidate for
    # `task-a00001`: its stem is `task-a00001--notes/notes`, which starts with
    # the id, so a folder somebody made to keep notes in put a second claim on
    # the id and the record above it answered 409 to every save.
    candidates, _ = record_paths_in([directory], store.paths(commit))
    found = []
    for path in candidates:
        stem = path[len(directory) + 1 : -len(".md")]
        if stem == record_id or stem.startswith(f"{record_id}--"):
            found.append(path)
    # Refuse rather than pick. This returned the first match, and "first match
    # wins" is a coin toss about which record a save destroys — the index resolves
    # the same collision the other way, so the file this chose was reliably not the
    # record the page had shown. Two files claiming one id is a blocker the pages
    # now draw; until a person resolves it, no write to that id is safe.
    if len(found) > 1:
        raise HTTPException(
            409,
            f"{', '.join(sorted(found))} both claim {record_id}. "
            "Rename or remove one in git, then reload — until then a save here "
            "cannot tell which record you meant.",
        )
    return found[0] if found else None


# The models by kind, off the ladder. Written out, this was the SIXTH copy of
# `KINDS` — the one the test that asserts the derivation did not name — so
# `POST /api/record` with `kind: product` raised KeyError and answered 500 on the
# only route that can create one.
MODELS = {rung.name: rung.model for rung in KINDS}


def _as_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_zoom(value: str) -> float | None:
    """Pixels per day, clamped. Unbounded, one typed zero makes an SVG megapixels
    wide and the tab stops responding."""
    try:
        return min(60.0, max(0.5, float(value)))
    except ValueError:
        return None


class Outbox:
    """One member's frames, and the task that puts them on the wire.

    A room used to broadcast by awaiting `socket.send_json` for each member in
    turn. That await is uvicorn's `await self.writable.wait()`, which asyncio
    clears the moment a transport's buffer fills, so a member who stops draining
    does not merely fall behind — they hold the coroutine that was sending to
    them, and therefore the handler it was called from. Every other member's
    keystroke and the room's own twenty-second timer both arrive at that same
    line, so one closed lid stopped the room and every commit in it while every
    page and `/healthz` went on answering 200.

    The queue is the fix, and it is a queue per member rather than a timeout per
    send because a timeout still couples them: everybody else waits for it to
    expire. Here the broadcast never waits at all — `offer` appends and returns —
    and being slow costs the slow member their own queue and nobody else's time.

    Bounded, because an unbounded queue in front of a socket nobody is reading is
    the same outage with a memory leak in it. Past the bound a member is not
    caught up but replaced: their queue is dropped for a single `reload`, which
    is the only honest frame to send a tab that has missed part of a CRDT stream
    it can only apply in order.

    Three numbers and not one, and each answers a different question.
    `MAX_OUTBOX_BYTES` is where being behind starts to count, `STALL_SECONDS` is
    how long behind may last, and `MAX_HELD_BYTES` is what this process will hold
    while the other two make up their minds — because the first two on their own
    bound the *duration* of the stall and say nothing at all about its size, and
    a member wedged for ten seconds queued 1.3 GB. All three are written down
    beside each other above, with what was measured against each.
    """

    def __init__(self, socket: WebSocket) -> None:
        self.socket = socket
        self._frames: deque[str] = deque()
        self._held = 0
        self._ready = asyncio.Event()
        # When this member first went past the ceiling and stayed there, or None
        # if they are keeping up. Cleared by getting back under it, which is the
        # only evidence that matters: a queue that goes down is a socket that is
        # being read.
        self._behind: float | None = None
        # Set when they have been given up on. Read by the socket's own read
        # loop, so a member who comes back to life leaves promptly rather than
        # typing into a room that is no longer listening to them.
        self.overrun = False

    def offer(self, frame: str) -> bool:
        """Queue one frame. False if this member has just been given up on.

        Never awaits and never raises: the whole point is that a caller
        broadcasting to a room cannot be delayed or interrupted by any one member
        in it.
        """
        if self.overrun:
            return False
        self._held += len(frame)
        self._frames.append(frame)
        self._ready.set()
        if self._held <= MAX_OUTBOX_BYTES:
            self._behind = None
            return True
        now = time.monotonic()
        if self._behind is None:
            self._behind = now
        # Two ways to be given up on, and the second is not an impatient version
        # of the first. The clock decides whether this member is draining, which
        # is the only question that can tell *behind* from *stalled* and is worth
        # ten seconds of tolerance. `MAX_HELD_BYTES` decides what this process
        # will spend waiting for that answer — and without it there was no
        # answer, because a queue that grows for the whole stall window grows by
        # however much the room broadcasts in it. Whichever comes first ends the
        # membership.
        if self._held <= MAX_HELD_BYTES and now - self._behind < STALL_SECONDS:
            return True
        self.overrun = True
        # Their queue is worth nothing to them now — a Yjs stream is applied in
        # order or not at all — so it goes, and one frame saying why takes its
        # place. Dropped rather than kept because the whole reason they are being
        # given up on is that this process is holding bytes nobody is reading.
        self._frames.clear()
        goodbye = json.dumps(
            {
                "t": "reload",
                "why": "this tab stopped keeping up with the room, so it has left "
                "it. Nothing in this tab is lost: Save writes the whole document, "
                "the way it did before rooms existed.",
            }
        )
        self._held = len(goodbye)
        self._frames.append(goodbye)
        self._ready.set()
        return False

    async def _next(self) -> str:
        while not self._frames:
            self._ready.clear()
            await self._ready.wait()
        frame = self._frames.popleft()
        self._held -= len(frame)
        return frame

    async def drain(self) -> None:
        """Put queued frames on the wire, for as long as this socket lives.

        One task per connection, so the only thing a blocked send blocks is the
        member it is blocked on. A send that fails is a socket that has gone: the
        read loop is what removes it from the room, and raising here would only
        turn a departure into a traceback.
        """
        try:
            while True:
                await self.socket.send_text(await self._next())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a socket ends in as many ways as there are networks
            return

    async def flushed(self, seconds: float) -> None:
        """Wait for what is still queued to reach the wire, or give up.

        Called by the leaving member's own handler and after the room has already
        been tidied up, so the only person a stalled flush costs time is the one
        leaving. It exists so that the last thing said to a socket — a `reload`,
        a refusal — is actually sent before the task carrying it is cancelled.
        """
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            async with asyncio.timeout(seconds):
                while self._frames:
                    await asyncio.sleep(0.01)


def create_app(
    repo: Path,
    *,
    auth: Literal["dev", "github"] = "dev",
    org: str = "C2SM",
    secret: str = "dev-secret",
    client_id: str = "",
    client_secret: str = "",
    remote: str = "",
    credentials: object | None = None,
    dev_login: str = "dev",
    today: date | None = None,
) -> FastAPI:
    if auth == "github":
        if secret in _DEV_SECRETS:
            raise ValueError(
                "refusing to start: auth='github' with a development signing secret would let "
                "anyone who has read this source mint a session for anybody."
            )
        if not client_id or not client_secret:
            raise ValueError(
                "refusing to start: auth='github' without a client id and secret cannot "
                "complete a sign-in, so nobody could ever write."
            )

    if remote and credentials is None and not remote.startswith("file:"):
        # A remote that needs a credential and has none pushes anonymously, which
        # GitHub refuses — and `_finish` swallows that into `pushed: False`. The
        # tool would look like it was working while every commit stayed on one
        # container's disk until it was replaced.
        from .github import GitHubApp

        absent = GitHubApp.missing(dict(os.environ)) or list(GitHubApp.NEEDS)
        raise ValueError(
            f"refusing to start: a remote at {remote} needs a credential and none is "
            f"configured. {', '.join(absent)} "
            f"{'is' if len(absent) == 1 else 'are'} unset — set "
            f"{'it' if len(absent) == 1 else 'them'}, or drop OPENPROJ_REMOTE to run "
            "against the local repository."
        )
    store = Store(Path(repo), remote=remote or None, credentials=credentials)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        """Hand the writer lock back when this server stops.

        It used to be released only by the process ending, which is true of every
        deployment and of nothing else: two servers over one repository in one
        process — a test that restarts one, a script that opens a second — met
        `StoreLocked` from a server that had already shut down. Single-writer is
        a correctness invariant and stays one; what changes is that stopping now
        counts as stopping.
        """
        yield
        store.close()

    app = FastAPI(title="openproj", lifespan=lifespan)

    @app.middleware("http")
    async def say_what_this_page_may_do(request: Request, call_next):
        """The four headers, on every response including the JSON and the errors.

        Written here rather than per route because the one that matters is the one
        nobody remembered to add: a 500's body is a traceback, a 404's is a
        sentence somebody typed, and both are documents a browser will render.

        `X-Content-Type-Options` because an asset is bytes somebody uploaded and
        the only thing standing between `image/png` and a document is that nobody
        sniffed it. `Referrer-Policy` because a record id in a path is the name of
        a piece of internal planning and there is no reason to hand it to whatever
        a body links out to. `frame-ancestors 'none'` here rather than in the page,
        because a `<meta>` ignores it — and `X-Frame-Options` beside it for the
        readers whose browser predates that.

        The policy itself is `render.CSP`, the same string the pages carry in a
        `<meta>`, so the served copy and the exported copy cannot drift into
        disagreeing about what a page is allowed to do.
        """
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = f"{render.CSP}; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    watchers: set[asyncio.Queue] = set()
    # An event stream is a request that never ends, and uvicorn waits for in-flight
    # requests BEFORE it runs lifespan shutdown — so a flag set there arrives after
    # the wait it was meant to shorten. Installing a signal handler here does not
    # work either: uvicorn installs its own afterwards and replaces it. The runner
    # sets this from uvicorn's own exit hook, which is the only thing that fires
    # early enough. See cli._serve.
    closing = threading.Event()
    app.state.closing = closing

    # The last index built, and the commit it was built from. An index is a pure
    # function of a commit and the day it is drawn around, so a second request
    # against the same commit can have the first one's answer.
    #
    # Measured before this existed, on a plan of 518 records: reading and parsing
    # every file out of the tree was 502 ms of a 941 ms PATCH, and every request
    # paid it — `save` twice, once for the contested-id check and once for the
    # loop check. 19 ms at 31 records, 116 at 208, 502 at 518: it is the cost that
    # grows with the plan, and the one that will be felt as the plan grows.
    #
    # One entry and not a dictionary of them. A plan has one head, and everything
    # in front of it is looking at that head; a cache of every commit ever served
    # would hold the whole history of a long-lived instance in memory to answer a
    # question nobody asks twice.
    #
    # `today` is part of the key because it is part of the answer: an index drawn
    # around yesterday has yesterday's overruns and yesterday's today-line, and an
    # instance that lives across midnight would otherwise serve them until
    # somebody wrote something.
    # One tuple under one name, and that shape is the point. Written as three
    # keys in a dict, a reader can pass the commit test, be preempted while a
    # writer replaces the entry, and then read `held["index"]` — handing back
    # THIS commit's sha with THAT commit's index. The page would be drawn from
    # one commit and hand the browser a different one as its `base_commit`, which
    # is the value every save is compared against.
    #
    # Reading a single name is one atomic load under the GIL, so there is no
    # window to be preempted in. 25 of this app's routes are sync `def` and
    # Starlette dispatches those through anyio's worker threads, so concurrent
    # readers are the normal case rather than the exotic one.
    held: tuple[str, date, Index] | None = None

    def index_now():
        nonlocal held
        commit = store.head()
        drawn = today or date.today()
        memo = held
        if memo is not None and memo[0] == commit and memo[1] == drawn:
            return commit, memo[2]
        commit, index = _build_index_at(commit, drawn)
        held = (commit, drawn, index)
        return commit, index

    def _build_index_at(commit: str, drawn: date):
        config, unreadable_config = _config_at(store, commit)
        records, unreadable_records = _records_at(store, commit)
        return commit, build_index(
            records,
            config,
            # Pinned only where somebody pinned it, which today is `openproj
            # demo`: the seed corpus is written around one day as "now", and
            # served in December it draws a plan every date of which is in the
            # past — a demo of a scheduler with nothing left to schedule. A write
            # still stamps the real date, because a commit happens when it
            # happens; this is the day the plan is DRAWN around.
            drawn,
            # Sorted by path, because a reader works through the list by opening
            # files and two walks finishing in whatever order is not that order.
            unreadable=sorted(
                [*unreadable_config, *unreadable_records], key=lambda one: one.path
            ),
        )

    # The last history walk, and the head it walked TO. Keyed on the commit
    # ALONE — deliberately narrower than the index cache's (commit, today)
    # above: the map is a fact about history, not about the day the plan is
    # drawn around, and an instance living across midnight must not re-walk a
    # second of history to redraw the same answer.
    #
    # One name, swapped atomically, for the reason `held` gives at length: two
    # dozen sync routes run on anyio worker threads, and reading a single name
    # is one atomic load under the GIL.
    edited_held: tuple[str, dict[str, int]] | None = None

    def edited_now() -> tuple[str, dict[str, int]]:
        nonlocal edited_held
        memo = edited_held
        if memo is not None and memo[0] == store.head():
            return memo
        # `known=memo` advances over just the new commits when the cached
        # commit is an ancestor of head; anything else — a rewound ref after a
        # lost push race is ROUTINE here, not a force-push story — discards and
        # re-walks. Retract-by-rebuild: no retraction logic to get wrong, and
        # affordable because the full walk is about a second (measured: ~0.5 ms
        # per commit on a 520-record plan).
        fresh = store.last_edited(known=memo)
        edited_held = fresh
        return fresh

    # Startup owns the first walk: `cli._serve` calls this before uvicorn
    # binds, and the lifespan hook stays empty at startup on purpose. The walk
    # must never ride a request — a second billed to whichever reader loses
    # the race is exactly the cost this cache exists to hide.
    app.state.warm_edited = edited_now

    def viewer(request: Request) -> User | None:
        """Both names are read, prefixed first.

        A signature that does not verify is nobody, so trying the second name
        after the first costs a session nothing and saves the one case where the
        two disagree: a server that used to be plain HTTP and is now behind TLS,
        where the browser is still holding yesterday's bare cookie.
        """
        for name in (SESSION_COOKIE, SESSION_COOKIE_INSECURE):
            user = read_session(request.cookies.get(name), secret)
            if user is not None:
                return user
        return None

    def writer(request: Request) -> User:
        """Who is allowed to write, decided per request rather than at login.

        In dev mode anybody may write, but the session still decides *who they
        are*: dev never invents an author, because a commit attributed to nobody
        is worse than no commit.

        `dev_login` is who a dev run is when no session says otherwise. It is
        `dev` for `openproj serve`, which is what it always was, and a name off
        the plan's own roster for `openproj demo` — because the People page hangs
        the icon picker off the signed-in person's ROW, and `dev` holds no work
        in any plan, so it has no row. A demo signed in as nobody is a demo of
        the People page with the one control on it missing.
        """
        user = viewer(request)
        if auth == "dev":
            return user or User(login=dev_login, member=True)
        if user is None:
            raise HTTPException(401, "sign in to make changes")
        if not user.member:
            raise HTTPException(403, f"{user.login} is not a member of {org}")
        return user

    def may_write(request: Request) -> bool:
        """Whether this request would be allowed to write, asked before a socket
        is opened rather than after it is refused.

        Through `writer` and not through a second reading of the session, for the
        reason `picker_for` below gives at length: two spellings of "who may
        write" is how a page comes to offer something whose only answer is 403.

        It matters that it is this function and not `/api/me`, which the page
        already fetches to draw the corner. `/api/me` answers `viewer` — the
        session cookie and nothing else — and under `--auth dev` there is no
        cookie while `writer` invents `dev_login` and permits the write. Gating on
        the corner would therefore refuse the socket in exactly the mode somebody
        tries this tool in, with every test still green, because the tests sign a
        cookie.
        """
        try:
            writer(request)
        except HTTPException:
            return False
        return True

    def picker_for(request: Request) -> str:
        """The login this request may set an icon for, or "" for nobody.

        The same two questions `PUT /api/icon` asks, asked before a control is
        drawn rather than after it is pressed: may this request write at all, and
        is its login one a file in `people/` can be named for. Answered here by
        calling `writer` rather than by a second reading of the session, because
        two spellings of "who may write" is how a page comes to offer a button
        whose only answer is 403 — the same defect as the cycle page that rendered
        every number and refused every Save.

        The roster is deliberately not one of the questions. `known_people` is the
        validator's list and a name missing from it is a warning there, never a
        refusal; making it decide who may pick an icon would put a hand-maintained
        file on the write path of something it does not validate — and the version
        of this that did exactly that drew a picker for everybody the moment
        `config/people.yaml` stopped parsing, because an unreadable roster reads
        as an empty one and an empty roster means "no check".
        """
        try:
            user = writer(request)
        except HTTPException:
            return ""
        return user.login if person_path(user.login) else ""

    def secure_for(request: Request) -> bool:
        """Whether cookies are marked Secure, from the scheme actually in use.

        Hard-coded true, a cookie set over plain HTTP is a cookie the browser
        never stores — which is every local run and every test. Behind Cloud Run
        the TLS is terminated upstream, so uvicorn must run with --proxy-headers
        for this to see https.
        """
        return request.url.scheme == "https"

    def session_name(request: Request) -> str:
        """The name that can actually be stored on this connection.

        Set and cleared through the same function, because a deletion aimed at
        the other name is a session that quietly stays signed in — and that half
        of this was already known and commented on before the setting half was
        found to have never worked at all.
        """
        return SESSION_COOKIE if secure_for(request) else SESSION_COOKIE_INSECURE

    async def announce(commit: str, changed: list[str]) -> None:
        for queue in list(watchers):
            queue.put_nowait({"commit": commit, "changed": changed})

    # -- pages --------------------------------------------------------------

    def page(html: str) -> HTMLResponse:
        return HTMLResponse(html)

    def record_list(only: str | None) -> HTMLResponse:
        """The landing and its two inbox views: one renderer, one page, the
        population decided by the route."""
        commit, index = index_now()
        # The map may be one commit ahead of `commit` if a write lands between
        # the two reads. The times are display; the rows are the index's; the
        # event stream's reload reconciles them a moment later.
        _, stamps = edited_now()
        return page(
            render.render_records(
                index,
                render.ROUTES,
                base_commit=commit,
                edited=edited_by_id(stamps),
                now=int(time.time()),
                only=only,
            )
        )

    @app.get("/", response_class=HTMLResponse)
    def records() -> HTMLResponse:
        return record_list(None)

    @app.get("/issues", response_class=HTMLResponse)
    def issues() -> HTMLResponse:
        return record_list("issue")

    @app.get("/notes", response_class=HTMLResponse)
    def notes() -> HTMLResponse:
        return record_list("note")

    @app.get("/table", response_class=HTMLResponse)
    def table() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_table(index, render.ROUTES, base_commit=commit))

    @app.get("/graph", response_class=HTMLResponse)
    def graph() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_graph(index, render.ROUTES, base_commit=commit))

    @app.get("/timeline", response_class=HTMLResponse)
    def timeline(
        from_: str = Query("", alias="from"), to: str = "", zoom: str = ""
    ) -> HTMLResponse:
        """The window and the day width come off the URL, so a view is a link.

        Every one of the three is typed by hand as easily as it is picked, so all
        three are parsed leniently: a nonsense value falls back to the default view
        rather than turning a bookmark into a 422.
        """
        window = (_as_date(from_), _as_date(to))
        return page(render.render_timeline(index_now()[1], render.ROUTES, window, _as_zoom(zoom)))

    def which_editor(request: Request) -> str:
        """Which editing surface this page is asked to carry.

        A query parameter and not a cookie, and that is the whole design: the
        two surfaces are 594 KB apart and the server has to know before it
        renders which one is in the page, while the preference that remembers the
        choice is `localStorage` and the server cannot see it. So the address is
        what decides, and the page carries the choice back into the address on
        the next visit so it is typed once.

        **The parameter opts out now, not in** — `?editor=plain`, on jcanton's
        "make ace the default, I think it's worth it", 2026-08-20. The machinery
        is unchanged and only its default arm moved, which means the page load
        that the sticky preference costs moved with it: it is the people who want
        the plain box who now pay a reload, and that is the better side to put it
        on, because it is the smaller page arriving for the person who asked for
        a smaller page rather than 594 KB arriving twice for everybody else.

        Read as an allowlist and not as a string, for the reason `_status_class`
        is written the way it is: whatever arrives goes nowhere near a lookup that
        could be surprised by it. Both spellings are named, so that `?editor=ace`
        keeps meaning what it always meant and a link somebody saved still opens
        the editor it promised.
        """
        asked = request.query_params.get("editor", "")
        return asked if asked in (render.ACE, render.PLAIN) else ""

    # The retired per-record routes, kept as addresses and nothing else.
    # Bookmarks, commit messages and chat scrollback are full of these URLs; a
    # URL that answered 200 last week and 404 this week reads as a deleted
    # record, not a moved page. 301 because the move is permanent, and the ids
    # are percent-encoded on the way through: a path segment out of the wire
    # is not a thing to write into a Location header verbatim. The `new`
    # routes are declared before the `{id}` routes because the router matches
    # in order and `new` would otherwise be a record id. (`/issues` and
    # `/notes` are not here: they briefly 301ed to `/` and render again now,
    # as the filtered views above.)
    @app.get("/issue/new")
    def new_issue_moved() -> RedirectResponse:
        return RedirectResponse("/new?kind=issue", status_code=301)

    @app.get("/note/new")
    def new_note_moved() -> RedirectResponse:
        return RedirectResponse("/new?kind=note", status_code=301)

    @app.get("/issue/{issue_id}")
    def issue_moved(issue_id: str) -> RedirectResponse:
        return RedirectResponse(f"/detail/{quote(issue_id, safe='')}", status_code=301)

    @app.get("/note/{note_id}")
    def note_moved(note_id: str) -> RedirectResponse:
        return RedirectResponse(f"/detail/{quote(note_id, safe='')}", status_code=301)

    @app.post("/api/promote")
    async def promote(request: Request) -> JSONResponse:
        """Turn a note or an issue into a record somebody can bet on.

        **An inbox that cannot become work is a second inbox nobody empties.**
        That is the whole reason this route exists: without it a note is a place
        ideas go to be forgotten politely, and the tool has two of those.

        Four decisions are worth reading before changing this.

        **The source survives.** It is not deleted, moved or emptied. It is the
        only record of the thinking that led to the bet, and `git log` is the
        team's memory — a promotion that removed the note would answer "where did
        this pitch come from" with a file nobody can open without knowing to look
        for a deletion. It also means `store` needs no delete, which would be a
        more destructive verb than anything else here has on a protected branch.

        **The trail is written at both ends, in two different registers.** The
        source gets `became` (or `pitched_into`), which is the machine-readable
        end, on the record where the decision was made — one direction only, the
        same rule `depends_on` follows. The new record says where it came from in
        its own shaping document, in prose. That is deliberately not a field: a
        `from_note` on `Record` would put a note id into every PLANNED record's
        frontmatter, and the table, the graph and the detail page would each
        have to decide what to do with it — the coupling that used to be
        prevented by notes not being records, and is prevented now by the
        field living on the unplanned side of the edge only. Prose cannot
        drift out of step with anything, because nothing reads it but a person.

        **One commit.** Two files, one decision. See `Store.write_all`: written as
        two commits, the second can fail after the first has landed, leaving a
        pitch in the plan and a note that does not know what it became — on a
        branch whose protection means the first commit cannot be taken back.

        **The new record is created in `shaping` and carries no field the source
        could not honestly give it.** Title, tags and body cross; owner, size,
        appetite, cycle and reviewer do not, because the source has none of them
        and inventing one would be this tool asserting a commitment nobody made.
        `shaping` is the status whose required-field gate is empty — "an idea
        nobody has bet on has no owner and no size by definition" — so a
        promotion always produces a record that validates. That is not luck; it
        is the same claim the note was already making, carried across.

        The request carries two values and both are closed vocabularies: a source
        id matched against the one record pattern and required to name an inbox
        rung, and a kind out of `DIRECTORY`. No path, no directory, no file
        name, no field, no body.
        """
        user = writer(request)
        payload = await _sent(request)
        source_id = str(payload.get("source") or "")
        kind = payload.get("kind")

        # The id decides which inbox this is, off the ladder, through the same
        # pattern every record write uses — the bespoke patterns went with the
        # bespoke routes. A kind that is not an inbox is a 400 like a garbage
        # id, because "promote a task" is not a request this route has ever
        # taken and the tell is the same either way: the source is not a note
        # or an issue.
        kind_of_source = KIND_OF_PREFIX.get(source_id.split("-")[0])
        if not ID_PATTERN.match(source_id) or kind_of_source not in INBOXES:
            raise HTTPException(400, f"{source_id!r} is not a note or an issue")
        inbox = kind_of_source
        stamp = INBOXES[inbox]
        # One phrase, used by the refusal and by the citation the promoted
        # document carries. Written twice they drift, and one of the two is prose
        # that ends up committed to the plan.
        article = _an(inbox)
        if kind not in render.PROMOTABLE[inbox]:
            raise HTTPException(
                422,
                f"{article} becomes {' or '.join(render.PROMOTABLE[inbox])}, not {kind!r}",
            )

        base = _base_in(store, payload) if payload.get("base_commit") else store.head()
        # The finder every record write uses: inbox files may carry `--slug`
        # names like any other record, so the path cannot be reconstructed
        # from the id — it has to be found.
        path = _path_for(store, base, source_id)
        original = store.read(base, path) if path is not None else None
        if original is None:
            raise HTTPException(404, f"no {inbox} {source_id!r}")
        # Parsed rather than read out of the index, because the index is at HEAD
        # and this is at the commit the page was rendered at — and a promotion
        # carries the body somebody was looking at, not one that moved under them.
        source = parse_text(original, path)
        # With defaults, because the file was found by its stem and its
        # frontmatter is a hand edit away from declaring some other kind: a
        # mis-kinded record loses its citation line, not the whole route.
        who = getattr(source, stamp.author, None)
        when = getattr(source, stamp.dated, None)

        record_id = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        commit = store.head()
        config, _ = _config_at(store, commit)
        content = patch_text(
            "---\n---\n",
            {
                "id": record_id,
                "kind": kind,
                "title": source.title,
                # The one status that requires nothing, which is the honest state
                # of anything that has just been promoted. See the docstring.
                "status": "shaping",
                "tags": list(source.tags),
                "created_schema_version": config.schema_version,
            },
            shaping_document(
                render.TEMPLATES.get(kind, ""),
                promoted_from(source_id, article, who, when),
                source.body,
            ),
        )
        try:
            candidate = parse_text(content, record_id)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a record: {why_it_will_not_read(error)}"
            ) from None
        blockers = [
            problem
            for problem in validate_all([*_records_at(store, commit)[0], candidate], config)
            if problem.record_id == record_id and problem.severity == "blocker"
        ]
        if blockers:
            return JSONResponse(
                {"problems": [p.model_dump(mode="json") for p in blockers]}, status_code=422
            )

        # Appended, not replaced: a note that split into two pitches is the normal
        # case, and it is the reason both fields are lists.
        marked = _patched(
            original, {stamp.link: [*getattr(source, stamp.link, []), record_id]}, None, path
        )
        # Read back before it is written, the refusal every write path here makes.
        # This one has the least to go wrong — the file parsed four lines up and
        # gains one list of ids — and it is the write that must not half-happen,
        # so it is checked rather than assumed.
        try:
            parse_text(marked, path)
        except ValueError as error:
            raise HTTPException(
                422,
                f"that would not read back as {article}: {why_it_will_not_read(error)}",
            ) from None
        written = await asyncio.to_thread(
            store.write_all,
            {f"{DIRECTORY[kind]}/{record_id}.md": content, path: marked},
            base_commit=base,
            author=user.login,
            message=f"{record_id}: promoted from {source_id}",
        )
        if written.outcome == "conflict":
            return _result(written, base)
        if written.commit:
            await announce(written.commit, [record_id, source_id])
        return JSONResponse(
            {"id": record_id, "outcome": written.outcome, "commit": written.commit},
            status_code=201,
        )

    @app.get("/cycles", response_class=HTMLResponse)
    def cycles() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_cycles(index, render.ROUTES, commit))

    @app.get("/cycle/{number}", response_class=HTMLResponse)
    def cycle(number: int) -> HTMLResponse:
        """Typed `int`, so nothing that is not a number ever reaches a path.

        Stronger than a pattern: FastAPI refuses a non-integral value before the
        handler body runs, so `..` and `%2F` cannot get as far as being rejected
        by a regex somebody might later relax.

        Bounded to the same numbers the save accepts. `int` admits -1 and 99999,
        which rendered a whole editable cycle page whose every Save was a 422
        from `CYCLE_PATTERN` — the read path and the write path disagreeing about
        which cycles exist, which is a dead end a person can only find by filling
        the form in first.
        """
        if not CYCLE_PATTERN.match(str(number)):
            raise HTTPException(404, "a cycle is numbered 0 to 9999")
        commit, index = index_now()
        return page(render.render_cycle(index, number, render.ROUTES, commit))

    @app.get("/deck/{number}", response_class=HTMLResponse)
    def deck(number: int) -> HTMLResponse:
        """The review deck for one cycle, printable to one slide a page.

        Bounded the same way `/cycle/{number}` is, and by the same pattern: two
        routes taking one number that disagreed about which numbers exist is the
        dead end that one already has a comment about.

        Read at `commit` and not at `store.head()`. The index and the pictures on
        the same slides have to be the same snapshot — a screenshot fetched from
        a commit later than the record beside it is a deck that quietly mixes two
        states of the plan, and this page's whole job is to be handed to somebody
        who cannot check.
        """
        if not CYCLE_PATTERN.match(str(number)):
            raise HTTPException(404, "a cycle is numbered 0 to 9999")
        commit, index = index_now()
        return page(
            render.render_deck(
                index,
                number,
                render.ROUTES,
                lambda name: store.read_asset(commit, f"assets/{name}"),
            )
        )

    @app.get("/people", response_class=HTMLResponse)
    def people(request: Request) -> HTMLResponse:
        me = picker_for(request)
        return page(
            render.render_people(index_now()[1], render.ROUTES, editable=bool(me), me=me)
        )

    @app.get("/new", response_class=HTMLResponse)
    def new(request: Request, kind: str = "task") -> HTMLResponse:
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        commit, index = index_now()
        who = viewer(request)
        return page(
            render.render_detail(
                index,
                render.ROUTES,
                base_commit=commit,
                may_write=may_write(request),
                editor=which_editor(request),
                creating=kind,
                signed_in=who.login if who else "",
            )
        )

    @app.get("/detail", response_class=HTMLResponse)
    def detail_index() -> HTMLResponse:
        return page(render.render_detail(index_now()[1], render.ROUTES))

    @app.get("/detail/{record_id}", response_class=HTMLResponse)
    def detail(record_id: str, request: Request) -> HTMLResponse:
        commit, index = index_now()
        if record_id not in index.records:
            raise HTTPException(404, f"no record {record_id!r}")
        # The page carries the commit it was rendered at, so a save is compared
        # against what the person actually saw rather than against whatever HEAD
        # has become while the tab sat open.
        #
        # And whether this reader may write, because the co-editing socket is
        # only offered to somebody the server would accept a frame from. Reads
        # here are public, so most page loads are readers — and every one of them
        # used to open a socket, be refused, and try four more times, which is
        # five red lines in the console of a page that is working exactly as
        # designed. That is how a real error comes to be ignored.
        who = viewer(request)
        return page(
            render.render_detail(
                index,
                render.ROUTES,
                only=record_id,
                base_commit=commit,
                may_write=may_write(request),
                editor=which_editor(request),
                signed_in=who.login if who else "",
            )
        )

    @app.post("/api/preview")
    async def preview(request: Request) -> JSONResponse:
        """Render markdown the same way the page will, on the server.

        A second markdown implementation in JavaScript would eventually disagree
        with this one, and the renderer people trust would not be the one whose
        output gets committed.

        The title comes with the body because the page drops a leading heading
        that only restates it, and the title being previewed is the one in the
        form — not the one in the repository, which the same Save is about to
        change.
        """
        payload = await _sent(request)
        # `str()` rather than a refusal: this route renders, it does not write, and
        # a preview is worth showing for whatever was typed. But the markdown
        # parser takes text and a number reached it as a TypeError — a 500 on the
        # only write-adjacent route that answers an anonymous visitor.
        return JSONResponse(
            {
                "html": render.preview_html(
                    str(payload.get("body") or ""), title=str(payload.get("title") or "")
                )
            }
        )

    @app.get("/api/body/{record_id}")
    def body(record_id: str) -> JSONResponse:
        """One record's shaping document, rendered, for the hover card.

        Fetched on hover rather than shipped with the rows. The table's payload
        is in every page of every view, and the body is the longest field a
        record has — inlining four hundred of them puts the whole corpus into
        every page load to answer a question about the one row somebody is
        pointing at.

        Rendered here and not in the browser for the reason `/api/preview` gives:
        a second markdown implementation in JavaScript would eventually disagree
        with this one, and the card would show something the detail page does
        not.

        404 rather than an empty body for an id this plan has not got, because a
        card that draws nothing for a typo and nothing for a record with no
        document is a card that cannot say which it is. An empty document is a
        200 with an empty string, and the card says so in words.
        """
        record = index_now()[1].records.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such record")
        return JSONResponse({"html": str(render._body_html(record, render.ROUTES))})

    # Two paths, one answer, because `/healthz` is not ours on Cloud Run.
    #
    # Google's frontend answers `/healthz` itself with its own 404 page — the
    # "Error 404 (Not Found)!!1" robot — and the request never reaches the
    # container. Observed on the deployed service: `/healthz` came back as
    # Google-branded HTML with no access-log line, while an unrouted path on the
    # same host came back as this app's JSON 404 carrying this app's CSP header.
    # So the check that is meant to prove the service is alive was the one URL
    # that could not reach it, and it failed on a service that was working.
    #
    # `/api/health` sits in the namespace this app already owns and nothing in
    # front of it claims. `/healthz` stays for a run behind anything else — it is
    # the convention every other health check follows — but nothing this project
    # ships points at it any more.
    @app.get("/healthz")
    @app.get("/api/health")
    def healthz() -> dict:
        # `version` because the whole point of tagging a deploy is being able to
        # ask the running service what it is, and until now it could not answer.
        # `head` is the PLAN's commit and moves whenever anybody saves a record;
        # `version` is this code's, and moves only on a release. They were one
        # field's worth of confusion apart, and the deploy runbook in AGENTS.md
        # told a reader to check a version string that nothing served.
        return {"ok": True, "head": store.head(), "version": __version__}

    @app.get("/api/index.json")
    def index_json() -> JSONResponse:
        commit, index = index_now()
        # Through the same door the pages' data blocks go through. `JSONResponse`
        # encodes with `allow_nan=False`, so a size somebody hand-edited to
        # `.inf` raised inside the encoder — after the response object existed,
        # which is a 500 in plain text on a route whose readers are scripts.
        return JSONResponse(
            what_json_can_carry(
                {
                    "head": commit,
                    "plan": {i: e.model_dump(mode="json") for i, e in index.plan.items()},
                    "spans": {i: s.model_dump(mode="json") for i, s in index.spans.items()},
                    "explanations": {i: e.text for i, e in index.explanations.items()},
                    # The PLAN's problems only, now that `validate_all` covers
                    # every record: `plan` is the only record map this payload
                    # ships, so a problem keyed by an inbox id would be keyed by
                    # an id the payload's own map cannot resolve — the count-
                    # versus-filter mismatch the table was already fixed for.
                    "problems": [
                        p.model_dump(mode="json")
                        for p in index.problems
                        if p.record_id in index.plan
                    ],
                    # A script reading this has to be able to tell "the plan
                    # holds sixteen tasks" from "the plan holds sixteen tasks
                    # that parsed", and nothing else in this payload says so.
                    "unreadable": [u.model_dump(mode="json") for u in index.unreadable],
                }
            )
        )

    @app.get("/api/table.json")
    def table_json() -> JSONResponse:
        """The table's own payload, exactly as the page was rendered with it.

        A write that moves a row in the tree changes columns nothing in the
        browser can recompute — the dates, the size, the blocker count, which
        project a row counts against — so the page re-reads them rather than
        guessing. It re-reads them through the same function that built the page,
        because the alternative is `_row` written a second time in JavaScript,
        and the copy that only runs after a save is the copy nobody would ever
        have looked at again.

        Not folded into `/api/index.json` beside it: that route answers with
        records and spans, which is the index, and a view of the index shaped
        for one page does not belong inside it. `what_json_can_carry` for the
        same reason the route above uses it — a `person_weeks` somebody
        hand-edited to `.inf` is a 500 in plain text on a route whose only
        readers are scripts.
        """
        return JSONResponse(what_json_can_carry(render._payload(index_now()[1])))

    # -- writing ------------------------------------------------------------

    def _result(written, commit_before: str) -> JSONResponse:
        """One shape for every answer. A caller should not have to know whether it
        succeeded to know which keys exist."""
        payload = {
            "outcome": written.outcome,
            "commit": written.commit,
            "conflict": written.conflict,
            "head": commit_before,
        }
        return JSONResponse(payload, status_code=409 if written.outcome == "conflict" else 200)

    @app.patch("/api/record/{record_id}")
    async def save(record_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        # A commit this repository does not have is a refusal, not a crash. This
        # is the one route that is handed a base older than HEAD by design — a
        # restored draft carries the commit it was drafted against — so a draft
        # that has sat in a browser through a re-clone of the plan arrives with a
        # sha `store.paths` throws on.
        base = _base_in(store, payload)
        path = _path_for(store, base, record_id)
        if path is None:
            raise HTTPException(404, f"no record {record_id!r}")
        original = store.read(base, path)
        # An id two files claim is an id this route cannot write to, and the check
        # is a question to the index rather than a second derivation of it.
        #
        # Comparing this file against its own name is not enough, and the case that
        # proves it has both halves innocent on their own: the file named for the
        # id declares it, so it looks right from here, while a *different* file —
        # named for something else — also declares it, and being later in tree
        # order takes the id in the index. The page showed that one. The save lands
        # on this one. Both answer 200 and neither file is individually wrong; the
        # contest only exists across the two, which is exactly what the index
        # already computed and drew a banner about.
        contested = [
            problem
            for problem in index_now()[1].problems
            if problem.record_id == record_id
            and problem.field == "id"
            and problem.severity == "blocker"
        ]
        if contested:
            raise HTTPException(
                409,
                f"{contested[0].message}. Resolve it in git and reload — a save here "
                "would edit a record that is not the one you were shown.",
            )

        fields = {k: v for k, v in _fields_in(payload).items() if k != "id"}
        _reject_bad_types(fields)
        # `parse_text` below deliberately takes any word — a file that arrived
        # in git with one must still load — so without this the PATCH door
        # committed a status nobody defined, and the plan woke up with a
        # blocker about it on a branch where the commit cannot be force-pushed
        # away.
        _reject_bad_status(_kind_for(record_id), fields)
        content = _patched(original, fields, body, path)
        # Parse before writing, the same refusal the cycle route beside this one
        # makes, and for a worse reason: a record that fails to load takes `/`,
        # `/detail/<id>` and `/api/index.json` down for everybody, on every read,
        # and the file is already in git — on a protected branch, so the commit
        # cannot be force-pushed away and the repair is a second crafted PATCH
        # against a sha the 500ing pages will not give you. `_reject_bad_types`
        # names numbers, lists and one bool; everything it does not name — a
        # title that is a number, a date that is a word, a tag that is null —
        # came through here and committed.
        try:
            candidate = parse_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a record: {why_it_will_not_read(error)}"
            ) from None
        # A record cannot be its own ancestor, and cannot wait for itself.
        # `validate_all` reports both as blockers, which is the right answer for a
        # plan that ARRIVED with one — a file in git is a fact, and refusing to
        # load it takes every page down over somebody else's mistake. It is the
        # wrong answer for a plan about to acquire one: the blocker would land
        # after the commit, on a protected branch, about a shape nobody can see
        # the cause of. Asked of the same function the validator asks, so the
        # refusal and the report cannot disagree.
        # `records`, not `plan`: an issue or a note handed to `loop_made`
        # must be checked against the population it actually lives in — a
        # candidate absent from the checked set is a question asked of the
        # wrong world.
        loop = loop_made(candidate, index_now()[1].records.values())
        if loop:
            raise HTTPException(409, loop)
        written = await asyncio.to_thread(
            store.write,
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{record_id}: {_named(fields, RECORD_FIELDS) or 'body'}",
        )
        if written.commit:
            await announce(written.commit, [record_id])
        return _result(written, base)

    @app.delete("/api/record/{record_id}")
    async def remove(record_id: str, request: Request) -> JSONResponse:
        """Take one record out of the plan.

        Out of the *plan*, not out of the repository: the commit removes the file
        from the tip and every version of it stays in the history, which is the
        one property that makes a delete button here defensible at all. Somebody
        who deletes the wrong thing gets it back with `git revert`.

        It cascades, and it says what it will take with it first. Everything filed
        under this record goes with it — a task whose pitch no longer exists is
        parented to an id that is not there, which is a blocker `validate_all`
        reports about a file its owner never touched. Everything that DEPENDS on
        it keeps its file and loses the dependency: that is unrelated work which
        merely waits for this, and deleting it would be a two-click gesture
        reaching across the plan.

        **The confirmation is binding.** The page sends back the ids it showed,
        and this refuses if the plan's answer has changed since — somebody filed a
        new task under the pitch while the panel was open, and the version without
        this check deletes it without ever having named it. That is the failure a
        cascade confirmation exists to prevent, so it is a compare-and-swap on the
        SHAPE of the deletion, beside the one the store already does on the bytes
        of each file.

        One commit for all of it, through `write_all`, for the reason promotion
        uses it: this is one decision, and a `git log` that shows a pitch removed
        and then four tasks removed says four things that are not true. It also
        removes the half-done state — a subtree half deleted, on a protected
        branch, is not a state anybody can be asked to repair.
        """
        user = writer(request)
        payload = await _sent(request)
        base = _base_in(store, payload)
        path = _path_for(store, base, record_id)
        if path is None:
            raise HTTPException(404, f"no record {record_id!r}")
        _, index = index_now()
        doomed, edited = cascade_of(index, record_id)

        shown = payload.get("also")
        if shown is not None and sorted(shown) != sorted(doomed + edited):
            raise HTTPException(
                409,
                "the plan changed while that was open: deleting "
                f"{record_id} now affects {_and_then(doomed + edited) or 'nothing else'}. "
                "Nothing was deleted — read it again and decide.",
            )

        files: dict[str, str | None] = {path: None}
        for other in doomed:
            gone = _path_for(store, base, other)
            if gone is None:
                raise HTTPException(409, f"{other} is filed under this and could not be found")
            files[gone] = None
        for other in edited:
            where = _path_for(store, base, other)
            if where is None:
                raise HTTPException(409, f"{other} depends on this and could not be found")
            # `records`, not `plan`: `cascade_of` iterates the total map,
            # so `edited` can name an unplanned record carrying a hand-written
            # `depends_on` — the plan-only lookup KeyErrored and the DELETE
            # 500ed, which is exactly the failure totality exists to prevent.
            kept = [
                target
                for target in index.records[other].depends_on
                if target != record_id and target not in doomed
            ]
            files[where] = _patched(store.read(base, where), {"depends_on": kept}, None, where)

        written = await asyncio.to_thread(
            store.write_all,
            files,
            base_commit=base,
            author=user.login,
            message=_deletion_message(record_id, doomed, edited),
        )
        if written.commit:
            await announce(written.commit, [record_id, *doomed, *edited])
        return _result(written, base)

    @app.put("/api/cycle/{number}")
    async def save_cycle(number: int, request: Request) -> JSONResponse:
        """Create or update one cycle record.

        PUT rather than PATCH because a cycle is set up in one sitting: the whole
        roster is written at once, and a missing name means somebody was removed
        rather than left alone. That is the opposite of a record's per-field
        merge, and conflating the two would make removing a person impossible.
        """
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        if not CYCLE_PATTERN.match(str(number)):
            raise HTTPException(422, "a cycle is numbered 0 to 9999")

        base = _base_in(store, payload)
        path = _cycle_path(number)
        original = store.read(base, path) or "---\n---\n"
        fields = _fields_in(payload)
        fields["cycle"] = number
        _reject_bad_cycle(fields)

        content = _patched(original, fields, body, path)
        # Parse before writing, not after: a roster that fails to load would take
        # every date on every page with it, and the file would already be in git.
        # Refused rather than raised — everything the checks above do not name
        # reached here as an unhandled ValidationError, which is a 500 with a
        # plain-text body, and a plain-text body is a client that cannot even
        # report the failure.
        try:
            parse_cycle_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a cycle: {why_it_will_not_read(error)}"
            ) from None
        written = await asyncio.to_thread(
            store.write,
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"cycle {number}: {_cycle_message(fields)}",
        )
        if written.commit:
            await announce(written.commit, [f"cycle-{number}"])
        return _result(written, base)

    @app.put("/api/icon")
    async def choose_icon(request: Request) -> JSONResponse:
        """Your own icon, in your own record, and nothing else anywhere.

        The writable surface is closed by construction — an id is admitted against
        a regex and the directory comes from its prefix — and this adds a fourth
        directory to it rather than a general config writer. `PUT /api/config/…`,
        or a file name in the body, is the version where the bound stops being a
        property of the shape and becomes a check inside a handler that somebody
        can be talked out of, forget on the second door, or relax by one case.
        `POST /api/record` had no type check at all for as long as its sibling
        did, because the closed surface was closed on one of two ways in.

        So four things are not parameters here:

        * **The directory.** `people/` is a constant in `model.person_path`, which
          is the only function that puts anything after it.
        * **The file name.** `LOGIN_PATTERN` is 1–39 of `[A-Za-z0-9-]` with no
          hyphen at either end, so no spelling of `..` and no encoding of `/` has
          anywhere to arrive. The same function answers the People page, so a
          login this refuses is a login that gets no picker drawn.
        * **The login.** It is `writer(request)`: the signed session, and the same
          name that becomes the commit's author. A body that could name somebody
          would make this an impersonation the route then has to defend against;
          with no such field there is nothing to defend. That is also the answer
          to "may somebody set another person's icon": no. It is a personal mark,
          nobody else has a reason to choose it, and the version that admits an
          admin is the version that takes a login off the wire. Somebody with
          commit access edits the file, which is a first-class way to use this
          tool rather than a workaround.
        * **The value.** `render.ICONS` is the vocabulary and it is closed. An
          icon the page cannot draw is refused here rather than stored and drawn
          as nothing later, because a stored value nothing renders is the failure
          this codebase keeps having: empty must not look like broken.

        **One record per person is the whole design, and it is about the merge.**
        The first attempt wrote everybody's icon into `config/people.yaml` — the
        one writable path that would have been YAML end to end — and `store.write`
        merges a file as frontmatter key-by-key plus a *line* merge of the prose
        under it. Two edits nobody would call a disagreement therefore produced
        text that is not YAML, committed as `outcome: "merged"` with a 200, and
        took the roster and every icon down on every page at once, on a protected
        branch. Here the settings are the frontmatter, so the merge over them is
        the structured one and cannot make something the model will not read; and
        two people picking at the same moment write two different paths, where
        compare-and-swap is scoped, so there is no merge to get right. The
        concurrency is not handled. It is absent.

        The roster is not consulted. `known_people` is the validator's list, a
        name missing from it is a warning there and never a refusal, and the live
        plan's is empty on purpose — making it decide who may pick a picture would
        put a hand-maintained file on this write path and let an unreadable one
        decide it for everybody, which is exactly how the last version came to
        draw a picker for people it would then refuse.
        """
        user = writer(request)
        payload = await _sent(request)
        # An allowlist of one key, and a refusal that names what else arrived. A
        # request carrying `login` or `path` is a client written against the
        # endpoint this deliberately is not, and answering 200 while quietly
        # ignoring the extra field is how that client ships believing it works.
        extra = sorted(set(payload) - {"icon"})
        if extra:
            raise HTTPException(
                422, f"an icon request carries an icon and nothing else, not {', '.join(extra)}"
            )
        # `in`, not `.get`. An absent key is a client that never sent one, and
        # reading it as "clear my icon" makes a destructive default out of the
        # exact mistake the guard two lines above exists to catch:
        # `JSON.stringify({icon: someUndefinedVar})` is `{}`, which arrived here
        # as 200, `outcome: committed`, and somebody's icon gone. Clearing is a
        # thing you ask for — `{"icon": null}` — not a thing you fail to say.
        if "icon" not in payload:
            raise HTTPException(422, "an icon request carries an icon; send null to clear it")
        icon = payload["icon"]
        if icon is not None and icon not in render.ICONS:
            raise HTTPException(
                422, f"{icon!r} is not an icon: expected one of {', '.join(render.ICONS)}, "
                     "or null to clear it"
            )
        path = person_path(user.login)
        if path is None:
            raise HTTPException(
                422,
                f"{user.login!r} is not a name this plan can keep a file under; a login is "
                "1 to 39 letters, digits and hyphens, and does not start or end with one",
            )

        base = store.head()
        original = store.read(base, path)
        # A record already there and already broken is not written over: the write
        # would bury somebody's hand edit inside a commit that reads like a person
        # choosing a picture. Refused with the reason, which is what a reader needs
        # to fix it in git — and it costs one person's icon, because it is one
        # person's file.
        before, why = (
            _person_or_why(original, path)
            if original is not None
            else (Person(login=user.login), "")
        )
        if before is None:
            raise HTTPException(
                422,
                f"{path} does not read as a person right now, so nothing may be written "
                f"over it: {why}",
            )
        # Nothing to do is not a commit. Pressing the icon you already have, or
        # clearing one nobody set, would otherwise put a commit into the plan's
        # history that changes no byte anybody can see — and `git log` on a plan is
        # meant to be a record of decisions. A picker is a control people press
        # twice.
        if before.icon == icon:
            return JSONResponse(
                {"outcome": "unchanged", "commit": None, "conflict": None, "head": base}
            )

        # Only the one field travels, over a file that may have a body somebody
        # wrote in git: `patch_text` rewrites the frontmatter alone and hands the
        # prose back byte for byte. Through `_patched`, the same helper the record
        # and cycle saves use, because a file in git can be anything and an
        # unguarded `patch_text` over one is a ruamel error under the router — a
        # 500 whose body is plain text, which is the one answer the picker cannot
        # read back to say what happened.
        content = _patched(original or "---\n---\n", {"icon": icon}, None, path)
        candidate, why = _person_or_why(content, path)
        if candidate is None:
            raise HTTPException(422, f"that would not read back as a person: {why}")

        written = await asyncio.to_thread(
            store.write,
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{user.login}: {f'icon {icon}' if icon else 'no icon'}",
        )
        if written.commit:
            # Read back what LANDED, not what was offered. The check above is on
            # the candidate, and the candidate is not what is committed the moment
            # `store.write` merges — which is precisely where the last version of
            # this feature wrote a file no page could read afterwards, past a guard
            # that had already passed on text the merge then replaced. It costs one
            # tree read and it is the only check here that can see a merge.
            landed, why = _person_or_why(store.read(written.commit, path) or "", path)
            if landed is None:
                raise HTTPException(
                    500,
                    f"{path} was committed as {written.commit[:7]} and does not read back: "
                    f"{why} — fix it in git",
                )
            # No ids: nothing on any page is named `people/<login>.md`, so every
            # reader is told the plan moved rather than being told something they
            # are looking at did.
            await announce(written.commit, [])
        return _result(written, base)

    @app.post("/api/asset")
    async def upload(request: Request) -> JSONResponse:
        """Raw bytes with a content-type header, not a multipart form.

        Multipart would mean another dependency for a request that carries one
        file and nothing else, and `fetch` posts a File object as a raw body
        without any help.
        """
        user = writer(request)
        kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if kind not in IMAGE_TYPES:
            raise HTTPException(415, f"images only: {', '.join(sorted(IMAGE_TYPES))}")
        data = await request.body()
        if not data:
            raise HTTPException(422, "that file is empty")
        if len(data) > MAX_ASSET_BYTES:
            raise HTTPException(
                413, f"that image is {len(data) // 1024} KB; the limit is "
                     f"{MAX_ASSET_BYTES // 1024} KB"
            )
        path, fresh = await asyncio.to_thread(store.put_asset, data, IMAGE_TYPES[kind], user.login)
        # The sha goes back to the uploader as well as out to everybody else. The
        # shell's banner suppresses news of a commit the tab made itself, and it
        # can only do that if the request that made it hands the sha back — an
        # upload that only announced popped "The plan changed." over its own paste.
        commit = store.head()
        if fresh:
            await announce(commit, [])
        return JSONResponse(
            {"path": path, "url": f"/{path}", "fresh": fresh, "commit": commit}
        )

    @app.get("/assets/{name}")
    def asset(name: str) -> Response:
        if not ASSET_PATTERN.match(name):
            raise HTTPException(404, "no such asset")
        data = store.read_asset(store.head(), f"assets/{name}")
        if data is None:
            raise HTTPException(404, "no such asset")
        suffix = "." + name.rsplit(".", 1)[-1]
        return Response(
            data,
            media_type=next(k for k, v in IMAGE_TYPES.items() if v == suffix),
            # The name IS the hash of the contents, so this bytes-for-bytes
            # cannot change under a cache.
            headers={"cache-control": "public, max-age=31536000, immutable"},
        )

    @app.post("/api/record")
    async def create(request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        fields = _fields_in(payload)
        body = _body_in(payload) or ""

        kind = fields.get("kind")
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        # The same door as the save beside it. Create had no type check at all,
        # so every value the save route refuses could be created instead — the
        # closed writable surface is only closed if both ways in are.
        _reject_bad_types(fields)
        # Before `validate_all` gets a say: the vocabulary refusal arrives as
        # one sentence naming the field — the same sentence PATCH and the room
        # give — rather than as a problems list that happens to mention it.
        _reject_bad_status(kind, fields)

        # A pitch has an appetite and a task has an effort. The create page carries
        # every kind's fields and hides the ones that do not apply, so what belongs
        # to this kind is decided here rather than by which controls a script left
        # visible: fields are written to the file before the model ever sees them,
        # and a key the model does not own would sit in the frontmatter unread.
        allowed = set(MODELS[kind].model_fields)
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise HTTPException(422, f"{_an(kind)} has no {', '.join(unknown)}")

        # Minted here, never accepted from the client: an id supplied by a browser
        # is a path supplied by a browser once it becomes `tasks/<id>.md`.
        record_id = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        commit = store.head()
        config, _ = _config_at(store, commit)
        fields["id"] = record_id
        # The defaults the deleted inbox routes used to supply. `author` is a
        # default and not a fact — somebody files what a colleague mentioned in
        # a corridor, so the form can say otherwise — but the date is written
        # last, over anything the client sent, exactly as the old routes
        # stripped it: `opened_on` and `written_on` are derived rows on the
        # page, and a client that sends one is overruled, not obeyed.
        inbox = INBOXES.get(kind)
        if inbox is not None:
            fields.setdefault(inbox.author, user.login)
            fields.setdefault("status", inbox.opens)
            fields[inbox.dated] = date.today().isoformat()
        # Grandfathering protects the corpus that already exists, not the record
        # being written right now: something created today is held to today's rules.
        fields.setdefault("created_schema_version", config.schema_version)
        content = patch_text("---\n---\n", fields, body)
        # The same refusal the save route makes, on the other door. `_reject_bad_types`
        # names numbers, lists and one bool; a title that is a number, a date that is
        # a word, a tag that is null and a reviewer that is an integer all passed it
        # and raised here as a bare ValidationError — a 500 whose body is plain text,
        # which is the one answer the create form cannot read back to say what was
        # wrong. Nothing was committed either way, so what this changes is whether the
        # person is told which field it was.
        try:
            candidate = parse_text(content, record_id)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a record: {why_it_will_not_read(error)}"
            ) from None
        problems = [
            p
            # A file already in the plan that will not parse is not this record's
            # problem and must not stop it being created: the validator only
            # needs the neighbours it can read, and the banner is what says the
            # rest are missing.
            for p in validate_all([*_records_at(store, commit)[0], candidate], config)
            if p.record_id == record_id and p.severity == "blocker"
        ]
        if problems:
            return JSONResponse(
                {"problems": [p.model_dump(mode="json") for p in problems]}, status_code=422
            )

        written = await asyncio.to_thread(
            store.write,
            path=f"{DIRECTORY[kind]}/{record_id}.md",
            content=content,
            # A base is optional here — a create has nothing to be stale against
            # — but one that was sent has to be real, because `store.write` reads
            # at it the moment HEAD has moved, which is exactly when a person
            # with an old tab open presses New.
            base_commit=_base_in(store, payload) if payload.get("base_commit") else commit,
            author=user.login,
            message=f"{record_id}: create",
        )
        if written.commit:
            await announce(written.commit, [record_id])
        if written.outcome == "conflict":
            return _result(written, commit)
        return JSONResponse(
            {"id": record_id, "outcome": written.outcome, "commit": written.commit},
            status_code=201,
        )

    # -- events -------------------------------------------------------------

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        """Server-Sent Events, not WebSockets: the traffic is one way, it survives
        a proxy that has never heard of an upgrade handshake, and the browser
        reconnects on its own."""
        queue: asyncio.Queue = asyncio.Queue()
        watchers.add(queue)

        async def stream():
            try:
                # A comment, not an event: it flushes the headers so a client knows
                # the stream is live, without looking like something happened.
                yield b": connected\n\n"
                waited = 0.0
                while not closing.is_set():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1)
                    except TimeoutError:
                        # A short wait so a shutdown is noticed in about a second,
                        # but a keepalive only every fifteen: the wakeup is for us,
                        # the bytes are for the client.
                        waited += 1
                        if waited >= 15:
                            waited = 0
                            yield b": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n".encode()
            finally:
                watchers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # -- co-editing ---------------------------------------------------------
    #
    # A socket, and not the event stream beside it, because this traffic goes
    # both ways: the stream exists to tell a page that the plan moved, and it
    # can only ever do that. `connect-src 'self'` already permits the `ws`/`wss`
    # variant of the page's own origin — CSP 3 matches the scheme by
    # upgrade-equivalence rather than by spelling — so the policy is untouched,
    # and `tests/browser.py` asks a real browser rather than trusting the
    # sentence you just read.
    #
    # A room is a way of arriving at a commit, never a replacement for one.
    # Everything below ends in exactly one `store.write`, against the room's
    # base, with a person as the author — so somebody editing in git, in a
    # second tab, or through the API is still handled by the same three-way
    # merge, and a genuine overlap still comes back as the same refusal.

    rooms = coedit.Rooms()
    # The outbox per connection, kept out of `Room` so `coedit.py` has nothing to
    # say about transport and can be tested without one.
    outboxes: dict[int, Outbox] = {}
    watching: dict[str, asyncio.Task] = {}
    connections = 0

    def _b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    def _raw(value: object) -> bytes | None:
        """Base64 off the wire, or None. Never an exception: a frame this cannot
        decode is one client's mistake and must not close anybody else's room.

        Bounded before decoding, on the string, because the string is what this
        process is holding while it decides — and bounded at what
        `MAX_UPDATE_BYTES` actually encodes to (four characters per three bytes)
        rather than at a round multiple, so raising the frame ceiling raises the
        memory the ceiling admits by the same amount and not by more.
        """
        if not isinstance(value, str) or len(value) > (MAX_UPDATE_BYTES + 2) // 3 * 4 + 4:
            return None
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return None

    def _to(connection: int, message: dict) -> None:
        """One frame to one member, queued. Never blocks, never raises."""
        outbox = outboxes.get(connection)
        if outbox is not None:
            outbox.offer(json.dumps(message))

    def _to_room(room: coedit.Room, message: dict, skip: int | None = None) -> None:
        """One frame to everybody in the room. Synchronous, and that is the point.

        This awaited `socket.send_json` per member in turn, with no timeout and
        no isolation. uvicorn's websocket send begins `await
        self.writable.wait()`, and asyncio clears that event whenever a
        transport's buffer fills — so one member who stopped draining (a closed
        lid, a tunnel, a proxy holding the response) suspended the broadcast, and
        with it *every other member's* update handler and the `_watch` timer,
        which reaches the same await through `_commit_room`. Measured against a
        real uvicorn server with three real sockets: after ann's socket stopped
        accepting writes, bo received nothing further, commits stopped, ann's
        sentence reached neither bo's document nor git, and the last-person-out
        commit did not fire either — while `/healthz` and every page went on
        answering 200, so nothing anywhere said the room was gone.

        So a broadcast puts bytes in a queue and returns. There is no `await` in
        here at all, which is what makes "one slow socket cannot reach another
        member's handler or the timer" a fact about the shape of this function
        rather than a promise about how long a send takes.

        Serialised once for the room rather than once per member, because
        `send_json` is `json.dumps` and this frame is the same frame for
        everybody.
        """
        frame = json.dumps(message)
        dropped = []
        for connection in list(room.members):
            if connection == skip:
                continue
            outbox = outboxes.get(connection)
            if outbox is None:
                continue
            if not outbox.offer(frame):
                dropped.append(connection)
        for connection in dropped:
            # Out of the room at once, so the people still typing stop waiting on
            # somebody who is a megabyte behind, and so the presence list stops
            # naming them. Their socket keeps its `reload` queued: they get it if
            # they ever drain, and their own handler tidies up either way.
            rooms.exit(room, connection)
        if dropped:
            # One pass and deliberately not a recursive `_to_room`: an eviction
            # here would cascade, and the next thing anybody does broadcasts the
            # roster again anyway.
            for connection in list(room.members):
                if (outbox := outboxes.get(connection)) is not None:
                    outbox.offer(
                        json.dumps(
                            {"t": "who", "people": room.people(), "where": room.where()}
                        )
                    )

    def _body_at(commit: str, path: str) -> str:
        """The body as the editor shows it, which is not the bytes after the
        frontmatter.

        `parse_text` drops the blank line a closing `---` leaves behind, and the
        detail page renders what `parse_text` returned — so a room seeded from
        the raw split opened one character different from the textarea it was
        drawn beside. Every editor said "1 unsaved change" before anybody typed,
        and twenty seconds later the room committed that character. The room and
        the page have to be looking at the same text or the room is arguing with
        the page it is on.
        """
        text = store.read(commit, path) or ""
        try:
            return parse_text(text, path).body
        except ValueError:
            # A file in git can be anything, and a room over one that is not a
            # record goes nowhere — the gate in `_commit_room` refuses it. But it
            # must not fail here, where there is nobody yet to tell.
            return split_front_matter(text)[1]

    async def _commit_room(
        room: coedit.Room, presser: str = "", fields: dict | None = None
    ) -> None:
        """One `store.write` for everything the room has typed since the last one.

        Fires on Save, on the last participant leaving, and after twenty seconds
        of quiet. The people in it are computed rather than declared — see
        `Room.credits`.

        The path is the room's, resolved once when it opened, and is deliberately
        not re-derived here. `PATCH /api/record` refuses when two files claim one
        id because it cannot know which record the page had shown; a room does
        know — it is holding that record's text — so a second claimant appearing
        in git mid-session is a blocker the pages draw, not a reason to strand
        everybody typing.

        **This never raises for a write that failed.** A timer task that dies
        takes the quiet window with it for as long as the room lives, and the
        only symptom is that nothing is committed any more. Every failure leaves
        by the same door instead: `refused`, into the room's own box, said to
        everybody in it. `_watch` guards itself as well, and the two are not the
        same guard — see the note there.

        **Nothing typed while this is running may be deleted.** Between the
        snapshot below and `room.settled` at the bottom there is no `await`, so
        no other coroutine can put a keystroke in the room that this would then
        take back out. That used to be a claim about `store.write` being
        synchronous while a broadcast sat in the middle of the same stretch: the
        snapshot was taken, `await _to_room(room, {"t": "saving"})` suspended on
        whichever member was slowest, another socket's handler applied a
        keystroke to the room while it waited, and `absorb` then forced the room
        back to the file — deleting that keystroke from every open document and,
        through the `saved` handler, from `localStorage` too. `_to_room` does not
        suspend any more, and `test_a_commit_never_deletes_what_was_typed_during_it`
        holds this function to having no `await` in that stretch.
        """
        fields = fields or {}
        author, others = room.credits(presser)
        if not author or (not fields and not room.pending()):
            # A Save with nothing to commit is still a Save, and it has to be
            # answered. `COEDIT.save()` has already said "saving…" and dispatched
            # `openproj:writing`, and the shell holds every "somebody else
            # changed this" banner until the matching `openproj:wrote` — so
            # returning in silence left that counter above zero for the life of
            # the page and no banner was ever drawn again. `onclose` puts it back
            # in five minutes on Cloud Run and never on a server with no request
            # deadline. The path without a room says "nothing changed" and stops;
            # this is the same sentence, and only when somebody pressed the
            # button, because the quiet window and the last person out are owed
            # nothing.
            if presser:
                _to_room(room, {"t": "nothing"})
            return
        try:
            # Said before the write, and before the snapshot. A commit is
            # announced to the event stream before the request that made it is
            # answered, so the shell's "somebody else changed this" banner has to
            # know a write is in the air first — otherwise the room's own commit
            # arrives as news that a stranger moved the plan.
            _to_room(room, {"t": "saving"})
            # The snapshot, taken after the last thing above it that could ever
            # have suspended, and read once. Everything from here to `absorb` is
            # one synchronous run of this coroutine; see the docstring.
            body = room.body()
            # The same ceiling `_body_in` holds a PATCH to. A room has no other:
            # every frame is bounded, and a document is unbounded exactly because
            # it is the sum of them.
            if len(body.encode("utf-8")) > MAX_BODY_BYTES:
                raise ValueError("this document is too large to commit")
            original = store.read(room.base, room.path)
            if original is None:
                # Said with what to do about it. A room's text lives in no
                # `localStorage` but the typist's own — everybody else's copy
                # arrived over the socket and was never an `input` event — so
                # "this is gone" without "copy it out" is an instruction to lose
                # the document, and this refusal repeats every twenty seconds
                # until somebody acts on it.
                raise ValueError(
                    f"{room.path} is not in the plan any more, so there is nothing to "
                    "write this against. Copy the document out of the editor before "
                    "closing this tab — the room is the only place it exists."
                )
            content = _patched(original, fields, body, room.path)
            # The same gate the PATCH route stands behind, and for the same
            # reason: a record that will not read back takes every page down for
            # everybody, on a branch where the commit cannot be force-pushed away.
            parse_text(content, room.path)

            message = f"{room.record_id}: {_named(fields, RECORD_FIELDS) or 'body'}"
            if others:
                # The trailer git itself reads. `store._commit` puts the author
                # in the author field, so `git log --format='%an'` is unchanged
                # and `git shortlog` sees both halves.
                trailers = "\n".join(
                    f"Co-authored-by: {login} <{login}@users.noreply.github.com>"
                    for login in others
                )
                message = f"{message}\n\n{trailers}"
            # Inside the try, which is the whole of this change: the write is
            # what actually fails, and it was the one step standing outside the
            # net. Everything after it only reports.
            # NOT on a thread, alone among the twelve writers, and the test
            # `test_a_commit_never_deletes_what_was_typed_during_it_by_construction`
            # is what says so. Between the snapshot this is committing and
            # `room.settled` below, the room must not suspend: anything typed
            # during a suspension is in the room and not in the snapshot, and the
            # absorb then deletes it from every open document. An `await` here is
            # exactly that suspension.
            #
            # So this one still blocks the event loop for the length of a push.
            # It is the rarest of the writers — a room commits when somebody
            # presses Save, or after twenty seconds of quiet, not per keystroke —
            # and buying the thread would mean making the absorb tolerant of text
            # that arrived mid-commit, which is a change to the co-editing
            # invariant rather than to where a call runs.
            written = store.write(
                path=room.path,
                content=content,
                base_commit=room.base,
                author=author,
                message=message,
            )
            if written.outcome == "conflict":
                # Into the room's own box, never into the editing surface: text
                # pasted into a textarea is text somebody saves back. The room
                # keeps the base it had and tries again once the text moves.
                room.refusal = written.conflict
                _to_room(room, {"t": "refused", "why": written.conflict})
                return
            # Whatever actually landed, which is not what was sent when `_merge`
            # folded in somebody's git commit. Applied back into the document so
            # the room sees their paragraph arrive as text rather than diverging
            # from the file.
            landed = _body_at(written.commit, room.path)
            # Only when the write changed something. `absorb` makes the room's
            # text *be* the text it is given, which is right on the join path
            # where the room is settled and wrong here the instant the room holds
            # anything the snapshot did not: it would delete it and broadcast the
            # deletion. The ordinary write changes nothing — `_body_at` reads back
            # exactly what went in — so the ordinary write now touches no
            # document at all, and this stays a comparison rather than a claim
            # about which coroutine ran when.
            update = room.absorb(landed) if landed != body else None
            # `landed`, which is what is in the file, and never `room.body()`,
            # which is what the room happens to be holding. The two are the same
            # in every ordinary case and they were the same line for that reason
            # — and when they differ, `room.body()` is the room telling itself
            # that a sentence it has never written is already in git. `pending()`
            # is that comparison, so believing it stops the quiet window
            # altogether: measured over real sockets, a sentence typed during a
            # save sat in the room for ever and no commit was ever made for it.
            room.settled(written.commit, landed)
            # Inside the try, with the write. These only report, but a report
            # that raises kills the caller just as thoroughly as a write that
            # does: `absorb` crosses two index spaces, `announce` writes to every
            # open event stream, and an escape from either used to take `_watch`
            # with it and stop every commit in the room for as long as it lived.
            _to_room(
                room,
                {
                    "t": "saved",
                    "commit": written.commit,
                    "outcome": written.outcome,
                    "pushed": written.pushed,
                    "update": _b64(update) if update else None,
                },
            )
            await announce(written.commit, [room.record_id])
        except WRITE_FAILURES as error:
            # Everything a write is documented to fail with, said in its own
            # words — see `WRITE_FAILURES`. The arm below catches the rest; this
            # one exists because these are the failures a person can act on, and
            # "another writer has the lock" is a different sentence from "this
            # broke".
            why = error.detail if isinstance(error, HTTPException) else str(error)
            room.refusal = why
            _to_room(room, {"t": "refused", "why": why})
        except Exception as error:  # noqa: BLE001 - see the docstring: this may not raise
            # A denylist is right where the failures can be named and the name is
            # what the reader needs; this file argues for that everywhere else and
            # `WRITE_FAILURES` above is one. It is wrong *here*, because what an
            # escape costs is not one bad message — it is the timer task, and a
            # dead timer has exactly one symptom, which is that nothing is
            # committed any more and nothing anywhere says so. So the tuple keeps
            # the sentences it can write and this keeps the promise, and the class
            # name goes out with it rather than a shrug.
            why = f"that save did not go through: {type(error).__name__}: {error}"
            room.refusal = why
            _to_room(room, {"t": "refused", "why": why})

    async def _watch(room: coedit.Room) -> None:
        """The quiet window, and the last second before a shutdown.

        One task per occupied room rather than one for all of them: it starts
        when somebody arrives and ends when the room empties, so a process that
        nobody is editing on holds no timers, and a test that opens a socket does
        not leave one running after it.

        **The tick is guarded, and it is a different guard from `_commit_room`'s.**
        That one promises "a save never raises" and writes a sentence about the
        save. This one promises "the timer outlives anything", including the
        things that are not the save: `room.pending()` walks the document,
        `closing.is_set()` is an event this process shares with the shutdown
        hook, and either can be the line that ends the task. A dead timer is
        silent — no exception reaches a request, no page changes, `/healthz` goes
        on answering — and what it costs is every commit this room would have
        made for as long as somebody has the tab open.

        **And it commits on the way out.** The last-person-out commit lives in
        the leaving socket's `finally`, which asks `room.empty()` and *then*
        broadcasts the roster — and that broadcast is what evicts a member who
        has stopped reading. So the room emptied one line after the commit was
        skipped, this loop fell through on its next tick with the text still in
        the room, and `rooms.sweep()` dropped it seven minutes later. Nothing
        rescued it: uvicorn cannot get a keepalive ping down a wedged socket, so
        the 40-second ping timeout never fired either. This is here rather than
        beside the eviction because it covers every route to an empty room, and
        because text that was acknowledged must never be silently discarded.
        """
        while room.members:
            await asyncio.sleep(1)
            try:
                if closing.is_set():
                    # The floor the design promises is the debounce window, and
                    # this is the second that gets most of it back. Same hook the
                    # event stream uses — uvicorn's exit fires it before it waits.
                    if room.pending():
                        await _commit_room(room)
                    return
                if room.pending() and room.quiet_for() >= coedit.QUIET_SECONDS:
                    # Not gated on `room.refusal`. Only `Room.apply` cleared it,
                    # so a `StoreLocked` — another writer, which is ordinary and
                    # transient — stopped the quiet window until somebody typed
                    # again, and a room whose typists had all stopped never got
                    # its text into git at all. The design promises a retry on the
                    # next window, and `tried()` is what makes it the *next* one
                    # rather than every second from here on.
                    await _commit_room(room)
                    room.tried()
            except Exception:  # noqa: BLE001 - the timer outlives anything; see the docstring
                continue
        # Guarded like the tick above and for the same reason: `pending()` walks
        # the document, and an escape here is the last chance this room had.
        with contextlib.suppress(Exception):
            if room.pending():
                await _commit_room(room)

    @app.websocket("/api/coedit/{record_id}")
    async def coedit_socket(socket: WebSocket, record_id: str) -> None:
        nonlocal connections
        # `writer` and not a second reading of the session. It reads one thing
        # off what it is handed — the cookies — and a WebSocket has them under
        # the same name, so it is handed the socket. Two spellings of "who may
        # write" is how a page comes to offer a control whose only answer is a
        # refusal, and this is the control that has to agree with `PATCH
        # /api/record` exactly: the room writes through the same gate.
        try:
            user = writer(socket)  # type: ignore[arg-type]
            head = store.head()
            path = _path_for(store, head, record_id)
        except HTTPException:
            # Not signed in, not a member, no such record, or two files claiming
            # one id. Refused before the handshake, which the browser sees as a
            # socket that would not open — and a socket that would not open is
            # the case this whole feature is designed to degrade into, so a
            # reader who may not write gets exactly today's editor.
            path = None
        if path is None:
            await socket.close(code=1008)
            return

        await socket.accept()
        connections += 1
        connection = connections
        room = rooms.get(record_id)
        if room is None:
            room = rooms.add(coedit.Room(record_id, path, head, _body_at(head, path)))
        elif not room.pending():
            # A room kept warm through a disconnection can have been overtaken by
            # a commit made in git or through the API. Folded in here while there
            # is nothing of anybody's to lose; when there is, the three-way merge
            # in `store.write` does it at the next commit instead.
            arriving = room.absorb(_body_at(head, path))
            room.settled(head, room.body())
            if arriving:
                # Said here, to the people already in the room, and not after
                # this socket's welcome — because it is not this socket's news
                # and does not depend on it. It used to be broadcast below, past
                # `await socket.receive_json()` and past the `return` that
                # answers a stale seed, so a tab that was correctly told to
                # reload took a colleague's `git push` with it on the way out.
                # Not self-correcting either: `settled` above means the next
                # write sees `landed == body` and broadcasts nothing, so the room
                # went on to commit a line no client had ever been shown, and the
                # room and the person reading it disagreed permanently with
                # nothing said. The joiner needs no copy — the absorb is already
                # in the document its welcome is composed from.
                _to_room(room, {"t": "update", "u": _b64(arriving)})

        # Last, and immediately before the `try` that will tidy it up, because
        # this is a task and a registry entry: anything between the two is a line
        # that can raise and leave both behind. And before anything writes to
        # this socket, because from here on *nothing* writes to it directly. One
        # writer per connection is what makes a broadcast unable to block — see
        # `Outbox` and `_to_room` — and a second path sending straight down the
        # socket would be a second place a slow member could stop the process,
        # which is the defect this replaced.
        outbox = Outbox(socket)
        outboxes[connection] = outbox
        posting = asyncio.create_task(outbox.drain())

        try:
            hello = await socket.receive_json()
            if not isinstance(hello, dict):
                raise ValueError("a hello is a JSON object")
            # The seed, not the base. Two documents built independently from the
            # same text share no history and merge into that text *twice*, so a
            # returning client whose document was seeded from a different commit
            # is answered with a reload rather than with a merge. The base moves
            # every time the room commits; the seed does not, which is what lets
            # somebody reconnect through Cloud Run's five-minute teardown without
            # noticing it happened.
            seed = hello.get("seed")
            if isinstance(seed, str) and seed != room.seed:
                outbox.offer(
                    json.dumps(
                        {
                            "t": "reload",
                            "why": "this document was rebuilt on the server while you were "
                            "away — reload the page to join the room again",
                        }
                    )
                )
                return
            # Composed, then joined, then sent, with no `await` between the first
            # two. This socket used to be in `sockets` from the moment it was
            # accepted, so a second tab could be handed somebody else's `update`
            # *before* its welcome: the frame landed on a document that had not
            # been seeded yet, and the welcome then found a document that no
            # longer matched what the server had rendered into the page — which
            # is the test a restored draft is judged by, so a clean merge came
            # back as the conflict report instead. Joining after the frame is
            # built and before it is sent is the only order with no gap in it:
            # anything applied to the room earlier is inside this update, and
            # anything applied later is broadcast to a socket that is already
            # listed, behind bytes that are already queued. The queue keeps that
            # order for free: the welcome is put in it before the room is joined,
            # so it is in front of every frame a broadcast can add.
            welcome = {
                "t": "welcome",
                "seed": room.seed,
                "base": room.base,
                "you": user.login,
                "sv": _b64(room.state()),
                "update": _b64(room.since(_raw(hello.get("sv")))),
            }
            outbox.offer(json.dumps(welcome))
            rooms.enter(room, connection, user.login)
            _to_room(room, {"t": "who", "people": room.people(), "where": room.where()})
            if room.refusal:
                _to(connection, {"t": "refused", "why": room.refusal})

            if watching.get(record_id) is None or watching[record_id].done():
                watching[record_id] = asyncio.create_task(_watch(room))

            checked = time.monotonic()
            while True:
                message = await socket.receive_json()
                if outbox.overrun:
                    # Given up on by the room while this was waiting: they are a
                    # whole document behind and the `reload` is already queued.
                    # Leaving here rather than at the next broadcast is what stops
                    # a tab that came back to life typing into a room that has
                    # stopped listening to it.
                    return
                if time.monotonic() - checked >= RECHECK_SECONDS:
                    # Who this socket is, asked again, because a socket outlives
                    # the answer it was opened with. `writer` was run once at the
                    # handshake and never after, so a sign-out or a revoked
                    # membership went on writing commits under that login for as
                    # long as the tab stayed open — and a socket outlives even the
                    # 24 hours the cookie is good for, which is the whole of what
                    # it adds to the HTTP side. The same `writer`, on the same
                    # cookies, so there is exactly one spelling of who may write.
                    try:
                        user = writer(socket)  # type: ignore[arg-type]
                    except HTTPException as refused:
                        _to(connection, {"t": "reload", "why": refused.detail})
                        return
                    checked = time.monotonic()
                if not isinstance(message, dict):
                    continue
                kind = message.get("t")
                if kind == "update":
                    update = _raw(message.get("u"))
                    if update is None or len(update) > MAX_UPDATE_BYTES:
                        # Not `continue`. A frame the room did not take is an
                        # edit this tab made and the room did not, so the two can
                        # never converge again — and this said nothing at all. A
                        # 263 kB paste produced no frame back, the quiet window
                        # committed the text from before it, and a Save beside it
                        # then answered `saved`, moved `ORIGINAL_BODY` to the
                        # room's stale text and dropped the draft, so the paste
                        # existed in one textarea and died with the tab. Answered
                        # the way an update that will not apply is answered,
                        # because it is the same condition: two copies that
                        # cannot converge.
                        _to(
                            connection,
                            {
                                "t": "reload",
                                "why": "this tab sent a change the room could not take, so "
                                "it has left the room. Nothing in this tab is lost: Save "
                                "writes the whole document, the way it did before rooms "
                                "existed.",
                            },
                        )
                        return
                    try:
                        room.apply(update, user.login)
                    except Exception:  # noqa: BLE001 - anything at all off a socket
                        # An update this document cannot read leaves the two
                        # copies unable to converge, and the only honest answer to
                        # that is to start again from the file.
                        _to(
                            connection,
                            {
                                "t": "reload",
                                "why": "this tab and the server stopped agreeing about "
                                "the document — reload the page",
                            },
                        )
                        return
                    _to_room(room, {"t": "update", "u": message["u"]}, skip=connection)
                elif kind == "at":
                    # Where this tab's caret is, relayed to the rest of the room.
                    # An `int()` and a bound, because it arrives off a socket and
                    # is drawn into a position: a float would be a NaN in
                    # somebody else's arithmetic, and an unbounded one is a band
                    # measured a million lines down.
                    try:
                        at = int(message.get("at"))
                    except (TypeError, ValueError):
                        continue
                    if not 0 <= at <= MAX_BODY_BYTES:
                        continue
                    room.sits(connection, at)
                    # To everybody else, not to the room: a tab does not need its
                    # own caret told back to it, and this frame is sent on every
                    # line somebody moves to.
                    _to_room(
                        room,
                        {"t": "who", "people": room.people(), "where": room.where()},
                        skip=connection,
                    )
                elif kind == "save":
                    fields = message.get("fields")
                    fields = dict(fields) if isinstance(fields, dict) else {}
                    fields.pop("id", None)
                    try:
                        _reject_bad_types(fields)
                        # The room writes through the same gate as PATCH — the
                        # comment on `writer` above says exactly that — so the
                        # vocabulary stands here too.
                        _reject_bad_status(_kind_for(record_id), fields)
                    except HTTPException as refused:
                        _to(connection, {"t": "refused", "why": refused.detail})
                        continue
                    await _commit_room(room, presser=user.login, fields=fields)
        except (WebSocketDisconnect, ValueError, KeyError, RuntimeError):
            # Every way a socket ends: closed politely, closed rudely, or handed
            # a frame that is not the JSON this speaks.
            pass
        finally:
            # The room first, and the flush after it. Everything here that anybody
            # else in the room is waiting on — the last-person-out commit, the
            # presence list — happens before this socket is given a single further
            # chance to be slow, so a member whose connection is wedged cannot
            # delay the commit their own departure triggers.
            outboxes.pop(connection, None)
            rooms.exit(room, connection)
            if room.empty():
                # The last person out commits, so a room that nobody comes back to
                # has already put its work in git — the twenty-second window is
                # the floor for a crash, not for leaving.
                with contextlib.suppress(Exception):
                    await _commit_room(room)
                # Cancelled rather than left to notice on its next tick: a timer
                # outliving the last socket is a task still pending when the loop
                # closes, which is a warning in every test that opens one.
                task = watching.pop(record_id, None)
                if task is not None:
                    task.cancel()
            else:
                _to_room(room, {"t": "who", "people": room.people(), "where": room.where()})
            rooms.sweep()
            # Now, and bounded. A `reload` or a refusal is the last thing several
            # of the paths above say, and cancelling the writer the instant they
            # said it would mean nobody ever heard it — while waiting for a socket
            # that will never drain would leave this task pending for ever.
            await outbox.flushed(FLUSH_SECONDS)
            posting.cancel()
            with contextlib.suppress(Exception):
                await socket.close()

    # -- sign in ------------------------------------------------------------

    @app.get("/api/me")
    def me(request: Request) -> JSONResponse:
        """Who the session says you are, for the corner of the nav.

        `{}` and 200 for a stranger, not 401. Every page here is readable signed
        out, so the signed-out answer is the ordinary one — and answering it with
        an error puts a red line in the console of a page that is working exactly
        as designed, which is how a real error comes to be ignored.

        The org travels with the answer because the page has no other way to name
        it: "not a member" is only useful when it says of what.
        """
        who = viewer(request)
        if who is None:
            return JSONResponse({"org": org})
        return JSONResponse({"login": who.login, "member": who.member, "org": org})

    @app.get("/login")
    def login(request: Request) -> RedirectResponse:
        state = secrets.token_urlsafe(32)
        redirect_uri = str(request.url_for("callback"))
        response = RedirectResponse(login_url(client_id, redirect_uri, state))
        # SameSite=Lax, not Strict: the callback is a top-level cross-site GET, and
        # Strict would drop this cookie so every login would fail state validation.
        response.set_cookie(
            STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", path="/"
        )
        return response

    @app.get("/auth/callback", name="callback")
    async def callback(request: Request) -> Response:
        expected = request.cookies.get(STATE_COOKIE)
        given = request.query_params.get("state")
        if not expected or not given or not secrets.compare_digest(expected, given):
            raise HTTPException(400, "that sign-in did not start here")

        # GitHub sends the browser back here when somebody clicks Cancel too, with
        # `error` in the query and no code at all. Left to fall through, that is
        # an exchange that fails and a bare "Internal Server Error" in front of
        # the one person who now cannot tell a refusal they chose from a tool
        # that is broken. `OAuthError` already carries GitHub's own wording.
        denied = request.query_params.get("error")
        if denied:
            raise HTTPException(
                400,
                f"GitHub did not authorise this sign-in ({denied}): "
                + request.query_params.get("error_description", "no description given"),
            )

        async with httpx.AsyncClient() as client:
            try:
                token = await exchange_code(
                    request.query_params.get("code", ""), client_id, client_secret, client
                )
                user = await identify(token, org, client)
            except OAuthError as exc:
                raise HTTPException(400, str(exc)) from exc
        # The token established who they are and is now dropped: it is never
        # written to the session and never used to push.
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            session_name(request),
            sign_session(user, secret),
            max_age=86400,
            httponly=True,
            secure=secure_for(request),
            samesite="lax",
            path="/",
        )
        response.delete_cookie(STATE_COOKIE, path="/")
        return response

    @app.post("/logout")
    def logout(request: Request) -> Response:
        response = RedirectResponse("/", status_code=303)
        # A __Host- cookie is only matched when Secure and Path=/ agree, so a
        # deletion that disagrees leaves the session quietly in place.
        response.delete_cookie(
            session_name(request),
            path="/",
            secure=secure_for(request),
            httponly=True,
            samesite="lax",
        )
        return response

    return app
