"""The contract for `validate_all`: which rule fires, on what field, with what words.

Messages are asserted literally because they are the product — they are what a
human sees in the CLI and the web view — so they are single-sourced as constants
here rather than retyped per test.

Grandfathering is the reason `Problem` carries `rule_version` at all: a rule
introduced after an entity was written may only warn about it, never block it.
`test_grandfathering_*` is the load-bearing test of this module.
"""

import time
from datetime import date
from pathlib import Path

from openproj.model import (
    _ID_PATTERN,
    Config,
    Entity,
    Pitch,
    Problem,
    Project,
    Task,
    cycle_of,
    load_repo,
    parse_text,
    validate_all,
)

TASK_ID = "task-aaa111"
OTHER_TASK_ID = "task-ddd444"
PITCH_ID = "pitch-bbb222"
OTHER_PITCH_ID = "pitch-eee555"
PROJECT_ID = "proj-ccc333"

NEEDS_TITLE = "title must not be empty"
BAD_ID_PATTERN = "id must match " + _ID_PATTERN.pattern
NEEDS_OWNER = "a ready entity needs an owner"
NEEDS_REVIEWER = "a ready entity needs a reviewer, or review waived"
NEEDS_EFFORT = "a ready task needs an appetite"
NEEDS_APPETITE = "a ready pitch needs an appetite"
NEEDS_SHAPED_BY = "a ready pitch needs to say who shaped it"
NEEDS_ASSIGNED_ON = "work in progress needs the date it was assigned"
NEEDS_SOMEBODY_READY = "a ready entity needs somebody on it"
NEEDS_SOMEBODY_WIP = "work in progress needs somebody on it"
NEEDS_INDEPENDENT_REVIEWER = (
    "work in progress needs a reviewer other than its owner, or review waived"
)
NEEDS_PR = "a done entity needs at least one PR"
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

    "No rule" includes the schema_version 2 ones, the same way `pitch` below has
    always had to carry `shaped_by`. Without `assignees` here every test in this
    file would be asserting about one problem while a second sat beside it.
    """
    fields: dict[str, object] = {
        "id": TASK_ID,
        "kind": "task",
        "title": "A task",
        "parent": PITCH_ID,
        "status": "ready",
        "owner": "jcanton",
        "assignees": ["jcanton"],
        "reviewers": ["msimberg"],
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
        "owner": "jcanton",
        "assignees": ["jcanton"],
        "reviewers": ["msimberg"],
        "person_weeks": 2.0,
        "shaped_by": "havogt",
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
        "owner": "jcanton",
        "assignees": ["jcanton"],
        "reviewers": ["msimberg"],
        "assigned_on": date(2026, 8, 3),
    }
    return Project(**(fields | overrides))


def check(*entities: Entity, config: Config | None = None) -> list[Problem]:
    return validate_all(list(entities), config or Config())


def only(problems: list[Problem], entity_id: str, field: str | None = None) -> Problem:
    matching = [
        p for p in problems
        if p.entity_id == entity_id and (field is None or p.field == field)
    ]
    named = entity_id if field is None else f"{entity_id}.{field}"
    assert len(matching) == 1, f"expected exactly one problem for {named}, got {matching}"
    return matching[0]


def summary(problem: Problem) -> tuple[str, str | None, str, int]:
    return (problem.severity, problem.field, problem.message, problem.rule_version)


def summaries(problems: list[Problem]) -> set[tuple[str, str, str | None, str, int]]:
    return {(p.severity, p.entity_id, p.field, p.message, p.rule_version) for p in problems}


def test_a_fully_specified_entity_has_no_problems():
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


def test_every_depends_on_target_must_exist():
    problem = only(check(task(depends_on=["task-fff666"])), TASK_ID)
    assert summary(problem) == ("blocker", "depends_on", missing_target("task-fff666"), 1)


def test_regression_an_entity_may_not_depend_on_its_own_ancestor_or_descendant():
    """Regression: containment already implies an ordering, so a dependency along
    the parent chain is a contradiction the scheduler cannot resolve."""
    upwards = only(check(task(depends_on=[PITCH_ID]), pitch()), TASK_ID)
    assert summary(upwards) == ("blocker", "depends_on", ancestor_dep(PITCH_ID), 1)
    downwards = only(check(task(), pitch(depends_on=[TASK_ID])), PITCH_ID)
    assert summary(downwards) == ("blocker", "depends_on", descendant_dep(TASK_ID), 1)


def test_a_depends_on_cycle_is_reported_on_every_entity_in_it():
    entities = (task(depends_on=[OTHER_TASK_ID]), task(id=OTHER_TASK_ID, depends_on=[TASK_ID]))
    found = check(*entities)
    for entity_id in (TASK_ID, OTHER_TASK_ID):
        assert summary(only(found, entity_id)) == ("blocker", "depends_on", DEPENDS_ON_CYCLE, 1)


def test_a_parent_chain_cycle_is_reported_on_every_entity_in_it():
    entities = (pitch(parent=OTHER_PITCH_ID), pitch(id=OTHER_PITCH_ID, parent=PITCH_ID))
    found = check(*entities)
    for entity_id in (PITCH_ID, OTHER_PITCH_ID):
        assert summary(only(found, entity_id)) == ("blocker", "parent", PARENT_CYCLE, 1)


def test_a_task_without_a_parent_is_only_a_warning():
    """Orphan tasks are a fact of migration, not a defect: warn, do not block."""
    problem = only(check(task(parent=None)), TASK_ID)
    assert summary(problem) == ("warning", "parent", SHOULD_HAVE_PARENT, 1)


def test_depending_on_a_shelved_entity_is_only_a_warning():
    shelved = task(id=OTHER_TASK_ID, status="shelved")
    problem = only(check(task(depends_on=[OTHER_TASK_ID]), shelved), TASK_ID)
    assert summary(problem) == ("warning", "depends_on", shelved_target(OTHER_TASK_ID), 1)


# --- rules that apply at one status -----------------------------------------


def test_a_todo_entity_needs_an_owner():
    assert summary(only(check(task(owner=None)), TASK_ID)) == ("blocker", "owner", NEEDS_OWNER, 1)


def test_a_todo_entity_needs_a_reviewer_unless_review_is_waived():
    problem = only(check(task(reviewers=[])), TASK_ID)
    assert summary(problem) == ("blocker", "reviewers", NEEDS_REVIEWER, 1)


def test_a_todo_entity_needs_a_size():
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


def test_a_todo_pitch_needs_shaped_by():
    """Version 2 of the rules; here on an entity created at 2, so it blocks."""
    problem = only(check(pitch(shaped_by=None, created_schema_version=2)), PITCH_ID)
    assert summary(problem) == ("blocker", "shaped_by", NEEDS_SHAPED_BY, 2)


def test_a_wip_entity_needs_assigned_on():
    for entity in (task(status="in_progress", assigned_on=None), project(assigned_on=None)):
        problem = only(check(entity), entity.id)
        assert summary(problem) == ("blocker", "assigned_on", NEEDS_ASSIGNED_ON, 1)


def test_a_wip_entity_needs_a_reviewer_who_is_not_its_owner():
    """Self-review is the same as no review, so the reviewer list must contain
    somebody else before work may be in progress."""
    wip = task(
        status="in_progress",
        assigned_on=date(2026, 8, 3),
        owner="jcanton",
        reviewers=["jcanton"],
    )
    problem = only(check(wip), TASK_ID)
    assert summary(problem) == ("blocker", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1)


def test_a_done_entity_needs_at_least_one_pr():
    problem = only(check(task(status="done", prs=[])), TASK_ID)
    assert summary(problem) == ("blocker", "prs", NEEDS_PR, 1)


def test_a_shelved_entity_has_no_requirements_at_all():
    """Shelved work is parked, not broken: nothing about it is worth reporting,
    not even the warnings that would fire on the same fields at any other status."""
    parked = task(status="shelved", parent=None, owner=None, reviewers=[], person_weeks=None)
    assert check(parked) == []


def test_review_waived_satisfies_both_the_todo_and_the_wip_reviewer_gates():
    todo = task(reviewers=[], review_waived=True)
    wip = task(
        status="in_progress",
        assigned_on=date(2026, 8, 3),
        owner="jcanton",
        reviewers=["jcanton"],
        review_waived=True,
    )
    assert check(todo) == []
    assert check(wip) == []


# --- grandfathering ---------------------------------------------------------


def test_grandfathering_turns_a_newer_rule_into_a_warning_on_an_older_entity():
    """The whole point of rule_version: shipping the version 2 shaped_by rule must
    not retroactively block a corpus written at version 1. Same entity, same
    missing field, severity decided by created_schema_version alone."""
    old = only(check(pitch(shaped_by=None, created_schema_version=1)), PITCH_ID)
    new = only(check(pitch(shaped_by=None, created_schema_version=2)), PITCH_ID)
    assert summary(old) == ("warning", "shaped_by", NEEDS_SHAPED_BY, 2)
    assert summary(new) == ("blocker", "shaped_by", NEEDS_SHAPED_BY, 2)


def test_grandfathering_does_not_soften_a_rule_older_than_the_entity():
    problem = only(check(pitch(owner=None, created_schema_version=2)), PITCH_ID)
    assert summary(problem) == ("blocker", "owner", NEEDS_OWNER, 1)


# --- what contains what, and what is bet ------------------------------------


def test_a_parent_of_the_wrong_kind_is_named_as_such():
    """The levels the spec claimed from its first day and nothing checked."""
    entities = [
        Project(id="proj-000001", kind="project", title="P"),
        Pitch(id="pitch-000001", kind="pitch", title="Q", parent="proj-000001"),
        Task(id="task-000001", kind="task", title="T", parent="pitch-000001"),
        Task(id="task-000002", kind="task", title="U", parent="task-000001",
             created_schema_version=4),
    ]
    problem = only(validate_all(entities, Config()), "task-000002", field="parent")
    assert summary(problem) == (
        "blocker", "parent", "a task belongs to a pitch or a project, not to a task", 4
    )


def test_a_task_may_hang_straight_off_a_project():
    """Work nobody pitched still belongs somewhere. The first real cycle imported
    had two of them — reported at the review, never bet — and the alternative was
    a pitch invented to hold them, which puts a bet in the corpus that no betting
    table ever made. A plan that lies about what was bet is worse than a tree
    that is two levels deep in places."""
    entities = [
        Project(id="proj-000001", kind="project", title="P"),
        Task(id="task-000001", kind="task", title="T", parent="proj-000001",
             created_schema_version=4),
    ]

    assert not [p for p in validate_all(entities, Config())
                if p.entity_id == "task-000001" and p.field == "parent"]


def test_a_project_belongs_to_nothing():
    entities = [
        Project(id="proj-000001", kind="project", title="P"),
        Project(id="proj-000002", kind="project", title="Q", parent="proj-000001",
                created_schema_version=4),
    ]
    problem = only(validate_all(entities, Config()), "proj-000002", field="parent")
    # A project belongs to a PRODUCT now, and to nothing else — the message is
    # built from `PARENT_KINDS`, which is built from the ladder, so it followed
    # the new rung without being edited.
    assert problem.message == "a project belongs to a product, not to a project"


def test_a_pitch_under_a_project_and_a_task_under_a_pitch_are_the_shape():
    entities = [
        Project(id="proj-000001", kind="project", title="P"),
        Pitch(id="pitch-000001", kind="pitch", title="Q", parent="proj-000001"),
        Task(id="task-000001", kind="task", title="T", parent="pitch-000001"),
    ]
    assert [p for p in validate_all(entities, Config()) if p.field == "parent"] == []


def test_a_chore_nobody_pitched_keeps_its_own_cycle_and_a_parented_task_does_not():
    """A bet is made on a pitch, or on a task nobody pitched. Both belong on a
    betting table; a task inside a pitch came with the pitch, and a second cycle
    number on it is one fact in two files."""
    dated = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    entities = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", cycle=36),
        Task(id="task-000001", kind="task", title="T", parent="pitch-000001", cycle=36,
             created_schema_version=4),
        Task(id="task-000002", kind="task", title="Chore", cycle=36),
    ]
    problems = [p for p in validate_all(entities, dated) if p.field == "cycle"]

    assert [p.entity_id for p in problems] == ["task-000001"]
    assert problems[0].severity == "warning", "it is ignored, not refused"
    assert cycle_of(entities[1], {e.id: e for e in entities}) == 36, "inherited from its pitch"
    assert cycle_of(entities[2], {e.id: e for e in entities}) == 36, "its own"


def test_a_project_is_not_bet_because_it_holds_bets():
    dated = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    entities = [Project(id="proj-000001", kind="project", title="P", cycle=36)]
    problem = only(validate_all(entities, dated), "proj-000001", field="cycle")
    assert problem.message.startswith("a project is not bet")
    assert cycle_of(entities[0], {"proj-000001": entities[0]}) is None


def test_tasks_that_add_up_to_more_than_the_bet_say_so():
    """The appetite is the box and the tasks are what somebody proposes to put in
    it. Nothing compared the two, so a six-week bet holding seven and a half
    weeks of tasks read as a six-week bet on every page."""
    entities = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=6.0),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=4.0),
        Task(id="task-000002", kind="task", title="B", parent="pitch-000001", person_weeks=3.5),
    ]
    problem = only(validate_all(entities, Config()), "pitch-000001", field="person_weeks")
    assert problem.severity == "warning", "cutting scope or re-betting is a decision"
    assert "7.5 weeks, more than the 6" in problem.message


def test_tasks_that_fit_inside_the_bet_say_nothing():
    """Under the appetite is the normal state of a pitch whose tasks are still
    being written, and saying so on every one of them is noise."""
    entities = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=6.0),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=4.0),
    ]
    assert [p for p in validate_all(entities, Config()) if p.field == "person_weeks"] == []


def test_a_shelved_task_is_not_counted_against_its_pitchs_appetite():
    entities = [
        Pitch(id="pitch-000001", kind="pitch", title="Q", person_weeks=4.0),
        Task(id="task-000001", kind="task", title="A", parent="pitch-000001", person_weeks=4.0),
        Task(id="task-000002", kind="task", title="B", parent="pitch-000001", person_weeks=4.0,
             status="shelved"),
    ]
    assert [p for p in validate_all(entities, Config()) if p.field == "person_weeks"] == []


# --- the seed corpus --------------------------------------------------------


def test_the_seed_corpus_reports_exactly_this_problem_set(seed_root: Path):
    """Integration over the real 17 files. The set is exhaustive on purpose: a new
    rule that fires on the committed corpus has to be argued for here first.

    Only pitch-1b3f9a is missing shaped_by *at status todo*, which is where that
    rule lives; the other four pitches are wip or done and so are not asked.

    The version-4 warnings are the argument for those rules, made against real
    files rather than invented ones. Every one of them is a thing the corpus
    already does and nothing had ever said: nine tasks carrying a `cycle` that
    belongs to the pitch they are part of, one task hung straight off a project —
    which is allowed now, and was the shape the first real import needed — and
    one pitch whose five tasks propose twice the work it was bet at. All
    warnings: the corpus is created_schema_version 2 and these rules are 4, so
    nothing written before them breaks.
    """
    entities, config, _ = load_repo(seed_root)
    assert len(entities) == 17
    inherits = "the bet is on the pitch, so this task takes its cycle from {}; " \
        "the number here is ignored"
    assert summaries(validate_all(entities, config)) == {
        # wip without a start date
        ("blocker", "proj-7e57a0", "assigned_on", NEEDS_ASSIGNED_ON, 1),
        ("blocker", "pitch-48ea9e", "assigned_on", NEEDS_ASSIGNED_ON, 1),
        # wip with an empty reviewer list and nothing underneath carrying one.
        # `pitch-5e7b1c` was here too and is not any more: its own list is empty,
        # but its tasks name iomaganaris, muellch and abishekg7, and a pitch whose
        # tasks are reviewed is reviewed. That is the rule doing what it was added
        # for, on the corpus the first real import produced.
        ("blocker", "pitch-48ea9e", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1),
        # done, but the migration recovered no PR links
        ("blocker", "pitch-2a7f3e", "prs", NEEDS_PR, 1),
        ("blocker", "pitch-3c9a41", "prs", NEEDS_PR, 1),
        ("blocker", "task-31f6c4", "prs", NEEDS_PR, 1),
        ("blocker", "task-3a52d8", "prs", NEEDS_PR, 1),
        ("blocker", "task-3e07b2", "prs", NEEDS_PR, 1),
        # grandfathered: the corpus is created_schema_version 1, the rule is 2
        ("warning", "pitch-1b3f9a", "shaped_by", NEEDS_SHAPED_BY, 2),
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
        # v4: 8.1 weeks of tasks inside a four-week bet
        (
            "warning",
            "pitch-5e7b1c",
            "person_weeks",
            "its 5 tasks add up to 8.1 weeks, more than the 4 it was bet at — "
            "cut scope, or re-bet it",
            4,
        ),
    }


# --- the roster -------------------------------------------------------------


def test_a_name_nobody_recognises_is_a_warning_not_a_refusal():
    """The roster is a hand-maintained file, so it is always slightly behind
    reality. Blocking on it would make a new colleague unassignable on their first
    day; warning catches the case that actually happens, which is a typo quietly
    creating a task nobody reviews."""
    roster = Config(known_people=["jcanton", "msimberg"])

    problem = only(check(task(owner="jcnaton"), config=roster), TASK_ID)
    assert summary(problem) == ("warning", "owner", "jcnaton is not in config/people.yaml", 1)


def test_a_roster_that_does_not_exist_checks_nothing():
    """An empty roster means the check is off. A tracker that refuses a name
    because nobody has written the roster yet is a tracker nobody finishes setting
    up."""
    assert check(task(owner="anybody-at-all"), config=Config()) == []


def test_every_person_field_is_checked_against_the_roster():
    roster = Config(known_people=["jcanton"])
    problems = check(
        task(owner="jcanton", reviewers=["ghost"], assignees=["phantom"]), config=roster
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
    entity.
    """
    stale = parse_text(
        "---\nid: pitch-bbb222\nkind: pitch\ntitle: T\nstatus: wip\npriority: 1\n---\n\nB.\n",
        "pitches/pitch-bbb222.md",
    )

    assert (stale.status, stale.priority) == ("wip", "1")
    fields = {(p.field, p.severity) for p in check(stale)}
    assert ("status", "blocker") in fields
    assert ("priority", "blocker") in fields


