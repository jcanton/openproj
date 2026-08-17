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
from typing import Literal

import networkx as nx
from frontmatter.default_handlers import YAMLHandler
from pydantic import BaseModel, ValidationError, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml", "people.yaml")
_ENTITY_DIRS = ("projects", "pitches", "tasks")
_CYCLE_DIR = "cycles"

# Python's `date` spans years 1 to 9999 and every way of leaving that range
# raises instead of saturating, so this is the widest move any of the two
# functions below can be asked for.
CALENDAR_DAYS = (date.max - date.min).days


def within_the_calendar(days: float) -> float:
    """`days`, bounded by the length of the calendar so that rounding it cannot raise.

    `round()` and `math.ceil()` both raise on infinity, and a length in weeks is
    a float that a hand-edited file may write as `.inf` — `effort_weeks: .inf`
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


class Cycle(BaseModel):
    """One cycle, as the betting table sets it up.

    Stored as `cycles/<number>.md`, frontmatter and a body, so it reuses the whole
    existing write path — per-key frontmatter merge, three-way body merge, scoped
    compare-and-swap. The body is where the cycle's goal goes.

    Only `starts_on` is stored. An end date stored beside a length is a second
    copy of one fact, and the two disagree the first time somebody moves a date.
    """

    cycle: int
    starts_on: date
    build_weeks: float = 4.0
    cooldown_weeks: float = 2.0
    # Fraction of the BUILD weeks, per person. Absent means nobody said
    # otherwise, which is not the same as unavailable — see `_availability_of`.
    availability: dict[str, float] = {}
    body: str = ""

    def _last_day(self, weeks: float) -> date:
        """The inclusive last day of `weeks` weeks beginning at `starts_on`.

        Clamped, because these two properties are read while the config is being
        assembled — before any rule has looked at the record — so raising here is
        `openproj check`, `openproj render` and nine of the ten routes gone at
        once. `build_weeks: 500000` typed into the Cycles form did exactly that.
        The route refuses that number now; a file somebody edited in git never
        passed the route, and this is what keeps the site up for that one.
        """
        return days_after(self.starts_on, round(within_the_calendar(weeks * 7)) - 1)

    @property
    def builds_until(self) -> date:
        return self._last_day(self.build_weeks)

    @property
    def ends_on(self) -> date:
        return self._last_day(self.build_weeks + self.cooldown_weeks)

    def capacity(self, who: str, nominal: float = 1.0) -> float:
        """Weeks of work this person can hold in this cycle."""
        return self.availability.get(who, nominal) * self.build_weeks


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

    def with_plans(self, plans: list[Cycle]) -> Config:
        """A cycle record supersedes `config/cycles.yaml` for its own number.

        Both exist on purpose: the YAML is how the dates were kept before there
        were records, and a repository part-way through will have some of each.
        """
        windows = dict(self.cycles) | {c.cycle: (c.starts_on, c.ends_on) for c in plans}
        return self.model_copy(
            update={"cycles": windows, "plans": {c.cycle: c for c in plans}}
        )


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

    id: str
    kind: Literal["project", "pitch", "task"]
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

    @field_validator("status", "priority", mode="before")
    @classmethod
    def _as_written(cls, value: object) -> object:
        """Take whatever is in the file, verbatim, and let validate_all judge it.

        A file written before a vocabulary change holds `priority: 1`, which YAML
        gives us as an int. Refusing it here means the whole index fails to load
        over one stale record; accepting it means one problem next to one entity.
        """
        return value if value is None else str(value)


class Project(Entity):
    pass


class Pitch(Entity):
    appetite_weeks: float | None = None
    shaped_by: str | None = None


class Task(Entity):
    effort_weeks: float | None = None


_MODELS: dict[str, type[Entity]] = {"project": Project, "pitch": Pitch, "task": Task}
_ID_PREFIXES = {"proj": "project", "pitch": "pitch", "task": "task"}
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
    return model.model_validate({"id": "", "title": "", **fields, "kind": kind, "body": body})


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
    entities, unreadable = readable(
        [
            f"{directory}/{path.name}"
            for directory in _ENTITY_DIRS
            for path in sorted((root / directory).glob("*.md"))
        ],
        # Read here rather than through `parse_file`, so the name in the message
        # is the name in `Unreadable.path`. `parse_file` names its source by the
        # absolute path it was handed, and the banner prints the path beside the
        # reason — so the two disagreeing put `/private/var/…/tasks/x.md` after
        # `tasks/x.md` on one line, and the served pages and `openproj check`
        # would answer differently to somebody grepping a build log for a file.
        lambda relative: parse_text((root / relative).read_text(encoding="utf-8"), relative),
    )
    plans, unreadable_plans = readable(
        [f"{_CYCLE_DIR}/{path.name}" for path in sorted((root / _CYCLE_DIR).glob("*.md"))],
        lambda relative: parse_cycle_text(
            (root / relative).read_text(encoding="utf-8"), relative
        ),
    )
    config, unreadable_config = read_config(*_config_on_disk(root))
    return (
        entities,
        config.with_plans(plans),
        # Sorted by path, so the banner and `openproj check` list them in the
        # order somebody would open them rather than in the order three separate
        # walks happened to finish.
        sorted([*unreadable, *unreadable_plans, *unreadable_config], key=lambda one: one.path),
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

    A pitch's appetite and a task's effort are the same quantity to everything
    downstream, so they are read in one place; the scheduler and the index both
    call this rather than reaching for either field.
    """
    for field in ("appetite_weeks", "effort_weeks"):
        stated = getattr(entity, field, None)
        if stated is not None:
            return float(stated), False
    return config.default_task_effort, True


