"""The single in-memory snapshot the table, the graph and the timeline render from.

Everything here is derived. `blocks` is the reverse of `depends_on` and is never
read from a file — a stored copy is stale by construction and lets one record
contradict the graph. Edges to entities that do not exist are dropped rather than
carried, so the forward and reverse maps always agree.

Filter state lives entirely in query parameters, so facet and filter values are
strings, and `apply_filters` returns ids sorted by id: a shared URL must render
the same twice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from pydantic import BaseModel, model_validator

from .model import (
    PRIORITY_RANK,
    RUNG,
    STATUS_ORDER,
    Config,
    Cycle,
    Entity,
    Problem,
    Unreadable,
    ancestors,
    checklist,
    cycle_of,
    sections,
    size_weeks,
    under,
    unread_fields,
    validate_all,
)
from .query import QueryError, evaluate, parse
from .schedule import Explanation, Span, schedule


def _people_on(entity: Entity) -> list[str]:
    """Everyone answerable for the work, each once. The same set the scheduler
    divides a size among, so the page and the timeline cannot disagree."""
    named = ([entity.owner] if entity.owner else []) + list(entity.assignees)
    return list(dict.fromkeys(named))

COMPUTED_PREDICATES = (
    "blocked",
    "unblocked",
    "overruns_cycle",
    # Any problem at all, of any severity. `has_blocker` is the strict half: the
    # table's headline counts blocking problems, and a link from that count to a
    # filter that also returns warnings sends people to rows there is nothing
    # wrong with — which is how a count stops being trusted.
    "missing_required_fields",
    "has_blocker",
    "review_waived",
    # Shape Up's circuit breaker, as a filter. Work still running past the end of
    # its cycle's build is the one list a betting table has to see, and it is
    # derived from dates the tool already has rather than from anything a person
    # remembers to set.
    "past_cycle_build",
    # In progress with nothing linked. Not a rule — opening a PR early to get CI
    # machine time is a good habit and a rule against it teaches people to stop
    # listing PRs — but it is a fair question to be able to ask of a whole cycle.
    "in_progress_without_prs",
    # Live work whose body keeps no checklist. A warning nobody has to act on —
    # the team's pitch template asks for one, and this is how you find the pitches
    # where nobody did. It is deliberately not a Problem: the body is prose.
    "untracked",
    "for_later",
)

_SCALAR_FACETS = ("kind", "status", "owner", "priority", "cycle")
_LIST_FACETS = ("assignees", "reviewers", "tags")
# The heading a deferred-scope list is written under, lowercased as `sections`
# returns it.
_FOR_LATER = "for later"


class Progress(BaseModel):
    """How far along one entity is, and what that was counted from.

    Two sources, never both. A pitch with tasks is as far along as its tasks are,
    weighted by their sizes — half a bet is half its weeks, not half its rows, and
    a four-week task beside a half-week one is not two equal halves of anything.
    A leaf counts the task list in its own body instead.

    Derived, never stored. Completion is `status: done` on a child, and a stored
    checkbox mirroring it is a second copy of one fact — stale the first time
    somebody closes a task from the table, for the same reason `blocks` is
    derived and not written.
    """

    done: float
    total: float
    # "weeks" when it came from child tasks, "items" from a body checklist.
    unit: str
    # The children it was counted from, in the order they are drawn. Empty for a
    # body checklist, whose items are in the body and stay there.
    of: list[str] = []

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0

    @property
    def text(self) -> str:
        """`3/4 items` or `0/0.5 wk` — the unit always, whichever it is.

        The weeks carried theirs and the items did not, so one column held `1/1`
        beside `0/1 wk` and the two looked like different measurements of the
        same thing rather than measurements of different things. jcanton,
        2026-08-20: "please make it consistent".

        Which unit it is stays visible rather than being unified away: half a bet
        is half its weeks and not half its rows — the whole argument in this
        class's docstring — so a rollup cannot be counted in items, and a
        checklist cannot honestly be converted into weeks.
        """
        return f"{self.done:g}/{self.total:g} {'wk' if self.unit == 'weeks' else 'items'}"


def _progress_of(
    entity: Entity, children: list[Entity], config: Config
) -> Progress | None:
    """A pitch's progress from its tasks, a leaf's from its own checklist."""
    if children:
        sized = [(kid, size_weeks(kid, config)[0]) for kid in children]
        return Progress(
            done=sum(size for kid, size in sized if kid.status == "done"),
            total=sum(size for _, size in sized),
            unit="weeks",
            of=[kid.id for kid, _ in sized],
        )
    ticked, items = checklist(entity.body)
    return Progress(done=ticked, total=items, unit="items") if items else None


class Index(BaseModel):
    # THE PLAN, and only the plan: kinds whose rung says `planned`. Narrowed on
    # purpose rather than superseded — every PM surface (table, graph, timeline,
    # people, scheduler, facets, /api/index.json) reads this field, so a consumer
    # nobody edits stays correct, and one that is forgotten fails closed: it sees
    # fewer records, never an unplanned one on the timeline.
    entities: dict[str, Entity]
    # Every record that parsed, whatever its kind. Reaching for this is a
    # deliberate act — the word looks wrong in a function about the timeline,
    # which is the point. The landing list, the detail lookup and the delete
    # cascade are its readers.
    #
    # Where the two inboxes went. `issues` and `notes` were separate maps here,
    # with a comment forbidding the rest of the index from reaching for them —
    # "a note that appears in a second view is a note that has become a bet
    # nobody made". That rule is now structural rather than admonitory: an
    # issue is an Entity on an unplanned rung, so it lives in `records`, is
    # filtered out of `entities` by the one comprehension in `build_index`,
    # and the model_validator below refuses any Index built otherwise. A PM
    # view that is forgotten reads `entities` and fails CLOSED — fewer
    # records, never more — where the old type boundary failed open the day
    # somebody passed the wrong dict. What survives of the admonition is one
    # word: reaching for `records` in a function about the plan is a
    # deliberate, greppable act, and the word looks wrong there on purpose.
    records: dict[str, Entity]
    children: dict[str, list[str]]
    blocked_by: dict[str, list[str]]
    blocks: dict[str, list[str]]
    spans: dict[str, Span]
    explanations: dict[str, Explanation]
    problems: list[Problem]
    # The plan files that are not records. Carried on the index rather than
    # handed to each renderer, because it is the answer to "is what I am looking
    # at the whole plan" and every page has to be able to say no.
    unreadable: list[Unreadable] = []
    facets: dict[str, list[str]]
    search_blob: dict[str, str]
    # Carried so a renderer needs nothing but the index: the timeline cannot draw
    # cycle boundaries or a today line without them, and it is handed no Config.
    cycles: dict[int, tuple[date, date]]
    plans: dict[int, Cycle]
    today: date
    default_task_effort: float
    nominal_availability: float = 1.0
    # Carried for the same reason the windows are: the timeline has to draw where
    # a cycle stops building, and it is handed no Config to ask.
    cooldown_weeks: float = 2.0
    # And the holidays, because a cycle's length is working days between two
    # meetings — the cycle page resolves an unsaved cycle through the same
    # `with_plans` a stored one goes through, and that needs them.
    holidays: list[date] = []
    # The roster from config/people.yaml, so a cycle nobody has been bet into yet
    # still has names to set availability against.
    known_people: list[str] = []
    # The icon each person picked for themselves, login to icon name, from
    # `people/<login>.md`. The choice and not the record: the one page that draws
    # these wants the mark beside a name, and an index carrying the whole record
    # would be carrying a body nothing reads. Keyed on every login that has a
    # record — not on the roster — because the People page is built from who is
    # named in the entity files, and a map keyed on the roster would draw nothing
    # for whoever was added to the plan this morning.
    icons: dict[str, str] = {}
    # How far along each entity is, counted once here rather than re-derived by
    # every column, panel and predicate that wants to say it. See `Progress`.
    progress: dict[str, Progress] = {}
    # Ids whose body keeps a "for later" list — deferred scope, which is the only
    # record the plan has of a bet being trimmed to fit.
    for_later: list[str] = []

    @model_validator(mode="after")
    def _the_plan_holds_only_planned_kinds(self) -> Index:
        """The guarantee the type system gave up when every kind became an Entity.

        `model.py` used to argue that an issue being a separate *type* is what
        kept it off the table by construction. This is that argument's
        replacement: one assertion at the single place an Index is made, instead
        of an exclusion in each of sixty read sites that somebody later forgets.
        """
        for entity in self.entities.values():
            if not RUNG[entity.kind].planned:
                raise ValueError(
                    f"{entity.id} is a {entity.kind}, and no {entity.kind} belongs in "
                    "the plan: .entities holds planned kinds only — put it in .records"
                )
        return self

    def counts_in(self, entity: Entity, cycle: int) -> bool:
        """Whether this entity's work lands inside this cycle's window.

        Bet into it, or **carried into it**: work bet in an earlier cycle and still
        running is doing so with this cycle's weeks. `cycle:` records where a bet
        was made and is never re-stamped (D-C1), which is what keeps an overrun
        accusing — but it also means a filter on `cycle == N` cannot see the
        carryover, and the page that exists to add up load was missing it.

        Carryover needs the cycle's dates to be answerable at all, so an undated
        cycle counts only what was bet into it by name: a number nobody has given
        a window to is a hypothetical, and letting it absorb every running item
        would put the whole plan's load on a page for a cycle that may never run.
        An entity with no span is the other way round — it is live work in a dated
        window, and silence about it is the failure this method exists to fix.

        Carryover is decided by the dates and not by the status. It asked for
        `in_progress`, which dropped a `ready` task sitting under a carried pitch
        even where its own span ran through the middle of this cycle — work
        somebody is about to do, in weeks this page is adding up, missing from the
        total. What has not started yet is still what a person's next weeks are
        spent on; whether it has begun is a different question from when it lands.
        """
        if entity.status in ("done", "shelved"):
            return False
        # The cycle of the BET this work is part of, which for a task under a
        # pitch is the pitch's. A task does not carry its own — the bet is made
        # once, on the thing the room named.
        mine = cycle_of(entity, self.entities)
        if mine == cycle:
            return True
        if mine is None or mine >= cycle:
            return False
        window = self.cycles.get(cycle)
        if window is None:
            return False
        span = self.spans.get(entity.id)
        return span is None or (span.start <= window[1] and span.end >= window[0])

    def build_end(self, cycle: int | None) -> date | None:
        """The last day of a cycle's build.

        From the record where there is one — `with_plans` fills `builds_until` in
        from the two meeting dates — and otherwise from the window less the
        cool-down. Asked through the index rather than by rebuilding a `Config`,
        which would substitute the default cool-down for the repository's own and
        leave a filter quietly disagreeing with the timeline it explains.
        """
        window = self.cycles.get(cycle) if cycle is not None else None
        if window is None:
            return None
        plan = self.plans.get(cycle)
        if plan is not None and plan.builds_until is not None:
            return plan.builds_until
        return window[1] - timedelta(days=round(self.cooldown_weeks * 7))

    def load(self, cycle: int) -> dict[str, float]:
        """Person-weeks each person is holding in this cycle.

        Charged where the assignees are, and split evenly among them (D-C4): a
        pitch whose children carry the names charges nothing itself, because its
        appetite is a rollup and charging both counts the same work twice.

        A carried item is charged its whole size, not the part of it that is left.
        Nothing in the plan records how much of a bet is done — the checklist in
        its body is a hint, not a measurement — and an invented percentage is a
        worse answer than a known overcount that a person can see and argue with.
        """
        held: dict[str, float] = {}
        for entity in self.entities.values():
            if not self.counts_in(entity, cycle):
                continue
            people = _people_on(entity)
            if not people or self.children.get(entity.id):
                continue
            size, _ = size_weeks(entity, Config(default_task_effort=self.default_task_effort))
            for who in people:
                held[who] = held.get(who, 0.0) + size / len(people)
        return held

    def carried_into(self, cycle: int) -> list[str]:
        """Ids counted against this cycle that were bet in an earlier one."""
        return sorted(
            entity.id
            for entity in self.entities.values()
            if cycle_of(entity, self.entities) != cycle and self.counts_in(entity, cycle)
        )


def _project_of(entity: Entity, by_id: dict[str, Entity]) -> str | None:
    """The project an entity belongs to, walking up the parent chain."""
    return _holder_of(entity, by_id, "project")


def _product_of(entity: Entity, by_id: dict[str, Entity]) -> str | None:
    """The product an entity belongs to. Same walk, one rung further up."""
    return _holder_of(entity, by_id, "product")


def _holder_of(entity: Entity, by_id: dict[str, Entity], kind: str) -> str | None:
    """The nearest ancestor of this kind, walking up the parent chain.

    A task names its pitch, never its project, so grouping by either is empty
    unless the chain is followed.

    One walk asked for a kind rather than one walk per kind: `product` was added
    above `project` and this was the function that would otherwise have been
    copied, with the copy free to disagree about what an unresolvable parent
    means.
    """
    if entity.kind == kind:
        return entity.id
    for ancestor in ancestors(entity.id, by_id):
        # `.get`, not `[]`. `ancestors` returns the chain as it is *named*, so its
        # last link can be an id no file was ever written for — and a dangling
        # parent is deliberately not a validation problem (see the `task()` helper
        # in test_validate), so a plan is allowed to contain one. Indexing it
        # raised KeyError out of `build_index`, which is the read path of `/`,
        # `/detail/<id>`, `/graph`, `/timeline`, `/people` and `/api/index.json`
        # alike: one committed `parent` field, sent by any signed-in member and
        # accepted with a 200, answered 500 to every reader on every page from
        # then on. Branch protection means that commit cannot be force-pushed
        # away, and the 500ing pages will not give you the sha to repair against.
        #
        # Unresolvable is answered the same way as no parent at all: no project.
        # Inventing one would put a node in the facet menu that the graph and the
        # table cannot agree exists, which is the failure the `blocked_by` edge
        # map already refuses next door.
        named = by_id.get(ancestor)
        if named is not None and named.kind == kind:
            return ancestor
    return None


# The one option in a facet menu that is not a value out of the data: it selects
# the entities where the field is empty.
#
# "Which pitches are not in a cycle yet" and "what has no reviewer" are the two
# questions a betting table actually asks, and neither could be asked at all —
# an unset field produces no facet value, so it could never be selected, and the
# blank option at the top of every menu means "no constraint" rather than
# "empty". Spelled in brackets, because a facet value is a login, a tag, a cycle
# number or a status, and none of those is ever written like this.
NO_VALUE = "(none)"

# What the search box searches, in one place, for both halves of the app.
#
# It used to be two definitions: this file swept title, tags, PR references *and
# the whole shaping document* into one blob, while the browser searched
# `row.title + ' ' + row.tags`. A word in a body found rows through a pasted link
# and nothing in the box in front of you; `#1364` found the entity on the server
# and nothing in the table — and neither side erred, which is the shape of every
# divergence this repository has shipped. The blob is built here now and travels
# on the row (`_row` in `render.py`), so the browser searches the string the
# server searched rather than a second idea of what a record says.
#
# **Fields, not bodies** — jcanton, 2026-08-19. The shaping document IS the
# record, but it is not the record's index: a 900-word pitch in a substring
# search makes every long word in the plan a match for something, and the reader
# cannot see why a row was kept. The document is read on the detail page, which
# is where a document is read.
#
# These seven and not every field: they are what a person names a record BY — its
# id, what it is called, the labels somebody put on it, the pull requests it is
# argued in, and the people whose names are on it. `status`, `kind`, `priority`
# and `cycle` are deliberately absent: each has a dropdown that says which values
# exist, and sweeping them in means typing `ready` matches half the plan through
# a box that cannot say which field it matched.
SEARCH_FIELDS = ("id", "title", "tags", "prs", "owner", "assignees", "reviewers")


def searchable(entity: Entity) -> str:
    """One record's searchable text: every value in `SEARCH_FIELDS`, lowered.

    Lowered here rather than at each comparison, because the browser holds this
    string and compares a lowered needle against it; a second `.toLowerCase()`
    per row per keystroke is the same answer computed fifteen thousand times.
    """
    said: list[str] = []
    for field in SEARCH_FIELDS:
        value = getattr(entity, field, None)
        said += value if isinstance(value, list) else [value] if value else []
    return " ".join(said).lower()


def _ordered(field: str, values: set[str]) -> list[str]:
    """Alphabetical, except where the values are a sequence rather than a set.

    Sorting a status alphabetically puts `done` at the top of the menu and
    `shaping` second from the bottom — the exact reverse of the order work moves
    in, for the first four of five. Priority reads `high, low, medium`, which is
    not an order anybody means by priority.
    """
    # `(none)` first wherever it appears, because it is not one of the values —
    # it is the question "which of these has nobody in it", and sorted with the
    # rest it lands under the bracket's ASCII position, above every login, where
    # it reads as somebody's name.
    rest = values - {NO_VALUE}
    head = [NO_VALUE] if NO_VALUE in values else []
    ranked = {"status": STATUS_ORDER, "priority": tuple(PRIORITY_RANK)}.get(field)
    if ranked is None:
        return head + sorted(rest)
    known = [v for v in ranked if v in rest]
    return head + known + sorted(v for v in rest if v not in ranked)


# The facets that are not a field on the record but an ancestor of it: a task
# names its pitch and nothing else, so "which project" and "which product" are
# both answers to a walk up the chain. Written once because three call sites ask
# the same question — `build_index`, `query_fields` and `matching` — and a list
# that grew a rung in two of them would offer a menu that filters nothing.
_HOLDER_FACETS = ("product", "project")


def _facet_values(entity: Entity, field: str, by_id: dict[str, Entity]) -> list[str]:
    """Every value of `field` on this entity, as strings. Absent values yield none.

    An unset field is not a facet value: emptiness is selected with `NO_VALUE`,
    which is a menu option rather than a fake owner named "unowned".
    """
    if field in _HOLDER_FACETS:
        holder = _holder_of(entity, by_id, field)
        return [holder] if holder else []
    # A field this rung does not read has no value to offer, whatever the model
    # defaults it to. `status` defaults to `shaping` on every entity, so without
    # this a product — which has no status at all — answered the Status menu as
    # if somebody had shaped it, and filtering to `shaping` brought back a
    # codebase.
    if field in unread_fields(entity.kind):
        return []
    value = getattr(entity, field, None)
    if isinstance(value, list):
        return [str(item) for item in value]
    return [] if value is None else [str(value)]


def build_index(
    entities: list[Entity],
    config: Config,
    today: date,
    unreadable: Iterable[Unreadable] = (),
) -> Index:
    records = {entity.id: entity for entity in entities}
    # THE INVERSION (spec §2). Filtered here, once, and nowhere else: the plan
    # keeps the old name so its sixty-odd consumers need no edit, and the
    # superset takes the new one so reading it is visible in review.
    plan = {eid: entity for eid, entity in records.items() if RUNG[entity.kind].planned}
    children: dict[str, list[str]] = {entity_id: [] for entity_id in records}
    blocked_by: dict[str, list[str]] = {}
    # Total over records, not over the plan: the record page draws fact rows for
    # every kind, and a map missing a key there is a KeyError on a page, not a
    # smaller answer.
    blocks: dict[str, list[str]] = {entity_id: [] for entity_id in records}

    for entity in entities:
        if entity.parent in children:
            children[entity.parent].append(entity.id)
        blocked_by[entity.id] = [target for target in entity.depends_on if target in records]
        for target in blocked_by[entity.id]:
            blocks[target].append(entity.id)

    spans, explanations = schedule(entities, config, today)

    facets: dict[str, set[str]] = defaultdict(set)
    search_blob: dict[str, str] = {}
    progress: dict[str, Progress] = {}
    for_later: list[str] = []
    # The blob is total: the landing list searches every record, and a record
    # missing from it is one its own page cannot find. PR references included —
    # "which entity is #1364?" is asked in front of a screen, and the answer was
    # only findable if the number also appeared in the prose. What goes in is
    # `SEARCH_FIELDS`, which is also what a row carries to the browser.
    for entity in records.values():
        search_blob[entity.id] = searchable(entity)
    # Facets, progress and deferred scope are PLAN facts: an unplanned kind in a
    # facet menu is a dead option on the table.
    for entity in plan.values():
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS):
            values = _facet_values(entity, field, records)
            # `NO_VALUE` is offered only where something is actually missing, so
            # a menu never carries an option that can select nothing. Every
            # status has a value, so Status never grows one; Cycle grows one the
            # moment a pitch is written and not yet bet.
            facets[field].update(values or [NO_VALUE])
        # A shelved child is not work anybody is waiting for, so it counts in
        # neither half of the fraction — otherwise parking a task makes a pitch
        # look less finished than it was the day before. Looked up in `plan`,
        # not `records`: an unplanned record with a hand-written `parent` is
        # already a containment problem, and counting it into a pitch's progress
        # would let the bad file move a number on the table.
        kids = [plan[k] for k in children[entity.id] if k in plan and plan[k].status != "shelved"]
        counted = _progress_of(entity, kids, config)
        if counted is not None:
            progress[entity.id] = counted
        if sections(entity.body).get(_FOR_LATER):
            for_later.append(entity.id)

    return Index(
        entities=plan,
        records=records,
        children=children,
        blocked_by=blocked_by,
        blocks=blocks,
        spans=spans,
        explanations=explanations,
        problems=validate_all(entities, config),
        unreadable=list(unreadable),
        facets={field: _ordered(field, values) for field, values in facets.items()}
        | {"predicate": sorted(COMPUTED_PREDICATES)},
        search_blob=search_blob,
        cycles=config.cycles,
        plans=config.plans,
        nominal_availability=config.nominal_availability,
        cooldown_weeks=config.cooldown_weeks,
        known_people=config.known_people,
        icons={
            login: person.icon for login, person in config.people.items() if person.icon
        },
        today=today,
        default_task_effort=config.default_task_effort,
        holidays=config.holidays,
        progress=progress,
        for_later=for_later,
    )


def _is_blocked(index: Index, entity_id: str) -> bool:
    """Blocked means waiting on work that is not over.

    Reading a non-empty `depends_on` as "blocked" would park a live task behind
    something finished months ago. The blocker is looked up in `records`:
    `blocked_by` is total over records, so its targets are there by
    construction, and a hand-written edge to an unplanned kind must not 500 the
    page that draws it.
    """
    return any(
        index.records[blocker].status not in ("done", "shelved")
        for blocker in index.blocked_by[entity_id]
    )


# Looked up in `records`, never `entities`: predicates run over whichever
# population `apply_filters` was handed, and the landing search hands it the
# whole one. `entities` ⊂ `records`, so the total map is always the safe door.
def _matches_predicate(index: Index, entity_id: str, predicate: str) -> bool:
    if predicate == "blocked":
        return _is_blocked(index, entity_id)
    if predicate == "unblocked":
        return not _is_blocked(index, entity_id)
    if predicate == "overruns_cycle":
        span = index.spans.get(entity_id)
        return span is not None and span.overruns_cycle_weeks is not None
    if predicate == "missing_required_fields":
        return any(problem.entity_id == entity_id for problem in index.problems)
    if predicate == "has_blocker":
        return any(
            problem.entity_id == entity_id and problem.severity == "blocker"
            for problem in index.problems
        )
    if predicate == "review_waived":
        return index.records[entity_id].review_waived
    if predicate == "past_cycle_build":
        entity = index.records[entity_id]
        span = index.spans.get(entity_id)
        window = index.cycles.get(entity.cycle) if entity.cycle is not None else None
        if entity.status != "in_progress" or span is None or window is None:
            return False
        return span.end > index.build_end(entity.cycle)
    if predicate == "in_progress_without_prs":
        entity = index.records[entity_id]
        return entity.status == "in_progress" and not entity.prs
    if predicate == "untracked":
        # Live work that says nothing about how far along it is: no tasks under
        # it and no checklist in it. A pitch with tasks is tracked by them.
        return (
            index.records[entity_id].status in ("ready", "in_progress")
            and entity_id not in index.progress
        )
    if predicate == "for_later":
        return entity_id in index.for_later
    return False


def query_fields(index: Index, entity_id: str) -> dict[str, list[str]]:
    """One record's values per field, lowered — what `query.evaluate` asks about.

    The browser builds the same map out of the row it was shipped (`queryFields`
    in `_FILTER_JS`), so the two parsers are handed identical data and a
    disagreement between them is the language rather than the plan.
    """
    entity = index.records[entity_id]
    fields = {
        field: [value.lower() for value in _facet_values(entity, field, index.records)]
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS)
    }
    fields["id"] = [entity.id.lower()]
    fields["title"] = [entity.title.lower()]
    fields["prs"] = [pr.lower() for pr in entity.prs]
    fields["predicate"] = [
        name for name in COMPUTED_PREDICATES if _matches_predicate(index, entity_id, name)
    ]
    return fields


def cascade_of(index: Index, entity_id: str) -> tuple[list[str], list[str]]:
    """What deleting this record takes with it: (also deleted, edited).

    Two different consequences, and conflating them would be the destructive
    mistake. A record filed UNDER this one has nowhere to be once it is gone, so
    it goes too — the whole subtree, however deep. A record that DEPENDS on this
    one is unrelated work that merely waits for it: deleting that would be a
    two-click gesture reaching across the plan into somebody else's task. It
    keeps its file and loses the dependency.

    Shelved work is in both lists. It is parked, not exempt: a shelved task under
    a deleted pitch is orphaned exactly as much as a ready one.

    Computed here rather than in the handler because the page has to show the same
    two lists before anybody presses anything, and a confirmation built from a
    second derivation of this is a confirmation that can be wrong.
    """
    doomed = under(entity_id, index.children)
    going = {entity_id, *doomed}
    edited = sorted(
        other
        for other, entity in index.records.items()
        if other not in going and going.intersection(entity.depends_on)
    )
    return sorted(doomed), edited


def apply_filters(
    index: Index,
    filters: dict[str, list[str]],
    query: str,
    over: dict[str, Entity] | None = None,
) -> list[str]:
    """AND across fields, OR within a field, then the query language.

    `over` picks the population and defaults to the plan: every caller that
    existed before the landing page is a PM surface, so a caller that forgets
    to ask for more fails closed. The landing list passes `index.records`.

    An unknown field or predicate matches nothing rather than everything: filter
    state comes from a hand-editable query string, and a typo that silently widens
    the result set is worse than one that visibly empties it.

    A query that cannot be read matches nothing, for the same reason and one
    more: half a query is a query somebody is still typing, and a table that
    widens to everything on the way to `kind:task and (` flickers through the
    whole plan at every keystroke. The sentence is not shown from here — this
    function answers with rows — so the caller that has a reader in front of it
    asks `parse` itself. See `render.py`'s `queryError`.
    """
    try:
        asked = parse(query)
    except QueryError:
        return []
    matched = []
    for entity_id, entity in (index.entities if over is None else over).items():
        fields = query_fields(index, entity_id)
        if not evaluate(asked, fields, index.search_blob[entity_id], NO_VALUE):
            continue
        for field, wanted in filters.items():
            if not wanted:
                continue
            if field == "predicate":
                found = any(_matches_predicate(index, entity_id, value) for value in wanted)
            elif field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS):
                # Empty is selectable, and it is the absence of every value
                # rather than one more of them — so it is asked of the list
                # itself, not looked up in it. Resolved against `records`, like
                # the menu these values came from and `query_fields` four lines
                # up — the holder walk starts at the entity itself, so a plan
                # lookup answers None for any record the plan does not hold.
                values = _facet_values(entity, field, index.records)
                found = bool(set(values) & set(wanted)) or (NO_VALUE in wanted and not values)
            else:
                found = False
            if not found:
                break
        else:
            matched.append(entity_id)
    return sorted(matched)
