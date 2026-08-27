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

import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from openproj import model
from openproj.model import Config, Cycle, Pitch, Record, Task
from openproj.schedule import Explanation, Span, schedule, working_days_after

MONDAY = date(2026, 8, 17)

CONFIG = Config(
    nominal_availability=1.0,
    holidays=[],
    cycles={36: (date(2026, 6, 22), date(2026, 8, 14)), 37: (date(2026, 8, 17), date(2026, 10, 9))},
)

# Availability != 1.0, so that the "never divide by availability" guard below can
# actually fail. Every other test uses CONFIG; this exists for that one guard.
HALF_TIME = CONFIG.model_copy(update={"nominal_availability": 0.6})


def task(suffix: str, *, owner: str | None = "ann", size: float | None = 1.0, **fields) -> Task:
    return Task(
        id=f"task-{suffix}", kind="task", title=suffix, owner=owner, person_weeks=size, **fields
    )


def pitch(suffix: str, *, owner: str | None = "ann", size: float | None = None, **fields) -> Pitch:
    return Pitch(
        id=f"pitch-{suffix}", kind="pitch", title=suffix, owner=owner, person_weeks=size, **fields
    )


def run(
    records: list[Record],
    today: date = MONDAY,
    config: Config = CONFIG,
    availability: dict[str, float] | None = None,
) -> tuple[dict[str, Span], dict[str, Explanation]]:
    """`availability` is a convenience: it becomes cycle 36's roster, which is the
    cycle the helpers below put records in by default."""
    if availability is not None:
        config = config.with_plans(
            [
                Cycle(
                    cycle=36,
                    starts_on=date(2026, 6, 22),
                    build_weeks=6.0,
                    availability=availability,
                )
            ]
        )
    return schedule(records, config, today)


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
    """The seed's year-end shutdown: 24 and 25 December 2026 are not working days."""
    config = model.load_config(seed_root)
    assert working_days_after(date(2026, 12, 21), 1.0, config) == date(2026, 12, 29)


def test_a_size_too_large_for_the_calendar_stops_at_the_last_day_it_can_name():
    """`person_weeks: 1000000` is one PATCH, and it used to be a 500 on every page.

    The walk added a day at a time until `timedelta` ran past year 9999 and
    raised OverflowError — out of `build_index`, so `/`, `/graph`, `/timeline`,
    `/people` and `/api/index.json` all answered 500 to every reader, for a
    committed value that no rule refuses. Two things are wrong with walking it
    at all: the exception, and the five million iterations before it.

    The end of the calendar is the honest answer. A bar that runs off the end of
    time is what "somebody typed a million weeks" looks like, and it is a page
    rather than a stack trace.
    """
    assert working_days_after(MONDAY, 1_000_000.0, CONFIG) == date.max
    assert working_days_after(MONDAY, 1e9, CONFIG) == date.max
    # Not by exhausting the calendar first: the bound is taken before the walk,
    # so a size nobody meant costs no more than a size somebody did.
    started = time.monotonic()
    working_days_after(MONDAY, 1e12, CONFIG)
    assert time.monotonic() - started < 1.0


def test_a_size_that_only_just_fits_is_still_walked_exactly():
    """The clamp must not round off a plan that genuinely reaches far out."""
    assert working_days_after(MONDAY, 52.0, CONFIG) == date(2027, 8, 13)
    assert working_days_after(MONDAY, 520.0, CONFIG) < date.max


# --------------------------------------------------------------------------- #
# The nine steps
# --------------------------------------------------------------------------- #


def test_step1_shelved_records_are_outside_the_graph_and_get_no_span():
    shelved = task("aaa001", status="shelved")
    spans, _ = run([shelved, task("aaa002", owner="bo", depends_on=["task-aaa001"])])
    assert "task-aaa001" not in spans
    assert spans["task-aaa002"].start == MONDAY


