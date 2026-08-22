"""Entities, configuration and validation.

Parse permissively, validate strictly: every entity field is optional at the type
level so that a hand-edited file with a missing field still loads. Requiredness
lives in `validate_all`, never in the parse types — see spec section 5.2.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable, Iterable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, NamedTuple

import networkx as nx
from frontmatter.default_handlers import YAMLHandler
from pydantic import BaseModel, PrivateAttr, ValidationError, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml", "people.yaml")
_CYCLE_DIR = "cycles"
_ISSUE_DIR = "issues"
_NOTE_DIR = "notes"
PEOPLE_DIR = "people"
_WORKING_DAYS_PER_WEEK = 5
# Calendar days from a betting table to the review meeting when a record does not
# say. Four weeks is what the team runs; the point of storing the date is that
# this number is only ever a guess, so it is used and then said out loud.
_DEFAULT_BUILD_DAYS = 28

# Python's `date` spans years 1 to 9999 and every way of leaving that range
# raises instead of saturating, so this is the widest move any of the two
# functions below can be asked for.
CALENDAR_DAYS = (date.max - date.min).days

# The largest body this tool will put in git. Starlette does not bound a request
# body and Cloud Run will happily carry 32 MB; a blob committed to git is
# permanent and branch protection blocks the force-push that would take it back
# out, so the only place to stop it is before the commit.
#
# Here rather than in `web.py`, where it was written, because it now has a second
# reader: the editor's status bar says how long a document is, and has to say
# when it is too long to save rather than letting a person find out from a 413
# after pressing Save. A ceiling written out twice is the defect this repository
# already paid for once — `MAX_UPDATE_BYTES` and this were both spelled
# `256 * 1024` in two files, one bounding a socket frame and one bounding what
# may be committed, and because a Yjs update is always larger than the text
# inside it the transport refused a body the policy would have taken, in silence.
# The transport bound is still derived from this one in `web.py`, and the number
# the page draws is now this object rather than a third copy of the digits.
MAX_BODY_BYTES = 256 * 1024


def within_the_calendar(days: float) -> float:
    """`days`, bounded by the length of the calendar so that rounding it cannot raise.

    `round()` and `math.ceil()` both raise on infinity, and a length in weeks is
    a float that a hand-edited file may write as `.inf` — `person_weeks: .inf`
    reached `math.ceil` inside the scheduler's own calendar guard and took every
    page down, which is the guard falling over rather than guarding. So the
    bound goes before the rounding, never after it.

    Both ends, because a range has two of them and this bounded one. `.inf` was
    the value that was found, so `.inf` was the value that was fixed;
    `effort_weeks: -.inf` is one character away in the same hand-edited file, it
    walked straight through the `min` below, and `math.ceil(-inf)` is the same
    OverflowError out of the same guard — every page 500, off a file already
    committed. The upper bound alone was never the property this function
    claimed; it was the half of it the crash happened to arrive from.

    The constant comes first in both comparisons because NaN loses every one of
    them: `min(CALENDAR_DAYS, nan)` is the constant, `min(nan, CALENDAR_DAYS)` is
    the NaN. A size of `inf - inf` is one subtraction away and rounds no better.
    """
    return max(-CALENDAR_DAYS, min(CALENDAR_DAYS, days))


def what_json_can_carry(data: object) -> object:
    """`data` with every non-finite float replaced by null.

    JSON has no infinity and no NaN. Python's encoder papers over that by
    writing the JavaScript literals `Infinity`, `-Infinity` and `NaN` — which
    `json.dumps` accepts and `JSON.parse` rejects, so the two ends of every page
    disagreed about what a payload even was. One `effort_weeks: .inf` edited
    into a file by hand and the whole plan vanished from the table behind "This
    page arrived without its data", which blames the network for a number, and
    `/api/index.json` answered 500 to every reader. The pages themselves render:
    `within_the_calendar` above already keeps the arithmetic on its feet. It is
    only the trip out that has no way to say it.

    Null rather than the calendar bound, and null rather than a refusal. Null is
    the true statement — JSON cannot carry this number — and it is what every
    page already draws as a dash. Clamping would put a number nobody wrote into
    a cell, and refusing would take down the page for a file that is already
    committed, which is the failure this whole path exists to avoid. NaN has no
    nearest representable value at all, so it settles the question for both.
    """
    if isinstance(data, float) and not math.isfinite(data):
        return None
    if isinstance(data, dict):
        return {key: what_json_can_carry(value) for key, value in data.items()}
    if isinstance(data, list):
        return [what_json_can_carry(value) for value in data]
    return data


def days_after(day: date, days: float) -> date:
    """`day` moved `days` calendar days, stopping at the ends of the calendar.

    The one place a date moves, and the reason it is one place: `day +
    timedelta(days=n)` raises OverflowError the moment the answer leaves years
    1 to 9999, every page is built from one index, so a single committed number
    that walks off the calendar answers 500 on all of them at once — on a
    protected branch, so the commit cannot be force-pushed away and the repair
    has to be crafted against a sha the 500ing pages will not hand over.
    `schedule.py` learned that and guarded its own copy; the three other places
    that added days to a date did not, so the question is answered here for all
    of them.

    `date.max` rather than an exception, and `days` rounded rather than
    refused: this is a drawing and scheduling primitive, and a primitive that
    raises is the 500. `date.max` is not a date anybody plans against, so a
    caller can read it as "as far as the calendar goes" with no second return
    value — which is what `working_days_after` already returns for work that
    does not fit.
    """
    days = within_the_calendar(days)
    if days > (date.max - day).days:
        return date.max
    if days < -(day - date.min).days:
        return date.min
    return day + timedelta(days=round(days))


class Problem(BaseModel):
    """One validation finding, carrying the rule version that introduced it.

    `rule_version` is what makes grandfathering possible: an entity is only
    blocked by rules that existed when it was created.
    """

    severity: Literal["blocker", "warning"]
    entity_id: str
    field: str | None
    message: str
    rule_version: int


ISSUE_STATUS = ("ready", "in_progress", "done", "shelved")


class Issue(BaseModel):
    """Something somebody noticed, before anybody has decided to do it.

    Stored as `issues/<id>.md`, and deliberately NOT an Entity. An entity is a
    bet: it carries an appetite, takes a place on the timeline and charges
    somebody's cycle. An issue is the opposite — most of them will never be
    worked on, which is the point of having somewhere to put them. Making it a
    separate type is what keeps it off the table, the graph, the people page and
    the timeline by construction, rather than by an exclusion in each of them
    that somebody later forgets.

    There is no `shaping`: shaping happens in the record an issue is promoted
    into and never in the issue itself, so a status for it here would be a second
    place to say what `pitched_into` already says. What it is promoted into is a
    pitch when the fix is worth a bet and a task when it is only worth doing —
    see `render.PROMOTABLE`, which offered pitch alone until a one-line fix had
    to be written up as a bet to get out of this inbox.
    """

    id: str
    title: str
    status: str = "ready"
    reported_by: str | None = None
    opened_on: date | None = None
    tags: list[str] = []
    # The pitches and tasks this was pitched into. One direction only: an entity
    # does not list its issues, because two directions for one edge disagree the
    # first time somebody edits the wrong end.
    pitched_into: list[str] = []
    body: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Parse permissively, validate strictly — the same bargain entities make.
        A word nobody defined is a validation problem, not a page that 500s."""
        return value if value is None else str(value)

    def state(self, entities: dict[str, Entity]) -> str:
        """What this issue actually is, given what it was pitched into.

        Derived rather than copied. An issue that has been pitched has been picked
        up, and one whose work is finished is finished — writing that into the
        file as well would be a second copy of a fact the link already carries,
        and the two disagree the moment somebody closes the pitch.

        Deriving is right HERE and was wrong for pull requests, on the same test:
        a link is local, typed by a person, and readable without a credential or a
        network call, and an issue carries no appetite, no capacity and no place
        on the timeline — so being wrong costs one row on one page rather than
        every date for twenty people.

        `shelved` is never overridden. "We are not doing this" is a decision, and
        a link somebody adds afterwards does not reverse it.
        """
        if self.status == "shelved":
            return "shelved"
        linked = [entities[i] for i in self.pitched_into if i in entities]
        if not linked:
            return self.status
        if all(entity.status in ("done", "shelved") for entity in linked):
            return "done"
        return "in_progress"


# Two, and the count is the design.
#
# An issue has four because an issue is a piece of work waiting to be scheduled:
# somebody picks it up, somebody finishes it. A note is not work and never
# becomes work — it becomes a *record* that is work, and then the note is over.
# So the only thing a person decides about a note is whether they are still
# thinking about it, and the only two answers are the two below.
#
# What is deliberately absent:
#
# * No `in_progress`. There is no such thing as working on a note. The moment
#   there is work there is a pitch, a task or a project, and this note points at
#   it — which is `promoted`, and `promoted` is DERIVED from `became` rather than
#   stored, for the same reason an issue's `done` is derived from `pitched_into`:
#   a status stored beside the link that already says it disagrees with the link
#   the first time somebody edits one of them.
# * No `ready`. "This is ready to be shaped" is a promise about a document
#   nobody has written; the button that writes it is one press away, and a status
#   that means "I am about to press that" is a status that goes stale in the
#   minute after somebody sets it.
# * No `done`. A note is not finished, it is answered — by a record somewhere
#   else, or by a decision to stop thinking about it. Both of those are below.
NOTE_STATUS = ("thinking", "dropped")
# Every state a note can be IN, in the order it moves through them: the two above
# that a person sets, plus the one only a promotion can give it. `NOTE_STATUS` is
# what may be written to a file; this is what a page may draw and sort by.
NOTE_STATES = ("thinking", "promoted", "dropped")


