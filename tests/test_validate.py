"""The contract for `validate_all`: which rule fires, on what field, with what words.

Messages are asserted literally because they are the product — they are what a
human sees in the CLI and the web view — so they are single-sourced as constants
here rather than retyped per test.

Grandfathering is the reason `Problem` carries `rule_version` at all: a rule
introduced after a record was written may only warn about it, never block it.
`test_grandfathering_*` is the load-bearing test of this module.
"""

import time
from datetime import date
from pathlib import Path

from openproj.cli import main
from openproj.model import (
    ID_PATTERN,
    KINDS,
    Config,
    Pitch,
    Problem,
    Project,
    Record,
    Task,
    cycle_of,
    load_repo,
    parse_text,
    required_at,
    validate_all,
)
from openproj.schedule import schedule

TASK_ID = "task-aaa111"
OTHER_TASK_ID = "task-ddd444"
PITCH_ID = "pitch-bbb222"
OTHER_PITCH_ID = "pitch-eee555"
PROJECT_ID = "proj-ccc333"

NEEDS_TITLE = "title must not be empty"
BAD_ID_PATTERN = "id must match " + ID_PATTERN.pattern
NEEDS_OWNER = "a ready record needs an owner"
NEEDS_REVIEWER = "a ready record needs a reviewer, or review waived"
NEEDS_EFFORT = "a ready task needs an appetite"
NEEDS_APPETITE = "a ready pitch needs an appetite"
NEEDS_START_DATE = "work in progress needs the date it started"
NEEDS_SIZE_WIP = "work in progress needs an appetite"
RETIRED_SHAPED_BY = (
    "shaped_by is no longer read: owner records who shaped a pitch and holds it — "
    "move the name there and delete this key"
)
NEEDS_SOMEBODY_READY = "a ready record needs somebody on it"
NEEDS_SOMEBODY_WIP = "work in progress needs somebody on it"
NEEDS_INDEPENDENT_REVIEWER = (
    "work in progress needs a reviewer other than its owner, or review waived"
)
NEEDS_PR = "a done record needs at least one PR"
NEEDS_END_DATE = "a done record needs the date it ended"
SHOULD_HAVE_PARENT = "a task should have a parent"
DEPENDS_ON_CYCLE = "part of a blocked-by cycle"
PARENT_CYCLE = "part of a parent cycle"


def bad_id_prefix(kind: str) -> str:
    return f"id prefix must match kind {kind}"


def missing_target(target: str) -> str:
    return f"blocked by {target}, which does not exist"


def shelved_target(target: str) -> str:
    return f"blocked by {target}, which is shelved"


def ancestor_dep(target: str) -> str:
    return f"cannot depend on {target}: it is an ancestor"


def descendant_dep(target: str) -> str:
    return f"cannot depend on {target}: it is a descendant"


def task(**overrides: object) -> Task:
    """A todo task that breaks no rule, so a test can break exactly one thing.

    Its parent is PITCH_ID, which most tests do not bother to pass alongside it:
    a parent that is absent from the repository is not itself a rule violation.

    "No rule" includes the schema_version 2 somebody-assigned rule. Without
    `assignees` here every test in this file would be asserting about one
    problem while a second sat beside it.
    """
    fields: dict[str, object] = {
        "id": TASK_ID,
        "kind": "task",
        "title": "A task",
        "parent": PITCH_ID,
        "status": "ready",
        "owner": "jackdawrie",
        "assignees": ["jackdawrie"],
        "reviewers": ["merganserly"],
        "person_weeks": 1.0,
    }
    return Task(**(fields | overrides))


def pitch(**overrides: object) -> Pitch:
    """A todo pitch that breaks no rule, including the schema_version 2 ones."""
    fields: dict[str, object] = {
        "id": PITCH_ID,
        "kind": "pitch",
        "title": "A pitch",
        "parent": None,
        "status": "ready",
        "owner": "jackdawrie",
        "assignees": ["jackdawrie"],
        "reviewers": ["merganserly"],
        "person_weeks": 2.0,
    }
    return Pitch(**(fields | overrides))


def project(**overrides: object) -> Project:
    """A wip project that breaks no rule."""
    fields: dict[str, object] = {
        "id": PROJECT_ID,
        "kind": "project",
        "title": "A project",
        "parent": None,
        "status": "in_progress",
        "owner": "jackdawrie",
        "assignees": ["jackdawrie"],
        "reviewers": ["merganserly"],
        "start_date": date(2026, 8, 3),
    }
    return Project(**(fields | overrides))


def check(
    *records: Record, config: Config | None = None, today: date | None = None
) -> list[Problem]:
    """`today` only where a test is about a date. Everywhere else it is left to
    `validate_all`'s own default, which is the real one — the fixtures below carry
    no start dates, so nothing else in this file floats with the clock."""
    return validate_all(list(records), config or Config(), None, today)


# A Monday, so a span's arithmetic is readable in the tests that assert on it:
# five working days is one calendar week from here with no weekend swallowed at
# the front. Fixed rather than `date.today()` because the rollup rule's message
# quotes the length of a scheduled span, and a rule whose words depend on which
# weekday the suite runs on is a rule nobody can pin.
PLAN_TODAY = date(2026, 8, 17)


def rolled_up(*records: Record, config: Config | None = None) -> list[Problem]:
    """`validate_all` as a whole PLAN sees it: scheduled first, spans passed in.

    `check` above is the other caller shape and the commoner one — a candidate
    record on its way to being written, judged with no schedule — and without
    spans `_rollup_problems` is simply not applied. Every test of that rule goes
    through here instead, because the two numbers it compares are the
    scheduler's: what the bet buys in calendar weeks, and how many weeks of work
    the tasks underneath actually occupy.
    """
    settings = config or Config()
    spans, _ = schedule(list(records), settings, PLAN_TODAY)
    # The same day for both halves. The scheduler's floor and the validator's
    # "this date has gone by" are one day by definition, and a helper that pinned
    # one and let the other read the clock would lay a span out from a Monday in
    # August and then judge its dates against whatever day the suite happens to
    # run on.
    return validate_all(list(records), settings, spans, PLAN_TODAY)


def only(problems: list[Problem], record_id: str, field: str | None = None) -> Problem:
    matching = [
        p for p in problems if p.record_id == record_id and (field is None or p.field == field)
    ]
    named = record_id if field is None else f"{record_id}.{field}"
    assert len(matching) == 1, f"expected exactly one problem for {named}, got {matching}"
    return matching[0]


def summary(problem: Problem) -> tuple[str, str | None, str, int]:
    return (problem.severity, problem.field, problem.message, problem.rule_version)


def summaries(problems: list[Problem]) -> set[tuple[str, str, str | None, str, int]]:
    return {(p.severity, p.record_id, p.field, p.message, p.rule_version) for p in problems}


def test_a_fully_specified_record_has_no_problems():
    """Guards the helpers: if the clean fixtures were dirty, every test below would
    be asserting about the wrong problem."""
    assert check(task(), pitch(), project()) == []


# --- rules that apply at any status -----------------------------------------


def test_a_title_must_not_be_empty():
    assert summary(only(check(task(title="")), TASK_ID)) == ("blocker", "title", NEEDS_TITLE, 1)


def test_an_id_must_match_the_pattern_and_agree_with_the_kind():
    malformed = only(check(task(id="task-zzz999")), "task-zzz999")
    assert summary(malformed) == ("blocker", "id", BAD_ID_PATTERN, 1)
    mismatched = only(check(task(id="pitch-aaa111")), "pitch-aaa111")
    assert summary(mismatched) == ("blocker", "id", bad_id_prefix("task"), 1)
    # Asked of the pattern directly, because httpx refuses to send a bare
    # newline in a URL and a proxy that does not is the whole point of the
    # anchors: written `^…$` this matches, and the id becomes a path with a
    # newline in it. `BAD_ID_PATTERN` derives from `.pattern` and cannot
    # catch a revert; this line is the one that can.
    assert not ID_PATTERN.match(TASK_ID + "\n")


def test_every_depends_on_target_must_exist():
    problem = only(check(task(depends_on=["task-fff666"])), TASK_ID)
    assert summary(problem) == ("blocker", "depends_on", missing_target("task-fff666"), 1)