def test_step2_a_dependency_cycle_leaves_its_members_and_descendants_unscheduled():
    """schedule() never raises: a cycle costs you those records, not the index."""
    records = [
        task("aaa001", depends_on=["task-aaa002"]),
        task("aaa002", owner="bo", depends_on=["task-aaa001"]),
        task("aaa003", owner="cy", depends_on=["task-aaa001"]),
        task("aaa004", owner="di"),
    ]
    spans, _ = run(records)
    caught = ("task-aaa001", "task-aaa002", "task-aaa003")
    assert [spans[i].unscheduled for i in caught] == [True, True, True]
    assert spans["task-aaa001"].start == spans["task-aaa001"].end == MONDAY
    assert spans["task-aaa004"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


def test_a_record_nobody_has_sized_gets_no_floor_span_from_a_dependency_cycle_either():
    """The stalled path wrote its placeholder before anybody asked about the size.

    Two unsized tasks pointing at each other came back at `start=end=today`,
    `unscheduled=True` — which the table draws as Start 27 Aug / End 27 Aug,
    styled `derived` exactly like a forecast and sorting to the top of a
    Start-ascending sort, because only the timeline reads that flag. That is the
    symptom §2 of the design and the leaf path's own comment both argue at length
    must never happen, reached by the one route neither of them was guarding.
    """
    records = [
        task("aaa001", size=None, depends_on=["task-aaa002"]),
        task("aaa002", owner="bo", size=None, depends_on=["task-aaa001"]),
    ]
    spans, _ = run(records)
    assert spans == {}


def test_an_unsized_child_caught_in_a_cycle_does_not_pin_its_pitch_to_today():
    """The other half of the same floor span, one level up.

    The rollup is `min(child.start)`/`max(child.end)` and cannot see
    `unscheduled`, so a stalled unsized child at today dragged its pitch's start
    back to today and had its overrun measured against a fabricated end — with
    nothing on the parent row to mark that any of it was invented.
    """
    records = [
        pitch("bbb001", owner="cy"),
        task("aaa001", parent="pitch-bbb001", size=None, depends_on=["task-aaa002"]),
        task("aaa002", owner="bo", size=None, depends_on=["task-aaa001"]),
        task("aaa003", parent="pitch-bbb001", size=2.0, start_date=date(2026, 9, 7)),
    ]
    spans, _ = run(records)
    assert "task-aaa001" not in spans
    assert spans["pitch-bbb001"].start == date(2026, 9, 7)


def test_step3_done_work_is_a_historical_point_marker_or_no_span_at_all():
    dated = task("aaa001", status="done", start_date=date(2026, 7, 1))
    spans, _ = run([dated, task("aaa002", status="done")])
    july = date(2026, 7, 1)
    assert spans["task-aaa001"] == Span(
        start=july, end=july, historical=True, budget_weeks=1.0, elapsed_weeks=None
    )
    assert "task-aaa002" not in spans


def test_step3_a_done_record_has_no_length_rather_than_a_fifth_of_a_week():
    """These two dates are one day, because nothing records where work ENDED yet.

    Read back through `_elapsed_weeks` that day was 0.2 — a fifth of a week,
    which is not a length but today twice, and which the comment beside
    `Span.elapsed_weeks` names as the thing it must not store. It travelled: a
    done pitch bet at eight printed "8.0 · 0.2 in tasks" on its own page, and
    `_rollup_problems` could not fire on a finished bet at any size, because a
    fifth of a week is inside every box there is.

    §4 of `design/time-model.md` stores an `end_date` somebody typed, and then
    this becomes a measurement instead of None.
    """
    spans, _ = run([task("aaa001", status="done", start_date=date(2026, 7, 1), size=8.0)])
    assert spans["task-aaa001"].elapsed_weeks is None


def test_step3_a_done_parent_stays_historical_even_with_a_live_child():
    records = [pitch("bbb001", status="done"), task("aaa001", parent="pitch-bbb001")]
    spans, _ = run(records)
    assert "pitch-bbb001" not in spans


def test_step4_duration_is_the_stated_size_at_nominal_availability():
    spans, _ = run([task("aaa001", size=2.0)])
    assert spans["task-aaa001"] == Span(
        start=MONDAY, end=date(2026, 8, 28), budget_weeks=2.0, elapsed_weeks=2.0
    )


def test_step4_a_record_nobody_has_sized_gets_no_span_at_all():
    """Not a span marked as a guess, and not an `unscheduled` one either.

    It used to be the first: half a week nobody had typed, placed, booked against
    its worker and drawn as a bar with `estimated=True` on it — a flag three of
    its readers dropped. An `unscheduled` span would be the second, and that is
    `start=end=today`: the table would draw Start and End of today, styled
    `derived` exactly like a real forecast and sorting to the top of a
    Start-ascending sort, while the timeline left the record out. No span is the
    answer a childless project already gives, and every view already copes.
    """
    spans, explanations = run([task("aaa001", size=None), task("aaa002", size=2.0)])
    assert "task-aaa001" not in spans
    assert "task-aaa001" not in explanations
    # And it books nothing: the sized task starts on the floor rather than after
    # a week of somebody else's invented work.
    assert spans["task-aaa002"] == Span(
        start=MONDAY, end=date(2026, 8, 28), budget_weeks=2.0, elapsed_weeks=2.0
    )


def test_step4_an_unsized_child_leaves_its_parent_the_dates_of_the_rest():
    """A floor span would be worse than none, and this is where it would show.

    The rollup is `min(child.start)`/`max(child.end)` with no `unscheduled` in
    its constructor, so one unsized child at `start=end=today` would pin the
    pitch's start to today and measure its overrun against a fabricated end,
    with nothing on the parent row marking it.
    """
    records = [
        pitch("bbb001"),
        task("aaa001", parent="pitch-bbb001", size=None),
        task("aaa002", parent="pitch-bbb001", size=2.0, depends_on=["task-aaa003"]),
        task("aaa003", size=1.0, owner="di"),
    ]
    spans, _ = run(records)
    assert "task-aaa001" not in spans
    assert spans["pitch-bbb001"] == spans["task-aaa002"].model_copy(
        update={
            "overruns_cycle_weeks": spans["pitch-bbb001"].overruns_cycle_weeks,
            # And the parent's own box, which is its own and not its child's: this
            # pitch carries no appetite, so there is nothing for `_rollup_problems`
            # to hold the rolled-up length against, while the task under it was bet
            # at two weeks. `elapsed_weeks` is deliberately NOT neutralised here —
            # the parent's dates are exactly the one sized child's, so its length
            # has to be too, and that is half of what this test is claiming.
            "budget_weeks": None,
        }
    )


def test_a_pitch_whose_children_are_all_unsized_is_not_scheduled_as_a_leaf():
    """Being a container is a property of the plan, not of who came back with a span.

    Every live child used to get one, so an empty `kids` meant "no children" and
    nothing else. With no default appetite it also means "children, none of them
    placeable" — and a pitch in that state fell past the rollup into the LEAF
    path, where it was placed against its own bet and BOOKED its own assignees.
    That breaks the second invariant in the module docstring: the pitch holds a
    booking while `Index._charged` skips it as a rollup and charges nobody, so
    the same person is priced twice by the scheduler and once by the ledger. The
    sized task below is the visible half — it queued behind a bet that should
    never have taken a slot.
    """
    records = [
        pitch("bbb001", owner="ann", size=2.0),
        task("aaa001", parent="pitch-bbb001", size=None),
        task("aaa002", parent="pitch-bbb001", size=None, owner="bo"),
        task("aaa003", owner="ann", size=1.0),
    ]
    spans, _ = run(records)
    assert "pitch-bbb001" not in spans, "a container with nothing placeable under it draws nothing"
    assert spans["task-aaa003"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


def test_a_task_that_exactly_fills_its_bet_is_level_with_the_box_and_not_over():
    """The box and the contents are both read in whole working days, or `=` cannot happen.

    `working_days_after` lays 2.5 weeks out as `ceil(12.5)` = thirteen days and
    `_elapsed_weeks` counts them back as 2.6, so the contents were ALWAYS the
    ceiling of the box: equal only when the size happened to be a multiple of a
    fifth of a week, and larger otherwise. `_rollup_problems` fires on strict
    `>`, so this pitch — bet at 2.5, holding one task bet at 2.5 on the same
    person, the design's `=` row exactly — warned that it needed 2.6 more than
    the 2.5 it had. Any fractional availability makes that the normal case.
    """
    records = [
        pitch("bbb001", owner="ann", size=2.5),
        task("aaa001", parent="pitch-bbb001", owner="ann", size=2.5),
    ]
    spans, _ = run(records)
    box = spans["pitch-bbb001"]
    assert box.budget_weeks == box.elapsed_weeks == pytest.approx(2.6)
    # And the leaf agrees with itself, which is where the bias came from: its box
    # and its contents are the same placement read from two ends.
    leaf = spans["task-aaa001"]
    assert leaf.budget_weeks == leaf.elapsed_weeks == pytest.approx(2.6)


def test_step5_ordering_is_by_priority_then_id():
    """Order is only observable through capacity: all three want the same worker."""
    records = [task("aaa001"), task("aaa002"), task("aaa003", priority="high")]
    spans, _ = run(records)
    assert spans["task-aaa003"].start == MONDAY
    assert spans["task-aaa001"].start == date(2026, 8, 24)
    assert spans["task-aaa002"].start == date(2026, 8, 31)


def test_step5_a_cycle_closed_by_a_containment_edge_does_not_raise():
    """depends_on alone is acyclic, so step 2 flags nothing — but the ordering
    graph adds child -> parent edges and closes the loop. A naive
    lexicographical_topological_sort raises NetworkXUnfeasible here and takes the
    whole page down over one bad record."""
    records = [
        # Bet at something, because the pitch is what this asserts a span for and
        # a record nobody has sized gets none — not even the `unscheduled`
        # placeholder this pair lands on. A pitch IS a bet, so a size on it is the
        # normal case rather than a prop for the test.
        pitch("bbb001", owner="bo", size=2.0),
        task("aaa001", parent="pitch-bbb001", depends_on=["pitch-bbb001"]),
    ]
    spans, _ = run(records)
    assert {"pitch-bbb001", "task-aaa001"} <= set(spans)


def test_step6_a_past_start_date_does_not_pull_work_into_the_past():
    """ready is max(today, start_date, blockers) — not `start_date or today`,
    which would schedule an item whose start date was last week into last week."""
    spans, _ = run([task("aaa001", start_date=date(2026, 8, 13), size=2.0)])
    assert spans["task-aaa001"] == Span(
        start=MONDAY, end=date(2026, 8, 28), budget_weeks=2.0, elapsed_weeks=2.0
    )


def test_step6_a_leaf_waits_for_today_its_start_date_and_its_blockers():
    records = [
        task("aaa001"),
        task("aaa002", owner="bo", depends_on=["task-aaa001"]),
        task("aaa003", owner="cy", start_date=date(2026, 9, 1)),
    ]
    spans, _ = run(records)
    assert spans["task-aaa002"].start == date(2026, 8, 24)  # the working day after Friday's end
    assert spans["task-aaa003"].start == date(2026, 9, 1)


def test_step7_one_item_per_worker_at_a_time_but_unowned_work_is_unlimited():
    records = [
        task("aaa001", owner=None),
        task("aaa002", owner=None),
        task("aaa003", reviewers=["bo"]),
        task("aaa004", owner="bo"),
    ]
    spans, _ = run(records)
    assert spans["task-aaa001"] == Span(
        start=MONDAY,
        end=date(2026, 8, 21),
        unowned=True,
        # Nobody on it is one notional person at the nominal rate, which is what
        # `_duration_weeks` divides by — so an unowned week is still a week.
        budget_weeks=1.0,
        elapsed_weeks=1.0,
    )
    assert spans["task-aaa002"].start == MONDAY
    assert spans["task-aaa004"].start == MONDAY  # reviewing is not doing


def test_step7_assignees_consume_capacity_and_are_not_unowned():
    records = [task("aaa001", owner=None, assignees=["cy"]), task("aaa002", owner="cy")]
    spans, _ = run(records)
    assert spans["task-aaa001"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )
    assert spans["task-aaa002"].start == date(2026, 8, 24)


def test_step8_a_parent_spans_from_its_first_child_to_its_last():
    records = [
        pitch("bbb001", owner="cy", size=4.0),
        task("aaa001", parent="pitch-bbb001"),
        task("aaa002", owner="bo", parent="pitch-bbb001", depends_on=["task-aaa001"]),
    ]
    spans, _ = run(records)
    # The two numbers differ here, and this is the shape they were added for: the
    # bet buys four weeks with cy on it, and the two tasks under it take two — one
    # each, on different people, so they run side by side. `_rollup_problems` is
    # the reader, and this is the case where it stays quiet.
    assert spans["pitch-bbb001"] == Span(
        start=MONDAY, end=date(2026, 8, 28), budget_weeks=4.0, elapsed_weeks=2.0
    )


def test_step9_finishing_after_the_cycle_builds_records_the_overrun_in_weeks():
    """Against the end of BUILD, not the end of the window: cool-down is not
    build time, and measuring to the window's end understated every overrun by
    the cool-down length and hid the small ones entirely."""
    spans, _ = run([task("aaa001", cycle=36), task("aaa002", owner="bo", cycle=37)])

    # Cycle 36 builds until 2026-07-31; cycle 37 until 2026-09-25.
    assert spans["task-aaa001"].overruns_cycle_weeks == pytest.approx(3.0)
    assert spans["task-aaa002"].overruns_cycle_weeks is None


def test_an_overrun_is_measured_against_build_and_not_against_cool_down():
    """The same span, the same cycle, two cool-down settings."""
    from openproj.model import Config

    window = {36: (date(2026, 6, 22), date(2026, 8, 14))}
    none = Config(cycles=window, cooldown_weeks=0.0, holidays=CONFIG.holidays)
    two = Config(cycles=window, cooldown_weeks=2.0, holidays=CONFIG.holidays)

    without, _ = run([task("aaa001", cycle=36)], config=none)
    with_cooldown, _ = run([task("aaa001", cycle=36)], config=two)

    assert with_cooldown["task-aaa001"].overruns_cycle_weeks == pytest.approx(
        without["task-aaa001"].overruns_cycle_weeks + 2.0
    )


# --------------------------------------------------------------------------- #
# Regression guards
# --------------------------------------------------------------------------- #


def test_regression_children_are_ordered_before_their_parent():
    """The parent outranks both children on (priority, id), so only the
    containment edges can keep it from being visited first — and a parent
    visited first has no child spans to build its own span from."""
    records = [
        pitch("bbb001", owner=None, priority="high"),
        task("aaa001", priority="low", parent="pitch-bbb001"),
        task("aaa002", owner="bo", priority="low", parent="pitch-bbb001", size=2.0),
    ]
    spans, _ = run(records)
    # No size on the pitch, so no box: `budget_weeks` stays None while the rolled
    # up length is a real two weeks. A bet nobody made cannot be exceeded.
    assert spans["pitch-bbb001"] == Span(start=MONDAY, end=date(2026, 8, 28), elapsed_weeks=2.0)


def test_step9_a_cycle_with_no_configured_dates_is_not_an_overrun():
    """A pitch may name a cycle nobody has dated yet. Indexing config.cycles
    directly turns that into a KeyError for the whole schedule."""
    spans, _ = run([task("aaa001", cycle=99)])
    assert spans["task-aaa001"].overruns_cycle_weeks is None


def test_a_size_is_person_weeks_and_the_people_on_it_divide_it():
    """D-C4: a size is the work ONE person would need, so three names on a
    six-week bet is two elapsed weeks. Staffing something makes it finish sooner,
    which is what a room believes when it puts three people on one pitch.

    This reverses D1 and the test that used to sit here, which asserted a size was
    never divided. That was right about the arithmetic the code did and wrong
    about what the number meant."""
    alone, _ = run([pitch("bbb001", owner="ann", size=6.0)])
    shared, _ = run([pitch("bbb001", owner="ann", assignees=["bo", "cy"], size=6.0)])

    assert alone["pitch-bbb001"].end == date(2026, 9, 25)  # six working weeks
    assert shared["pitch-bbb001"].end == date(2026, 8, 28)  # two


def test_an_owner_who_is_also_an_assignee_is_one_person():
    """Most owners are. Counted twice they were booked twice, and now that the
    people on a bet divide it, they would have halved it single-handed."""
    once, _ = run([pitch("bbb001", owner="ann", size=4.0)])
    twice, _ = run([pitch("bbb001", owner="ann", assignees=["ann"], size=4.0)])

    assert once["pitch-bbb001"] == twice["pitch-bbb001"]


def test_availability_stretches_the_work_of_whoever_is_slower():
    """One person at 60% takes a three-week bet five weeks. That IS the answer,
    not the bug the old spec called out — that draft was only wrong under D1's
    reading of what a size means."""
    full, _ = run([pitch("bbb001", owner="ann", size=3.0, cycle=36)])
    half, _ = run([pitch("bbb001", owner="ann", size=3.0, cycle=36)], availability={"ann": 0.5})

    assert full["pitch-bbb001"].end == date(2026, 9, 4)  # three working weeks
    assert half["pitch-bbb001"].end == date(2026, 9, 25)  # six


def test_somebody_nobody_rated_works_at_the_nominal_rate():
    """Absent from the map means nobody said otherwise, not unavailable. A roster
    that must name everybody to schedule anybody goes stale and takes the dates
    with it."""
    rated, _ = run([pitch("bbb001", owner="ann", size=3.0, cycle=36)], availability={"zz": 0.1})
    unrated, _ = run([pitch("bbb001", owner="ann", size=3.0, cycle=36)])

    # Dates only: the rated run has a cycle RECORD, whose own build length also
    # decides the overrun, and this test is about the rate rather than the box.
    assert rated["pitch-bbb001"].start == unrated["pitch-bbb001"].start
    assert rated["pitch-bbb001"].end == unrated["pitch-bbb001"].end


def test_unowned_work_is_one_notional_person_rather_than_a_division_by_zero():
    spans, _ = run([task("aaa001", owner=None, size=2.0)])

    assert spans["task-aaa001"].unowned
    assert spans["task-aaa001"].end == date(2026, 8, 28)  # two working weeks


def test_regression_a_task_and_a_pitch_of_the_same_size_take_the_same_time():
    spans, _ = run([task("aaa001", size=2.0), pitch("bbb001", owner="bo", size=2.0)])
    assert spans["task-aaa001"] == spans["pitch-bbb001"]


def test_regression_done_work_neither_occupies_the_future_nor_consumes_capacity():
    finished = task("aaa001", status="done", start_date=date(2026, 7, 1), size=4.0)
    records = [finished, task("aaa002")]
    spans, _ = run(records)
    assert spans["task-aaa001"].end == date(2026, 7, 1)
    assert spans["task-aaa002"].start == MONDAY


def test_regression_a_parent_does_not_double_book_the_owner_of_its_only_child():
    records = [pitch("bbb001", size=2.0), task("aaa001", parent="pitch-bbb001", size=2.0)]
    spans, _ = run(records)
    # Identical down to the two weeks numbers: the pitch was bet at the same size
    # as its only child and holds the same person, so the box and the contents are
    # the same two weeks whichever end you read them from.
    child = Span(start=MONDAY, end=date(2026, 8, 28), budget_weeks=2.0, elapsed_weeks=2.0)
    assert spans["pitch-bbb001"] == spans["task-aaa001"] == child


def test_regression_depending_on_an_ancestor_is_rejected_and_degrades_gracefully():
    child = task("aaa001", parent="pitch-bbb001", depends_on=["pitch-bbb001"])
    # Sized for the same reason as the containment-cycle test above: the claim
    # here is that both records still come back, and an unsized one comes back
    # from nowhere at all.
    records = [pitch("bbb001", owner="bo", size=2.0), child]
    problems = model.validate_all(records, CONFIG)
    assert any(
        p.record_id == "task-aaa001" and p.field == "depends_on" and p.severity == "blocker"
        for p in problems
    )
    spans, _ = run(records)  # the containment cycle must not take the whole schedule down
    assert {"task-aaa001", "pitch-bbb001"} <= spans.keys()


# --------------------------------------------------------------------------- #
# Explanations
# --------------------------------------------------------------------------- #


def test_a_blocker_bound_start_is_explained_by_naming_the_blocker():
    records = [task("aaa001"), task("aaa002", owner="bo", depends_on=["task-aaa001"])]
    _, explanations = run(records)
    assert explanations["task-aaa002"] == Explanation(
        record_id="task-aaa002",
        text="Cannot start before 2026-08-24: task-aaa001 finishes on 2026-08-21.",
        blocker_id="task-aaa001",
    )


def test_a_worker_bound_start_is_explained_by_naming_the_worker():
    _, explanations = run([task("aaa001"), task("aaa002")])
    assert explanations["task-aaa002"] == Explanation(
        record_id="task-aaa002",
        text="Cannot start before 2026-08-24: ann is busy until 2026-08-21.",
        worker_busy_until=date(2026, 8, 21),
    )


def test_work_that_starts_today_needs_no_explanation():
    _, explanations = run([task("aaa001")])
    assert "task-aaa001" not in explanations


def test_a_stated_start_the_floor_overrode_is_the_one_case_that_needs_a_sentence():
    """`if start <= floor: return None` was the whole of this branch, and it is
    exactly where a reader needs a sentence most: the record says 2026-08-10 in
    its frontmatter, the page says 2026-08-17 under a column labelled "Start
    date", and nothing between the two said why. Nothing is holding this up — no
    blocker, no busy worker — so the two fields that name those stay empty and the
    sentence names the calendar instead.
    """
    _, explanations = run([task("aaa001", status="ready", start_date=date(2026, 8, 10))])

    assert explanations["task-aaa001"] == Explanation(
        record_id="task-aaa001",
        text="Starts on 2026-08-17: the 2026-08-10 you set has passed and work has not begun.",
    )


def test_a_start_date_a_record_is_already_working_to_is_not_explained_away():
    """The same date on a record that says the work began is not overridden at
    all — `_place` takes it as the start — so there is nothing to explain, and a
    sentence saying it "has passed and work has not begun" would contradict the
    status two rows above it on the same page."""
    began = [task("aaa001", status="in_progress", start_date=date(2026, 8, 10))]

    spans, explanations = run(began)

    assert spans["task-aaa001"].start == date(2026, 8, 10)
    assert "task-aaa001" not in explanations


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #

WORKERS = ["ann", "bo", "cy"]
PARENT_ID = "pitch-000001"


@st.composite
def dags(draw: st.DrawFn) -> list[Record]:
    """A random valid DAG: tasks numbered in topological order, each depending
    only on lower-numbered ones, some of them hanging off a common parent."""
    count = draw(st.integers(min_value=1, max_value=6))
    tasks: list[Record] = []
    for i in range(count):
        deps = draw(st.lists(st.integers(0, i - 1), max_size=2, unique=True)) if i else []
        tasks.append(
            Task(
                id=f"task-{i:06x}",
                kind="task",
                title=f"generated {i}",
                owner=draw(st.sampled_from([*WORKERS, None])),
                assignees=draw(st.lists(st.sampled_from(WORKERS), max_size=1, unique=True)),
                person_weeks=draw(st.sampled_from([None, 0.1, 0.5, 1.0, 2.0])),
                priority=draw(st.sampled_from(["high", "medium", "low"])),
                parent=PARENT_ID if draw(st.booleans()) else None,
                start_date=draw(st.sampled_from([None, MONDAY, MONDAY + timedelta(days=10)])),
                depends_on=[f"task-{d:06x}" for d in deps],
            )
        )
    if any(t.parent for t in tasks):
        tasks.append(Pitch(id=PARENT_ID, kind="pitch", title="generated parent", priority="medium"))
    return tasks


def workers_of(record: Record) -> list[str]:
    return ([record.owner] if record.owner else []) + record.assignees


@settings(deadline=None)
@given(dags())
def test_property_no_dependent_ever_starts_before_its_blocker_has_finished(records: list[Record]):
    spans, _ = run(records)
    for record in records:
        # Every leaf the generator sizes is placed, and every leaf it does not is
        # absent — asserted rather than worked around, because the loop below has
        # to skip the absent ones and a skip that is never checked is a property
        # that quietly stops testing anything.
        if record.kind == "task":
            assert (record.person_weeks is not None) == (record.id in spans)
        for blocker in record.depends_on:
            # A blocker with no span holds nothing back: `_place` skips a target
            # that is not in `spans`, which is the branch a childless project has
            # always taken and is now also the one an unsized record takes. The
            # claim is about the pairs the scheduler placed.
            if record.id in spans and blocker in spans:
                assert spans[record.id].start > spans[blocker].end


@settings(deadline=None)
@given(dags())
def test_property_a_worker_never_holds_two_overlapping_spans(records: list[Record]):
    spans, _ = run(records)
    for worker in WORKERS:
        booked = sorted(
            (spans[e.id].start, spans[e.id].end)
            for e in records
            if e.kind == "task" and worker in workers_of(e) and e.id in spans
        )
        assert all(a[1] < b[0] for a, b in zip(booked, booked[1:], strict=False))


@settings(deadline=None)
@given(dags())
def test_property_adding_an_item_that_shares_no_worker_and_no_ancestor_never_moves_that_items_span(
    records: list[Record],
):
    before, _ = run(records)
    stranger = Task(id="task-ffffff", kind="task", title="stranger", owner="zed", person_weeks=2.0)
    after, _ = run([*records, stranger])
    assert {i: after[i] for i in before} == before


# --------------------------------------------------------------------------- #
# The seed corpus, end to end
# --------------------------------------------------------------------------- #

GOLDEN_TODAY = date(2026, 8, 17)

# EVERY DATE BELOW WAS DERIVED BY HAND. DO NOT REGENERATE THEM.
#
# Read this before growing the corpus. These eighteen spans are the only place in
# the repository that asserts "the scheduler computes the RIGHT dates" rather than
# "the scheduler agrees with itself". Recompute them by running `schedule` and
# pasting the answer and the assertion becomes a tautology that passes under every
# possible bug — a size divided by the wrong rate, a holiday skipped, an inherited
# edge dropped, the `begun` break inverted. There would then be nothing left in the
# suite that could tell. Everything else in this corpus can be rebuilt; this cannot.
#
# So the procedure, when a new record adds a key here:
#   1. Confirm the existing spans did NOT move. A new PLANNED record must share no
#      worker and no ancestor with an existing one — that is exactly as narrow as
#      the property in `test_property_adding_an_item_that_shares_no_worker_and_
#      no_ancestor_never_moves_that_items_span`, and the looser claim is false
#      under a capacity-1 model. Unplanned rungs (issues, notes) never reach the
#      scheduler and are free.
#   2. Derive the new span from the algorithm — `_duration_weeks` (size / sum of
#      rates), `_availability_of` (rates come from the cycle of the BET, i.e. the
#      parent pitch), `blockers_of`'s ancestor loop, `_place`'s `begun` branch,
#      `working_days_after` and the holiday list — and WRITE THE ARITHMETIC DOWN.
#   3. Only then run it. If the two disagree, stop: it is either the derivation or
#      the scheduler, and which one it is matters more than the branch.
#
# Re-derived 2026-08-16 for D-C4: a size is person-weeks and the people on it
# divide it. Every record with more than one worker moved; the single-worker ones
# did not, which is the check that the change did what it says. Two were verified
# by hand against the definition rather than copied out of the run:
#   task-53a9f0  size 2.0, one worker  -> 2 elapsed weeks, 08-17 .. 08-28
#   pitch-48ea9e size 2.0, two workers -> 1 elapsed week,  08-17 .. 08-21
# Three of these moved when work already in progress stopped being floored at
# today. `task-53a9f0` is `in_progress` and starts 2026-08-13, four days before
# GOLDEN_TODAY, so it now starts on the day it actually started; `pitch-5e7b1c`
# is its parent and rolls up to it; `pitch-1b3f9a` is `ready` with no
# `start_date` and moves earlier only because a worker comes free sooner. Each
# was re-derived by hand against the new rule, not copied out of a failure.
#
# The seven hearth-island keys were added 2026-08-23. Every one of the eleven
# above was measured unmoved first, then each new one was derived by hand against
# the algorithm and only afterwards compared with the run; the two agreed on all
# seven. The working is in `THE HEARTH ISLAND` below, and the four mechanisms it
# turns on are named there. Cycles 37 and 38 are dated by `cycles/*.md` records
# and not by `config/cycles.yaml`, so `Config.with_plans` is in the derivation too.
GOLDEN_SPANS = {
    "proj-7e57a0": (date(2026, 8, 24), date(2026, 8, 28)),
    "pitch-1b3f9a": (date(2026, 8, 27), date(2026, 9, 2)),
    "pitch-48ea9e": (date(2026, 8, 17), date(2026, 8, 21)),
    "pitch-5e7b1c": (date(2026, 8, 13), date(2026, 9, 21)),
    "task-0e4b7a": (date(2026, 8, 24), date(2026, 8, 28)),
    "task-2b6c94": (date(2026, 8, 24), date(2026, 8, 26)),
    "task-53a9f0": (date(2026, 8, 13), date(2026, 8, 26)),
    "task-58d7c6": (date(2026, 9, 15), date(2026, 9, 21)),
    "task-5a4e39": (date(2026, 8, 17), date(2026, 8, 17)),
    "task-5c1d84": (date(2026, 8, 18), date(2026, 9, 14)),
    "task-5f062b": (date(2026, 8, 18), date(2026, 8, 24)),
    # --- the hearth island, under prod-7c2b81 -> proj-9a4c25 ----------------
    "proj-9a4c25": (date(2026, 8, 13), date(2027, 1, 21)),
    "pitch-6f2d18": (date(2026, 8, 13), date(2026, 8, 28)),
    "pitch-7b3e94": (date(2026, 8, 31), date(2027, 1, 21)),
    "task-6a5c02": (date(2026, 8, 17), date(2026, 8, 28)),
    "task-6b7d31": (date(2026, 8, 13), date(2026, 8, 19)),
    "task-7c8e40": (date(2026, 8, 31), date(2026, 9, 11)),
    "task-7d9f52": (date(2026, 12, 21), date(2027, 1, 21)),
}

# THE HEARTH ISLAND — the arithmetic behind the seven keys above.
#
# The calendar. 2026-08-17 is a Monday (pinned by `pitch-48ea9e`, five working
# days 08-17..08-21). 08-13 Thu, 08-28 Fri, 08-31 Mon, 09-11 Fri, 09-14 Mon,
# 11-30 Mon, 12-21 Mon, 2027-01-21 Thu, 2027-01-22 Fri, 2027-01-25 Mon.
#
# The two cycle records, resolved by `Config._resolve`:
#   37  starts 2026-08-17, NO `reviews_on` -> assumed_review True;
#       reviews_on = starts + _DEFAULT_BUILD_DAYS(28) = 09-14;
#       builds_until = previous working day = 2026-09-11;
#       cycle 38 exists and starts later, so assumed_end False (the `after`
#       branch, which nothing else in either corpus takes) and ends_on = 11-29;
#       build_weeks = 20 working days / 5 = 4.0.
#       rates: redpollard 0.5, chiffchaffy 0.25, Whimbrelson 1.0.
#   38  starts 2026-11-30, reviews_on 2027-01-25 -> assumed_review False;
#       builds_until = previous working day = 2027-01-22;
#       no later cycle, so assumed_end True and
#       ends_on = reviews + (round(2.0*7) - 1) = 2027-02-07;
#       build_weeks = 40 working days MINUS the four WEEKDAY holidays inside it
#       (12-24 Thu, 12-25 Fri, 12-31 Thu, 01-01 Fri; 12-26 is a Saturday and
#       costs nothing) = 36 / 5 = 7.2, not 8.0. That subtraction is the one
#       number in the repository that has to know about Christmas.
#       rates: Whimbrelson 0.5, stonechatty 0.5.
#
# The four leaves. `_availability_of` reads the cycle of the BET, so a task takes
# its parent pitch's roster and carries no `cycle:` of its own.
#
#   task-6a5c02  size 1.5; workers dedup to [redpollard, chiffchaffy] (redpoll is
#                owner AND assignee and counts once); cycle 37 rates 0.5 + 0.25
#                = 0.75; 1.5 / 0.75 = 2.0 weeks = 10 working days. No blockers.
#                `in_progress` with a `start_date`, so `begun`: starts on
#                2026-08-17 and today does not move it.
#                08-17,18,19,20,21,24,25,26,27,28          -> 08-17 .. 08-28
#
#   task-6b7d31  size 0.5; one worker [redpollard] at 0.5; 0.5 / 0.5 = 1.0 week
#                = 5 working days. `begun`, starting 2026-08-13 — FOUR DAYS
#                BEFORE GOLDEN_TODAY, so the floor does not apply.
#                08-13,14,17,18,19                          -> 08-13 .. 08-19
#                redpollard is already booked 08-17..08-28 by task-6a5c02 and
#                this span OVERLAPS it. It does not move, because `_place`
#                breaks out of the contention loop when `begun`. That is the
#                only thing holding this date: turn either record to `ready` and
#                this one lands 08-31..09-04 instead.
#
#   task-7c8e40  size 1.0; one worker [Whimbrelson] at 0.5 (cycle 38, read
#                although the span lands in September — the rate belongs to the
#                bet, not to the calendar); 1.0 / 0.5 = 2.0 weeks = 10 days.
#                It has NO `depends_on` and NO `start_date`. Its start comes
#                entirely from `pitch-7b3e94`'s `depends_on: [pitch-6f2d18]`,
#                INHERITED through `blockers_of`'s ancestor loop: pitch-6f2d18
#                ends 08-28, next working day 08-31.
#                08-31,09-01,02,03,04,07,08,09,10,11        -> 08-31 .. 09-11
#                Delete the ancestor loop and this drops ten working days to the
#                floor. It is the only inherited edge in GOLDEN_SPANS.
#
#   task-7d9f52  size 2.0; one worker [stonechatty] at 0.5; 4.0 weeks = 20 days.
#                Blockers in `blockers_of` order: task-7c8e40 (ends 09-11 ->
#                ready 09-14); issue-9f2b48, which is an ISSUE and therefore not
#                in `live`, not in `spans`, and skipped by the `target in spans`
#                guard — it contributes NOTHING, which is the whole of the
#                `off_plan_deps` claim; and pitch-6f2d18, which loses at 08-28.
#                Then `start_date: 2026-12-21` beats all of it: start 12-21.
#                Twenty working days stepping over 12-24, 12-25, 12-31 and
#                01-01 (12-26 is a Saturday and costs nothing):
#                  12-21,22,23 | 12-28,29,30 | 01-04,05,06,07,08 |
#                  01-11,12,13,14,15 | 01-18,19,20,21
#                                                           -> 12-21 .. 2027-01-21
#                Remove those four holidays and the twentieth day is 01-15 —
#                four working days earlier. This is the only span in either
#                corpus that straddles the shutdown.
#
# The three rollups are min(start)/max(end) over children and book nobody:
#   pitch-6f2d18  over 6a5c02 (08-17..08-28) and 6b7d31 (08-13..08-19)
#   pitch-7b3e94  over 7c8e40 (08-31..09-11) and 7d9f52 (12-21..2027-01-21)
#   proj-9a4c25   over both pitches
#
# No island record adds an overrun: every span ends at or before its cycle's
# `build_end`, and task-7d9f52 ends 2027-01-21 against cycle 38's 2027-01-22 —
# ONE WORKING DAY INSIDE, which is a deliberate boundary test of `_overrun`'s
# `<=`. proj-9a4c25 is measured against nothing, because `bet_of` finds its
# parent product absent from `live` and hands back the project, whose own
# `cycle` is null.

# Every done record in the corpus has a null start_date, and the shelved one is
# out of the graph, so none of them appear on the timeline at all. The hearth
# island adds nothing here: none of its records is `done`, and its two PRODUCTS
# never enter `live` at all, because `RUNG["product"].schedules` is False. This
# set is what asserts that a product draws no bar — a rectangle behind every real
# bar, saying nothing the bars do not.
GOLDEN_ABSENT = {
    "pitch-2a7f3e",
    "pitch-3c9a41",
    "task-31f6c4",
    "task-3a52d8",
    "task-3d84e9",
    "task-3e07b2",
    # The two products, named here rather than left to the dict equality above.
    # `GOLDEN_SPANS` not holding a key is the absence of an assertion; this set
    # is the assertion, and the sentence over it was written about records that
    # were not in it.
    "prod-6d1a70",
    "prod-7c2b81",
}

# Measured against the end of BUILD rather than the end of the window, so every
# one of these grew by the two cool-down weeks — except where the span itself
# also moved. Cool-down is not build time.
#
# The hearth island adds no entry and changes no number. Every island span ends
# at or before its cycle's `build_end`, and `task-7d9f52` ends 2027-01-21 against
# cycle 38's 2027-01-22 — inside by one working day, on purpose, so that the `<=`
# in `_overrun` is a boundary somebody chose rather than a comparison nothing
# stands on.
GOLDEN_OVERRUNS = {
    "pitch-48ea9e": 15.0,
    "pitch-5e7b1c": 52 / 7,
    "task-2b6c94": 166 / 7,
    # 26/7, not 4.0: it starts four days earlier now, so it ends four days
    # earlier and overruns its cycle by that much less.
    "task-53a9f0": 26 / 7,
    "task-58d7c6": 52 / 7,
    "task-5a4e39": 17 / 7,
    "task-5c1d84": 45 / 7,
    "task-5f062b": 24 / 7,
}


def test_the_seed_corpus_schedules_to_the_golden_timeline(seed_root: Path):
    records, config, _ = model.load_repo(seed_root)
    spans, _ = schedule(records, config, GOLDEN_TODAY)
    assert {i: (s.start, s.end) for i, s in spans.items()} == GOLDEN_SPANS


def test_the_seed_corpus_golden_overruns_and_flags(seed_root: Path):
    records, config, _ = model.load_repo(seed_root)
    spans, _ = schedule(records, config, GOLDEN_TODAY)
    assert not GOLDEN_ABSENT & spans.keys()
    overruns = {i: s.overruns_cycle_weeks for i, s in spans.items() if s.overruns_cycle_weeks}
    assert overruns == pytest.approx(GOLDEN_OVERRUNS)
    assert not [s for s in spans.values() if s.unowned]
    assert not [s for s in spans.values() if s.unscheduled or s.historical]


def test_the_cycle_records_the_goldens_are_derived_against(seed_root: Path):
    """The inputs to half of GOLDEN_SPANS, pinned where they can be read.

    Cycles 37 and 38 are dated by `cycles/0037.md` and `cycles/0038.md` and by
    nothing in `config/cycles.yaml`, so `Config.with_plans` creating a window is
    itself part of the derivation — and every per-person rate in the island spans
    is read off these two records. If one of them moves, seven spans above are
    wrong and the failure should say which number moved rather than only which
    dates did.
    """
    _, config, _ = model.load_repo(seed_root)

    assert 37 not in _cycles_yaml(seed_root) and 38 not in _cycles_yaml(seed_root)
    assert config.cycles[37] == (date(2026, 8, 17), date(2026, 11, 29))
    assert config.cycles[38] == (date(2026, 11, 30), date(2027, 2, 7))
    # The four YAML-dated cycles are untouched by the two records beside them.
    assert config.cycles[36] == (date(2026, 6, 22), date(2026, 8, 14))

    thirty_seven = config.plans[37]
    assert thirty_seven.builds_until == date(2026, 9, 11)
    assert thirty_seven.build_weeks == 4.0
    # No `reviews_on` in the file, so the four-week build is assumed and said so;
    # a later cycle exists, so the END is read rather than assumed. Nothing else
    # in either corpus takes that second branch.
    assert thirty_seven.assumed_review and not thirty_seven.assumed_end
    assert thirty_seven.availability == {"redpollard": 0.5, "chiffchaffy": 0.25, "Whimbrelson": 1.0}

    thirty_eight = config.plans[38]
    assert thirty_eight.builds_until == date(2027, 1, 22)
    assert not thirty_eight.assumed_review and thirty_eight.assumed_end
    # 7.2 and not 8.0: eight whole Mon-Fri weeks is 40 working days, less the FOUR
    # weekday holidays inside the shutdown — 12-24, 12-25, 12-31, 01-01. 12-26 is
    # a Saturday and costs nothing, which is why it is four and not five. This is
    # the one number in the repository that has to know about Christmas.
    assert thirty_eight.build_weeks == 7.2
    shutdown = [d for d in config.holidays if date(2026, 12, 1) <= d <= date(2027, 1, 31)]
    assert [d for d in shutdown if d.weekday() < 5] == [
        date(2026, 12, 24),
        date(2026, 12, 25),
        date(2026, 12, 31),
        date(2027, 1, 1),
    ]
    assert [d for d in shutdown if d.weekday() >= 5] == [date(2026, 12, 26)]


def _cycles_yaml(root: Path) -> dict:
    import yaml

    return yaml.safe_load((root / "config" / "cycles.yaml").read_text())["cycles"]


def test_a_cool_down_longer_than_the_window_does_not_invert_the_build():
    """It would put the end of build before the cycle began, and then everything
    in that cycle overruns by definition. Clamped rather than rejected: a bad
    number in one config file should cost that cycle's flag, not every date."""
    from openproj.model import Config
    from openproj.schedule import build_end

    window = (date(2026, 6, 22), date(2026, 8, 14))
    absurd = Config(cycles={36: window}, cooldown_weeks=20.0)

    assert build_end(36, window, absurd) == window[0]
    assert build_end(36, window, absurd) >= window[0]


def test_a_record_too_large_for_the_calendar_is_unscheduled_and_says_why():
    """Not clamped to `date.max`: unscheduled, the way a dependency cycle is.

    A span ending at the end of the calendar is drawable in principle and a
    disaster in practice — the timeline sets its scale from the widest span, so
    one absurd number flattens every real bar to a hairline, and `_month_ticks`
    walks eight thousand years of months building an SVG nobody can open. An
    unscheduled span is dropped from the plot, which is what the scheduler
    already does with work it cannot place.
    """
    spans, explanations = run([task("aaa001", size=1_000_000.0), task("aaa002", owner="bo")])

    assert spans["task-aaa001"].unscheduled
    assert spans["task-aaa001"].start == spans["task-aaa001"].end == MONDAY
    assert "runs past the end of the calendar" in explanations["task-aaa001"].text
    # The plan around it is untouched: one absurd number is one absurd row.
    assert spans["task-aaa002"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


def test_a_done_date_at_the_end_of_the_calendar_costs_its_dependent_and_nothing_else():
    """A `done` span is whatever `start_date` says, and no rule refuses a date.

    `start_date: 9999-12-31` typed into the detail page committed, and then
    `_next_working_day` — walking from the blocker's last day to the day after
    it — stepped one day off the calendar and raised OverflowError out of
    `build_index`. Every page that reads the index answered 500 to every reader,
    for good.

    The dependent is unscheduled and says so, which is the same answer the
    scheduler already gives work that does not fit. The done row keeps the date
    somebody typed: it is history as recorded, and rewriting it here would make
    the timeline disagree with the field on the detail page.
    """
    spans, explanations = run(
        [
            task("aaa001", status="done", start_date=date.max, prs=["o/r#1"]),
            task("aaa002", owner="bo", depends_on=["task-aaa001"]),
            task("aaa003", owner="cy"),
        ]
    )

    assert spans["task-aaa001"] == Span(
        start=date.max,
        end=date.max,
        historical=True,
        budget_weeks=1.0,
        # No length: a done record is a point marker until an end date is stored
        # on it, and one day read back as a fifth of a week was a measurement of
        # nothing.
        elapsed_weeks=None,
    )
    assert spans["task-aaa002"].unscheduled
    assert "runs past the end of the calendar" in explanations["task-aaa002"].text
    assert spans["task-aaa003"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


def test_a_worker_booked_to_the_end_of_the_calendar_does_not_spin():
    """The placement loop advances `start` past whoever is busy, so a worker
    booked to `date.max` used to hand it a start it could not move past — and
    with the walk saturating instead of raising, that is an infinite loop rather
    than a stack trace. The calendar question is asked each time round, so the
    loop ends with an answer instead."""
    started = time.monotonic()
    spans, explanations = run(
        [
            task("aaa001", status="done", start_date=date.max, prs=["o/r#1"]),
            task("aaa002", depends_on=["task-aaa001"]),
            task("aaa003"),  # same owner as aaa002, so it queues behind it
        ]
    )

    assert time.monotonic() - started < 5.0
    assert spans["task-aaa002"].unscheduled
    assert spans["task-aaa003"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


@pytest.mark.parametrize("size", [float("inf"), float("nan")])
def test_a_size_that_is_not_a_number_is_one_bad_row(size: float):
    """`Infinity` and `NaN` are valid JSON to Python's parser, so `person_weeks:
    Infinity` was one PATCH away — and `math.ceil(inf)` raised inside
    `_runs_past_the_calendar` itself. The guard was the thing that fell over, so
    every page 500'd on a committed value that no rule refuses.

    The route refuses the number now. This is the file somebody wrote by hand.
    """
    spans, _ = run([task("aaa001", size=size), task("aaa002", owner="bo")])

    assert spans["task-aaa001"].unscheduled
    assert spans["task-aaa002"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


# --------------------------------------------------------------------------- #
# A dependency written on a pitch is what its tasks wait for
# --------------------------------------------------------------------------- #


def test_a_pitch_level_dependency_delays_the_tasks_inside_the_dependent_pitch():
    """ "The bed port waits for throughflow" is a sentence about two pitches, and
    it moved nothing: only a leaf is placed against its blockers, and a parent's
    span is the rollup of children who had never heard of the edge.

    The demo shipped with exactly this — the bed starting a month before the
    throughflow it declared it waited for, while the table's `blocked` filter
    returned it. Two views of one record, disagreeing."""
    spans, _ = run(
        [
            pitch("aaa001"),
            pitch("aaa002", depends_on=["pitch-aaa001"]),
            task("bbb001", parent="pitch-aaa001", size=2.0, owner="ann"),
            task("bbb002", parent="pitch-aaa002", size=2.0, owner="bo"),
        ]
    )

    blocker_ends = spans["pitch-aaa001"].end
    assert spans["task-bbb002"].start > blocker_ends, "the task waits for its pitch's blocker"
    assert spans["pitch-aaa002"].start > blocker_ends, "so the rollup does too"


def test_a_dependency_is_inherited_down_the_whole_chain_not_just_one_level():
    """A project's blocker reaches the tasks two levels below it. The edge stays
    written once, where somebody wrote it."""
    spans, _ = run(
        [
            task("aaa001", size=2.0, owner="cy"),
            model.Project(id="proj-000001", kind="project", title="M", depends_on=["task-aaa001"]),
            pitch("aaa002", parent="proj-000001"),
            task("bbb002", parent="pitch-aaa002", size=1.0, owner="ann"),
        ]
    )

    assert spans["task-bbb002"].start > spans["task-aaa001"].end


def test_an_inherited_blocker_is_named_in_the_explanation():
    """The first unexplained date is when a timeline stops being believed, and an
    inherited blocker is the least obvious of them: the reason is written on a
    record one level up from the bar somebody is pointing at."""
    _, why = run(
        [
            pitch("aaa001"),
            pitch("aaa002", depends_on=["pitch-aaa001"]),
            task("bbb001", parent="pitch-aaa001", size=2.0, owner="ann"),
            task("bbb002", parent="pitch-aaa002", size=2.0, owner="bo"),
        ]
    )

    assert why["task-bbb002"].blocker_id == "pitch-aaa001"
    assert "pitch-aaa001" in why["task-bbb002"].text


def test_a_loop_that_only_inheritance_closes_costs_those_records_and_no_others():
    """Neither edge is illegal on its own: a pitch waits for another, and one of
    that other's tasks waits for one of this pitch's. Together they deadlock, and
    `_unschedulable` cannot see it — it reads the written edges. The sort must not
    raise, because one contradictory pair costing every date on the page is the
    failure this scheduler is built to avoid."""
    spans, _ = run(
        [
            pitch("aaa001", depends_on=["pitch-aaa002"], size=1.0),
            # Both bet at something: the assertion below is that the deadlocked
            # records come back marked unscheduled, and an unsized record has no
            # span to mark.
            pitch("aaa002", size=1.0),
            task("bbb001", parent="pitch-aaa001", size=1.0, owner="ann"),
            task("bbb002", parent="pitch-aaa002", size=1.0, owner="bo", depends_on=["task-bbb001"]),
            task("ccc001", size=1.0, owner="cy"),
        ]
    )

    assert any(spans[i].unscheduled for i in ("pitch-aaa002", "task-bbb002"))
    assert spans["task-ccc001"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    ), "an unrelated task keeps its dates"


def test_a_project_with_no_pitches_draws_nothing():
    """It is a container, and an empty one contains nothing. Having no size field
    it fell to the default and drew a half-week bar nobody had written."""
    spans, _ = run(
        [
            model.Project(id="proj-000001", kind="project", title="Empty", owner="ann"),
            task("aaa001", size=1.0, owner="ann"),
        ]
    )

    assert "proj-000001" not in spans
    assert spans["task-aaa001"] == Span(
        start=MONDAY, end=date(2026, 8, 21), budget_weeks=1.0, elapsed_weeks=1.0
    )


def test_a_project_with_pitches_is_still_their_rollup():
    spans, _ = run(
        [
            model.Project(id="proj-000001", kind="project", title="M"),
            pitch("aaa001", parent="proj-000001", size=1.0, owner="ann"),
        ]
    )

    # Everything but the box, which a container does not have: `Rung.sized` says a
    # project carries no appetite of its own, so `budget_weeks` is None on it while
    # its only pitch was bet at a week. The dates and the rolled-up length are the
    # pitch's exactly, which is what "still their rollup" means.
    assert spans["proj-000001"] == spans["pitch-aaa001"].model_copy(update={"budget_weeks": None})


def test_work_in_progress_starts_when_it_started_and_not_today():
    """`in_progress` is a statement that the work HAS begun, so its start is a
    fact rather than a forecast — and the floor at `today` exists to stop a plan
    drawing work starting in the past, which is right for a bet nobody has picked
    up and wrong for one somebody is holding.

    Importing a cycle after it ran is what showed this: every live bet in the
    team's real cycle 37 was drawn beginning on the day of the import, weeks
    after the review meeting that closed the cycle, while the two `done` ones sat
    correctly back in July.
    """
    began = task("aaa001", status="in_progress", start_date=date(2026, 6, 22))
    waiting = task("aaa002", owner="bo", status="ready", start_date=date(2026, 6, 22))
    spans, _ = schedule([began, waiting], CONFIG, date(2026, 8, 17))

    assert spans["task-aaa001"].start == date(2026, 6, 22)
    # The one nobody has started is still floored at today, which is the rule
    # this change deliberately leaves alone.
    assert spans["task-aaa002"].start == date(2026, 8, 17)


def test_two_things_one_person_is_already_doing_are_drawn_at_once():
    """One person does one thing at a time — unless they are already doing both.

    Serialising is a forecast about work not yet picked up; applied to bets
    somebody is holding it becomes a prediction about the past. The first real
    cycle imported had one person on five live rows, and serialising them drew
    the last starting six weeks after the review meeting that closed the cycle.

    That the person is over capacity is true and worth saying — the load column
    and the cycle's over-capacity line say it, against the number, rather than by
    moving a date that has already happened.
    """
    both = [
        task("aaa001", status="in_progress", start_date=date(2026, 6, 22)),
        task("aaa002", status="in_progress", start_date=date(2026, 6, 22)),
    ]
    spans, _ = schedule(both, CONFIG, date(2026, 8, 17))

    assert spans["task-aaa001"].start == spans["task-aaa002"].start == date(2026, 6, 22)

    # Work nobody has started is still serialised, which is the rule this leaves
    # alone: a forecast that books one person twice is a forecast that is wrong.
    queued = [task("bbb001"), task("bbb002")]
    later, _ = schedule(queued, CONFIG, date(2026, 8, 17))
    assert later["task-bbb001"].start != later["task-bbb002"].start
