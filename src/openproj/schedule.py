"""Derive a timeline from sizes, dependencies and start dates.

Nobody types a start or an end date. A `Span` is inclusive — `end` is the last
working day the item occupies — so anything following it starts on the next
working day, never the same one.

Two invariants earn their own tests because breaking either produces a schedule
that looks plausible and is wrong:

* A size is PERSON-weeks, and the people on it divide it — each at their own
  availability. Three names on a six-week bet is two elapsed weeks, and one
  person at 60% takes a three-week bet five weeks. (D-C4, 2026-08-16. This
  reverses D1, which said a size was already elapsed weeks and must never be
  divided; D1 was wrong about how the team estimates, and with a single assignee
  at full availability the two readings agree, which is why it went unnoticed.)
* Only leaves consume a worker's capacity. A parent's span is a rollup of work its
  children already booked; booking the parent too double-books its owner.

A size is the one input with no substitute. There is no default appetite, so a
record nobody has sized is not scheduled at all — no span, exactly as a childless
project gets none — rather than scheduled at some assumed length and marked as a
guess. `schedule` says at length why a floor span would have been worse.

The scheduler never raises. A cycle, a contradictory record or a cycle number
nobody has dated costs you those records, never the whole page.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from typing import NamedTuple

import networkx as nx
from pydantic import BaseModel

from .model import (
    PRIORITY_RANK,
    RUNG,
    Config,
    Record,
    Sentence,
    ancestors,
    cycle_of,
    days_after,
    size_weeks,
    start_date_has_passed,
    within_the_calendar,
    workers_on,
)

_WORKING_DAYS_PER_WEEK = 5


class Span(BaseModel):
    start: date
    end: date
    unowned: bool = False
    # Work that is over: these dates are a record of what happened rather than a
    # forecast of what will. It is what the timeline hatches now — see the
    # `_MARK_WORDS` in `render/timeline.py`, and `estimated`, which used to have
    # that channel and no longer exists. That flag meant "the appetite behind
    # these dates was invented", and with no default appetite left to invent one
    # there is no such span: an unsized record gets no span at all.
    historical: bool = False
    unscheduled: bool = False
    overruns_cycle_weeks: float | None = None
    # WHICH cycle that number is about, travelling beside it.
    #
    # It is `cycle_of(record, by_id)` — the cycle the BET was made in, which for
    # a task under a pitch is the pitch's — and it is carried rather than looked
    # up again by whoever prints the sentence, because the two answers were
    # different and the page printed the wrong one. `render/detail.py` formatted
    # `record.cycle`, and a task carries no cycle of its own, so four seed task
    # pages read "▲ overruns cycle None by 4.7 weeks": the one sentence in the
    # tool that says a bet did not fit its box, unreadable. It was hidden from
    # the tests because 11 of the fixture corpus's 15 tasks happen to write their
    # own `cycle:`.
    #
    # None exactly when `overruns_cycle_weeks` is None, and the two are set
    # together in every constructor below. A record that overran was measured
    # against something, or it was not measured at all.
    overruns_cycle: int | None = None
    # The box, in calendar weeks: this record's OWN appetite over the summed
    # availability of the people on it, rounded by `_budget_weeks` to the whole
    # working days the scheduler would actually lay that appetite out over. Two
    # names on an eight-week bet have bought themselves four weeks, and four
    # weeks is what the bet buys.
    #
    # Carried here rather than computed where it is read, because the one place
    # that has to compare it against `elapsed_weeks` is `_rollup_problems` in
    # `model.py`, and `model.py` cannot import this module — `schedule` imports
    # `model`. A number the scheduler already computes, travelling on the span
    # beside the dates it produced, is the only shape that keeps the comparison
    # from being written a second time somewhere it can be reached.
    #
    # None where the record states no appetite of its own. That is every
    # container, and every pitch nobody has bet on yet — which is why
    # `_rollup_problems` stays silent about both.
    budget_weeks: float | None = None
    # And the contents, in the same units and through the same rounding: the
    # working days this record actually occupies. For a leaf that is its own
    # span; for a pitch it is the UNION of the days its children occupy, which
    # already knows whether two tasks ran side by side or queued behind one
    # shared person — and which is deliberately not the length of the span above,
    # because the days between a task finishing and the next one starting are
    # days nobody is working and no remedy the warning offers can recover. See
    # `_occupied_weeks`.
    #
    # **Whose days, is decided by whether the record holds children and never by
    # which branch produced the span.** A leaf reports its own; anything with
    # children reports what is under it, finished records included — a bet that
    # ran from January to June holding one week of work holds one week, and the
    # five idle months belong to the dates above and to no reading of this. The
    # historical branch used to answer with the record's own interval whether or
    # not it held anything, and `check`, the reading view and the appetite cell
    # all called that number "its tasks".
    #
    # None wherever there is no length to report, which is two cases now and was
    # three. An unscheduled LEAF, whose `start` and `end` are a placeholder for
    # "no answer" rather than dates anybody forecast — a fifth of a week is not a
    # length, it is today twice. And a parent none of whose children have one,
    # which is the first case seen from above.
    #
    # The third was a `historical` span, and it went with §4 of
    # `design/time-model.md`: a done record's dates were its start date twice,
    # for want of anywhere to record where finished work ended, and there is an
    # `end_date` now. So on a finished leaf this is the one number on any span
    # that was MEASURED rather than forecast — working days between two dates
    # somebody wrote down — and the parents of finished work get a length back
    # with it. A record written before the gate existed still carries no end and
    # still lands here as None, which is why this stays optional.
    elapsed_weeks: float | None = None


class Explanation(Sentence):
    """Why a record starts when it does: one sentence, and the dates it names.

    A `Sentence` (`model.py`), which is where the argument for holding the dates
    as dates is written and where `text` and `drawn` are. This class is what a
    scheduling sentence carries on top of the wording: which record it is about,
    and the two things a reader may want to follow from it.

    The machinery was written here first, and it moved when `Problem` needed the
    same two forms for the same reason — a validator sentence naming a start date
    was drawn ISO on the record page, a few rows above this one's day-first
    reading of that same date.
    """

    record_id: str
    blocker_id: str | None = None
    worker_busy_until: date | None = None


def _is_working_day(day: date, config: Config) -> bool:
    return day.weekday() < 5 and day not in config.holidays


def _next_working_day(day: date, config: Config) -> date:
    """The first working day after `day`, or the end of the calendar if there is none.

    This walk and `_first_working_day`'s stop at `date.max` rather than stepping
    past it. `_place` calls this on a blocker's last day, and a `done` record
    carries whatever `start_date` says — so `start_date: 9999-12-31`, typed
    into the detail page, walked one day off the end of the calendar and
    answered 500 on every page that reads the index. Saturating is the same
    answer `working_days_after` already gives, and `_place` asks about the
    calendar before it uses either.
    """
    day = days_after(day, 1)
    while day < date.max and not _is_working_day(day, config):
        day = days_after(day, 1)
    return day


def _first_working_day(day: date, config: Config) -> date:
    while day < date.max and not _is_working_day(day, config):
        day = days_after(day, 1)
    return day


def _working_days(weeks: float) -> int:
    """Whole working days in `weeks`.

    Rounded to six decimals first: 1.2 * 5 is 6.000000000000001 in binary
    floating point, and a naive ceil would buy a seventh day. Bounded before the
    ceil, because `math.ceil` raises on infinity: `person_weeks: Infinity` is
    valid JSON to Python's parser and one PATCH away, and it raised here —
    inside `_runs_past_the_calendar`, so the guard was the thing that fell over
    and every page 500'd on a value already committed.
    """
    return max(1, math.ceil(within_the_calendar(round(weeks * _WORKING_DAYS_PER_WEEK, 6))))


def _budget_weeks(duration: float | None) -> float | None:
    """`duration` as the whole working days the scheduler will actually lay it out over.

    The box has to be canonicalised the same way the contents are, or the two are
    not comparable. `working_days_after` lays a duration out as
    `_working_days(duration) = max(1, ceil(duration * 5))` days and
    `_occupied_weeks` counts those days back as `working / 5`, so a span's length
    is always the CEILING of the duration that produced it — equal to it when
    `duration * 5` is a whole number and strictly greater whenever it is not.

    Held against the raw duration, that ceiling is a systematic bias and not a
    rounding error. `_rollup_problems` fires on strict `>`, so a pitch bet at 2.5
    weeks holding one task bet at 2.5 weeks on the same person — the contents
    filling the box exactly, which is the `=` row of the design's own table — laid
    out thirteen working days against a box of twelve and a half and warned that
    it needed 2.6 more than the 2.5 it had. Any fractional availability puts every
    bet in that position: eight person-weeks over two people at 60% is 6.67, which
    is 33.3 days, which is 34 laid out. The `=` state was unreachable and
    everything adjacent to it painted warn.

    So both sides are read in the unit the scheduler works in — whole working
    days — and a bet that is exactly filled compares equal. This is the number
    `_rollup_problems` also QUOTES ("the 4.0 the bet buys at 2"), which is the
    other half of the fix: a page that says 2.6 against a stated 2.5 and calls it
    level would be telling a reader the comparison is broken.

    None passes through, because a record nobody has sized has no box rather than
    a box of one day — `max(1, ...)` is the scheduler's floor on work it is
    laying out, not a size it may invent for work it is not.
    """
    if duration is None:
        return None
    return _working_days(duration) / _WORKING_DAYS_PER_WEEK


def _working_days_between(start: date, end: date, config: Config) -> int:
    """How many working days a stretch from `start` to `end` inclusive holds.

    The inverse of `_working_days`, and it has to be that rather than a calendar
    subtraction over seven, because the number it feeds is compared against
    `_budget_weeks` — `Span.budget_weeks` against `Span.elapsed_weeks`, in
    `_rollup_problems`. `working_days_after` turns four weeks into twenty working
    days and lands on the Friday of the fourth week, which is twenty-six calendar
    days: over seven that is 3.7, so a pitch whose single task exactly filled its
    bet would have read seven per cent under it, the `=` state in the design's
    own table would have been unreachable, and a bet overrun by a tenth would
    have painted as comfortably inside. Weekends and holidays are not work, and
    the box was never measured in them.

    The `/5` — which is `_occupied_weeks`' now, and used to be this function's —
    is only half of what makes that comparison sound, and this docstring used to
    claim it was all of it. The other half is `_budget_weeks`, which puts the box
    through the same whole-day ceiling `working_days_after` applied to it on the
    way in — see there for why an uncanonicalised box made `=` unreachable a
    second way, through the ceil rather than through the divisor.

    Counted by arithmetic and not by walking, unlike everything else here that
    steps day by day. A stretch is bounded by what somebody typed as a
    `start_date`, so `9999-12-31` is one hand-edit from two and a half million
    iterations per span — the same shape as the OverflowError
    `_runs_past_the_calendar` exists to ask about before the walk rather than
    after it.

    Holidays land on the same footing they have in `_is_working_day`: subtracted
    only when they fall on a weekday, since a holiday on a Sunday was never a
    working day to lose.
    """
    if end < start:
        return 0
    days = (end - start).days + 1
    weeks, remainder = divmod(days, 7)
    # Whole weeks are five working days each whatever weekday they begin on; only
    # the tail has to be looked at a day at a time, and it is at most six days.
    working = weeks * _WORKING_DAYS_PER_WEEK + sum(
        1 for step in range(remainder) if days_after(start, weeks * 7 + step).weekday() < 5
    )
    working -= sum(1 for day in config.holidays if start <= day <= end and day.weekday() < 5)
    return max(0, working)


def _occupied_weeks(intervals: list[tuple[date, date]], config: Config) -> float | None:
    """Weeks of work in the UNION of `intervals`, or None where they cover nothing.

    This is what a bet's contents are measured as, and the enclosing interval —
    `min(child.start)` to `max(child.end)` — is what it used to be. That charged
    a bet for calendar in which nobody was working. `pitch-7b3e94` in the fixture
    corpus holds two tasks worth six weeks between them, the second of them dated
    to after the plant shutdown, so the interval enclosing them ran from August to
    January and the pitch was warned at twenty weeks against a three-week box.
    Fourteen of those twenty weeks were a gap, and the sentence the warning
    carries offers three remedies — cut scope, re-bet, add people — of which none
    touches a gap. A number that makes the tool name a cause that is not the
    cause is worse than no number.

    The same mechanism read a length back out of the two dates a done record's
    point marker carried, which were the same date twice: a pitch holding one
    task that started in January was warned at thirty-three weeks. §4 of
    `design/time-model.md` gave a done record a recorded `end_date`, so what it
    now contributes is the days it really ran and not the stretch from its start
    to today. A child with no length still contributes no interval at all — an
    unsized record, and a finished one written before the end date existed — so
    it drops out of the arithmetic rather than being subtracted from it.

    **Merged and not summed, which is what keeps shared assignees right.** Two
    tasks on one person serialise — `_place` books workers, so a contended person
    queues behind themselves — and their intervals abut, so the union is their
    sum and a bet that does not fit still says so. The same two tasks on two
    people run side by side, and the union is the longer of the two rather than
    both added up. Nothing new is taught about parallelism: the placer already
    modelled it, and a day is counted once because it is one day.

    **Days are added as whole days and divided once at the end**, which is why
    `_working_days_between` counts days rather than returning weeks. Adding weeks
    per interval instead puts binary-floating-point noise into a comparison
    decided on strict `>`: one day and two days are `0.2 + 0.4 =
    0.6000000000000001` against a box of exactly 0.6, and 640 of the 3481 pairs
    under twelve weeks land the same way. That is the `=` row of the design's
    table going unreachable for a third reason, on top of the two `_budget_weeks`
    records.
    """
    days = 0
    covered_to: date | None = None
    for start, end in sorted(intervals):
        if covered_to is not None:
            if end <= covered_to:
                continue
            # Sorted by start, so everything before `covered_to` has been counted
            # already; only the tail this interval adds is new.
            start = max(start, days_after(covered_to, 1))
        days += _working_days_between(start, end, config)
        covered_to = end
    # None rather than zero where nothing was occupied at all, because that is
    # not a bet whose tasks take no time — it is a bet none of whose tasks has a
    # length to report, and `Span.elapsed_weeks` already spells None as "no
    # answer" everywhere else it appears. Zero would read as measured, paint the
    # `▾` good tint on a pitch nobody can say anything about, and answer
    # `_rollup_problems` that a finished bet fitted its box.
    return None if covered_to is None else days / _WORKING_DAYS_PER_WEEK


def _runs_past_the_calendar(start: date, weeks: float, config: Config) -> bool:
    """Whether `weeks` of work beginning at `start` outruns the end of `date`.

    `person_weeks: 1000000` is one PATCH away and no rule refuses it. The day
    walk below used to keep adding days until `timedelta` went past year 9999
    and raised OverflowError — out of `build_index`, so `/`, `/graph`,
    `/timeline`, `/people` and `/api/index.json` all answered 500 to every
    reader, off a value already committed to a branch whose protection means the
    commit cannot be force-pushed away. The five million iterations before the
    raise are the other half of it, so the question is asked before the walk
    rather than answered by catching what the walk throws.

    Each working day costs one calendar day, plus at most two more for a
    weekend, plus one for each configured holiday it steps over — and a walk
    that only moves forward steps over each holiday at most once. So
    `3 * days + len(holidays)` is a ceiling on the calendar days consumed,
    including the roll-forward in `_first_working_day`. Against the ~2.9 million
    days between now and `date.max`, nothing anybody plans comes near it.
    """
    return 3 * _working_days(weeks) + len(config.holidays) > (date.max - start).days


def working_days_after(start: date, weeks: float, config: Config) -> date:
    """The inclusive last day of `weeks` working weeks beginning at `start`.

    The end of the calendar when the work does not fit inside it: this is the
    primitive, and a primitive that raises is a 500 on every page. The scheduler
    asks `_runs_past_the_calendar` first and leaves such a record unscheduled,
    which is the answer a reader can actually use.
    """
    if _runs_past_the_calendar(start, weeks, config):
        return date.max
    day = _first_working_day(start, config)
    for _ in range(_working_days(weeks) - 1):
        day = _next_working_day(day, config)
    return day


def _duration_weeks(record: Record, config: Config, by_id: dict[str, Record]) -> float | None:
    """Elapsed weeks, or None for a record nobody has sized.

    A size is PERSON-weeks — the work one person would need — so the people on it
    divide it, each at their own availability (D-C4, 2026-08-16; this supersedes
    D1, which said the opposite and was wrong about how the team estimates).

    Two consequences worth stating, because both reverse earlier behaviour:
    staffing a bet with three people makes it finish sooner, which is what the
    room believes when it puts three names on one; and one person at 60% takes a
    three-week bet five weeks, which is the right answer rather than the bug the
    old spec calls out — that draft was only wrong under D1's reading.

    Nobody assigned is one notional person at nominal availability. Zero would be
    a division by zero, and infinity is not a useful forecast for unowned work.

    None where the record states no size, because the arithmetic below has
    nothing to divide. It used to divide half a week nobody had typed and hand
    back a second value saying so, which is a duration in every respect that
    matters — it was placed, it booked its workers, it drew a bar — with a flag
    beside it asking every reader to remember that it was fiction.
    """
    size = size_weeks(record)
    if size is None:
        return None
    rates = [_availability_of(who, record, config, by_id) for who in workers_on(record)]
    return size / (sum(rates) or config.nominal_availability or 1.0)


def _availability_of(who: str, record: Record, config: Config, by_id: dict[str, Record]) -> float:
    """One person's rate in the cycle this record was bet into.

    Read from the record's own cycle rather than passed in, so there is one
    source: a global override and a per-cycle record would disagree the first
    time somebody set both.

    Being on a cycle's roster is what being in that cycle means, so somebody bet
    into a cycle they are not on is a planning mistake — but it is not one the
    scheduler can fix by refusing to produce a date. It uses the nominal rate and
    the cycle page names them, which is where a person can act on it. A rate of
    zero reads the same way rather than as a bet nobody can ever finish.
    """
    # The cycle of the BET, so a task reads the rates of the cycle its pitch was
    # bet into. A task carries no cycle of its own any more, and falling back to
    # nominal here would have quietly undone every per-person rate on the page.
    number = cycle_of(record, by_id)
    plan = config.plans.get(number) if number is not None else None
    stated = plan.availability.get(who) if plan else None
    return stated if stated else config.nominal_availability or 1.0


class Overrun(NamedTuple):
    """How far past its cycle's build a record ran, and which cycle that was.

    One value and not two, because the two are one measurement: the number is
    meaningless without the window it was taken against, and the page that
    printed them separately printed a number from here beside a cycle read off
    the record — see `Span.overruns_cycle`. Handed back together, a caller that
    has one has the other, and there is no arrangement of these lines in which
    it can hold a weeks-past-cycle-37 and call it cycle 41.
    """

    cycle: int
    weeks: float


def _overrun(record: Record, end: date, config: Config, by_id: dict[str, Record]) -> Overrun | None:
    """Weeks past the end of the BUILD of the cycle this was bet into, or None.

    Cool-down is not build time — Shape Up's whole point is that work lands
    inside the build weeks and the cool-down is for the mess afterwards. Measured
    against the end of the window instead, every overrun was understated by the
    cool-down length and some were hidden completely.

    The cycle is the one the BET was made in, which for a task under a pitch is
    the pitch's. A project is measured against nothing: it holds bets rather than
    being one, and its span is the rollup of pitches bet in different cycles — so
    judging it against any single cycle produced the demo's `warm_bubble`,
    "overruns cycle 36 by 17 weeks", a milestone accused of missing a box nobody
    ever put it in.

    A cycle nobody has dated yet is not an overrun. Indexing `config.cycles`
    directly would turn one unconfigured number into a KeyError for every span.
    """
    number = cycle_of(record, by_id)
    if number is None:
        return None
    window = config.cycles.get(number)
    if window is None:
        return None
    builds_until = build_end(number, window, config)
    if end <= builds_until:
        return None
    return Overrun(number, (end - builds_until).days / 7)


def _overrun_fields(
    record: Record, end: date, config: Config, by_id: dict[str, Record]
) -> dict[str, object]:
    """The two `Span` keys an overrun sets, so that no constructor can set one.

    Splatted into all three `Span` constructions below rather than written out at
    each, and that is the point of it rather than a saving of two lines: the
    defect this pair exists to fix was a number and a cycle number that came from
    different places, and a shape where one can be passed without the other is a
    shape where they can drift again. `Span.overruns_cycle` is None exactly when
    `Span.overruns_cycle_weeks` is, because this is the only thing that writes
    either.
    """
    over = _overrun(record, end, config, by_id)
    return {
        "overruns_cycle": over.cycle if over is not None else None,
        "overruns_cycle_weeks": over.weeks if over is not None else None,
    }


def build_end(number: int | None, window: tuple[date, date], config: Config) -> date:
    """The last day of a cycle's build.

    From the cycle's own record where there is one, and otherwise from the global
    cool-down applied to the end of the window.
    """
    plan = config.plans.get(number) if number is not None else None
    ends = (
        # Resolved by `Config.with_plans`, which is the only thing that builds a
        # `plans` map — but a `Cycle` handed straight to a Config would carry
        # None, and a date is wanted here rather than a raise.
        plan.builds_until or window[0]
        if plan is not None
        # Backwards through `days_after` for the same reason as everything else:
        # a cool-down of `.inf` weeks in one config file is `round()` raising,
        # and one absurd number in `defaults.yaml` is not worth every page.
        else days_after(window[1], -(config.cooldown_weeks * 7))
    )
    # A cool-down longer than the window would put the end of build before the
    # cycle began, and then every record in it overruns by definition. Clamped
    # rather than rejected: a bad number in one config file should cost that
    # cycle's flag, not every date on the page.
    return max(ends, window[0])


def blockers_of(record: Record, by_id: dict[str, Record]) -> list[str]:
    """What this record waits for: its own blockers, and its ancestors'.

    A dependency is written at the level people think at. "The land port waits
    for turbulence" is a sentence about two pitches, and it was decoration: only
    a leaf is placed against its blockers, while a parent's span is the rollup of
    children who had never heard of the edge. The demo shipped with it — land
    starting a month before the turbulence it declared it waited for, marked
    `blocked` in the table and drawn concurrent on the timeline, the two views
    disagreeing about the same record.

    So a bet's blockers are its tasks' blockers. Inherited rather than copied: the
    edge stays written once, on the record somebody wrote it on, and `blocks`
    keeps meaning what it says on the page.

    Order is the chain's, nearest first, deduplicated — it decides only which
    blocker gets named in the explanation when two end on the same day.
    """
    waits = list(record.depends_on)
    for ancestor in ancestors(record.id, by_id):
        # `.get`, not `[]`. `ancestors` returns the chain as it is *named*, so its
        # last link can be an id no file was written for — a dangling parent is
        # deliberately legal — and the map handed in here is the *live* one, so a
        # `done` or `shelved` ancestor is absent from it too. Neither is a reason
        # to raise out of the scheduler: an ancestor nobody can read waits for
        # nothing, and a finished one is not waiting for anything either.
        above = by_id.get(ancestor)
        if above is not None:
            waits += above.depends_on
    return list(dict.fromkeys(waits))


def _ordering(active: dict[str, Record], config: Config) -> tuple[list[str], set[str]]:
    """Visit order: blockers before dependents, children before parents.

    Containment is not a dependency, so a topological sort over `depends_on`
    alone would visit a parent before the children its span is built from. The
    two edge kinds can also disagree — a record depending on its own ancestor
    contributes a dependency edge one way and a containment edge the other — and
    that record is dropped rather than allowed to raise.

    Inherited edges are in here as well as in `_place`. A task placed against its
    pitch's blocker has to be visited after that blocker has a span, and the raw
    dependency edge only orders the pitch — which is placed *after* the task,
    being a rollup of it.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(active)
    for record in active.values():
        for blocker in blockers_of(record, active):
            if blocker in active:
                graph.add_edge(blocker, record.id)

    contradictory: set[str] = set()
    for record in active.values():
        if record.parent not in active:
            continue
        if nx.has_path(graph, record.parent, record.id):
            contradictory |= {record.id, record.parent}
            continue
        graph.add_edge(record.id, record.parent)

    graph.remove_nodes_from(contradictory)
    # Inheritance can close a loop that neither edge kind closes on its own: a
    # pitch waiting on another whose task waits on one of this pitch's. Both
    # records are legal on their own and `_unschedulable` cannot see it, because
    # it reads the written edges. Caught here as the sort's own precondition
    # rather than by letting `lexicographical_topological_sort` raise — one
    # contradictory pair must cost those records, never every date on the page.
    looping = {
        node
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for node in component
    } | {node for node in graph if graph.has_edge(node, node)}
    if looping:
        contradictory |= looping | {
            downstream for node in looping for downstream in nx.descendants(graph, node)
        }
        graph.remove_nodes_from(contradictory & set(graph))
    order = nx.lexicographical_topological_sort(
        graph,  # An unknown priority sorts as medium rather than raising: validate_all
        # has already said so, and the timeline should still draw.
        key=lambda node: (
            PRIORITY_RANK.get(active[node].priority, PRIORITY_RANK["medium"]),
            node,
        ),
    )
    return list(order), contradictory