def test_regression_a_record_may_not_depend_on_its_own_ancestor_or_descendant():
    """Regression: containment already implies an ordering, so a dependency along
    the parent chain is a contradiction the scheduler cannot resolve."""
    upwards = only(check(task(depends_on=[PITCH_ID]), pitch()), TASK_ID)
    assert summary(upwards) == ("blocker", "depends_on", ancestor_dep(PITCH_ID), 1)
    downwards = only(check(task(), pitch(depends_on=[TASK_ID])), PITCH_ID)
    assert summary(downwards) == ("blocker", "depends_on", descendant_dep(TASK_ID), 1)


def test_a_depends_on_cycle_is_reported_on_every_record_in_it():
    records = (task(depends_on=[OTHER_TASK_ID]), task(id=OTHER_TASK_ID, depends_on=[TASK_ID]))
    found = check(*records)
    for record_id in (TASK_ID, OTHER_TASK_ID):
        assert summary(only(found, record_id)) == ("blocker", "depends_on", DEPENDS_ON_CYCLE, 1)


def test_a_parent_chain_cycle_is_reported_on_every_record_in_it():
    records = (pitch(parent=OTHER_PITCH_ID), pitch(id=OTHER_PITCH_ID, parent=PITCH_ID))
    found = check(*records)
    for record_id in (PITCH_ID, OTHER_PITCH_ID):
        assert summary(only(found, record_id)) == ("blocker", "parent", PARENT_CYCLE, 1)


def test_a_task_without_a_parent_is_only_a_warning():
    """Orphan tasks are a fact of migration, not a defect: warn, do not block."""
    problem = only(check(task(parent=None)), TASK_ID)
    assert summary(problem) == ("warning", "parent", SHOULD_HAVE_PARENT, 1)


def test_depending_on_a_shelved_record_is_only_a_warning():
    shelved = task(id=OTHER_TASK_ID, status="shelved")
    problem = only(check(task(depends_on=[OTHER_TASK_ID]), shelved), TASK_ID)
    assert summary(problem) == ("warning", "depends_on", shelved_target(OTHER_TASK_ID), 1)


# --- rules that apply at one status -----------------------------------------


def test_a_todo_record_needs_an_owner():
    assert summary(only(check(task(owner=None)), TASK_ID)) == ("blocker", "owner", NEEDS_OWNER, 1)


def test_a_todo_record_needs_a_reviewer_unless_review_is_waived():
    problem = only(check(task(reviewers=[])), TASK_ID)
    assert summary(problem) == ("blocker", "reviewers", NEEDS_REVIEWER, 1)


def test_a_todo_record_needs_a_size():
    assert summary(only(check(task(person_weeks=None)), TASK_ID)) == (
        "blocker",
        "person_weeks",
        NEEDS_EFFORT,
        1,
    )
    assert summary(only(check(pitch(person_weeks=None)), PITCH_ID)) == (
        "blocker",
        "person_weeks",
        NEEDS_APPETITE,
        1,
    )


def test_a_file_that_still_says_shaped_by_warns_and_points_at_owner():
    """The field retired into `owner` (jcanton, 2026-08-24). Parsing is
    permissive, so the key lands in `_unread` and round-trips untouched — which
    is exactly the silence this rule exists to break: a pitch that records who
    shaped it and shows nothing is "empty looks like broken". A warning and
    never a blocker, asserted on a record created AFTER the rule's version so
    the severity cannot be grandfathering's doing."""
    text = (
        "---\nid: pitch-bbb222\nkind: pitch\ntitle: P\n"
        "created_schema_version: 9\nshaped_by: hornbillow\n---\n\nb\n"
    )
    problem = only(check(parse_text(text, f"pitches/{PITCH_ID}.md")), PITCH_ID)
    assert summary(problem) == ("warning", "shaped_by", RETIRED_SHAPED_BY, 5)


def test_a_retired_key_on_a_shelved_record_stays_unreported():
    """Shelved work is parked, not broken — the exemption every other rule gets,
    and the retired-field rule must not be the one that nags anyway."""
    text = (
        "---\nid: pitch-bbb222\nkind: pitch\ntitle: P\nstatus: shelved\n"
        "shaped_by: hornbillow\n---\n\nb\n"
    )
    assert check(parse_text(text, f"pitches/{PITCH_ID}.md")) == []


def test_a_wip_record_needs_a_start_date():
    for record in (task(status="in_progress", start_date=None), project(start_date=None)):
        problem = only(check(record), record.id)
        assert summary(problem) == ("blocker", "start_date", NEEDS_START_DATE, 1)


def test_a_start_date_that_has_drifted_into_the_past_is_a_warning():
    """The half of the rule no door can catch.

    A date typed as future becomes past by the passage of time, with nobody
    editing anything, so no refusal at any write path ever fires on it. The
    scheduler has been discarding it since it was written — the start is
    `max(floor, start_date, blocker_ready)` — and until this rule the ledger said
    nothing at all about a record whose file and whose Start column disagree.

    A warning and not a blocker precisely because nobody did it. There is no edit
    to refuse and no moment at which anybody could have been told.
    """
    for status in ("thinking", "shaping", "ready"):
        stale = task(status=status, start_date=date(2026, 8, 17))
        assert summary(only(check(stale, today=date(2026, 8, 28)), TASK_ID, "start_date")) == (
            "warning",
            "start_date",
            "the start date 2026-08-17 has passed and the work has not begun, so this is "
            "scheduled from today instead: move the date, or say the work has started",
            5,
        ), status


def test_a_start_date_still_to_come_is_what_the_field_is_for():
    """The boundary is today, and today itself is not past. A date in the future
    is an ordinary plan — somebody says when they will pick this up — and a rule
    that nagged about the day it was typed would fire on every record written
    before lunch."""
    for stated in (date(2026, 8, 28), date(2026, 9, 30)):
        soon = task(start_date=stated)
        assert [p for p in check(soon, today=date(2026, 8, 28)) if p.field == "start_date"] == []


def test_a_start_date_in_the_past_is_expected_once_the_work_has_begun():
    """Scoped to status, and it has to be. At `in_progress` a date that has gone
    by is not merely allowed, it is the correct value and the gate above demands
    the field — "I started this on Monday and it is now Wednesday" is the ordinary
    case. At `done` it is the whole span. Unscoped, this rule would nag about
    every record that is actually being worked on."""
    began = date(2026, 8, 17)
    for record in (
        task(status="in_progress", start_date=began),
        task(status="done", start_date=began, prs=["https://github.com/c2sm/x/pull/1"]),
    ):
        assert [
            p for p in check(record, today=date(2026, 8, 28)) if p.field == "start_date"
        ] == [], record.status


def test_a_start_date_on_a_rung_that_is_never_scheduled_is_not_judged_twice():
    """An issue reads no dates at all, and `unread_fields` already says so beside
    the record. A second sentence about the same key — one saying the date is not
    read, one saying it has passed — is this validator arguing with itself about a
    field nothing derives anything from."""
    text = (
        "---\nid: issue-9f2b48\nkind: issue\ntitle: I\nstatus: ready\n"
        "start_date: 2026-08-17\n---\n\nb\n"
    )
    issue = parse_text(text, "issues/issue-9f2b48.md")
    said = [summary(p) for p in check(issue, today=date(2026, 8, 28)) if p.field == "start_date"]
    assert said == [
        ("warning", "start_date", "an issue is never scheduled, so its start_date is not read", 1)
    ]


def test_a_wip_record_needs_a_size():
    """The gate stopped at `ready`, and `in_progress` is reachable without ever
    passing through it — so an unsized record could be running, and three in
    icon4py-plan were. With no default appetite behind it, such a record is not
    scheduled, weighs nothing in its pitch's progress and charges nobody's
    capacity: it is work that is happening and that the plan cannot account for.

    A container is asked for nothing, because it has nothing to be asked for:
    `project()` is in progress and holds no `person_weeks` field at all.
    """
    started = {"status": "in_progress", "start_date": date(2026, 8, 3), "person_weeks": None}
    for record, record_id in ((task(**started), TASK_ID), (pitch(**started), PITCH_ID)):
        assert summary(only(check(record), record_id, "person_weeks")) == (
            "blocker",
            "person_weeks",
            NEEDS_SIZE_WIP,
            1,
        )
    assert [p for p in check(project()) if p.field == "person_weeks"] == []


