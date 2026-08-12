"""Entities, configuration and validation.

Parse permissively, validate strictly: every entity field is optional at the type
level so that a hand-edited file with a missing field still loads. Requiredness
lives in `validate_all`, never in the parse types — see spec section 5.2.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Literal

from frontmatter.default_handlers import YAMLHandler
from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq

_CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml")
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
    status: Literal["todo", "wip", "done", "shelved"] = "todo"

    owner: str | None = None
    assignees: list[str] = []
    reviewers: list[str] = []
    review_waived: bool = False

    assigned_on: date | None = None
    priority: int = 2
    depends_on: list[str] = []
    cycle: int | None = None
    tags: list[str] = []
    prs: list[str] = []

    body: str = ""
    created_schema_version: int = 1


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
