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
number, `assets/<sha>` by the hash of the bytes, `people/<login>.md` by
`model.LOGIN_PATTERN` (see `PUT /api/icon`), and `drawings/<drawing id>.png` by
`DRAWING_PATTERN`. No route takes a path, a directory
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
import functools
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
import pygit2
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from . import __version__, coedit, render, vendor
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
    DATED_FIELDS,
    DIRECTORY,
    ID_PATTERN,
    INBOXES,
    KIND_NAMES,
    KINDS,
    MAX_BODY_BYTES,
    MAX_SLIDE_BYTES,
    PEOPLE_DIR,
    RUNG,
    Config,
    Cycle,
    Person,
    Record,
    Slide,
    Unreadable,
    _an,
    edited_by_id,
    ends_before_it_starts,
    in_model_order,
    loop_made,
    mint_id,
    named,
    opening_fields,
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
    start_date_has_passed,
    unknown_fields,
    unread_fields,
    validate_all,
    weeks_outside_every_cycle,
    what_json_can_carry,
    why_it_will_not_read,
)
from .pusher import Pusher
from .store import (
    Condition,
    Store,
    StoreDiverged,
    StoreLocked,
    StoreSwamped,
    SyncOutcome,
    swamped,
)

# What a write can fail with, as one name so the two callers of `store.write`
# cannot disagree about it. `StoreLocked` and `StoreDiverged` are `RuntimeError`s
# and `_commit` goes through pygit2, which raises `GitError`; a net woven from
# `(HTTPException, ValueError)` alone therefore let three of the five past it. A
# tuple and not `Exception`, because `readable` (`model.py`) is the one place in
# this codebase that catches everything, and everywhere else the list of what has
# actually been seen is the honest one.
#
# "So the two callers cannot disagree" was the intent and was not yet the fact:
# for a long time this tuple was caught in exactly one place, the co-editing
# socket, and `grep -c exception_handler web.py` answered 0. The HTTP half caught
# nothing, and the same raise that the room turned into a sentence turned into a
# bare 500 on every page. Both halves catch it now — `_write_or_refuse` below,
# and `_commit_room` — and neither has a list of its own.
WRITE_FAILURES = (
    HTTPException,
    ValueError,
    StoreLocked,
    StoreDiverged,
    StoreSwamped,
    pygit2.GitError,
)


# The middle of a whole-store refusal — true of BOTH conditions that close the
# store, the fork and the pile, and written once so the two 503s below stay one
# vocabulary: what may differ between them is only what clears the condition.
_WHOLE_PLAN = (
    " — nothing was written, and this is the whole plan rather than this "
    "one record. Every save will be refused until "
)

# The first log line in this package, and the argument for there being one at
# all. Everything the server has had to say so far had a person to say it to —
# a refusal on the page, a sentence in a socket frame — or a health surface:
# `_wedged` below reaches an operator through `/api/health`. A refused co-editing
# room has neither reader. Every page answers 200 while it is stuck, `/api/health`
# asks the store and the store is fine — it did its job by refusing — and the
# people in the room are shown a sentence only they can act on. The server's own
# output is the one surface an operator actually watches, so that is where the
# operator's half of a room refusal goes. WARNING through a named stdlib logger,
# with no configuration on purpose: `logging`'s last-resort handler already puts
# WARNING and above on stderr, which is what Cloud Run collects, and a deployment
# that does configure logging can route `openproj.web` without this file knowing.
_LOG = logging.getLogger(__name__)


def _refusal(error: Exception) -> HTTPException:
    """One member of `WRITE_FAILURES`, as the answer a person gets.

    The co-editing socket has said a sentence about these since it was written —
    `_commit_room`'s `refused` frame, the only place the tuple above was used.
    The seven HTTP write routes caught nothing, so the same raise left Starlette's
    default handler to answer 500 with twenty-one bytes of `text/plain`. Measured
    on a forked plan: 26 write requests over three passes, every one of them
    `Internal Server Error`, `response.json()` rejecting on all 26, and the store's
    own sentence — the one that names the two shas — going to the server log,
    which nobody in a browser is reading.

    Both surfaces are built from the same failure here, so the room and the page
    cannot start describing one condition in two ways.
    """
    # Already an answer. Every route above raises these deliberately — a 404 for a
    # record that is not there, a 422 for a field that would not read back — and
    # a store call cannot raise one at all. It is in the tuple because the room's
    # catcher covers a whole body of work rather than one call, and passing it
    # through untouched is what lets the tuple be used whole rather than sliced
    # into a second list that would drift from this one.
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, StoreDiverged):
        # 503, and the argument is worth writing down because the two codes that
        # come to mind first are both wrong.
        #
        # 500 claims a bug in this service. There is none. The store's write
        # gate refuses to commit onto a fork rather than guess which commits to
        # discard, and that refusal is the reason nobody's work has been
        # destroyed — the code that ran is the code that was meant to run, and
        # what is wedged is the repository it was pointed at. A 500 sends
        # somebody to read this file, which is the one place the answer is not.
        #
        # 409 is the one that reads right and is the one that must not be used.
        # It already means something to every page that writes: `refusal()` in
        # `render/shell.py` answers a 409 out of `answer.conflict`, the report
        # naming the file and each field that disagreed, and four call sites
        # branch on `status === 409` before they look at anything else. A
        # divergence carries no such report, so a 409 here would paint the
        # conflict box empty and say "somebody else changed this first" — a
        # sentence describing something a reload fixes, about something no reload
        # will touch.
        #
        # 503 is the honest one: this service cannot take writes, for a reason
        # outside the request, and a monitor that reads 5xx as "the write half is
        # down" is reading it correctly, because it is down. Deliberately with no
        # `Retry-After`: RFC 9110 makes that header the way a 503 says "come back
        # in N seconds", and this does not clear on a timer. It clears when
        # somebody merges the two histories, and until then a scheduled retry is
        # another 503 and another line in the log.
        #
        # Every browser path is safe with it, and that was checked rather than
        # assumed: every write site in `render/` tests `!response.ok` — or
        # `status === 409` — before it looks at anything else, so a 503 is read
        # as a refusal at all of them and as success at none. Held from the
        # browser's side by `test_every_page_that_writes_says_the_whole_sentence_
        # a_forked_plan_answers` in `tests/test_writes.py`, which drives the
        # shipped scripts with whatever this function actually returns.
        return HTTPException(
            503,
            # The store's own words first. They carry the two shas, which are the
            # whole of what somebody with a terminal needs, and they keep the
            # sentence in the log identical to the sentence on the page. Then the
            # part the store cannot know: that the request was refused, that this
            # is the plan and not this one record, and that trying again is not
            # the thing to do.
            f"{error}{_WHOLE_PLAN}somebody merges the two "
            "histories in the plan repository by hand; trying again will not clear it.",
        )
    if isinstance(error, StoreSwamped):
        # The pile past its ceiling: the same 503 and the same skeleton as the
        # fork above — one vocabulary for "this store will not take your
        # write", because two wordings would read as two outages — with the one
        # honest difference spelled out where the truth differs. A fork clears
        # only by hand and retrying is futile; a pile clears on its own the
        # moment the pusher lands it, so "try again in a few minutes" is the
        # right advice here and would be a lie there.
        return HTTPException(
            503,
            f"{error}{_WHOLE_PLAN}the saves already made here land on GitHub. "
            "Your edit is still in front of you — keep it there and try again "
            "in a few minutes.",
        )
    if isinstance(error, StoreLocked):
        # Reachable from `Store.__init__` rather than from a write — the flock is
        # taken once, at open — so this arm is for the day that stops being true.
        # 503 for the same reason as above and not the one below: another process
        # holding the lock is not a bug in this one. Nothing is added to the
        # store's own words, which already name the holding pid and how to clear
        # it; all this route knows and it does not is that nothing was written.
        return HTTPException(503, f"{error} Nothing was written.")
    # `ValueError` and `pygit2.GitError`: the failures the tuple names and this
    # file cannot write a better sentence for than the class and the message. The
    # room says exactly this, in exactly these words, in its own last arm — one
    # condition, one description, on both surfaces. 500 here and not above,
    # because an unexpected git error IS this service failing to do a thing it
    # should be able to do.
    #
    # It costs the traceback in the server log, because a handled `HTTPException`
    # is not logged the way an escaped exception is. That is the trade this file
    # keeps making and it is the right way round: the log has a reader only if
    # somebody already knows to look, and the person who pressed Save has no
    # other way to be told anything at all. The class name travels in the answer
    # rather than a shrug, which is what makes the answer worth reading.
    return HTTPException(500, f"that save did not go through: {type(error).__name__}: {error}")


async def _write_or_refuse(write, /, *args, **kwargs):
    """Run one store write off the event loop, and answer rather than crash.

    The narrow waist every HTTP write already had: each of the ten routes ends
    in exactly one `asyncio.to_thread(store.…)` call, so wrapping that call is
    the whole of the write path and nothing else. Kept as a function rather than
    an `@app.exception_handler`, because `WRITE_FAILURES` is true of a *write*
    and is not true of the app: a `ValueError` out of a read route is not a
    refused save, and registering the tuple's members app-wide would answer one
    as though it were.

    `test_no_write_route_escapes_the_refusal` (`tests/test_web.py`) reads this
    file as syntax and holds the shape — every `store.write`, `store.write_all`,
    `store.put_asset`, `store.put_drawing` and `store.remove` outside
    `_commit_room` is the first argument here — so a write route added outside
    this shape goes unnoticed rather than refused.
    """
    try:
        return await asyncio.to_thread(write, *args, **kwargs)
    except WRITE_FAILURES as error:
        raise _refusal(error) from None


def _a_restart_discards(state: Condition) -> str:
    """The warning both red conditions carry, written once.

    An operator holding a red monitor has one first instinct, and it is the
    wrong one for the same reason under a fork and under a pile: on Cloud Run's
    in-memory filesystem a restart really does clear the condition, by
    discarding exactly the commits `unpushed` is counting.
    """
    many = state.unpushed != 1
    return (
        f"on this filesystem a restart clears it by discarding the {state.unpushed} "
        f"commit{'s' if many else ''} on this disk that "
        f"{'have' if many else 'has'} not reached the remote"
    )


def _wedged(state: Condition) -> str | None:
    """A store that cannot write, said so a person can act on it — or None
    while it can.

    Beside `_refusal` because they are the two halves of each condition and have
    to stay legible against each other: that one answers the person who pressed
    Save, this one answers `/api/health`. Both open on the store's own wording —
    the force-push guard's sentence for a fork, `swamped`'s for the pile —
    because wording one outage three ways makes it look like three outages.

    They differ in the half that follows, and deliberately: the person is told
    what their save's fate is, the operator what a restart costs. The fork is
    asked first, as at the write gate — a forked store swamps eventually, and
    the fork's advice is the one that still holds when both are true.
    """
    if state.diverged:
        return (
            f"{state.refusal}. Retrying will not help and neither will a restart: "
            f"{_a_restart_discards(state)}. Somebody has to "
            "merge the two histories in the plan repository by hand — "
            "deploy/RUNBOOK.md, 'The service cannot write'."
        )
    choking = swamped(state)
    if choking is None:
        return None
    return (
        f"{choking}. Do not restart: {_a_restart_discards(state)} — they exist "
        "nowhere else. This clears on its own the moment the pusher lands the "
        "backlog; if it is not draining, find out why the push is failing "
        "before anything else."
    )