def test_a_shaping_record_is_left_unsized_on_purpose():
    """The gate deliberately does not reach down the ladder. A bet nobody has
    shaped has no appetite yet, and demanding one is demanding a guess — which is
    the whole thing this change took out of the scheduler."""
    for status in ("thinking", "shaping"):
        unsized = pitch(status=status, person_weeks=None)
        assert [p for p in check(unsized) if p.field == "person_weeks"] == [], status


def test_a_wip_record_needs_a_reviewer_who_is_not_its_owner():
    """Self-review is the same as no review, so the reviewer list must contain
    somebody else before work may be in progress."""
    wip = task(
        status="in_progress",
        start_date=date(2026, 8, 3),
        owner="jackdawrie",
        reviewers=["jackdawrie"],
    )
    problem = only(check(wip), TASK_ID)
    assert summary(problem) == ("blocker", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1)


def test_a_done_record_needs_at_least_one_pr():
    # With the end date supplied, so that the one problem reported is the one this
    # test is about: `done` gates two fields now, and `only` asserts there is
    # exactly one.
    problem = only(check(task(status="done", prs=[], end_date=date(2026, 8, 20))), TASK_ID)
    assert summary(problem) == ("blocker", "prs", NEEDS_PR, 1)


def test_a_shelved_record_has_no_requirements_at_all():
    """Shelved work is parked, not broken: nothing about it is worth reporting,
    not even the warnings that would fire on the same fields at any other status."""
    parked = task(status="shelved", parent=None, owner=None, reviewers=[], person_weeks=None)
    assert check(parked) == []


def test_review_waived_satisfies_both_the_todo_and_the_wip_reviewer_gates():
    todo = task(reviewers=[], review_waived=True)
    wip = task(
        status="in_progress",
        start_date=date(2026, 8, 3),
        owner="jackdawrie",
        reviewers=["jackdawrie"],
        review_waived=True,
    )
    assert check(todo) == []
    assert check(wip) == []


# --- grandfathering ---------------------------------------------------------


def test_grandfathering_turns_a_newer_rule_into_a_warning_on_an_older_record():
    """The whole point of rule_version: shipping the version 2 somebody-assigned
    rule must not retroactively block a corpus written at version 1. Same
    record, same missing field, severity decided by created_schema_version
    alone."""
    old = only(check(pitch(assignees=[], created_schema_version=1)), PITCH_ID)
    new = only(check(pitch(assignees=[], created_schema_version=2)), PITCH_ID)
    assert summary(old) == ("warning", "assignees", NEEDS_SOMEBODY_READY, 2)
    assert summary(new) == ("blocker", "assignees", NEEDS_SOMEBODY_READY, 2)


def test_grandfathering_does_not_soften_a_rule_older_than_the_record():
    problem = only(check(pitch(owner=None, created_schema_version=2)), PITCH_ID)
    assert summary(problem) == ("blocker", "owner", NEEDS_OWNER, 1)


# --- what contains what, and what is bet ------------------------------------


def test_a_parent_of_the_wrong_kind_is_named_as_such():
    """The levels the spec claimed from its first day and nothing checked."""
    records = [
        Project(id="proj-000001", kind="project", title="P"),
        Pitch(id="pitch-000001", kind="pitch", title="Q", parent="proj-000001"),
        Task(id="task-000001", kind="task", title="T", parent="pitch-000001"),
        Task(
            id="task-000002", kind="task", title="U", parent="task-000001", created_schema_version=4
        ),
    ]
    problem = only(validate_all(records, Config()), "task-000002", field="parent")
    assert summary(problem) == (
        "blocker",
        "parent",
        "a task belongs to a pitch or a project, not to a task",
        4,
    )

    # And with its article right when the wrong parent's kind starts with a
    # vowel — reachable since `by_id` is every record, so a task hand-filed
    # under an issue reaches this sentence and used to read "a issue".
    filed = [
        parse_text(
            "---\nid: issue-000001\nkind: issue\ntitle: Broken\nstatus: ready\n---\n\nx\n",
            "issues/issue-000001.md",
        ),
        Task(
            id="task-000003",
            kind="task",
            title="V",
            parent="issue-000001",
            created_schema_version=4,
        ),
    ]
    problem = only(validate_all(filed, Config()), "task-000003", field="parent")
    assert problem.message == "a task belongs to a pitch or a project, not to an issue"


def test_a_task_may_hang_straight_off_a_project():
    """Work nobody pitched still belongs somewhere. The first real cycle imported
    had two of them — reported at the review, never bet — and the alternative was
    a pitch invented to hold them, which puts a bet in the corpus that no betting
    table ever made. A plan that lies about what was bet is worse than a tree
    that is two levels deep in places."""
    records = [
        Project(id="proj-000001", kind="project", title="P"),
        Task(
            id="task-000001", kind="task", title="T", parent="proj-000001", created_schema_version=4
        ),
    ]

    assert not [
        p
        for p in validate_all(records, Config())
        if p.record_id == "task-000001" and p.field == "parent"
    ]


def test_a_project_belongs_to_nothing():
    records = [
        Project(id="proj-000001", kind="project", title="P"),
        Project(
            id="proj-000002",
            kind="project",
            title="Q",
            parent="proj-000001",
            created_schema_version=4,
        ),
    ]
    problem = only(validate_all(records, Config()), "proj-000002", field="parent")
    # A project belongs to a PRODUCT now, and to nothing else — the message is
    # built from `PARENT_KINDS`, which is built from the ladder, so it followed
    # the new rung without being edited.
    assert problem.message == "a project belongs to a product, not to a project"


def test_a_pitch_under_a_project_and_a_task_under_a_pitch_are_the_shape():
    records = [
        Project(id="proj-000001", kind="project", title="P"),
        Pitch(id="pitch-000001", kind="pitch", title="Q", parent="proj-000001"),
        Task(id="task-000001", kind="task", title="T", parent="pitch-000001"),
    ]
    assert [p for p in validate_all(records, Config()) if p.field == "parent"] == []


def test_a_chore_nobody_pitched_keeps_its_own_cycle_and_a_parented_task_does_not():
    """A bet is made on a pitch, or on a task nobody pitched. Both belong on a
    betting table; a task inside a pitch came with the pitch, and a second cycle
    number on it is one fact in two files."""
    dated = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", cycle=36),
        Task(
            id="task-000001",
            kind="task",
            title="T",
            parent="pitch-000001",
            cycle=36,
            created_schema_version=4,
        ),
        Task(id="task-000002", kind="task", title="Chore", cycle=36),
    ]
    problems = [p for p in validate_all(records, dated) if p.field == "cycle"]

    assert [p.record_id for p in problems] == ["task-000001"]
    assert problems[0].severity == "warning", "it is ignored, not refused"
    assert cycle_of(records[1], {e.id: e for e in records}) == 36, "inherited from its pitch"
    assert cycle_of(records[2], {e.id: e for e in records}) == 36, "its own"


def test_a_project_is_not_bet_because_it_holds_bets():
    dated = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    records = [Project(id="proj-000001", kind="project", title="P", cycle=36)]
    problem = only(validate_all(records, dated), "proj-000001", field="cycle")
    assert problem.message.startswith("a project is not bet")
    assert cycle_of(records[0], {"proj-000001": records[0]}) is None


OVER_THE_BOX = (
    "its tasks need {} weeks with the people on them, more than the {} the bet buys at {} — "
    "cut scope, re-bet it, or put more people on it"
)