def _unschedulable(active: dict[str, Record]) -> set[str]:
    """Records on a `depends_on` cycle, plus everything downstream of one."""
    graph = nx.DiGraph()
    graph.add_nodes_from(active)
    for record in active.values():
        for blocker in record.depends_on:
            if blocker in active:
                graph.add_edge(blocker, record.id)
    caught = {
        node
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for node in component
    } | {node for node in active if graph.has_edge(node, node)}
    return caught | {d for node in caught for d in nx.descendants(graph, node)}


def schedule(
    records: list[Record], config: Config, today: date
) -> tuple[dict[str, Span], dict[str, Explanation]]:
    # Shelved work is parked, and a kind the ladder says is never scheduled has
    # nothing to schedule. A product groups the codebases a plan spans — gt4py
    # under icon4py, dace, pmap — and holds no work of its own; given a span it
    # drew a bar on the timeline spanning everything beneath it, which is a
    # rectangle behind every real bar saying nothing the bars do not.
    #
    # Read off `RUNG` rather than by naming the kind here, because "which kinds
    # are scheduled" is a property of a kind and belongs beside the others.
    live = {e.id: e for e in records if e.status != "shelved" and RUNG[e.kind].schedules}
    children: dict[str, list[str]] = defaultdict(list)
    for record in live.values():
        if record.parent in live:
            children[record.parent].append(record.id)

    spans: dict[str, Span] = {}
    explanations: dict[str, Explanation] = {}
    # The stretch each LEAF occupies: one interval per record that has a length
    # to report, forecast for work that is still to come and measured for work
    # that finished with a recorded end. Kept beside the spans rather than derived
    # from them because a span is the enclosing pair of dates and this is what
    # lies inside it — the two differ by every gap in the plan, and it is the days
    # inside that a bet is judged against (`_occupied_weeks`).
    #
    # **Leaves only, and a parent's contents gathered from underneath it at the
    # end** (`_intervals_under`, and the pass below the placement loop). This map
    # used to carry an entry for a parent too, concatenated from its children as
    # each parent was placed, and a parent could then only be measured at the
    # moment the loop reached it. A finished pitch is placed on the historical
    # branch before any of that runs, so it was given the length of its OWN two
    # dates instead — see there.
    #
    # Gathering downwards needs no order at all, and it also stops a record in
    # the middle with nothing of its own from swallowing what is under it: a
    # pitch finished before `end_date` existed and never given a start date gets
    # no span, so it wrote nothing here, so its project was charged for none of
    # the tasks inside it. A walk to the leaves passes straight through it.
    occupied: dict[str, list[tuple[date, date]]] = {}

    # Completed work is a historical marker, never a forecast, and never a claim
    # on anyone's future capacity.
    for record in live.values():
        if record.status == "done" and record.start_date is not None:
            # Where the work actually stopped, and the start date only where
            # nobody has said. This branch drew a POINT until §4 of
            # `design/time-model.md` landed — `end=start_date`, so a finished
            # record's End column showed its start, its bar was a dot, and
            # `elapsed_weeks` had nothing to measure. It has a typed end now, and
            # the gate in `_status_problems` is what makes the fallback rare
            # rather than routine: only a record written before version 5 reaches
            # it, and what that record gets is exactly the point marker it had.
            #
            # An end BEFORE the start is read as no end at all, not clamped to
            # one. `end_date` and `start_date` are two typed fields with no
            # derivation between them, so a hand-written file can contradict
            # itself — `ends_before_it_starts` is a blocker at the door and in
            # `validate_all` — and a plan in git is a fact this module draws
            # rather than refuses. Drawn literally it is a bar with a negative
            # width, a negative length handed to `_rollup_problems`, and a
            # `min`/`max` rollup reporting a pitch that started after it
            # finished. Clamped to the start it is worse in a quieter way: the
            # span becomes one day, and one day read back as an interval is 0.2 —
            # the fifth of a week this branch spent a release learning is not a
            # length. So the honest reading is that this record records no usable
            # end, which is exactly the state of one written before the field
            # existed, and it lands on the same branch.
            ended = (
                record.end_date
                if record.end_date and record.end_date >= record.start_date
                else None
            )
            spans[record.id] = Span(
                start=record.start_date,
                end=ended or record.start_date,
                historical=True,
                budget_weeks=_budget_weeks(_duration_weeks(record, config, live)),
                # With a recorded end, the one number on any span that is a
                # measurement rather than a forecast: two dates somebody wrote
                # down, so the working days between them are days that were
                # actually spent. Without one, None, and the long argument for
                # that is still live because the branch is still reachable — the
                # two dates are then the SAME date, and a point read back as an
                # interval is one working day, 0.2, which was taken for a real
                # measurement everywhere it went. A done pitch bet at eight
                # printed "8.0 · 0.2 in tasks" on its own page, and
                # `_rollup_problems` could never fire on a finished bet, because
                # a fifth of a week is under every box there is.
                #
                # `if ended` and not `_occupied_weeks` deciding, because it
                # cannot: handed one interval it will honestly report the day it
                # covers, and the whole point is that a record with no end date
                # covers no days that anybody measured.
                #
                # And its OWN interval only where it is a leaf. A finished record
                # that holds children is a box like any other, and what is in the
                # box is its tasks — so a parent is left to the pass under the
                # placement loop, which is where every parent's contents are
                # computed and the only place they are. Written here it was the
                # record's own idle calendar, and every reader called it "its
                # tasks": a pitch bet at 8.0, started in January and finished at
                # the end of June holding a single one-week task was reported by
                # `check` as needing 25.4 weeks for tasks that need one, with the
                # same 25.4 in the appetite cell. That is the reading §3 of
                # `design/time-model.md` threw out for live pitches — a number
                # naming a cause that is not the cause, and none of the three
                # remedies the sentence offers touches six idle months — arriving
                # on the one population §4b exists to serve, and by the ordinary
                # lifecycle rather than by a corner: ready → in_progress → done
                # leaves a record carrying both dates.
                elapsed_weeks=_occupied_weeks([(record.start_date, ended)], config)
                if ended and not children.get(record.id)
                else None,
                # Reached at last on this branch, and reached here because this is
                # where the records that can answer the question live.
                # `_overrun` was called on the two forecast branches only, so
                # `overruns_cycle_weeks` was None for every FINISHED record —
                # the one number that says whether a bet landed inside its cycle,
                # absent for exactly the population that could say. A forecast
                # overrun is a prediction; this one happened.
                **_overrun_fields(record, ended or record.start_date, config, live),
            )
            # And the days it occupied go up to its parent, which is the other
            # half of the same change. `_occupied_weeks`' own docstring records
            # what the point marker did here — a pitch holding one task that
            # started in January was warned at thirty-three weeks, because the
            # enclosing reading pulled those two dates back out — and §3 of the
            # design says where it lands: a child with no length contributes
            # nothing, and a done record with a recorded end has a length and
            # starts contributing honestly. Nothing is written for a record with
            # no end date, so it goes on contributing nothing, exactly as an
            # unsized one does.
            #
            # Nothing is written for a finished PARENT either, on the same rule
            # as the length above: these two dates enclose its tasks and are not
            # a stretch of work beside them, so contributing them upwards would
            # charge a project once for the pitch's calendar and again for every
            # task inside it. Its tasks are reached from above without it, since
            # `_intervals_under` walks the whole subtree rather than one level.
            if ended and not children.get(record.id):
                occupied[record.id] = [(record.start_date, ended)]

    active = {i: e for i, e in live.items() if e.status != "done"}
    stalled = _unschedulable(active)
    order, contradictory = _ordering({i: e for i, e in active.items() if i not in stalled}, config)
    floor = _first_working_day(today, config)
    for record_id in stalled | contradictory:
        budget = _budget_weeks(_duration_weeks(active[record_id], config, live))
        # A record with no duration to lay out gets no span here either. This loop
        # wrote one unconditionally, so it reached `start=end=floor,
        # unscheduled=True` before the question was ever asked below — and two
        # unsized tasks in a dependency cycle came back reading Start 27 Aug /
        # End 27 Aug in the table, styled `derived` exactly like a forecast and
        # sorting to the top of a Start-ascending sort. That is the precise
        # symptom §2 of `design/time-model.md` and the long comment further down
        # both argue at length must not happen, arrived at by a path neither of
        # them was guarding. One such child also pinned its pitch's rollup to
        # today, since `min(child.start)` cannot see the flag.
        #
        # **Two populations reach this, not one**, and the difference is worth
        # saying because only the first is a record anybody could fix. A leaf
        # nobody has sized: somebody states an appetite and it is placed. And
        # every CONTAINER — a project carries no size field at all, by design, so
        # `_duration_weeks` is None for one however complete it is, and a project
        # caught in a dependency cycle therefore loses its span entirely rather
        # than standing at the floor. That is the same landing an empty project
        # already has and every view already copes with — but `Index.counts_in`
        # went on documenting the older behaviour, that an unplaceable record is
        # given a floor span on both of this function's branches and is therefore
        # still counted somewhere. It says what this does now.
        #
        # "Could not be placed" and "there is nothing to place" are two different
        # answers, and only the first of them is worth a pair of dates.
        if budget is None:
            continue
        # The budget travels even here. It is a fact about the bet — what these
        # people at these rates buy — and it is true of a record the scheduler
        # could not place as much as of one it could. `elapsed_weeks` is left
        # None on purpose: these two dates are `floor` twice, standing for "no
        # answer", and reading a fifth of a week out of them would hand
        # `_rollup_problems` a length nothing forecast.
        #
        # Left None on this line, that is. A record here that holds children is
        # filled in from below by the pass under the loop, like every other
        # parent: its own placement is the thing with no answer, while the tasks
        # inside it were placed and the days they take are a fact about the box
        # whatever the scheduler could make of the box's own dates.
        spans[record_id] = Span(start=floor, end=floor, unscheduled=True, budget_weeks=budget)

    booked: dict[str, list[tuple[date, date]]] = defaultdict(list)
    for record_id in order:
        record = active[record_id]
        # Whether this is a container is a question about the PLAN — does anything
        # name it as its parent — and not about which of those children happen to
        # have come back with a span. The two used to be the same question, because
        # every live child got one; with no default appetite they are not, and a
        # pitch whose children are ALL unsized had an empty `kids` and fell
        # straight through to the leaf path below. It was then placed like a leaf:
        # it booked its own assignees against a duration derived from its own
        # appetite, which double-books whoever owns it the moment one of those
        # children is sized — the second invariant in this module's docstring —
        # while `Index._charged` skips it as a rollup and charges nobody, and
        # `_rollup_problems` compared the pitch against its own placement and
        # warned about it.
        #
        # A container whose children are all unplaceable gets no span at all,
        # which is the landing an empty project already has and every view already
        # copes with. The rollup below is the only way a parent may acquire dates.
        kid_ids = children.get(record_id, ())
        if kid_ids:
            kids = [spans[k] for k in kid_ids if k in spans]
            if not kids:
                continue
            began, ended = min(k.start for k in kids), max(k.end for k in kids)
            # The dates still enclose everything underneath: a pitch runs from its
            # first task to its last, and a gap in the middle is part of how long
            # it is on the wall. It is only the number the BOX is compared against
            # that stops being that stretch — a bar drawn over a gap is a true
            # picture of when this pitch is in flight, while a bet charged for
            # that gap is a warning naming a cause nobody can act on.
            #
            # The contents are not computed here, although they come from the
            # same children these dates do. They are the pass under this loop
            # instead, because a parent placed on the historical branch never
            # reaches this line at all and was measuring its own two dates — one
            # arithmetic every parent goes through, rather than one written here
            # and a different one written there.
            spans[record_id] = Span(
                start=began,
                end=ended,
                **_overrun_fields(record, ended, config, live),
                # The one place this record's OWN size is read on the rollup
                # branch, which used to return before `_duration_weeks` was ever
                # reached — a parent's dates come from its children and never
                # from its appetite, so nothing here had a use for it. The
                # comparison in `_rollup_problems` does: the bet is the box and
                # these dates are what somebody proposes to put in it, and
                # neither number means anything without the other beside it.
                budget_weeks=_budget_weeks(_duration_weeks(record, config, live)),
            )
            continue

        # A project is a container, and an empty one contains nothing to draw. It
        # has no size field, so it fell to the default and drew a half-week bar
        # nobody had written — a phantom on the timeline for a milestone whose
        # pitches have not been shaped yet. No span at all is the honest answer,
        # and every view already copes with a record that has none.
        if record.kind == "project":
            continue

        duration = _duration_weeks(record, config, live)
        # And a record nobody has sized leaves by the same door, for the same
        # reason: there is no honest answer, so there is none.
        #
        # **Not an `unscheduled` span, which is what it looks like it should be.**
        # `unscheduled` is not a "no answer" state — it is `start=end=today`, and
        # exactly one place in `src/` reads the flag, the timeline's `drawn`
        # filter. Nothing else does: the rows payload does not carry it, the
        # detail page prints its dates regardless, the cycle page prints them. So
        # an unsized task would read Start and End of today in the table, styled
        # `derived` exactly like a real forecast, with the End tooltip still
        # claiming it was derived from the start and the appetite, sorting to the
        # top of a Start-ascending sort — and be simply absent from the timeline.
        # Two pages, two answers, and the table is the one people use.
        #
        # A floor span is worse than none upwards, too: the parent rollup above
        # takes `min(child.start)` and `max(child.end)` with no `unscheduled` in
        # its constructor, so one unsized child would pin a pitch's start to
        # today, the pitch's overrun would be measured against that fabricated
        # end, and nothing on the parent row would mark it.
        if duration is None:
            continue

        workers = workers_on(record)
        placed = _place(record, duration, workers, booked, spans, floor, today, config, live)
        if placed is None:
            # Unscheduled, exactly as a dependency cycle is: the scheduler has no
            # answer, and saying so is better than inventing one. Clamping the end
            # to `date.max` instead was worse in every direction — the timeline
            # then drew a bar to the end of time and `_month_ticks` walked eight
            # thousand years of months, so the page that stopped raising started
            # producing megabytes of ticks nobody asked for. `render` drops an
            # unscheduled span from the plot entirely, so this keeps one absurd
            # number from setting the scale for every other bar on the page.
            # Nothing is booked either: work with no dates on it holds nobody's
            # capacity.
            spans[record_id] = Span(
                start=floor,
                end=floor,
                unscheduled=True,
                unowned=not workers,
                budget_weeks=_budget_weeks(duration),
            )
            explanations[record_id] = Explanation(
                record_id=record_id,
                sentence="Not placed: {weeks} weeks of work runs past the end of the calendar.",
                # The one sentence here with no date in it. The size still goes
                # through `parts` rather than into the template, so that the
                # claim above `sentence` — a literal, never built out of data —
                # is true of every construction and not of three out of four.
                parts={"weeks": f"{duration:g}"},
            )
            continue
        span, explanation = placed
        # A leaf occupies exactly the days it was placed over. This is where the
        # FORECAST intervals enter the plan — a parent holds only what it was
        # handed from below — and the done loop above is where the measured ones
        # do. A record that got no span holds nothing in either, and that is how
        # an unsized task drops out of what its pitch is charged for rather than
        # being filtered out somewhere further up.
        occupied[record_id] = [(span.start, span.end)]
        spans[record_id] = span.model_copy(
            update={
                "unowned": not workers,
                **_overrun_fields(record, span.end, config, live),
                # A leaf's budget IS the duration it was placed at — there are no
                # children to roll up — so with both put through `_working_days`
                # the two are the same number here, exactly. They used not to be:
                # the budget was the raw duration and `elapsed_weeks` the whole
                # days it was laid out over, so every leaf whose size was not a
                # multiple of a fifth of a week reported contents larger than its
                # own box. Carried anyway rather than left None on leaves: a field
                # present on some spans and absent on others makes every reader
                # ask which kind of span it has, and the answer would be "the ones
                # with children", which is the one thing a reader of a single span
                # cannot see.
                "budget_weeks": _budget_weeks(duration),
                "elapsed_weeks": _occupied_weeks(occupied[record_id], config),
            }
        )
        if explanation is not None:
            explanations[record_id] = explanation
        for worker in workers:
            booked[worker].append((span.start, span.end))

    # What is in each box, once every leaf that has a length has one. A record
    # that holds children is measured by the days its children occupy on EVERY
    # branch above — placed, unplaceable, or finished — which is the whole of
    # §3's reading and the thing three separate constructors used to each answer
    # for themselves. The finished branch answered it worst, with the record's
    # own start and end date, so a bet that ran from January to June holding one
    # week of work was reported as holding twenty-five.
    #
    # After the loop rather than inside it, because the historical branch runs
    # before the loop begins and a done pitch can hold a task that is still
    # running. Nothing in between reads `elapsed_weeks` — `_place` reads a
    # blocker's dates and nothing else off a span — so the only cost of waiting
    # is that a parent's contents are set a second time on the one branch that
    # already knew them.
    for record_id, span in list(spans.items()):
        if not children.get(record_id):
            continue
        spans[record_id] = span.model_copy(
            update={
                "elapsed_weeks": _occupied_weeks(
                    _intervals_under(record_id, children, occupied), config
                )
            }
        )

    return spans, explanations


