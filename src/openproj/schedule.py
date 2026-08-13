"""Derive a timeline from sizes, dependencies and assignment dates.

Nobody types a start or an end date. A `Span` is inclusive — `end` is the last
working day the item occupies — so anything following it starts on the next
working day, never the same one.

Two invariants earn their own tests because breaking either produces a schedule
that looks plausible and is wrong:

* A size is never divided by availability. `appetite_weeks` already means elapsed
  weeks at nominal availability, so the ratio `nominal / availability(owner)` is
  1 unless someone works at a different rate. Dividing turns every three-week bet
  into five.
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
    """Elapsed weeks, and whether the size was defaulted rather than stated."""
    size, defaulted = size_weeks(entity, config)
    availability = config.nominal_availability
    ratio = config.nominal_availability / availability if availability else 1.0
    return size * ratio, defaulted


def _workers(entity: Entity) -> list[str]:
    return ([entity.owner] if entity.owner else []) + list(entity.assignees)


def _overrun(entity: Entity, end: date, config: Config) -> float | None:
    """Weeks past the end of the entity's cycle, or None.

    A cycle nobody has dated yet is not an overrun. Indexing `config.cycles`
    directly would turn one unconfigured number into a KeyError for every span.
    """
    window = config.cycles.get(entity.cycle) if entity.cycle is not None else None
    if window is None or end <= window[1]:
        return None
    return (end - window[1]).days / 7


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
        graph, key=lambda node: (PRIORITY_RANK[active[node].priority], node)
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