def test_tasks_that_do_not_fit_in_the_weeks_the_bet_bought_say_so():
    """The appetite is the box and the tasks are what somebody proposes to put in
    it. Nothing compared the two, so a six-week bet holding seven and a half
    weeks of tasks read as a six-week bet on every page.

    The design's own worked example, because it is the case the person-week sum
    could not see: eight person-weeks with two people on them buy four calendar
    weeks, and four and a half person-weeks of tasks sit comfortably inside eight
    — but not inside four, once both tasks are on the same person and have to
    queue. The old arithmetic said this pitch was fine. 4.6 rather than the
    design's 4.5 because `_working_days` buys a whole third day for half a week,
    which is the scheduler's rounding and not a second opinion about the size.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=8.0,
            assignees=["jackdawrie", "merganserly"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=4.0,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000002",
            kind="task",
            title="B",
            parent="pitch-000001",
            person_weeks=0.5,
            assignees=["jackdawrie"],
        ),
    ]
    problem = only(rolled_up(*records), "pitch-000001", field="person_weeks")
    assert problem.severity == "warning", "every remedy is a decision for a person"
    assert problem.message == OVER_THE_BOX.format("4.6", "4.0", 2)


def test_the_same_tasks_on_different_people_fit_and_say_nothing():
    """The span is why the sum went. Four weeks and half a week are four and a
    half of calendar if one person holds both and four if they run side by side,
    and the scheduler already knows which — `_place` books workers, so a
    contended person serialises their own work and an uncontended pair does not.
    A sum reports four and a half in both cases and is wrong in one of them.

    Same three records as the test above with one name changed, which is the
    whole demonstration.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=8.0,
            assignees=["jackdawrie", "merganserly"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=4.0,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000002",
            kind="task",
            title="B",
            parent="pitch-000001",
            person_weeks=0.5,
            assignees=["merganserly"],
        ),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_a_gap_between_the_tasks_is_not_work_and_is_not_warned_about():
    """The contents is what the tasks occupy, not the stretch that encloses them.

    This was `max(child.end) - min(child.start)`, so a task somebody dated to
    November put every week between August and November inside the bet. The
    corpus has one — `pitch-7b3e94`, whose second task waits for the plant
    shutdown — and it was warned at twenty weeks against a three-week box, of
    which fourteen were a gap. What makes that worse than a wrong number is the
    sentence attached to it: cut scope, re-bet it, or put more people on it are
    the three remedies, and none of them shortens a wait.

    Two people, so nothing queues and the whole distance is the stated date. The
    bet still buys 2.0 and the tasks still hold 2.0, which is the `=` row.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=4.0,
            assignees=["jackdawrie", "merganserly"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=1.0,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000002",
            kind="task",
            title="B",
            parent="pitch-000001",
            person_weeks=1.0,
            assignees=["merganserly"],
            start_date=date(2026, 11, 2),
        ),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_tasks_that_fit_inside_the_bet_say_nothing():
    """Under the appetite is the normal state of a pitch whose tasks are still
    being written, and saying so on every one of them is noise."""
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=6.0),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=4.0),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_a_pitch_nobody_has_bet_on_is_not_accused_of_exceeding_a_bet():
    """No appetite is no box, and a box nobody drew cannot be overflowed. The
    span still has a length — its tasks are scheduled — so the guard is
    `budget_weeks`, which is None for a pitch with no `person_weeks` of its own
    and for every container, and not the presence of dates."""
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Q"),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=9.0),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_a_shelved_task_is_not_counted_against_its_pitchs_appetite():
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=4.0),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=4.0),
        Task(
            id="task-000002",
            kind="task",
            title="B",
            parent="pitch-000001",
            person_weeks=4.0,
            status="shelved",
        ),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_a_task_nobody_sized_is_not_counted_at_a_number_nobody_typed():
    """Four unsized tasks under a one-week bet summed to `4 ×
    default_task_effort = 2` weeks and told somebody to cut scope or re-bet —
    an instruction built entirely out of a config default. The docstring said
    "only stated sizes are compared" the whole time; this holds it to that on
    the children, where it was false.

    It survives the move to spans by a different route, and that is the point of
    keeping it: an unsized record is scheduled nowhere at all, so it contributes
    no dates to roll up, and there is no filter left for anybody to forget.
    """
    records = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=1.0),
        *[
            Task(id=f"task-00000{n}", kind="task", title="T", parent="pitch-000001")
            for n in range(1, 5)
        ],
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_unsized_tasks_drop_out_of_the_rollup_and_the_sized_ones_still_warn():
    """When only some children are sized, the sized ones alone overrunning the
    box is still a statement somebody made, so the warning fires on what has
    dates — and the unsized ones can only make it worse, never better, so firing
    on the short answer is the conservative one.

    The message no longer counts anything, which is the visible change here. It
    used to say "its 2 sized tasks alone add up to 5 weeks … and the 1 without a
    size can only add to that", because a sum has to confess what it left out of
    itself. A span does not: it is the length of the work that is actually
    placed, and what is missing from it is missing from the plan rather than from
    the arithmetic. Naming the gap is the table cell's job — the fourth state,
    muted rather than good — and it is not this sentence's.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=4.0,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=3.0,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000002",
            kind="task",
            title="B",
            parent="pitch-000001",
            person_weeks=2.0,
            assignees=["jackdawrie"],
        ),
        Task(id="task-000003", kind="task", title="C", parent="pitch-000001"),
    ]
    said = [p for p in rolled_up(*records) if p.field == "person_weeks"]
    assert [p.message for p in said] == [OVER_THE_BOX.format("5.0", "4.0", 1)]


def test_a_bet_its_tasks_exactly_fill_is_level_with_the_box_and_says_nothing():
    """The `=` row of the design's own table, which used to be unreachable.

    `working_days_after` lays 2.5 weeks out as `ceil(12.5)` = thirteen working
    days and `_occupied_weeks` reads them back as 2.6, so the contents were always
    the CEILING of the box: equal only where the size was a multiple of a fifth
    of a week, larger everywhere else. This rule fires on strict `>`, so a pitch
    bet at 2.5 holding one task bet at 2.5 on the same person — the tasks filling
    the box exactly — was told it needed 2.6 more than the 2.5 it had. Any
    fractional availability puts every bet in that position, so this was not an
    edge case but the normal one.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=2.5,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=2.5,
            assignees=["jackdawrie"],
        ),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


def test_the_sentence_quotes_the_box_after_the_same_rounding_it_compares_with():
    """A number in the message that the comparison did not use is a message nobody
    can check. The bet is 2.5 person-weeks on one person, which the scheduler will
    lay out over thirteen working days — so the box this rule holds the tasks
    against is 2.6, and 2.6 is what the sentence has to say it is. It said 2.5,
    which is the stated appetite rather than the box, and a reader adding it up
    found a warning that fired on numbers that were not over.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=2.5,
            assignees=["jackdawrie"],
        ),
        Task(
            id="task-000001",
            kind="task",
            title="A",
            parent="pitch-000001",
            person_weeks=3.0,
            assignees=["jackdawrie"],
        ),
    ]
    problem = only(rolled_up(*records), "pitch-000001", field="person_weeks")
    assert problem.message == OVER_THE_BOX.format("3.0", "2.6", 1)


def test_a_pitch_whose_tasks_are_all_unsized_is_not_compared_against_its_own_placement():
    """It was the tasks that had to fit in the box, and here it was the pitch itself.

    A container is a container by the plan and not by which of its children came
    back with a span, and that distinction only appeared when the default
    appetite went: a pitch whose every child is unsized had no child spans to
    roll up, fell through to the leaf path and was PLACED — so `budget_weeks` and
    `elapsed_weeks` both described the pitch's own placement, the second being
    the ceiling of the first, and this rule told somebody to cut scope on a bet
    holding no measured work at all.
    """
    records = [
        Pitch(
            id="pitch-000001",
            kind="pitch",
            title="Q",
            person_weeks=2.5,
            assignees=["jackdawrie"],
        ),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001"),
        Task(id="task-000002", kind="task", title="B", parent="pitch-000001"),
    ]
    assert [p for p in rolled_up(*records) if p.field == "person_weeks"] == []


# --- the seed corpus --------------------------------------------------------