def test_a_stale_vocabulary_still_schedules_and_renders():
    """The page has to survive the record. A tracker that shows nothing because one
    file is old is worse than one that shows the file and says what is wrong."""
    from datetime import date

    from openproj.index import build_index

    stale = parse_text(
        "---\nid: task-aaa111\nkind: task\ntitle: T\nstatus: wip\npriority: 1\n---\n\nB.\n",
        "tasks/task-aaa111.md",
    )
    index = build_index([stale], Config(), date(2026, 8, 17))

    assert "task-aaa111" in index.spans
    assert any(p.field == "status" for p in index.problems)


def test_a_cycle_nobody_dated_is_reported_rather_than_ignored():
    """`_overrun` looks the window up with `.get`, so an undated number does not
    raise — it returns None, and the entity silently stops being checked for
    overrun. A typo therefore reads as "on time" forever, which is the one
    reading nobody would question."""
    config = Config(cycles={36: (date(2026, 6, 22), date(2026, 8, 14))})
    entities = [task(cycle=99), task(id="task-000002", cycle=36)]

    problems = validate_all(entities, config)
    reported = [p for p in problems if p.field == "cycle"]

    assert len(reported) == 1
    assert reported[0].entity_id == entities[0].id
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
        name
        for model in (Project, Pitch, Task)
        for name in model.model_fields
        if "_" in name
    }
    assert "review_waived" in spelled_in_the_file, "the derivation still finds the fields"

    # Every gate, tripped at once: each status, each kind, a missing dependency, a
    # shelved one, and a pair that depend on each other.
    loop_a, loop_b, SHELVED_ID = "task-f00001", "task-f00002", "task-f00003"
    entities = [
        pitch(status="ready", owner=None, reviewers=[], person_weeks=None, shaped_by=None),
        task(status="in_progress", assigned_on=None, reviewers=["jcanton"], owner="jcanton"),
        project(status="ready", owner=None, reviewers=[]),
        Task(id=OTHER_TASK_ID, kind="task", title="T", status="ready", owner="jcanton",
             reviewers=["msimberg"], person_weeks=None, depends_on=["task-999999", SHELVED_ID]),
        Task(id=SHELVED_ID, kind="task", title="D", status="shelved", owner="jcanton"),
        Task(id=loop_a, kind="task", title="A", status="shaping", depends_on=[loop_b]),
        Task(id=loop_b, kind="task", title="B", status="shaping", depends_on=[loop_a]),
    ]
    problems = check(*entities)
    assert len(problems) >= 9, f"the gates did not all fire: {[p.message for p in problems]}"

    leaked = sorted(
        (p.field, p.message)
        for p in problems
        for name in spelled_in_the_file
        if name in p.message
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
        task(reviewers=["msimberg"]),
    )

    assert [p for p in held if p.entity_id == PITCH_ID and p.field == "reviewers"] == []


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
        check(pitch(reviewers=[]), task(reviewers=["msimberg"], status="shelved")),
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
        task(reviewers=["msimberg"]),
    )

    assert [p for p in held if p.field == "reviewers"] == []


