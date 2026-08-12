"""The scheduler contract, written before the scheduler exists.

Two conventions run through every assertion here and are worth stating once,
because they are the source of most off-by-one arguments:

* A `Span` is **inclusive**. `end` is the last working day the item occupies, so
  a one-week item starting on a Monday ends on the Friday, not on the following
  Monday. Anything that follows it — a dependent, or the next item for the same
  worker — starts on the next working day *after* that end.
* A size in weeks is a size in *working* weeks: five working days each, rounded
  up to a whole day, with weekends and configured holidays skipped. Availability
  scales that number; it does not redefine what a week is.

`today` is passed explicitly everywhere. A suite that calls `date.today()` stops
testing the scheduler and starts testing the calendar.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from openproj import model
from openproj.model import Config, Entity, Pitch, Task
from openproj.schedule import Explanation, Span, schedule, working_days_after

MONDAY = date(2026, 8, 17)

CONFIG = Config(
    nominal_availability=1.0,
    default_task_effort=0.5,
    holidays=[],
    cycles={36: (date(2026, 6, 22), date(2026, 8, 14)), 37: (date(2026, 8, 17), date(2026, 10, 9))},
)


def task(suffix: str, *, owner: str | None = "ann", size: float | None = 1.0, **fields) -> Task:
    return Task(
        id=f"task-{suffix}", kind="task", title=suffix, owner=owner, effort_weeks=size, **fields
    )


def pitch(suffix: str, *, owner: str | None = "ann", size: float | None = None, **fields) -> Pitch:
    return Pitch(
        id=f"pitch-{suffix}", kind="pitch", title=suffix, owner=owner, appetite_weeks=size, **fields
    )


def run(
    entities: list[Entity], today: date = MONDAY, config: Config = CONFIG
) -> tuple[dict[str, Span], dict[str, Explanation]]:
    return schedule(entities, config, today)


# --------------------------------------------------------------------------- #
# working_days_after
# --------------------------------------------------------------------------- #


def test_a_week_is_five_working_days_ending_on_the_fifth():
    assert working_days_after(MONDAY, 1.0, CONFIG) == date(2026, 8, 21)
    assert working_days_after(MONDAY, 3.0, CONFIG) == date(2026, 9, 4)


def test_fractional_weeks_round_up_to_a_whole_day():
    """0.5 weeks is 2.5 days of work, which occupies three days on a calendar.

    1.2 is here because 1.2 * 5 is the kind of arithmetic that lands on
    6.000000000000001 and buys a seventh day.
    """
    assert working_days_after(MONDAY, 0.4, CONFIG) == date(2026, 8, 18)
    assert working_days_after(MONDAY, 0.5, CONFIG) == date(2026, 8, 19)
    assert working_days_after(MONDAY, 1.2, CONFIG) == date(2026, 8, 24)


def test_weekends_do_not_count_and_a_weekend_start_rolls_forward():
    assert working_days_after(date(2026, 8, 20), 0.6, CONFIG) == date(2026, 8, 24)
    assert working_days_after(date(2026, 8, 15), 1.0, CONFIG) == date(2026, 8, 21)


def test_configured_holidays_do_not_count(seed_root: Path):
    """The seed's ETH year-end closure: 24 and 25 December 2026 are not working days."""
    config = model.load_config(seed_root)
    assert working_days_after(date(2026, 12, 21), 1.0, config) == date(2026, 12, 29)


# --------------------------------------------------------------------------- #
# The nine steps
# --------------------------------------------------------------------------- #


def test_step1_shelved_entities_are_outside_the_graph_and_get_no_span():
    shelved = task("aaa001", status="shelved")
    spans, _ = run([shelved, task("aaa002", owner="bo", depends_on=["task-aaa001"])])
    assert "task-aaa001" not in spans
    assert spans["task-aaa002"].start == MONDAY


def test_step2_a_dependency_cycle_leaves_its_members_and_descendants_unscheduled():
    """schedule() never raises: a cycle costs you those entities, not the index."""
    entities = [
        task("aaa001", depends_on=["task-aaa002"]),
        task("aaa002", owner="bo", depends_on=["task-aaa001"]),
        task("aaa003", owner="cy", depends_on=["task-aaa001"]),
        task("aaa004", owner="di"),
    ]
    spans, _ = run(entities)
    caught = ("task-aaa001", "task-aaa002", "task-aaa003")
    assert [spans[i].unscheduled for i in caught] == [True, True, True]
    assert spans["task-aaa001"].start == spans["task-aaa001"].end == MONDAY
    assert spans["task-aaa004"] == Span(start=MONDAY, end=date(2026, 8, 21))