def test_the_seed_corpus_reports_exactly_this_problem_set(seed_root: Path):
    """Integration over the real 30 files. The set is exhaustive on purpose: a new
    rule that fires on the committed corpus has to be argued for here first.

    The retired `shaped_by` reports nothing here, and that absence is asserted
    by the set being exhaustive: the corpus dropped the key when the field
    retired into `owner`, and the retired-key warning fires only on a file that
    still carries it (its own test parses one).

    The version-4 warnings are the argument for those rules, made against real
    files rather than invented ones. Every one of them is a thing the corpus
    already does and nothing had ever said: nine tasks carrying a `cycle` that
    belongs to the pitch they are part of, one task hung straight off a project —
    which is allowed now, and was the shape the first real import needed — and
    TWO pitches whose tasks, as they are actually staffed, need more calendar than
    the bets bought. It said one, and one was true while that comparison was a sum
    of person-weeks against an undivided appetite; moving it to calendar-against-
    calendar found `pitch-7b3e94` as well, whose two tasks fit its bet as effort
    and cannot fit it as time. All warnings: the corpus is
    created_schema_version 2 and these rules are 4, so nothing written before them
    breaks.

    The corpus grew from 17 files to 30 on 2026-08-23, and this set grew by
    exactly four entries — all four on records the growth added, none on a record
    that was already here. That second half is the load-bearing one: growing a
    corpus must not change what the checker says about the files already in it,
    and this assertion is where that would be caught. Every added entry is a
    document deliberately written wrong; see the comments beside them.
    """
    records, config, _ = load_repo(seed_root)
    assert len(records) == 30
    # Scheduled, because one rule reads spans — see `rolled_up`. At `PLAN_TODAY`
    # rather than the real one, and that is now the whole reason the numbers below
    # can be written down at all. This comment used to claim the rollup entries
    # came out identical for every "today" from 2025 to 2030, on the grounds that
    # their children carry start dates of their own; that was true of the enclosing
    # span and is false of the days the children occupy. Four of `pitch-5e7b1c`'s
    # five tasks are `ready` with no start date, so the chain they form begins on
    # the floor and moves with it, while the fifth is `in_progress` from a stated
    # 13 August and does not — and what the union counts from the chain is only
    # its tail past that fixed stretch, which is two working days longer from the
    # 17th than from the 13th. So the same corpus reads 5.2 at one and 5.6 at the
    # other, and this set is a snapshot only because the day is named here.
    # `pitch-7b3e94`'s 6.0 is steadier — both its tasks are held by dates rather
    # than by the floor, one behind `pitch-6f2d18`'s in-progress children and one
    # by its own stated 2026-12-21 — but steadier is not still, and the argument
    # for pinning the day is the pair of them and not either alone.
    spans, _ = schedule(records, config, PLAN_TODAY)
    inherits = (
        "the bet is on the pitch, so this task takes its cycle from {}; the number here is ignored"
    )
    # `PLAN_TODAY` here too, and now it is load-bearing rather than tidy: one rule
    # compares a stated start date against the day the plan is judged around, and
    # this corpus holds a ready task dated 2026-12-21. Left to read the clock,
    # this frozen set would acquire an entry on the day that date goes by — a
    # snapshot that changes with nobody editing anything, which is the one thing a
    # snapshot may not do.
    assert summaries(validate_all(records, config, spans, PLAN_TODAY)) == {
        # Nine records at ready or in_progress with nobody assigned, which is the
        # argument for that rule made against real files: an owner answers for a
        # bet and assignees are who is doing it, and the scheduler prices a record
        # by the people on it — so each of these is forecast as though a whole
        # person were on it while naming nobody. All warnings, because the corpus
        # is created_schema_version 1 and the rule is 2.
        ("warning", "pitch-1b3f9a", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "proj-7e57a0", "assignees", NEEDS_SOMEBODY_WIP, 2),
        ("warning", "task-0e4b7a", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "task-2b6c94", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "task-53a9f0", "assignees", NEEDS_SOMEBODY_WIP, 2),
        ("warning", "task-58d7c6", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "task-5a4e39", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "task-5c1d84", "assignees", NEEDS_SOMEBODY_READY, 2),
        ("warning", "task-5f062b", "assignees", NEEDS_SOMEBODY_READY, 2),
        # wip without a start date
        ("blocker", "proj-7e57a0", "start_date", NEEDS_START_DATE, 1),
        ("blocker", "pitch-48ea9e", "start_date", NEEDS_START_DATE, 1),
        # wip with an empty reviewer list and nothing underneath carrying one.
        # `pitch-5e7b1c` was here too and is not any more: its own list is empty,
        # but its tasks name ibisbillie, mudlarkish and accentor9, and a pitch whose
        # tasks are reviewed is reviewed. That is the rule doing what it was added
        # for, on the corpus this one was converted from.
        ("blocker", "pitch-48ea9e", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1),
        # done, but no PR links were recorded
        ("blocker", "pitch-2a7f3e", "prs", NEEDS_PR, 1),
        ("blocker", "pitch-3c9a41", "prs", NEEDS_PR, 1),
        ("blocker", "task-31f6c4", "prs", NEEDS_PR, 1),
        ("blocker", "task-3a52d8", "prs", NEEDS_PR, 1),
        ("blocker", "task-3e07b2", "prs", NEEDS_PR, 1),
        # v5: done, and no record of the day it ended. The SAME five records, and
        # that is the whole demonstration of what grandfathering is for. These
        # files are migrated history — three of them say `start_date: null` and
        # one says it in as many words, `# was fabricated during migration;
        # unknown` — so there is no end date anybody can supply, and no way for
        # the file to say so. The rule is 5 and this corpus is
        # created_schema_version 2, so what they get is a warning; a record
        # created from now on is created at 5 and is blocked.
        #
        # `seed/` went the other way and is the other half of the argument: both
        # of ITS done tasks carry real start dates, so both were given real end
        # dates rather than being left to the demotion. A demo that leans on
        # grandfathering is a demo teaching people to ignore the rule.
        ("warning", "pitch-2a7f3e", "end_date", NEEDS_END_DATE, 5),
        ("warning", "pitch-3c9a41", "end_date", NEEDS_END_DATE, 5),
        ("warning", "task-31f6c4", "end_date", NEEDS_END_DATE, 5),
        ("warning", "task-3a52d8", "end_date", NEEDS_END_DATE, 5),
        ("warning", "task-3e07b2", "end_date", NEEDS_END_DATE, 5),
        # v4: a bet is made on a pitch, and these tasks are part of one
        ("warning", "task-2b6c94", "cycle", inherits.format("pitch-2a7f3e"), 4),
        ("warning", "task-31f6c4", "cycle", inherits.format("pitch-3c9a41"), 4),
        ("warning", "task-3a52d8", "cycle", inherits.format("pitch-3c9a41"), 4),
        ("warning", "task-3e07b2", "cycle", inherits.format("pitch-3c9a41"), 4),
        ("warning", "task-53a9f0", "cycle", inherits.format("pitch-5e7b1c"), 4),
        ("warning", "task-58d7c6", "cycle", inherits.format("pitch-5e7b1c"), 4),
        ("warning", "task-5a4e39", "cycle", inherits.format("pitch-5e7b1c"), 4),
        ("warning", "task-5c1d84", "cycle", inherits.format("pitch-5e7b1c"), 4),
        ("warning", "task-5f062b", "cycle", inherits.format("pitch-5e7b1c"), 4),
        # v4: the migration hung this one straight off the project
        # v4: two pitches whose tasks, as actually staffed, do not fit in the
        # calendar weeks their bets bought. `pitch-5e7b1c` was the only one of
        # these before, on the person-week sum — "its 5 tasks add up to 8.1
        # weeks, more than the 4 it was bet at" — and `pitch-7b3e94` is the move
        # to the calendar finding what that sum could not: 1.0 and 2.0 against a
        # bet of 3.0 is a perfect fit as effort, and six weeks against three as
        # time, because Whimbrel and Stonechat are each half-available and the
        # second task waits for the first. Both are real shapes in the corpus
        # rather than files written wrong on purpose, which is the argument for
        # the rule.
        #
        # `pitch-6f2d18` was here as a third and is not any more, and the reason
        # is the union rather than a softened rule. Its two tasks overlap on
        # purpose — cycle 37's own record says in as many words that the lowering
        # and the benchmark were left running alongside rather than queued behind
        # each other, both under Redpoll — so the days they share are counted
        # once: 13 August to 28 August is 12 working days, where adding their
        # placements up gives 15. Twelve against the 14 that 2.0 person-weeks buys
        # Redpoll at a half and Chiffchaff at a quarter is a bet that fits, and a
        # sum of 15 was a bet that did not. This entry going is the union doing
        # the thing it was added for.
        (
            "warning",
            "pitch-5e7b1c",
            "person_weeks",
            OVER_THE_BOX.format("5.6", "2.0", 2),
            4,
        ),
        (
            "warning",
            "pitch-7b3e94",
            "person_weeks",
            OVER_THE_BOX.format("6.0", "3.0", 2),
            4,
        ),
        # `prod-7c2b81` carries `person_weeks`, `depends_on` and `owner` in its
        # frontmatter on purpose, and its body says so and says not to fix it. It
        # is the only file in either corpus these three `unread_fields` rules have
        # to fire on — before it they were exercised only by records the tests
        # built in memory, which proves the rule and not the reading of a file.
        # Two blockers and one warning, and that split is the point: an appetite
        # or a dependency on a container is a claim about work that is not there,
        # while an owner on it is only a name nobody reads.
        (
            "blocker",
            "prod-7c2b81",
            "depends_on",
            "a product waits on nothing: its projects, pitches and tasks do",
            1,
        ),
        ("blocker", "prod-7c2b81", "person_weeks", "a product carries no appetite", 1),
        (
            "warning",
            "prod-7c2b81",
            "owner",
            "a product is a grouping and is never scheduled, so its owner is not read",
            1,
        ),
        # `note-b14d6a` points `became` at a pitch nobody wrote a file for, and its
        # body explains that the link is broken and is being left broken: the idea
        # was re-shaped twice and neither board row became a record. So the note
        # falls back to `thinking` rather than claiming a promotion nothing opens,
        # and the missing id is reported beside it. Do not "fix" the note.
        ("warning", "note-b14d6a", "became", "became pitch-000000, which is missing", 1),
    }


