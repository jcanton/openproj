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
`projects|pitches|tasks/<id>.md` is the shape of it, and every path added since
is admitted the same way and by nothing else: `cycles/<n>.md` by a number,
`issues/<id>.md` and `notes/<id>.md` by their own patterns, `assets/<sha>` by the
hash of the bytes, and `people/<login>.md` by `model.LOGIN_PATTERN` (see
`PUT /api/icon`). No route takes a path, a directory or a file name from a
request — `POST /api/promote` writes two files and takes neither of their names,
because a record id and a kind decide both. This matters more than
usual because branch protection means a bad write cannot be force-pushed away
afterwards.

**A save preserves the file.** Only touched fields travel, and `patch_text` applies
them through a round-trip loader so comments, key order and list style survive.

**A refusal writes nothing.** A conflict is a 409 carrying a rendered report with
no conflict markers in it, because a marker that reaches the client reaches a
textarea and is then saved back.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import secrets
import threading
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from . import render
from .auth import (
    OAuthError,
    User,
    exchange_code,
    identify,
    login_url,
    read_session,
    sign_session,
)
from .index import build_index
from .model import (
    CONFIG_FILES,
    ISSUE_STATUS,
    NOTE_ID_PATTERN,
    NOTE_STATUS,
    PEOPLE_DIR,
    Config,
    Cycle,
    Entity,
    Issue,
    Note,
    Person,
    Pitch,
    Project,
    Task,
    Unreadable,
    parse_cycle_text,
    parse_issue_text,
    parse_note_text,
    parse_person_text,
    parse_text,
    patch_text,
    person_path,
    promoted_from,
    read_config,
    readable,
    record_paths_in,
    shaping_document,
    validate_all,
    what_json_can_carry,
    why_it_will_not_read,
)
from .store import Store

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

ID_PATTERN = re.compile(r"^(proj|pitch|task)-[0-9a-f]{6}$")
DIRECTORY = {"project": "projects", "pitch": "pitches", "task": "tasks"}
PREFIX = {"project": "proj", "pitch": "pitch", "task": "task"}

# Starlette does not bound a request body and Cloud Run will happily carry 32 MB.
# A blob committed to git is permanent and branch protection blocks the force-push
# that would take it back out, so the only place to stop it is before the commit.
MAX_BODY_BYTES = 256 * 1024
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
# ID_PATTERN rather than folded into it: the entity id pattern is what keeps the
# writable surface closed by construction, and widening it to admit a fourth
# shape is how that property gets lost by degrees.
CYCLE_PATTERN = re.compile(r"^[0-9]{1,4}$")
ISSUE_DIR = "issues"
ISSUE_ID_PATTERN = re.compile(r"^issue-[0-9a-f]{6}$")
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


def _cycles_at(store: Store, commit: str) -> tuple[list[Cycle], list[Unreadable]]:
    paths, too_deep = record_paths_in([CYCLE_DIR], store.paths(commit))
    plans, refused = readable(paths, lambda path: parse_cycle_text(store.read(commit, path), path))
    return plans, [*refused, *too_deep]


def _cycle_path(number: int) -> str:
    return f"{CYCLE_DIR}/{number:04d}.md"


def _issues_at(store: Store, commit: str) -> tuple[list[Issue], list[Unreadable]]:
    paths, too_deep = record_paths_in([ISSUE_DIR], store.paths(commit))
    issues, refused = readable(paths, lambda path: parse_issue_text(store.read(commit, path), path))
    return issues, [*refused, *too_deep]


def _issue_path(issue_id: str) -> str:
    """The one place an issue id becomes part of a path.

    Checked against its own pattern rather than against the entity one: entity
    ids decide `projects|pitches|tasks/<id>.md`, and admitting a fourth shape
    there would widen the surface that regex exists to keep closed.
    """
    if not ISSUE_ID_PATTERN.match(issue_id):
        raise HTTPException(400, f"{issue_id!r} is not an issue id")
    return f"{ISSUE_DIR}/{issue_id}.md"


NOTE_DIR = "notes"


def _notes_at(store: Store, commit: str) -> tuple[list[Note], list[Unreadable]]:
    paths, too_deep = record_paths_in([NOTE_DIR], store.paths(commit))
    notes, refused = readable(paths, lambda path: parse_note_text(store.read(commit, path), path))
    return notes, [*refused, *too_deep]


