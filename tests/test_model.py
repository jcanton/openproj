from datetime import date

import pytest
from pydantic import ValidationError

from openproj.model import Entity, Pitch, Project, Task


def test_an_entity_needs_only_id_kind_and_title():
    """Parse permissively: everything else must be optional, or one hand-edited
    file with a missing field would make the whole repository unloadable."""
    entity = Entity(id="task-abc123", kind="task", title="Something")
    assert entity.status == "shaping"
    assert entity.owner is None
    assert entity.assignees == []
    assert entity.reviewers == []
    assert entity.review_waived is False
    assert entity.depends_on == []
    assert entity.priority == "medium"
    assert entity.created_schema_version == 1


def test_sizes_are_optional_on_both_subclasses():
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").appetite_weeks is None
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").shaped_by is None
    assert Task(id="task-abc123", kind="task", title="T").effort_weeks is None


def test_the_subclasses_carry_only_their_own_size_field():
    assert "effort_weeks" not in Pitch.model_fields
    assert "appetite_weeks" not in Task.model_fields
    assert "shaped_by" not in Task.model_fields
    assert Project.model_fields.keys() == Entity.model_fields.keys()


def test_optional_fields_still_accept_real_values():
    pitch = Pitch(
        id="pitch-1b3f9a",
        kind="pitch",
        title="MPI on CI verify with serial",
        appetite_weeks=1.0,
        shaped_by="jcanton",
        owner="msimberg",
        reviewers=["jcanton"],
        assigned_on=date(2026, 8, 13),
        depends_on=["task-5a4e39"],
    )
    assert pitch.appetite_weeks == 1.0
    assert pitch.assigned_on == date(2026, 8, 13)


def test_status_and_kind_are_still_constrained():
    """Permissive about absence, not about nonsense: an unknown status is a typo,
    not a missing value, and silently accepting it would corrupt the scheduler."""
    with pytest.raises(ValidationError):
        Entity(id="task-abc123", kind="task", title="T", status="in-progress")
    with pytest.raises(ValidationError):
        Entity(id="task-abc123", kind="banana", title="T")
