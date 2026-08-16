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
from datetime import date, timedelta

import networkx as nx
from pydantic import BaseModel

from .model import PRIORITY_RANK, Config, Entity, size_weeks

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
    day += timedelta(days=1)
    while not _is_working_day(day, config):
        day += timedelta(days=1)
    return day


def _first_working_day(day: date, config: Config) -> date:
    while not _is_working_day(day, config):
        day += timedelta(days=1)
    return day


def working_days_after(start: date, weeks: float, config: Config) -> date:
    """The inclusive last day of `weeks` working weeks beginning at `start`.

    Rounded to whole days, and to six decimals first: 1.2 * 5 is 6.000000000000001
    in binary floating point, and a naive ceil would buy a seventh day.
    """
    days = max(1, math.ceil(round(weeks * _WORKING_DAYS_PER_WEEK, 6)))
    day = _first_working_day(start, config)
    for _ in range(days - 1):
        day = _next_working_day(day, config)
    return day


def _duration_weeks(entity: Entity, config: Config) -> tuple[float, bool]:
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
    rates = [_availability_of(who, entity, config) for who in _workers(entity)]
    return size / (sum(rates) or config.nominal_availability or 1.0), defaulted


def _availability_of(who: str, entity: Entity, config: Config) -> float:
    """One person's rate in the cycle this entity was bet into.

    Read from the entity's own cycle rather than passed in, so there is one
    source: a global override and a per-cycle record would disagree the first
    time somebody set both.

    Absent from the roster means "nobody said otherwise", not "unavailable" — a
    roster that has to name everybody to schedule anybody is a roster that goes
    stale and takes the dates with it. A rate of zero means the same, rather than
    meaning a bet nobody can ever finish.
    """
    plan = config.plans.get(entity.cycle) if entity.cycle is not None else None
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


def _overrun(entity: Entity, end: date, config: Config) -> float | None:
    """Weeks past the end of the cycle's BUILD, or None.

    Cool-down is not build time — Shape Up's whole point is that work lands
    inside the build weeks and the cool-down is for the mess afterwards. Measured
    against the end of the window instead, every overrun was understated by the
    cool-down length and some were hidden completely.

    A cycle nobody has dated yet is not an overrun. Indexing `config.cycles`
    directly would turn one unconfigured number into a KeyError for every span.
    """
    window = config.cycles.get(entity.cycle) if entity.cycle is not None else None
    if window is None:
        return None
    builds_until = build_end(entity.cycle, window, config)
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
        else window[1] - timedelta(days=round(config.cooldown_weeks * 7))
    )
    # A cool-down longer than the window would put the end of build before the
    # cycle began, and then every entity in it overruns by definition. Clamped
    # rather than rejected: a bad number in one config file should cost that
    # cycle's flag, not every date on the page.
    return max(ends, window[0])


def _ordering(
    active: dict[str, Entity], config: Config
) -> tuple[list[str], set[str]]:
    """Visit order: blockers before dependents, children before parents.

    Containment is not a dependency, so a topological sort over `depends_on`
    alone would visit a parent before the children its span is built from. The
    two edge kinds can also disagree — an entity depending on its own ancestor
    contributes a dependency edge one way and a containment edge the other — and
    that record is dropped rather than allowed to raise.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(active)
    for entity in active.values():
        for blocker in entity.depends_on:
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
    order = nx.lexicographical_topological_sort(
        graph, # An unknown priority sorts as medium rather than raising: validate_all
        # has already said so, and the timeline should still draw.
        key=lambda node: (PRIORITY_RANK.get(active[node].priority, 1), node)
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
                overruns_cycle_weeks=_overrun(entity, max(k.end for k in kids), config),
            )
            continue

        duration, estimated = _duration_weeks(entity, config)
        workers = _workers(entity)
        span, explanation = _place(
            entity, duration, workers, booked, spans, floor, config
        )
        spans[entity_id] = span.model_copy(
            update={
                "estimated": estimated,
                "unowned": not workers,
                "overruns_cycle_weeks": _overrun(entity, span.end, config),
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
) -> tuple[Span, Explanation | None]:
    """Earliest slot at or after the entity is ready, respecting capacity 1."""
    blocker_id, blocker_ready = None, floor
    for target in entity.depends_on:
        if target in spans and spans[target].end >= blocker_ready:
            blocker_id, blocker_ready = target, _next_working_day(spans[target].end, config)

    ready = max(floor, entity.assigned_on or floor, blocker_ready)
    start = _first_working_day(ready, config)
    busy_worker, busy_until = None, None
    while True:
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