def _note_path(note_id: str) -> str:
    """The one place a note id becomes part of a path.

    `NOTE_ID_PATTERN` is imported from `model` rather than written out again here
    the way the issue pattern above is. The same regex decides what the validator
    calls a legal id and what this concatenates into `notes/<id>.md`, and two
    copies of that rule is how the surface it keeps closed gets opened by degrees
    — the check being in two files is exactly what let `people/team/ann.md` be a
    record to one half of this application and not to the other.
    """
    if not NOTE_ID_PATTERN.match(note_id):
        raise HTTPException(400, f"{note_id!r} is not a note id")
    return f"{NOTE_DIR}/{note_id}.md"


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
    paths, too_deep = record_paths_in([PEOPLE_DIR], store.paths(commit))
    people, refused = readable(
        paths, lambda path: parse_person_text(store.read(commit, path), path)
    )
    return people, [*refused, *too_deep]


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
    issues, refused_issues = _issues_at(store, commit)
    notes, refused_notes = _notes_at(store, commit)
    people, refused_people = _people_at(store, commit)
    return (
        config.with_plans(plans).with_issues(issues).with_notes(notes).with_people(people),
        [*refused, *refused_plans, *refused_issues, *refused_notes, *refused_people],
    )


def _entities_at(store: Store, commit: str) -> tuple[list[Entity], list[Unreadable]]:
    paths, too_deep = record_paths_in(DIRECTORY.values(), store.paths(commit))
    entities, refused = readable(paths, lambda path: parse_text(store.read(commit, path), path))
    return entities, [*refused, *too_deep]


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
_LISTS = ("assignees", "reviewers", "tags", "prs", "depends_on", "shaped_by")


def _reject_bad_issue(fields: dict) -> None:
    """A form returns strings, and an issue's fields are few enough to name."""
    unknown = sorted(set(fields) - set(Issue.model_fields))
    if unknown:
        raise HTTPException(422, f"an issue has no {', '.join(unknown)}")
    for name in ("tags", "pitched_into"):
        if name in fields and not isinstance(fields[name], list):
            raise HTTPException(422, f"{name} must be a list")
    status = fields.get("status")
    if status is not None and status not in ISSUE_STATUS:
        raise HTTPException(422, f"{status!r} is not a status for an issue")


def _reject_bad_note(fields: dict) -> None:
    """A form returns strings, and a note has fewer fields than anything else here.

    Its own function rather than `_reject_bad_issue` with a model argument: the
    two records share a shape today and are meant to diverge — the whole point of
    having both is that they are different questions — and one gate serving two
    vocabularies is a gate that gets a parameter and then an `if` and then admits
    a status to the wrong record.
    """
    unknown = sorted(set(fields) - set(Note.model_fields))
    if unknown:
        raise HTTPException(422, f"a note has no {', '.join(unknown)}")
    for name in ("tags", "became"):
        if name in fields and not isinstance(fields[name], list):
            raise HTTPException(422, f"{name} must be a list")
    status = fields.get("status")
    if status is not None and status not in NOTE_STATUS:
        raise HTTPException(
            422,
            f"{status!r} is not a status for a note: expected one of "
            f"{', '.join(NOTE_STATUS)}. A note that became something is promoted, "
            "which is read off what it became rather than typed.",
        )


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
    entity save learned it when a restored draft began carrying the commit it
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


def _directory_for(entity_id: str) -> str:
    """The directory an id belongs in, or a refusal. The one place an id becomes
    part of a path — everything else must come through here."""
    if not ID_PATTERN.match(entity_id):
        raise HTTPException(400, f"{entity_id!r} is not an entity id")
    prefix = entity_id.split("-")[0]
    kind = next(k for k, p in PREFIX.items() if p == prefix)
    return DIRECTORY[kind]


def _path_for(store: Store, commit: str, entity_id: str) -> str | None:
    """Where this entity's file actually is, at this commit.

    Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    the path cannot be reconstructed from the id — it has to be found. Guessing
    `<id>.md` works on a corpus nobody has renamed and fails on every real one.
    """
    directory = _directory_for(entity_id)
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
        if stem == entity_id or stem.startswith(f"{entity_id}--"):
            found.append(path)
    # Refuse rather than pick. This returned the first match, and "first match
    # wins" is a coin toss about which record a save destroys — the index resolves
    # the same collision the other way, so the file this chose was reliably not the
    # record the page had shown. Two files claiming one id is a blocker the pages
    # now draw; until a person resolves it, no write to that id is safe.
    if len(found) > 1:
        raise HTTPException(
            409,
            f"{', '.join(sorted(found))} both claim {entity_id}. "
            "Rename or remove one in git, then reload — until then a save here "
            "cannot tell which record you meant.",
        )
    return found[0] if found else None


