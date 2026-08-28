from datetime import date

import pytest
from pydantic import ValidationError

from openproj.model import (
    ISSUE_STATUS,
    KINDS,
    Issue,
    Pitch,
    Project,
    Record,
    Task,
    checklist,
    checklist_items,
    only_sections,
    parse_cycle_text,
    patch_text,
    sections,
    split_front_matter,
    without_checklist,
    without_sections,
)


def test_a_record_needs_only_id_kind_and_title():
    """Parse permissively: everything else must be optional, or one hand-edited
    file with a missing field would make the whole repository unloadable."""
    record = Record(id="task-abc123", kind="task", title="Something")
    assert record.status == "thinking"
    assert record.owner is None
    assert record.assignees == []
    assert record.reviewers == []
    assert record.review_waived is False
    assert record.depends_on == []
    assert record.priority == "medium"
    assert record.created_schema_version == 1


def test_a_record_opens_at_the_foot_of_its_own_ladder():
    """The opening status is written once per ladder, and it is that ladder's
    first word.

    It used to be written five times: three model defaults, an `opens` column in
    `web.INBOXES`, and two `|| 'shaping'` fallbacks in the form scripts. They all
    agreed, and they agreed right up until the planned ladder gained a rung below
    `shaping` — at which point four of the five would have gone on naming a word
    that is no longer where anything starts, in silence, because nothing ever
    compares them. The rule that replaced them is the one asserted here.

    Derived AND written out. The derivation is what stops the default drifting
    out of the vocabulary it has to be a member of; the literal list is what says
    which order was meant, since a ladder reordered by accident satisfies the
    derivation perfectly.
    """
    for rung in KINDS:
        # A product reads no status at all — `statuses=()` — so it has no foot to
        # open at. It still INHERITS `Record.status`, which is the line below.
        if not rung.statuses:
            continue
        opens = rung.model.model_fields["status"].default
        assert opens == rung.statuses[0], rung.name

    assert {rung.name: rung.model.model_fields["status"].default for rung in KINDS} == {
        # Nobody has looked at it yet: the three planned rungs that read the plan
        # ladder open at its foot.
        "project": "thinking",
        "pitch": "thinking",
        "task": "thinking",
        # Inherited and unread. A product carries the word in memory and no page
        # ever asks it for one, because `status` is on `unread_fields("product")`
        # — pinned here so that moving the base default is a line somebody sees.
        "product": "thinking",
        # Reported, therefore already thought about: an issue's ladder starts a
        # rung higher and deliberately has no `thinking` on it at all.
        "issue": "ready",
        # Where the word came from. A note has been `thinking` since notes
        # existed, and `STATUS_ORDER` borrowed it rather than inventing one.
        "note": "thinking",
    }
    assert "thinking" not in ISSUE_STATUS
    assert Task(id="task-abc123", kind="task", title="T").status == "thinking"
    assert Issue(id="issue-abc123", kind="issue", title="I").status == "ready"


def test_sizes_are_optional_on_both_subclasses():
    assert Pitch(id="pitch-abc123", kind="pitch", title="P").person_weeks is None
    assert Task(id="task-abc123", kind="task", title="T").person_weeks is None


def test_a_pitch_and_a_task_share_one_size_field_and_a_project_has_none():
    """`appetite_weeks` and `effort_weeks` were one quantity under two names that
    `size_weeks` read as one on every call. A project is a container for pitches
    and has no size of its own to state."""
    assert "person_weeks" in Pitch.model_fields
    assert "person_weeks" in Task.model_fields
    assert "person_weeks" not in Project.model_fields
    # Retired, and deliberately not coming back: on a pitch `owner` is who
    # shaped it and holds it — jcanton, 2026-08-24, having counted four lists
    # of people on one record. This line is the tripwire.
    assert "shaped_by" not in Pitch.model_fields
    assert Project.model_fields.keys() == Record.model_fields.keys()


def test_optional_fields_still_accept_real_values():
    pitch = Pitch(
        id="pitch-1b3f9a",
        kind="pitch",
        title="MPI on CI verify with serial",
        person_weeks=1.0,
        owner="merganserly",
        reviewers=["jackdawrie"],
        start_date=date(2026, 8, 13),
        depends_on=["task-5a4e39"],
    )
    assert pitch.person_weeks == 1.0
    assert pitch.start_date == date(2026, 8, 13)


def test_status_and_kind_are_still_constrained():
    """Permissive about absence, not about nonsense: an unknown status is a typo,
    not a missing value, and silently accepting it would corrupt the scheduler."""
    # Status is deliberately NOT constrained here: a stale or mistyped one has to
    # parse and be reported, or one old file takes every page down. See
    # test_validate.test_a_word_nobody_defined_is_a_problem_and_not_a_crash.
    assert Record(id="task-abc123", kind="task", title="T", status="in-progress").status
    with pytest.raises(ValidationError):
        Record(id="task-abc123", kind="banana", title="T")


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


