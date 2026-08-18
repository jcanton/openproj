from datetime import date

import pytest
from pydantic import ValidationError

from openproj.model import (
    Entity,
    Pitch,
    Project,
    Task,
    checklist,
    parse_cycle_text,
    patch_text,
    sections,
    split_front_matter,
)


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
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").person_weeks is None
    # A list, and empty rather than None: shaping is often done in pairs, and a
    # bare string in a file still parses (and still writes back) as one name.
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").shaped_by == []
    assert Pitch(id="pitch-abc123", kind="pitch", title="P", shaped_by="jcanton").shaped_by == [
        "jcanton"
    ]
    assert Task(id="task-abc123", kind="task", title="T").person_weeks is None


def test_a_pitch_and_a_task_share_one_size_field_and_a_project_has_none():
    """`appetite_weeks` and `effort_weeks` were one quantity under two names that
    `size_weeks` read as one on every call. A project is a container for pitches
    and has no size of its own to state."""
    assert "person_weeks" in Pitch.model_fields
    assert "person_weeks" in Task.model_fields
    assert "person_weeks" not in Project.model_fields
    # `shaped_by` is the field that really is one kind's: shaping is what a pitch
    # gets, and it is asked for at `ready`.
    assert "shaped_by" not in Task.model_fields
    assert Project.model_fields.keys() == Entity.model_fields.keys()


def test_optional_fields_still_accept_real_values():
    pitch = Pitch(
        id="pitch-1b3f9a",
        kind="pitch",
        title="MPI on CI verify with serial",
        person_weeks=1.0,
        shaped_by="jcanton",
        owner="msimberg",
        reviewers=["jcanton"],
        assigned_on=date(2026, 8, 13),
        depends_on=["task-5a4e39"],
    )
    assert pitch.person_weeks == 1.0
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


def test_an_empty_frontmatter_block_is_frontmatter_and_not_body():
    """`---\\n---\\n` has no newline of its own before the closing delimiter, so
    partitioning the opening `---\\n` away leaves `---\\n`, which contains no
    `\\n---\\n` — and the whole document came back as body with no frontmatter.

    `web.py` starts a record that does not exist yet from exactly that string, so
    `patch_text` copied it into the body: every cycle started without a goal was
    committed with a literal `---` and `---` as its text, and the page drew two
    horizontal rules under an empty heading, which is what it was asked to draw.
    """
    assert split_front_matter("---\n---\n") == ("", "")
    assert split_front_matter("---\n---") == ("", "")
    assert split_front_matter("---\n---\n\nreal body\n") == ("", "\nreal body\n")
    # And the ordinary cases are untouched.
    assert split_front_matter("---\ncycle: 1\n---\nbody\n") == ("cycle: 1", "body\n")
    assert split_front_matter("no frontmatter\n") == ("", "no frontmatter\n")


def test_a_record_created_from_nothing_carries_no_delimiters_in_its_body():
    """The end-to-end shape of the bug above: this is the exact call `web.py`
    makes for a cycle that does not exist yet."""
    written = patch_text("---\n---\n", {"cycle": 90, "starts_on": "2026-09-28"}, None)

    assert written == "---\ncycle: 90\nstarts_on: '2026-09-28'\n---\n"
    assert "---\n---" not in written.removeprefix("---\n")


def test_the_goal_is_a_field_and_the_notes_are_the_body():
    """Two things written at different moments by different people: the goal is
    settled at the betting table and then does not move, the notes accumulate all
    cycle. Sharing one box put the cycle's whole point wherever the growing half
    of the document happened to leave it."""
    cycle = parse_cycle_text(
        "---\ncycle: 38\nstarts_on: 2026-09-28\ngoal: Ship the dycore port\n---\n"
        "Turbulence was left out: no reviewer free.\n",
        "cycles/0038.md",
    )

    assert cycle.goal == "Ship the dycore port"
    assert cycle.body == "Turbulence was left out: no reviewer free.\n"
    # A record written before the field existed still loads, with an empty goal
    # rather than a refusal — every field here is optional at the type level.
    assert parse_cycle_text("---\ncycle: 1\nstarts_on: 2026-01-05\n---\n", "c.md").goal == ""


