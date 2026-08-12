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
from datetime import date

from pydantic import BaseModel

from .model import Config, Entity, Problem, ancestors, validate_all
from .schedule import Explanation, Span, schedule

COMPUTED_PREDICATES = (
    "blocked",
    "unblocked",
    "overruns_cycle",
    "missing_required_fields",
    "review_waived",
)

_SCALAR_FACETS = ("kind", "status", "owner", "priority", "cycle")
_LIST_FACETS = ("assignees", "reviewers", "tags")


class Index(BaseModel):
    entities: dict[str, Entity]
    children: dict[str, list[str]]
    blocked_by: dict[str, list[str]]
    blocks: dict[str, list[str]]
    spans: dict[str, Span]
    explanations: dict[str, Explanation]
    problems: list[Problem]
    facets: dict[str, list[str]]
    search_blob: dict[str, str]


def _project_of(entity: Entity, by_id: dict[str, Entity]) -> str | None:
    """The project an entity belongs to, walking up the parent chain.

    A task names its pitch, never its project, so grouping by project is empty
    unless the chain is followed.
    """
    if entity.kind == "project":
        return entity.id
    for ancestor in ancestors(entity.id, by_id):
        if by_id[ancestor].kind == "project":
            return ancestor
    return None


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


def build_index(entities: list[Entity], config: Config, today: date) -> Index:
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
    for entity in entities:
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, "project"):
            facets[field].update(_facet_values(entity, field, by_id))
        search_blob[entity.id] = " ".join(
            [entity.title, *entity.tags, entity.body]
        ).lower()

    return Index(
        entities=by_id,
        children=children,
        blocked_by=blocked_by,
        blocks=blocks,
        spans=spans,
        explanations=explanations,
        problems=validate_all(entities, config),
        facets={field: sorted(values) for field, values in facets.items()}
        | {"predicate": sorted(COMPUTED_PREDICATES)},
        search_blob=search_blob,
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
    if predicate == "review_waived":
        return index.entities[entity_id].review_waived
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