def _intervals_under(
    record_id: str,
    children: Mapping[str, list[str]],
    occupied: Mapping[str, list[tuple[date, date]]],
) -> list[tuple[date, date]]:
    """Every stretch the leaves below `record_id` occupy, in no particular order.

    The whole subtree and not one level, so that a project is charged the days
    its tasks take wherever they hang: through a pitch that was placed, through
    one nobody has sized and that therefore has no span, and through a finished
    one whose own two dates are the box around those tasks rather than work
    beside them. Reaching downwards is also what makes this answerable at any
    moment, which the level-by-level version was not — it could only be computed
    as each parent was placed, and a finished parent is never placed.

    Overlaps are left in: `_occupied_weeks` merges, and a day counted twice here
    is still one day there. Sorting is its job too.

    A parent chain is allowed to contain a cycle — `validate_all` reports one as
    a blocker rather than refusing the plan, so the scheduler meets one — and
    `seen` is what makes that a subtree walk that terminates rather than a hang
    on a page somebody has to be able to open to fix it.
    """
    intervals: list[tuple[date, date]] = []
    seen = {record_id}
    stack = list(children.get(record_id, ()))
    while stack:
        kid = stack.pop()
        if kid in seen:
            continue
        seen.add(kid)
        intervals.extend(occupied.get(kid, ()))
        stack.extend(children.get(kid, ()))
    return intervals