def test_check_over_the_seed_corpus_prints_exactly_the_validated_problems(seed_root: Path, capsys):
    """The seed-check pin, CLI half. The snapshot test above pins WHAT
    `validate_all` says about the real corpus, entry by entry; this pins that
    `openproj check` relays all of it — every line, the sort, the count, the
    exit code — and adds nothing. Together they freeze the command's output
    over `seed/`, which is what has to survive the `unread_fields` re-cut and
    the per-rung vocabulary unchanged: a problem this pair does not notice
    appearing or vanishing is a validation change that got past the refactor.
    """
    records, config, unreadable = load_repo(seed_root)
    # The real today, and not `PLAN_TODAY`, because `_check` schedules against
    # `date.today()` and this test's whole claim is that the command relays what
    # the validator says — computed the way the command computes it, or the pin
    # is against a second implementation of the command rather than against it.
    spans, _ = schedule(records, config, date.today())
    problems = sorted(
        validate_all(records, config, spans),
        key=lambda p: (p.severity, p.record_id, p.field or ""),
    )
    blockers = [p for p in problems if p.severity == "blocker"]

    assert main(["check", str(seed_root)]) == 1
    lines = capsys.readouterr().out.splitlines()

    expected = [
        f"blocker: {one.path}: this file is not a record, so nothing in it is in the plan: "
        f"{one.why}"
        for one in unreadable
    ]
    expected += [f"{p.severity}: {p.record_id}: {p.field}: {p.message}" for p in problems]
    expected.append(
        f"{len(blockers) + len(unreadable)} blockers, {len(problems) - len(blockers)} warnings"
    )
    assert lines == expected


# --- the roster -------------------------------------------------------------


def test_a_name_nobody_recognises_is_a_warning_not_a_refusal():
    """The roster is a hand-maintained file, so it is always slightly behind
    reality. Blocking on it would make a new colleague unassignable on their first
    day; warning catches the case that actually happens, which is a typo quietly
    creating a task nobody reviews."""
    roster = Config(known_people=["jackdawrie", "merganserly"])

    problem = only(check(task(owner="jackdawire"), config=roster), TASK_ID)
    assert summary(problem) == (
        "warning",
        "owner",
        "jackdawire is not in config/people.yaml",
        1,
    )


def test_a_roster_that_does_not_exist_checks_nothing():
    """An empty roster means the check is off. A tracker that refuses a name
    because nobody has written the roster yet is a tracker nobody finishes setting
    up."""
    assert check(task(owner="anybody-at-all"), config=Config()) == []


def test_every_person_field_is_checked_against_the_roster():
    roster = Config(known_people=["jackdawrie"])
    problems = check(
        task(owner="jackdawrie", reviewers=["ghost"], assignees=["phantom"]), config=roster
    )

    assert {(p.field, p.message.split()[0]) for p in problems} == {
        ("reviewers", "ghost"),
        ("assignees", "phantom"),
    }


def test_a_word_nobody_defined_is_a_problem_and_not_a_crash():
    """The invariant this restores: parse permissively, validate strictly.

    A pitch written before a vocabulary change holds `status: wip`, and YAML hands
    back `priority: 1` as an int. Refusing either at parse time took every page
    down with a 500 over one stale record — which is precisely the failure the
    permissive-parse rule exists to prevent. One bad file is one problem beside one
    record.
    """
    stale = parse_text(
        "---\nid: pitch-bbb222\nkind: pitch\ntitle: T\nstatus: wip\npriority: 1\n---\n\nB.\n",
        "pitches/pitch-bbb222.md",
    )

    assert (stale.status, stale.priority) == ("wip", "1")
    fields = {(p.field, p.severity) for p in check(stale)}
    assert ("status", "blocker") in fields
    assert ("priority", "blocker") in fields


def test_each_rung_accepts_exactly_its_own_status_words():
    """The vocabulary is a per-rung fact now, not one module-level ladder.

    Derived from `KINDS` rather than written out per kind, so a rung added
    later — an issue, whose ladder has no `shaping` — is held to its own words
    by this same loop on the day it lands. Only `p.field == "status"` is
    filtered for, because a valid word can still gate other fields (`ready`
    demands an owner) and those problems are some other test's business.
    """
    for rung in KINDS:
        blank = rung.model(id=f"{rung.prefix}-000000", kind=rung.name, title="T")
        for word in rung.statuses:
            said = check(blank.model_copy(update={"status": word}))
            assert not [p for p in said if p.field == "status"], (rung.name, word)
        if rung.statuses:
            # The article restated rather than imported: `_an` is what builds
            # the message, and a test that asks `_an` what `_an` said cannot
            # notice it breaking. "for an issue", because the same word can be
            # a status two rungs up and a sentence that denies it outright
            # argues with the page the reader just came from.
            article = "an" if rung.name[:1] in "aeiou" else "a"
            vocab = only(
                check(blank.model_copy(update={"status": "wip"})), blank.id, field="status"
            )
            assert summary(vocab) == (
                "blocker",
                "status",
                f"'wip' is not a status for {article} {rung.name}: "
                f"expected one of {', '.join(rung.statuses)}",
                1,
            ), rung.name


def test_a_kind_that_reads_no_status_has_no_vocabulary_to_violate():
    """A product's status is unread, so no word on it is a vocabulary blocker —
    the "not read" warning from `unread_fields` is the whole report, whether the
    word is on the work ladder or on no ladder at all. `shelved` is the case
    that changed: it used to buy the file a silent skip through the parked
    exemption, using a word a product does not even read, and now the exemption
    is structural (`_parked`) a product cannot park and the warning appears.
    """
    for word in ("shelved", "banana"):
        written = parse_text(
            f"---\nid: prod-000001\nkind: product\ntitle: hearth\nstatus: {word}\n---\n\nx\n",
            "products/prod-000001.md",
        )
        said = validate_all([written], Config())
        assert [(p.severity, p.field) for p in said] == [("warning", "status")], (word, said)
        assert "not read" in said[0].message


def test_a_stale_vocabulary_still_schedules_and_renders():
    """The page has to survive the record. A tracker that shows nothing because one
    file is old is worse than one that shows the file and says what is wrong."""
    from datetime import date

    from openproj.index import build_index

    # Sized, because the claim is about the two stale WORDS and nothing else: a
    # record with no appetite gets no span whatever its status says, so leaving
    # `person_weeks` out would have this test passing or failing on a rule it is
    # not about.
    stale = parse_text(
        "---\nid: task-aaa111\nkind: task\ntitle: T\nstatus: wip\npriority: 1\n"
        "person_weeks: 1\n---\n\nB.\n",
        "tasks/task-aaa111.md",
    )
    index = build_index([stale], Config(), date(2026, 8, 17))

    assert "task-aaa111" in index.spans
    assert any(p.field == "status" for p in index.problems)