class Note(BaseModel):
    """An idea before anybody knows what it is.

    Stored as `notes/<id>.md`, and — like an issue and for the same reason — not
    an Entity. The distinction between the two inboxes is the whole point of
    having two:

        an issue is "we found something existing that is broken";
        a note is "we are thinking of creating something that does not exist and
        our ideas are confused".

    A note is therefore not a pitch in `shaping`, which is the thing it most looks
    like from a distance. A pitch presupposes that you know what you are shaping:
    it has a problem, a solution and an appetite, and it sits on the betting table
    as a bet somebody could take. A note precedes all three. Putting one in the
    table as a `shaping` pitch would make the plan look like it holds bets nobody
    has made, and the appetite column would be empty on a record that has no
    appetite to be missing.

    So it is not an entity: no size, no cycle, no owner, no dates it is placed
    against, no dependencies, no place in the containment tree. It appears on the
    notes page and nowhere else — by construction, because nothing on the table,
    the graph, the timeline or the people page ever sees one, rather than by an
    exclusion in each of them that somebody later forgets.

    The fields it does have are the ones a confused idea can honestly carry:

    * `title` — the best one line anybody has for it yet, and expected to be
      wrong. It is what the promotion carries into the pitch, where it can be
      rewritten by somebody who now knows.
    * `written_by` — who to ask, not who owns it. A note has no owner: an owner
      is a commitment, and the whole claim of this record is that nobody has
      committed to anything. One name and not a list, because "who is thinking
      about this" invites a roster of people who have not agreed to anything,
      which is an assignment wearing a different word.
    * `tags` — how three notes about one subject find each other at the next
      brainstorm. Free text, validated by nothing, and the cheapest useful field
      here.
    * `became` — the records this turned into. See `state`.
    """

    id: str
    title: str
    status: str = "thinking"
    written_by: str | None = None
    written_on: date | None = None
    tags: list[str] = []
    # The entities this note graduated into. One direction only, on the note,
    # exactly as `Issue.pitched_into` is: two directions for one edge disagree the
    # first time somebody edits the wrong end.
    #
    # And it is on the NOTE rather than on the entity for a second reason the
    # issue does not have. A `from_note` field on `Entity` would put a note id
    # into the type every view of the plan is built from, and then the table's
    # facets, the detail page's fact rows and the graph would each have to decide
    # what to do with it — which is precisely the coupling "a note is not an
    # entity" exists to prevent. What the promoted record says about where it came
    # from, it says in its own shaping document, in prose. See `shaping_document`.
    became: list[str] = []
    body: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Parse permissively, validate strictly, the same bargain every record
        here makes. A word nobody defined is a validation problem, not a 500."""
        return value if value is None else str(value)

    def state(self, entities: dict[str, Entity]) -> str:
        """What this note actually is, given what it became.

        Derived from the link rather than stored beside it — `NOTE_STATUS` has the
        argument. Three answers:

        `dropped` first and unconditionally. "We thought about this and we are not
        doing it" was said by a person, and somebody linking a record to it
        afterwards does not un-say it. The same rule `Issue.state` gives `shelved`.

        `promoted` when at least one thing it became is a record that exists. Not
        "all of them": a brainstorm that splits into two pitches is promoted the
        moment either exists, because the only question this page asks is whether
        the idea was acted on. And a link whose target is gone falls back to
        `thinking` rather than claiming a promotion nobody can open — the missing
        id is a warning from `note_problems`, beside the note, where it can be
        fixed.

        Nothing here reads the *status* of what it became. Whether that pitch
        ships is the pitch's business; a note reporting on it would be a second
        copy of the pitch's status, drawn on the one page that has no reason to
        care.
        """
        if self.status == "dropped":
            return "dropped"
        if any(target in entities for target in self.became):
            return "promoted"
        return self.status


class Unreadable(BaseModel):
    """A file in the plan that is not a record, and the reason in one line.

    Deliberately not a `Problem`. A Problem is about an entity: it is keyed by
    entity id, every page hangs it on that entity's row, and the table's headline
    count links to a filter over entities. A file that will not parse has no
    entity — that is precisely what is wrong with it — so keying one to a path
    would add to a count whose filter can never show it, which is the mismatch
    that count was fixed for once already.
    """

    path: str
    why: str


def why_it_will_not_read(error: BaseException, path: str = "") -> str:
    """One line somebody can act on, out of whatever the read threw.

    `str(ValidationError)` is four lines and a documentation URL; a ruamel error
    is a paragraph with a caret drawn under the offending column. What a reader
    standing in front of a banner needs is which field, or which line, and the
    rest is noise that makes the banner unread.

    `path` is stripped off the front when the message already carries it — the
    parse errors raised here name their source, and the banner names the file
    beside the reason, so leaving it in prints the path twice on one line.
    """
    if isinstance(error, ValidationError):
        said = "; ".join(
            f"{'.'.join(str(part) for part in one['loc']) or 'the record'}: {one['msg']}"
            for one in error.errors()
        )
    elif isinstance(error, MarkedYAMLError):
        # The line number is the only thing that makes a YAML error actionable,
        # and it is the part `str()` buries under the drawing.
        where = f", line {error.problem_mark.line + 1}" if error.problem_mark else ""
        said = f"{error.context + ', ' if error.context else ''}{error.problem}{where}"
    elif isinstance(error, ValueError):
        said = str(error)
    else:
        # Named rather than swallowed. Anything arriving here is a way of failing
        # nobody has met yet, and "could not be read" with no reason attached is
        # a sentence people learn to skip.
        said = f"{type(error).__name__}: {error}"
    prefix = f"{path}: "
    return said[len(prefix) :] if path and said.startswith(prefix) else said


def readable[T](
    paths: Iterable[str], load: Callable[[str], T]
) -> tuple[list[T], list[Unreadable]]:
    """The records that loaded, and one `Unreadable` for every file that did not.

    The one place a plan file is read, because there were four and not one of
    them had this. `load` does the whole trip — fetch the bytes, decode them,
    scan the YAML, validate the model — since every one of those steps is a way a
    file somebody wrote in git fails, and a guard around only the last of them is
    the guard that was already here.

    Fifteen files proved it: no `---` at all, a flow sequence that never closes,
    a tab where YAML wants spaces, `effort_weeks: three`, `assigned_on: next
    tuesday`, a frontmatter written as a list, a cycle numbered `forty-one`, a
    config file that is half a line. Every one of them answered 500 on `/`,
    `/graph`, `/timeline`, `/people`, `/cycles`, `/detail`, `/new` and
    `/api/index.json` at once — not the page that shows the file, every page, for
    every reader, until somebody with a terminal fixed it. `openproj check`, the
    tool you would reach for to find out which file, died with a traceback on the
    first one and never mentioned the second.

    `except Exception`, and this is the one place in the codebase that earns it.
    The failures are not one family and cannot be enumerated: `no YAML
    frontmatter` is a ValueError raised twenty lines below, an unclosed flow
    sequence is a ruamel ParserError, a size spelled as a word is a pydantic
    ValidationError, bytes that are not UTF-8 are a UnicodeDecodeError out of the
    decode, and a frontmatter written as a list reached `.get` as an
    AttributeError. A tuple of the ones that have been seen is a denylist, and
    the cost of missing the next spelling is every page for everybody — which is
    the failure this function exists to end. What each one *says* is
    `why_it_will_not_read`'s problem, and it names the type for anything it does
    not recognise, so nothing is lost by catching broadly here.
    """
    records: list[T] = []
    refused: list[Unreadable] = []
    for path in paths:
        try:
            records.append(load(path))
        except Exception as error:  # noqa: BLE001 - see above; this is the file boundary
            refused.append(Unreadable(path=path, why=why_it_will_not_read(error, path)))
    return records, refused


def record_paths_in(
    directories: Iterable[str], paths: Iterable[str]
) -> tuple[list[str], list[Unreadable]]:
    """The record paths in these plan directories, and one `Unreadable` for every
    markdown file below them that is nested too deep to be one.

    A plan directory holds one file per record and does not nest. That is not a
    convention, it is what the rest of the code already assumes: `login_of` reads
    a person's login off the filename, `_path_for` (`web.py`) reads an entity's id
    off it, and `person_path` and `_cycle_path` write one flat name. The server
    read the same tree by asking whether the FIRST path segment was `people` —
    which is true of `people/team/ann.md` — so a file one directory down became a
    second record for `ann` on every page the server drew, while the CLI globbed
    one level and never saw it. Two halves of one application disagreeing about
    which record is which is worse than either answer on its own, and the one the
    reader gets is decided by which of two paths sorts last.

    Both halves ask this now, so the disagreement cannot come back: `web.py` hands
    it the tree at a commit and `load_repo` hands it an `rglob` of the disk.

    **Reported, not skipped**, which is why it lives here beside `readable` and
    returns the same type. A plan file that is not a record costs that file and
    nothing else, and every page says which file — because the failure that rule
    exists to prevent is not the 500, it is the page that draws fifteen of sixteen
    records and looks completely normal. Ignoring a nested file is that page
    again: somebody committed it on purpose and is waiting to see their icon, and
    nothing anywhere would ever tell them the file is not in the plan. So it is
    named, with the move that fixes it, on every page and in `openproj check`.
    """
    wanted = tuple(directories)
    record_paths: list[str] = []
    too_deep: list[Unreadable] = []
    for path in paths:
        if not path.endswith(".md"):
            continue
        # The directory the file is IN, not the first segment of its path. That
        # substitution is the whole defect.
        below = path.rpartition("/")[0]
        if below in wanted:
            record_paths.append(path)
            continue
        deeper = next((one for one in wanted if below.startswith(f"{one}/")), None)
        if deeper:
            too_deep.append(
                Unreadable(
                    path=path,
                    why=f"{deeper}/ holds one file per record and does not nest, so nothing "
                    f"reads this — move it up into {deeper}/ or out of the plan",
                )
            )
    return record_paths, too_deep


class Cycle(BaseModel):
    """One cycle, as the betting table sets it up.

    Stored as `cycles/<number>.md`, frontmatter and a body, so it reuses the whole
    existing write path — per-key frontmatter merge, three-way body merge, scoped
    compare-and-swap. `goal` is the field the betting table settles; the body is
    the notes that accumulate under it.

    **Two dates are stored, and both are meetings.** `starts_on` is the betting
    table and the first day of build; `reviews_on` is the review meeting, which is
    also the brainstorm for the next cycle — build ended the working day before
    it. Everything else about the calendar is worked out from those two.

    Lengths were stored instead, and a length is a prediction of a date somebody
    picks: `starts_on + 4 weeks` cannot know that the review was moved for a
    conference, that the team leaves a month between two cycles, or that a cycle
    over the year-end closure holds a fortnight of building and not four weeks.
    Capacity is `availability × build weeks`, so that last one was the betting
    table's own number being wrong.

    `builds_until`, `ends_on` and `build_weeks` are filled in by
    `Config.with_plans`, which is where the holidays and the neighbouring cycles
    can be seen. They are derived, never parsed and never written.
    """

    cycle: int
    starts_on: date
    # Optional at the type level like everything else: a record written before
    # this field existed still loads, and the resolver assumes a length rather
    # than taking the page down. See `_resolve`.
    reviews_on: date | None = None
    # Fraction of the BUILD weeks, per person. Absent means nobody said
    # otherwise, which is not the same as unavailable — see `_availability_of`.
    availability: dict[str, float] = {}
    # What the cycle is FOR, in a sentence or two, and a field rather than the
    # first line of the body — because the two are written at different moments
    # by different people. The goal is settled at the betting table and then does
    # not move; the notes below it accumulate all cycle. Sharing one box meant the
    # goal was whatever happened to be at the top of a growing document, and
    # nothing could put it above the table where the room is looking.
    goal: str = ""
    # Everything else the room said: why a pitch was left out, what would make it
    # a bet next time. Prose, so it is the body and not a field.
    body: str = ""

    # --- derived by Config.with_plans ---------------------------------------
    builds_until: date | None = None
    ends_on: date | None = None
    build_weeks: float = 0.0
    # Whether the two above were assumed rather than read: no `reviews_on` in the
    # file, or no next cycle to end the cool-down. The page says so rather than
    # printing a date it invented as though somebody had chosen it.
    assumed_review: bool = False
    assumed_end: bool = False

    def capacity(self, who: str, nominal: float = 1.0) -> float:
        """Weeks of work this person can hold in this cycle."""
        return self.availability.get(who, nominal) * self.build_weeks


class Person(BaseModel):
    """One person's own settings, stored as `people/<login>.md`.

    Frontmatter and a body, the same shape as an entity, a cycle and an issue —
    and that shape is the whole argument for this record existing at all. The
    first attempt at icons put them in `config/people.yaml`, which would have been
    the first writable path in this repository that is YAML end to end, and
    `store.write` merges a file as *frontmatter key-by-key plus a line merge of
    the prose below it*. Route whole-file YAML through that and two edits nobody
    would call a disagreement — they add a name to the roster, I clear my icon —
    line-merge into something that is not YAML at all, commit with a 200, and take
    the roster and everybody's icon down on every page at once. Here the settings
    ARE the frontmatter, so the merge that runs over them is the structured one:
    it cannot produce a file the model will not read, because it never produces
    text — it dumps a map.

    The second property is better still. One record per person means two people
    picking an icon at the same moment write two different paths, and
    compare-and-swap in `store.py` is scoped to the path. The concurrency that
    killed the first attempt does not get handled here; it stops existing.

    **The login is in the path and nowhere else**, which is a deliberate break
    with the other three record types. They carry their id in the frontmatter too,
    and they have to: an id there is minted, opaque and the join key other records
    point at — `parent`, `depends_on`, `pitched_into` — while the filename carries
    a slug that drifts as titles are edited. Nothing points at a person record. It
    is looked up by the one thing that identifies it, which is the login, which is
    the filename. Writing it a second time inside the file would buy nothing and
    would buy in `_identity_problems`: two copies of one fact, resolved in
    opposite directions by two halves of the app, a blocker rule to notice it and
    a special case in the save to refuse over it. `parse_person_text` takes the
    login from the path and ignores a `login:` somebody types into the
    frontmatter, so there is no second answer to disagree with.

    **The body is not a field.** A person record has one below the fence like
    every other record here, and nothing in this codebase reads it or offers a box
    to type it in. That is the decision, not an omission: a body is a good place
    to say who somebody is, and a box nobody fills is furniture on a page — so the
    file keeps the room and the app makes no promise about it. The bytes survive a
    save anyway, and by construction rather than by care: `patch_text` writes the
    fields back over the frontmatter alone, and `_merge_body` line-merges the
    prose. Somebody who writes two sentences about themselves in git keeps them,
    and the day this tool wants to draw them, they are already there.

    Nothing here is a roster. `config/people.yaml`'s `known_people` is the roster,
    it is read by the validator and by the cycle page, and this record neither
    reads nor writes it: a record for somebody off the roster is one person's
    preference, and a roster entry with no record is somebody who has not picked
    an icon. Both are ordinary.
    """

    login: str
    # The name of a drawing, not the drawing. `render.ICONS` decides what the
    # picker offers and what the server accepts, so `git log` reads as a decision
    # and the drawings can be redrawn without touching anybody's choice. A plain
    # `str | None` and not an enum of the names that exist today, for the same
    # reason `status` is a plain `str`: a file written before an icon was renamed
    # has to survive being read, or renaming one takes the People page down for
    # everybody.
    icon: str | None = None

    @field_validator("icon", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Parse permissively, validate strictly — the same bargain every other
        record makes. `icon: 7` is somebody's hand edit, and the cost of it should
        be a name nothing draws rather than a file that will not load."""
        return value if value is None else str(value)


