from datetime import date

import pytest
from pydantic import ValidationError

from openproj.model import Entity, Pitch, Project, Task, checklist, sections


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
    # A list, and empty rather than None: shaping is often done in pairs, and a
    # bare string in a file still parses (and still writes back) as one name.
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").shaped_by == []
    assert Pitch(id="pitch-abc123", kind="pitch", title="P", shaped_by="jcanton").shaped_by == [
        "jcanton"
    ]
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
    # Status is deliberately NOT constrained here: a stale or mistyped one has to
    # parse and be reported, or one old file takes every page down. See
    # test_validate.test_a_word_nobody_defined_is_a_problem_and_not_a_crash.
    assert Entity(id="task-abc123", kind="task", title="T", status="in-progress").status
    with pytest.raises(ValidationError):
        Entity(id="task-abc123", kind="banana", title="T")


# --------------------------------------------------------------------------- #
# Reading the shaping document
#
# Two readers over the body, and nothing that writes to it. The team's pitch
# template asks for a `## Progress` checklist and for `## No-gos`; these are how
# the tool can count one and notice the other without turning prose into fields.
# --------------------------------------------------------------------------- #


def test_a_checklist_is_counted_including_its_sub_items():
    """The template nests subtasks under tasks, and "2 of 4" is what a reader
    means by it — the sub-items are the work."""
    body = (
        "## Progress\n\n"
        "- [x] Task 1 ([PR#1](https://example.invalid))\n"
        "  - [x] Subtask A\n"
        "  - [ ] Subtask B\n"
        "- [ ] Task 2\n"
    )
    assert checklist(body) == (2, 4)


def test_a_body_with_no_checklist_counts_nothing_rather_than_zero_of_zero():
    """A body nobody has written a list in has no progress to report, which is
    not the same as no progress made."""
    assert checklist("## Problem\n\nProse only.\n") == (0, 0)


def test_a_checklist_inside_a_code_fence_is_somebody_elses_example():
    """A pitch about tooling quotes task lists. Counting them would report
    progress on an example."""
    body = "## Solution\n\n```markdown\n- [ ] not ours\n- [x] also not\n```\n\n- [x] ours\n"
    assert checklist(body) == (1, 1)


def test_sections_are_keyed_by_their_heading_lowercased_and_flat():
    """Flat on purpose: the template is flat, and a reader asking for "no-gos"
    does not care whether it was written with two hashes or three."""
    assert sections("## Problem\n\nP\n\n### No-gos\n\nNone of it.\n") == {
        "problem": "P",
        "no-gos": "None of it.",
    }


def test_a_heading_inside_a_code_fence_is_not_a_section():
    assert "no-gos" not in sections("## Problem\n\n```\n## No-gos\n```\n")


def test_an_empty_section_is_present_and_empty_so_a_reader_can_tell_them_apart():
    """`## No-gos` with nothing under it is the corpus's most common state, and it
    is not the same as never having written the heading."""
    assert sections("## No-gos\n\n## Progress\n\n- [ ] a\n")["no-gos"] == ""