# The half the room appends to every refusal it makes — the one action that
# works in a room whose base no longer moves. Module-level, not inline in
# `_refuse_room`, because the cross-surface test in `tests/test_web.py`
# separates the store's words from this sentence to compare them against the
# HTTP answer: the store's half travels verbatim to both surfaces, and a second
# spelling of this half is how the two would drift apart unnoticed.
COPY_WORK_OUT = (
    "Copy your work out of the editor before you close this tab — "
    "nothing typed since the last save has reached the plan."
)


# Why the co-editing socket said no, in a code and a sentence the browser can
# read — and the whole reason the route accepts a socket it is about to close.
#
# **A close code only crosses the wire after a handshake.** Refusing before
# `accept` is an HTTP 403 in the access log and, in the browser, `onclose` with
# code 1006 and an empty reason — which is byte for byte what a connection that
# merely dropped looks like. Cloud Run's request deadline drops this socket every
# five minutes by design, so reconnecting is the normal case, and the page could
# not tell the two apart: it retried a permanent refusal for ever. One tab did
# exactly that between 2026-08-22 09:15 and 2026-08-24 10:45 — 49 hours, roughly
# 2,900 refused handshakes, once a minute, after its session passed the 24 hours
# `read_session` gives one. Nothing on screen ever said it had been signed out.
#
# So the refusal is accepted and then closed. It costs one `101` in the access
# log where a `403` used to be, which is worth saying out loud because `403` on
# this path was a usable signal that a tab was knocking and being turned away;
# the codes below are that signal now, and they reach the person as well.
#
# 4000-4999 is the range the protocol reserves for an application, and the page
# stops on any of them rather than on a list it has to keep in step — see
# `editor.py`'s `onclose`. Which code is off the refusal's own status, so there
# is one answer to "why may I not write this", given by the code that decides it.
_SOCKET_REFUSALS = {
    400: (4400, "that is not a record id — reload the page"),
    # Not "your session has expired", although expiry is what produces this in
    # practice: the same arm answers a client that was never signed in at all,
    # and telling somebody their session ran out when they never had one sends
    # them looking for a thing that did not happen.
    401: (4401, "you are not signed in any more — reload the page and sign in to edit"),
    403: (4403, "you are not a member of the organisation that may edit this plan"),
    409: (4409, "two files in the plan claim this id, so it cannot be edited"),
}
# What a close frame will carry: 125 bytes of payload, two of which are the code.
# A longer reason is not truncated by the library — it is a frame the peer
# rejects, which would turn a sentence into the silence it was written to end. So
# it is cut here, where the budget is known.
_CLOSE_REASON_BYTES = 123


async def _refuse_socket(socket: WebSocket, refused: HTTPException | None, record_id: str) -> None:
    """Turn a co-editing socket away, saying which of the reasons it was.

    `refused` is None when `_path_for` simply found no file, which is not an
    exception and is the one refusal that names the record back.
    """
    code, why = _SOCKET_REFUSALS.get(
        refused.status_code if refused is not None else 404,
        (4404, f"{record_id} is not in the plan any more — reload the page"),
    )
    await socket.accept()
    # The frame first and the close code second, because they answer two
    # different vintages of this page and only one of them is deployable.
    #
    # A page already open in somebody's browser is the page that was served to
    # it, and the tab this was written for has been open since 2026-08-21. That
    # page's `onclose` takes no argument and cannot read a code — but its
    # `heard()` has always stopped permanently on `{"t": "reload"}`, and that is
    # the only sentence that can reach it. Without this frame the accept alone
    # makes it WORSE: its `onopen` sets `attempts = 0`, so a refusal that is
    # accepted resets the backoff and the tab knocks every 500 ms instead of
    # every thirty seconds — sixty times more often, until somebody reloads it.
    # Which is a thing nobody was going to do, since nothing on the screen ever
    # said anything was wrong.
    #
    # A page served after this deploy stops on either one. Belt and braces on
    # purpose: the frame is what rescues the tabs that are already out there,
    # and the code is what a page can still act on when a proxy or an older
    # revision eats the frame.
    await socket.send_json({"t": "reload", "why": why})
    await socket.close(code=code, reason=why.encode()[:_CLOSE_REASON_BYTES].decode(errors="ignore"))


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
# `DIRECTORY` is imported from `model.py` and NOT re-derived here, along with
# `MODELS`, `PREFIX`, `INBOXES` and `opens_at` — which this file no longer names
# at all, now that minting a record goes through `model.mint_id` and
# `model.opening_fields`. All of them were defined on this line until the CLI
# grew a write path of its own and needed the same five: importing them from
# this module would have put FastAPI and uvicorn on the import path of `openproj
# check`, and deriving them a second time in `cli.py` is how a ladder comes to
# have a rung in one place and not the other. The comment that used to sit here
# was already counting — "the SEVENTH copy" — which is the argument for moving
# them rather than for adding an eighth.
#
# The rung an id names, read off its prefix — the inverse of `PREFIX`, and the
# one of the group that only this file asks for. It answers the two questions a
# bare id has to: which directory its file lives in, and which status vocabulary
# judges a write to it.
KIND_OF_PREFIX = {rung.prefix: rung.name for rung in KINDS}


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
# How many records one bulk write may touch. A bound rather than a policy: the
# gesture that reaches this route is a cmd-click selection in a table, so the
# realistic number is two to twenty, and the whole plan is a few hundred. What it
# stops is a hand-crafted payload naming every record in the plan and holding the
# single writer lock while `write_all` reads, patches and parses all of them —
# not malice necessarily, a loop with a bug in it. Refused out loud and naming
# the number, because a silent truncation would write *some* of the selection,
# which is the half-done state this whole route exists to prevent.
MAX_BULK_RECORDS = 100
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

# `GET /static/{name}` answers for the two vendored bundles that are fetched
# rather than carried: Excalidraw on the first press of the drawing button, and
# mermaid on a page that turns out to have a diagram on it. Both are megabytes
# that most readers of most pages never meet, and both would fail the page-wide
# scans if they were inlined — `static/VENDOR.md` has the arithmetic. This is
# an allowlist of vendored names, not a directory listing — the writable
# surface is closed by construction (this module's docstring), and a route
# that took its file name from the request and opened `static/<name>` would
# open the readable surface the same way a path traversal always does. Every
# name here is checked in exactly once, by hand, alongside what it should be
# served as; there is no name this dict does not already know about.
STATIC_ALLOWLIST = {
    "excalidraw.js": "application/javascript",
    "mermaid.min.js": "application/javascript",
}

DRAWING_DIR = "drawings"
DRAWING_SUFFIX = ".png"
# A drawing is named by its id alone. Kept separate from `ID_PATTERN` for the
# reason `CYCLE_PATTERN` gives below it: the record id pattern is what keeps the
# writable surface closed by construction, and widening it to admit a fifth
# shape is how that property gets lost by degrees. `\A`/`\Z` and not `^`/`$`,
# which admit a trailing newline.
DRAWING_PATTERN = re.compile(r"\Adraw-[0-9a-f]{6}\Z")

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
# The most slides one cycle's deck may be ordered into. A cycle holds tens of
# records and the deck draws the leaves among them; this is an order of magnitude
# above the largest real cycle, and it exists because `deck_order` is otherwise
# an unbounded list of strings a writer can put in a file in git, on a protected
# branch, where the force-push that would take it back out is blocked. The same
# reasoning as `MAX_CYCLE_WEEKS` above, which was written after the unbounded
# version had already committed.
MAX_DECK_SLIDES = 500
# The most sections one slide may choose. They are headings in one shaping
# document; the team's own template ships six, and a record with a hundred is not
# one anybody is standing up and presenting from. Same argument as the two bounds
# above — an unbounded list of strings that reaches a file in git needs a number
# somewhere, and the door is the only place it can be.
MAX_SLIDE_SECTIONS = 100


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
                422,
                f"the review meeting is {reviews}, which is not after the betting "
                f"table on {opens} — a cycle needs at least one day of build",
            )
        if (reviews - opens).days > MAX_CYCLE_WEEKS * 7:
            raise HTTPException(
                422,
                f"{(reviews - opens).days // 7} weeks from the betting table to the "
                f"review meeting is not a cycle; the most this will hold is "
                f"{MAX_CYCLE_WEEKS:g} weeks",
            )
    # A sentence, and bounded — this reaches a `<h2>`-adjacent line on a page and
    # a line in a YAML file, and neither wants a pasted document. Coerced to a
    # string rather than refused for not being one, because a form sends what was
    # typed and a goal of `2026` is a person writing a year, not an error.
    if "goal" in fields:
        goal = "" if fields["goal"] is None else str(fields["goal"]).strip()
        if len(goal) > MAX_GOAL_CHARS:
            raise HTTPException(
                422,
                f"a cycle goal is {MAX_GOAL_CHARS} characters at most; that one is "
                f"{len(goal)}. The rest belongs in the notes under the betting table.",
            )
        fields["goal"] = goal
    rates = fields.get("availability")
    if rates is not None:
        if not isinstance(rates, dict):
            raise HTTPException(422, "availability must be a map of login to fraction")
        fields["availability"] = {
            str(who): _as_positive(rate, f"availability of {who}") for who, rate in rates.items()
        }
    if "deck_order" in fields:
        fields["deck_order"] = _as_record_ids(fields["deck_order"], "deck_order")


def _as_record_ids(value: object, name: str) -> list[str]:
    """A list of record ids, refused at the door rather than sanitised on the way out.

    `Cycle` parses this permissively — a file that arrived in git holding
    nonsense here has to load, or one hand edit takes every date on every page
    down. The write path is the opposite bargain and always has been: what a
    person committed by hand is a fact to work around, what this server is about
    to commit is a choice it can decline. `PATCH /api/record` learned that the
    expensive way, with eleven bodies that committed and then 500ed every page.

    Bounded, because a deck order is one id per slide in one cycle and a cycle
    holds tens of records. Unbounded, this is a list of arbitrary strings a
    signed-in writer can put in a file in git, on a protected branch, where
    branch protection blocks the force-push that would take it back out.

    Not checked against the records that exist, deliberately. An order naming an
    id this cycle has since stopped holding is ORDINARY — somebody re-bets while
    a deck tab is open — and `_deck_order` ignores it. Refusing it here would
    turn a stale tab into a dead end whose only cure is a reload, which is the
    same failure `/cycle/-1` was before it was bounded.
    """
    if not isinstance(value, list):
        raise HTTPException(422, f"{name} is a list of record ids, not {value!r}")
    if len(value) > MAX_DECK_SLIDES:
        raise HTTPException(
            422,
            f"{name} holds at most {MAX_DECK_SLIDES} record ids, and that one holds {len(value)}",
        )
    for one in value:
        if not isinstance(one, str) or not ID_PATTERN.match(one):
            raise HTTPException(422, f"{name} holds record ids, and {one!r} is not one")
    return list(value)


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
_LISTS = ("assignees", "reviewers", "tags", "prs", "depends_on", "pitched_into", "became")


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
    if "slide" in fields:
        fields["slide"] = _as_slide(fields["slide"])