def test_in_progress_wants_somebody_other_than_the_owner_from_underneath_too():
    """The second reviewer rule reads the same set. A pitch in progress whose only
    task is reviewed by the pitch's own owner is a pitch nobody else is
    reviewing, which is the thing that rule is about."""
    problem = only(
        check(
            pitch(reviewers=[], status="in_progress", assigned_on=date(2026, 8, 3)),
            task(reviewers=["jcanton"], owner="jcanton"),
        ),
        PITCH_ID,
        field="reviewers",
    )

    assert "other than its owner" in problem.message


def test_a_parent_cycle_does_not_send_the_reviewer_walk_round_for_ever():
    """The walk that reads reviewers off the work underneath had no memory of
    where it had been, and a plan is allowed to contain a parent cycle — this
    tool reports one as a blocker rather than refusing to load the plan, which is
    the whole reason `test_a_parent_chain_cycle_is_reported_on_every_entity_in_it`
    above has a corpus to run on.

    On that corpus the walk went round for ever, appending a reviewer per pass:
    an infinite loop that also grows. It took a laptop down before any test
    noticed, because the suite it was in simply never finished — which is what
    this bound is for. A test that hangs reports nothing; a test that fails names
    the thing.
    """
    entities = (pitch(parent=OTHER_PITCH_ID), pitch(id=OTHER_PITCH_ID, parent=PITCH_ID))

    started = time.monotonic()
    found = check(*entities)
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