class Config(BaseModel):
    """Repository-wide planning configuration.

    `schema_version` is the version NEW entities are created at, which is not
    necessarily the version the existing corpus was written at.
    """

    schema_version: int = 1
    nominal_availability: float = 1.0
    default_task_effort: float = 0.5
    # Shape Up's cool-down is not build time, so a bet that lands in it did not
    # fit its box. The overrun is measured against the end of BUILD, and this is
    # how many weeks of the window are not build.
    cooldown_weeks: float = 2.0
    holidays: list[date] = []
    cycles: dict[int, tuple[date, date]] = {}
    # The roster, from config/people.yaml. Empty means the check is off, which is
    # the right default: a tracker that refuses a name because nobody has written
    # a roster yet is a tracker nobody finishes setting up.
    known_people: list[str] = []
    # Keyed by cycle number. Loaded from `cycles/*.md`, not from a config file.
    plans: dict[int, Cycle] = {}
    issues: dict[str, Issue] = {}
    notes: dict[str, Note] = {}
    # Keyed by login. Loaded from `people/*.md`, and deliberately not from the
    # roster above: this is what each person chose for themselves, and the roster
    # is who the team says is on it. Neither answers the other's question, and a
    # login in one and not the other is the normal state of both.
    people: dict[str, Person] = {}

    def with_people(self, people: list[Person]) -> Config:
        """Carried on the config for the same reason cycles and issues are:
        nothing iterates people records, one page looks them up, and threading a
        fourth value through every caller to be dropped by all but one of them is
        the shape this already rejected twice."""
        return self.model_copy(update={"people": {person.login: person for person in people}})

    def with_issues(self, issues: list[Issue]) -> Config:
        """Carried on the config for the same reason cycles are: nothing iterates
        issues except the one page that is about them, and every other caller
        would have had to thread a third value through and then drop it."""
        return self.model_copy(update={"issues": {i.id: i for i in issues}})

    def with_notes(self, notes: list[Note]) -> Config:
        """Carried on the config for the reason issues are, one page and no
        iteration — and it earns it twice over here, because a note is the record
        the rest of this module has the least business knowing about."""
        return self.model_copy(update={"notes": {n.id: n for n in notes}})

    def with_plans(self, plans: list[Cycle]) -> Config:
        """A cycle record supersedes `config/cycles.yaml` for its own number.

        Both exist on purpose: the YAML is how the dates were kept before there
        were records, and a repository part-way through will have some of each.

        This is also where each record's derived dates are worked out, because it
        is the only place that can see all three things they need: the holidays,
        the record itself, and the cycle after it.
        """
        resolved = [self._resolve(c, plans) for c in plans]
        windows = dict(self.cycles) | {c.cycle: (c.starts_on, c.ends_on) for c in resolved}
        return self.model_copy(
            update={"cycles": windows, "plans": {c.cycle: c for c in resolved}}
        )

    def _resolve(self, plan: Cycle, plans: list[Cycle]) -> Cycle:
        """One record's derived dates and its length in working weeks.

        The cool-down runs from the review meeting to the next cycle's betting
        table, and that date is stored once — on the next cycle. Two copies of one
        date disagree the first time somebody moves a betting table, which is the
        argument that keeps `blocks` derived too. With no next record it falls
        back to a fortnight and says the date was assumed.
        """
        assumed_review = plan.reviews_on is None
        # Build ends the working day BEFORE the review: you review what was
        # finished before you walked in.
        reviews_on = plan.reviews_on or days_after(plan.starts_on, _DEFAULT_BUILD_DAYS)
        builds_until = max(plan.starts_on, self.previous_working_day(reviews_on))

        after = sorted(c.starts_on for c in plans if c.starts_on > plan.starts_on)
        assumed_end = not after
        ends_on = (
            days_after(after[0], -1)
            if after
            else days_after(reviews_on, round(self.cooldown_weeks * 7) - 1)
        )
        return plan.model_copy(
            update={
                "builds_until": builds_until,
                # A cool-down cannot end before the build it follows: a next cycle
                # starting inside this one is a planning mistake, and it must cost
                # that date rather than every span drawn against the window.
                "ends_on": max(builds_until, ends_on),
                "build_weeks": self.working_weeks(plan.starts_on, builds_until),
                "assumed_review": assumed_review,
                "assumed_end": assumed_end,
            }
        )

    def is_working_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def previous_working_day(self, day: date) -> date:
        """The last working day strictly before `day`, floored at the calendar."""
        day = days_after(day, -1)
        while day > date.min and not self.is_working_day(day):
            day = days_after(day, -1)
        return day

    def next_working_day(self, day: date) -> date:
        """The first working day strictly after `day`, capped at the calendar."""
        day = days_after(day, 1)
        while day < date.max and not self.is_working_day(day):
            day = days_after(day, 1)
        return day

    def working_weeks(self, first: date, last: date) -> float:
        """Working days in an inclusive span, in weeks of five.

        This is what capacity is charged against, so it is the one number that
        has to know about Christmas: a cycle over the ETH closure holds less work
        than one in March, and a length in weeks could not say so.

        Counted a week at a time rather than a day at a time, because the walk is
        over dates a person typed: `reviews_on: 9999-12-31` is one save away and
        a day loop over it is 2.9 million iterations inside `load_config`, on the
        read path of every page. Whole weeks contribute five days each whatever
        they contain, so only the remainder and the holidays are looked at.
        """
        if last < first:
            return 0.0
        weeks, rest = divmod((last - first).days + 1, 7)
        days = weeks * _WORKING_DAYS_PER_WEEK
        days += sum(
            days_after(first, weeks * 7 + offset).weekday() < 5 for offset in range(rest)
        )
        days -= sum(1 for one in self.holidays if first <= one <= last and one.weekday() < 5)
        return round(max(0, days) / _WORKING_DAYS_PER_WEEK, 3)