def test_step3_done_work_is_a_historical_point_marker_or_no_span_at_all():
    dated = task("aaa001", status="done", assigned_on=date(2026, 7, 1))
    spans, _ = run([dated, task("aaa002", status="done")])
    july = date(2026, 7, 1)
    assert spans["task-aaa001"] == Span(start=july, end=july, historical=True)
    assert "task-aaa002" not in spans


def test_step3_a_done_parent_stays_historical_even_with_a_live_child():
    entities = [pitch("bbb001", status="done"), task("aaa001", parent="pitch-bbb001")]
    spans, _ = run(entities)
    assert "pitch-bbb001" not in spans


def test_step4_duration_is_the_stated_size_at_nominal_availability():
    spans, _ = run([task("aaa001", size=2.0)])
    assert spans["task-aaa001"] == Span(start=MONDAY, end=date(2026, 8, 28))


def test_step4_a_missing_size_falls_back_to_the_default_and_is_marked_estimated():
    spans, _ = run([task("aaa001", size=None)])
    assert spans["task-aaa001"] == Span(start=MONDAY, end=date(2026, 8, 19), estimated=True)


def test_step5_ordering_is_by_priority_then_id():
    """Order is only observable through capacity: all three want the same worker."""
    entities = [task("aaa001"), task("aaa002"), task("aaa003", priority=1)]
    spans, _ = run(entities)
    assert spans["task-aaa003"].start == MONDAY
    assert spans["task-aaa001"].start == date(2026, 8, 24)
    assert spans["task-aaa002"].start == date(2026, 8, 31)


def test_step6_a_leaf_waits_for_today_its_assignment_date_and_its_blockers():
    entities = [
        task("aaa001"),
        task("aaa002", owner="bo", depends_on=["task-aaa001"]),
        task("aaa003", owner="cy", assigned_on=date(2026, 9, 1)),
    ]
    spans, _ = run(entities)
    assert spans["task-aaa002"].start == date(2026, 8, 24)  # the working day after Friday's end
    assert spans["task-aaa003"].start == date(2026, 9, 1)


def test_step7_one_item_per_worker_at_a_time_but_unowned_work_is_unlimited():
    entities = [
        task("aaa001", owner=None),
        task("aaa002", owner=None),
        task("aaa003", reviewers=["bo"]),
        task("aaa004", owner="bo"),
    ]
    spans, _ = run(entities)
    assert spans["task-aaa001"] == Span(start=MONDAY, end=date(2026, 8, 21), unowned=True)
    assert spans["task-aaa002"].start == MONDAY
    assert spans["task-aaa004"].start == MONDAY  # reviewing is not doing


def test_step7_assignees_consume_capacity_and_are_not_unowned():
    entities = [task("aaa001", owner=None, assignees=["cy"]), task("aaa002", owner="cy")]
    spans, _ = run(entities)
    assert spans["task-aaa001"] == Span(start=MONDAY, end=date(2026, 8, 21))
    assert spans["task-aaa002"].start == date(2026, 8, 24)


def test_step8_a_parent_spans_from_its_first_child_to_its_last():
    entities = [
        pitch("bbb001", owner="cy", size=4.0),
        task("aaa001", parent="pitch-bbb001"),
        task("aaa002", owner="bo", parent="pitch-bbb001", depends_on=["task-aaa001"]),
    ]
    spans, _ = run(entities)
    assert spans["pitch-bbb001"] == Span(start=MONDAY, end=date(2026, 8, 28))


def test_step9_finishing_after_the_cycle_ends_records_the_overrun_in_weeks():
    spans, _ = run([task("aaa001", cycle=36), task("aaa002", owner="bo", cycle=37)])
    assert spans["task-aaa001"].overruns_cycle_weeks == pytest.approx(1.0)
    assert spans["task-aaa002"].overruns_cycle_weeks is None


# --------------------------------------------------------------------------- #
# Regression guards
# --------------------------------------------------------------------------- #


def test_regression_children_are_ordered_before_their_parent():
    """The parent outranks both children on (priority, id), so only the
    containment edges can keep it from being visited first — and a parent
    visited first has no child spans to build its own span from."""
    entities = [
        pitch("bbb001", owner=None, priority=1),
        task("aaa001", priority=3, parent="pitch-bbb001"),
        task("aaa002", owner="bo", priority=3, parent="pitch-bbb001", size=2.0),
    ]
    spans, _ = run(entities)
    assert spans["pitch-bbb001"] == Span(start=MONDAY, end=date(2026, 8, 28))