# --------------------------------------------------------------------------- #
# A person's own record: `people/<login>.md`
#
# The identity is the path and only the path. Every other record here carries its
# id in the frontmatter as well, and has to — an id is minted, opaque and pointed
# at by other records, while the filename carries a slug that drifts. Nothing
# points at a person record, so a second copy of the login would buy nothing and
# would buy `_identity_problems`: two answers to "which record is this", resolved
# in opposite directions by two halves of the app.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "login",
    ("jcanton", "a", "a" * 39, "OngChia", "yiluchen1066", "abishekg7", "a-b", "a--b"),
)
def test_a_login_becomes_the_one_path_it_may_be_written_at(login: str):
    """1 to 39 of `[A-Za-z0-9-]`, no hyphen at either end — every one of these is
    a real login from the team's own roster or the edge of the rule. `a--b` is
    admitted although GitHub itself refuses it: being narrower than the wire buys
    nothing this pattern exists for, and would refuse somebody the day GitHub
    relaxes its own rule."""
    from openproj.model import person_path

    assert person_path(login) == f"people/{login}.md"


@pytest.mark.parametrize(
    "login",
    (
        "",                      # nobody
        "-ann",                  # a leading hyphen
        "ann-",                  # and a trailing one
        "a" * 40,                # one over the limit
        "../config/defaults",    # the reason this is a pattern and not a check
        "a/b",
        "ann.md",
        "ann name",
        ".",
        "..",
        "ann\n",                 # a trailing newline is not the end of a match
        "ann\nbo",
    ),
)
def test_a_name_that_is_not_a_login_gets_no_path_at_all(login: str):
    """The writable surface is closed by construction, and this is the
    construction. `people/` gains one file per person and there is no path
    parameter anywhere near it: a login that does not match is not sanitised, not
    escaped and not written — it has nowhere to arrive.

    `ann\\n` is here because `$` in a Python pattern matches before a trailing
    newline, which is how a path check comes to admit a name with a line break in
    it. `\\Z` is what this one uses.
    """
    from openproj.model import person_path

    assert person_path(login) is None


def test_a_person_record_takes_its_login_from_the_path():
    """The path is the identity. The record itself says only what was chosen."""
    from openproj.model import parse_person_text

    person = parse_person_text("---\nicon: fox\n---\n", "people/jcanton.md")

    assert person.login == "jcanton"
    assert person.icon == "fox"


def test_a_login_typed_into_the_frontmatter_is_ignored_rather_than_believed():
    """The one thing a second copy of the identity could do is disagree with the
    first, and then which record this is depends on which half of the app you
    ask. That is `_identity_problems`, two blocker rules and a special case in
    the entity save, all paid for a fact the filename already carried — so here
    the frontmatter simply has no say."""
    from openproj.model import parse_person_text

    person = parse_person_text("---\nlogin: bo\nicon: owl\n---\n", "people/ann.md")

    assert person.login == "ann"


def test_a_file_in_people_that_is_not_named_for_a_login_is_refused():
    """A `people/notes.md` somebody dropped in by hand is one unreadable file
    with a reason beside it — not a person called `notes` who quietly appears on
    a page beside the real ones."""
    from openproj.model import parse_person_text

    with pytest.raises(ValueError, match="is not one"):
        parse_person_text("---\nicon: fox\n---\n", "people/some notes.md")


@pytest.mark.parametrize("written", ("icon: 7", "icon: [fox]", "icon: {a: b}"))
def test_an_icon_nobody_can_draw_still_reads(written: str):
    """Parse permissively, validate strictly — the same bargain `status` makes.
    A hand edit should cost the drawing beside one name, never the file: a person
    record that will not load is one that takes its login's mark off the page and
    a line of the unreadable banner with it."""
    from openproj.model import parse_person_text

    assert parse_person_text(f"---\n{written}\n---\n", "people/ann.md").login == "ann"


def test_a_sentence_somebody_wrote_about_themselves_survives_a_pick():
    """The body is not a field and nothing here reads it — and it still has to
    come back byte for byte, because the file is one a person may write in git.
    That is `patch_text`'s promise rather than this record's, which is the point:
    the record shape inherits it instead of restating it."""
    original = "---\nicon: fox\n---\n\nAnn, who works on the dycore.\n"

    patched = patch_text(original, {"icon": "owl"})

    assert patched == "---\nicon: owl\n---\n\nAnn, who works on the dycore.\n"