def test_a_box_at_the_end_of_a_file_is_a_box():
    """The end of a line is as good as a space after `]`, and this is not a
    corner: `_TASK_TEMPLATE` ends `## Progress\\n\\n- [ ]` with nothing after the
    bracket, so it was the shape of every task this tool creates. Wanting real
    whitespace there meant that line was not a point at all — `checklist` did not
    count it, so a fresh task reported nothing about its own progress, and
    `without_checklist` did not lift it, so a review slide printed the literal
    characters `[ ]` under a `## Progress` nothing had emptied.

    This is the half of that fix which is not about the deck: a point with no
    words is a point wherever progress is counted, which is what `checklist_items`
    already said it was."""
    assert checklist_items("- [ ]") == [(False, "")]
    assert checklist_items("## Progress\n\n- [x]") == [(True, "")]
    assert checklist("- [x] Gather to rank 0\n- [ ]") == (1, 2)
    assert without_checklist("## Progress\n\n- [ ]") == ""
    # Still a marker and not a prefix: what follows the bracket has to be the end
    # of the line or a space, or `[ ]` is somebody's prose about a box.
    assert checklist_items("- [ ]x nothing ticked here") == []
    assert checklist_items("- [] no room in it") == []


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


def test_a_section_is_dropped_with_everything_written_underneath_it():
    """A section's NAME is flat and its EXTENT is not. Ending a section at the
    next heading of any depth at all let a `### Second one` written under
    `## Rabbit holes` escape a drop of "rabbit holes" — and arrive on a review
    slide with nothing above it to say what it was part of, which is worse than
    printing the whole section."""
    body = (
        "## Rabbit holes\n\nThe TDMA.\n\n### Second one\n\nThe tap points.\n\n## Notes\n\nKept.\n"
    )
    assert without_sections(body, {"rabbit holes"}) == "## Notes\n\nKept."
    assert "The tap points." in only_sections(body, {"rabbit holes"})
    assert "Kept." not in only_sections(body, {"rabbit holes"})


def test_a_heading_survives_a_subsection_that_survives_it():
    """Emptying a heading of its own lines is not emptying it. `## Progress` that
    held the checklist and a `### Still to do` under it has no text of its own
    once the boxes are lifted, and deleting it on that reading left the
    subsection on the page under nothing."""
    kept = without_checklist("## Progress\n\n- [x] one\n\n### Still to do\n\nThe halo.\n")

    assert "### Still to do" in kept
    assert "## Progress" in kept, "the subsection was left with no heading over it"
    assert "- [x] one" not in kept


def test_a_heading_over_nothing_but_another_empty_heading_goes_too():
    """The other half of the same rule: a heading inside the subtree does not
    count as content, or `## A` stays alive on the strength of a `### B` that
    this same pass is about to delete, and prints as a heading over a blank."""
    kept = without_checklist("## A\n\n### B\n\n- [ ] gone\n\n## C\n\nReal text.\n")

    assert kept == "## C\n\nReal text."


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
        "---\ncycle: 38\nstarts_on: 2026-09-28\ngoal: Ship the core solver port\n---\n"
        "Throughflow was left out: no reviewer free.\n",
        "cycles/0038.md",
    )

    assert cycle.goal == "Ship the core solver port"
    assert cycle.body == "Throughflow was left out: no reviewer free.\n"
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
    ("jackdawrie", "a", "a" * 39, "Oxpeckerly", "yellowhammer7", "accentor9", "a-b", "a--b"),
)
def test_a_login_becomes_the_one_path_it_may_be_written_at(login: str):
    """1 to 39 of `[A-Za-z0-9-]`, no hyphen at either end — every one of these is
    a login from this corpus's own roster or the edge of the rule. `a--b` is
    admitted although GitHub itself refuses it: being narrower than the wire buys
    nothing this pattern exists for, and would refuse somebody the day GitHub
    relaxes its own rule."""
    from openproj.model import person_path

    assert person_path(login) == f"people/{login}.md"


@pytest.mark.parametrize(
    "login",
    (
        "",  # nobody
        "-ann",  # a leading hyphen
        "ann-",  # and a trailing one
        "a" * 40,  # one over the limit
        "../config/defaults",  # the reason this is a pattern and not a check
        "a/b",
        "ann.md",
        "ann name",
        ".",
        "..",
        "ann\n",  # a trailing newline is not the end of a match
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

    person = parse_person_text("---\nicon: fox\n---\n", "people/jackdawrie.md")

    assert person.login == "jackdawrie"
    assert person.icon == "fox"


def test_a_login_typed_into_the_frontmatter_is_ignored_rather_than_believed():
    """The one thing a second copy of the identity could do is disagree with the
    first, and then which record this is depends on which half of the app you
    ask. That is `_identity_problems`, two blocker rules and a special case in
    the record save, all paid for a fact the filename already carried — so here
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
    original = "---\nicon: fox\n---\n\nAnn, who works on the core solver.\n"

    patched = patch_text(original, {"icon": "owl"})

    assert patched == "---\nicon: owl\n---\n\nAnn, who works on the core solver.\n"
