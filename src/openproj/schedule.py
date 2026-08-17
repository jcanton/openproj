"""Derive a timeline from sizes, dependencies and assignment dates.

Nobody types a start or an end date. A `Span` is inclusive — `end` is the last
working day the item occupies — so anything following it starts on the next
working day, never the same one.

Two invariants earn their own tests because breaking either produces a schedule
that looks plausible and is wrong:

* A size is PERSON-weeks, and the people on it divide it — each at their own
  availability. Three names on a six-week bet is two elapsed weeks, and one
  person at 60% takes a three-week bet five weeks. (D-C4, 2026-08-16. This
  reverses D1, which said a size was already elapsed weeks and must never be
  divided; D1 was wrong about how the team estimates, and with a single assignee
  at full availability the two readings agree, which is why it went unnoticed.)
* Only leaves consume a worker's capacity. A parent's span is a rollup of work its
  children already booked; booking the parent too double-books its owner.

The scheduler never raises. A cycle, a contradictory record or a cycle number
nobody has dated costs you those entities, never the whole page.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import networkx as nx
from pydantic import BaseModel

from .model import (
    PRIORITY_RANK,
    Config,
    Entity,
    ancestors,
    cycle_of,
    days_after,
    size_weeks,
    within_the_calendar,
)

_WORKING_DAYS_PER_WEEK = 5


class Span(BaseModel):
    start: date
    end: date
    estimated: bool = False
    unowned: bool = False
    historical: bool = False
    unscheduled: bool = False
    overruns_cycle_weeks: float | None = None


class Explanation(BaseModel):
    entity_id: str
    text: str
    blocker_id: str | None = None
    worker_busy_until: date | None = None


def _is_working_day(day: date, config: Config) -> bool:
    return day.weekday() < 5 and day not in config.holidays


def _next_working_day(day: date, config: Config) -> date:
    """The first working day after `day`, or the end of the calendar if there is none.

    This walk and `_first_working_day`'s stop at `date.max` rather than stepping
    past it. `_place` calls this on a blocker's last day, and a `done` entity
    carries whatever `assigned_on` says — so `assigned_on: 9999-12-31`, typed
    into the detail page, walked one day off the end of the calendar and
    answered 500 on every page that reads the index. Saturating is the same
    answer `working_days_after` already gives, and `_place` asks about the
    calendar before it uses either.
    """
    day = days_after(day, 1)
    while day < date.max and not _is_working_day(day, config):
        day = days_after(day, 1)
    return day


def _first_working_day(day: date, config: Config) -> date:
    while day < date.max and not _is_working_day(day, config):
        day = days_after(day, 1)
    return day


def _working_days(weeks: float) -> int:
    """Whole working days in `weeks`.

    Rounded to six decimals first: 1.2 * 5 is 6.000000000000001 in binary
    floating point, and a naive ceil would buy a seventh day. Bounded before the
    ceil, because `math.ceil` raises on infinity: `person_weeks: Infinity` is
    valid JSON to Python's parser and one PATCH away, and it raised here —
    inside `_runs_past_the_calendar`, so the guard was the thing that fell over
    and every page 500'd on a value already committed.
    """
    return max(1, math.ceil(within_the_calendar(round(weeks * _WORKING_DAYS_PER_WEEK, 6))))


def _runs_past_the_calendar(start: date, weeks: float, config: Config) -> bool:
    """Whether `weeks` of work beginning at `start` outruns the end of `date`.

    `person_weeks: 1000000` is one PATCH away and no rule refuses it. The day
    walk below used to keep adding days until `timedelta` went past year 9999
    and raised OverflowError — out of `build_index`, so `/`, `/graph`,
    `/timeline`, `/people` and `/api/index.json` all answered 500 to every
    reader, off a value already committed to a branch whose protection means the
    commit cannot be force-pushed away. The five million iterations before the
    raise are the other half of it, so the question is asked before the walk
    rather than answered by catching what the walk throws.

    Each working day costs one calendar day, plus at most two more for a
    weekend, plus one for each configured holiday it steps over — and a walk
    that only moves forward steps over each holiday at most once. So
    `3 * days + len(holidays)` is a ceiling on the calendar days consumed,
    including the roll-forward in `_first_working_day`. Against the ~2.9 million
    days between now and `date.max`, nothing anybody plans comes near it.
    """
    return 3 * _working_days(weeks) + len(config.holidays) > (date.max - start).days


def working_days_after(start: date, weeks: float, config: Config) -> date:
    """The inclusive last day of `weeks` working weeks beginning at `start`.

    The end of the calendar when the work does not fit inside it: this is the
    primitive, and a primitive that raises is a 500 on every page. The scheduler
    asks `_runs_past_the_calendar` first and leaves such an entity unscheduled,
    which is the answer a reader can actually use.
    """
    if _runs_past_the_calendar(start, weeks, config):
        return date.max
    day = _first_working_day(start, config)
    for _ in range(_working_days(weeks) - 1):
        day = _next_working_day(day, config)
    return day


def _duration_weeks(
    entity: Entity, config: Config, by_id: dict[str, Entity]
) -> tuple[float, bool]:
    """Elapsed weeks, and whether the size was defaulted rather than stated.

    A size is PERSON-weeks — the work one person would need — so the people on it
    divide it, each at their own availability (D-C4, 2026-08-16; this supersedes
    D1, which said the opposite and was wrong about how the team estimates).

    Two consequences worth stating, because both reverse earlier behaviour:
    staffing a bet with three people makes it finish sooner, which is what the
    room believes when it puts three names on one; and one person at 60% takes a
    three-week bet five weeks, which is the right answer rather than the bug the
    old spec calls out — that draft was only wrong under D1's reading.

    Nobody assigned is one notional person at nominal availability. Zero would be
    a division by zero, and infinity is not a useful forecast for unowned work.
    """
    size, defaulted = size_weeks(entity, config)
    rates = [_availability_of(who, entity, config, by_id) for who in _workers(entity)]
    return size / (sum(rates) or config.nominal_availability or 1.0), defaulted


def _availability_of(
    who: str, entity: Entity, config: Config, by_id: dict[str, Entity]
) -> float:
    """One person's rate in the cycle this entity was bet into.

    Read from the entity's own cycle rather than passed in, so there is one
    source: a global override and a per-cycle record would disagree the first
    time somebody set both.

    Being on a cycle's roster is what being in that cycle means, so somebody bet
    into a cycle they are not on is a planning mistake — but it is not one the
    scheduler can fix by refusing to produce a date. It uses the nominal rate and
    the cycle page names them, which is where a person can act on it. A rate of
    zero reads the same way rather than as a bet nobody can ever finish.
    """
    # The cycle of the BET, so a task reads the rates of the cycle its pitch was
    # bet into. A task carries no cycle of its own any more, and falling back to
    # nominal here would have quietly undone every per-person rate on the page.
    number = cycle_of(entity, by_id)
    plan = config.plans.get(number) if number is not None else None
    stated = plan.availability.get(who) if plan else None
    return stated if stated else config.nominal_availability or 1.0


def _workers(entity: Entity) -> list[str]:
    """Everyone on the hook, each counted once.

    An owner who is also an assignee — which is most of them — was counted twice,
    so they were booked twice and, now that the workers divide the size, would
    have halved it on their own.
    """
    named = ([entity.owner] if entity.owner else []) + list(entity.assignees)
    return list(dict.fromkeys(named))


def _overrun(
    entity: Entity, end: date, config: Config, by_id: dict[str, Entity]
) -> float | None:
    """Weeks past the end of the BUILD of the cycle this was bet into, or None.

    Cool-down is not build time — Shape Up's whole point is that work lands
    inside the build weeks and the cool-down is for the mess afterwards. Measured
    against the end of the window instead, every overrun was understated by the
    cool-down length and some were hidden completely.

    The cycle is the one the BET was made in, which for a task under a pitch is
    the pitch's. A project is measured against nothing: it holds bets rather than
    being one, and its span is the rollup of pitches bet in different cycles — so
    judging it against any single cycle produced the demo's `warm_bubble`,
    "overruns cycle 36 by 17 weeks", a milestone accused of missing a box nobody
    ever put it in.

    A cycle nobody has dated yet is not an overrun. Indexing `config.cycles`
    directly would turn one unconfigured number into a KeyError for every span.
    """
    number = cycle_of(entity, by_id)
    window = config.cycles.get(number) if number is not None else None
    if window is None:
        return None
    builds_until = build_end(number, window, config)
    if end <= builds_until:
        return None
    return (end - builds_until).days / 7


def build_end(number: int | None, window: tuple[date, date], config: Config) -> date:
    """The last day of a cycle's build.

    From the cycle's own record where there is one, and otherwise from the global
    cool-down applied to the end of the window.
    """
    plan = config.plans.get(number) if number is not None else None
    ends = (
        plan.builds_until
        if plan is not None
        # Backwards through `days_after` for the same reason as everything else:
        # a cool-down of `.inf` weeks in one config file is `round()` raising,
        # and one absurd number in `defaults.yaml` is not worth every page.
        else days_after(window[1], -(config.cooldown_weeks * 7))
    )
    # A cool-down longer than the window would put the end of build before the
    # cycle began, and then every entity in it overruns by definition. Clamped
    # rather than rejected: a bad number in one config file should cost that
    # cycle's flag, not every date on the page.
    return max(ends, window[0])


def blockers_of(entity: Entity, by_id: dict[str, Entity]) -> list[str]:
    """What this entity waits for: its own blockers, and its ancestors'.

    A dependency is written at the level people think at. "The land port waits
    for turbulence" is a sentence about two pitches, and it was decoration: only
    a leaf is placed against its blockers, while a parent's span is the rollup of
    children who had never heard of the edge. The demo shipped with it — land
    starting a month before the turbulence it declared it waited for, marked
    `blocked` in the table and drawn concurrent on the timeline, the two views
    disagreeing about the same record.

    So a bet's blockers are its tasks' blockers. Inherited rather than copied: the
    edge stays written once, on the entity somebody wrote it on, and `blocks`
    keeps meaning what it says on the page.

    Order is the chain's, nearest first, deduplicated — it decides only which
    blocker gets named in the explanation when two end on the same day.
    """
    waits = list(entity.depends_on)
    for ancestor in ancestors(entity.id, by_id):
        # `.get`, not `[]`. `ancestors` returns the chain as it is *named*, so its
        # last link can be an id no file was written for — a dangling parent is
        # deliberately legal — and the map handed in here is the *live* one, so a
        # `done` or `shelved` ancestor is absent from it too. Neither is a reason
        # to raise out of the scheduler: an ancestor nobody can read waits for
        # nothing, and a finished one is not waiting for anything either.
        above = by_id.get(ancestor)
        if above is not None:
            waits += above.depends_on
    return list(dict.fromkeys(waits))


def _ordering(
    active: dict[str, Entity], config: Config
) -> tuple[list[str], set[str]]:
    """Visit order: blockers before dependents, children before parents.

    Containment is not a dependency, so a topological sort over `depends_on`
    alone would visit a parent before the children its span is built from. The
    two edge kinds can also disagree — an entity depending on its own ancestor
    contributes a dependency edge one way and a containment edge the other — and
    that record is dropped rather than allowed to raise.

    Inherited edges are in here as well as in `_place`. A task placed against its
    pitch's blocker has to be visited after that blocker has a span, and the raw
    dependency edge only orders the pitch — which is placed *after* the task,
    being a rollup of it.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(active)
    for entity in active.values():
        for blocker in blockers_of(entity, active):
            if blocker in active:
                graph.add_edge(blocker, entity.id)

    contradictory: set[str] = set()
    for entity in active.values():
        if entity.parent not in active:
            continue
        if nx.has_path(graph, entity.parent, entity.id):
            contradictory |= {entity.id, entity.parent}
            continue
        graph.add_edge(entity.id, entity.parent)

    graph.remove_nodes_from(contradictory)
    # Inheritance can close a loop that neither edge kind closes on its own: a
    # pitch waiting on another whose task waits on one of this pitch's. Both
    # records are legal on their own and `_unschedulable` cannot see it, because
    # it reads the written edges. Caught here as the sort's own precondition
    # rather than by letting `lexicographical_topological_sort` raise — one
    # contradictory pair must cost those entities, never every date on the page.
    looping = {
        node
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for node in component
    } | {node for node in graph if graph.has_edge(node, node)}
    if looping:
        contradictory |= looping | {
            downstream for node in looping for downstream in nx.descendants(graph, node)
        }
        graph.remove_nodes_from(contradictory & set(graph))
    order = nx.lexicographical_topological_sort(
        graph, # An unknown priority sorts as medium rather than raising: validate_all
        # has already said so, and the timeline should still draw.
        key=lambda node: (
            PRIORITY_RANK.get(active[node].priority, PRIORITY_RANK["medium"]),
            node,
        )
    )
    return list(order), contradictory


