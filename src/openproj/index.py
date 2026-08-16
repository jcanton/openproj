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
from datetime import date

from pydantic import BaseModel

from .model import (
    PRIORITY_RANK,
    STATUS_ORDER,
    Config,
    Cycle,
    Entity,
    Problem,
    Unreadable,
    ancestors,
    checklist,
    sections,
    size_weeks,
    validate_all,
)
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


class Index(BaseModel):
    entities: dict[str, Entity]
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
    # The roster from config/people.yaml, so a cycle nobody has been bet into yet
    # still has names to set availability against.
    known_people: list[str] = []
    # Ticked and total task-list items in each body, counted once here rather than
    # re-scanned by every column, predicate and page that wants to say "7/12".
    progress: dict[str, tuple[int, int]] = {}
    # Ids whose body keeps a "for later" list — deferred scope, which is the only
    # record the plan has of a bet being trimmed to fit.
    for_later: list[str] = []

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
        """
        if entity.status in ("done", "shelved"):
            return False
        if entity.cycle == cycle:
            return True
        if entity.status != "in_progress" or entity.cycle is None or entity.cycle >= cycle:
            return False
        window = self.cycles.get(cycle)
        if window is None:
            return False
        span = self.spans.get(entity.id)
        return span is None or (span.start <= window[1] and span.end >= window[0])

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
            if entity.cycle != cycle and self.counts_in(entity, cycle)
        )


def _project_of(entity: Entity, by_id: dict[str, Entity]) -> str | None:
    """The project an entity belongs to, walking up the parent chain.

    A task names its pitch, never its project, so grouping by project is empty
    unless the chain is followed.
    """
    if entity.kind == "project":
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
        if named is not None and named.kind == "project":
            return ancestor
    return None


def _ordered(field: str, values: set[str]) -> list[str]:
    """Alphabetical, except where the values are a sequence rather than a set.

    Sorting a status alphabetically puts `done` at the top of the menu and
    `shaping` second from the bottom — the exact reverse of the order work moves
    in, for the first four of five. Priority reads `high, low, medium`, which is
    not an order anybody means by priority.
    """
    ranked = {"status": STATUS_ORDER, "priority": tuple(PRIORITY_RANK)}.get(field)
    if ranked is None:
        return sorted(values)
    known = [v for v in ranked if v in values]
    return known + sorted(v for v in values if v not in ranked)


def _facet_values(entity: Entity, field: str, by_id: dict[str, Entity]) -> list[str]:
    """Every value of `field` on this entity, as strings. Absent values yield none.

    An unset field is not a facet value: "unowned" is a question for the predicate
    list, not a fake owner name in the menu.
    """
    if field == "project":
        project = _project_of(entity, by_id)
        return [project] if project else []
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
    by_id = {entity.id: entity for entity in entities}
    children: dict[str, list[str]] = {entity_id: [] for entity_id in by_id}
    blocked_by: dict[str, list[str]] = {}
    blocks: dict[str, list[str]] = {entity_id: [] for entity_id in by_id}

    for entity in entities:
        if entity.parent in children:
            children[entity.parent].append(entity.id)
        blocked_by[entity.id] = [target for target in entity.depends_on if target in by_id]
        for target in blocked_by[entity.id]:
            blocks[target].append(entity.id)

    spans, explanations = schedule(entities, config, today)

    facets: dict[str, set[str]] = defaultdict(set)
    search_blob: dict[str, str] = {}
    progress: dict[str, tuple[int, int]] = {}
    for_later: list[str] = []
    for entity in entities:
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, "project"):
            facets[field].update(_facet_values(entity, field, by_id))
        search_blob[entity.id] = " ".join(
            [entity.title, *entity.tags, entity.body]
        ).lower()
        ticked, total = checklist(entity.body)
        if total:
            progress[entity.id] = (ticked, total)
        if sections(entity.body).get(_FOR_LATER):
            for_later.append(entity.id)

    return Index(
        entities=by_id,
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
        known_people=config.known_people,
        today=today,
        default_task_effort=config.default_task_effort,
        cooldown_weeks=config.cooldown_weeks,
        progress=progress,
        for_later=for_later,
    )


def _is_blocked(index: Index, entity_id: str) -> bool:
    """Blocked means waiting on work that is not over.

    Reading a non-empty `depends_on` as "blocked" would park a live task behind
    something finished months ago.
    """
    return any(
        index.entities[blocker].status not in ("done", "shelved")
        for blocker in index.blocked_by[entity_id]
    )


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
        return index.entities[entity_id].review_waived
    if predicate == "untracked":
        return (
            index.entities[entity_id].status in ("ready", "in_progress")
            and entity_id not in index.progress
        )
    if predicate == "for_later":
        return entity_id in index.for_later
    return False


def apply_filters(index: Index, filters: dict[str, list[str]], query: str) -> list[str]:
    """AND across fields, OR within a field, then a substring search.

    An unknown field or predicate matches nothing rather than everything: filter
    state comes from a hand-editable query string, and a typo that silently widens
    the result set is worse than one that visibly empties it.
    """
    needle = query.strip().lower()
    matched = []
    for entity_id, entity in index.entities.items():
        if needle and needle not in index.search_blob[entity_id]:
            continue
        for field, wanted in filters.items():
            if not wanted:
                continue
            if field == "predicate":
                found = any(_matches_predicate(index, entity_id, value) for value in wanted)
            elif field in (*_SCALAR_FACETS, *_LIST_FACETS, "project"):
                found = bool(set(_facet_values(entity, field, index.entities)) & set(wanted))
            else:
                found = False
            if not found:
                break
        else:
            matched.append(entity_id)
    return sorted(matched)