def _as_slide(value: object) -> dict | None:
    """One record's slide settings, refused at the door rather than defaulted.

    `Slide` parses permissively — a hand edit that says `progress: banana` costs
    one slide drawn the generated way, never a record that will not load. This is
    the other half of that bargain and the one this repository keeps relearning:
    what a person committed by hand is a fact to work around, what this server is
    about to commit is a choice it can decline. Sanitising here instead would
    write the *corrected* value into git and leave nobody any way to see that
    what they sent was not what landed.

    `null` is how the editor says "stop personalising this and go back to the
    generated slide", so it is a value rather than an omission — the one write
    that takes the key back out of the file.

    The prose is bounded because nothing else bounds it. A body goes through
    `_body_in`'s `MAX_BODY_BYTES`; this is frontmatter, and there is no ceiling
    anywhere on the way in — which on a protected branch means a blob that cannot
    be taken back out.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(422, f"slide is a map of settings, not {value!r}")
    unknown = sorted(set(value) - set(Slide.model_fields))
    if unknown:
        raise HTTPException(
            422,
            f"slide has no setting called {unknown[0]!r}; it holds {', '.join(Slide.model_fields)}",
        )
    for name in ("skip", "progress", "prs", "lead"):
        if name in value and not isinstance(value[name], bool):
            raise HTTPException(422, f"slide.{name} must be true or false, not {value[name]!r}")
    chosen = value.get("sections")
    if chosen is not None:
        if not isinstance(chosen, list) or not all(isinstance(one, str) for one in chosen):
            raise HTTPException(422, f"slide.sections is a list of section names, not {chosen!r}")
        # Bounded against the same kind of unbounded-list-into-git argument as
        # `deck_order`, and low: these are headings in one document, and a
        # document with a hundred of them is not one anybody is presenting from.
        if len(chosen) > MAX_SLIDE_SECTIONS:
            raise HTTPException(
                422,
                f"slide.sections names at most {MAX_SLIDE_SECTIONS} sections, and that one "
                f"names {len(chosen)}",
            )
    prose = value.get("body")
    if prose is not None:
        if not isinstance(prose, str):
            raise HTTPException(422, f"slide.body is text, not {prose!r}")
        if len(prose.encode("utf-8")) > MAX_SLIDE_BYTES:
            raise HTTPException(413, "that slide is too large to commit")
    return dict(value)


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


def _reject_a_start_date_this_write_puts_in_the_past(
    fields: dict, candidate: Record, before: Record | None, today: date
) -> None:
    """A start date typed into the past, before it is a file.

    The other half of `start_date_has_passed`, and the reason it is a function
    with two callers rather than two `if`s: the validator warns about a date that
    DRIFTED into the past — nobody edited anything, the calendar moved — and this
    refuses one somebody is typing there right now. Same question, and the
    severities differ because the situations do. There is somebody at a keyboard
    here who can be told and can fix it in the same second; there is nobody at all
    on the drift path.

    **What is refused is the WRITE, and not the state the record is in.** The
    first version asked the candidate alone, which reads as "this record is
    illegal" — and a record whose stated date has merely drifted by is illegal by
    that reading every second of every day, with nobody having touched it. So the
    door refused every write that so much as passed over one: `{"title":
    "Renamed"}` on a drifted task answered 422 naming a field the payload did not
    carry, and a bulk edit refused the entire selection because one row in it had
    a date that had gone by. Renaming, retagging, reparenting by drag and drawing
    a dependency edge were all impossible for that record, and the sentence they
    got named the wrong cause. **The co-editing room was the worst of it**: it ran
    this on every flush, so a shaping document being written on a drifted record
    was refused identically on Save, on the twenty-second quiet window and on the
    last person out — told to copy the work out of the editor, and holding the
    only copy of the document until the last tab closed.

    The delta is what lets the room keep the gate rather than lose it. Deleting
    it from `_commit_room` was the first repair and it went a door too far: that
    function commits the record page's FIELDS as well as its prose — `save()`
    there hands the form to `COEDIT.save(fields)` whenever the socket is up — so
    the surface people actually edit on was the one surface with no rule. All four
    doors ask it now, and the two flushes nobody typed at carry `{}` and fall
    through, which is exactly the distinction the delta draws.

    So the question is asked of the delta: the candidate is illegal AND this write
    is what made it so — the payload typed the date, or the record was legal until
    this write moved its status back onto a date that was already standing in it.
    Drift with an unrelated payload over it is exactly the case that falls
    through, and what it earns is `validate_all`'s warning, which is what drift is.

    **`before` is the record as it stands, and `None` means there is none** — the
    create door, where nothing is standing and therefore every value in the
    candidate is one somebody has just typed. It is also what a record the index
    cannot show us reads as, and refusing there is the conservative half of the
    rule rather than a hole in it.

    It still reads the CANDIDATE and not the payload alone, alone among the
    `_reject_*` family, and it has to: the rule is about two fields at once and a
    PATCH carries only the ones that moved. `{"status": "ready"}` sent to a record
    that already holds a past date is this refusal, and the date is not in
    `fields`. The parsed candidate is the one place the new status and the old
    date are true at the same time, which is why this is called after `parse_text`
    rather than beside its siblings above.

    **The remedies are the write's, and there are two writes here.** One sentence
    served both and it was wrong about the commoner one. Somebody typing a date
    into a record whose status they are not touching is usually behind on the
    status rather than wrong about the date — "I started this on Monday" — and
    `in_progress` is the remedy that fits. Somebody MOVING the status is the
    opposite case: dragging the hill ball from `in_progress` back to `ready` is an
    ordinary correction, and it was answered with "or set the status to
    in_progress if it started then", which is the state they are deliberately
    leaving, while clearing the date — the fix — was not named at all. An error
    that names a remedy the person has just rejected reads as the tool not having
    understood the gesture, and this one said it on all four doors.

    The status is not quoted back. Three of the four doors run `_reject_bad_status`
    before this and the room runs none, so the word can be anything a payload
    carries — and naming the CONTROL rather than its value is the better sentence
    anyway, by the rule that copy names what a person touched.
    """
    if not start_date_has_passed(candidate, today):
        return
    if "start_date" not in fields and before is not None and start_date_has_passed(before, today):
        return
    if "status" in fields:
        said = (
            "the status you are setting says the work has not begun. "
            f"Clear the start date, or pick one from {today} on."
        )
    else:
        said = (
            "this record says the work has not begun. "
            f"Pick a date from {today} on, or set the status to in_progress if it started then."
        )
    raise HTTPException(422, f"start_date: {candidate.start_date} has already passed, and {said}")


def _reject_dates_this_write_cannot_mean(
    fields: dict, candidate: Record, calendar: Callable[[], Config]
) -> None:
    """The two date-versus-date rules of §6, refused where somebody can fix them.

    There was no such door before this. `_reject_bad_types` asks whether two
    fields are numeric and the date coercion takes any parseable ISO date, so the
    only date-RANGE check in the whole application was the one for cycle files —
    and `2025-09-11` typed for `2026-09-11` committed with a 200. After it,
    `span.start <= window[1] and span.end >= window[0]` can never be true for any
    cycle, so the record drops silently out of `counts_in`, out of `Index.load`
    and out of `carried_into` while `openproj check` reports the plan clean. A
    cycle quietly loses a person's work and there is no error anywhere to chase.

    **Two rules, one door, because they share their whole shape.** Both are
    questions about the dates on the record and nothing else; both have a
    `validate_all` twin, which is where the same predicate reports the case
    nobody typed; and both take the same delta test below. Split into two
    functions they would be two identical guards and four call sites at each of
    the four write doors, and the thing that matters — that a write is judged on
    what it typed — would be written twice.

    **Asked of the delta, which `_reject_a_start_date_this_write_puts_in_the_past`
    above learned the expensive way.** A record can arrive in either state
    without anybody writing to it: a hand edit in git puts two contradictory
    dates in a file, and editing `config/cycles.yaml` can move every window out
    from under a date that was inside one yesterday. Asked of the state, this
    door would then refuse `{"title": "Renamed"}` on that record, name a field
    the payload does not carry, refuse a bulk retag because one row in the
    selection was affected, and refuse every flush of a shaping document being
    written in the co-editing room. So what is refused is the write that typed a
    date, and what a record that merely holds one gets is the warning
    `validate_all` reports beside it.

    The candidate rather than the payload's raw values, because `parse_text` has
    already turned them into dates and this is a rule about dates. The payload
    decides WHETHER to ask; the parsed record answers.

    `calendar` is a callable and not a `Config` because of the same delta: three
    of the four doors have no configuration to hand and would have to read one —
    `_config_at` walks the whole tree at a commit and parses every cycle and
    every person under it — and the overwhelming majority of writes name no date
    at all. A retitle, a retag and every quiet flush of the co-editing room would
    each have paid for a calendar nothing was going to compare against. Passing
    the read rather than the answer keeps the delta test in one place, which is
    the other half of why this is one function.
    """
    if not set(DATED_FIELDS) & set(fields):
        return
    config = calendar()
    if ends_before_it_starts(candidate):
        raise HTTPException(
            422,
            f"end_date: {candidate.end_date} is before the start date "
            f"{candidate.start_date}, so this record would have finished before it began.",
        )
    for name in DATED_FIELDS:
        if name not in fields:
            continue
        away = weeks_outside_every_cycle(getattr(candidate, name, None), config)
        if away is not None:
            raise HTTPException(
                422,
                f"{name}: {getattr(candidate, name)} is {away:.0f} weeks outside every cycle "
                "this plan has dated, so it would count towards none of them. Check the year.",
            )


def _reject_undeclared_fields(fields: dict, known: tuple[str, ...], what: str) -> None:
    """A key no model declares, refused rather than committed and forgotten.

    Both write doors kept every key the payload carried and handed the lot to
    `patch_text`, which writes whatever it is given: an undeclared name landed in
    the frontmatter with a 200, was read back into `record._unread`, re-emitted
    verbatim by `serialise` for ever, and read by nothing. The case that makes it
    urgent rather than untidy is a rename — a tab left open across the deploy that
    retired `assigned_on` PATCHes `assigned_on`, is told it saved, and commits a
    dead key carrying the one date the whole schedule is derived from, on a
    protected branch where the commit cannot be taken back out.

    An allowlist, and derived from `model_fields` rather than written down here,
    which is the same argument `_named` makes about the commit message it builds
    from these names: a list of fields kept by hand is a list that goes stale on
    the commit that adds a field, and the models are the only place that cannot.

    The union of every rung's fields, deliberately, and not this record's own kind.
    Whether a PITCH may carry `person_weeks` is a question the validator already
    answers beside the record — "a project carries no appetite" — and answering it
    here as well would make the API door stricter than the hand-written file it
    has to stay equal to, which is the argument `_reject_bad_status` makes above
    for a status a kind does not read. What is refused here is a name that means
    nothing to any record at all.
    """
    unknown = sorted(set(fields) - set(known))
    if unknown:
        raise HTTPException(
            422,
            f"{what} has no field called {unknown[0]!r}; it holds {', '.join(known)}",
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
    worse than none. Measured on the record PATCH and the cycle PUT, which were
    the two routes that kept a field name no model declares; the issue and note
    routes were closed already, because their own gates refused one. Both now
    stand behind `_reject_undeclared_fields`, so the sentence that used to be
    true of two routes is true of all of them.

    An allowlist and not an escape. Stripping newlines would leave the next
    person to work out which characters git's trailer parser accepts, and there
    is no denylist of those that is ever finished — where the model's own field
    names are Python identifiers and cannot spell a trailer at all.

    `others` is therefore unreachable from those doors now and is kept anyway. It
    is the second guard on the same invariant and the cheap one: this function
    signs a line in a commit, the door in front of it is a different function, and
    a route added later that forgets the door must still not be able to put a key
    off the wire into a commit message. A save that wrote something this cannot
    name is still a save that wrote something, and the count says so.

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


def _patched(
    original: str, fields: dict, body: str | None, path: str, drop: Sequence[str] = ()
) -> str:
    """The file with those fields applied, or a refusal naming the file.

    About the file being edited, not about the edit. `patch_text` loads the
    frontmatter it is going to change, so a record somebody wrote in git whose
    YAML never closes raised a ruamel ParserError under the router — a 500 with a
    `text/plain` body, which is the one answer the editor cannot read back to say
    what happened. The page below it is already telling the reader that this file
    is not a record; this is what Save says when they try anyway.
    """
    try:
        return patch_text(original, fields, body, drop)
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


# `MODELS` is imported from `model.py` with `DIRECTORY` and `PREFIX`; the
# derivation that stood here was the SIXTH copy of `KINDS` — the one the test that
# asserts the derivation did not name — so `POST /api/record` with
# `kind: product` raised KeyError and answered 500 on the only route that can
# create one.


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
    org: str = "",
    secret: str = "dev-secret",
    client_id: str = "",
    client_secret: str = "",
    remote: str = "",
    credentials: object | None = None,
    dev_login: str = "dev",
    today: date | None = None,
    github_transport: httpx.BaseTransport | None = None,
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
        if not org:
            # Membership of the org is the whole of the write permission, so a
            # blank one is not "anybody may write" — it is a question nobody
            # answered. It used to default to one team's org in this file,
            # which made every other deployment silently that team's.
            raise ValueError(
                "refusing to start: auth='github' without an org — membership of the org "
                "is what decides who may write. Pass --org, or set OPENPROJ_ORG."
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
        """Start the pusher, and on the way out land the backlog and hand the
        writer lock back.

        The lock used to be released only by the process ending, which is true
        of every deployment and of nothing else: two servers over one repository
        in one process — a test that restarts one, a script that opens a second
        — met `StoreLocked` from a server that had already shut down.
        Single-writer is a correctness invariant and stays one; what changes is
        that stopping now counts as stopping.

        The pusher closes BEFORE the store does, in that order because the
        drain still writes refs under the flock the store is about to release —
        and it exists at all because uvicorn runs lifespan shutdown only after
        the in-flight requests finish, so by the time the drain runs nothing
        can add to the backlog it is flushing. This is the window
        `deploy/boot.py`'s execv fix (v0.19.2) opened: SIGTERM actually reaches
        the server now, so this code runs on Cloud Run instead of being
        SIGKILLed ten silent seconds later.
        """
        loop = asyncio.get_running_loop()

        def landed(outcome: SyncOutcome) -> None:
            # On the loop, via the pusher's call_soon_threadsafe hop below, so
            # the queues are touched from the one thread that owns them.
            #
            # Every successful pass is announced, the quiet day included — not
            # only recoveries, which was the first shape and left the ordinary
            # save unconfirmed forever: this frame is what clears the "saved
            # here, not on GitHub yet" mark, and a page cannot wait to see its
            # own sha on main instead because recovery re-mints shas
            # (design/deferred-push.md, "Confirmation cannot be 'my sha is on
            # main'"). The frame's shape is documented at `broadcast`; the
            # (sha, branch) pairs go out as two-element arrays.
            if outcome.state != "landed":
                return
            broadcast(
                {
                    "t": "landed",
                    "landed": outcome.landed,
                    "remapped": outcome.remapped,
                    "parked": outcome.parked,
                }
            )

        def deliver(outcome: SyncOutcome) -> None:
            # Called on the pusher's thread. `call_soon_threadsafe` is the one
            # documented way onto a running loop from outside it; a loop mid-
            # shutdown may refuse, and the announcement is visibility, never
            # durability — the refs already carry everything it says.
            try:
                loop.call_soon_threadsafe(landed, outcome)
            except RuntimeError:
                pass

        pusher = Pusher(store, deliver=deliver)
        app.state.pusher = pusher
        pusher.start()
        yield
        pusher.close()
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

    def broadcast(frame: dict) -> None:
        """Put one frame on every open event stream. Loop-thread only.

        The stream carries two kinds of frame, told apart by `"t"`:

          {"commit": sha, "changed": [ids]}   — a write landed in the LOCAL
              repository. Bare, no discriminator, and staying that way: it is
              the shape every already-shipped page recognises a plan change by.

          {"t": "landed", "landed": sha, "remapped": {old: new},
           "parked": [[sha, branch]]}         — the pusher confirmed the REMOTE
              holds everything up to `landed`, re-minting and parking the shas
              named. The shell rebroadcasts it as an `openproj:landed` DOM
              event for the table's row marks and the editor's save state.

        Any further kind must carry its own `"t"`: an untyped frame IS the
        plan-changed frame as far as every listener is concerned.
        """
        for queue in list(watchers):
            queue.put_nowait(frame)

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
            unreadable=sorted([*unreadable_config, *unreadable_records], key=lambda one: one.path),
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
    # And the index, for the same reason and against a sharper edge. `index_now`
    # takes no lock by design — see the comment above it — so N concurrent
    # readers arriving on a cold key each build their own index rather than
    # queueing behind one build. Measured on a fresh server: twenty first
    # requests all completed within 5 ms of each other AT 10.35 SECONDS, which
    # is twenty parses serialised by the GIL; the first `GET /` costs 621 ms and
    # the second 32 ms. The affected minute delivered 355 pages against 431 for
    # the same load warm — 16% of a minute's throughput spent on the first ten
    # seconds.
    #
    # `--min-instances 0` re-arms this on every idle period, every deploy and
    # every recycle, so on Cloud Run it is not a first-boot curiosity, it is what
    # the first person after lunch gets.
    #
    # A single-flight guard inside `index_now` would also work and is refused:
    # it puts a lock on a read path that is deliberately lock-free and whose
    # comment argues for that. The herd is a cold-start artefact, not a steady
    # state — once warm there is nothing left to collapse.
    app.state.warm_index = index_now

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
        # The plan-changed frame, deliberately bare — see `broadcast` for the
        # stream's two kinds and why this one never grows a discriminator.
        broadcast({"commit": commit, "changed": changed})

    # -- pages --------------------------------------------------------------

    def page(html: str) -> HTMLResponse:
        return HTMLResponse(html)

    def record_list(request: Request, only: str | None) -> HTMLResponse:
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
                may_write=may_write(request),
            )
        )

    @app.get("/", response_class=HTMLResponse)
    def records(request: Request) -> HTMLResponse:
        return record_list(request, None)

    @app.get("/issues", response_class=HTMLResponse)
    def issues(request: Request) -> HTMLResponse:
        return record_list(request, "issue")

    @app.get("/notes", response_class=HTMLResponse)
    def notes(request: Request) -> HTMLResponse:
        return record_list(request, "note")

    @app.get("/table", response_class=HTMLResponse)
    def table(request: Request) -> HTMLResponse:
        commit, index = index_now()
        return page(
            render.render_table(
                index, render.ROUTES, base_commit=commit, may_write=may_write(request)
            )
        )

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
        renders which one is in the page.

        **The parameter opts out** — `?editor=plain`, on jcanton's "make ace the
        default, I think it's worth it", 2026-08-20.

        **And it is now the whole mechanism**, 2026-08-24: "remove the toggle,
        have ace as default for everybody ... don't delete the plain editor but
        make it only accessible by `/?editor=plain`". It used to be sticky —
        typing it wrote a `localStorage` preference and the page put that back
        into the address on every later visit, so it was typed once. That went
        with the switch that made it discoverable: a preference nothing on the
        page can show you or unset is a trap, and one that also costs a redirect
        on every record is the expensive kind. So this parameter applies to the
        page it is on and to no other, and a value stored before that change is
        not read.

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
        `shaping`'s required-field gate is empty — "an idea nobody has bet on has
        no owner and no size by definition" — so a promotion always produces a
        record that validates. That is not luck; it is the same claim the note
        was already making, carried across. It is deliberately not `thinking`,
        the status a record otherwise opens on: `thinking` says nobody has looked
        at this, and pressing Promote is somebody looking at it.

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

        record_id = mint_id(kind)
        commit = store.head()
        config, _ = _config_at(store, commit)
        content = patch_text(
            "---\n---\n",
            {
                "id": record_id,
                "kind": kind,
                "title": source.title,
                # NOT the model's opening status, and the one place in the app
                # that says so on purpose. `Record.status` opens on `thinking`,
                # which means nobody has looked at this yet; somebody has just
                # pressed Promote on this one, and that press is the looking.
                # Both gates are empty, so the old argument here — the one status
                # that requires nothing — stopped choosing between the two words
                # the moment `thinking` joined the ladder, and meaning chooses
                # instead. See the docstring, and `_HILL_HANDED_ON` in
                # `render/hill.py`, which draws the source note's ball at this
                # same word: move one and the picture lies about where the record
                # went.
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
        written = await _write_or_refuse(
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
            # `pushed` as on a PATCH: without it the promote path had nothing
            # to hang a "saved here, not on GitHub yet" mark on.
            {
                "id": record_id,
                "outcome": written.outcome,
                "commit": written.commit,
                "pushed": written.pushed,
            },
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
    def deck(number: int, request: Request) -> HTMLResponse:
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
                lambda path: store.read_asset(commit, path),
                # The commit the rail's Save compares against, and whether this
                # reader may write at all. Both, for the reason `render_deck`
                # says: a reader keeps the rail, because it is how anybody finds
                # slide nine of eleven, and only a writer is offered the drag.
                base_commit=commit,
                may_write=may_write(request),
            )
        )

    @app.get("/help", response_class=HTMLResponse)
    def help_page() -> HTMLResponse:
        """Every document this tool ships, on one page.

        Nothing on it varies by who is looking — a reader who is not signed in
        gets the same page as anybody else, which is the point of documentation —
        so it takes no `Request`. It takes the index all the same, for the one
        thing every page owes: the banner naming plan files that will not parse.
        """
        return page(render.render_help(index_now()[1], render.ROUTES))

    @app.get("/people", response_class=HTMLResponse)
    def people(request: Request) -> HTMLResponse:
        me = picker_for(request)
        return page(render.render_people(index_now()[1], render.ROUTES, editable=bool(me), me=me))

    @app.get("/new", response_class=HTMLResponse)
    def new(request: Request, kind: str = "task") -> HTMLResponse:
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        # A reader is refused the page rather than shown a hollow one. Every
        # control on the create form is behind `may_write`, so a signed-out
        # visitor who reached it got the heading, the kind picker and nothing to
        # type into — jcanton, 2026-08-24: "this opens a crippled editor page".
        #
        # Asked through `writer` (which `may_write` calls) and not through the
        # session, because the two disagree in the mode the tool is tried in:
        # under `--auth dev` there is no session and `/api/me` says signed out,
        # while the write path invents a user and takes the write. A gate on the
        # session would refuse the demo its own create form.
        if not may_write(request):
            raise HTTPException(403, "sign in to create a record")
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
    def detail(record_id: str, request: Request, view: str = "") -> HTMLResponse:
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
        # The slide editor is a VIEW of this record, at this record's own
        # address — jcanton, 2026-08-25: "don't make it /slide/<id> but keep it
        # in /detail/<id> if possible". A query and not a path segment, so a link
        # to the slide is a link to the record and the back button behaves.
        #
        # A separate renderer behind one route rather than a fourth state inside
        # `showView`: `detail.py` is three thousand lines of one page's
        # machinery — a co-editing socket, a draft store, two editors — and a
        # slide editor needs none of it. Anything this route does not recognise
        # is the record page, because a mistyped query should land somebody on
        # the page they asked for rather than on a 404 about a spelling.
        if view == "slide":
            return page(
                render.render_slide_editor(
                    index,
                    record_id,
                    render.ROUTES,
                    base_commit=commit,
                    may_write=may_write(request),
                    editor=which_editor(request),
                    asset=lambda path: store.read_asset(commit, path),
                )
            )
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

    @app.post("/api/slide/preview")
    async def slide_preview(request: Request) -> JSONResponse:
        """One record's slides, as the deck would draw them, from unsaved settings.

        The same reason `/api/preview` beside it exists, one level up. A slide is
        markdown through `_markdown`, sections chosen by `only_sections`, a
        checklist lifted by `checklist_items` and pull requests linked by
        `_pr_link` — five functions, none of which exists in the browser. A
        preview drawn there would be a second renderer of a slide, in a second
        language, agreeing with the projector only for as long as somebody kept
        the two in step. That is precisely the failure a generated deck exists to
        end, and reintroducing it inside the feature for editing one would be a
        poor joke.

        Renders, never writes, so it takes whatever was typed: the settings
        arrive through the same `_as_slide` the save door uses, because a preview
        that accepted a shape the save will refuse is a preview of something
        nobody can keep.
        """
        payload = await _sent(request)
        commit, index = index_now()
        record_id = payload.get("record_id")
        if not isinstance(record_id, str) or record_id not in index.records:
            raise HTTPException(404, "no such record")
        settings = _as_slide(payload.get("slide"))
        # A copy carrying the unsaved settings, and the stored record untouched.
        # `model_copy` rather than assigning through: the index is shared by every
        # request in this process, and a preview that mutated it would show one
        # reader's unsaved draft to everybody else's page until the next reload.
        record = index.records[record_id].model_copy(
            update={"slide": None if settings is None else Slide.model_validate(settings)}
        )
        return JSONResponse(
            {
                "html": str(
                    render.slide_html(
                        index,
                        record,
                        render.ROUTES,
                        render.inlined_assets(
                            [record.body, record.slide.body if record.slide else ""],
                            lambda path: store.read_asset(commit, path),
                        ),
                    )
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

    # What GitHub last said about each repository the plan names:
    # `owner/repo -> (good until, entries, whether the last attempt failed)`.
    #
    # On the closure and not at module scope because the repositories are this
    # plan's and the token is this app's — a module-level cache is one every test
    # that builds a second app would share, which is the shape of a test that
    # passes because of the one before it.
    pulls: dict[str, tuple[float, list[dict[str, object]], bool]] = {}
    pulls_lock = threading.Lock()

    def _live_pull_requests(repositories: list[str]) -> tuple[list[dict], bool]:
        """Every open pull request in these repositories, and whether it is stale.

        `{value, label}` — the shape the combobox already reads, so the page
        merges this with what the corpus cites and needs no second code path.

        **One lock around the whole sweep**, which serialises the refresh rather
        than letting every request in a burst start its own. FastAPI runs a sync
        route in a threadpool, so without it the first typing burst after a cache
        expiry is one API call per keystroke against a rate limit that is shared
        with everything else this deployment does. Held across the network call
        deliberately: at one refresh per repository per five minutes the wait it
        can cause is a wait somebody would otherwise have had anyway.

        A failure keeps whatever was cached and is retried at the ordinary
        interval, not immediately — GitHub being down must not cost a call per
        request — and the entries it kept are still worth offering, because a
        pull request that was open five minutes ago is almost certainly still
        open.

        The exceptions are named rather than caught wholesale: `open_pull_requests`
        documents itself as raising for a refusal, and around that the failures
        are httpx's transport errors and a body that is not the JSON this reads.
        Anything outside the tuple reaches the route and 500s it, which is the
        right answer for a defect here — the page's own fetch fails and the
        completion is back to the corpus either way.
        """
        import json as _json

        from .github import PULLS_TTL_SECONDS, open_pull_requests

        # `github_transport` is `create_app`'s one test seam for this: an httpx
        # transport a test answers from without a socket, the same shape and the
        # same name `GitHubApp.transport` already carries. It is None in every
        # deployment, which is the real network.

        app_for = credentials if hasattr(credentials, "api_headers") else None
        now = time.monotonic()
        offered: list[dict] = []
        stale = False
        with pulls_lock:
            for repository in repositories:
                until, entries, failed = pulls.get(repository, (0.0, [], False))
                if now >= until:
                    try:
                        entries = open_pull_requests(repository, app_for, github_transport)
                        failed = False
                    except (httpx.HTTPError, _json.JSONDecodeError, KeyError, ValueError):
                        # WARNING and not an exception: the operator wants to know
                        # the completion is narrower than it should be; nobody
                        # wants a traceback per five minutes for a repository that
                        # has been renamed.
                        _LOG.warning("could not read open pull requests for %s", repository)
                        failed = True
                    pulls[repository] = (now + PULLS_TTL_SECONDS, entries, failed)
                stale = stale or failed
                offered += [
                    {"value": f"{repository}#{one['number']}", "label": str(one["title"])}
                    for one in entries
                ]
        return offered, stale

    @app.get("/api/prs")
    def prs(request: Request) -> JSONResponse:
        """Open pull requests in the repositories the PLAN names, `{value,label}`.

        The completion in a shaping document and in the `prs:` field has always
        offered what the corpus already cites, which answers "which of the ones
        we have written down" and never "which are open right now" — jcanton,
        2026-08-25, asking for the latter.

        **This route takes no input, and that is the security decision on it.**
        A `?repo=` parameter would make this server a proxy that fetches any URL
        on api.github.com that anybody can name, from an IP inside our project,
        with our token on it where the App has access. The repositories come from
        `config/defaults.yaml` through `Config.repositories`, which is validated
        against an allowlist at the model — so the set this can ever ask about is
        a thing somebody committed to the plan repository.

        **Signed-in writers only**, for the same reason the create form is: this
        completion is drawn on the pages a writer gets, and a route that spends a
        network call and a rate-limit slot for an anonymous visitor is a route
        that can be made to spend them all.

        A refusal is not an error here. What this offers is a widening of a list
        the page already has, so GitHub being down, rate-limited or unreachable
        answers with whatever is still cached and otherwise with nothing at all —
        the completion goes back to the corpus, which is where it was yesterday.
        `stale` says which, for a reader who wonders why a pull request opened a
        minute ago is not on the list.
        """
        if not may_write(request):
            raise HTTPException(403, "sign in to read the open pull requests")
        _, index = index_now()
        offered, stale = _live_pull_requests(index.repositories)
        return JSONResponse({"prs": offered, "stale": stale})

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
    def healthz() -> JSONResponse:
        """Whether this service can write, in the two places a check looks.

        `ok` was a literal, so it could not be false, and a store wedged on
        `StoreDiverged` — every save answering 500, for the life of the container
        — reported itself healthy on all six asks the concurrency audit made of
        it. `store.condition()` reads that state off two local refs; see its
        docstring for why there is no fetch here and nothing to clear.

        **`ok` is about writing, not about pushing.** `unpushed` above zero is
        usually GitHub having been away for a moment; the pusher retries on its
        own clock and the pile drains with nobody doing anything. A flag that
        goes red for a condition that heals itself is a flag people learn to
        ignore, which is how the one that matters gets missed. So the verdict is
        exactly "are writes being refused": a divergence, which is permanent and
        needs a person, or a pile past the ceiling the write gate refuses at
        (`swamped`, store.py) — and below that ceiling the pile is reported in
        numbers, never as a flag. `unpushed`, `oldest_unpushed_age` and `parked`
        travel beside the verdict for a monitor to set its own threshold and its
        own patience on; they are also what the shell's banner reads.

        **503 and not a 200 carrying a false flag.** `_refusal` argues the code
        itself and this uses the same one, so the write routes and the check that
        watches them cannot disagree about what a wedged plan is. What is this
        route's own argument is that the code has to move at all: a flag only a
        JSON-parsing reader can see is precisely the second key nobody reads.
        `gcloud_deploy.sh` verifies a deploy with `curl -fsS "$URL/api/health"`,
        which exits 0 on any 200 whatever the body says, and an uptime check is a
        status code unless somebody configures it not to be. Left at 200, this
        would be a flag that is honest and unread, which is the outage again.

        The corollary, and it belongs in `deploy/RUNBOOK.md` rather than only
        here: this is not a liveness probe and must not be wired as one. Cloud Run
        answers a failing liveness probe by replacing the container, and replacing
        the container clears this condition by discarding the unpushed commits.

        `head` and `version` keep their meanings: `head` is the PLAN's commit and
        moves whenever anybody saves a record, `version` is this code's and moves
        only on a release. They were one field's worth of confusion apart, and the
        deploy runbook told a reader to check a version string nothing served.
        """
        state = store.condition()
        detail = _wedged(state)
        return JSONResponse(
            {
                "ok": detail is None,
                "head": state.head,
                "version": __version__,
                "unpushed": state.unpushed,
                # The pile, in numbers — what the shell's banner reads, and what
                # re-scopes the alarm to "non-zero and NOT draining" now that
                # every save is briefly unpushed (design/deferred-push.md,
                # "Health"): the age is what tells a stuck pile from the
                # ordinary two-second window, and `parked` counts the commits
                # that reached GitHub but not main.
                "oldest_unpushed_age": state.oldest_unpushed_age,
                "parked": state.parked,
                # Always present, `null` when there is nothing wrong: a key that
                # appears only sometimes is a key a JSON path breaks on, and this
                # is read by scripts. The wording is the store's own — the
                # force-push guard's for a fork, `swamped`'s for the pile — so
                # the operator reading a monitor and the person whose save was
                # refused are told the same thing, plus what to do about it,
                # which is the half a condition report is useless without.
                "detail": detail,
            },
            status_code=200 if detail is None else 503,
        )

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
        payload = render._payload(index_now()[1])
        # Two facts about the STORE, added here rather than in `_payload`
        # because they are not the index's to know: this payload is also the
        # table's poll fallback for its "saved here, not on GitHub yet" marks.
        # The event stream has no replay — Cloud Run recycles it every 300s —
        # so a tab that reconnected has missed the landed frame for good, and
        # this is where it learns its saves are safe (design/deferred-push.md,
        # "Confirmation cannot be 'my sha is on main'"). `landed` is the
        # confirmed tip by NAME; `unpushed` at zero says the whole pile has
        # drained, which is the answer that survives the tip having moved past
        # this tab's own shas. `condition()` reads two local refs — no network,
        # no lock — so a poll costs what a page read costs.
        state = store.condition()
        payload["landed"] = state.remote
        payload["unpushed"] = state.unpushed
        # The parked verdict must ride here too, not only in the landed frame:
        # a parked recovery leaves `unpushed: 0` — the sha honestly LEFT the
        # pile for a branch — so a tab that missed the frame would read the
        # two keys above as "everything landed" and clear the one mark that
        # had to become the branch-naming problem. Same (sha, branch) pairs as
        # the frame; the store's method says how far back it can honestly
        # answer (since this process started — no further record exists).
        payload["parked"] = store.parked_branches()
        return JSONResponse(what_json_can_carry(payload))

    # -- writing ------------------------------------------------------------

    def _result(written, commit_before: str) -> JSONResponse:
        """One shape for every answer. A caller should not have to know whether it
        succeeded to know which keys exist."""
        payload = {
            "outcome": written.outcome,
            "commit": written.commit,
            "conflict": written.conflict,
            "head": commit_before,
            # Whether the commit reached the remote. `Store` has always set this
            # honestly and exactly one caller in the application read it — the
            # co-editing socket's `saved` frame — so every HTTP write answered
            # 200 with a sha and no way to say the sha is only here.
            #
            # It matters because Cloud Run's filesystem is in memory and
            # `--min-instances 0` tears the instance down after a few quiet
            # minutes. Measured with the remote made unwritable for 8 s: ten
            # saves answered 200 with a commit sha, and all ten were on the
            # instance and on no origin.
            #
            # This does not stop the loss. It makes it visible, which is the
            # difference between somebody copying their text out and somebody
            # closing the tab.
            "pushed": written.pushed,
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
        # Before anything asks what a value is: a key no record declares has no
        # type to be wrong. It used to be written through to the file.
        _reject_undeclared_fields(fields, RECORD_FIELDS, "a record")
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
        # The record as it stands, read out of the same population `loop_made` is
        # asked about above rather than parsed a second time out of `original`:
        # the rule needs to know whether this write is what put the date in the
        # past or whether it had drifted there already, and one memoised index is
        # cheaper than a second parse of a file this route has already parsed once.
        _reject_a_start_date_this_write_puts_in_the_past(
            fields, candidate, index_now()[1].records.get(record_id), today or date.today()
        )
        # And the two rules that compare a date against the plan's own calendar.
        # The config is read at `base` — the commit this write is a delta against
        # — rather than at HEAD, so that the windows this date is judged by are
        # the ones the person typing it was looking at.
        _reject_dates_this_write_cannot_mean(fields, candidate, lambda: _config_at(store, base)[0])
        written = await _write_or_refuse(
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

    def _rekind_plan(index, record, kind: str) -> tuple[list[str], list[str]]:
        """What changing this record's kind would refuse, and what it would drop.

        Both computed before anything is written, and both handed back to the
        page BEFORE it commits — the fields are a compare-and-swap on the shape
        of the change, exactly as `also` is for a cascading delete. A reader who
        was shown "this drops its appetite and its assignees" and then had
        something else dropped was not asked.

        **This is not a second copy of the containment ladder, and the sentence
        below is deliberately not the validator's.** `RUNG[k].under` and
        `PARENT_KINDS[k]` are the same tuple — both are `Rung.under` off the one
        `KINDS` sequence — so there is nothing here that can drift from what
        `_containment_problems` (`model.py`) would say about the record
        afterwards; the ladder is single-sourced already and merging the two
        readers would move a name, not a fact.

        What can drift, and did, is the WORDING. `_containment_problems` answers
        "this record standing here is wrong" — *a pitch belongs to a project, not
        to an issue* — with no ids in it and nothing to do about it, because it
        is a line in a report beside the record it is about. This answers "the
        change you just asked for cannot be made", names both records, and says
        what to do instead. Folding them into one sentence would make one of
        those two refusals say something it does not mean, which is why the
        duplication stays. `_an` is imported from the model for exactly that
        reason: the wording is the part that has to be kept in step by hand, and
        the article was the first piece of it to come apart — this line read
        `f"a {kind}"` and said "a issue" on the day issues joined the ladder,
        which is the failure `_an`'s own docstring names.
        """
        rung = RUNG[kind]
        refusals: list[str] = []

        # Where it sits. A pitch is filed under a project and a task may be
        # filed under either a pitch or a project, so pitch->task keeps its
        # parent and task->pitch under a pitch does not.
        if record.parent:
            above = index.records.get(record.parent)
            if above is None:
                # The parent stays a bare id here and only here: no record in the
                # plan claims that name, so there is no title to give it and the
                # complaint is about the spelling. The record itself is named the
                # way every other refusal on this route names one.
                refusals.append(
                    f"{named(record.id, index.records)} names {record.parent} as its parent "
                    "and that record is not in the plan"
                )
            elif above.kind not in rung.under:
                refusals.append(
                    f"{_an(kind)} cannot be filed under {_an(above.kind)} and "
                    f"{named(record.id, index.records)} is under "
                    f"{named(record.parent, index.records)}. Move it first, or take its "
                    "parent off"
                )

        # What sits under it. `under` is per rung, so a pitch with tasks under it
        # can become a project (a task may be filed under a project) and cannot
        # become a task (nothing is filed under a task).
        below = sorted(other.id for other in index.records.values() if other.parent == record.id)
        stranded = [other for other in below if kind not in RUNG[index.records[other].kind].under]
        if stranded:
            # Title then id for every one of them: "Move them first" is an
            # instruction to open each of these files and change its `parent`,
            # and a list of six bare ids is six lookups before anybody can start.
            refusals.append(
                f"{_and_then([named(one, index.records) for one in stranded])} "
                f"{'is' if len(stranded) == 1 else 'are'} filed "
                f"under {named(record.id, index.records)}, and nothing may be filed "
                f"under {_an(kind)}. Move them first"
            )

        # What it would stop being able to say. `unread_fields` is the ladder's
        # own answer and the same one the editors ask, so a field this drops is
        # a field the new kind would not have offered.
        drops = sorted(
            field
            for field in unread_fields(kind)
            if getattr(record, field, None) not in (None, "", [], False)
        )
        return refusals, drops

    @app.post("/api/rekind")
    async def rekind(request: Request) -> JSONResponse:
        """Change a record's kind, by making a new record and retiring the old one.

        **The id carries the kind, so changing the kind changes the id.** That is
        the whole reason this is a route and not a field on `PATCH
        /api/record/{id}`: `pitch-b20000` cannot become a task without becoming
        `task-<something>`, because `ID_PATTERN` and `_directory_for` both read
        the prefix, and `validate_all` refuses a record whose prefix and kind
        disagree. The alternative — freeing ids from kinds — was weighed with
        jcanton on 2026-08-26 and refused: it moves the seam that turns an id
        into a path, and it points every id in git history, every PR link and
        every note at a file that no longer exists.

        So: mint the new id, carry the record across, repoint everything that
        named the old one, and remove it. **One commit**, through `write_all`,
        for the reason promotion and the cascading delete use it — this is one
        decision, and a `git log` showing a task appear, four tasks get a new
        parent and a pitch vanish says six things that are not true. It also has
        no half-done state: a plan where the new record exists and its children
        still point at the old one is not a state anybody can be asked to repair,
        on a protected branch.

        **No trail field** — jcanton's call in the same conversation. The commit
        message says what happened and git has the rest; a `was:` in the
        frontmatter is a field the validator, the table and the detail page all
        have to learn for a rename that happens rarely.

        `drop` is a compare-and-swap on the SHAPE of the change, like `also` on a
        delete: the page sends the fields it told the reader would be lost, and a
        mismatch is a 409 rather than a write nobody agreed to.
        """
        user = writer(request)
        payload = await _sent(request)
        record_id = str(payload.get("id") or "")
        kind = payload.get("kind")
        if not ID_PATTERN.match(record_id):
            raise HTTPException(400, f"{record_id!r} is not a record id")
        if kind not in KIND_NAMES:
            raise HTTPException(422, f"{kind!r} is not a kind")
        was = _kind_for(record_id)
        if kind == was:
            raise HTTPException(422, f"{record_id} is already {_an(kind)}")

        base = _base_in(store, payload)
        path = _path_for(store, base, record_id)
        if path is None:
            raise HTTPException(404, f"no record {record_id!r}")

        _, index = index_now()
        record = index.records.get(record_id)
        if record is None:
            raise HTTPException(404, f"no record {record_id!r}")

        refusals, drops = _rekind_plan(index, record, kind)
        if refusals:
            raise HTTPException(409, ". ".join(refusals))
        # **Losing a field is a question before it is a write**, the shape the
        # cascading delete already uses for `also`. A record that loses nothing
        # goes straight through — there is no question to ask — and one that
        # would lose something is refused until the page sends back the list it
        # showed the reader. Sending a list that does not match what the server
        # computes is the same refusal: it means the plan moved under the panel,
        # and a reader who was shown "this drops its appetite" and then lost its
        # owner as well was not asked.
        shown = payload.get("drops")
        if drops and shown is None:
            # A `JSONResponse` and not an `HTTPException`, so the list travels
            # beside the sentence. The page has to send the same list back to
            # confirm, and re-deriving it by parsing prose the server wrote is
            # how a confirmation comes to mean something other than what it said.
            return JSONResponse(
                {
                    # The record by title and then by id. `_and_then(drops)` beside
                    # it is a list of FIELD names and stays exactly as it is —
                    # `appetite`, `owner` — because those are the keys the reader
                    # will look for in the file, not records with titles.
                    "detail": (
                        f"making {named(record_id, index.records)} {_an(kind)} drops "
                        f"{_and_then(drops)}, because {_an(kind)} does not read "
                        f"{'that field' if len(drops) == 1 else 'those fields'}. "
                        "Nothing was changed."
                    ),
                    "drops": drops,
                },
                status_code=409,
            )
        if shown is not None and sorted(shown) != drops:
            raise HTTPException(
                409,
                "the plan changed while that was open: making "
                f"{named(record_id, index.records)} {_an(kind)} now drops "
                f"{_and_then(drops) or 'nothing'}. Nothing was changed — read it "
                "again and decide.",
            )

        # A fresh id, minted the way `POST /api/record` mints one. Collisions are
        # not checked here for the same reason they are not there: six hex bytes
        # against a plan of hundreds, and `write_all` refuses a path that already
        # holds something anyway.
        new_id = mint_id(kind)
        original = store.read(base, path)
        # One pass: the two fields that change, and the fields the new rung does
        # not read taken out. `patch_text` cannot remove a key by setting it to
        # `None` — that writes `field:` with nothing after it, which is a field
        # that is present and empty, and `validate_all` reads the difference.
        content = _patched(original, {"id": new_id, "kind": kind}, None, path, drop=drops)
        try:
            candidate = parse_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a record: {why_it_will_not_read(error)}"
            ) from None

        files: dict[str, str | None] = {
            f"{DIRECTORY[kind]}/{new_id}.md": content,
            path: None,
        }

        # Everything that named the old id, in the four fields that hold one.
        # `blocks` is not among them: it is derived in `build_index` and never
        # stored, so repointing it here would be writing down a fact the index
        # computes — the invariant this repository states first.
        for other in index.records.values():
            if other.id == record_id:
                continue
            fields: dict = {}
            if other.parent == record_id:
                fields["parent"] = new_id
            for name in ("depends_on", "pitched_into", "became"):
                held = getattr(other, name, None)
                if held and record_id in held:
                    fields[name] = [new_id if one == record_id else one for one in held]
            if not fields:
                continue
            where = _path_for(store, base, other.id)
            if where is None:
                # Both records by title and id. The id is not decoration here: the
                # only way out of this refusal is to go and look at the plan in
                # git, where a file is found by the id and never by the title.
                raise HTTPException(
                    409,
                    f"{named(other.id, index.records)} names "
                    f"{named(record_id, index.records)} and its file could not be found",
                )
            files[where] = _patched(store.read(base, where), fields, None, where)

        # The same loop question the batch write asks, and for the same reason:
        # a shape that only exists once every one of these files has moved is a
        # shape this write would create.
        after = {one.id: one for one in index.records.values() if one.id != record_id}
        after[candidate.id] = candidate
        loop = loop_made(candidate, after.values())
        if loop:
            raise HTTPException(409, loop)

        written = await _write_or_refuse(
            store.write_all,
            files,
            base_commit=base,
            author=user.login,
            message=f"{new_id}: was {record_id}, {was} becomes {kind}",
        )
        if written.outcome == "conflict":
            return _result(written, base)
        if written.commit:
            await announce(
                written.commit,
                [
                    record_id,
                    new_id,
                    *sorted(
                        one
                        for one in index.records
                        if one != record_id and _path_for(store, base, one) in files
                    ),
                ],
            )
        return JSONResponse(
            {
                "id": new_id,
                "was": record_id,
                "dropped": drops,
                "outcome": written.outcome,
                "commit": written.commit,
                "conflict": written.conflict,
                "head": base,
                "pushed": written.pushed,
            },
            status_code=200,
        )

    @app.patch("/api/records")
    async def save_many(request: Request) -> JSONResponse:
        """One field-set, several records, ONE commit.

        The table can now write a column across a selection — pick the cells with
        cmd/ctrl-click or a shift range, edit any one of them, and every record in
        it takes the value. That is one decision somebody made, and `git log` on a
        plan is the team's record of decisions: six commits saying "status ready"
        describe six decisions that were never made. `Store.write_all` already
        commits several files under one lock with a compare-and-swap per path, so
        this route is the gate in front of it and nothing else.

        **It is `/api/records` and the singular route is untouched.** Routing the
        bulk case through `PATCH /api/record/{id}` in a loop was the alternative
        and it is the one that cannot be made right: the second call in the loop
        is written against the commit the first one made, so a conflict halfway
        leaves half the selection written on a protected branch, with no way to
        say which half from the client.

        Every refusal the singular route makes, made here first and for every
        record, because a batch that half-applies is the state this exists to
        prevent. Nothing is written until all of them have passed:

        * a record that is not in the plan is a 404 naming it;
        * an id two files claim is a 409, same as the singular route — the save
          would edit a record that is not the one on screen;
        * a bad type, or a status no vocabulary defines, is refused before the
          file is touched;
        * every patched file is parsed before any of them is written, so a batch
          cannot put a file into git that takes every page down;
        * `loop_made` is asked of each candidate against a population with ALL
          the candidates substituted, and not against the stored plan — six rows
          taking a new parent in one commit can make a cycle that no single one
          of them makes on its own.

        `ids` is deduplicated and its order is not the sender's to choose: the
        commit message is built from the model's field order and a count, so
        nothing the payload carries reaches a line this server signs except
        through `_named`.
        """
        user = writer(request)
        payload = await _sent(request)
        base = _base_in(store, payload)

        wanted = payload.get("ids")
        if not isinstance(wanted, list) or not all(isinstance(one, str) for one in wanted):
            raise HTTPException(422, "ids must be a list of record ids")
        # Order fixed by the plan and not by the payload, and deduplicated: the
        # same id twice is one file, and `write_all` is a mapping — the second
        # would silently replace the first with the identical content anyway,
        # which is a thing better said than relied on.
        ids = [one for one in dict.fromkeys(wanted)]
        if not ids:
            raise HTTPException(422, "no records to write")
        if len(ids) > MAX_BULK_RECORDS:
            raise HTTPException(
                422,
                f"{len(ids)} records in one write, and the limit is {MAX_BULK_RECORDS}. "
                "Narrow the selection.",
            )

        fields = {k: v for k, v in _fields_in(payload).items() if k != "id"}
        if not fields:
            raise HTTPException(422, "no fields to write")
        # The same door as the save beside it, and a worse blast radius: one
        # undeclared key here is a dead line committed into every file in the
        # selection, in one commit, on a protected branch.
        _reject_undeclared_fields(fields, RECORD_FIELDS, "a record")
        _reject_bad_types(fields)

        _, index = index_now()
        contested = {
            problem.record_id
            for problem in index.problems
            if problem.field == "id" and problem.severity == "blocker"
        }

        files: dict[str, str | None] = {}
        candidates = []
        for record_id in ids:
            path = _path_for(store, base, record_id)
            if path is None:
                raise HTTPException(404, f"no record {record_id!r}")
            if record_id in contested:
                raise HTTPException(
                    409,
                    f"{record_id} is claimed by two files. Resolve it in git and reload — "
                    "a save here would edit a record that is not the one you were shown.",
                )
            _reject_bad_status(_kind_for(record_id), fields)
            content = _patched(store.read(base, path), fields, None, path)
            try:
                candidates.append(parse_text(content, path))
            except ValueError as error:
                raise HTTPException(
                    422,
                    f"{record_id} would not read back as a record: {why_it_will_not_read(error)}",
                ) from None
            files[path] = content

        # One read of the plan's calendar for the whole batch, and only if a date
        # is written at all: `_reject_dates_this_write_cannot_mean` asks for it
        # once and then holds it, rather than walking the tree once per record in
        # a selection that may be fifty of them.
        calendar = functools.cache(lambda: _config_at(store, base)[0])
        # The population every candidate is judged against is the plan with all of
        # them already applied. Asked that way round because the batch lands as one
        # commit: a shape that only exists once every record in the selection has
        # moved is a shape this write would create, and checking each candidate
        # against the stored plan would miss exactly that.
        after = {record.id: record for record in index.records.values()}
        for candidate in candidates:
            after[candidate.id] = candidate
        for candidate in candidates:
            loop = loop_made(candidate, after.values())
            if loop:
                raise HTTPException(409, loop)
            # Per candidate, because the answer is per record: one date and one
            # status set over a selection lands on records that are at different
            # rungs, and the whole point of the rule is that `in_progress` is the
            # one where the date is right. The batch is one commit, so a refusal
            # about any of them refuses all of them — which is the same shape the
            # bulk status edit already has when it cannot mark something done, and
            # the reason this asks about the delta and not about the state: the
            # state reading refused a selection outright because one row in it
            # held a date that had gone by on its own, which made a bulk retag
            # impossible for anybody whose selection touched a drifted record.
            # `index.records`, the population `after` is built from a line above.
            _reject_a_start_date_this_write_puts_in_the_past(
                fields, candidate, index.records.get(candidate.id), today or date.today()
            )
            # Per candidate for the same reason, over the plan's calendar as it
            # stands at the commit this batch is a delta against. The read is
            # memoised across the loop by `calendar` below: one payload of fields
            # is written over every id here, so if it names a date at all it names
            # it for all of them, and the windows do not move between two records.
            _reject_dates_this_write_cannot_mean(fields, candidate, calendar)

        written = await _write_or_refuse(
            store.write_all,
            files,
            base_commit=base,
            author=user.login,
            message=(
                f"{len(ids)} records: {_named(fields, RECORD_FIELDS) or 'body'}"
                if len(ids) > 1
                else f"{ids[0]}: {_named(fields, RECORD_FIELDS) or 'body'}"
            ),
        )
        if written.commit:
            await announce(written.commit, ids)
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
            # Titles and ids in the sentence, while `also` on the wire stays a
            # list of bare ids: they are two different things that happen to hold
            # the same records. `shown` is a compare-and-swap on the SHAPE of the
            # deletion and nobody reads it; this is read, and then acted on —
            # somebody has to go and look at each of these before pressing again.
            affects = _and_then([named(one, index.records) for one in doomed + edited])
            raise HTTPException(
                409,
                "the plan changed while that was open: deleting "
                f"{named(record_id, index.records)} now affects "
                f"{affects or 'nothing else'}. "
                "Nothing was deleted — read it again and decide.",
            )

        files: dict[str, str | None] = {path: None}
        for other in doomed:
            gone = _path_for(store, base, other)
            if gone is None:
                # Named the same way as the sentence above, and the id is the
                # load-bearing half: the file this cannot find is found in git by
                # the id, and this is a state only a person with a checkout can
                # get anybody out of.
                raise HTTPException(
                    409,
                    f"{named(other, index.records)} is filed under this and "
                    "could not be found",
                )
            files[gone] = None
        for other in edited:
            where = _path_for(store, base, other)
            if where is None:
                raise HTTPException(
                    409,
                    f"{named(other, index.records)} depends on this and could not be found",
                )
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

        written = await _write_or_refuse(
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
        # The other door `_named` measured and found open. A cycle's frontmatter
        # takes an undeclared key exactly as a record's does, and the file it goes
        # into is the one every date on every page is derived from.
        _reject_undeclared_fields(fields, CYCLE_FIELDS, "a cycle")
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
        written = await _write_or_refuse(
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
                422,
                f"{icon!r} is not an icon: expected one of {', '.join(render.ICONS)}, "
                "or null to clear it",
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

        written = await _write_or_refuse(
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
                413,
                f"that image is {len(data) // 1024} KB; the limit is {MAX_ASSET_BYTES // 1024} KB",
            )
        path, fresh = await _write_or_refuse(store.put_asset, data, IMAGE_TYPES[kind], user.login)
        # The sha goes back to the uploader as well as out to everybody else. The
        # shell's banner suppresses news of a commit the tab made itself, and it
        # can only do that if the request that made it hands the sha back — an
        # upload that only announced popped "The plan changed." over its own paste.
        commit = store.head()
        if fresh:
            await announce(commit, [])
        return JSONResponse({"path": path, "url": f"/{path}", "fresh": fresh, "commit": commit})

    @app.get("/static/{name}")
    def vendored(name: str) -> Response:
        """A vendored file, over HTTP — the one gap Task 6 found: nothing
        served `static/` before this, because every other vendored library is
        read off disk and inlined into a rendered page rather than fetched by
        the browser on its own. `STATIC_ALLOWLIST` is the whole check; `name`
        never reaches a filesystem path except as a key into it, so `..`, an
        encoded slash folded into one path segment, or a name simply not in
        the dict all end here rather than at `vendor._static_dir()`. Not a
        `StaticFiles` mount: this repository has never had one, and a mount's
        whole feature is taking a path from the request — everything else
        here takes an id and derives the path itself instead.
        """
        media_type = STATIC_ALLOWLIST.get(name)
        if media_type is None:
            raise HTTPException(404, "no such vendored file")
        data = (vendor._static_dir() / name).read_bytes()
        return Response(
            data,
            media_type=media_type,
            # Honest here in a way it would not be for a drawing: a vendored
            # file changes only with a release, so a byte-identical `name`
            # really does mean byte-identical content, forever, the same
            # promise `/assets/{name}` makes for a content-addressed upload.
            headers={"cache-control": "public, max-age=31536000, immutable"},
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

    def _drawing_path(name: str) -> str:
        stem, _, suffix = name.rpartition(".")
        if not DRAWING_PATTERN.match(stem) or f".{suffix}" != DRAWING_SUFFIX:
            raise HTTPException(404, "no such drawing")
        return f"{DRAWING_DIR}/{name}"

    async def _drawing_body(request: Request) -> bytes:
        """The bytes of a drawing, checked the way `/api/asset` checks an
        upload, through a narrower door. `IMAGE_TYPES` is untouched — a
        drawing is `image/png` alone, because that is the one format
        Excalidraw exports to this route — and the byte ceiling is
        `MAX_ASSET_BYTES` again rather than a second number that could drift
        from it. The signature check exists because the content-type header
        is what the client claims, not what the bytes are.
        """
        kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if kind != "image/png":
            raise HTTPException(415, "a drawing is a PNG")
        data = await request.body()
        if len(data) > MAX_ASSET_BYTES:
            raise HTTPException(
                413,
                f"that drawing is {len(data) // 1024} KB; the limit is "
                f"{MAX_ASSET_BYTES // 1024} KB",
            )
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(422, "that is not a PNG")
        return data

    @app.get("/drawings/{name}")
    def drawing(name: str, request: Request) -> Response:
        path = _drawing_path(name)
        head = store.head()
        blob = store.blob_id(head, path)
        if blob is None:
            raise HTTPException(404, "no such drawing")
        tag = f'"{blob}"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"etag": tag, "cache-control": "no-cache"})
        data = store.read_asset(head, path)
        if data is None:
            raise HTTPException(404, "no such drawing")
        return Response(
            data,
            media_type="image/png",
            # NOT `immutable`. The asset route earns that header by the name
            # being the hash of the contents, and a drawing's name is its id —
            # the bytes under it change. `no-cache` means revalidate, not do
            # not store, and the ETag turns the revalidation into a 304
            # whenever the drawing has not moved.
            headers={"etag": tag, "cache-control": "no-cache"},
        )

    @app.post("/api/drawing")
    async def draw(request: Request) -> JSONResponse:
        user = writer(request)
        data = await _drawing_body(request)
        # The mint, here and never from the client, for the reason `/api/record`
        # gives: an id supplied by a browser is a path supplied by a browser
        # once it becomes `drawings/<id>.png`. Retried, because unlike a record
        # this CAN check — the path is the id, so there is no `<id>--<slug>`
        # ambiguity, and `put_drawing` does the check under the same lock it
        # writes in. At a thousand drawings the birthday bound is about 3%.
        for _ in range(8):
            drawing_id = f"draw-{secrets.token_hex(3)}"
            path = f"{DRAWING_DIR}/{drawing_id}{DRAWING_SUFFIX}"
            written, blob = await _write_or_refuse(
                store.put_drawing, path, data, None, user.login, f"draw {path}"
            )
            if written.outcome == "committed":
                commit = store.head()
                await announce(commit, [])
                return JSONResponse(
                    {"id": drawing_id, "path": path, "etag": blob, "commit": commit}
                )
        raise HTTPException(500, "could not mint a drawing id")

    @app.put("/api/drawing/{drawing_id}")
    async def redraw(drawing_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        if not DRAWING_PATTERN.match(drawing_id):
            raise HTTPException(404, "no such drawing")
        base = request.headers.get("if-match", "").strip('"')
        if not base:
            raise HTTPException(428, "say which version of the drawing you started from")
        data = await _drawing_body(request)
        path = f"{DRAWING_DIR}/{drawing_id}{DRAWING_SUFFIX}"
        written, blob = await _write_or_refuse(
            store.put_drawing, path, data, base, user.login, f"redraw {path}"
        )
        # Through `_result`, the house shape every other write route answers
        # in, and not a bare `HTTPException(409, written.conflict)`: that
        # serialises as `{"detail": …}`, and the shell's `refusal()` reads
        # `answer.conflict` on a 409 — so a drawing conflict answered in
        # `detail` fell through to the generic "somebody changed this first"
        # instead of the sentence this route means to show.
        if written.outcome == "conflict":
            return _result(written, base)
        commit = store.head()
        await announce(commit, [])
        return JSONResponse({"id": drawing_id, "path": path, "etag": blob, "commit": commit})

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
        # visible.
        unknown = unknown_fields(kind, fields)
        if unknown:
            raise HTTPException(422, f"{_an(kind)} has no {', '.join(unknown)}")

        # The id and the opening fields, from `model.py` — the one copy, shared
        # with `openproj new`. Everything this route knows and that one does not
        # is on this side of the call: a signed-in login to default the author to,
        # and a commit to read the config at.
        record_id = mint_id(kind)
        commit = store.head()
        config, _ = _config_at(store, commit)
        content = patch_text(
            "---\n---\n",
            in_model_order(
                kind,
                opening_fields(kind, fields, config, record_id=record_id, who=user.login),
            ),
            body,
        )
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
        # The same refusal the save route makes, on the other door, and it cannot
        # be left to the list below: what `validate_all` says about a stated date
        # that has passed is a WARNING — nobody typed it, the calendar moved — and
        # this filters to blockers. Somebody typing it into a create form is the
        # other half of that rule and the half a person can act on.
        #
        # With no `before` at all, which is not an omission: a record that does
        # not exist yet has nothing standing in it, so nothing here can have
        # drifted and every value in this candidate is one somebody has just typed.
        _reject_a_start_date_this_write_puts_in_the_past(
            fields, candidate, None, today or date.today()
        )
        _reject_dates_this_write_cannot_mean(fields, candidate, lambda: config)
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

        written = await _write_or_refuse(
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
            # `pushed` as on a PATCH: without it the create path had nothing
            # to hang a "saved here, not on GitHub yet" mark on.
            {
                "id": record_id,
                "outcome": written.outcome,
                "commit": written.commit,
                "pushed": written.pushed,
            },
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
                        json.dumps({"t": "who", "people": room.people(), "where": room.where()})
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

    def _refuse_room(room: coedit.Room, why: str) -> None:
        """One refusal, said to both of the readers it has — every arm of
        `_commit_room` leaves through here, and
        `test_every_refusal_a_room_makes_leaves_through_one_door` holds that,
        because an instruction written three times is one edit away from wording
        one condition three ways, which makes it look like three conditions.

        The frame is for the person who was typing, and it appends the one
        action that works. The audit's four-cell probe
        (`design/probes/concurrency-audit.md`, §4 Loss 3) measured why: a conflict
        leaves `room.base` where it was, every retry re-runs the same merge
        against the same base with a `mine` that only grows, and the join path's
        absorb is gated on `not room.pending()` — false for exactly the stuck
        room — so a reload does not clear it either. The report already names
        the file, the lines and both texts; what it never said is what to DO,
        and 373 characters typed and acknowledged in three browsers reached the
        plan never. Stored on the room with the sentence in it, because the
        join path replays `room.refusal` to whoever arrives next, and they were
        not there to hear this frame.

        The log is for the operator, who has no surface at all otherwise: every
        page answers 200 while a room is wedged and `/api/health` asks the
        store, which is fine. The same split as `_wedged` beside `_refusal` at
        the top of this file, and the same rule — the store's words open both
        surfaces verbatim, and each surface appends only the half it alone can
        say: the frame what to do, the log where to look. The base is in the
        line because it is how a wedged room is told apart from an ordinary
        refusal in the output: the same path refused again at the same base is
        the same stuck merge, not a new one.
        """
        room.refusal = f"{why} {COPY_WORK_OUT}"
        _to_room(room, {"t": "refused", "why": room.refusal})
        # The first line of `why` and never the rest: a conflict report's tail
        # is one line per collision, quoting both sides of the document being
        # typed. On the surface this line exists for, each stderr line is one
        # log entry, so the tail would let anybody in the editor append entries
        # to the operator's log — the `Co-authored-by:` trailer family again —
        # and a scan for "the same path at the same base, repeatedly" would
        # have to reassemble one refusal from many entries first. One line per
        # refusal is the guarantee; the people who need the full report are in
        # the room, and the frame above already carries it to them.
        _LOG.warning(
            "the room on %s refused to commit at base %s with %d editing: %s",
            room.path,
            room.base,
            len(room.members),
            # Guarded because `"".splitlines()` is `[]` and a bare exception can
            # stringify to nothing: an IndexError here escapes the arms that call
            # this and kills the room's timer, which may not happen — see
            # `_commit_room`'s docstring.
            why.splitlines()[0] if why else why,
        )

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
        by the same door instead — `_refuse_room`, into the room's own box for
        the people in it and one WARNING for whoever reads the server's output.
        `_watch` guards itself as well, and the two are not the same guard — see
        the note there.

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
                # A room's text lives in no `localStorage` but the typist's own
                # — everybody else's copy arrived over the socket and was never
                # an `input` event — so the room really is the only place the
                # whole document exists. The "copy it out" instruction used to
                # be written here and here alone; it is `_refuse_room`'s now,
                # said identically on every refusal, and this arm keeps only
                # the part the helper cannot know: that the file itself is gone.
                raise ValueError(
                    f"{room.path} is not in the plan any more, so there is nothing to "
                    "write this against — the room is the only place the document "
                    "exists."
                )
            content = _patched(original, fields, body, room.path)
            # The same gate the PATCH route stands behind, and for the same
            # reason: a record that will not read back takes every page down for
            # everybody, on a branch where the commit cannot be force-pushed away.
            candidate = parse_text(content, room.path)
            # **A room commits frontmatter, not only prose, and that is why this
            # gate is here.** `save()` on the record page ends at
            # `if (COEDIT.live()) { COEDIT.save(fields); return; }` — while the
            # socket is up, which is the ordinary case, the form's fields come
            # through this function and never through `PATCH /api/record`. So a
            # start date typed into the past on the primary editing surface was
            # answered 422 by the door nobody was using and committed by the one
            # everybody was: the same field, the same record, two answers, and the
            # file left saying a ready pitch began last month.
            #
            # It is asked in the DELTA form the other three doors use, and the
            # delta is the whole of what was wrong with the version that stood
            # here before. That one asked the parsed candidate alone — "is this
            # record illegal" — and a date that has merely drifted by makes it
            # illegal every second of every day with nobody having touched it. It
            # therefore fired on all three of the ways a room reaches git: Save,
            # the twenty-second quiet window and the last person out. Three people
            # writing a shaping document on a drifted record were told to copy
            # their work out of the editor, and the document existed in the room
            # and in no file until the last tab closed it. In this form a flush
            # carrying no fields cannot be refused by it at all — the timer and the
            # last person out send `{}`, and a body edit is never what makes a date
            # late — so what is refused is the press that typed the date, and the
            # prose stays in the room to be saved again the moment it is corrected.
            #
            # `before` is the record as the file has it at the room's own base,
            # which is what this write is a delta against; the guard is there
            # because a file in git can be anything `patch_text` will round-trip
            # and `parse_text` will not read, and `None` there means the
            # conservative half of the rule, as it does on the create door.
            try:
                before = parse_text(original, room.path)
            except ValueError:
                before = None
            _reject_a_start_date_this_write_puts_in_the_past(
                fields, candidate, before, today or date.today()
            )
            # The room is the surface people actually edit on, so it gets every
            # rule the PATCH door has or it is the one door with none. A flush
            # that carries no fields carries no date either, and falls straight
            # through — see the delta argument above, which is this rule's too.
            _reject_dates_this_write_cannot_mean(
                fields, candidate, lambda: _config_at(store, room.base)[0]
            )

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
                _refuse_room(room, written.conflict)
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
            _refuse_room(room, why)
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
            _refuse_room(room, why)

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
        refused: HTTPException | None = None
        try:
            user = writer(socket)  # type: ignore[arg-type]
            head = store.head()
            path = _path_for(store, head, record_id)
        except HTTPException as error:
            # Not signed in, not a member, no such record, or two files claiming
            # one id. A reader who may not write gets exactly today's editor —
            # that is the case this whole feature is designed to degrade into —
            # but the page has to be able to tell that apart from a socket that
            # merely dropped, and the sentence is how it does.
            refused, path = error, None
        if path is None:
            await _refuse_socket(socket, refused, record_id)
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
                        # Here rather than only in `_commit_room`, which stands
                        # behind this and would refuse the same key: this is where
                        # the refusal reaches the person who typed it, as a
                        # sentence in their own room, instead of arriving as a
                        # failed commit with nothing said about which key.
                        _reject_undeclared_fields(fields, RECORD_FIELDS, "a record")
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