MODELS = {"project": Project, "pitch": Pitch, "task": Task}


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
    app = FastAPI(title="openproj")

    @app.middleware("http")
    async def say_what_this_page_may_do(request: Request, call_next):
        """The four headers, on every response including the JSON and the errors.

        Written here rather than per route because the one that matters is the one
        nobody remembered to add: a 500's body is a traceback, a 404's is a
        sentence somebody typed, and both are documents a browser will render.

        `X-Content-Type-Options` because an asset is bytes somebody uploaded and
        the only thing standing between `image/png` and a document is that nobody
        sniffed it. `Referrer-Policy` because an entity id in a path is the name of
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

    def index_now():
        commit = store.head()
        config, unreadable_config = _config_at(store, commit)
        entities, unreadable_entities = _entities_at(store, commit)
        return commit, build_index(
            entities,
            config,
            date.today(),
            # Sorted by path, because a reader works through the list by opening
            # files and two walks finishing in whatever order is not that order.
            unreadable=sorted(
                [*unreadable_config, *unreadable_entities], key=lambda one: one.path
            ),
        )

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
        """
        user = viewer(request)
        if auth == "dev":
            return user or User(login="dev", member=True)
        if user is None:
            raise HTTPException(401, "sign in to make changes")
        if not user.member:
            raise HTTPException(403, f"{user.login} is not a member of {org}")
        return user

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

    @app.get("/", response_class=HTMLResponse)
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

    @app.get("/issues", response_class=HTMLResponse)
    def issues() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_issues(index, render.ROUTES, commit))

    @app.get("/issue/new", response_class=HTMLResponse)
    def new_issue(request: Request) -> HTMLResponse:
        commit, index = index_now()
        who = viewer(request)
        return page(
            render.render_issue(index, None, render.ROUTES, commit, who.login if who else "")
        )

    @app.get("/issue/{issue_id}", response_class=HTMLResponse)
    def one_issue(issue_id: str, request: Request) -> HTMLResponse:
        commit, index = index_now()
        who = viewer(request)
        try:
            return page(
                render.render_issue(
                    index, issue_id, render.ROUTES, commit, who.login if who else ""
                )
            )
        except KeyError:
            raise HTTPException(404, f"no issue {issue_id!r}") from None

    @app.post("/api/issue")
    async def open_issue(request: Request) -> JSONResponse:
        """Deliberately the shortest write path in the tool.

        Somebody has just noticed something while doing something else. Anything
        this asks for beyond a title is a reason not to write it down at all, so
        the id and the date are the server's and everything else can be filled in
        later or never.
        """
        user = writer(request)
        payload = await request.json()
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(422, "an issue needs a title")

        given = {k: v for k, v in (payload.get("fields") or {}).items()
                 if k not in ("id", "title", "opened_on")}
        _reject_bad_issue(given)
        issue_id = f"issue-{secrets.token_hex(3)}"
        fields = {
            "id": issue_id,
            "title": title,
            "status": "ready",
            # Whoever is signed in, as a default rather than as a fact. The
            # session knows who is writing — it is the same name that becomes the
            # commit's author — and that is right almost every time. It is not
            # right when somebody files what a colleague mentioned in a corridor,
            # so the form can say otherwise.
            "reported_by": user.login,
            **given,
            # `opened_on` stays the server's: it is when this record was made,
            # which is not an opinion.
            "opened_on": date.today().isoformat(),
        }
        content = patch_text("---\n---\n", fields, payload.get("body") or "")
        parse_issue_text(content, issue_id)
        written = store.write(
            path=_issue_path(issue_id),
            content=content,
            base_commit=payload.get("base_commit") or store.head(),
            author=user.login,
            message=f"{issue_id}: open",
        )
        if written.commit:
            await announce(written.commit, [issue_id])
        return JSONResponse({"id": issue_id, "commit": written.commit})

    @app.patch("/api/issue/{issue_id}")
    async def save_issue(issue_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        payload = await request.json()
        body = payload.get("body")
        if body is not None and len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise HTTPException(413, "that body is too large to commit")

        base = payload["base_commit"]
        path = _issue_path(issue_id)
        original = store.read(base, path)
        if original is None:
            raise HTTPException(404, f"no issue {issue_id!r}")

        fields = {k: v for k, v in (payload.get("fields") or {}).items() if k != "id"}
        _reject_bad_issue(fields)
        content = patch_text(original, fields, body)
        # Read back before it is written: a file the loader cannot parse would
        # take the issues page with it, and it would already be in git.
        parse_issue_text(content, path)
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{issue_id}: {', '.join(fields) or 'body'}",
        )
        if written.commit:
            await announce(written.commit, [issue_id])
        return _result(written, base)

    @app.get("/notes", response_class=HTMLResponse)
    def notes() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_notes(index, render.ROUTES, commit))

    @app.get("/note/new", response_class=HTMLResponse)
    def new_note(request: Request) -> HTMLResponse:
        commit, index = index_now()
        who = viewer(request)
        return page(
            render.render_note(index, None, render.ROUTES, commit, who.login if who else "")
        )

    @app.get("/note/{note_id}", response_class=HTMLResponse)
    def one_note(note_id: str, request: Request) -> HTMLResponse:
        commit, index = index_now()
        who = viewer(request)
        try:
            return page(
                render.render_note(index, note_id, render.ROUTES, commit, who.login if who else "")
            )
        except KeyError:
            raise HTTPException(404, f"no note {note_id!r}") from None

    @app.post("/api/note")
    async def write_note(request: Request) -> JSONResponse:
        """The shortest write path in the tool, and shorter than the issue's.

        Somebody is in the middle of thinking. Every field this asks for is a
        reason to close the tab instead, so it asks for a title and the server
        supplies the rest.
        """
        user = writer(request)
        payload = await _sent(request)
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(422, "a note needs a title, even a bad one")

        given = {k: v for k, v in _fields_in(payload).items()
                 if k not in ("id", "title", "written_on")}
        _reject_bad_note(given)
        note_id = f"note-{secrets.token_hex(3)}"
        fields = {
            "id": note_id,
            "title": title,
            "status": "thinking",
            # Whoever is signed in, as a default rather than as a fact — the same
            # bargain the issue makes. It is who to ask, and the form can say
            # somebody else wrote the thing down at the whiteboard.
            "written_by": user.login,
            **given,
            # The server's, because when this was written down is not an opinion.
            "written_on": date.today().isoformat(),
        }
        content = patch_text("---\n---\n", fields, _body_in(payload) or "")
        parse_note_text(content, note_id)
        written = store.write(
            path=_note_path(note_id),
            content=content,
            base_commit=payload.get("base_commit") or store.head(),
            author=user.login,
            message=f"{note_id}: write down",
        )
        if written.commit:
            await announce(written.commit, [note_id])
        return JSONResponse({"id": note_id, "commit": written.commit})

    @app.patch("/api/note/{note_id}")
    async def save_note(note_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        if body is not None and len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise HTTPException(413, "that body is too large to commit")

        base = _base_in(store, payload)
        path = _note_path(note_id)
        original = store.read(base, path)
        if original is None:
            raise HTTPException(404, f"no note {note_id!r}")

        fields = {k: v for k, v in _fields_in(payload).items() if k != "id"}
        _reject_bad_note(fields)
        # Through `_patched` and not a bare `patch_text`: the file being edited
        # came out of git and can be anything, and a frontmatter whose YAML never
        # closes is a ruamel error under the router — a 500 with a plain-text
        # body, which is the one answer this page cannot read back.
        content = _patched(original, fields, body, path)
        # Read back before it is written: a file the loader cannot parse would
        # take the notes page with it, and it would already be in git.
        parse_note_text(content, path)
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{note_id}: {', '.join(fields) or 'body'}",
        )
        if written.commit:
            await announce(written.commit, [note_id])
        return _result(written, base)

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
        `from_note` on `Entity` would put a note id into the type every view of
        the plan is built from, and the table, the graph and the detail page would
        each have to decide what to do with it — which is exactly the coupling
        that keeping notes out of `Entity` exists to prevent. Prose cannot drift
        out of step with anything, because nothing reads it but a person.

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
        id matched against its own pattern, and a kind out of `DIRECTORY`. No
        path, no directory, no file name, no field, no body.
        """
        user = writer(request)
        payload = await _sent(request)
        source_id = str(payload.get("source") or "")
        kind = payload.get("kind")

        if NOTE_ID_PATTERN.match(source_id):
            inbox, path, link = "note", _note_path(source_id), "became"
        elif ISSUE_ID_PATTERN.match(source_id):
            inbox, path, link = "issue", _issue_path(source_id), "pitched_into"
        else:
            raise HTTPException(400, f"{source_id!r} is not a note or an issue")
        # One phrase, used by the refusal and by the citation the promoted
        # document carries. Written twice they drift, and one of the two is prose
        # that ends up committed to the plan.
        article = "an issue" if inbox == "issue" else "a note"
        if kind not in render.PROMOTABLE[inbox]:
            raise HTTPException(
                422,
                f"{article} becomes {' or '.join(render.PROMOTABLE[inbox])}, not {kind!r}",
            )

        base = _base_in(store, payload) if payload.get("base_commit") else store.head()
        original = store.read(base, path)
        if original is None:
            raise HTTPException(404, f"no {inbox} {source_id!r}")
        # Parsed rather than read out of the index, because the index is at HEAD
        # and this is at the commit the page was rendered at — and a promotion
        # carries the body somebody was looking at, not one that moved under them.
        source = (
            parse_note_text(original, path) if inbox == "note"
            else parse_issue_text(original, path)
        )
        who = source.written_by if inbox == "note" else source.reported_by
        when = source.written_on if inbox == "note" else source.opened_on

        entity_id = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        commit = store.head()
        config, _ = _config_at(store, commit)
        content = patch_text(
            "---\n---\n",
            {
                "id": entity_id,
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
            candidate = parse_text(content, entity_id)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as an entity: {why_it_will_not_read(error)}"
            ) from None
        blockers = [
            problem
            for problem in validate_all([*_entities_at(store, commit)[0], candidate], config)
            if problem.entity_id == entity_id and problem.severity == "blocker"
        ]
        if blockers:
            return JSONResponse(
                {"problems": [p.model_dump(mode="json") for p in blockers]}, status_code=422
            )

        # Appended, not replaced: a note that split into two pitches is the normal
        # case, and it is the reason both fields are lists.
        marked = _patched(original, {link: [*getattr(source, link), entity_id]}, None, path)
        # Read back before it is written, the refusal every write path here makes.
        # This one has the least to go wrong — the file parsed four lines up and
        # gains one list of ids — and it is the write that must not half-happen,
        # so it is checked rather than assumed.
        try:
            (parse_note_text if inbox == "note" else parse_issue_text)(marked, path)
        except ValueError as error:
            raise HTTPException(
                422,
                f"that would not read back as {article}: {why_it_will_not_read(error)}",
            ) from None
        written = store.write_all(
            {f"{DIRECTORY[kind]}/{entity_id}.md": content, path: marked},
            base_commit=base,
            author=user.login,
            message=f"{entity_id}: promoted from {source_id}",
        )
        if written.outcome == "conflict":
            return _result(written, base)
        if written.commit:
            await announce(written.commit, [entity_id, source_id])
        return JSONResponse(
            {"id": entity_id, "outcome": written.outcome, "commit": written.commit},
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
    def new(kind: str = "task") -> HTMLResponse:
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        commit, index = index_now()
        return page(render.render_new(kind, commit, render.ROUTES, index))

    @app.get("/detail", response_class=HTMLResponse)
    def detail_index() -> HTMLResponse:
        return page(render.render_detail(index_now()[1], render.ROUTES))

    @app.get("/detail/{entity_id}", response_class=HTMLResponse)
    def detail(entity_id: str) -> HTMLResponse:
        commit, index = index_now()
        if entity_id not in index.entities:
            raise HTTPException(404, f"no entity {entity_id!r}")
        # The page carries the commit it was rendered at, so a save is compared
        # against what the person actually saw rather than against whatever HEAD
        # has become while the tab sat open.
        return page(
            render.render_detail(index, render.ROUTES, only=entity_id, base_commit=commit)
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
        return {"ok": True, "head": store.head()}

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
                    "entities": {i: e.model_dump(mode="json") for i, e in index.entities.items()},
                    "spans": {i: s.model_dump(mode="json") for i, s in index.spans.items()},
                    "explanations": {i: e.text for i, e in index.explanations.items()},
                    "problems": [p.model_dump(mode="json") for p in index.problems],
                    # A script reading this has to be able to tell "the plan
                    # holds sixteen tasks" from "the plan holds sixteen tasks
                    # that parsed", and nothing else in this payload says so.
                    "unreadable": [u.model_dump(mode="json") for u in index.unreadable],
                }
            )
        )

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

    @app.patch("/api/entity/{entity_id}")
    async def save(entity_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        # A commit this repository does not have is a refusal, not a crash. This
        # is the one route that is handed a base older than HEAD by design — a
        # restored draft carries the commit it was drafted against — so a draft
        # that has sat in a browser through a re-clone of the plan arrives with a
        # sha `store.paths` throws on.
        base = _base_in(store, payload)
        path = _path_for(store, base, entity_id)
        if path is None:
            raise HTTPException(404, f"no entity {entity_id!r}")
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
            if problem.entity_id == entity_id
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
            parse_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as an entity: {why_it_will_not_read(error)}"
            ) from None
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{entity_id}: {', '.join(fields) or 'body'}",
        )
        if written.commit:
            await announce(written.commit, [entity_id])
        return _result(written, base)

    @app.put("/api/cycle/{number}")
    async def save_cycle(number: int, request: Request) -> JSONResponse:
        """Create or update one cycle record.

        PUT rather than PATCH because a cycle is set up in one sitting: the whole
        roster is written at once, and a missing name means somebody was removed
        rather than left alone. That is the opposite of an entity's per-field
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
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"cycle {number}: {', '.join(k for k in fields if k != 'cycle') or 'goal'}",
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
        `POST /api/entity` had no type check at all for as long as its sibling
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
        # prose back byte for byte. Through `_patched`, the same helper the entity
        # and cycle saves use, because a file in git can be anything and an
        # unguarded `patch_text` over one is a ruamel error under the router — a
        # 500 whose body is plain text, which is the one answer the picker cannot
        # read back to say what happened.
        content = _patched(original or "---\n---\n", {"icon": icon}, None, path)
        candidate, why = _person_or_why(content, path)
        if candidate is None:
            raise HTTPException(422, f"that would not read back as a person: {why}")

        written = store.write(
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
        path, fresh = store.put_asset(data, IMAGE_TYPES[kind], user.login)
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

    @app.post("/api/entity")
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

        # A pitch has an appetite and a task has an effort. The create page carries
        # every kind's fields and hides the ones that do not apply, so what belongs
        # to this kind is decided here rather than by which controls a script left
        # visible: fields are written to the file before the model ever sees them,
        # and a key the model does not own would sit in the frontmatter unread.
        allowed = set(MODELS[kind].model_fields)
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise HTTPException(422, f"a {kind} has no {', '.join(unknown)}")

        # Minted here, never accepted from the client: an id supplied by a browser
        # is a path supplied by a browser once it becomes `tasks/<id>.md`.
        entity_id = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        commit = store.head()
        config, _ = _config_at(store, commit)
        fields["id"] = entity_id
        # Grandfathering protects the corpus that already exists, not the entity
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
            candidate = parse_text(content, entity_id)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as an entity: {why_it_will_not_read(error)}"
            ) from None
        problems = [
            p
            # A file already in the plan that will not parse is not this entity's
            # problem and must not stop it being created: the validator only
            # needs the neighbours it can read, and the banner is what says the
            # rest are missing.
            for p in validate_all([*_entities_at(store, commit)[0], candidate], config)
            if p.entity_id == entity_id and p.severity == "blocker"
        ]
        if problems:
            return JSONResponse(
                {"problems": [p.model_dump(mode="json") for p in problems]}, status_code=422
            )

        written = store.write(
            path=f"{DIRECTORY[kind]}/{entity_id}.md",
            content=content,
            # A base is optional here — a create has nothing to be stale against
            # — but one that was sent has to be real, because `store.write` reads
            # at it the moment HEAD has moved, which is exactly when a person
            # with an old tab open presses New.
            base_commit=_base_in(store, payload) if payload.get("base_commit") else commit,
            author=user.login,
            message=f"{entity_id}: create",
        )
        if written.commit:
            await announce(written.commit, [entity_id])
        if written.outcome == "conflict":
            return _result(written, commit)
        return JSONResponse(
            {"id": entity_id, "outcome": written.outcome, "commit": written.commit},
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
