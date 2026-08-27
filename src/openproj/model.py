"""Records, configuration and validation.

Parse permissively, validate strictly: every record field is optional at the type
level so that a hand-edited file with a missing field still loads. Requiredness
lives in `validate_all`, never in the parse types — see spec section 5.2.
"""

from __future__ import annotations

import io
import math
import re
import secrets
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

import networkx as nx
from frontmatter.default_handlers import YAMLHandler
from pydantic import BaseModel, PrivateAttr, ValidationError, field_validator, model_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.scalarstring import LiteralScalarString

if TYPE_CHECKING:  # pragma: no cover - imported for the annotation and nothing else
    # `schedule` imports this module, so the arrow only ever points one way at
    # runtime. `validate_all` still has to name the type it is handed, because
    # what `_rollup_problems` reads off a span — `budget_weeks` against
    # `elapsed_weeks` — is a contract with the scheduler and not a loose mapping
    # of floats that any caller could invent.
    from .schedule import Span

CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml", "people.yaml")
_CYCLE_DIR = "cycles"
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

    `rule_version` is what makes grandfathering possible: a record is only
    blocked by rules that existed when it was created.
    """

    severity: Literal["blocker", "warning"]
    record_id: str
    field: str | None
    message: str
    rule_version: int


class Unreadable(BaseModel):
    """A file in the plan that is not a record, and the reason in one line.

    Deliberately not a `Problem`. A Problem is about a record: it is keyed by
    record id, every page hangs it on that record's row, and the table's headline
    count links to a filter over records. A file that will not parse has no
    record — that is precisely what is wrong with it — so keying one to a path
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


def readable[T](paths: Iterable[str], load: Callable[[str], T]) -> tuple[list[T], list[Unreadable]]:
    """The records that loaded, and one `Unreadable` for every file that did not.

    The one place a plan file is read, because there were four and not one of
    them had this. `load` does the whole trip — fetch the bytes, decode them,
    scan the YAML, validate the model — since every one of those steps is a way a
    file somebody wrote in git fails, and a guard around only the last of them is
    the guard that was already here.

    Fifteen files proved it: no `---` at all, a flow sequence that never closes,
    a tab where YAML wants spaces, `effort_weeks: three`, `start_date: next
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
    a person's login off the filename, `_path_for` (`web.py`) reads a record's id
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
    # The order the review deck walks its slides in, by record id.
    #
    # **On the cycle and not on the records**, and that is a concurrency decision
    # rather than a taste. An order is one list about many records, so storing a
    # rank on each record would make one drag of one thumbnail a write to every
    # file below it — where `store.py`'s compare-and-swap is scoped to the path,
    # so a rail with eleven slides on it would contend eleven ways per gesture.
    # Here one drag is one write to one file, and the file is the one the deck is
    # already of.
    #
    # The mirror argument is why the slides' CONTENT is not here: that is one
    # record's own, seven presenters edit seven of them at once, and putting them
    # all in this file would be the contention this arrangement just removed. See
    # `Slide`.
    #
    # **Partial and stale are both ordinary.** `_deck_order` draws what is listed
    # in the order listed, then everything else after it — so a record bet into
    # the cycle after somebody saved an order still gets a slide, and an id left
    # here by a record that has since moved out is ignored rather than drawn as a
    # gap. An order that could take a slide off the deck by going stale is an
    # order nobody could trust, and the deck is the one page whose reader cannot
    # check.
    deck_order: list[str] = []

    # --- derived by Config.with_plans ---------------------------------------
    builds_until: date | None = None
    ends_on: date | None = None
    build_weeks: float = 0.0
    # Whether the two above were assumed rather than read: no `reviews_on` in the
    # file, or no next cycle to end the cool-down. The page says so rather than
    # printing a date it invented as though somebody had chosen it.
    assumed_review: bool = False
    assumed_end: bool = False

    @field_validator("deck_order", mode="before")
    @classmethod
    def _ids_as_written(cls, value: object) -> object:
        """Whatever is in the file, reduced to the ids in it — never a refusal.

        Parse permissively, validate strictly, and here the stakes are the whole
        calendar: a cycle that fails to load takes every derived date on every
        page with it, and this field is the newest thing in the file and so the
        likeliest to be wrong in one written by hand. The cost of nonsense here
        must be a deck in its default order, which is exactly what an empty list
        gives — `_deck_order` falls through to the bet-then-title ordering the
        deck used before this field existed.

        The write door is the opposite bargain and says so: `_as_record_ids`
        (`web.py`) refuses rather than sanitises, because what this server is
        about to commit is a choice it can decline, and a file that arrived in
        git is a fact it cannot.
        """
        if not isinstance(value, list):
            return []
        return [one for one in value if isinstance(one, str)]

    def capacity(self, who: str, nominal: float = 1.0) -> float:
        """Weeks of work this person can hold in this cycle."""
        return self.availability.get(who, nominal) * self.build_weeks


class Person(BaseModel):
    """One person's own settings, stored as `people/<login>.md`.

    Frontmatter and a body, the same shape as a record, a cycle and an issue —
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
    with every other record here. They carry their id in the frontmatter too,
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


