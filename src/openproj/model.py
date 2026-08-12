"""Entities, configuration and validation.

Parse permissively, validate strictly: every entity field is optional at the type
level so that a hand-edited file with a missing field still loads. Requiredness
lives in `validate_all`, never in the parse types — see spec section 5.2.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from ruamel.yaml import YAML

_CONFIG_FILES = ("defaults.yaml", "cycles.yaml", "holidays.yaml")


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