def _unschedulable(active: dict[str, Entity]) -> set[str]:
    """Entities on a `depends_on` cycle, plus everything downstream of one."""
    graph = nx.DiGraph()
    graph.add_nodes_from(active)
    for entity in active.values():
        for blocker in entity.depends_on:
            if blocker in active:
                graph.add_edge(blocker, entity.id)
    caught = {
        node
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for node in component
    } | {node for node in active if graph.has_edge(node, node)}
    return caught | {d for node in caught for d in nx.descendants(graph, node)}


def schedule(
    entities: list[Entity], config: Config, today: date
) -> tuple[dict[str, Span], dict[str, Explanation]]:
    live = {e.id: e for e in entities if e.status != "shelved"}
    children: dict[str, list[str]] = defaultdict(list)
    for entity in live.values():
        if entity.parent in live:
            children[entity.parent].append(entity.id)

    spans: dict[str, Span] = {}
    explanations: dict[str, Explanation] = {}

    # Completed work is a historical marker, never a forecast, and never a claim
    # on anyone's future capacity.
    for entity in live.values():
        if entity.status == "done" and entity.assigned_on is not None:
            spans[entity.id] = Span(
                start=entity.assigned_on, end=entity.assigned_on, historical=True
            )

    active = {i: e for i, e in live.items() if e.status != "done"}
    stalled = _unschedulable(active)
    order, contradictory = _ordering(
        {i: e for i, e in active.items() if i not in stalled}, config
    )
    floor = _first_working_day(today, config)
    for entity_id in stalled | contradictory:
        spans[entity_id] = Span(start=floor, end=floor, unscheduled=True)

    booked: dict[str, list[tuple[date, date]]] = defaultdict(list)
    for entity_id in order:
        entity = active[entity_id]
        kids = [spans[k] for k in children.get(entity_id, ()) if k in spans]
        if kids:
            spans[entity_id] = Span(
                start=min(k.start for k in kids),
                end=max(k.end for k in kids),
                estimated=any(k.estimated for k in kids),
                overruns_cycle_weeks=_overrun(entity, max(k.end for k in kids), config, live),
            )
            continue

        # A project is a container, and an empty one contains nothing to draw. It
        # has no size field, so it fell to the default and drew a half-week bar
        # nobody had written — a phantom on the timeline for a milestone whose
        # pitches have not been shaped yet. No span at all is the honest answer,
        # and every view already copes with an entity that has none.
        if entity.kind == "project":
            continue

        duration, estimated = _duration_weeks(entity, config, live)
        workers = _workers(entity)
        placed = _place(entity, duration, workers, booked, spans, floor, config, live)
        if placed is None:
            # Unscheduled, exactly as a dependency cycle is: the scheduler has no
            # answer, and saying so is better than inventing one. Clamping the end
            # to `date.max` instead was worse in every direction — the timeline
            # then drew a bar to the end of time and `_month_ticks` walked eight
            # thousand years of months, so the page that stopped raising started
            # producing megabytes of ticks nobody asked for. `render` drops an
            # unscheduled span from the plot entirely, so this keeps one absurd
            # number from setting the scale for every other bar on the page.
            # Nothing is booked either: work with no dates on it holds nobody's
            # capacity.
            spans[entity_id] = Span(
                start=floor, end=floor, unscheduled=True, estimated=estimated,
                unowned=not workers,
            )
            explanations[entity_id] = Explanation(
                entity_id=entity_id,
                text=f"Not placed: {duration:g} weeks of work runs past the end of the calendar.",
            )
            continue
        span, explanation = placed
        spans[entity_id] = span.model_copy(
            update={
                "estimated": estimated,
                "unowned": not workers,
                "overruns_cycle_weeks": _overrun(entity, span.end, config, live),
            }
        )
        if explanation is not None:
            explanations[entity_id] = explanation
        for worker in workers:
            booked[worker].append((span.start, span.end))

    return spans, explanations