def test_regression_a_three_week_appetite_is_three_working_weeks_not_five():
    """Dividing by availability unconditionally turns 3.0 into 5.0 and ends this
    on 2026-09-18 instead."""
    spans, _ = run([pitch("bbb001", size=3.0)])
    assert spans["pitch-bbb001"].end == date(2026, 9, 4)


def test_regression_a_task_and_a_pitch_of_the_same_size_take_the_same_time():
    spans, _ = run([task("aaa001", size=2.0), pitch("bbb001", owner="bo", size=2.0)])
    assert spans["task-aaa001"] == spans["pitch-bbb001"]


def test_regression_done_work_neither_occupies_the_future_nor_consumes_capacity():
    finished = task("aaa001", status="done", assigned_on=date(2026, 7, 1), size=4.0)
    entities = [finished, task("aaa002")]
    spans, _ = run(entities)
    assert spans["task-aaa001"].end == date(2026, 7, 1)
    assert spans["task-aaa002"].start == MONDAY


def test_regression_a_parent_does_not_double_book_the_owner_of_its_only_child():
    entities = [pitch("bbb001", size=2.0), task("aaa001", parent="pitch-bbb001", size=2.0)]
    spans, _ = run(entities)
    child = Span(start=MONDAY, end=date(2026, 8, 28))
    assert spans["pitch-bbb001"] == spans["task-aaa001"] == child


def test_regression_depending_on_an_ancestor_is_rejected_and_degrades_gracefully():
    child = task("aaa001", parent="pitch-bbb001", depends_on=["pitch-bbb001"])
    entities = [pitch("bbb001", owner="bo"), child]
    problems = model.validate_all(entities, CONFIG)
    assert any(
        p.entity_id == "task-aaa001" and p.field == "depends_on" and p.severity == "blocker"
        for p in problems
    )
    spans, _ = run(entities)  # the containment cycle must not take the whole schedule down
    assert {"task-aaa001", "pitch-bbb001"} <= spans.keys()


# --------------------------------------------------------------------------- #
# Explanations
# --------------------------------------------------------------------------- #


def test_a_blocker_bound_start_is_explained_by_naming_the_blocker():
    entities = [task("aaa001"), task("aaa002", owner="bo", depends_on=["task-aaa001"])]
    _, explanations = run(entities)
    assert explanations["task-aaa002"] == Explanation(
        entity_id="task-aaa002",
        text="Cannot start before 2026-08-24: task-aaa001 finishes on 2026-08-21.",
        blocker_id="task-aaa001",
    )


def test_a_worker_bound_start_is_explained_by_naming_the_worker():
    _, explanations = run([task("aaa001"), task("aaa002")])
    assert explanations["task-aaa002"] == Explanation(
        entity_id="task-aaa002",
        text="Cannot start before 2026-08-24: ann is busy until 2026-08-21.",
        worker_busy_until=date(2026, 8, 21),
    )


def test_work_that_starts_today_needs_no_explanation():
    _, explanations = run([task("aaa001")])
    assert "task-aaa001" not in explanations


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #

WORKERS = ["ann", "bo", "cy"]
PARENT_ID = "pitch-000001"


@st.composite
def dags(draw: st.DrawFn) -> list[Entity]:
    """A random valid DAG: tasks numbered in topological order, each depending
    only on lower-numbered ones, some of them hanging off a common parent."""
    count = draw(st.integers(min_value=1, max_value=6))
    tasks: list[Entity] = []
    for i in range(count):
        deps = draw(st.lists(st.integers(0, i - 1), max_size=2, unique=True)) if i else []
        tasks.append(
            Task(
                id=f"task-{i:06x}",
                kind="task",
                title=f"generated {i}",
                owner=draw(st.sampled_from([*WORKERS, None])),
                assignees=draw(st.lists(st.sampled_from(WORKERS), max_size=1, unique=True)),
                effort_weeks=draw(st.sampled_from([None, 0.1, 0.5, 1.0, 2.0])),
                priority=draw(st.integers(1, 3)),
                parent=PARENT_ID if draw(st.booleans()) else None,
                assigned_on=draw(st.sampled_from([None, MONDAY, MONDAY + timedelta(days=10)])),
                depends_on=[f"task-{d:06x}" for d in deps],
            )
        )
    if any(t.parent for t in tasks):
        tasks.append(Pitch(id=PARENT_ID, kind="pitch", title="generated parent", priority=2))
    return tasks


