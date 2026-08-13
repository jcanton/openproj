"""Entities, configuration and validation.

Parse permissively, validate strictly: every entity field is optional at the type
level so that a hand-edited file with a missing field still loads. Requiredness
lives in `validate_all`, never in the parse types — see spec section 5.2.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Literal

import networkx as nx
from frontmatter.default_handlers import YAMLHandler
from pydantic import BaseModel, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq

_CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml", "people.yaml")
_ENTITY_DIRS = ("projects", "pitches", "tasks")


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


class Config(BaseModel):
    """Repository-wide planning configuration.

    `schema_version` is the version NEW entities are created at, which is not
    necessarily the version the existing corpus was written at.
    """

    schema_version: int = 1
    nominal_availability: float = 1.0
    default_task_effort: float = 0.5
    holidays: list[date] = []
    cycles: dict[int, tuple[date, date]] = {}
    # The roster, from config/people.yaml. Empty means the check is off, which is
    # the right default: a tracker that refuses a name because nobody has written
    # a roster yet is a tracker nobody finishes setting up.
    known_people: list[str] = []


def load_config(root: Path) -> Config:
    """Merge the three config files. Absent files fall back to the defaults.

    Unknown keys are ignored so that a repository with a half-written config
    still loads rather than taking the whole index down.
    """
    data: dict[str, object] = {}
    for name in _CONFIG_FILES:
        path = root / "config" / name
        if not path.is_file():
            continue
        loaded = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update({k: v for k, v in loaded.items() if k in Config.model_fields})
    return Config.model_validate(data)


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


def load_repo(root: Path) -> tuple[list[Entity], Config]:
    entities = [
        parse_file(path)
        for directory in _ENTITY_DIRS
        for path in sorted((root / directory).glob("*.md"))
    ]
    return entities, load_config(root)


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
        yield "blocker", "depends_on", "part of a depends_on cycle", 1
        return
    # A parent cycle makes "ancestor" undefined, so the relational checks are
    # skipped rather than reporting a second, derived problem for one broken chain.
    own_ancestors = set() if entity.id in parent_cycles else set(ancestors(entity.id, by_id))
    for target in entity.depends_on:
        if target not in by_id:
            yield "blocker", "depends_on", f"depends_on target {target} does not exist", 1
        elif target in own_ancestors:
            yield "blocker", "depends_on", f"cannot depend on {target}: it is an ancestor", 1
        elif entity.id in ancestors(target, by_id):
            yield "blocker", "depends_on", f"cannot depend on {target}: it is a descendant", 1
        elif by_id[target].status == "shelved":
            yield "warning", "depends_on", f"depends_on target {target} is shelved", 1


def _status_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]:
    """One gate per status, not a cumulative stack.

    `shaping` is exempt because an idea nobody has bet on yet has no owner and no
    size by definition, and demanding them is how a tracker stops being somewhere
    people put half-formed things. `done` is exempt from the earlier gates for a
    duller reason: migrated history often cannot say who owned something in 2025,
    and a validator that blocks on unknowable facts gets switched off.
    """
    if entity.status in ("shaping", "shelved"):
        return
    if entity.status == "ready":
        if entity.owner is None:
            yield "blocker", "owner", "a ready entity needs an owner", 1
        if not (entity.review_waived or entity.reviewers):
            yield "blocker", "reviewers", "a ready entity needs a reviewer, or review_waived", 1
        field = _SIZE_FIELD.get(entity.kind)
        if field is not None and getattr(entity, field) is None:
            yield "blocker", field, f"a ready {entity.kind} needs {field}", 1
        if entity.kind == "pitch" and entity.shaped_by is None:
            yield "blocker", "shaped_by", "a ready pitch needs shaped_by", 2
    elif entity.status == "in_progress":
        if entity.assigned_on is None:
            yield "blocker", "assigned_on", "work in progress needs assigned_on", 1
        if not entity.review_waived and not (set(entity.reviewers) - {entity.owner}):
            yield (
                "blocker",
                "reviewers",
                "work in progress needs a reviewer other than its owner, or review_waived",
                1,
            )
    elif entity.status == "done" and not entity.prs:
        yield "blocker", "prs", "a done entity needs at least one PR", 1


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