def _place(
    entity: Entity,
    duration: float,
    workers: list[str],
    booked: dict[str, list[tuple[date, date]]],
    spans: dict[str, Span],
    floor: date,
    config: Config,
    by_id: dict[str, Entity],
) -> tuple[Span, Explanation | None] | None:
    """Earliest slot at or after the entity is ready, respecting capacity 1.

    `None` when no slot fits inside the calendar. The question used to be asked
    once, in `schedule`, against today — but the start is not today: a blocker
    dated at the end of time, or a worker booked until it, pushes it there, and
    then the walks below stepped off the calendar and raised. Asked against the
    start each time round the loop it is also what terminates the loop, since
    `start` only ever moves forward.
    """
    blocker_id, blocker_ready = None, floor
    # Its own blockers and its ancestors': a dependency written on the pitch is
    # what its tasks wait for. See `blockers_of`.
    for target in blockers_of(entity, by_id):
        if target in spans and spans[target].end >= blocker_ready:
            blocker_id, blocker_ready = target, _next_working_day(spans[target].end, config)

    ready = max(floor, entity.assigned_on or floor, blocker_ready)
    start = _first_working_day(ready, config)
    busy_worker, busy_until = None, None
    while True:
        if _runs_past_the_calendar(start, duration, config):
            return None
        end = working_days_after(start, duration, config)
        clash = [
            (worker, booked_end)
            for worker in workers
            for booked_start, booked_end in booked[worker]
            if booked_start <= end and start <= booked_end
        ]
        if not clash:
            break
        busy_worker, busy_until = max(clash, key=lambda pair: pair[1])
        start = _next_working_day(busy_until, config)

    return Span(start=start, end=end), _explain(
        entity.id, start, floor, blocker_id, blocker_ready, busy_worker, busy_until, spans
    )


def _explain(
    entity_id: str,
    start: date,
    floor: date,
    blocker_id: str | None,
    blocker_ready: date,
    busy_worker: str | None,
    busy_until: date | None,
    spans: dict[str, Span],
) -> Explanation | None:
    """Name the constraint that actually decided the start date.

    Work that begins today is not delayed by anything and needs no sentence; the
    first *unexplained* surprising date is when people stop trusting the timeline.
    """
    if start <= floor:
        return None
    if busy_until is not None and busy_until >= blocker_ready:
        return Explanation(
            entity_id=entity_id,
            text=f"Cannot start before {start}: {busy_worker} is busy until {busy_until}.",
            worker_busy_until=busy_until,
        )
    if blocker_id is not None:
        return Explanation(
            entity_id=entity_id,
            text=f"Cannot start before {start}: {blocker_id} finishes on {spans[blocker_id].end}.",
            blocker_id=blocker_id,
        )
    return None