# --------------------------------------------------------------------------- #
# Validation
#
# Rules are data, not branches: each carries the schema_version that introduced
# it, which is what makes grandfathering possible. A rule newer than the entity
# it is judging may only warn. Adding a required field must never invalidate a
# corpus written before the field existed — otherwise the rule gets reverted
# rather than adopted.
# --------------------------------------------------------------------------- #

_ID_PATTERN = re.compile(r"^(proj|pitch|task)-[0-9a-f]{6}$")
_PREFIX_FOR_KIND = {"project": "proj", "pitch": "pitch", "task": "task"}
_SIZE_FIELD = {"pitch": "appetite_weeks", "task": "effort_weeks"}

# Statuses in the order work moves through them. `shaping` is an idea nobody has
# committed to yet, so it demands nothing — the same reason `shelved` does not.
# The gates are cumulative from `ready` onwards.
STATUS_ORDER = ("shaping", "ready", "in_progress", "done", "shelved")
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


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


def _status_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]:
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
    if entity.status in ("shaping", "shelved"):
        return
    if entity.status == "ready":
        if entity.owner is None:
            yield "blocker", "owner", "a ready entity needs an owner", 1
        if not (entity.review_waived or entity.reviewers):
            yield "blocker", "reviewers", "a ready entity needs a reviewer, or review waived", 1
        field = _SIZE_FIELD.get(entity.kind)
        if field is not None and getattr(entity, field) is None:
            # One word for both fields, because they are one quantity: a pitch
            # stores it as appetite_weeks and a task as effort_weeks, and the
            # reader is asked for an appetite either way.
            yield "blocker", field, f"a ready {entity.kind} needs an appetite", 1
        if entity.kind == "pitch" and entity.shaped_by is None:
            yield "blocker", "shaped_by", "a ready pitch needs to say who shaped it", 2
    elif entity.status == "in_progress":
        if entity.assigned_on is None:
            yield "blocker", "assigned_on", "work in progress needs the date it was assigned", 1
        if not entity.review_waived and not (set(entity.reviewers) - {entity.owner}):
            yield (
                "blocker",
                "reviewers",
                "work in progress needs a reviewer other than its owner, or review waived",
                1,
            )
    elif entity.status == "done" and not entity.prs:
        yield "blocker", "prs", "a done entity needs at least one PR", 1


def required_at() -> dict[str, tuple[str, ...]]:
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
    """
    gates: dict[str, list[str]] = {}
    for kind, model in (("project", Project), ("pitch", Pitch), ("task", Task)):
        for status in STATUS_ORDER:
            blank = model(id=f"{_PREFIX_FOR_KIND[kind]}-000000", kind=kind, title="", status=status)
            for _, field, _, _ in _status_problems(blank):
                if field and status not in gates.setdefault(field, []):
                    gates[field].append(status)
    return {field: tuple(statuses) for field, statuses in gates.items()}


def _vocabulary_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]:
    """A word nobody defined, named where it is rather than as a stack trace."""
    if entity.status not in STATUS_ORDER:
        yield (
            "blocker",
            "status",
            f"{entity.status!r} is not a status: expected one of {', '.join(STATUS_ORDER)}",
            1,
        )
    if entity.priority not in PRIORITY_RANK:
        yield (
            "blocker",
            "priority",
            f"{entity.priority!r} is not a priority: expected high, medium or low",
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


def _problems_for(
    entity: Entity,
    config: Config,
    by_id: dict[str, Entity],
    parent_cycles: set[str],
    dep_cycles: set[str],
) -> Iterator[tuple[str, str | None, str, int]]:
    """Yield (severity_before_grandfathering, field, message, rule_version)."""
    if not entity.title.strip():
        yield "blocker", "title", "title must not be empty", 1
    if not _ID_PATTERN.match(entity.id):
        yield "blocker", "id", "id must match ^(proj|pitch|task)-[0-9a-f]{6}$", 1
    elif not entity.id.startswith(_PREFIX_FOR_KIND[entity.kind] + "-"):
        yield "blocker", "id", f"id prefix must match kind {entity.kind}", 1

    if entity.id in parent_cycles:
        yield "blocker", "parent", "part of a parent cycle", 1
    elif entity.kind == "task" and entity.parent is None:
        yield "warning", "parent", "a task should have a parent", 1

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
    yield from _status_problems(entity)
    yield from _people_problems(entity, config)


def validate_all(entities: list[Entity], config: Config) -> list[Problem]:
    """Check every entity against every rule it is old enough to be held to.

    Shelved entities are exempt from all of them: parked work is not broken work,
    and a validator that nags about it teaches people to ignore the validator.
    """
    by_id = {entity.id: entity for entity in entities}
    parent_cycles = _cyclic_members({e.id: [e.parent] if e.parent else [] for e in entities})
    dep_cycles = _cyclic_members({e.id: list(e.depends_on) for e in entities})

    problems: list[Problem] = []
    for entity in entities:
        if entity.status == "shelved":
            continue
        for severity, field, message, rule_version in _problems_for(
            entity, config, by_id, parent_cycles, dep_cycles
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
    return problems


def split_front_matter(text: str) -> tuple[str, str]:
    """The frontmatter block and the body, without reformatting either."""
    if not text.startswith("---"):
        return "", text
    _, _, rest = text.partition("---\n")
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