def _place(
    record: Record,
    duration: float,
    workers: list[str],
    booked: dict[str, list[tuple[date, date]]],
    spans: dict[str, Span],
    floor: date,
    today: date,
    config: Config,
    by_id: dict[str, Record],
) -> tuple[Span, Explanation | None] | None:
    """Earliest slot at or after the record is ready, respecting capacity 1.

    `None` when no slot fits inside the calendar. The question used to be asked
    once, in `schedule`, against today — but the start is not today: a blocker
    dated at the end of time, or a worker booked until it, pushes it there, and
    then the walks below stepped off the calendar and raised. Asked against the
    start each time round the loop it is also what terminates the loop, since
    `start` only ever moves forward.

    `today` and `floor` are both here and they are different facts. The floor is
    the first WORKING day at or after today and is what a start is held to; today
    is the day the plan is drawn around, and it is the only honest thing to ask
    "has this date passed" against. Only `_explain` reads it.
    """
    blocker_id, blocker_ready = None, floor
    # Its own blockers and its ancestors': a dependency written on the pitch is
    # what its tasks wait for. See `blockers_of`.
    for target in blockers_of(record, by_id):
        if target in spans and spans[target].end >= blocker_ready:
            blocker_id, blocker_ready = target, _next_working_day(spans[target].end, config)

    # Work in progress started on the day its `start_date` names, and today
    # does not move it.
    #
    # The floor is `today`, and it exists so a plan never draws work starting in
    # the past — which is right for a bet nobody has picked up and wrong for one
    # somebody is holding. `in_progress` is a statement that the work HAS begun,
    # so its start is a fact rather than a forecast. Importing a cycle after it
    # ran is what showed this: every live bet in cycle 37 was drawn starting on
    # the day of the import, weeks after the review meeting that closed the
    # cycle, while the two `done` ones sat correctly back in July.
    #
    # Blockers do not hold it back either, for the same reason: if a thing is
    # under way, it is under way, and a graph that draws it waiting is drawing a
    # rule rather than the plan. An in-progress item whose blocker is unfinished
    # is a real and visible state — `_ordering` and the problems list are where
    # that gets said.
    begun = record.status == "in_progress" and record.start_date is not None
    ready = record.start_date if begun else max(floor, record.start_date or floor, blocker_ready)
    start = _first_working_day(ready, config)
    busy_worker, busy_until = None, None
    while True:
        if _runs_past_the_calendar(start, duration, config):
            return None
        end = working_days_after(start, duration, config)
        clash = [
            (worker, booked_end)
            for worker in workers
            for booked_start, booked_end in booked[worker]
            if booked_start <= end and start <= booked_end
        ]
        if not clash:
            break
        busy_worker, busy_until = max(clash, key=lambda pair: pair[1])
        # One person does one thing at a time — unless they are already doing
        # both. Contention is a forecast about work not yet picked up, and for a
        # bet somebody is holding it is a prediction about the past: the first
        # real cycle imported had one person on five live rows, and serialising
        # them drew the last one starting in late September, six weeks after the
        # review that closed the cycle. That someone is over capacity is true and
        # worth saying, and the load column and the cycle's over-capacity line
        # are where it is said, against the number rather than by moving a date.
        if begun:
            break
        start = _next_working_day(busy_until, config)

    return Span(start=start, end=end), _explain(
        record.id,
        start,
        floor,
        blocker_id,
        blocker_ready,
        busy_worker,
        busy_until,
        spans,
        # The date the floor is about to throw away, asked of the validator's own
        # predicate rather than of `record.start_date < floor` written out here.
        # The two are not the same question on a Saturday — the floor is the first
        # WORKING day, so a bare comparison against it calls a date that is still
        # today "passed" — and this sentence and the warning in `validate_all`
        # must be true of exactly the same records, or the page explains something
        # the check does not mention and vice versa.
        record.start_date if start_date_has_passed(record, today) else None,
    )