def workers_of(entity: Entity) -> list[str]:
    return ([entity.owner] if entity.owner else []) + entity.assignees


@settings(deadline=None)
@given(dags())
def test_property_no_dependent_ever_starts_before_its_blocker_has_finished(entities: list[Entity]):
    spans, _ = run(entities)
    for entity in entities:
        for blocker in entity.depends_on:
            assert spans[entity.id].start > spans[blocker].end


@settings(deadline=None)
@given(dags())
def test_property_a_worker_never_holds_two_overlapping_spans(entities: list[Entity]):
    spans, _ = run(entities)
    for worker in WORKERS:
        booked = sorted(
            (spans[e.id].start, spans[e.id].end)
            for e in entities
            if e.kind == "task" and worker in workers_of(e)
        )
        assert all(a[1] < b[0] for a, b in zip(booked, booked[1:], strict=False))


@settings(deadline=None)
@given(dags())
def test_property_adding_an_item_that_shares_no_worker_and_no_ancestor_never_moves_that_items_span(
    entities: list[Entity],
):
    before, _ = run(entities)
    stranger = Task(id="task-ffffff", kind="task", title="stranger", owner="zed", effort_weeks=2.0)
    after, _ = run([*entities, stranger])
    assert {i: after[i] for i in before} == before


# --------------------------------------------------------------------------- #
# The seed corpus, end to end
# --------------------------------------------------------------------------- #

GOLDEN_TODAY = date(2026, 8, 17)

GOLDEN_SPANS = {
    "proj-7e57a0": (date(2026, 8, 31), date(2026, 9, 4)),
    "pitch-1b3f9a": (date(2026, 8, 31), date(2026, 9, 4)),
    "pitch-48ea9e": (date(2026, 8, 17), date(2026, 8, 28)),
    "pitch-5e7b1c": (date(2026, 8, 17), date(2026, 9, 21)),
    "task-0e4b7a": (date(2026, 8, 31), date(2026, 9, 4)),
    "task-2b6c94": (date(2026, 8, 31), date(2026, 9, 2)),
    "task-53a9f0": (date(2026, 8, 17), date(2026, 8, 28)),
    "task-58d7c6": (date(2026, 9, 15), date(2026, 9, 21)),
    "task-5a4e39": (date(2026, 8, 17), date(2026, 8, 17)),
    "task-5c1d84": (date(2026, 8, 18), date(2026, 9, 14)),
    "task-5f062b": (date(2026, 8, 18), date(2026, 8, 24)),
}

# Every done entity in the corpus has a null assigned_on, and the shelved one is
# out of the graph, so none of them appear on the timeline at all.
GOLDEN_ABSENT = {
    "pitch-2a7f3e",
    "pitch-3c9a41",
    "task-31f6c4",
    "task-3a52d8",
    "task-3d84e9",
    "task-3e07b2",
}

GOLDEN_OVERRUNS = {
    "pitch-48ea9e": 14.0,
    "pitch-5e7b1c": 38 / 7,
    "task-2b6c94": 159 / 7,
    "task-53a9f0": 2.0,
    "task-58d7c6": 38 / 7,
    "task-5a4e39": 3 / 7,
    "task-5c1d84": 31 / 7,
    "task-5f062b": 10 / 7,
}


def test_the_seed_corpus_schedules_to_the_golden_timeline(seed_root: Path):
    entities, config = model.load_repo(seed_root)
    spans, _ = schedule(entities, config, GOLDEN_TODAY)
    assert {i: (s.start, s.end) for i, s in spans.items()} == GOLDEN_SPANS


def test_the_seed_corpus_golden_overruns_and_flags(seed_root: Path):
    entities, config = model.load_repo(seed_root)
    spans, _ = schedule(entities, config, GOLDEN_TODAY)
    assert not GOLDEN_ABSENT & spans.keys()
    overruns = {i: s.overruns_cycle_weeks for i, s in spans.items() if s.overruns_cycle_weeks}
    assert overruns == pytest.approx(GOLDEN_OVERRUNS)
    assert not [s for s in spans.values() if s.estimated or s.unowned]
    assert not [s for s in spans.values() if s.unscheduled or s.historical]