def test_a_cycle_nobody_dated_is_reported_rather_than_ignored():
    """`_overrun` looks the window up with `.get`, so an undated number does not
    raise — it returns None, and the record silently stops being checked for
    overrun. A typo therefore reads as "on time" forever, which is the one
    reading nobody would question."""
    config = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    records = [task(cycle=99), task(id="task-000002", cycle=36)]

    problems = validate_all(records, config)
    reported = [p for p in problems if p.field == "cycle"]

    assert len(reported) == 1
    assert reported[0].record_id == records[0].id
    assert reported[0].severity == "warning"
    assert "no dates" in reported[0].message


def test_no_message_names_a_field_the_way_the_file_spells_it():
    """A message is a sentence somebody reads; `Problem.field` is the identifier.

    `work in progress needs a reviewer other than its owner, or review_waived` was
    printed two inches under a checkbox the same page labels "Review waived" — one
    field, two names, on one screen, which is what F11 was about. The identifier is
    not lost by fixing that: it stays on `Problem.field`, which is how the page
    finds the control to mark and how a caller filters.

    The forbidden set is derived from the models rather than listed, so a tenth
    field added tomorrow is covered without anybody remembering this test. Only
    snake_case names are checked: a one-word field like `owner` or `title` is
    already the word a reader uses, so forbidding it would forbid English.
    """
    spelled_in_the_file = {
        name for model in (Project, Pitch, Task) for name in model.model_fields if "_" in name
    }
    assert "review_waived" in spelled_in_the_file, "the derivation still finds the fields"

    # Every gate, tripped at once: each status, each kind, a missing dependency, a
    # shelved one, and a pair that depend on each other.
    loop_a, loop_b, SHELVED_ID = "task-f00001", "task-f00002", "task-f00003"
    records = [
        pitch(status="ready", owner=None, reviewers=[], person_weeks=None),
        task(status="in_progress", start_date=None, reviewers=["jackdawrie"], owner="jackdawrie"),
        project(status="ready", owner=None, reviewers=[]),
        Task(
            id=OTHER_TASK_ID,
            kind="task",
            title="T",
            status="ready",
            owner="jackdawrie",
            reviewers=["merganserly"],
            person_weeks=None,
            depends_on=["task-999999", SHELVED_ID],
        ),
        Task(id=SHELVED_ID, kind="task", title="D", status="shelved", owner="jackdawrie"),
        Task(id=loop_a, kind="task", title="A", status="shaping", depends_on=[loop_b]),
        Task(id=loop_b, kind="task", title="B", status="shaping", depends_on=[loop_a]),
    ]
    problems = check(*records)
    assert len(problems) >= 9, f"the gates did not all fire: {[p.message for p in problems]}"

    leaked = sorted(
        (p.field, p.message) for p in problems for name in spelled_in_the_file if name in p.message
    )
    assert leaked == [], f"a rule spelled a field the file's way: {leaked}"


# --------------------------------------------------------------------------- #
# Reviewers, counted from the work underneath
# --------------------------------------------------------------------------- #


def test_a_pitch_whose_tasks_are_reviewed_is_reviewed():
    """jcanton, 2026-08-19, using it: a pitch with reviewed tasks under it was
    still asked to name a reviewer of its own.

    It is asking for a second copy of a fact that is already written one level
    below — and the copy goes stale the first time a task changes hands. The work
    being reviewed IS the tasks.
    """
    held = check(
        pitch(reviewers=[]),
        task(reviewers=["merganserly"]),
    )

    assert [p for p in held if p.record_id == PITCH_ID and p.field == "reviewers"] == []


def test_a_pitch_with_nothing_under_it_still_needs_a_reviewer():
    """The rule inherits, it does not excuse: a pitch nobody has broken into tasks
    has no work under it to be reviewed, so the question stands."""
    problem = only(check(pitch(reviewers=[])), PITCH_ID, field="reviewers")

    assert problem.message == NEEDS_REVIEWER


def test_a_pitch_whose_tasks_name_nobody_still_needs_a_reviewer():
    """Two tasks that name nobody are not a reviewer between them."""
    problem = only(
        check(pitch(reviewers=[]), task(reviewers=[], review_waived=True)),
        PITCH_ID,
        field="reviewers",
    )

    assert problem.message == NEEDS_REVIEWER


def test_a_shelved_task_reviews_nothing():
    """Parked work is not work anybody is reviewing, and `validate_all` already
    leaves shelved children out of the map this walks."""
    problem = only(
        check(pitch(reviewers=[]), task(reviewers=["merganserly"], status="shelved")),
        PITCH_ID,
        field="reviewers",
    )

    assert problem.message == NEEDS_REVIEWER


def test_a_project_inherits_through_its_pitches():
    """Walked rather than read one level deep: a project holds pitches, and the
    people reviewing the tasks under those pitches are reviewing the project's
    work too."""
    held = check(
        project(reviewers=[], status="ready", person_weeks=None),
        pitch(parent=PROJECT_ID, reviewers=[]),
        task(reviewers=["merganserly"]),
    )

    assert [p for p in held if p.field == "reviewers"] == []


def test_in_progress_wants_somebody_other_than_the_owner_from_underneath_too():
    """The second reviewer rule reads the same set. A pitch in progress whose only
    task is reviewed by the pitch's own owner is a pitch nobody else is
    reviewing, which is the thing that rule is about."""
    problem = only(
        check(
            pitch(reviewers=[], status="in_progress", start_date=date(2026, 8, 3)),
            task(reviewers=["jackdawrie"], owner="jackdawrie"),
        ),
        PITCH_ID,
        field="reviewers",
    )

    assert "other than its owner" in problem.message


def test_a_parent_cycle_does_not_send_the_reviewer_walk_round_for_ever():
    """The walk that reads reviewers off the work underneath had no memory of
    where it had been, and a plan is allowed to contain a parent cycle — this
    tool reports one as a blocker rather than refusing to load the plan, which is
    the whole reason `test_a_parent_chain_cycle_is_reported_on_every_record_in_it`
    above has a corpus to run on.

    On that corpus the walk went round for ever, appending a reviewer per pass:
    an infinite loop that also grows. It took a laptop down before any test
    noticed, because the suite it was in simply never finished — which is what
    this bound is for. A test that hangs reports nothing; a test that fails names
    the thing.
    """
    records = (pitch(parent=OTHER_PITCH_ID), pitch(id=OTHER_PITCH_ID, parent=PITCH_ID))

    started = time.monotonic()
    found = check(*records)
    took = time.monotonic() - started

    assert took < 5, f"the validator took {took:.1f}s over a two-record cycle"
    # And it still says the thing that is actually wrong.
    assert {p.field for p in found} == {"parent"}


def test_a_parent_cycle_does_not_send_the_delete_walk_round_for_ever():
    """The same lesson, asked of the second walk to be written over that map.

    `under` is what a delete cascades along, so the loop this bound is for would
    now be reached by pressing a button rather than by loading a page — and it
    would be reached while building the list somebody is about to authorise.
    """
    from openproj.model import under

    ring = {PITCH_ID: [OTHER_PITCH_ID], OTHER_PITCH_ID: [PITCH_ID]}

    started = time.monotonic()
    found = under(PITCH_ID, ring)
    took = time.monotonic() - started

    assert took < 5, f"the walk took {took:.1f}s over a two-record cycle"
    assert found == [OTHER_PITCH_ID], "a record must not be filed under itself"


def test_a_todo_record_needs_somebody_on_it():
    """An owner answers for the bet; assignees are who is doing the work.

    Not the same question, and the scheduler already reads them as different
    things: it prices a record by the people on it, so a bet with an owner and
    nobody assigned is one that has been accepted and staffed with nobody — and it
    is then scheduled as if a full person were on it. jcanton, 2026-08-22.
    """
    problem = only(check(task(assignees=[], created_schema_version=2)), TASK_ID)
    assert summary(problem) == ("blocker", "assignees", NEEDS_SOMEBODY_READY, 2)