def _config_mapping(path: str, text: str) -> tuple[str, dict]:
    loaded = YAML(typ="safe").load(text)
    if loaded is None:  # an empty config file is not a broken one
        return path, {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: a config file is a map of settings, and this is not")
    return path, loaded


def read_config(
    paths: Iterable[str], text_of: Callable[[str], str]
) -> tuple[Config, list[Unreadable]]:
    """The merged configuration, and the config files that could not be merged.

    `paths` are repository-relative and are the config files that exist; reading
    them is `text_of`'s job and is done inside the guard, because a config file
    saved in latin-1 is a UnicodeDecodeError before any of this gets a look at it.

    Validated after each file rather than once at the end. "The configuration is
    invalid" names no file and leaves a reader four to search; validating the
    merge as it grows says which one broke it. A file that will not merge is
    dropped and named, and the settings in the others still load — the same
    bargain the entity files get, and for the same reason: `holidays:
    [not-a-day]` is one word in one file and it took every page down.
    """
    loaded, refused = readable(paths, lambda path: _config_mapping(path, text_of(path)))
    data: dict[str, object] = {}
    for path, mapping in loaded:
        # Unknown keys are ignored so a repository with a half-written config
        # still loads rather than taking the whole index down.
        candidate = {**data, **{k: v for k, v in mapping.items() if k in Config.model_fields}}
        try:
            Config.model_validate(candidate)
        except ValidationError as error:
            refused.append(Unreadable(path=path, why=why_it_will_not_read(error, path)))
            continue
        data = candidate
    return Config.model_validate(data), refused


def load_config(root: Path) -> Config:
    """Merge the config files on disk. Absent files fall back to the defaults.

    Drops `read_config`'s second answer on purpose: a caller that wants the
    settings should not have to take delivery of a report, and `load_repo` below
    is what carries it to the pages. Nothing that renders anything calls this.
    """
    return read_config(*_config_on_disk(root))[0]


def _config_on_disk(root: Path) -> tuple[list[str], Callable[[str], str]]:
    """The config files this repository actually has, and how to read one.

    Filtered to what exists rather than letting a missing file raise: absent is
    the normal state of three of the four, and reporting `holidays.yaml` as
    unreadable because nobody wrote one would make the banner meaningless.
    """
    paths = [
        f"config/{name}" for name in CONFIG_FILES if (root / "config" / name).is_file()
    ]
    return paths, lambda path: (root / path).read_text(encoding="utf-8")


class Entity(BaseModel):
    """A project, pitch or task.

    Every field but `id`, `kind` and `title` is optional. That is deliberate:
    requiredness is a validation rule, not a parse constraint, so a file missing
    a mandatory field still parses and reports a Problem instead of taking the
    index down.
    """

    # Where this record was read from, so its two names can be compared. A private
    # attribute and not a field: `serialise` dumps the model, so anything declared
    # here is written back into the file, and the path a record was found at is the
    # one piece of information that must never become part of the record.
    _source: str = PrivateAttr(default="")

    # The frontmatter keys this model does not read. Parsing drops them — pydantic
    # ignores extras — so without this a `person_weeks: 3` written on a product is
    # gone before any rule can see it, and "a product carries no appetite" is a
    # rule that cannot fire. Private for the same reason `_source` is: `serialise`
    # dumps the model, and a list of keys the record does not have must not be
    # written back into the record.
    _unread: tuple[str, ...] = PrivateAttr(default=())

    id: str
    # Not a `Literal` written out: the rungs are `KINDS` below, and a kind
    # spelled in two places is a kind that gets added to one of them.
    kind: str
    title: str
    parent: str | None = None
    # A plain string, not a Literal. An unknown status has to survive parsing and
    # be reported, because the alternative is what actually happened: one file
    # written before a vocabulary change took every page down with a 500 instead
    # of showing a problem next to the record that caused it.
    status: str = "shaping"

    owner: str | None = None
    assignees: list[str] = []
    reviewers: list[str] = []
    review_waived: bool = False

    assigned_on: date | None = None
    # Named rather than numbered: "priority 2" means nothing to a reader, and a
    # number invites arithmetic on something that is only an ordering. A plain
    # string for the same reason as `status` — see above.
    priority: str = "medium"
    depends_on: list[str] = []
    cycle: int | None = None
    tags: list[str] = []
    prs: list[str] = []

    body: str = ""
    created_schema_version: int = 1

    @field_validator("kind")
    @classmethod
    def _a_rung_of_the_ladder(cls, value: str) -> str:
        """A kind this tool does not have is a file it cannot place.

        Strict, unlike `status` and `priority`, and the difference is what the
        field decides. An unknown status is a word next to a record that still
        loads, still sorts and still draws; an unknown KIND has no directory, no
        id prefix, no parent rule and no model — there is nothing to draw it as.
        It was a `Literal` and is a check against `KINDS` for the same reason
        everything else about a kind now is: one ladder, and a rung added to it is
        a rung everywhere.
        """
        if value not in KIND_NAMES:
            raise ValueError(f"kind must be one of {', '.join(KIND_NAMES)}, not {value!r}")
        return value

    @field_validator("status", "priority", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Take whatever is in the file, verbatim, and let validate_all judge it.

        A file written before a vocabulary change holds `priority: 1`, which YAML
        gives us as an int. Refusing it here means the whole index fails to load
        over one stale record; accepting it means one problem next to one entity.
        """
        return value if value is None else str(value)

    def state(self, entities: dict[str, Entity]) -> str:
        """What this record actually is — for a plan record, its written status.

        The base of the derivation `Issue.state` and `Note.state` already do:
        one method any page can call on any record, so a read display never has
        to know which kinds derive their state from links and which just have
        one. The argument goes unused here because the derivations need it — a
        state read off a link needs the link's targets to look at.
        """
        return self.status


class Project(Entity):
    pass


class Pitch(Entity):
    # PERSON-weeks: the work one person would need, which the people on it divide
    # (D-C4). Named for its unit because the unit is what went wrong — D1 read the
    # same number as elapsed weeks and the scheduler was wrong for as long as that
    # stood. One field on both kinds, because a pitch's appetite and a task's
    # effort were two names for one quantity that `size_weeks` already read as one.
    person_weeks: float | None = None
    # A list, because shaping is usually done in pairs — two of the four shaped
    # pitches in the team's own corpus name two or three people. A bare string
    # still parses and still writes back as a bare string, so no file has to
    # change and `git blame` on the field survives.
    shaped_by: list[str] = []

    @field_validator("shaped_by", mode="before")
    @classmethod
    def _one_or_many(cls, value: object) -> object:
        if value is None:
            return []
        return [value] if isinstance(value, str) else value


class Task(Entity):
    person_weeks: float | None = None


class Product(Entity):
    """A codebase, and a container for projects — nothing else.

    gt4py is the DSL under icon4py, dace is a backend, pmap is another code, and
    work in one of them waits on work in another. Kept in ONE plan for exactly
    that reason — jcanton, 2026-08-20: separate corpora "would prevent
    cross-dependencies", and a dependency this tool cannot express is a
    dependency somebody tracks in their head.

    It inherits every field an entity has and is allowed almost none of them.
    `KINDS` below is what enforces that, so the rule lives in one table rather
    than in a validator per field: a product has no owner, no dates, no appetite,
    is never scheduled, and may not depend on anything. Its projects, pitches and
    tasks carry all of that.
    """


# Statuses in the order work moves through them. `shaping` is an idea nobody has
# committed to yet, so it demands nothing — the same reason `shelved` does not.
# The gates are cumulative from `ready` onwards.
#
# Above the ladder rather than with `PRIORITY_RANK`, because the ladder now
# reads it: a rung carries the status vocabulary its kind reads, and three of
# the four rungs carry this one.
STATUS_ORDER = ("shaping", "ready", "in_progress", "done", "shelved")


# THE LADDER. Every other map about kinds is derived from this one, in this
# order, coarsest first — which is what makes "the top of the tree" a fact about
# the list rather than the word `project` written down in twenty places.
#
# jcanton asked for it while asking for `product`: "make the code more flexible so
# it doesn't hardcode project for top-of-the-list but rather uses an actual list
# or ordered data structure ... maybe with their properties associated to it".
# The properties are here because they are what differs BETWEEN kinds, and a
# property kept somewhere else is one that gets forgotten when a rung is added —
# which is exactly what adding `product` had to go and find in twelve places.
class Rung(NamedTuple):
    """One kind, and everything that is true of it and not of its neighbours."""

    name: str
    prefix: str            # what its ids start with
    directory: str         # where its files live
    model: type[Entity]
    under: tuple[str, ...]  # the kinds it may be filed under, nearest first
    schedules: bool        # does the scheduler give it dates
    depends: bool          # may it wait on anything
    sized: bool            # may it carry person_weeks
    carded: bool           # does a hover show its shaping document
    planned: bool          # does it appear in the plan: table, graph, timeline, people, scheduler
    statuses: tuple[str, ...]  # the status vocabulary this kind reads; () means status is not read


KINDS: tuple[Rung, ...] = (
    # `statuses=()` — status is one of the nine fields a product does not read
    # (jcanton, 2026-08-20: a codebase is not `in_progress`), and () is how the
    # ladder says so now that the vocabulary is a per-rung fact.
    Rung("product", "prod", "products", Product, under=(),
         schedules=False, depends=False, sized=False, carded=False,
         planned=True, statuses=()),
    Rung("project", "proj", "projects", Project, under=("product",),
         schedules=True, depends=True, sized=False, carded=True,
         planned=True, statuses=STATUS_ORDER),
    Rung("pitch", "pitch", "pitches", Pitch, under=("project",),
         schedules=True, depends=True, sized=True, carded=True,
         planned=True, statuses=STATUS_ORDER),
    # A task may skip the pitch — work that nobody shaped still belongs to a
    # project — which is why `under` is written out per rung rather than derived
    # as "everything coarser". Derived, a task could be filed straight under a
    # product, three rungs up, which is not a thing anybody means.
    Rung("task", "task", "tasks", Task, under=("pitch", "project"),
         schedules=True, depends=True, sized=True, carded=True,
         planned=True, statuses=STATUS_ORDER),
)

KIND_NAMES: tuple[str, ...] = tuple(rung.name for rung in KINDS)


# The fields that describe work being done, or evidence that it was: a rung the
# scheduler never sees reads none of them. Nobody is assigned to a codebase, a
# codebase is not in a cycle, and — jcanton, 2026-08-20 — a codebase does not
# have a pull request either. `status` is not in this tuple any more: whether a
# kind reads a status is its own axis (`Rung.statuses`), because a kind can
# read one without ever being scheduled — gated here, giving it a status would
# have dragged in the eight fields that come with being work.
_WORK_FIELDS = (
    "owner", "assignees", "reviewers", "review_waived", "assigned_on",
    "cycle", "priority", "prs",
)


def unread_fields(kind: str) -> tuple[str, ...]:
    """The fields this rung does not read, off the ladder.

    One function and not a list per kind, because two places have to agree about
    it: `validate_all` reports a field written into a file, and the editors
    (`_editable_for`, the create form, the table's new row) decline to offer it.
    A form offering a box the validator then complains about is those two
    disagreeing in the most annoying possible order.
    """
    rung = RUNG[kind]
    fields: list[str] = []
    if not rung.depends:
        fields.append("depends_on")
    if not rung.sized:
        fields.append("person_weeks")
    if not rung.schedules:
        fields.extend(_WORK_FIELDS)
    # `status` on its own gate: a kind with an empty vocabulary reads no status.
    # Today that is only `product`, whose behaviour this preserves exactly —
    # `statuses=()` keeps status unread — but gating on the vocabulary rather
    # than on `schedules` is what lets a rung read a status without inheriting
    # the eight scheduling fields above.
    if not rung.statuses:
        fields.append("status")
    return tuple(fields)
RUNG: dict[str, Rung] = {rung.name: rung for rung in KINDS}
_MODELS: dict[str, type[Entity]] = {rung.name: rung.model for rung in KINDS}
_ID_PREFIXES = {rung.prefix: rung.name for rung in KINDS}
# Where a reader looks for records. Written out at the top of this file, it was
# the FIFTH copy of the ladder — with `PREFIX` and `_KIND_MODELS` in `render.py`
# and `DIRECTORY` in `web.py` — and it is the one that failed silently: a plan
# holding two products loaded thirty-three records and none of them was a
# product, with nothing reported, because a directory nobody walks is a
# directory whose files do not exist.
_ENTITY_DIRS = tuple(rung.directory for rung in KINDS)


def edited_by_id(stamps: dict[str, int]) -> dict[str, int]:
    """Per-record last-edited epochs, joined from `Store.last_edited`'s per-path
    map.

    Here rather than in `web.py` or `cli.py` because the layout facts it reads —
    which directories hold records, `<id>--<slug>.md` with a slug that drifts —
    are this module's (`record_paths_in`, `_path_for`'s stem rule), and both the
    server and the export need the join. Two copies is the drift this file bans.

    Two files claiming one id is a blocker the pages already draw; for a time
    column the newest claim wins, because the row exists either way and a wrong
    recency beats a missing row.
    """
    record_paths, _ = record_paths_in(_ENTITY_DIRS, stamps)
    found: dict[str, int] = {}
    for path in record_paths:
        stem = path.rpartition("/")[2].removesuffix(".md")
        record_id = stem.partition("--")[0]
        if stamps[path] > found.get(record_id, 0):
            found[record_id] = stamps[path]
    return found


_SPLITTER = YAMLHandler()


def _round_trip_yaml() -> YAML:
    """A ruamel round-trip parser tuned to leave a hand-written block alone.

    Round-trip mode already keeps comments and key order; the rest is emitter
    settings that would otherwise restyle the file: `width` stops long titles
    being folded, `indent` reproduces the two-space list indentation the corpus
    uses, and the representer keeps an explicit `null` from collapsing to a bare
    `key:`. A fresh instance per call because a YAML object is not reentrant.
    """
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.representer.add_representer(
        type(None),
        lambda representer, _: representer.represent_scalar("tag:yaml.org,2002:null", "null"),
    )
    return yaml


def _split(text: str, source: str) -> tuple[str, str]:
    """Frontmatter text and body text, the body kept byte-for-byte.

    `frontmatter.parse` would do this in one call but it strips the body and
    hands back a plain dict, dropping the comments ruamel just recovered — so we
    use the handler's splitter and load the YAML ourselves.
    """
    try:
        frontmatter, content = _SPLITTER.split(text)
    except ValueError as error:
        raise ValueError(f"{source}: no YAML frontmatter") from error
    # The split leaves the blank line that separates frontmatter from prose;
    # `serialise` puts exactly one back.
    return frontmatter, content.lstrip("\n")


def parse_text(text: str, source: str) -> Entity:
    """Parse one entity file. `source` names the file in error messages only."""
    frontmatter, body = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    # Said here rather than met four lines down as `'CommentedSeq' object has no
    # attribute 'get'`. A frontmatter written as a list of one-key items is a
    # plausible typo — it is what you get from pasting a bullet list — and the
    # reader is owed the sentence rather than the internals of the thing that
    # tripped over it.
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the frontmatter has to be a map of fields, and this is not")

    kind = data.get("kind")
    if kind not in _MODELS:
        kind = _ID_PREFIXES.get(str(data.get("id", "")).split("-")[0])
    if kind not in _MODELS:
        raise ValueError(f"{source}: no usable 'kind', and the id names no known kind either")

    model = _MODELS[kind]
    fields = {
        name: value
        for name, value in data.items()
        if name in model.model_fields
        # A hand-written `reviewers: null` means "absent", not "not a list".
        and not (value is None and model.model_fields[name].default is not None)
    }
    entity = model.model_validate({"id": "", "title": "", **fields, "kind": kind, "body": body})
    # The record remembers the file it came from, because it is the only moment
    # both halves of its identity are in the same place. `source` was already here
    # and was only ever used to name the file in an error message.
    entity._source = source
    entity._unread = tuple(name for name in data if name not in model.model_fields)
    return entity


def parse_file(path: Path) -> Entity:
    return parse_text(path.read_text(encoding="utf-8"), str(path))


def parse_cycle_text(text: str, source: str) -> Cycle:
    """Parse one cycle file. Same frontmatter-and-body shape as an entity, and a
    different type: nearly every field an Entity carries is nonsense on a cycle,
    and the one it would reach for — `assignees: list[str]` — cannot hold the
    fraction that is the whole point of the record."""
    frontmatter, body = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the frontmatter has to be a map of fields, and this is not")
    fields = {k: v for k, v in data.items() if k in Cycle.model_fields}
    return Cycle.model_validate({**fields, "body": body})


def parse_cycle_file(path: Path) -> Cycle:
    return parse_cycle_text(path.read_text(encoding="utf-8"), str(path))


def parse_issue_text(text: str, source: str) -> Issue:
    frontmatter, body = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    fields = {k: v for k, v in data.items() if k in Issue.model_fields}
    return Issue.model_validate({"id": "", "title": "", **fields, "body": body})


def parse_issue_file(path: Path) -> Issue:
    return parse_issue_text(path.read_text(encoding="utf-8"), str(path))


def parse_note_text(text: str, source: str) -> Note:
    frontmatter, body = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    # The same guard the cycle parser carries and the issue parser does not: a
    # frontmatter written as a list is `data.items()` on a CommentedSeq, which is
    # an AttributeError rather than a ValueError — caught by `readable`, but named
    # to the reader as "AttributeError: 'CommentedSeq' object has no attribute
    # 'items'" instead of as the thing that is actually wrong with their file.
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the frontmatter has to be a map of fields, and this is not")
    fields = {k: v for k, v in data.items() if k in Note.model_fields}
    return Note.model_validate({"id": "", "title": "", **fields, "body": body})


def parse_note_file(path: Path) -> Note:
    return parse_note_text(path.read_text(encoding="utf-8"), str(path))


# A GitHub login: 1 to 39 characters of `[A-Za-z0-9-]`, never opening or closing
# with a hyphen. One pattern, used by both halves of this feature — the writer
# below turns a login into the one path it may write, and `parse_person_text`
# turns a path back into the login it is for. Written twice they would eventually
# disagree, and the disagreement would be a file in `people/` that the server
# wrote and the loader will not read.
#
# Not `[^/]+`, not `\w+`, and no path parameter anywhere near it: `people/` has to
# be closed by construction the way `projects|pitches|tasks/<id>.md` is, because
# branch protection means a write that escapes the directory cannot be
# force-pushed away afterwards. Consecutive hyphens are legal here and are not at
# GitHub — being narrower than the wire buys nothing this pattern is for, and
# would refuse a login the day GitHub relaxes its own rule.
#
# `\A` and `\Z`, not `^` and `$`. In Python `$` also matches immediately BEFORE a
# trailing newline, so `^...$` admits `ann\n` — which is a login this would have
# happily turned into `people/ann\n.md`. Found by putting it in the parametrised
# list rather than by reasoning about it, which is the only way this class of
# thing gets found.
LOGIN_PATTERN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")


def person_path(login: str) -> str | None:
    """`people/<login>.md`, or None for a name no file here may be called.

    The only place a login becomes a path, and the only place `people/` is
    spelled with something variable after it. Both callers ask this one question:
    the icon write refuses what it answers None to, and the People page draws no
    picker for it — because a control whose only answer is a refusal is a dead end
    a person can only find by pressing it, which is what the cycle page that
    rendered `/cycle/-1` was.
    """
    return f"{PEOPLE_DIR}/{login}.md" if LOGIN_PATTERN.match(login) else None


def login_of(source: str) -> str:
    """The login a person record is for, read off its path.

    The path is the identity — see `Person` — so this is where identity comes
    from, and it is checked rather than trusted: a `people/notes.md` somebody
    dropped in by hand is one unreadable file with a reason beside it, not a
    person called `notes` who quietly appears on a page.
    """
    login = Path(source).name.removesuffix(".md")
    if not LOGIN_PATTERN.match(login):
        raise ValueError(
            f"{source}: a file in {PEOPLE_DIR}/ is named for a GitHub login, "
            f"and {login!r} is not one"
        )
    return login


def parse_person_text(text: str, source: str) -> Person:
    """Parse one person record. `source` is the path, and is where the login is.

    `login:` in the frontmatter is ignored on purpose. The path already says who
    this is, and a second copy of that fact is a copy that can disagree with the
    first — which for an id is `_identity_problems`, two blocker rules and a
    special case in the entity save, all of it paid for a fact the filename
    already carried.
    """
    frontmatter, _ = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the frontmatter has to be a map of fields, and this is not")
    fields = {k: v for k, v in data.items() if k in Person.model_fields and k != "login"}
    return Person.model_validate({**fields, "login": login_of(source)})


def _in_the_style_of(old: object, new: object) -> object:
    """Keep a hand-written `tags: [a, b]` from becoming a three-line block list
    the moment somebody adds a tag from the web.

    An empty sequence records no style at all — `[]` is the only way to write
    one — so it is filled in flow style, which keeps the edit to a single line.
    """
    if isinstance(old, CommentedSeq) and old.fa.flow_style() is not False and isinstance(new, list):
        styled = CommentedSeq(new)
        styled.fa.set_flow_style()
        return styled
    # A field that grew from a scalar to a list keeps its scalar spelling while it
    # holds one value. `shaped_by: jcanton` is what the corpus is written in, and
    # rewriting every one of them to `[jcanton]` on an unrelated save is a diff
    # nobody asked for in a file somebody else is reading.
    if isinstance(old, str) and isinstance(new, list) and len(new) == 1:
        return new[0]
    return new


def serialise(entity: Entity, original_text: str | None = None) -> str:
    """Render an entity back to file text, preserving the original formatting.

    Given the file it came from, the frontmatter is edited in place: a key keeps
    its position, its comment and its style, and only keys whose value actually
    changed are rewritten. Without an original this writes a fresh skeleton with
    every field spelled out, nulls included, so the next human edit has something
    to fill in.
    """
    yaml = _round_trip_yaml()
    dumped = entity.model_dump(exclude={"body"})
    if original_text is None:
        data = dumped
    else:
        data = yaml.load(_split(original_text, entity.id)[0]) or {}
        for key, value in dumped.items():
            if key in data:
                if data[key] != value:
                    data[key] = _in_the_style_of(data[key], value)
            elif value != type(entity).model_fields[key].default:
                data[key] = value

    stream = io.StringIO()
    yaml.dump(data, stream)
    return f"---\n{stream.getvalue()}---\n" + (f"\n{entity.body}" if entity.body else "")


def _plan_files(root: Path, *directories: str) -> tuple[list[str], list[Unreadable]]:
    """The record paths under these directories on disk, and the nested files.

    `rglob`, not `glob`, and that is the point of it: a file one directory too
    deep has to be FOUND before `record_paths_in` can name it. Globbing one level
    skipped it silently, which is how `openproj check` reported "0 blockers" over
    a `people/team/ann.md` the served page was drawing as somebody's icon.

    Repo-relative and POSIX-spelled, because the path in an `Unreadable` is what
    the banner prints and what somebody greps a build log for — the absolute path
    this walk actually produced would put `/private/var/…/tasks/x.md` beside
    `tasks/x.md` in one list.
    """
    return record_paths_in(
        directories,
        [
            found.relative_to(root).as_posix()
            for directory in directories
            for found in sorted((root / directory).rglob("*.md"))
        ],
    )


def load_repo(root: Path) -> tuple[list[Entity], Config, list[Unreadable]]:
    """Everything in a plan repository: the records, the configuration, and the
    files that are neither.

    The cycle records are folded into the config rather than returned beside it,
    because a cycle is configuration in the sense that matters here: nothing
    iterates it, everything looks it up.

    The files that will not read are the third element and cannot be folded
    anywhere, because everything about them is a list somebody has to work
    through. Three values and not two, and the two-value version is what every
    caller had until this round: it raised on the first file that would not
    parse, so `openproj check` died with a traceback instead of reporting, never
    mentioned the second bad file, and the server answered 500 on every route to
    every reader until somebody with a terminal fixed the first one. A repository
    a whole team can push to will contain a file that is not a record; that is
    not an exceptional condition, it is Tuesday.
    """
    entity_paths, nested_entities = _plan_files(root, *_ENTITY_DIRS)
    entities, unreadable = readable(
        entity_paths,
        # Read here rather than through `parse_file`, so the name in the message
        # is the name in `Unreadable.path`. `parse_file` names its source by the
        # absolute path it was handed, and the banner prints the path beside the
        # reason — so the two disagreeing put `/private/var/…/tasks/x.md` after
        # `tasks/x.md` on one line, and the served pages and `openproj check`
        # would answer differently to somebody grepping a build log for a file.
        lambda relative: parse_text((root / relative).read_text(encoding="utf-8"), relative),
    )
    cycle_paths, nested_plans = _plan_files(root, _CYCLE_DIR)
    plans, unreadable_plans = readable(
        cycle_paths,
        lambda relative: parse_cycle_text(
            (root / relative).read_text(encoding="utf-8"), relative
        ),
    )
    # Issues through the same door: a file somebody hand-edited in git is how
    # every one of these fails, and an issue file is no different from a cycle
    # file in that respect.
    issue_paths, nested_issues = _plan_files(root, _ISSUE_DIR)
    issues, unreadable_issues = readable(
        issue_paths,
        lambda relative: parse_issue_text(
            (root / relative).read_text(encoding="utf-8"), relative
        ),
    )
    # And the notes, through the same door for the third time.
    note_paths, nested_notes = _plan_files(root, _NOTE_DIR)
    notes, unreadable_notes = readable(
        note_paths,
        lambda relative: parse_note_text(
            (root / relative).read_text(encoding="utf-8"), relative
        ),
    )
    # And the person records, through the same door again. One file per person is
    # what makes a bad one cost one person's icon instead of the whole page — the
    # arrangement this replaced put every icon and the roster in one file, where a
    # single hand edit took all of them at once.
    people_paths, nested_people = _plan_files(root, PEOPLE_DIR)
    people, unreadable_people = readable(
        people_paths,
        lambda relative: parse_person_text(
            (root / relative).read_text(encoding="utf-8"), relative
        ),
    )
    config, unreadable_config = read_config(*_config_on_disk(root))
    return (
        entities,
        config.with_plans(plans).with_issues(issues).with_notes(notes).with_people(people),
        # Sorted by path, so the banner and `openproj check` list them in the
        # order somebody would open them rather than in the order five separate
        # walks happened to finish.
        sorted(
            [
                *unreadable,
                *unreadable_plans,
                *unreadable_issues,
                *unreadable_notes,
                *unreadable_people,
                *unreadable_config,
                # A record filed one directory too deep is a file that is not a
                # record, and lands in the same list for the same reason.
                *nested_entities,
                *nested_plans,
                *nested_issues,
                *nested_notes,
                *nested_people,
            ],
            key=lambda one: one.path,
        ),
    )


def ancestors(entity_id: str, by_id: dict[str, Entity]) -> list[str]:
    """The parent chain, nearest first.

    A cycle in the chain is a validation blocker (see `validate_all`), so here it
    only has to stop: return the chain walked so far rather than spinning.
    """
    chain: list[str] = []
    seen = {entity_id}
    entity = by_id.get(entity_id)
    while entity is not None and entity.parent is not None and entity.parent not in seen:
        chain.append(entity.parent)
        seen.add(entity.parent)
        entity = by_id.get(entity.parent)
    return chain


def size_weeks(entity: Entity, config: Config) -> tuple[float, bool]:
    """Weeks of work, and whether that number had to be invented.

    One field on a pitch and a task, and none on a project — a container has no
    size of its own. Read here rather than reached for directly, so the scheduler,
    the index and the pages cannot disagree about what a missing one means.
    """
    stated = getattr(entity, "person_weeks", None)
    if stated is not None:
        return float(stated), False
    return config.default_task_effort, True


# --------------------------------------------------------------------------- #
# Reading the shaping document
#
# The body is prose and stays prose: nothing here validates it, rewrites it or
# requires it. These two functions only read what the team's own pitch template
# already asks people to write, so that a checklist somebody is keeping by hand
# can be counted instead of retyped as a second set of records.
# --------------------------------------------------------------------------- #

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
# The hashes are a group of their own because a section's NAME is flat and its
# EXTENT is not: `sections` keys on group 2 and ignores depth, while the two
# functions that carve a section out of a body have to know where it ends.
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
# A box, and the end of a line is as good as a space after it. Demanding real
# whitespace there dropped exactly one line, and it is the line this tool writes
# itself: `_TASK_TEMPLATE` (`render.py`) ends `## Progress\n\n- [ ]` with nothing
# after the bracket, so every task created from it held an unticked point that
# `checklist` did not count and `without_checklist` did not take away — and it
# reached a review slide as the literal characters `[ ]` under a `## Progress`
# heading that nothing had emptied.
#
# The regex was the defect and not the template. An empty box at the end of a
# file is a box; a reader sees one, GitHub ticks one, and the fix on the other
# side — a trailing space in a template — is invisible, and the next editor,
# formatter or pre-commit hook to touch the file deletes it and puts this back.
# Widening it is deliberately not deck-local: a point with no words now counts
# wherever progress is counted, which is what `checklist_items` already says it
# means — "a point that is only a box keeps its place in the count and says
# nothing, which is exactly what is on the page it came from".
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\](?=\s|$)")
# Fenced blocks, kept whole so that a pitch quoting markdown keeps its example.
_FENCED = re.compile(r"((?:^|\n)(?:```|~~~).*?(?:\n(?:```|~~~)[^\n]*|\Z))", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def without_comments(body: str) -> str:
    """A shaping document with its HTML comments taken out.

    The team's pitch template carries its guidance in `<!-- … -->`, which is
    invisible in HackMD and, with markdown-it's `html: false`, would print as
    literal text — so every pitch pasted across would arrive with its own
    instructions showing. Stripped rather than rendered: turning HTML on to hide
    four comments would put every hand-edited body's markup into the page.

    Here rather than in the renderer for two reasons. It reads a shaping document,
    which is what this section of the module is for; and `render.py` is held to a
    rule — `test_no_page_is_assembled_by_substitution` — that no page is assembled
    by `replace` or `sub`. This runs on the source before the tokeniser sees it,
    which is not that defect, but the rule is enforced as syntax on purpose and
    the function was in the wrong module anyway.
    """
    if "<!--" not in body:
        return body
    return "".join(
        part if part.lstrip("\n").startswith(("```", "~~~")) else _COMMENT.sub("", part)
        for part in _FENCED.split(body)
    )


def _outside_code(body: str) -> Iterator[tuple[str, bool]]:
    """Each line, and whether it is inside a fenced code block.

    A pitch that quotes a markdown snippet would otherwise have its example
    headings counted as its own.
    """
    fenced = False
    for line in body.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            yield line, True
            continue
        yield line, fenced


def sections(body: str) -> dict[str, str]:
    """The text under each heading, keyed by the heading itself, lowercased.

    Flat, ignoring heading depth: the template is flat, and a reader asking for
    "no-gos" does not care whether it was written as `##` or `###`.
    """
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line, in_code in _outside_code(body):
        heading = None if in_code else _HEADING.match(line)
        if heading:
            current = found.setdefault(heading.group(2).strip().lower(), [])
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


def checklist_items(body: str) -> list[tuple[bool, str]]:
    """Every task-list item as (ticked, what it says), in the order written.

    Anywhere, not only under `## Progress`: the template puts them there, and
    real notes also keep them under `## Solution`. Sub-items are items, and they
    arrive flat — `checklist` counts them that way, which is what somebody
    reading "7/12" means by it, and a list drawn with a hierarchy the number does
    not have is the two-copies-of-one-fact problem in a new spelling.

    The text is what follows the box, stripped. A point that is only a box —
    `- [ ]` with nothing after it — keeps its place in the count and says nothing,
    which is exactly what is on the page it came from.
    """
    found: list[tuple[bool, str]] = []
    for line, in_code in _outside_code(body):
        if in_code:
            continue
        mark = _CHECKBOX.match(line)
        if mark:
            found.append((mark.group(1) != " ", line[mark.end():].strip()))
    return found


def checklist(body: str) -> tuple[int, int]:
    """Ticked and total task-list items anywhere in the body.

    Counted from `checklist_items` rather than by a second walk of the same
    lines. The deck draws those points beside this number: two parses of one
    document is two chances for the tick on a slide and the "7/12" above it to
    disagree about the same line.
    """
    items = checklist_items(body)
    return sum(1 for ticked, _ in items if ticked), len(items)


def without_checklist(body: str) -> str:
    """The body with its task-list items taken out, and any heading they emptied.

    For the deck, which lifts those points to the top of the slide and ticks
    them. Left in place as well they print twice — the duplication the detail
    page avoids by not lifting a leaf's checklist at all (`_progress_view`). A
    slide cannot make that trade: it is read from the back of a room, and `[x]`
    is not a tick.

    The emptied heading is the second half and not a nicety. `## Progress` is
    where the team's task template puts the list, so on nearly every task
    removing the items leaves a heading with nothing whatever under it.

    Here and not in `render.py` for the reason `without_comments` is here: it
    reads a shaping document, and `render.py` is held to
    `test_no_page_is_assembled_by_substitution`.
    """
    return _without_emptied_headings(
        [
            (line, in_code)
            for line, in_code in _outside_code(body)
            if in_code or not _CHECKBOX.match(line)
        ]
    )


def _under(kept: list[tuple[str, bool]], at: int, level: int) -> Iterator[tuple[str, bool]]:
    """Everything under the heading at `at`: down to the next one as shallow."""
    for line, in_code in kept[at + 1:]:
        heading = None if in_code else _HEADING.match(line)
        if heading and len(heading.group(1)) <= level:
            return
        yield line, in_code


def _without_emptied_headings(kept: list[tuple[str, bool]]) -> str:
    """Lines, minus every heading whose whole subtree is now empty.

    Its subtree, and not the lines up to the next heading of any depth at all. A
    `## Progress` holding nothing but the checklist and a `### Still to do` under
    it has no text of its OWN once the boxes are lifted, and deleting it on that
    reading left `### Still to do` on the page under nothing — a subsection
    orphaned from the heading that said what it was part of.

    Headings inside the subtree do not count as text either. Otherwise `## A`
    over an empty `### B` keeps A alive on the strength of a line that is about
    to be deleted by this same rule, and A is left as a heading over a blank.
    """
    out: list[str] = []
    for at, (line, in_code) in enumerate(kept):
        heading = None if in_code else _HEADING.match(line)
        if heading:
            under = _under(kept, at, len(heading.group(1)))
            if not any(
                text.strip()
                for text, nested in under
                if nested or not _HEADING.match(text)
            ):
                continue
        out.append(line)
    return "\n".join(out).strip("\n")


def without_emptied_headings(body: str) -> str:
    """The body, minus every heading whose whole subtree is empty.

    The same prune `without_checklist` finishes with, reachable on its own,
    because taking a checklist away is not the only way to empty a heading. The
    deck also takes whole sections away — and a `## Notes` whose only content was
    a `### Solution` under it came out of that drop as a heading over blank paper,
    which is the exact thing the prune exists to stop, arriving one step after
    `without_checklist` had already run and could no longer see it.
    """
    return _without_emptied_headings(list(_outside_code(body)))


def _by_section(body: str, names: Iterable[str], keep: bool) -> str:
    """The named sections with everything nested under them, kept or dropped.

    Named the way `sections` keys them — lowercased, and matched at any depth,
    because the template is flat and a reader asking for "no-gos" does not care
    whether somebody wrote `##` or `###`.

    The *extent* is not flat, and reading it flatly was a bug: every heading
    ended the section above it, so a `### Second rabbit hole` written under
    `## Rabbit holes` escaped a drop of "rabbit holes" and arrived on a slide
    with nothing above it to say what it belonged to. A section runs to the next
    heading of its own level or shallower, which is what a reader means by it.
    """
    wanted = {name.strip().lower() for name in names}
    out: list[str] = []
    # The level of the matched heading whose subtree this is inside, or None.
    # Carried across the loop rather than recomputed, because what decides a line
    # is the heading above it. A `##` inside a fence never reaches this, so a
    # document quoting a template keeps its example whole.
    depth: int | None = None
    for line, in_code in _outside_code(body):
        heading = None if in_code else _HEADING.match(line)
        if heading and (depth is None or len(heading.group(1)) <= depth):
            named = heading.group(2).strip().lower() in wanted
            depth = len(heading.group(1)) if named else None
        if (depth is not None) is keep:
            out.append(line)
    return "\n".join(out).strip("\n")


def without_sections(body: str, names: Iterable[str]) -> str:
    """The body without these sections, heading and subsections and all.

    For the deck, which asks a shaping document for the part of it a review is
    about. Passing the set in rather than knowing it here is what lets the caller
    read it off `TEMPLATES` instead of listing it again.
    """
    return _by_section(body, names, keep=False)


def only_sections(body: str, names: Iterable[str]) -> str:
    """Just these sections, heading and subsections and all.

    The other half of the same walk. The deck needs both: a review slide leads
    with what happened, and falls back to the one section of the bet that says
    what was going to happen when nobody wrote anything else down.
    """
    return _by_section(body, names, keep=True)


# --------------------------------------------------------------------------- #
# Validation
#
# Rules are data, not branches: each carries the schema_version that introduced
# it, which is what makes grandfathering possible. A rule newer than the entity
# it is judging may only warn. Adding a required field must never invalidate a
# corpus written before the field existed — otherwise the rule gets reverted
# rather than adopted.
# --------------------------------------------------------------------------- #

_ID_PATTERN = re.compile(
    r"^(" + "|".join(rung.prefix for rung in KINDS) + r")-[0-9a-f]{6}$"
)
# Its own pattern, not a fourth alternative in the one above: that regex is what
# keeps `projects|pitches|tasks/<id>.md` the whole writable surface for entities,
# and widening it to admit a record that is not an entity is how that property
# gets lost by degrees.
_ISSUE_ID_PATTERN = re.compile(r"^issue-[0-9a-f]{6}$")
# A third shape for the third kind of record, and not an alternative inside
# either of the two above, for the reason the comment above gives.
#
# Public, and the ONLY copy: `web.py` imports this one rather than writing the
# same regex a second time, because the pattern is both what the validator judges
# an id by and what closes `notes/<id>.md` as a writable path — and two spellings
# of one rule is how the surface that regex keeps closed gets opened by degrees.
# The issue pattern beside it is written out twice, once here and once in
# `web.py`; that is the arrangement this one deliberately does not copy.
#
# `\A` and `\Z`, not `^` and `$`, for the reason `LOGIN_PATTERN` gives below: in
# Python `$` also matches immediately before a trailing newline, so `^…$` admits
# `note-a1b2c3\n` — an id that passes the guard and then becomes the path
# `notes/note-a1b2c3\n.md`.
NOTE_ID_PATTERN = re.compile(r"\Anote-[0-9a-f]{6}\Z")
_PREFIX_FOR_KIND = {rung.name: rung.prefix for rung in KINDS}
_SIZE_FIELD = {"pitch": "person_weeks", "task": "person_weeks"}

# Five levels, because three were not enough to say the thing the team was already
# writing: the HackMD table escalates past its top value as `High+`. A scale whose
# top is used for everything urgent stops ordering anything.
PRIORITY_RANK = {"very_high": 0, "high": 1, "medium": 2, "low": 3, "very_low": 4}


def _cyclic_members(edges: dict[str, list[str]]) -> set[str]:
    """Every node on a cycle, including self-loops."""
    graph = nx.DiGraph()
    graph.add_nodes_from(edges)
    for source, targets in edges.items():
        graph.add_edges_from((source, target) for target in targets if target in edges)
    caught = {
        node
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for node in component
    }
    return caught | {node for node in edges if graph.has_edge(node, node)}


def _loop_through(edges: dict[str, list[str]], node: str) -> list[str]:
    """The shortest loop this node is on, as a chain that starts and ends on it.

    Named rather than merely detected, because "that would make a loop" and
    "pitch-a would be its own grandparent, through pitch-b" are different amounts
    of help, and the second one says what to undo.

    Walked from each of the node's own edges rather than by asking for any cycle
    in the component: a strongly connected component containing this node also
    contains loops it is not on, and naming one of those would send somebody to
    edit a record that is not the problem.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(edges)
    for source, targets in edges.items():
        graph.add_edges_from((source, target) for target in targets if target in edges)
    for target in edges.get(node, []):
        if target in graph and nx.has_path(graph, target, node):
            return [node, *nx.shortest_path(graph, target, node)]
    return [node]


def loop_made(candidate: Entity, plan: Iterable[Entity]) -> str | None:
    """The loop this record would put itself on, named, or None.

    `validate_all` reports parent and blocked-by cycles as blockers, and reporting
    is the right answer for a plan that ARRIVED with one: a file in git is a fact,
    and refusing to load it would take every page down over somebody else's
    mistake. It is the wrong answer for a plan about to acquire one, which is what
    a PATCH of `parent` or `depends_on` can do — the blocker would land after the
    commit, on a protected branch, and the repair is a second crafted PATCH
    against a plan that is now reporting a problem nobody can see the cause of.

    Both graphs are asked through the same `_cyclic_members` that `validate_all`
    asks, so a save cannot be refused for a loop the validator would not report,
    or committed into one it would.
    """
    by_id = {entity.id: entity for entity in plan if entity.id != candidate.id}
    by_id[candidate.id] = candidate
    for field, edges in (
        ("parent", {i: [e.parent] if e.parent else [] for i, e in by_id.items()}),
        ("depends_on", {i: list(e.depends_on) for i, e in by_id.items()}),
    ):
        if candidate.id in _cyclic_members(edges):
            chain = " → ".join(_loop_through(edges, candidate.id))
            word = "filed under itself" if field == "parent" else "waiting for itself"
            return f"that would leave {candidate.id} {word}: {chain}"
    return None


def _dependency_problems(
    entity: Entity, by_id: dict[str, Entity], parent_cycles: set[str], dep_cycles: set[str]
) -> Iterator[tuple[str, str | None, str, int]]:
    if entity.id in dep_cycles:
        yield "blocker", "depends_on", "part of a blocked-by cycle", 1
        return
    # A parent cycle makes "ancestor" undefined, so the relational checks are
    # skipped rather than reporting a second, derived problem for one broken chain.
    own_ancestors = set() if entity.id in parent_cycles else set(ancestors(entity.id, by_id))
    for target in entity.depends_on:
        if target not in by_id:
            yield "blocker", "depends_on", f"blocked by {target}, which does not exist", 1
        elif target in own_ancestors:
            yield "blocker", "depends_on", f"cannot depend on {target}: it is an ancestor", 1
        elif entity.id in ancestors(target, by_id):
            yield "blocker", "depends_on", f"cannot depend on {target}: it is a descendant", 1
        elif by_id[target].status == "shelved":
            yield "warning", "depends_on", f"blocked by {target}, which is shelved", 1


def under(entity_id: str, children: dict[str, list[str]]) -> list[str]:
    """Every record filed below this one, however deep, each once and not itself.

    What a delete has to cascade over. Read from the index's `children` map — ids
    rather than entities, which is the shape the write path has — and returned in
    the order the walk finds them, sorted by the caller where it is shown to
    somebody.

    Shelved work is included, unlike in `reviewers_under` below. The two ask
    different questions: that one asks who is reviewing live work, and parked work
    has nobody; this one asks what would be orphaned, and a shelved task under a
    deleted pitch is orphaned exactly as much as a ready one.

    **The walk remembers where it has been**, for the reason spelled out at length
    on `reviewers_under`: a plan is allowed to contain a parent cycle, and the
    version of that function without a `seen` set took a laptop down.
    """
    found: list[str] = []
    seen: set[str] = {entity_id}
    stack = list(children.get(entity_id, []))
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        found.append(child)
        stack += children.get(child, [])
    return found


def reviewers_under(entity_id: str, children: dict[str, list[Entity]]) -> list[str]:
    """Everybody reviewing the work filed under this record, each once.

    A pitch with tasks under it is reviewed by whoever reviews those tasks. That
    is not a shortcut: the work being reviewed IS the tasks, and asking the pitch
    to name a reviewer of its own was asking for a second copy of a fact that is
    already written down one level below — one that goes stale the first time
    somebody changes a task.

    Walked rather than read one level deep, so a project inherits from the tasks
    under its pitches. A shelved child carries nobody: `validate_all` builds this
    map without them, because parked work is not work anybody is reviewing.

    **The walk remembers where it has been, because a plan is allowed to contain
    a parent cycle.** `validate_all` reports one as a blocker rather than refusing
    to load — a record that is wrong is worth showing beside the others — so this
    map really can hold A whose child is B whose child is A. The first version of
    this had no `seen`, and on that corpus it walked the pair for ever, appending
    a reviewer per pass: an infinite loop whose memory grows. It took a laptop
    down before a test caught it, which is why the test below exists.
    """
    found: list[str] = []
    seen: set[str] = {entity_id}
    stack = list(children.get(entity_id, []))
    while stack:
        child = stack.pop()
        if child.id in seen:
            continue
        seen.add(child.id)
        found += child.reviewers
        stack += children.get(child.id, [])
    return list(dict.fromkeys(found))


def _status_problems(
    entity: Entity, reviewers: list[str] | None = None
) -> Iterator[tuple[str, str | None, str, int]]:
    """One gate per status, not a cumulative stack.

    `shaping` is exempt because an idea nobody has bet on yet has no owner and no
    size by definition, and demanding them is how a tracker stops being somewhere
    people put half-formed things. `done` is exempt from the earlier gates for a
    duller reason: migrated history often cannot say who owned something in 2025,
    and a validator that blocks on unknowable facts gets switched off.

    Every message names its field the way the reader's screen names it, never the
    way the file spells it. A message is a sentence somebody reads, and it used to
    sit two inches under a checkbox labelled "Review waived" saying `review_waived`
    — one field with two names on one screen. The identifier is not lost: it stays
    on `Problem.field`, which is how the page finds the control to mark.
    """
    # Whoever reviews this, counting the work under it. `None` means "ask the
    # record itself", which is what a blank entity with no corpus around it can
    # answer — `required_at` derives the gates that way.
    reviews = entity.reviewers if reviewers is None else reviewers
    # A rung the scheduler never sees has no work state to gate. On a product,
    # `status` is a label to filter by — shelved hides a codebase and everything
    # under it — and not a claim that anybody is doing it, so demanding an owner
    # at `ready` and a PR at `done` would be demanding the very fields the same
    # ladder says the record does not read.
    if entity.kind in RUNG and not RUNG[entity.kind].schedules:
        return
    if entity.status in ("shaping", "shelved"):
        return
    if entity.status == "ready":
        if entity.owner is None:
            yield "blocker", "owner", "a ready entity needs an owner", 1
        # And somebody actually on it. An owner is who answers for the bet, which
        # is not the same question as who is doing the work — the scheduler prices
        # a record by the people on it (`_people_on`), so a bet with an owner and
        # nobody assigned is a bet that has been accepted and staffed with nobody.
        # jcanton, 2026-08-22.
        if not entity.assignees:
            yield "blocker", "assignees", "a ready entity needs somebody on it", 2
        if not (entity.review_waived or reviews):
            yield "blocker", "reviewers", "a ready entity needs a reviewer, or review waived", 1
        field = _SIZE_FIELD.get(entity.kind)
        if field is not None and getattr(entity, field) is None:
            # One field and one word now. It was `appetite_weeks` on a pitch and
            # `effort_weeks` on a task — one quantity under two names, which
            # `size_weeks` had to paper over on every read.
            yield "blocker", field, f"a ready {entity.kind} needs an appetite", 1
        if entity.kind == "pitch" and not entity.shaped_by:
            yield "blocker", "shaped_by", "a ready pitch needs to say who shaped it", 2
    elif entity.status == "in_progress":
        if entity.assigned_on is None:
            yield "blocker", "assigned_on", "work in progress needs the date it was assigned", 1
        if not entity.assignees:
            yield "blocker", "assignees", "work in progress needs somebody on it", 2
        if not entity.review_waived and not (set(reviews) - {entity.owner}):
            yield (
                "blocker",
                "reviewers",
                "work in progress needs a reviewer other than its owner, or review waived",
                1,
            )
    elif entity.status == "done" and not entity.prs:
        yield "blocker", "prs", "a done entity needs at least one PR", 1


def required_at(kind: str | None = None) -> dict[str, tuple[str, ...]]:
    """Which statuses demand each field, derived from the gate rather than copied.

    A form needs this and an HTML `required` attribute cannot express it: what the
    form must hold depends on the status chosen in that same form a moment ago. So
    the page carries the gates itself — and the map it used to carry was written by
    hand as "the first status that demands it", read cumulatively, which is not
    what the rules say. `_status_problems` is a chain of `elif`: `done` wants a PR
    and forgives the owner that `ready` insists on, deliberately, because migrated
    history often cannot name who owned something in 2025. Read cumulatively, the
    form refused to create exactly the entity the server would have accepted.

    Derived by running the gate over a blank entity of each kind at each status and
    collecting the fields it names, so it cannot drift from the rule it mirrors —
    it *is* the rule. It lives here rather than in `render.py`, which used to reach
    across and import `_status_problems`: the fields a status demands are this
    module's knowledge, and the page is only the thing that prints them. It is
    still only a courtesy; the server's answer is the truth.

    `kind` narrows it to one, which is what a caller asking about a RECORD wants:
    merged, the map says a project is missing `person_weeks` at `ready`, and a
    project has no such field. The form does want the merge — it draws the
    controls for a kind that can still be switched — so that stays the default.
    """
    gates: dict[str, list[str]] = {}
    kinds = tuple((rung.name, rung.model) for rung in KINDS)
    for name, model in kinds:
        if kind is not None and name != kind:
            continue
        for status in STATUS_ORDER:
            blank = model(id=f"{_PREFIX_FOR_KIND[name]}-000000", kind=name, title="", status=status)
            for _, field, _, _ in _status_problems(blank):
                if field and status not in gates.setdefault(field, []):
                    gates[field].append(status)
    return {field: tuple(statuses) for field, statuses in gates.items()}


def _vocabulary_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]:
    """A word nobody defined, named where it is rather than as a stack trace."""
    statuses = RUNG[entity.kind].statuses
    # An empty vocabulary means the kind reads no status, so there is no word to
    # judge: `unread_fields` already reports a status written on such a file as
    # "not read", and a blocker on top of that would hold a product to a ladder
    # it was just told it does not have. Judging against `STATUS_ORDER` here is
    # what this replaced, and it was wrong in both directions at once: it would
    # turn every stale note into an ungrandfatherable blocker the day notes
    # become records, and it makes `shaping` silently legal on an issue.
    if statuses and entity.status not in statuses:
        yield (
            "blocker",
            "status",
            f"{entity.status!r} is not a status: expected one of {', '.join(statuses)}",
            1,
        )
    if entity.priority not in PRIORITY_RANK:
        yield (
            "blocker",
            "priority",
            f"{entity.priority!r} is not a priority: expected one of "
            f"{', '.join(PRIORITY_RANK)}",
            1,
        )


def _people_problems(entity: Entity, config: Config) -> Iterator[tuple[str, str | None, str, int]]:
    """Names that are nobody, reported as a warning.

    A warning rather than a blocker on purpose: the roster is a file somebody
    maintains by hand, so it is always slightly behind reality, and a new
    colleague must not be unassignable on their first day. It catches the case
    that actually happens — a typo that quietly makes a task nobody reviews.
    """
    if not config.known_people:
        return
    for field in ("owner", "shaped_by", "assignees", "reviewers"):
        value = getattr(entity, field, None)
        for login in value if isinstance(value, list) else [value] if value else []:
            if login not in config.known_people:
                yield "warning", field, f"{login} is not in config/people.yaml", 1


# Which kind may contain which. A project is the top of the tree and holds
# pitches; a pitch holds tasks and belongs to a project or to nothing; a task
# belongs to a pitch, or straight to a project, or to nothing.
#
# The spec claimed this from the first day and nothing enforced it, so the frozen
# corpus already hangs a task straight off a project. Introduced at rule_version
# 4, which means every record written before it warns rather than breaks.
#
# A task may name a project because the first real cycle imported had two of
# them: work reported at the review that nobody had pitched, and that belongs
# with a milestone rather than nowhere. The alternative was a pitch invented to
# hold them, which puts a bet in the corpus that no betting table ever made —
# and a plan that lies about what was bet is worse than one whose tree is two
# levels deep in places. `is_bettable` already says a parentless task is bet in
# its own right; a task under a project takes the project's cycle, the same way
# a task under a pitch takes the pitch's, so nothing downstream has to change.
#
# Public, and it was `_PARENT_KINDS`: the table ships this map to the browser so
# that dragging a row onto one that cannot hold it is refused while the mouse is
# still down, rather than after a save. Three lines of JavaScript saying the same
# thing would be the copy that goes stale — this map was widened only yesterday,
# and a page still refusing a task on a project would be the tool arguing with
# its own validator.
# Off the ladder, where each rung says what it may sit under. Written out by hand
# here it said `project: ()` — "a project is the top" — which stopped being true
# the moment a rung was added above it, in a constant three hundred lines from the
# one being added.
PARENT_KINDS = {rung.name: rung.under for rung in KINDS}


def is_bettable(entity: Entity) -> bool:
    """Whether a cycle can be bet on this record.

    A pitch, or a task nobody pitched. Those are the two things a betting table
    puts a name against: everything else either contains bets (a project) or is
    part of one (a task under a pitch), and takes its cycle from what holds it.
    """
    return entity.kind == "pitch" or (entity.kind == "task" and entity.parent is None)


def bet_of(entity: Entity, by_id: dict[str, Entity]) -> Entity | None:
    """The record whose bet this one is part of — itself, or its pitch.

    One place, because the cycle page, the scheduler's overrun and the capacity
    sum all have to agree about which cycle a task is being done in, and three
    walks up the parent chain are three chances to disagree.

    A `parent` naming a file nobody wrote is deliberately allowed — a plan
    half-way through an import has them — and such a task falls back to its own
    `cycle`. There is no pitch to inherit from, and dropping the number it does
    carry would take the work out of every capacity sum on the site over a
    reference somebody has not written yet.
    """
    if is_bettable(entity):
        return entity
    if entity.parent is None:
        return None
    parent = by_id.get(entity.parent)
    if parent is None:
        return entity
    return parent if is_bettable(parent) else None


def cycle_of(entity: Entity, by_id: dict[str, Entity]) -> int | None:
    """The cycle this entity's work belongs to: its own, or its pitch's."""
    bet = bet_of(entity, by_id)
    return bet.cycle if bet is not None else None


def _containment_problems(
    entity: Entity, by_id: dict[str, Entity]
) -> Iterator[tuple[str, str | None, str, int]]:
    """A parent of the wrong kind.

    Only when the parent resolves: a `parent` naming a file nobody wrote is
    deliberately not a problem, so that a plan half-way through an import still
    loads and still says what it can.
    """
    parent = by_id.get(entity.parent) if entity.parent else None
    if parent is None:
        return
    allowed = PARENT_KINDS.get(entity.kind, ())
    if parent.kind not in allowed:
        belongs = " or ".join(f"a {kind}" for kind in allowed) or "nothing"
        yield (
            "blocker",
            "parent",
            f"a {entity.kind} belongs to {belongs}, not to a {parent.kind}",
            4,
        )


def _bet_problems(
    entity: Entity, by_id: dict[str, Entity]
) -> Iterator[tuple[str, str | None, str, int]]:
    """A cycle stamped on something nobody bets.

    A bet is made on a pitch, or on a chore nobody pitched. A task under a pitch
    is part of that bet and takes its cycle from it; a project is a container for
    bets and is not one. Stored on both, the two are one fact in two files and
    the copy is stale the first time somebody re-bets the pitch — which is the
    same argument that keeps `blocks` derived.
    """
    if entity.cycle is None or is_bettable(entity):
        return
    # Nothing to inherit from: an unresolved parent leaves this record's own
    # number the only one there is, and `bet_of` keeps it for that reason.
    if entity.parent is not None and entity.parent not in by_id:
        return
    if entity.kind == "project":
        yield (
            "warning",
            "cycle",
            "a project is not bet — its pitches are, and its span is their rollup",
            4,
        )
        return
    parent = by_id.get(entity.parent) if entity.parent else None
    named = f" from {parent.id}" if parent is not None else ""
    yield (
        "warning",
        "cycle",
        f"the bet is on the pitch, so this task takes its cycle{named}; "
        "the number here is ignored",
        4,
    )


def _rollup_problems(
    entity: Entity, children: dict[str, list[Entity]], config: Config
) -> Iterator[tuple[str, str | None, str, int]]:
    """Children that add up to more than the bet they sit inside.

    The appetite is the box, and its tasks are what somebody proposes to put in
    it. Nothing compared the two, so a six-week bet holding seven and a half
    weeks of tasks read as a six-week bet everywhere on the site — and the span,
    which is the rollup of the children, quietly ran past it anyway.

    A warning, never a blocker: the answer is to cut scope or to re-bet, and both
    are decisions for a person. Only stated sizes are compared — a pitch whose
    tasks are not written yet is under its appetite by definition, which is not
    worth saying.
    """
    kids = children.get(entity.id, [])
    stated, defaulted = size_weeks(entity, config)
    if not kids or defaulted:
        return
    total = sum(size_weeks(kid, config)[0] for kid in kids)
    if total > stated:
        yield (
            "warning",
            _SIZE_FIELD.get(entity.kind),
            f"its {len(kids)} tasks add up to {total:g} weeks, more than the "
            f"{stated:g} it was bet at — cut scope, or re-bet it",
            4,
        )


def _carries(entity: Entity, field: str) -> bool:
    """Whether this record was actually given `field` — something to report.

    Two places to look, because a rung that does not read a field usually does
    not declare it either: on the object when the model has it, and in `_unread`
    when it does not, where parsing put the key it dropped. A product has no
    `person_weeks` attribute at all, so reading the object alone made "a product
    carries no appetite" a rule that could never fire on a file anybody wrote.

    Compared against the model's own default rather than against None: `priority`
    defaults to a real value, so `is not None` would report every product ever
    written.
    """
    if field in entity._unread:
        return True
    if field not in type(entity).model_fields:
        return False
    value = getattr(entity, field)
    if value in (None, [], "", False):
        return False
    return value != type(entity).model_fields[field].get_default(
        call_default_factory=True
    )


def _problems_for(
    entity: Entity,
    config: Config,
    by_id: dict[str, Entity],
    children: dict[str, list[Entity]],
    parent_cycles: set[str],
    dep_cycles: set[str],
) -> Iterator[tuple[str, str | None, str, int]]:
    """Yield (severity_before_grandfathering, field, message, rule_version)."""
    if not entity.title.strip():
        yield "blocker", "title", "title must not be empty", 1
    if not _ID_PATTERN.match(entity.id):
        yield "blocker", "id", f"id must match {_ID_PATTERN.pattern}", 1
    elif not entity.id.startswith(_PREFIX_FOR_KIND[entity.kind] + "-"):
        yield "blocker", "id", f"id prefix must match kind {entity.kind}", 1

    # What this rung is not allowed to carry, off the ladder rather than out of a
    # validator per field. A product is a container: it groups the codebases a
    # plan spans so that work in one can wait on work in another, and it holds
    # none of the things work holds. A file that gives it one is reported beside
    # the record rather than refused, like everything else here — the plan still
    # loads and still says what is wrong.
    #
    # Rule version 1 and not the current one, alone among the rules added since
    # version 1. Grandfathering exists so a rule invented today does not turn
    # somebody's year-old file red — but no file can predate a KIND, and every
    # product that will ever exist is written after this. Stamped 5, a
    # hand-written product with `depends_on` reports a warning where it means a
    # blocker, for ever.
    if entity.kind in RUNG:
        name = entity.kind
        for field in unread_fields(name):
            if not _carries(entity, field):
                continue
            if field == "depends_on":
                yield (
                    "blocker", "depends_on",
                    f"a {name} waits on nothing: its projects, pitches and tasks do",
                    1,
                )
            elif field == "person_weeks":
                yield "blocker", "person_weeks", f"a {name} carries no appetite", 1
            else:
                # A warning and not a blocker: an owner on a container is ignored
                # rather than wrong, and refusing the file over it would be
                # refusing to load the plan over a word nobody reads.
                yield (
                    "warning", field,
                    f"a {name} is a grouping and is never scheduled, "
                    f"so its {field} is not read",
                    1,
                )

    if entity.id in parent_cycles:
        yield "blocker", "parent", "part of a parent cycle", 1
    elif entity.kind == "task" and entity.parent is None:
        yield "warning", "parent", "a task should have a parent", 1

    # Not while the chain is a loop: "part of a parent cycle" already says this
    # record's containment is broken, and adding that its parent is the wrong
    # kind is a second sentence about the same thing — in a set of records where
    # every one of them is going to say it.
    if entity.id not in parent_cycles:
        yield from _containment_problems(entity, by_id)
        yield from _bet_problems(entity, by_id)
        yield from _rollup_problems(entity, children, config)

    if entity.cycle is not None and entity.cycle not in config.cycles:
        # `_overrun` looks the window up with `.get`, so a number nobody has dated
        # does not raise — it silently returns None and the entity stops being
        # checked for overrun at all. A typo therefore reads as "on time" forever.
        yield (
            "warning",
            "cycle",
            f"cycle {entity.cycle} has no dates in config/cycles.yaml, "
            "so this is not checked for overrun",
            3,
        )

    yield from _dependency_problems(entity, by_id, parent_cycles, dep_cycles)
    yield from _vocabulary_problems(entity)
    # The reviewers of the work under this record count as its own. A pitch whose
    # tasks each name a reviewer is reviewed; asking it to name one as well is
    # asking for a second copy of a fact that is already a level below, and the
    # copy goes stale the first time a task changes hands.
    yield from _status_problems(
        entity, list(dict.fromkeys([*entity.reviewers, *reviewers_under(entity.id, children)]))
    )
    yield from _people_problems(entity, config)


def issue_problems(config: Config, entities: list[Entity]) -> list[Problem]:
    """The rules an issue is held to, which are few on purpose.

    An issue is somewhere to put a half-formed thing. A tracker that argues with
    you while you are writing down what you just noticed is a tracker people stop
    writing things down in — so an issue needs a title and a status that is a
    word, and everything else is a warning at most.
    """
    by_id = {entity.id: entity for entity in entities}
    problems: list[Problem] = []

    def note(issue: Issue, severity: str, field: str | None, message: str) -> None:
        problems.append(
            Problem(
                severity=severity,
                entity_id=issue.id,
                field=field,
                message=message,
                rule_version=1,
            )
        )

    for issue in config.issues.values():
        if not _ISSUE_ID_PATTERN.match(issue.id):
            note(issue, "blocker", "id", "id must match ^issue-[0-9a-f]{6}$")
        if not issue.title.strip():
            note(issue, "blocker", "title", "title must not be empty")
        if issue.status not in ISSUE_STATUS:
            note(
                issue,
                "blocker",
                "status",
                f"{issue.status!r} is not a status for an issue: expected one of "
                f"{', '.join(ISSUE_STATUS)}",
            )
        for target in issue.pitched_into:
            if target not in by_id:
                # A warning, not a blocker: an issue outlives the pitch it fed,
                # and a shelved pitch deleted later should not break the page the
                # issue is read on.
                note(issue, "warning", "pitched_into", f"pitched into {target}, which is missing")
        if issue.reported_by and config.known_people:
            if issue.reported_by not in config.known_people:
                note(issue, "warning", "reported_by", f"{issue.reported_by} is not in the roster")
    return problems


def note_problems(config: Config, entities: list[Entity]) -> list[Problem]:
    """The rules a note is held to, which are fewer than an issue's on purpose.

    An issue at least claims something is broken. A note claims nothing at all —
    it is where a half-formed idea goes so that it is written down somewhere
    instead of nowhere — so a validator with opinions about one is a validator
    that makes people stop writing them. A title and a status that is a word, and
    everything else is a warning.
    """
    by_id = {entity.id: entity for entity in entities}
    problems: list[Problem] = []

    def flag(note: Note, severity: str, field: str | None, message: str) -> None:
        problems.append(
            Problem(
                severity=severity, entity_id=note.id, field=field,
                message=message, rule_version=1,
            )
        )

    for note in config.notes.values():
        if not NOTE_ID_PATTERN.match(note.id):
            flag(note, "blocker", "id", "id must match ^note-[0-9a-f]{6}$")
        if not note.title.strip():
            flag(note, "blocker", "title", "title must not be empty")
        if note.status not in NOTE_STATUS:
            flag(
                note, "blocker", "status",
                f"{note.status!r} is not a status for a note: expected one of "
                f"{', '.join(NOTE_STATUS)}",
            )
        for target in note.became:
            if target not in by_id:
                # A warning, and the reason is the same as the issue's, plus one.
                # A note outlives what it became; and because `state` reads this
                # link, a missing target is already visible as the note dropping
                # back to "thinking" — this names which id went, which is the part
                # a person needs to repair it.
                flag(note, "warning", "became", f"became {target}, which is missing")
        if note.written_by and config.known_people:
            if note.written_by not in config.known_people:
                flag(note, "warning", "written_by", f"{note.written_by} is not in the roster")
    return problems


def shaping_document(template: str, provenance: str, body: str) -> str:
    """The body a promoted record arrives with.

    A note is by definition unshaped, so the pitch it becomes must not arrive
    looking shaped. What it gets is the team's own template for its kind — the
    same one `/new` starts from — with the note's own text placed under
    `## Problem`, which is exactly what that heading asks for: "the raw idea, a
    use case, or something we have seen that motivates us to work on this". That
    is what a note *is*. Every other heading arrives empty, carrying its guidance
    comment, and that is not a defect in the promotion: it is the honest state of
    a document five seconds old. `_shaping_hints` says nothing about it yet,
    because a `shaping` pitch owes nothing — it starts naming the missing Rabbit
    holes and No-gos the moment somebody moves this to `ready`, which is the
    moment it claims to be shaped.

    Nothing is copied into a *field*. The promoted record is created in `shaping`,
    which is the one status that requires nothing at all — "an idea nobody has bet
    on has no owner and no size by definition" — so a promotion always produces a
    record that validates, without inventing an owner, an appetite or a cycle
    that nobody agreed to. That is not a convenience; it is the same claim the
    note makes, carried across intact.

    `provenance` is one line of visible prose above everything, and it is the
    answer to "where did this pitch come from" asked of the record itself. Prose
    rather than a frontmatter field for two reasons: a field would put a note id
    inside `Entity`, which drags notes into every view of the plan that is built
    from it; and a second stored end of an edge whose first end is already stored
    on the note is the two-copies-of-one-fact problem `depends_on` exists to
    avoid. A sentence in a shaping document cannot fall out of step with anything,
    because nothing reads it — a person does.

    Built by composition rather than by substituting into the template, because
    `render.py` and `web.py` are held to `test_no_page_is_assembled_by_substitution`
    and this function is a hair away from being in one of them. It splits at the
    template's SECOND heading, so the note's text lands under the first one
    whatever that first one happens to say, and a template with one heading or
    none still works.
    """
    lines = template.splitlines()
    headings = [i for i, line in enumerate(lines) if line.startswith("#")]
    at = headings[1] if len(headings) > 1 else len(lines)
    blocks = [
        provenance.strip(),
        "\n".join(lines[:at]).strip(),
        body.strip(),
        "\n".join(lines[at:]).strip(),
    ]
    return "\n\n".join(block for block in blocks if block) + "\n"


def promoted_from(source_id: str, what: str, who: str | None, when: date | None) -> str:
    """The one line that says where a promoted record came from.

    A blockquote, so it reads as an epigraph on the page rather than as the first
    sentence of the problem statement — and so the person rewriting the document
    can see at a glance which part is theirs.

    The id is plain text and not a link. The record is a file: somebody reading
    this in `git show` can `cat notes/note-a1b2c3.md`, and a URL to a server that
    may not be running is worth less to them than the path. The pages linkify
    ids where they already do.

    `who` and `when` are both optional, because a record somebody wrote by hand in
    git is allowed to have neither, and a line reading "by None on None" is worse
    than a shorter one that is true. One shape for both inboxes: a note and an
    issue differ in what they are, which is `what`, and not in how they are cited.
    """
    if who and when:
        said = f"by {who} on {when.isoformat()}"
    elif who:
        said = f"by {who}"
    elif when:
        said = f"written on {when.isoformat()}"
    else:
        # Not "by nobody on no date": a record with neither is an ordinary record
        # somebody committed by hand, and the line still has to say where the
        # document came from, which is the only thing it is for.
        said = "in this plan"
    return f"> Promoted from {source_id} — {what} {said}."
def named_for(entity: Entity) -> bool:
    """Whether the file this record was read from is named for the id it declares.

    Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    only the half before `--` is the fact; the rest is decoration and renaming it
    is legal.
    """
    stem = Path(entity._source).name.removesuffix(".md")
    return stem == entity.id or stem.startswith(f"{entity.id}--")


def _identity_problems(entities: list[Entity]) -> Iterator[Problem]:
    """An entity says who it is twice, and here the two are made to agree.

    The id is in the frontmatter and it is in the filename, and nothing compared
    them — so the two halves of the application resolved a collision in opposite
    directions. `build_index` keeps the LAST file in tree order for an id;
    `_path_for` writes to the FIRST filename that matches. A file whose
    frontmatter claimed an id belonging to another file therefore took that id in
    the index and left the write pointing at the other one: a reader edited the
    record on screen, pressed save, and a different record changed on disk, with
    a 200 and no warning, while `openproj check` printed no problems at all.

    Both halves are blockers and neither is grandfathered, which is the one place
    this file makes that exception. Grandfathering exists so that a new rule about
    what a record must *contain* does not invalidate a repository written before
    it — a fair trade, because the cost of the warning is a missing field. This is
    not a rule about content. It is the question of which record you are looking
    at, and a warning here still lets the save land on the wrong file.

    A record with no source is one built in memory rather than read from a file,
    and it has no filename to disagree with.
    """
    claimants: dict[str, list[str]] = {}
    for entity in entities:
        if entity._source:
            claimants.setdefault(entity.id, []).append(entity._source)

    for entity in entities:
        if not entity._source:
            continue
        if not named_for(entity):
            yield Problem(
                severity="blocker",
                entity_id=entity.id,
                field="id",
                message=(
                    f"this record says it is {entity.id} and its file is named "
                    f"{Path(entity._source).name} — until they agree, a save can land "
                    "on the wrong file"
                ),
                rule_version=1,
            )
        others = [path for path in claimants[entity.id] if path != entity._source]
        if others:
            yield Problem(
                severity="blocker",
                entity_id=entity.id,
                field="id",
                message=(
                    f"{', '.join(sorted(others))} claims this id too, so which record "
                    "this is depends on which half of the app you ask"
                ),
                rule_version=1,
            )


def _parked(entity: Entity) -> bool:
    """Exempt from every rule: parked work is not broken work.

    Structural rather than the word `shelved`: every status ladder ends in its
    kind's terminal state — `STATUS_ORDER` and `ISSUE_STATUS` in `shelved`,
    `NOTE_STATUS` in `dropped` — so "the last word of this rung's own ladder" is
    the rule, and a rung added later is exempt in its own vocabulary with no
    edit here. A kind with no vocabulary is never parked: a product claiming
    `status: shelved` used to buy itself a silent skip with a word it does not
    even read, and now its written-but-unread status is reported instead.
    """
    statuses = RUNG[entity.kind].statuses
    return bool(statuses) and entity.status == statuses[-1]


def validate_all(entities: list[Entity], config: Config) -> list[Problem]:
    """Check every entity against every rule it is old enough to be held to.

    Parked entities — those at their own ladder's terminal status, see
    `_parked` — are exempt from all of them: parked work is not broken work,
    and a validator that nags about it teaches people to ignore the validator.
    """
    by_id = {entity.id: entity for entity in entities}
    parent_cycles = _cyclic_members({e.id: [e.parent] if e.parent else [] for e in entities})
    dep_cycles = _cyclic_members({e.id: list(e.depends_on) for e in entities})
    children: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.parent in by_id and not _parked(entity):
            children.setdefault(entity.parent, []).append(entity)

    problems: list[Problem] = []
    for entity in entities:
        if _parked(entity):
            continue
        for severity, field, message, rule_version in _problems_for(
            entity, config, by_id, children, parent_cycles, dep_cycles
        ):
            grandfathered = rule_version > entity.created_schema_version
            problems.append(
                Problem(
                    severity="warning" if grandfathered else severity,
                    entity_id=entity.id,
                    field=field,
                    message=message,
                    rule_version=rule_version,
                )
            )
    # Outside the loop above, and outside `shelved`'s exemption with it. Parked
    # work is not broken work — but a shelved record can still be the one whose id
    # a second file has taken, and the save that lands on the wrong file does not
    # care that one of the two is parked.
    problems.extend(_identity_problems(entities))
    return problems


def split_front_matter(text: str) -> tuple[str, str]:
    """The frontmatter block and the body, without reformatting either.

    The empty block is its own case and has to be, because the closing delimiter
    of `---\n---\n` is not preceded by a newline of its own: partitioning the
    opening `---\n` away leaves `---\n`, which contains no `\n---\n`, so the
    whole document was reported as body with no frontmatter at all.

    That is not a curiosity. `web.py` starts a record that does not exist yet from
    exactly that string, so `patch_text` copied it into the body — and every cycle
    started without a goal was committed with a literal `---` and `---` as its
    text. The page then drew two horizontal rules under a heading with nothing in
    it, which is what it was asked to draw. Found from a screenshot of that.
    """
    if not text.startswith("---"):
        return "", text
    _, _, rest = text.partition("---\n")
    if rest.startswith("---\n"):
        return "", rest[len("---\n") :]
    if rest.rstrip("\n") == "---":
        return "", ""
    front, sep, body = rest.partition("\n---\n")
    return (front, body) if sep else ("", text)


def patch_text(original: str, fields: dict, body: str | None = None) -> str:
    """Apply only the named fields to a file, leaving everything else byte-identical.

    Round-trip, not re-serialise: a person's comments, key order, blank lines and
    list style survive a save. "Edit it in git if you prefer" stops being true the
    first time a save reformats somebody's file, and nobody comes back after that.
    """
    front, existing_body = split_front_matter(original)
    yaml = YAML()
    yaml.preserve_quotes = True
    mapping = yaml.load(front) or {}
    for key, value in fields.items():
        mapping[key] = value
    stream = io.StringIO()
    yaml.dump(mapping, stream)
    return f"---\n{stream.getvalue()}---\n{existing_body if body is None else body}"