def test_a_todo_entity_needs_somebody_on_it():
    """An owner answers for the bet; assignees are who is doing the work.

    Not the same question, and the scheduler already reads them as different
    things: it prices a record by the people on it, so a bet with an owner and
    nobody assigned is one that has been accepted and staffed with nobody — and it
    is then scheduled as if a full person were on it. jcanton, 2026-08-22.
    """
    problem = only(check(task(assignees=[])), TASK_ID)
    assert summary(problem) == ("blocker", "assignees", NEEDS_SOMEBODY_READY, 2)


def test_work_in_progress_needs_somebody_on_it():
    problem = only(check(task(status="in_progress", assigned_on=date(2026, 8, 3),
                              assignees=[])), TASK_ID)
    assert summary(problem) == ("blocker", "assignees", NEEDS_SOMEBODY_WIP, 2)


def test_shaping_and_shelved_are_not_asked_who_is_on_them():
    """The two statuses that demand nothing at all go on demanding nothing.

    A rule added at one rung has to stay at that rung: an idea nobody has bet on
    owes nothing, and neither does parked work.
    """
    for status in ("shaping", "shelved"):
        found = [p for p in check(task(status=status, assignees=[])) if p.field == "assignees"]
        assert found == [], status


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
    from openproj.model import required_at

    for kind in ("project", "pitch", "task"):
        assert set(required_at(kind)["assignees"]) == {"ready", "in_progress"}, kind
