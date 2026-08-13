"""The contract for `validate_all`: which rule fires, on what field, with what words.

Messages are asserted literally because they are the product — they are what a
human sees in the CLI and the web view — so they are single-sourced as constants
here rather than retyped per test.

Grandfathering is the reason `Problem` carries `rule_version` at all: a rule
introduced after an entity was written may only warn about it, never block it.
`test_grandfathering_*` is the load-bearing test of this module.
"""

from datetime import date
from pathlib import Path

from openproj.model import (
    Config,
    Entity,
    Pitch,
    Problem,
    Project,
    Task,
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
BAD_ID_PATTERN = "id must match ^(proj|pitch|task)-[0-9a-f]{6}$"
NEEDS_OWNER = "a ready entity needs an owner"
NEEDS_REVIEWER = "a ready entity needs a reviewer, or review_waived"
NEEDS_EFFORT = "a ready task needs effort_weeks"
NEEDS_APPETITE = "a ready pitch needs appetite_weeks"
NEEDS_SHAPED_BY = "a ready pitch needs shaped_by"
NEEDS_ASSIGNED_ON = "work in progress needs assigned_on"
NEEDS_INDEPENDENT_REVIEWER = (
    "work in progress needs a reviewer other than its owner, or review_waived"
)
NEEDS_PR = "a done entity needs at least one PR"
SHOULD_HAVE_PARENT = "a task should have a parent"
DEPENDS_ON_CYCLE = "part of a depends_on cycle"
PARENT_CYCLE = "part of a parent cycle"


def bad_id_prefix(kind: str) -> str:
    return f"id prefix must match kind {kind}"


def missing_target(target: str) -> str:
    return f"depends_on target {target} does not exist"


def shelved_target(target: str) -> str:
    return f"depends_on target {target} is shelved"


def ancestor_dep(target: str) -> str:
    return f"cannot depend on {target}: it is an ancestor"


def descendant_dep(target: str) -> str:
    return f"cannot depend on {target}: it is a descendant"


def task(**overrides: object) -> Task:
    """A todo task that breaks no rule, so a test can break exactly one thing.

    Its parent is PITCH_ID, which most tests do not bother to pass alongside it:
    a parent that is absent from the repository is not itself a rule violation.
    """
    fields: dict[str, object] = {
        "id": TASK_ID,
        "kind": "task",
        "title": "A task",
        "parent": PITCH_ID,
        "status": "ready",
        "owner": "jcanton",
        "reviewers": ["msimberg"],
        "effort_weeks": 1.0,
    }
    return Task(**(fields | overrides))


def pitch(**overrides: object) -> Pitch:
    """A todo pitch that breaks no rule, including the schema_version 2 one."""
    fields: dict[str, object] = {
        "id": PITCH_ID,
        "kind": "pitch",
        "title": "A pitch",
        "parent": None,
        "status": "ready",
        "owner": "jcanton",
        "reviewers": ["msimberg"],
        "appetite_weeks": 2.0,
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
        "reviewers": ["msimberg"],
        "assigned_on": date(2026, 8, 3),
    }
    return Project(**(fields | overrides))


def check(*entities: Entity, config: Config | None = None) -> list[Problem]:
    return validate_all(list(entities), config or Config())


def only(problems: list[Problem], entity_id: str) -> Problem:
    matching = [p for p in problems if p.entity_id == entity_id]
    assert len(matching) == 1, f"expected exactly one problem for {entity_id}, got {matching}"
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
    assert summary(only(check(task(effort_weeks=None)), TASK_ID)) == (
        "blocker",
        "effort_weeks",
        NEEDS_EFFORT,
        1,
    )
    assert summary(only(check(pitch(appetite_weeks=None)), PITCH_ID)) == (
        "blocker",
        "appetite_weeks",
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
    parked = task(status="shelved", parent=None, owner=None, reviewers=[], effort_weeks=None)
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


# --- the seed corpus --------------------------------------------------------


def test_the_seed_corpus_reports_exactly_this_problem_set(seed_root: Path):
    """Integration over the real 17 files. The set is exhaustive on purpose: a new
    rule that fires on the committed corpus has to be argued for here first.

    Only pitch-1b3f9a is missing shaped_by *at status todo*, which is where that
    rule lives; the other four pitches are wip or done and so are not asked.
    """
    entities, config = load_repo(seed_root)
    assert len(entities) == 17
    assert summaries(validate_all(entities, config)) == {
        # wip without a start date
        ("blocker", "proj-7e57a0", "assigned_on", NEEDS_ASSIGNED_ON, 1),
        ("blocker", "pitch-48ea9e", "assigned_on", NEEDS_ASSIGNED_ON, 1),
        # wip with an empty reviewer list
        ("blocker", "pitch-48ea9e", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1),
        ("blocker", "pitch-5e7b1c", "reviewers", NEEDS_INDEPENDENT_REVIEWER, 1),
        # done, but the migration recovered no PR links
        ("blocker", "pitch-2a7f3e", "prs", NEEDS_PR, 1),
        ("blocker", "pitch-3c9a41", "prs", NEEDS_PR, 1),
        ("blocker", "task-31f6c4", "prs", NEEDS_PR, 1),
        ("blocker", "task-3a52d8", "prs", NEEDS_PR, 1),
        ("blocker", "task-3e07b2", "prs", NEEDS_PR, 1),
        # grandfathered: the corpus is created_schema_version 1, the rule is 2
        ("warning", "pitch-1b3f9a", "shaped_by", NEEDS_SHAPED_BY, 2),
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