# What a repository may be called. The allowlist `Config.repositories` is judged
# by — see the validator there for why this is not a denylist.
#
# **Each segment must START with a letter or a digit**, which is the half that is
# not decoration: `[\w.-]+` alone matches `..`, so `../..` is a legal name by that
# rule and `https://api.github.com/repos/../../x/pulls` is a request to an
# endpoint nobody wrote down. GitHub's own names start with an alphanumeric or an
# underscore, so nothing real is refused by tightening it.
_REPOSITORY = re.compile(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*")


class Config(BaseModel):
    """Repository-wide planning configuration.

    `schema_version` is the version NEW records are created at, which is not
    necessarily the version the existing corpus was written at.
    """

    schema_version: int = 1
    nominal_availability: float = 1.0
    # `default_task_effort` was here, and it was the one setting that answered a
    # question nobody had asked the plan: how long an unsized record should be
    # treated as taking. `size_weeks` says why it went. A plan whose
    # `config/defaults.yaml` still carries the key loads exactly as before —
    # `read_config` keeps only the keys `Config` declares — so the removal costs
    # a stale line in a file and nothing else.
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
    # The repositories this plan's work happens in, as `owner/repo`, from
    # config/defaults.yaml. Empty is the ordinary state and means one thing only:
    # the pull-request completion offers what the corpus already cites and asks
    # nothing of the network. Named here rather than in this tool's source
    # because they are a fact about the PLAN — jcanton, 2026-08-25, asking
    # whether icon4py's and gt4py's open pull requests could be offered — and
    # openproj is not the icon4py team's tool alone.
    repositories: list[str] = []
    # Keyed by cycle number. Loaded from `cycles/*.md`, not from a config file.
    plans: dict[int, Cycle] = {}
    # Keyed by login. Loaded from `people/*.md`, and deliberately not from the
    # roster above: this is what each person chose for themselves, and the roster
    # is who the team says is on it. Neither answers the other's question, and a
    # login in one and not the other is the normal state of both.
    people: dict[str, Person] = {}

    @field_validator("repositories")
    @classmethod
    def _repositories_are_owner_and_repo(cls, given: list[str]) -> list[str]:
        """`owner/repo`, and nothing else.

        **An allowlist, and it has to be**: this value ends up in a URL path on
        api.github.com. A `..` or a `?` or a second slash in it is a request to
        an endpoint nobody wrote down, and `AGENTS.md` records what a denylist of
        URL spellings is worth. The two segments are exactly what GitHub allows
        in a name — letters, digits, dot, dash, underscore — so anything else is
        a typo or an attempt, and both are refused the same way.

        Refused rather than filtered, which is the bargain every other config
        value already has: the file is dropped and NAMED in the banner, where a
        silent skip would leave somebody looking at a completion that offers
        nothing and no reason anywhere on the page.
        """
        for name in given:
            if not _REPOSITORY.fullmatch(name):
                raise ValueError(
                    f"repositories: {name!r} is not an owner/repo — two segments of "
                    "letters, digits, dots, dashes and underscores, like "
                    "'C2SM/icon4py'"
                )
        return given

    def with_people(self, people: list[Person]) -> Config:
        """Carried on the config for the same reason cycles are: nothing
        iterates people records, one page looks them up, and threading a
        fourth value through every caller to be dropped by all but one of them is
        the shape this already rejected twice."""
        return self.model_copy(update={"people": {person.login: person for person in people}})

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
        return self.model_copy(update={"cycles": windows, "plans": {c.cycle: c for c in resolved}})

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
        days += sum(days_after(first, weeks * 7 + offset).weekday() < 5 for offset in range(rest))
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
    bargain the record files get, and for the same reason: `holidays:
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
    paths = [f"config/{name}" for name in CONFIG_FILES if (root / "config" / name).is_file()]
    return paths, lambda path: (root / path).read_text(encoding="utf-8")


# Statuses in the order work moves through them, and the vocabulary a project, a
# pitch and a task read — `Rung.statuses` below hands this same tuple to those
# three rungs, so a word added here reaches all three at once.
#
# `thinking` is the foot of the hill: nobody has looked at this yet. It demands
# nothing, for the same reason `shaping` demands nothing and rather more so, and
# it is where a new record opens. It is not new — it was already a note's opening
# word, already had a stop on the hill at t=0.0 and already had a human label —
# what changed on 2026-08-24 is that a planned record may stand there too, so
# "written down, not thought about" stops having to be spelled `shaping`, which
# claims somebody is already shaping it. jcanton: "all records should be able to
# have this status, except for issues".
#
# Deliberately absent from `ISSUE_STATUS` — the argument is written beside that
# tuple, where the omission is.
#
# Above `Record` rather than beside `PRIORITY_RANK`, and above the ladder rather
# than inside it, because both of them read it: the ladder carries it to three
# rungs, and `Record.status` opens on its first word.
STATUS_ORDER = ("thinking", "shaping", "ready", "in_progress", "done", "shelved")


# The largest slide prose this tool will put in git, and a fraction of what a
# body may be. A slide is a fixed 16:9 sheet read from the back of a room; the
# most text that can physically fit on one is a few hundred words, so a ceiling
# three orders of magnitude above that is not a limit anybody meets, it is a
# bound on what a crafted PATCH can commit into a *frontmatter* block scalar —
# where, unlike a body, there is no `MAX_BODY_BYTES` already standing in front of
# it. Derived from that constant rather than written as digits, for the reason
# written beside it: two ceilings spelled out separately are two ceilings that
# drift, and this repository has already paid for that once.
MAX_SLIDE_BYTES = MAX_BODY_BYTES // 16


class Slide(BaseModel):
    """What one record contributes to its cycle's review deck.

    **Absent means generated.** `Record.slide` is `None` on every record nobody
    has opened the slide editor for, and that is not a default standing in for a
    choice — it is the statement that no choice has been made, which is what lets
    the deck go on drawing what it drew before this field existed. A `Slide()`
    with everything at its default is a different fact: somebody looked, chose
    nothing, and meant it. Collapsing the two would have made shipping this
    feature a change to every existing deck.

    **The prose is here and not in the body**, which is the one decision in this
    class worth the paragraph. `checklist_items` scans the whole body and feeds
    `index.progress`, which feeds the table's meter, the detail panel's count and
    every rollup above it — so a `## Slide` section in the body means a checkbox
    somebody typed into a *slide* moves the plan's own numbers. `sections()` has
    the same reach (`index.py`'s "for later", `detail.py`'s written-sections
    panel). The alternative was stripping the section at all eight call sites,
    each of which would fail silently and none of which would fail in a test.
    Here it cannot reach any of them: a body is a body.

    What it costs is real and was weighed. Prose in YAML is prose somebody
    hand-editing in git has to indent correctly, and `store.write` merges
    frontmatter per key — so two people writing this same record's slide prose at
    once resolve whole-value, where a body would have line-merged. That is a
    trade of merge granularity on a field one presenter writes for their own
    record, against arithmetic every page displays.

    **`sections` is the chosen list, not the excluded one.** A section added to
    the record after somebody personalised its slide therefore does NOT appear on
    the slide until they open the editor and tick it — jcanton, 2026-08-25:
    "newly-discovered section should always arrive but not checked, default is
    leave out". The editor is where the reconciliation happens, and it happens on
    open without writing anything: a GET that commits would fire for every reader
    of the page and 403 the ones who may not write.
    """

    # Not presented at all. The record stays bet into the cycle and stays on the
    # rail — greyed, not hidden, because a slide that vanishes is one nobody can
    # find their way back to. Excluded from presentation mode, drawn dimmed on
    # `/deck/<n>` so the presenter can see what they dropped.
    skip: bool = False
    # The two things the slide already lifted out of the record before any of
    # this existed: the ticked checklist at the top, and the pull requests under
    # it. Default true because that is what the deck drew the day before this
    # field was added, and a personalisation that changes the drawing merely by
    # existing is one nobody can reason about.
    progress: bool = True
    prs: bool = True
    # The record's own section names, lowercased the way `sections()` keys them.
    # A list and not a set because YAML has no set and a person hand-editing this
    # writes a list; the ORDER in it is not read — the slide draws sections in
    # body order, which is the order the author is looking at while they tick the
    # boxes. Left as a list so that changing that later is a change to one
    # function rather than to the file format.
    sections: list[str] = []
    # Whether the record's opening prose — everything above its first heading —
    # goes on the slide.
    #
    # Its own flag because it is the one part of a body that `sections` cannot
    # name. Without it a record whose body is plain prose with no headings at all
    # has an empty section list, and personalising such a record would blank a
    # slide that had been drawing perfectly well: the checkbox UI would offer
    # nothing to tick, so there would be no way to get the text back. Default
    # true, like the two flags above and for the same reason — it is what the
    # deck drew before this field existed.
    lead: bool = True
    # Whatever the author wants to say that the record does not. Free markdown,
    # split into further slides on `\newslide` — see `slide_chunks`.
    body: str = ""

    @model_validator(mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Take what is usable and DROP what is not, so a default takes its place.

        Parse permissively, validate strictly — the same bargain `status` and
        `priority` make, and here the argument is stronger rather than weaker. A
        `progress: banana` somebody hand-edited is worth one slide drawn the
        generated way; it is not worth a record that will not load, and a record
        that will not load takes the other four hundred with it.

        Dropping the key rather than substituting a value is what makes that
        true without writing the defaults out a second time: pydantic fills the
        field from its own declaration above, so there is one place a default is
        written and it is the field. Returning a corrected value from a
        `field_validator` cannot do that — the validator has no way to name the
        default, so it would have to repeat it.

        The bare-scalar `sections: solution` is corrected rather than dropped:
        it is what somebody writing YAML by hand types, it can only mean one
        thing, and refusing to read it would be this tool being stricter about
        its own file than a person is.
        """
        if not isinstance(value, dict):
            return {}
        taken = {}
        for key in ("skip", "progress", "prs", "lead"):
            if isinstance(value.get(key), bool):
                taken[key] = value[key]
        if isinstance(value.get("body"), str):
            taken["body"] = value["body"]
        chosen = value.get("sections")
        if isinstance(chosen, str):
            taken["sections"] = [chosen.strip().lower()]
        elif isinstance(chosen, list):
            taken["sections"] = [
                str(name).strip().lower()
                for name in chosen
                if isinstance(name, str | int | float) and not isinstance(name, bool)
            ]
        return taken


class Record(BaseModel):
    """One record of any rung: project, pitch, task, product, issue or note.

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
    #
    # THE opening status: the one place a new record's first word is written, and
    # `STATUS_ORDER[0]` rather than the word itself because a record opens at the
    # foot of its own ladder — `Issue.status` and `Note.status` say the same about
    # theirs. Widening a ladder at the foot therefore moves its default with it,
    # which is exactly what putting `thinking` in front of `shaping` is.
    #
    # Everything that needs the value reads it from here: the create form builds a
    # blank through this model, the table's draft row reads this field's default,
    # the two form scripts are handed it, and `POST /api/record` writes no status
    # key at all for a planned kind — so the record opens here on the way back in.
    # `POST /api/promote` is the one place that deliberately says otherwise, and
    # says why on the line that does it.
    status: str = STATUS_ORDER[0]

    owner: str | None = None
    assignees: list[str] = []
    reviewers: list[str] = []
    review_waived: bool = False

    # The one date anybody types, and the whole schedule is derived from it.
    # It was `assigned_on` until 2026-08-27 — a name borrowed from an HR event,
    # for a field that has only ever meant the day the work began, feeding a
    # column already called Start. `_SIZE_FIELD`'s one-field-one-word cleanup is
    # the precedent, and the old key is named in `_RETIRED` rather than quietly
    # read: a file still saying `assigned_on:` parses clean and would otherwise
    # lose its date in silence.
    start_date: date | None = None
    # Named rather than numbered: "priority 2" means nothing to a reader, and a
    # number invites arithmetic on something that is only an ordering. A plain
    # string for the same reason as `status` — see above.
    priority: str = "medium"
    depends_on: list[str] = []
    cycle: int | None = None
    tags: list[str] = []
    prs: list[str] = []

    body: str = ""
    # What this record contributes to its cycle's review deck, or `None` where
    # nobody has said — see `Slide`, which is where the whole argument is.
    #
    # Deliberately absent from `EDITABLE` (`tokens.py`), which is what keeps it
    # off the facts column and out of the create form. That dict is the page's
    # key order and the set of fields a form offers; this is neither a fact about
    # the work nor something to fill in while creating one, and jcanton was
    # explicit that the slide's own settings must not turn up in the record's
    # reading view. It is still in `RECORD_FIELDS` — which `web.py` derives from
    # `model_fields` — so the save path can write it and name it in a commit.
    slide: Slide | None = None
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
        over one stale record; accepting it means one problem next to one record.
        """
        return value if value is None else str(value)

    @field_validator("slide", mode="before")
    @classmethod
    def _a_slide_or_nothing(cls, value: object) -> object:
        """A `slide:` that is not a map is nobody's slide, so it is nobody's slide.

        `Slide` sanitises what is *inside* the map; this decides whether there is
        one at all, and the distinction is the whole point of the field being
        optional. Letting `slide: 5` through to `Slide()` would read a hand edit
        nobody meant as "somebody opened the editor and chose nothing", which
        draws a heading over blank paper — the exact failure `_review` was
        rewritten to stop. Absent means generated, so garbage means generated.
        """
        # A `Slide` as well as a mapping, and this is not a convenience. A
        # `mode="before"` validator sees whatever the caller passed, and
        # `Record(slide=Slide(...))` and `record.model_copy(update={"slide":
        # Slide(...)})` both pass the MODEL — which is not a dict, so the first
        # version of this line turned every one of them into `None` silently.
        # `/api/slide/preview` builds its unsaved copy exactly that way, so the
        # preview would have drawn the stored slide while claiming to draw the
        # typed one. Found by a test, in the fixture that built a record the
        # obvious way.
        return value if isinstance(value, dict | Slide) else None

    def state(self, records: dict[str, Record]) -> str:
        """What this record actually is — for a plan record, its written status.

        The base of the derivation `Issue.state` and `Note.state` already do:
        one method any page can call on any record, so a read display never has
        to know which kinds derive their state from links and which just have
        one. The argument goes unused here because the derivations need it — a
        state read off a link needs the link's targets to look at.
        """
        return self.status


class Project(Record):
    pass


class Pitch(Record):
    # PERSON-weeks: the work one person would need, which the people on it divide
    # (D-C4). Named for its unit because the unit is what went wrong — D1 read the
    # same number as elapsed weeks and the scheduler was wrong for as long as that
    # stood. One field on both kinds, because a pitch's appetite and a task's
    # effort were two names for one quantity that `size_weeks` already read as one.
    person_weeks: float | None = None
    # There is no `shaped_by` any more — jcanton, 2026-08-24: owner, shaped_by,
    # assignees and reviewers was one hat too many, so on a pitch `owner` means
    # "who shaped it and holds it". The cost was known when he chose: the team's
    # own HackMD header says "Shaped by", and shaping is usually a pair where
    # `owner` holds one name. Do not reintroduce either. A file that still
    # carries the key round-trips untouched and warns, through `_RETIRED`.


class Task(Record):
    person_weeks: float | None = None


class Product(Record):
    """A codebase, and a container for projects — nothing else.

    gt4py is the DSL under icon4py, dace is a backend, pmap is another code, and
    work in one of them waits on work in another. Kept in ONE plan for exactly
    that reason — jcanton, 2026-08-20: separate corpora "would prevent
    cross-dependencies", and a dependency this tool cannot express is a
    dependency somebody tracks in their head.

    It inherits every field a record has and is allowed almost none of them.
    `KINDS` below is what enforces that, so the rule lives in one table rather
    than in a validator per field: a product has no owner, no dates, no appetite,
    is never scheduled, and may not depend on anything. Its projects, pitches and
    tasks carry all of that.
    """


# An issue's own ladder, which starts one rung further up than a planned
# record's and is not derived from it. Two words are deliberately missing, for
# two different reasons, and both are refusals rather than omissions —
# `_vocabulary_problems` and `_reject_bad_status` (`web.py`) read the vocabulary
# off the rung, so a word that is not here is a blocker on a file and a 422 on
# the door with no code of their own.
#
# No `shaping`: see the docstring below — shaping happens in the record an issue
# is promoted into, never in the issue.
#
# No `thinking`: an issue is *reported*. Somebody hit the thing, worked out what
# was wrong and wrote it down, so it has already been thought about — that is
# what filing it was — and this ladder starts at `ready` for exactly that
# reason. `thinking` on an issue would be the tool claiming nobody has looked at
# something somebody had just finished looking at. jcanton, 2026-08-24, widening
# `thinking` to the planned rungs: "all records should be able to have this
# status, except for issues".
ISSUE_STATUS = ("ready", "in_progress", "done", "shelved")


class Issue(Record):
    """Something somebody noticed, before anybody has decided to do it.

    Stored as `issues/<id>.md`, and — since the sixth rung landed — a Record,
    on a rung with `planned=False`. It used to be a separate type, and the
    argument for that was real: a separate type kept an issue off the table, the
    graph, the people page and the timeline *by construction*, rather than by an
    exclusion in each of them that somebody later forgets. What replaced the
    type is a stronger construction, not a repeal of it. `build_index` builds
    `Index.plan` by filtering the records down to planned rungs in one
    comprehension; a model_validator on `Index` refuses any index whose `plan`
    holds an unplanned kind; and the KINDS-derived sweep in the tests seeds one
    record of every unplanned rung and asserts its absence from every plan
    view. The type boundary lived in sixty read sites' annotations with no
    compiler behind them and failed OPEN — forget one filter and an issue
    appears on the timeline. A forgotten consumer of the filtered map now
    fails CLOSED: it sees fewer records, never more.

    What the type cost while it lasted was a second copy of every page, and #67
    measured the drift that buys: the note page got the status hill and the
    issue page did not, in one commit, by the same author.

    Its own fields survive the move unchanged. There is no `shaping` in
    `ISSUE_STATUS`: shaping happens in the record an issue is promoted into and
    never in the issue itself, so a status for it here would be a second place
    to say what `pitched_into` already says — and now that the vocabulary is
    read off the rung, `shaping` is *refused* on an issue rather than silently
    legal, which closes a hole the old bespoke validator left open.
    """

    # The foot of this rung's own ladder, exactly as `Record.status` is the foot
    # of the planned one's. Written as `[0]` and not as the word so that the
    # default cannot come to disagree with the vocabulary it has to be a member
    # of — which is the whole of what widening `STATUS_ORDER` had to move.
    status: str = ISSUE_STATUS[0]
    reported_by: str | None = None
    opened_on: date | None = None
    # The pitches and tasks this was pitched into. One direction only: a record
    # does not list its issues, because two directions for one edge disagree the
    # first time somebody edits the wrong end.
    pitched_into: list[str] = []

    def state(self, records: dict[str, Record]) -> str:
        """What this issue actually is, given what it was pitched into.

        Derived rather than copied. An issue that has been pitched has been
        picked up, and one whose work is finished is finished — writing that
        into the file as well would be a second copy of a fact the link already
        carries, and the two disagree the moment somebody closes the pitch.

        `shelved` is never overridden. "We are not doing this" is a decision,
        and a link somebody adds afterwards does not reverse it.
        """
        if self.status == "shelved":
            return "shelved"
        linked = [records[i] for i in self.pitched_into if i in records]
        if not linked:
            return self.status
        if all(record.status in ("done", "shelved") for record in linked):
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
# What is deliberately absent: no `in_progress` (there is no such thing as
# working on a note — the moment there is work there is a record, which is
# `promoted`, DERIVED from `became` rather than stored); no `ready` ("ready to
# be shaped" is a promise the Promote button keeps in one press); no `done` (a
# note is not finished, it is answered — by a record somewhere else, or by
# `dropped`).
NOTE_STATUS = ("thinking", "dropped")
# Every state a note can be IN, in the order it moves through them: the two
# above that a person sets, plus the one only a promotion can give it.
# `NOTE_STATUS` is what may be written to a file; this is what a page may draw
# and sort by.
NOTE_STATES = ("thinking", "promoted", "dropped")


class Note(Record):
    """An idea before anybody knows what it is.

    Stored as `notes/<id>.md`. Like the issue above it is a Record on an
    unplanned rung, and the docstring there carries the argument for the new
    boundary; what this one keeps is the distinction between the two inboxes,
    which the model change did not touch:

        an issue is "we found something existing that is broken";
        a note is "we are thinking of creating something that does not exist
        and our ideas are confused".

    A note is therefore not a pitch in `shaping`, which is the thing it most
    looks like from a distance. A pitch presupposes that you know what you are
    shaping: it has a problem, a solution and an appetite, and it sits on the
    betting table as a bet somebody could take. A note precedes all three, and
    `planned=False` on its rung is what keeps the plan from looking like it
    holds bets nobody has made — enforced in `build_index`, guarded by the
    Index validator, swept by the KINDS-derived test.

    The fields it declares are the ones a confused idea can honestly carry:
    `written_by` is who to ask, not who owns it (an owner is a commitment, and
    the whole claim of this record is that nobody has committed to anything);
    `became` is the records it graduated into, one direction only, exactly as
    `Issue.pitched_into` is. Every work field it inherits from Record —
    owner, cycle, priority, the lot — is on `unread_fields("note")`, so the
    editors never offer one and the validator reports one that is written in
    by hand.
    """

    # The same rule as the other two ladders: a record opens on the first word of
    # its own. This one has held the word `thinking` since notes existed — it is
    # where the word came from — and `STATUS_ORDER` has now borrowed it.
    status: str = NOTE_STATUS[0]
    written_by: str | None = None
    written_on: date | None = None
    # The records this note graduated into. On the NOTE and not on the planned
    # record it became: a `from_note` field on `Record` would put a note id
    # into the type every view of the plan is built from. What the promoted
    # record says about where it came from, it says in its own shaping
    # document, in prose. See `shaping_document`.
    became: list[str] = []

    def state(self, records: dict[str, Record]) -> str:
        """`dropped` first and unconditionally — "we are not doing this" was
        said by a person, and somebody linking a record afterwards does not
        un-say it (the same rule `Issue.state` gives `shelved`). `promoted`
        when at least one thing it became exists — not all of them, because a
        brainstorm that splits into two pitches is promoted the moment either
        exists. A link whose target is gone falls back to `thinking` rather
        than claiming a promotion nobody can open; the missing id is a warning
        beside the note, where it can be fixed. Nothing here reads the STATUS
        of what it became: whether that pitch ships is the pitch's business.
        """
        if self.status == "dropped":
            return "dropped"
        if any(target in records for target in self.became):
            return "promoted"
        return self.status


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
    prefix: str  # what its ids start with
    directory: str  # where its files live
    model: type[Record]
    under: tuple[str, ...]  # the kinds it may be filed under, nearest first
    schedules: bool  # does the scheduler give it dates
    depends: bool  # may it wait on anything
    sized: bool  # may it carry person_weeks
    carded: bool  # does a hover show its shaping document
    planned: bool  # does it appear in the plan: table, graph, timeline, people, scheduler
    statuses: tuple[str, ...]  # the status vocabulary this kind reads; () means status is not read
    # The field that answers "who is behind this record". Per rung because the
    # kinds do not share one: `owner` is who HOLDS a piece of work, `reported_by`
    # and `written_by` are who noticed or wrote — which is why the column that
    # reads this is headed "Who" and not "Created by": a header promising
    # authorship over a field recording ownership is copy drift.
    who: str


KINDS: tuple[Rung, ...] = (
    # `statuses=()` — status is one of the nine fields a product does not read
    # (jcanton, 2026-08-20: a codebase is not `in_progress`), and () is how the
    # ladder says so now that the vocabulary is a per-rung fact.
    # `who="owner"` on a rung whose `owner` is unread (it is in `_WORK_FIELDS`
    # and a product is not work): the readers of `who` go through
    # `unread_fields`, so a product answers "Who" with nothing rather than with
    # a field it does not read.
    Rung(
        "product",
        "prod",
        "products",
        Product,
        under=(),
        schedules=False,
        depends=False,
        sized=False,
        carded=False,
        planned=True,
        statuses=(),
        who="owner",
    ),
    Rung(
        "project",
        "proj",
        "projects",
        Project,
        under=("product",),
        schedules=True,
        depends=True,
        sized=False,
        carded=True,
        planned=True,
        statuses=STATUS_ORDER,
        who="owner",
    ),
    Rung(
        "pitch",
        "pitch",
        "pitches",
        Pitch,
        under=("project",),
        schedules=True,
        depends=True,
        sized=True,
        carded=True,
        planned=True,
        statuses=STATUS_ORDER,
        who="owner",
    ),
    # A task may skip the pitch — work that nobody shaped still belongs to a
    # project — which is why `under` is written out per rung rather than derived
    # as "everything coarser". Derived, a task could be filed straight under a
    # product, three rungs up, which is not a thing anybody means.
    Rung(
        "task",
        "task",
        "tasks",
        Task,
        under=("pitch", "project"),
        schedules=True,
        depends=True,
        sized=True,
        carded=True,
        planned=True,
        statuses=STATUS_ORDER,
        who="owner",
    ),
    Rung(
        "issue",
        "issue",
        "issues",
        Issue,
        under=(),
        schedules=False,
        depends=False,
        sized=False,
        carded=False,
        planned=False,
        statuses=ISSUE_STATUS,
        who="reported_by",
    ),
    Rung(
        "note",
        "note",
        "notes",
        Note,
        under=(),
        schedules=False,
        depends=False,
        sized=False,
        carded=False,
        planned=False,
        statuses=NOTE_STATUS,
        who="written_by",
    ),
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
    "owner",
    "assignees",
    "reviewers",
    "review_waived",
    "start_date",
    "cycle",
    "priority",
    "prs",
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
_MODELS: dict[str, type[Record]] = {rung.name: rung.model for rung in KINDS}
_ID_PREFIXES = {rung.prefix: rung.name for rung in KINDS}
# Where a reader looks for records. Written out at the top of this file, it was
# the FIFTH copy of the ladder — with `PREFIX` and `_KIND_MODELS` in `render.py`
# and `DIRECTORY` in `web.py` — and it is the one that failed silently: a plan
# holding two products loaded thirty-three records and none of them was a
# product, with nothing reported, because a directory nobody walks is a
# directory whose files do not exist.
_RECORD_DIRS = tuple(rung.directory for rung in KINDS)


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
    record_paths, _ = record_paths_in(_RECORD_DIRS, stamps)
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


def parse_text(text: str, source: str) -> Record:
    """Parse one record file. `source` names the file in error messages only."""
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
    record = model.model_validate({"id": "", "title": "", **fields, "kind": kind, "body": body})
    # The record remembers the file it came from, because it is the only moment
    # both halves of its identity are in the same place. `source` was already here
    # and was only ever used to name the file in an error message.
    record._source = source
    record._unread = tuple(name for name in data if name not in model.model_fields)
    return record


def parse_file(path: Path) -> Record:
    return parse_text(path.read_text(encoding="utf-8"), str(path))


def parse_cycle_text(text: str, source: str) -> Cycle:
    """Parse one cycle file. Same frontmatter-and-body shape as a record, and a
    different type: nearly every field a Record carries is nonsense on a cycle,
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
    special case in the record save, all of it paid for a fact the filename
    already carried.
    """
    frontmatter, _ = _split(text, source)
    data = _round_trip_yaml().load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the frontmatter has to be a map of fields, and this is not")
    fields = {k: v for k, v in data.items() if k in Person.model_fields and k != "login"}
    return Person.model_validate({**fields, "login": login_of(source)})


def _as_block(text: object) -> object:
    """Multi-line text as a YAML literal block, where a literal block is safe.

    Slide prose is the first prose this tool puts in frontmatter, and the default
    emitter writes it as `body: "hello\\nworld"` — one long line of escapes. That
    is readable by the parser and not by a person, and "edit it in git if you
    prefer" is a promise this repository keeps by not writing files nobody wants
    to open. A literal block gives back the lines somebody typed.

    Guarded, because the block form cannot carry everything a string can. A line
    ending in a space loses it — YAML strips trailing whitespace on every line of
    a literal block, so the round trip would come back different from what was
    saved, silently, which is worse than an ugly line. `\\r` is the same problem
    with a different spelling: the emitter has no way to say "this line ends in a
    carriage return" inside a block. Both fall back to the quoted form, which is
    ugly and exact.

    Exactness beats beauty in a file that is also a record, so the guard is what
    the value CAN do rather than what it usually does.
    """
    if not isinstance(text, str) or "\n" not in text or "\r" in text:
        return text
    if any(line != line.rstrip() for line in text.split("\n")):
        return text
    return LiteralScalarString(text)


def _readable_slide(mapping: object) -> object:
    """The same mapping, with a slide's prose written as lines rather than escapes.

    Narrow on purpose: it reaches for exactly one key in exactly one nested map,
    and leaves a mapping without one alone. A general walk that blockified every
    multi-line string it met would reformat `goal`, a title somebody wrapped, and
    every field this tool has not thought about yet — which is the one thing
    `serialise` exists to never do.
    """
    if isinstance(mapping, dict) and isinstance(mapping.get("slide"), dict):
        slide = mapping["slide"]
        if "body" in slide:
            slide["body"] = _as_block(slide["body"])
    return mapping


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
    # A scalar-to-list clause stood here for `shaped_by`, the one list field
    # whose validator accepted a bare string. The field is retired, no list
    # field parses from a scalar any more, and a branch no input can reach is a
    # branch that silently rots — so it went with the field.
    return new


def serialise(record: Record, original_text: str | None = None) -> str:
    """Render a record back to file text, preserving the original formatting.

    Given the file it came from, the frontmatter is edited in place: a key keeps
    its position, its comment and its style, and only keys whose value actually
    changed are rewritten. Without an original this writes a fresh skeleton with
    every field spelled out, nulls included, so the next human edit has something
    to fill in.
    """
    yaml = _round_trip_yaml()
    dumped = record.model_dump(exclude={"body"})
    if original_text is None:
        data = dumped
    else:
        data = yaml.load(_split(original_text, record.id)[0]) or {}
        for key, value in dumped.items():
            if key in data:
                if data[key] != value:
                    data[key] = _in_the_style_of(data[key], value)
            elif value != type(record).model_fields[key].default:
                data[key] = value

    stream = io.StringIO()
    yaml.dump(_readable_slide(data), stream)
    return f"---\n{stream.getvalue()}---\n" + (f"\n{record.body}" if record.body else "")


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


def load_repo(root: Path) -> tuple[list[Record], Config, list[Unreadable]]:
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
    record_paths, nested_records = _plan_files(root, *_RECORD_DIRS)
    records, unreadable = readable(
        record_paths,
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
        lambda relative: parse_cycle_text((root / relative).read_text(encoding="utf-8"), relative),
    )
    # The person records, through the same door. One file per person is
    # what makes a bad one cost one person's icon instead of the whole page — the
    # arrangement this replaced put every icon and the roster in one file, where a
    # single hand edit took all of them at once.
    people_paths, nested_people = _plan_files(root, PEOPLE_DIR)
    people, unreadable_people = readable(
        people_paths,
        lambda relative: parse_person_text((root / relative).read_text(encoding="utf-8"), relative),
    )
    config, unreadable_config = read_config(*_config_on_disk(root))
    return (
        records,
        config.with_plans(plans).with_people(people),
        # Sorted by path, so the banner and `openproj check` list them in the
        # order somebody would open them rather than in the order the separate
        # walks happened to finish.
        sorted(
            [
                *unreadable,
                *unreadable_plans,
                *unreadable_people,
                *unreadable_config,
                # A record filed one directory too deep is a file that is not a
                # record, and lands in the same list for the same reason.
                *nested_records,
                *nested_plans,
                *nested_people,
            ],
            key=lambda one: one.path,
        ),
    )


def ancestors(record_id: str, by_id: dict[str, Record]) -> list[str]:
    """The parent chain, nearest first.

    A cycle in the chain is a validation blocker (see `validate_all`), so here it
    only has to stop: return the chain walked so far rather than spinning.
    """
    chain: list[str] = []
    seen = {record_id}
    record = by_id.get(record_id)
    while record is not None and record.parent is not None and record.parent not in seen:
        chain.append(record.parent)
        seen.add(record.parent)
        record = by_id.get(record.parent)
    return chain


def size_weeks(record: Record) -> float | None:
    """Weeks of work somebody stated, or None where nobody has stated any.

    One field on a pitch and a task, and none on a project — a container has no
    size of its own. Read here rather than reached for directly, so the scheduler,
    the index and the pages cannot disagree about what a missing one means.

    **There is no default appetite, and None is what stands where it stood.** An
    absent size used to come back as `config.default_task_effort` — half a week
    nobody had typed — with a second return value saying the number was invented;
    and a flag is only as good as the callers that read it. Three dropped it on
    the floor, so the invented half-week was summed into a cycle's bet, charged
    against a person's capacity and turned into a bar on the timeline, each of
    those places presenting it exactly as it presents a number somebody
    estimated. The setting is gone rather than defaulted to zero, because zero is
    a size and this is the absence of one: a caller has to decide what it does
    about a record nobody has sized, and it cannot decide that if this function
    keeps answering on its behalf.
    """
    stated = getattr(record, "person_weeks", None)
    return None if stated is None else float(stated)


def workers_on(record: Record) -> list[str]:
    """Everyone on the hook for this record, each counted once.

    An owner who is also an assignee — which is most of them — was counted twice,
    so they were booked twice and, now that the workers divide the size, would
    have halved it on their own.

    Here rather than in `schedule.py`, where it was written, because two things
    now ask it. The scheduler divides a size by these people's availabilities to
    get a duration; `_rollup_problems` names how many of them there are in the
    sentence it yields, since "the 4.0 the bet buys at 2" is unreadable without
    the 2. Both readings have to come off the same list or the sentence explains
    a number computed from a different set of names than the one it counts.
    """
    named = ([record.owner] if record.owner else []) + list(record.assignees)
    return list(dict.fromkeys(named))


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


def lead_text(body: str) -> str:
    """Everything above the first heading — the opening `sections` cannot name.

    `sections` keys its answer by heading, so the paragraph a record opens with
    is in none of them. On a well-shaped record that is nothing at all, because
    the template opens with `## Problem`; on a chore somebody wrote three
    sentences into it is the entire document, and a slide chooser built only out
    of headings would have had nothing to offer for it.

    A heading inside a fence is not a heading, which is the same `_outside_code`
    walk every reader here makes and matters more than usual: a record whose
    opening paragraph quotes a markdown example would otherwise end at the `#`
    inside the quote.
    """
    out: list[str] = []
    for line, in_code in _outside_code(body):
        if not in_code and _HEADING.match(line):
            break
        out.append(line)
    return "\n".join(out).strip("\n")


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
            found.append((mark.group(1) != " ", line[mark.end() :].strip()))
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
    for line, in_code in kept[at + 1 :]:
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
                text.strip() for text, nested in under if nested or not _HEADING.match(text)
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


# Where the author says "and then a second slide". A whole line, so a `\newslide`
# written mid-sentence is the word and not a break, and outside a code fence, so
# a document explaining this feature can quote it.
#
# `\newslide` and not `---`, which is what reveal.js, remark and Marp all use and
# was the first candidate. It cannot be used here: `---` is the frontmatter fence
# this repository's own parser splits on, and `_SPLITTER.split` would read the
# first one in a slide as the end of the record's frontmatter. Choosing the
# convention every other deck tool uses would have meant a record that no longer
# loads, which is the one cost this codebase refuses everywhere else. jcanton
# asked for `\newslide` before any of that was worked out, and it is the spelling
# that survives the constraint.
_NEWSLIDE = re.compile(r"^[ \t]*\\newslide[ \t]*$")


def slide_chunks(prose: str) -> list[str]:
    """One entry per slide the author asked for, in order, at least one always.

    Always at least one, and that is what the callers rely on: a record with no
    slide prose at all still has a slide — the generated one — so the empty
    string is a chunk rather than an absence. A list that could be empty would
    put `if chunks:` at every call site, and one of them would get it wrong.

    Split outside code fences, so a `\\newslide` inside a triple-backtick block
    is text somebody is showing rather than a break they are asking for. This is
    the same `_outside_code` walk `sections` and `checklist_items` use, for the
    same reason each of them uses it.
    """
    chunks: list[list[str]] = [[]]
    for line, in_code in _outside_code(prose):
        if not in_code and _NEWSLIDE.match(line):
            chunks.append([])
            continue
        chunks[-1].append(line)
    return ["\n".join(lines).strip("\n") for lines in chunks]


def slide_title(title: str, at: int) -> str:
    """`Title`, then `Title (2)`, `Title (3)` for each continuation after it.

    The first slide is never numbered, whether or not any follow — jcanton,
    2026-08-25: "no (1) on the first / unique". A `(1)` says the same thing the
    absence of a number already says, and it says it on the one slide of the
    record that most often stands alone.
    """
    return title if at == 0 else f"{title} ({at + 1})"


# --------------------------------------------------------------------------- #
# Validation
#
# Rules are data, not branches: each carries the schema_version that introduced
# it, which is what makes grandfathering possible. A rule newer than the record
# it is judging may only warn. Adding a required field must never invalidate a
# corpus written before the field existed — otherwise the rule gets reverted
# rather than adopted.
# --------------------------------------------------------------------------- #

# One pattern for every rung, issues and notes included — where there were
# three. The comments that stood here argued the opposite: the plan-only
# pattern was what kept `projects|pitches|tasks/<id>.md` the whole writable
# surface, so admitting an inbox id would have widened that surface "by
# degrees", and each inbox therefore kept a pattern of its own. Both halves of
# that argument moved when the ladder did. The writable surface is now DERIVED
# from `KINDS` (`web.ID_PATTERN`, `web.DIRECTORY`), so it widens exactly when a
# rung is added and never otherwise — there is no "by degrees" left to lose.
# And what keeps an issue out of the PLAN is no longer which pattern its id
# matches but `planned=False` on its rung, enforced once in `build_index`,
# asserted by the Index model_validator, and swept by the KINDS-derived
# exclusion test. A pattern was the wrong home for that rule anyway: it could
# only refuse ids, and the leak it guarded against — an issue on the timeline —
# never travelled through an id.
#
# Public and the ONLY copy: `web.py` imports this rather than deriving the same
# regex a second time, because it is both what the validator judges an id by and
# what closes `<directory>/<id>.md` as a writable path — the arrangement the old
# note pattern's own comment argued for, now applied to the one pattern there
# is. `\A` and `\Z`, not `^` and `$`, for the reason `LOGIN_PATTERN` gives
# below: in Python `$` also matches immediately before a trailing newline, so
# `^…$` admits `task-a1b2c3\n` — an id that passes the guard and would then
# become the path `tasks/task-a1b2c3\n.md`. Each prefix through `re.escape`,
# because nothing else stops a future rung's prefix carrying a regex
# metacharacter into an alternation.
ID_PATTERN = re.compile(
    r"\A(" + "|".join(re.escape(rung.prefix) for rung in KINDS) + r")-[0-9a-f]{6}\Z"
)
# The three questions a kind has to answer before a record of it can be written:
# what its ids start with, where its file goes, and which model reads it. All
# three are `Rung` columns, and all three are derived HERE rather than wherever
# somebody happens to need them.
#
# `web.py` used to hold its own copies and its own comments counted them — "the
# SEVENTH copy, written out three lines under a map that was already derived" —
# and the CLI needing the same three is what finally moved them down. It could
# not import them from `web.py` without pulling FastAPI, uvicorn and the whole
# server into `openproj check`, and a fourth derivation to avoid an import is how
# a ladder gets a rung in one place and not another.
PREFIX = {rung.name: rung.prefix for rung in KINDS}
DIRECTORY = {rung.name: rung.directory for rung in KINDS}
MODELS: dict[str, type[Record]] = {rung.name: rung.model for rung in KINDS}
_PREFIX_FOR_KIND = PREFIX
_SIZE_FIELD = {"pitch": "person_weeks", "task": "person_weeks"}


class Inbox(NamedTuple):
    """What a writer owns when an inbox record is created, and the link a
    promotion writes on it.

    One row per unplanned rung, because these were the defaults of the deleted
    `POST /api/issue` and `POST /api/note` routes, and losing them would make the
    shortest write paths in the tool ask for four fields instead of a title.
    """

    author: str  # defaults to whoever is writing; the caller may say otherwise
    dated: str  # never the caller's: when a record was made is not an opinion
    link: str  # what a promotion appends the new record's id to


INBOXES = {
    "issue": Inbox("reported_by", "opened_on", "pitched_into"),
    "note": Inbox("written_by", "written_on", "became"),
}


def mint_id(kind: str, taken: Collection[str] = ()) -> str:
    """A new id for this kind, avoiding any already spoken for.

    Never accepted from a caller who is not trusted with a path: an id supplied
    by a browser is a path supplied by a browser the moment it becomes
    `<directory>/<id>.md`.

    Six hex characters is 16.7 million and not infinity, and the loser of a
    collision is a record silently written over by the next one. `taken` is
    empty for a caller that has no cheap way to enumerate what exists; re-minting
    costs nothing for one that does.
    """
    while True:
        minted = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        if minted not in taken:
            return minted


def unknown_fields(kind: str, fields: Iterable[str]) -> list[str]:
    """The names this kind's model does not own, sorted.

    A pitch has an appetite and a task has an effort, and the two write paths
    reach this question from opposite directions: a create form carrying every
    kind's controls and hiding the ones that do not apply, and a `--set` on a
    command line. Both write fields to the file before the model ever sees them,
    so a key the model does not own would sit in the frontmatter unread by
    anything, with every later reader believing it meant something.
    """
    return sorted(set(fields) - set(MODELS[kind].model_fields))


def in_model_order(kind: str, fields: dict) -> dict:
    """The same fields, in the order this kind's model declares them.

    `patch_text` writes keys in the order the mapping hands them over, which
    without this is whatever order the caller happened to build: a file led by
    whichever `--set` came first on a command line, or by whichever key a form's
    JSON serialised first, with `id` wherever it fell. Every record in the corpus
    opens `id`, `kind`, `title`, and the models declare those three in exactly
    that order — so the model IS the convention, and reading the order off it
    beats writing the same list down again here.

    Both write paths go through this, so a record created in the browser and one
    created from a terminal are the same file. They were not, and nothing would
    have told anybody: two orders are both valid YAML and both read back
    identically, so the only thing that noticed was a person reading a diff.

    A field the model does not own is dropped. Both callers have already refused
    those by name through `unknown_fields`, so there is nothing here to lose —
    and silently carrying one through would put it in the frontmatter unread,
    which is the thing that check exists to prevent.
    """
    return {field: fields[field] for field in MODELS[kind].model_fields if field in fields}


def opening_fields(
    kind: str,
    fields: dict,
    config: Config,
    *,
    record_id: str,
    who: str | None = None,
    today: date | None = None,
) -> dict:
    """The frontmatter of a record five seconds old: what the writer owns, over
    what the caller asked for.

    One copy, because the two write paths — `POST /api/record` and `openproj new`
    — differ in everything except this. One has a signed-in login, a commit to
    read the config at and a compare-and-swap; the other has a working directory
    and a person at a terminal. What they share is the answer to "what does a new
    record of this kind arrive with", and that answer being written down twice is
    exactly the failure this whole change is about: an agent copying a
    neighbouring record got `prs` wrong because nothing ran the rules at the
    moment of writing, and two spellings of the defaults would have been the same
    bug one level up.

    `who` is a default and not a fact — somebody files what a colleague mentioned
    in a corridor, so a caller may say otherwise, and a caller that does not know
    (a terminal knows a git identity, and the plan is written in GitHub logins)
    passes None rather than guessing. The DATE is not a default: `opened_on` and
    `written_on` are derived rows on the page, and a caller that sends one is
    overruled rather than obeyed.

    Grandfathering protects the corpus that already exists and never the record
    being written right now, so the schema version is the repository's own number
    at the moment of writing: something created today is held to today's rules.

    The caller's mapping is copied, not written through. A function that fills in
    six defaults and also mutates its argument is two things, and the second one
    is invisible at the call site.

    Fields and not finished text, so that what a caller does with them afterwards
    stays the caller's: `openproj new` puts them in the model's declared order
    before writing, and the create route hands over whatever the form sent. That
    is a difference worth being able to have — and if the two ever should agree
    about key order, the place to say so is one line at each call and not a
    parameter here.
    """
    opening = dict(fields)
    opening["id"] = record_id
    inbox = INBOXES.get(kind)
    if inbox is not None:
        if who is not None:
            opening.setdefault(inbox.author, who)
        opening.setdefault("status", opens_at(kind))
        opening[inbox.dated] = (today or date.today()).isoformat()
    opening.setdefault("created_schema_version", config.schema_version)
    return opening


def opens_at(kind: str) -> str:
    """The status a record of this kind is created in, off the model.

    There used to be an `opens` column on the ladder holding `ready` for an issue
    and `thinking` for a note — the same two words the models already declare as
    their defaults, written out a second time. Nothing caught that, because the
    two copies agreed, and they agreed until the day the planned ladder gained a
    rung at its foot and somebody had to remember there was a second list. A
    planned record already gets this for free: a writer that sets no `status` key
    for one leaves it to open at whatever the model says on the way back in. This
    is the same fact for the two rungs that do write the key, asked of the same
    place.
    """
    return str(MODELS[kind].model_fields["status"].default)


def _an(kind: str) -> str:
    """`a task`, `an issue` — the article this module's own prose uses.

    A problem message is a sentence somebody reads, and `f"a {kind}"` read
    "a issue" the day issues joined the ladder. One helper, imported by
    `web.py` for its refusals, because two spellings of one sentence rule is
    how one of them comes to say "a issue" again.
    """
    return f"an {kind}" if kind[:1] in "aeiou" else f"a {kind}"


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


def loop_made(candidate: Record, plan: Iterable[Record]) -> str | None:
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
    by_id = {record.id: record for record in plan if record.id != candidate.id}
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
    record: Record, by_id: dict[str, Record], parent_cycles: set[str], dep_cycles: set[str]
) -> Iterator[tuple[str, str | None, str, int]]:
    if record.id in dep_cycles:
        yield "blocker", "depends_on", "part of a blocked-by cycle", 1
        return
    # A parent cycle makes "ancestor" undefined, so the relational checks are
    # skipped rather than reporting a second, derived problem for one broken chain.
    own_ancestors = set() if record.id in parent_cycles else set(ancestors(record.id, by_id))
    for target in record.depends_on:
        if target not in by_id:
            yield "blocker", "depends_on", f"blocked by {target}, which does not exist", 1
        elif target in own_ancestors:
            yield "blocker", "depends_on", f"cannot depend on {target}: it is an ancestor", 1
        elif record.id in ancestors(target, by_id):
            yield "blocker", "depends_on", f"cannot depend on {target}: it is a descendant", 1
        elif by_id[target].status == "shelved":
            yield "warning", "depends_on", f"blocked by {target}, which is shelved", 1


def under(record_id: str, children: dict[str, list[str]]) -> list[str]:
    """Every record filed below this one, however deep, each once and not itself.

    What a delete has to cascade over. Read from the index's `children` map — ids
    rather than records, which is the shape the write path has — and returned in
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
    seen: set[str] = {record_id}
    stack = list(children.get(record_id, []))
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        found.append(child)
        stack += children.get(child, [])
    return found


def reviewers_under(record_id: str, children: dict[str, list[Record]]) -> list[str]:
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
    seen: set[str] = {record_id}
    stack = list(children.get(record_id, []))
    while stack:
        child = stack.pop()
        if child.id in seen:
            continue
        seen.add(child.id)
        found += child.reviewers
        stack += children.get(child.id, [])
    return list(dict.fromkeys(found))


def _appetite_problem(record: Record, sentence: str) -> Iterator[tuple[str, str | None, str, int]]:
    """The size gate, in the words of the status asking for it.

    Two statuses demand an appetite and both ask the same three questions — does
    this rung carry a size field, is it empty, and which field is it called —
    so they ask them in one place. Written out twice, the copy that would rot is
    the field lookup: `_SIZE_FIELD` is what keeps `person_weeks` from being named
    in a message, and a second hand-written `getattr(record, "person_weeks")`
    would be a gate that silently stops firing for a rung added later.

    A container yields nothing rather than a blocker it could never satisfy: a
    project has no size of its own, which is `size_weeks`' first sentence, and
    `_SIZE_FIELD` is where that is written down.

    Stamped 1, the version the `ready` gate already carries, because this is that
    rule reaching one rung further and not a new demand. Grandfathering it under
    a newer version would demote it to a warning for every record in the corpus
    — which is every record it was written for, since the unsized-and-running
    state is one that existing plans are already in.
    """
    field = _SIZE_FIELD.get(record.kind)
    if field is not None and getattr(record, field) is None:
        # One field and one word now. It was `appetite_weeks` on a pitch and
        # `effort_weeks` on a task — one quantity under two names, which
        # `size_weeks` had to paper over on every read.
        yield "blocker", field, sentence, 1


# The statuses at which the work has not begun, read off the ladder rather than
# written out as three words. `STATUS_ORDER` is the ladder and `in_progress` is
# where work starts, so everything before it is a forecast; a rung added at the
# foot — which is exactly what putting `thinking` in front of `shaping` was —
# joins this set on the commit that adds it, and a hand-written triple would not
# have. `shelved` falls on the far side by construction, being last: parked work
# is exempt from every rule anyway (`_parked`), and a date on it is a record of
# work that was picked up and put down rather than a forecast that has rotted.
_BEFORE_WORK_BEGINS = STATUS_ORDER[: STATUS_ORDER.index("in_progress")]


def start_date_has_passed(record: Record, today: date) -> bool:
    """Whether this record states a start date that has passed with nothing begun.

    **One function, two callers, and that is the whole reason it is a function.**
    `web.py` refuses a date TYPED into the past at the door, with a 422; this
    module warns about one that DRIFTED there, because a date typed as future
    becomes past by the passage of time with nobody editing anything, and no
    refusal at any door will ever fire on that. Two situations, two severities and
    two sentences — but one question, asked once. This repository has been bitten
    three times by one fact with two implementations (the search blob, the
    `(none)` sentinel, and `appetite_weeks` reading as three different numbers
    across three pages), and a second copy of this one would disagree with the
    first at exactly the boundary that matters, which is whether `in_progress` is
    inside the rule or outside it.

    **Scoped to status, and it has to be, or a legitimate edit becomes
    impossible.** At `in_progress` a start date in the past is not merely allowed,
    it is the correct value and the gate above demands the field: "I started this
    on Monday and it is now Wednesday" is the ordinary case. Unscoped, a blanket
    refusal would force somebody to change the status first and backfill the date
    second — the wrong order, and the one everybody would get wrong. At `done` the
    date is the whole span.

    A kind the scheduler never sees is outside it too, for the reason
    `_status_problems` opens with: a rung that reads no dates has no work state to
    gate, and `unread_fields` already says beside the record that its start date
    is not read there. A second sentence about the same key would be this file
    arguing with itself.
    """
    if record.start_date is None or record.status not in _BEFORE_WORK_BEGINS:
        return False
    if record.kind in RUNG and not RUNG[record.kind].schedules:
        return False
    return record.start_date < today


def _status_problems(
    record: Record, reviewers: list[str] | None = None
) -> Iterator[tuple[str, str | None, str, int]]:
    """One gate per status, not a cumulative stack.

    `thinking` and `shaping` are exempt because an idea nobody has bet on yet has
    no owner and no size by definition, and demanding them is how a tracker stops
    being somewhere people put half-formed things. `thinking` the more so: it is
    the word for "nobody has looked at this yet", so it can only ever demand less
    than the rung above it, and it demands nothing.

    `thinking` is *named* in that tuple rather than left to the `elif` chain,
    which would give it the same silence by accident — no branch matches it, so
    nothing is yielded and `required_at` lists it against no field. The behaviour
    is identical either way; what the tuple buys is that the exemption is a
    sentence somebody wrote, in the place a reader looks to ask what a status
    demands, rather than a gap that lasts until the chain grows an `else`.

    `done` is exempt from the earlier gates for a duller reason: migrated history
    often cannot say who owned something in 2025, and a validator that blocks on
    unknowable facts gets switched off.

    Every message names its field the way the reader's screen names it, never the
    way the file spells it. A message is a sentence somebody reads, and it used to
    sit two inches under a checkbox labelled "Review waived" saying `review_waived`
    — one field with two names on one screen. The identifier is not lost: it stays
    on `Problem.field`, which is how the page finds the control to mark.
    """
    # Whoever reviews this, counting the work under it. `None` means "ask the
    # record itself", which is what a blank record with no corpus around it can
    # answer — `required_at` derives the gates that way.
    reviews = record.reviewers if reviewers is None else reviewers
    # A rung the scheduler never sees has no work state to gate. On a product,
    # `status` is a label to filter by — shelved hides a codebase and everything
    # under it — and not a claim that anybody is doing it, so demanding an owner
    # at `ready` and a PR at `done` would be demanding the very fields the same
    # ladder says the record does not read.
    if record.kind in RUNG and not RUNG[record.kind].schedules:
        return
    if record.status in ("thinking", "shaping", "shelved"):
        return
    if record.status == "ready":
        if record.owner is None:
            yield "blocker", "owner", "a ready record needs an owner", 1
        # And somebody actually on it. An owner is who answers for the bet, which
        # is not the same question as who is doing the work — the scheduler prices
        # a record by the people on it (`workers_on`), so a bet with an owner and
        # nobody assigned is a bet that has been accepted and staffed with nobody.
        # jcanton, 2026-08-22.
        if not record.assignees:
            yield "blocker", "assignees", "a ready record needs somebody on it", 2
        if not (record.review_waived or reviews):
            yield "blocker", "reviewers", "a ready record needs a reviewer, or review waived", 1
        yield from _appetite_problem(record, f"a ready {record.kind} needs an appetite")
        # No shaped_by gate any more: a pitch's owner IS who shaped it, and the
        # owner rule above already asks every ready record for one.
    elif record.status == "in_progress":
        if record.start_date is None:
            yield "blocker", "start_date", "work in progress needs the date it started", 1
        # And it needs a size, for the same reason `ready` does and one more.
        # The gate used to stop at `ready`, so a record could be sized-checked on
        # the way in, have its appetite deleted, and go on running with none —
        # and reaching `in_progress` without ever passing `ready` is the ordinary
        # path rather than a rung somebody skipped, which is why icon4py-plan has
        # three of these. With no default standing behind them, an unsized record
        # in flight now has no span, no bar, no weight in its pitch's rollup and
        # no claim on anybody's capacity: it is work that is happening and that
        # the plan cannot account for at all.
        yield from _appetite_problem(record, "work in progress needs an appetite")
        if not record.assignees:
            yield "blocker", "assignees", "work in progress needs somebody on it", 2
        if not record.review_waived and not (set(reviews) - {record.owner}):
            yield (
                "blocker",
                "reviewers",
                "work in progress needs a reviewer other than its owner, or review waived",
                1,
            )
    elif record.status == "done" and not record.prs:
        yield "blocker", "prs", "a done record needs at least one PR", 1


def required_at(kind: str | None = None) -> dict[str, tuple[str, ...]]:
    """Which statuses demand each field, derived from the gate rather than copied.

    A form needs this and an HTML `required` attribute cannot express it: what the
    form must hold depends on the status chosen in that same form a moment ago. So
    the page carries the gates itself — and the map it used to carry was written by
    hand as "the first status that demands it", read cumulatively, which is not
    what the rules say. `_status_problems` is a chain of `elif`: `done` wants a PR
    and forgives the owner that `ready` insists on, deliberately, because migrated
    history often cannot name who owned something in 2025. Read cumulatively, the
    form refused to create exactly the record the server would have accepted.

    Derived by running the gate over a blank record of each kind at each status and
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


def _vocabulary_problems(record: Record) -> Iterator[tuple[str, str | None, str, int]]:
    """A word nobody defined, named where it is rather than as a stack trace."""
    statuses = RUNG[record.kind].statuses
    # An empty vocabulary means the kind reads no status, so there is no word to
    # judge: `unread_fields` already reports a status written on such a file as
    # "not read", and a blocker on top of that would hold a product to a ladder
    # it was just told it does not have. Judging against `STATUS_ORDER` here is
    # what this replaced, and it was wrong in both directions at once: it would
    # turn every stale note into an ungrandfatherable blocker the day notes
    # become records, and it makes `shaping` silently legal on an issue.
    if statuses and record.status not in statuses:
        # "for an issue", because the vocabulary is the rung's, not the tool's:
        # a word this rung refuses can be a real status on a planned rung —
        # `shaping` on a pitch — and a sentence that denies the word outright
        # argues with the page the reader just came from. The API refusal in
        # `web.py` already says "for {_an(kind)}"; two spellings of one
        # sentence rule is how one of them comes to drift.
        yield (
            "blocker",
            "status",
            f"{record.status!r} is not a status for {_an(record.kind)}: "
            f"expected one of {', '.join(statuses)}",
            1,
        )
    if record.priority not in PRIORITY_RANK:
        yield (
            "blocker",
            "priority",
            f"{record.priority!r} is not a priority: expected one of {', '.join(PRIORITY_RANK)}",
            1,
        )


def _people_problems(record: Record, config: Config) -> Iterator[tuple[str, str | None, str, int]]:
    """Names that are nobody, reported as a warning.

    A warning rather than a blocker on purpose: the roster is a file somebody
    maintains by hand, so it is always slightly behind reality, and a new
    colleague must not be unassignable on their first day. It catches the case
    that actually happens — a typo that quietly makes a task nobody reviews.
    """
    if not config.known_people:
        return
    for field in ("owner", "assignees", "reviewers", "reported_by", "written_by"):
        value = getattr(record, field, None)
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


def is_bettable(record: Record) -> bool:
    """Whether a cycle can be bet on this record.

    A pitch, or a task nobody pitched. Those are the two things a betting table
    puts a name against: everything else either contains bets (a project) or is
    part of one (a task under a pitch), and takes its cycle from what holds it.
    """
    return record.kind == "pitch" or (record.kind == "task" and record.parent is None)


def bet_of(record: Record, by_id: dict[str, Record]) -> Record | None:
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
    if is_bettable(record):
        return record
    if record.parent is None:
        return None
    parent = by_id.get(record.parent)
    if parent is None:
        return record
    return parent if is_bettable(parent) else None


def cycle_of(record: Record, by_id: dict[str, Record]) -> int | None:
    """The cycle this record's work belongs to: its own, or its pitch's."""
    bet = bet_of(record, by_id)
    return bet.cycle if bet is not None else None


def _containment_problems(
    record: Record, by_id: dict[str, Record]
) -> Iterator[tuple[str, str | None, str, int]]:
    """A parent of the wrong kind.

    Only when the parent resolves: a `parent` naming a file nobody wrote is
    deliberately not a problem, so that a plan half-way through an import still
    loads and still says what it can.
    """
    parent = by_id.get(record.parent) if record.parent else None
    if parent is None:
        return
    allowed = PARENT_KINDS.get(record.kind, ())
    if parent.kind not in allowed:
        # `_an`, because `by_id` is every record: a task hand-filed under an
        # issue reaches this sentence, and `f"a {kind}"` reads "a issue".
        belongs = " or ".join(_an(kind) for kind in allowed) or "nothing"
        yield (
            "blocker",
            "parent",
            f"{_an(record.kind)} belongs to {belongs}, not to {_an(parent.kind)}",
            4,
        )


def _bet_problems(
    record: Record, by_id: dict[str, Record]
) -> Iterator[tuple[str, str | None, str, int]]:
    """A cycle stamped on something nobody bets.

    A bet is made on a pitch, or on a chore nobody pitched. A task under a pitch
    is part of that bet and takes its cycle from it; a project is a container for
    bets and is not one. Stored on both, the two are one fact in two files and
    the copy is stale the first time somebody re-bets the pitch — which is the
    same argument that keeps `blocks` derived.
    """
    if record.cycle is None or is_bettable(record):
        return
    # Nothing to inherit from: an unresolved parent leaves this record's own
    # number the only one there is, and `bet_of` keeps it for that reason.
    if record.parent is not None and record.parent not in by_id:
        return
    if record.kind == "project":
        yield (
            "warning",
            "cycle",
            "a project is not bet — its pitches are, and its span is their rollup",
            4,
        )
        return
    parent = by_id.get(record.parent) if record.parent else None
    named = f" from {parent.id}" if parent is not None else ""
    yield (
        "warning",
        "cycle",
        f"the bet is on the pitch, so this task takes its cycle{named}; the number here is ignored",
        4,
    )


def _rollup_problems(
    record: Record, children: dict[str, list[Record]], spans: Mapping[str, Span] | None
) -> Iterator[tuple[str, str | None, str, int]]:
    """A pitch whose tasks, as actually staffed, do not fit in the box it was bet at.

    The appetite is the box and its tasks are what somebody proposes to put in
    it. Nothing compared the two, so a six-week bet holding seven and a half
    weeks of tasks read as a six-week bet everywhere on the site — and the span,
    which is the rollup of the children, quietly ran past it anyway.

    **Calendar against calendar, and it is the span that answers.** This summed
    the children's person-weeks and held the total against the parent's stated
    appetite, which answers "is there more work here than we said" — a question
    nobody is asking in front of a plan. Four person-weeks and one sit
    comfortably inside an eight person-week bet and still do not fit, if the bet
    bought four calendar weeks with two people and the tasks need four and a
    half on the one person holding both. So the box is `Span.budget_weeks` —
    this record's own appetite over the availability of its own people — and the
    contents is `Span.elapsed_weeks`, the length of the rolled-up span.

    **The span is what makes shared assignees come out right**, and it is why the
    sum went. Two tasks of four weeks and half a week are four and a half weeks
    of calendar if one person holds both and four if they run side by side on
    different people; a sum reports four and a half in both cases and is wrong in
    one of them. Nothing new had to be taught about parallelism, because `_place`
    books workers and a contended person already serialises their own work.

    That also retires a paragraph this docstring used to carry. Only stated sizes
    were compared, and that sentence was true of the parent and false of the
    children: every unsized child was summed at the old `config.default_task_effort`,
    so a warning telling somebody to cut scope quoted a total partly made of a
    number nobody typed. Both halves of that are gone — the default no longer
    exists, and an unsized record gets no span at all, so it drops out of the
    rollup by not being in it rather than by being filtered out of a sum. The
    conservatism survives the move: a pitch holding four unsized tasks and one
    sized one rolls up a span covering the sized one alone, which can only be
    shorter than the truth.

    **A warning, never a blocker**, because every remedy is a decision for a
    person — and the sentence names the third one the old wording could not see.
    Staffing shortens a bar, so putting another person on the pitch is as real an
    answer as cutting scope or re-betting, and the old arithmetic could not say
    so because people were not in it.

    **Silent without spans.** `validate_all` takes them optionally: the callers
    that validate one candidate record on its way to being written have no
    schedule and are reporting on that record, not on the plan around it. This
    rule is the plan's, and it is asked by `Index.load` and by `openproj check`,
    which schedule first.
    """
    kids = children.get(record.id, [])
    span = spans.get(record.id) if spans is not None else None
    if not kids or span is None:
        return
    # Silent where the parent has no appetite of its own — `budget_weeks` is None
    # for a container and for a pitch nobody has bet on yet, and a bet that was
    # never made cannot be exceeded. Silent too where the rollup has no length:
    # that is an unscheduled span, whose two dates stand for "no answer".
    if span.budget_weeks is None or span.elapsed_weeks is None:
        return
    if span.elapsed_weeks <= span.budget_weeks:
        return
    # `workers_on` and not `assignees`, because that is the list the scheduler
    # divided the appetite by to get the budget in the first place. Counting a
    # different set of names here would explain the number with the wrong one.
    # Nobody on it is one notional person, which is what `_duration_weeks`
    # assumed when it computed the budget being quoted.
    people = len(workers_on(record)) or 1
    # One decimal on both, and not the `:g` the rest of this module uses on sizes
    # somebody typed. These two are computed reals — an eight-week bet over two
    # people at 60% is 6.666666666666667 — and `:g` would put five decimal places
    # of arithmetic noise into a sentence a person is meant to act on.
    yield (
        "warning",
        _SIZE_FIELD.get(record.kind),
        f"its tasks need {span.elapsed_weeks:.1f} weeks with the people on them, more than "
        f"the {span.budget_weeks:.1f} the bet buys at {people} — "
        "cut scope, re-bet it, or put more people on it",
        4,
    )


def _carries(record: Record, field: str) -> bool:
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
    if field in record._unread:
        return True
    if field not in type(record).model_fields:
        return False
    value = getattr(record, field)
    if value in (None, [], "", False):
        return False
    return value != type(record).model_fields[field].get_default(call_default_factory=True)


# The links a promotion writes on its source, and the phrase each is reported
# with. One direction only — the promoted record does not list its sources — so
# the only thing that can rot is the target going away, and that is a warning,
# not a blocker: an issue outlives the pitch it fed, and a shelved pitch deleted
# later should not turn the record that pointed at it red. `state()` already
# shows the consequence (the claim quietly drops back to the stored status);
# this names WHICH id went, which is the part a person needs to repair it.
_PROMOTION_LINKS = {"pitched_into": "pitched into", "became": "became"}


# Fields this tool used to read and no longer does, and where each value lives
# now. Parsing is permissive, so a retired key survives in `_unread` and
# `patch_text` round-trips it byte for byte — nothing is lost from the file, and
# nothing appears on the screen. That silence is the "empty must not look like
# broken" family: a pitch that records who shaped it and shows nothing. So the
# key is named, once, here — a warning and never a blocker, because the file is
# not wrong, it is older than the vocabulary.
#
# `shaped_by` retired 2026-08-24 — jcanton: owner, shaped_by, assignees and
# reviewers was one hat too many, so `owner` on a pitch is who shaped it and
# holds it.
#
# `assigned_on` retired 2026-08-27 into `start_date`, and it is here for a
# sharper reason than the tidiness of the name: a date is the value being
# stranded. A file that still says `assigned_on:` parses clean, keeps the dead
# key for ever and loses the one date the whole schedule is derived from, so
# every record in it snaps to today's floor with nothing on any page to say
# why. That is not backwards compatibility — the field is gone — but the file
# is told so.
_RETIRED = {
    "shaped_by": "owner records who shaped a pitch and holds it — "
    "move the name there and delete this key",
    "assigned_on": "start_date records when the work began — "
    "move the date there and delete this key",
}


def _problems_for(
    record: Record,
    config: Config,
    by_id: dict[str, Record],
    children: dict[str, list[Record]],
    parent_cycles: set[str],
    dep_cycles: set[str],
    spans: Mapping[str, Span] | None,
    today: date,
) -> Iterator[tuple[str, str | None, str, int]]:
    """Yield (severity_before_grandfathering, field, message, rule_version)."""
    if not record.title.strip():
        yield "blocker", "title", "title must not be empty", 1
    if not ID_PATTERN.match(record.id):
        yield "blocker", "id", f"id must match {ID_PATTERN.pattern}", 1
    elif not record.id.startswith(_PREFIX_FOR_KIND[record.kind] + "-"):
        yield "blocker", "id", f"id prefix must match kind {record.kind}", 1

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
    if record.kind in RUNG:
        name = record.kind
        for field in unread_fields(name):
            if not _carries(record, field):
                continue
            if field == "depends_on":
                # The clause about projects, pitches and tasks belongs to the
                # container it was written for; an inbox record simply is not
                # work that waits.
                said = f"{_an(name)} waits on nothing"
                if RUNG[name].planned:
                    said += ": its projects, pitches and tasks do"
                yield "blocker", "depends_on", said, 1
            elif field == "person_weeks":
                yield "blocker", "person_weeks", f"{_an(name)} carries no appetite", 1
            else:
                # A warning and not a blocker: an owner on a container is ignored
                # rather than wrong, and refusing the file over it would be
                # refusing to load the plan over a word nobody reads. A planned
                # kind here is a grouping (today, a product); an unplanned one
                # is an inbox record, which is not a grouping of anything.
                what = (
                    f"{_an(name)} is a grouping and is never scheduled"
                    if RUNG[name].planned
                    else f"{_an(name)} is never scheduled"
                )
                yield "warning", field, f"{what}, so its {field} is not read", 1

    # Any kind, because a retired key is in nobody's `model_fields` and so lands
    # in `_unread` wherever it is written. Stamped 5 for the whole map — the
    # version that retired `shaped_by`, and the one `assigned_on` retires under
    # too. Splitting the loop to give each key a number of its own would buy
    # nothing anybody reads: a warning is what is yielded, grandfathering only
    # ever demotes, and there is no severity below a warning to demote one to.
    # The version is still carried, because what it says is which vocabulary a
    # Problem belongs to.
    for field, where in _RETIRED.items():
        if field in record._unread:
            yield "warning", field, f"{field} is no longer read: {where}", 5

    if record.id in parent_cycles:
        yield "blocker", "parent", "part of a parent cycle", 1
    elif record.kind == "task" and record.parent is None:
        yield "warning", "parent", "a task should have a parent", 1

    # Not while the chain is a loop: "part of a parent cycle" already says this
    # record's containment is broken, and adding that its parent is the wrong
    # kind is a second sentence about the same thing — in a set of records where
    # every one of them is going to say it.
    if record.id not in parent_cycles:
        yield from _containment_problems(record, by_id)
        yield from _bet_problems(record, by_id)
        yield from _rollup_problems(record, children, spans)

    if record.cycle is not None and record.cycle not in config.cycles:
        # `_overrun` looks the window up with `.get`, so a number nobody has dated
        # does not raise — it silently returns None and the record stops being
        # checked for overrun at all. A typo therefore reads as "on time" forever.
        yield (
            "warning",
            "cycle",
            f"cycle {record.cycle} has no dates in config/cycles.yaml, "
            "so this is not checked for overrun",
            3,
        )

    yield from _dependency_problems(record, by_id, parent_cycles, dep_cycles)
    for field, phrase in _PROMOTION_LINKS.items():
        for target in getattr(record, field, []):
            if target not in by_id:
                yield "warning", field, f"{phrase} {target}, which is missing", 1
    yield from _vocabulary_problems(record)
    # The reviewers of the work under this record count as its own. A pitch whose
    # tasks each name a reviewer is reviewed; asking it to name one as well is
    # asking for a second copy of a fact that is already a level below, and the
    # copy goes stale the first time a task changes hands.
    yield from _status_problems(
        record, list(dict.fromkeys([*record.reviewers, *reviewers_under(record.id, children)]))
    )
    # The drift half of `start_date_has_passed`; the door holds the other half.
    # A warning and not a blocker, and the difference is not severity for its own
    # sake: nobody did this. The date was in the future when it was typed and the
    # calendar moved under it, so there is no edit to refuse and no moment at
    # which anybody could have been told. What the reader gets instead is the
    # sentence the schedule is already acting on — `_place` discards the stated
    # date for the floor, and `_explain` says so on the record's own page.
    #
    # Stamped 5, the vocabulary this whole change belongs to, on the same
    # reasoning `_RETIRED` gives above: a warning is what is yielded,
    # grandfathering only ever demotes, and there is no severity below a warning
    # to demote one to. The version still says which vocabulary the Problem is
    # from.
    if start_date_has_passed(record, today):
        yield (
            "warning",
            "start_date",
            f"the start date {record.start_date} has passed and the work has not begun, "
            "so this is scheduled from today instead: move the date, or say the work "
            "has started",
            5,
        )
    yield from _people_problems(record, config)


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

    Nothing is copied into a *field*. The promoted record is created in `shaping`
    — not in `thinking`, which is where a record opens when nobody has looked at
    it, and somebody has just pressed Promote on this one. Both gates are empty,
    so "the status that requires nothing" no longer tells the two apart and the
    meaning does: a promotion always produces a record that validates, without
    inventing an owner, an appetite or a cycle that nobody agreed to. That is not
    a convenience; it is the same claim the note makes, carried across intact.

    `provenance` is one line of visible prose above everything, and it is the
    answer to "where did this pitch come from" asked of the record itself. Prose
    rather than a frontmatter field for two reasons: a field would put a note id
    inside `Record`, which drags notes into every view of the plan that is built
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


def named_for(record: Record) -> bool:
    """Whether the file this record was read from is named for the id it declares.

    Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    only the half before `--` is the fact; the rest is decoration and renaming it
    is legal.
    """
    stem = Path(record._source).name.removesuffix(".md")
    return stem == record.id or stem.startswith(f"{record.id}--")


def _identity_problems(records: list[Record]) -> Iterator[Problem]:
    """A record says who it is twice, and here the two are made to agree.

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
    for record in records:
        if record._source:
            claimants.setdefault(record.id, []).append(record._source)

    for record in records:
        if not record._source:
            continue
        if not named_for(record):
            yield Problem(
                severity="blocker",
                record_id=record.id,
                field="id",
                message=(
                    f"this record says it is {record.id} and its file is named "
                    f"{Path(record._source).name} — until they agree, a save can land "
                    "on the wrong file"
                ),
                rule_version=1,
            )
        others = [path for path in claimants[record.id] if path != record._source]
        if others:
            yield Problem(
                severity="blocker",
                record_id=record.id,
                field="id",
                message=(
                    f"{', '.join(sorted(others))} claims this id too, so which record "
                    "this is depends on which half of the app you ask"
                ),
                rule_version=1,
            )


def _parked(record: Record) -> bool:
    """Exempt from every rule: parked work is not broken work.

    Structural rather than the word `shelved`: every status ladder ends in its
    kind's terminal state — `STATUS_ORDER` and `ISSUE_STATUS` in `shelved`,
    `NOTE_STATUS` in `dropped` — so "the last word of this rung's own ladder" is
    the rule, and a rung added later is exempt in its own vocabulary with no
    edit here. A kind with no vocabulary is never parked: a product claiming
    `status: shelved` used to buy itself a silent skip with a word it does not
    even read, and now its written-but-unread status is reported instead.
    """
    statuses = RUNG[record.kind].statuses
    return bool(statuses) and record.status == statuses[-1]


def validate_all(
    records: list[Record],
    config: Config,
    spans: Mapping[str, Span] | None = None,
    today: date | None = None,
) -> list[Problem]:
    """Check every record against every rule it is old enough to be held to.

    Parked records — those at their own ladder's terminal status, see
    `_parked` — are exempt from all of them: parked work is not broken work,
    and a validator that nags about it teaches people to ignore the validator.

    `spans` is the scheduler's output, and the one rule that reads it —
    `_rollup_problems`, on whether a pitch's tasks fit in the calendar weeks its
    bet bought — is simply not applied without it. Optional rather than
    required, because the two kinds of caller want different answers. `Index.load`
    and `openproj check` are judging a whole plan and schedule it first, so they
    pass them. Every write path validates one candidate record against the
    records around it, before it is a file, to answer "may this be saved" — and
    a rollup is a fact about the plan the record is joining rather than about the
    record, so scheduling the whole corpus on each keystroke would buy an answer
    that is not to the question being asked.

    `today` is the day the plan is judged around, threaded the way `spans` is
    threaded and for the same reason: an index drawn around a pinned day — the
    demo corpus is written around one — must not be told a different day by a
    rule inside it. It defaults rather than switching its rule off, which is where
    it parts company with `spans`: what day it is always has an honest answer,
    where a schedule the caller did not run does not, and a date rule that goes
    quiet when nobody passes an argument is the "0 blockers, 0 warnings on a plan
    that answers 500" failure with a different cause.
    """
    today = today or date.today()
    by_id = {record.id: record for record in records}
    parent_cycles = _cyclic_members({e.id: [e.parent] if e.parent else [] for e in records})
    dep_cycles = _cyclic_members({e.id: list(e.depends_on) for e in records})
    children: dict[str, list[Record]] = {}
    for record in records:
        if record.parent in by_id and not _parked(record):
            children.setdefault(record.parent, []).append(record)

    problems: list[Problem] = []
    for record in records:
        if _parked(record):
            continue
        for severity, field, message, rule_version in _problems_for(
            record, config, by_id, children, parent_cycles, dep_cycles, spans, today
        ):
            grandfathered = rule_version > record.created_schema_version
            problems.append(
                Problem(
                    severity="warning" if grandfathered else severity,
                    record_id=record.id,
                    field=field,
                    message=message,
                    rule_version=rule_version,
                )
            )
    # Outside the loop above, and outside `_parked`'s exemption with it. Parked
    # work is not broken work — but a parked record can still be the one whose id
    # a second file has taken, and the save that lands on the wrong file does not
    # care that one of the two is parked.
    problems.extend(_identity_problems(records))
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


def patch_text(
    original: str, fields: dict, body: str | None = None, drop: Sequence[str] = ()
) -> str:
    """Apply only the named fields to a file, leaving everything else byte-identical.

    Round-trip, not re-serialise: a person's comments, key order, blank lines and
    list style survive a save. "Edit it in git if you prefer" stops being true the
    first time a save reformats somebody's file, and nobody comes back after that.

    `drop` REMOVES keys, which setting a field to `None` does not: `None` is a
    value, it round-trips as `field:` with nothing after it, and every reader
    then sees a field that is present and empty rather than one that is not
    there. The two are different to `validate_all` — a product carrying
    `status:` is a product that reads a field its rung does not have — and the
    one caller that needs the difference is changing a record's kind, where the
    fields the new rung does not read have to leave the file rather than sit in
    it blank.

    Silent about a key that is not there, because the caller computing which
    fields a rung does not read has no reason to know which of them this
    particular file happened to write down.
    """
    front, existing_body = split_front_matter(original)
    yaml = YAML()
    yaml.preserve_quotes = True
    mapping = yaml.load(front) or {}
    for key in drop:
        mapping.pop(key, None)
    for key, value in fields.items():
        mapping[key] = value
    stream = io.StringIO()
    yaml.dump(_readable_slide(mapping), stream)
    return f"---\n{stream.getvalue()}---\n{existing_body if body is None else body}"