def _explain(
    record_id: str,
    start: date,
    floor: date,
    blocker_id: str | None,
    blocker_ready: date,
    busy_worker: str | None,
    busy_until: date | None,
    spans: dict[str, Span],
    passed: date | None,
) -> Explanation | None:
    """Name the constraint that actually decided the start date.

    Work that begins today is not delayed by anything and needs no sentence; the
    first *unexplained* surprising date is when people stop trusting the timeline.

    `passed` is the exception to that, and it is the one case a reader most needs
    a sentence for. A stated date that has gone by is discarded for the floor —
    `start` above is `max(floor, start_date, blocker_ready)` — so the record shows
    a start nobody typed, under a column labelled "Start date", with the date they
    DID type sitting in the frontmatter two rows above. This branch returned None
    there, which is silence at precisely the point where the page contradicts the
    file.

    **No date here is formatted.** Every one is named in a slot and handed over
    as a date, and `Explanation` fills the sentence in whichever format the reader
    it is going to reads every other date in. These sentences went out day-first
    from this function once, because the record page they are printed on draws its
    dates that way — and that made `openproj schedule` print a day-first sentence
    beside its own two ISO columns, and `--json` carry one inside a document whose
    every other date is ISO. Which format a sentence wants is a fact about the
    reader, and this function cannot see one.
    """
    if start <= floor:
        if passed is not None:
            return Explanation(
                record_id=record_id,
                # No `blocker_id` and no `worker_busy_until`: nothing is holding
                # this up. The constraint is the calendar, and the two fields
                # beside the sentence name the two things that are not it.
                sentence=(
                    "Starts on {start}: the {passed} you set has passed and work has not begun."
                ),
                parts={"start": start, "passed": passed},
            )
        return None
    if busy_until is not None and busy_until >= blocker_ready:
        return Explanation(
            record_id=record_id,
            sentence="Cannot start before {start}: {worker} is busy until {until}.",
            # `busy_worker` cannot be None here — it and `busy_until` are
            # assigned in one statement from the same `max`, and this branch has
            # already asked about the other half. `or ""` because the type does
            # not know that and `parts` is validated: where the old f-string
            # would have written the word "None" into the sentence, a None here
            # would raise, and this module's contract is that it never does.
            parts={"start": start, "worker": busy_worker or "", "until": busy_until},
            worker_busy_until=busy_until,
        )
    if blocker_id is not None:
        return Explanation(
            record_id=record_id,
            sentence="Cannot start before {start}: {blocker} finishes on {ends}.",
            parts={"start": start, "blocker": blocker_id, "ends": spans[blocker_id].end},
            blocker_id=blocker_id,
        )
    return None