def test_work_in_progress_needs_somebody_on_it():
    problem = only(
        check(
            task(
                status="in_progress",
                start_date=date(2026, 8, 3),
                assignees=[],
                created_schema_version=2,
            )
        ),
        TASK_ID,
    )
    assert summary(problem) == ("blocker", "assignees", NEEDS_SOMEBODY_WIP, 2)


def test_the_statuses_that_demand_nothing_are_not_asked_who_is_on_them():
    """The three statuses that demand nothing at all go on demanding nothing.

    A rule added at one rung has to stay at that rung: an idea nobody has bet on
    owes nothing, nobody has even looked at a `thinking` record, and parked work
    is not broken work.
    """
    for status in ("thinking", "shaping", "shelved"):
        found = [p for p in check(task(status=status, assignees=[])) if p.field == "assignees"]
        assert found == [], status


def test_nothing_is_asked_of_a_record_nobody_has_looked_at():
    """`thinking` is the foot of the ladder, and the gate at the foot is empty.

    Stated as "nothing at all", not "nothing about assignees", because the point
    of the word is that it is where a half-formed record can sit without the tool
    nagging — which is the whole argument for having it. A record stripped of
    every gated field is the case: at `ready` it collects five blockers, and at
    `thinking` it must collect none.

    And asked of `required_at` as well, because that is the copy the create form
    and the table's inline editor read: a field marked required at a status the
    server demands nothing at is a form refusing a record the server would take.
    """
    bare = {
        "owner": None,
        "assignees": [],
        "reviewers": [],
        "person_weeks": None,
        "start_date": None,
        "prs": [],
    }
    # The control: the same record one rung up really does collect a handful, so
    # the empty list below is the status answering and not the fixture being
    # clean by accident.
    assert {p.field for p in check(task(status="ready", **bare))} == {
        "owner",
        "assignees",
        "reviewers",
        "person_weeks",
    }
    assert check(task(status="thinking", **bare)) == []

    for kind in ("project", "pitch", "task"):
        demanded = [field for field, at in required_at(kind).items() if "thinking" in at]
        assert demanded == [], kind
        # No more than `shaping` did, which is the rule the widening was held to:
        # a status further down the hill cannot ask for more than the one above.
        assert not {f for f, at in required_at(kind).items() if "thinking" in at} - {
            f for f, at in required_at(kind).items() if "shaping" in at
        }, kind


def test_the_rule_only_blocks_a_record_written_after_it_existed():
    """The grandfathering bargain, on the newest rule to take it.

    Adding a required field must never invalidate a corpus written before the
    field existed, or the rule gets reverted rather than adopted. A record created
    at schema_version 1 is warned; one created at 2 is refused.
    """
    older = only(check(task(assignees=[], created_schema_version=1)), TASK_ID)
    newer = only(check(task(assignees=[], created_schema_version=2)), TASK_ID)
    assert older.severity == "warning"
    assert newer.severity == "blocker"
    assert older.message == newer.message == NEEDS_SOMEBODY_READY


def test_the_form_is_told_to_ask_for_somebody():
    """`required_at` is what marks the label, and it is derived from the gate
    rather than restated — so this is the same rule, read the way a form reads
    it."""
    for kind in ("project", "pitch", "task"):
        assert set(required_at(kind)["assignees"]) == {"ready", "in_progress"}, kind


# --- §4 and §6: the end date, and dates compared to dates ---------------------


def test_a_done_record_needs_the_date_it_ended():
    """The one fact a finished record holds that nothing can derive.

    Without it the span is the start date twice — a dot on the timeline, an End
    column showing a start, no elapsed weeks and no overrun — so the field is not
    bookkeeping: it is what makes every reader of finished work able to say
    anything at all.
    """
    done = task(status="done", prs=["kilnlab/kiln4py#1"], created_schema_version=5)
    problem = only(check(done), TASK_ID)
    assert summary(problem) == ("blocker", "end_date", NEEDS_END_DATE, 5)
    assert check(done.model_copy(update={"end_date": date(2026, 8, 20)})) == []


def test_a_record_that_was_already_done_is_warned_and_not_blocked():
    """Grandfathering, on the rule it was chosen for.

    A corpus of finished work written before this field existed cannot supply it —
    `tests/fixtures/corpus` says `# was fabricated during migration; unknown` on
    one of its own start dates — so shipping this rule below `schema_version`
    would have turned five real files red on the commit that added it, and the
    rule would have been reverted rather than adopted. Shipped at 5, with
    `schema_version` moved 4 -> 5 in the same change, it warns about them and
    blocks everything written from now on.
    """
    older = only(check(task(status="done", prs=["x/y#1"], created_schema_version=4)), TASK_ID)
    newer = only(check(task(status="done", prs=["x/y#1"], created_schema_version=5)), TASK_ID)
    assert older.severity == "warning"
    assert newer.severity == "blocker"
    assert older.message == newer.message == NEEDS_END_DATE


def test_the_form_is_told_to_ask_for_the_end_date():
    """The gate read the way a form reads it, which is how the table's panel and
    the record page's Save both come to ask for this without either of them
    knowing the rule."""
    for kind in ("project", "pitch", "task"):
        assert set(required_at(kind)["end_date"]) == {"done"}, kind


def test_a_record_cannot_have_finished_before_it_began():
    """Two typed dates and no derivation between them, and nothing compared them.

    A blocker rather than a warning, and version 1 rather than 5, which is the
    exception this file makes exactly twice: grandfathering exists so a rule
    invented today does not turn last year's file red, and no file can predate the
    FIELD. `end_date` arrives at version 5, so anything carrying one was written
    after this rule existed, whatever version the file declares of itself.
    """
    backwards = task(
        status="done",
        prs=["x/y#1"],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 3),
        created_schema_version=1,
    )
    problem = only(check(backwards), TASK_ID, "end_date")
    assert summary(problem) == (
        "blocker",
        "end_date",
        "the end date 2026-08-03 is before the start date 2026-08-20, "
        "so this record finished before it began",
        1,
    )
    assert check(backwards.model_copy(update={"end_date": date(2026, 8, 20)})) == []


DATED = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})


def test_a_date_typed_a_year_out_is_reported_rather_than_silently_dropped():
    """§6's failure, made to say something.

    `2025-09-11` for `2026-09-11` parses, commits and then makes
    `span.start <= window[1] and span.end >= window[0]` false for every cycle
    there is — so the record drops out of `counts_in`, out of `Index.load` and out
    of `carried_into` at once, while `openproj check` reports the plan clean. A
    cycle loses a person's work and there is no error anywhere to chase.
    """
    strayed = task(status="in_progress", start_date=date(2025, 9, 11), person_weeks=1.0)
    problem = only(check(strayed, config=DATED), TASK_ID, "start_date")
    assert summary(problem) == (
        "warning",
        "start_date",
        "2025-09-11 is 41 weeks outside every cycle this plan has dated, so this record "
        "counts towards none of them: check the year",
        5,
    )


def test_a_date_near_the_plans_cycles_is_left_alone():
    """The allowance is what keeps the rule from refusing the ordinary case: work
    bet in the last cycle anybody has dated runs on into the next one, which by
    definition has no window yet."""
    for day in (date(2026, 6, 22), date(2026, 8, 14), date(2026, 10, 30), date(2026, 4, 6)):
        near = task(status="in_progress", start_date=day, person_weeks=1.0)
        assert [p for p in check(near, config=DATED) if p.field == "start_date"] == [], day


def test_a_plan_that_has_dated_no_cycles_checks_no_dates():
    """The same bargain the roster check makes: a tool that refuses dates before
    anybody has written a cycles file is a tool nobody finishes setting up."""
    strayed = task(status="in_progress", start_date=date(2025, 9, 11), person_weeks=1.0)
    assert [p for p in check(strayed) if p.field == "start_date"] == []


def test_the_end_date_is_held_to_the_same_calendar_as_the_start():
    """Both fields, because a rule enforced on one date and reported on two is the
    one-fact-two-implementations failure with extra steps."""
    strayed = task(
        status="done",
        prs=["x/y#1"],
        start_date=date(2026, 7, 6),
        end_date=date(2027, 9, 11),
        created_schema_version=5,
    )
    problem = only(check(strayed, config=DATED), TASK_ID, "end_date")
    assert problem.severity == "warning"
    assert problem.message.startswith("2027-09-11 is 56 weeks outside every cycle")
