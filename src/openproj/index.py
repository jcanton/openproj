"""The single in-memory snapshot the table, the graph and the timeline render from.

Everything here is derived. `blocks` is the reverse of `depends_on` and is never
read from a file — a stored copy is stale by construction and lets one record
contradict the graph. Edges to records that do not exist are dropped rather than
carried, so the forward and reverse maps always agree.

Filter state lives entirely in query parameters, so facet and filter values are
strings, and `apply_filters` returns ids sorted by id: a shared URL must render
the same twice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from pydantic import BaseModel, model_validator

from .model import (
    PRIORITY_RANK,
    RUNG,
    STATUS_ORDER,
    Config,
    Cycle,
    Problem,
    Record,
    Unreadable,
    ancestors,
    checklist,
    cycle_of,
    sections,
    size_weeks,
    under,
    unread_fields,
    validate_all,
    workers_on,
)
from .query import QueryError, evaluate, parse
from .schedule import Explanation, Span, schedule

COMPUTED_PREDICATES = (
    "blocked",
    "unblocked",
    "overruns_cycle",
    # Any problem at all, of any severity. `has_blocker` is the strict half: the
    # table's headline counts blocking problems, and a link from that count to a
    # filter that also returns warnings sends people to rows there is nothing
    # wrong with — which is how a count stops being trusted.
    "missing_required_fields",
    "has_blocker",
    "review_waived",
    # Shape Up's circuit breaker, as a filter. Work still running past the end of
    # its cycle's build is the one list a betting table has to see, and it is
    # derived from dates the tool already has rather than from anything a person
    # remembers to set.
    "past_cycle_build",
    # In progress with nothing linked. Not a rule — opening a PR early to get CI
    # machine time is a good habit and a rule against it teaches people to stop
    # listing PRs — but it is a fair question to be able to ask of a whole cycle.
    "in_progress_without_prs",
    # Live work whose body keeps no checklist. A warning nobody has to act on —
    # the team's pitch template asks for one, and this is how you find the pitches
    # where nobody did. It is deliberately not a Problem: the body is prose.
    "untracked",
    "for_later",
)

_SCALAR_FACETS = ("kind", "status", "owner", "priority", "cycle")
_LIST_FACETS = ("assignees", "reviewers", "tags")
# The heading a deferred-scope list is written under, lowercased as `sections`
# returns it.
_FOR_LATER = "for later"


class Progress(BaseModel):
    """How far along one record is, and what that was counted from.

    Two sources, never both. A pitch with tasks is as far along as its tasks are,
    weighted by their sizes — half a bet is half its weeks, not half its rows, and
    a four-week task beside a half-week one is not two equal halves of anything.
    A leaf counts the task list in its own body instead.

    Derived, never stored. Completion is `status: done` on a child, and a stored
    checkbox mirroring it is a second copy of one fact — stale the first time
    somebody closes a task from the table, for the same reason `blocks` is
    derived and not written.
    """

    done: float
    total: float
    # "weeks" when it came from child tasks, "items" from a body checklist.
    unit: str
    # The children it was counted from, in the order they are drawn. Empty for a
    # body checklist, whose items are in the body and stay there.
    of: list[str] = []

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0

    @property
    def text(self) -> str:
        """`3/4 items` or `0/0.5 wk` — the unit always, whichever it is.

        The weeks carried theirs and the items did not, so one column held `1/1`
        beside `0/1 wk` and the two looked like different measurements of the
        same thing rather than measurements of different things. jcanton,
        2026-08-20: "please make it consistent".

        Which unit it is stays visible rather than being unified away: half a bet
        is half its weeks and not half its rows — the whole argument in this
        class's docstring — so a rollup cannot be counted in items, and a
        checklist cannot honestly be converted into weeks.
        """
        return f"{self.done:g}/{self.total:g} {'wk' if self.unit == 'weeks' else 'items'}"


def _weighed(kid: Record, rolled: Callable[[str], Progress | None]) -> tuple[float, float] | None:
    """One child's (done, total) weeks, or None when it carries no weeks at all.

    **The total is what was BET on that child.** A sized rung carries its own
    appetite and that is the number somebody typed, so it is the one used — a
    pitch counts for its appetite whether or not its tasks add up to it, which is
    the mismatch `_rollup_problems` exists to report rather than to hide. A
    container carries no appetite, so its total is what is under it.

    **A sized rung nobody has sized weighs nothing, and is left out of the
    fraction rather than counted at zero.** `size_weeks` used to answer
    `config.default_task_effort` for it — a fallback written for an unsized task,
    and applied to a container as readily, so a product holding a project worth
    five weeks reported `0/0.5 wk` under a meter reading "0 per cent of this bet
    is done", on a denominator nobody typed. Now that the answer is None, the
    same `return None` an empty container already takes is the honest one: a
    denominator this record cannot contribute to is a denominator it stays out
    of, and `Progress.of` names who was counted so the panel that lists them
    cannot list a record the fraction does not include.

    **The done half rolls up.** A child that is `done` counts for the whole of
    it — that is the only completion this model stores, and `Progress` says so.
    A child that is not done still counts for whatever is finished BENEATH it,
    so a project whose pitches are half-built reads half-built instead of zero.
    Before this, a container's children were weighed as leaves and two pitches at
    4/7.5 and 3/7.5 rolled up to a project reading 0/31.

    Container or leaf is read off the ladder — `Rung.sized` already means "may it
    carry person_weeks", which is exactly the question — so a seventh rung needs
    no edit here.

    None, rather than a default, when a container has nothing under it. An empty
    project contributes no weeks because there are no weeks under it, and
    inventing half of one puts the same made-up number back in a smaller place.
    It also keeps the units apart: a container whose own body has a checklist
    counts in items, and items cannot be summed into weeks — the same reason
    `Progress` refuses to convert one into the other.
    """
    below = rolled(kid.id)
    if RUNG[kid.kind].sized:
        stated = size_weeks(kid)
        if stated is None:
            return None
        total = stated
    elif below is not None and below.unit == "weeks":
        total = below.total
    else:
        return None
    if kid.status == "done":
        return total, total
    if below is not None and below.unit == "weeks":
        return below.done, total
    return 0.0, total


def _progress_of(
    record: Record,
    children: list[Record],
    rolled: Callable[[str], Progress | None],
) -> Progress | None:
    """A container's progress from what is under it, a leaf's from its own
    checklist. `rolled` answers a child's own rollup and is memoised by the
    caller, because a container's weight is not known until its descendants are.
    """
    if children:
        weighed = [(kid, _weighed(kid, rolled)) for kid in children]
        counted = [(kid, half) for kid, half in weighed if half is not None]
        if counted:
            return Progress(
                done=sum(done for _, (done, _) in counted),
                total=sum(total for _, (_, total) in counted),
                unit="weeks",
                of=[kid.id for kid, _ in counted],
            )
        # Nothing under here weighs anything: every child is a container with
        # nothing under it, or a sized rung nobody has sized. There is no honest
        # fraction either way, so there is none — the same answer a leaf with no
        # checklist gives, and for the same reason. A pitch whose tasks are all
        # unsized therefore draws no progress panel at all, where it used to draw
        # one over a denominator made entirely of the default: `2/2 wk` on four
        # tasks nobody had estimated, which is a measurement of nothing presented
        # as a measurement of the bet.
        return None
    ticked, items = checklist(record.body)
    return Progress(done=ticked, total=items, unit="items") if items else None


class Index(BaseModel):
    # THE PLAN, and only the plan: kinds whose rung says `planned`. Narrowed on
    # purpose rather than superseded — every PM surface (table, graph, timeline,
    # people, scheduler, facets, /api/index.json) reads this field, so a consumer
    # nobody edits stays correct, and one that is forgotten fails closed: it sees
    # fewer records, never an unplanned one on the timeline. One letter from
    # `plans` below, which holds the cycle FILES — a grep for either will find
    # both, and reading one for the other concludes a bet from a calendar.
    plan: dict[str, Record]
    # Every record that parsed, whatever its kind. The landing list, the detail
    # lookup and the delete cascade are its readers — the places that must
    # resolve an id that may name an issue or a note. Everything else reads
    # `plan`.
    #
    # Where the two inboxes went. `issues` and `notes` were separate maps here,
    # with a comment forbidding the rest of the index from reaching for them —
    # "a note that appears in a second view is a note that has become a bet
    # nobody made". That rule is now structural rather than admonitory: an
    # issue is a Record on an unplanned rung, so it lives in `records`, is
    # left out of `plan` by the one comprehension in `build_index`, and the
    # model_validator below refuses any Index built otherwise. A PM view
    # that is forgotten reads `plan` and fails CLOSED — fewer records,
    # never more — where the old type boundary failed open the day somebody
    # passed the wrong dict. What survives of the admonition is that the
    # reach is spoken: each name states its population, so a function about
    # the plan that takes `records` says so on the line that does it, and
    # `.records` is one grep away from every site that widened its view.
    records: dict[str, Record]
    children: dict[str, list[str]]
    blocked_by: dict[str, list[str]]
    blocks: dict[str, list[str]]
    spans: dict[str, Span]
    explanations: dict[str, Explanation]
    problems: list[Problem]
    # The plan files that are not records. Carried on the index rather than
    # handed to each renderer, because it is the answer to "is what I am looking
    # at the whole plan" and every page has to be able to say no.
    unreadable: list[Unreadable] = []
    facets: dict[str, list[str]]
    search_blob: dict[str, str]
    # Carried so a renderer needs nothing but the index: the timeline cannot draw
    # cycle boundaries or a today line without them, and it is handed no Config.
    cycles: dict[int, tuple[date, date]]
    plans: dict[int, Cycle]
    today: date
    # `default_task_effort` was carried here too, for the four renderers that
    # rebuilt a one-field `Config` out of it to ask `size_weeks` a question it no
    # longer answers. Nothing computes with it, so nothing carries it.
    nominal_availability: float = 1.0
    # Carried for the same reason the windows are: the timeline has to draw where
    # a cycle stops building, and it is handed no Config to ask.
    cooldown_weeks: float = 2.0
    # And the holidays, because a cycle's length is working days between two
    # meetings — the cycle page resolves an unsaved cycle through the same
    # `with_plans` a stored one goes through, and that needs them.
    holidays: list[date] = []
    # The roster from config/people.yaml, so a cycle nobody has been bet into yet
    # still has names to set availability against.
    known_people: list[str] = []
    # The repositories this plan's work happens in, carried for the reason the
    # roster is: a renderer is handed an index and never a Config, and the pull
    # request completion has to know which repositories to ask about.
    repositories: list[str] = []
    # The icon each person picked for themselves, login to icon name, from
    # `people/<login>.md`. The choice and not the record: the one page that draws
    # these wants the mark beside a name, and an index carrying the whole record
    # would be carrying a body nothing reads. Keyed on every login that has a
    # record — not on the roster — because the People page is built from who is
    # named in the record files, and a map keyed on the roster would draw nothing
    # for whoever was added to the plan this morning.
    icons: dict[str, str] = {}
    # How far along each record is, counted once here rather than re-derived by
    # every column, panel and predicate that wants to say it. See `Progress`.
    progress: dict[str, Progress] = {}
    # Ids whose body keeps a "for later" list — deferred scope, which is the only
    # record the plan has of a bet being trimmed to fit.
    for_later: list[str] = []

    @model_validator(mode="after")
    def _the_plan_holds_only_planned_kinds(self) -> Index:
        """The guarantee the type system gave up when every kind became a Record.

        `model.py` used to argue that an issue being a separate *type* is what
        kept it off the table by construction. This is that argument's
        replacement: one assertion at the single place an Index is made, instead
        of an exclusion in each of sixty read sites that somebody later forgets.
        """
        for record in self.plan.values():
            if not RUNG[record.kind].planned:
                raise ValueError(
                    f"{record.id} is a {record.kind}, and no {record.kind} belongs in "
                    "the plan: .plan holds planned kinds only — put it in .records"
                )
        return self

    def counts_in(self, record: Record, cycle: int) -> bool:
        """Whether this record's work lands inside this cycle's window.

        Bet into it, or **carried into it**: work bet in an earlier cycle and still
        running is doing so with this cycle's weeks. `cycle:` records where a bet
        was made and is never re-stamped (D-C1), which is what keeps an overrun
        accusing — but it also means a filter on `cycle == N` cannot see the
        carryover, and the page that exists to add up load was missing it.

        Carryover needs the cycle's dates to be answerable at all, so an undated
        cycle counts only what was bet into it by name: a number nobody has given
        a window to is a hypothetical, and letting it absorb every running item
        would put the whole plan's load on a page for a cycle that may never run.

        **A record with no span carries into nothing it has not started.** The
        last line read `span is None or (...)`, written when no span meant the
        scheduler had tried and failed: a rare record, live work in a dated
        window, and worth counting late rather than losing. It stopped meaning
        that when the default appetite went. An unsized record now leaves the
        placer by a `continue` and gets no span at all, which is the normal state
        of every `shaping` and `thinking` bet — precisely the population
        `unsized_in` exists to count — so each of them was carried into every
        dated cycle after its own, for ever. The `· N not sized` badge that exists
        to explain a shrinking total over-reported on all of them, and
        `carried_into` listed bets nobody has shaped as carryover into cycles they
        have nothing to do with. A bet is a fact somebody stated and it counts
        where it was stated, which the `mine == cycle` line above has already
        answered.

        **A placement is not the only thing that says work is still running.**
        Dropping that disjunct outright overshot in the other direction. The size
        gate is `ready` only, so unsized-and-`in_progress` is reachable by the
        normal path rather than by skipping a rung — §2 of `design/time-model.md`
        counts three such records in icon4py-plan — and each of them vanished
        from the very cycle somebody is working on it in: no weeks, which is
        right, and no `· N not sized` beside them, which is the silent shrink the
        badge was added to prevent. `in_progress` plus a start date is what is
        left when there is no span, and what it can honestly claim is the stretch
        from that date to today. Not one day further: nobody has said how long
        this takes, so a forecast would be an invention, and inventing one
        forwards is precisely the haunting above. `today >= window[0]` is that
        limit written down — a cycle that has not opened can never pick this up.
        A record `in_progress` with no start date at all is a blocker at the door;
        here it is bounded at today, so it counts in the cycle running now and in
        no earlier one.

        **Only where there is no span at all**, and the sized sibling in
        `test_work_that_has_started_is_counted_where_it_is_running_even_with_no_size`
        is the boundary. A record the scheduler placed is answered by its dates,
        because a status nobody has kept up to date is not a second calendar: a
        task that ran 22–26 June and is still marked `in_progress` is carried by
        its span into the cycles that span touches and no others. Reading the
        status there too would put every stale record into every cycle from its
        start to today — the same haunting, differently sourced.

        **The state that clause was written for no longer reaches it.** A record
        the scheduler genuinely cannot place — a dependency cycle, a duration
        that outruns the calendar — is given `Span(unscheduled=True)` at the
        floor on both of `schedule`'s branches rather than nothing, so it is
        still counted, in the cycle today falls in. Nothing is unplaceable and
        sized any more: having no span means having no length anybody stated.

        Carryover is decided by the dates and not by the status. It asked for
        `in_progress`, which dropped a `ready` task sitting under a carried pitch
        even where its own span ran through the middle of this cycle — work
        somebody is about to do, in weeks this page is adding up, missing from the
        total. What has not started yet is still what a person's next weeks are
        spent on; whether it has begun is a different question from when it lands.
        """
        if record.status in ("done", "shelved"):
            return False
        # The cycle of the BET this work is part of, which for a task under a
        # pitch is the pitch's. A task does not carry its own — the bet is made
        # once, on the thing the room named.
        mine = cycle_of(record, self.plan)
        if mine == cycle:
            return True
        if mine is None or mine >= cycle:
            return False
        window = self.cycles.get(cycle)
        if window is None:
            return False
        span = self.spans.get(record.id)
        if span is not None:
            return span.start <= window[1] and span.end >= window[0]
        if record.status != "in_progress":
            return False
        # The one measurement an unsized record has. `or self.today` is a bound
        # and never a date this returns or draws: with no start date the stretch
        # collapses to today, which is the cycle the work is demonstrably in.
        began = record.start_date or self.today
        return began <= window[1] and self.today >= window[0]

    def build_end(self, cycle: int | None) -> date | None:
        """The last day of a cycle's build.

        From the record where there is one — `with_plans` fills `builds_until` in
        from the two meeting dates — and otherwise from the window less the
        cool-down. Asked through the index rather than by rebuilding a `Config`,
        which would substitute the default cool-down for the repository's own and
        leave a filter quietly disagreeing with the timeline it explains.
        """
        window = self.cycles.get(cycle) if cycle is not None else None
        if window is None:
            return None
        plan = self.plans.get(cycle)
        if plan is not None and plan.builds_until is not None:
            return plan.builds_until
        return window[1] - timedelta(days=round(self.cooldown_weeks * 7))

    def load(self, cycle: int) -> dict[str, float]:
        """Person-weeks each person is holding in this cycle.

        Charged where the assignees are, and split evenly among them (D-C4): a
        pitch whose children carry the names charges nothing itself, because its
        appetite is a rollup and charging both counts the same work twice.

        A carried item is charged its whole size, not the part of it that is left.
        Nothing in the plan records how much of a bet is done — the checklist in
        its body is a hint, not a measurement — and an invented percentage is a
        worse answer than a known overcount that a person can see and argue with.

        Work nobody has sized charges nobody, and `unsized_in` is how a page says
        so — read them together or the number is smaller than it was last week
        for a reason nothing on the screen gives.
        """
        return self._charged(cycle)[0]

    def unsized_in(self, cycle: int) -> dict[str, list[str]]:
        """Ids counted against this cycle that state no size, by the person they
        are on the hook for.

        The other half of `load`. `thinking` and `shaping` work is legitimately
        unsized — a bet nobody has shaped yet has no appetite, and the validator
        deliberately does not demand one — but `counts_in` says all of it is what
        somebody's next weeks are spent on, so it used to be charged half a week
        each and quietly held up a total. With the default gone the total is the
        weeks somebody actually stated, which is smaller and correct, and a
        smaller number arriving with no explanation is exactly the defect this
        pairing prevents.

        **Where it was bet, and then wherever it is actually being worked on.**
        Everything that lands in here is a sized-nothing leaf, and a leaf with no
        size gets no span, so this list and `counts_in`'s carryover arm are two
        readings of one condition — which is why it is that method that answers
        both, and not a second rule written here. A bet nobody has started is
        counted once, in the cycle it was stated in, and haunts nothing after it;
        one that is `in_progress` is counted again in each cycle between its start
        date and today, because that is where somebody's weeks are going. Both of
        those are `counts_in`'s wording, so the count on a page and the weeks
        beside it are over one set of records rather than two that agree most of
        the time.

        Keyed by person rather than counted, because the two callers want
        different arithmetic over the same walk: a person's own figure names the
        records on their own hook, and a cycle's names the distinct records
        behind every figure on the page — a record with two assignees is one
        unsized bet on the cycle card and one on each of their rows.
        """
        return self._charged(cycle)[1]

    def _charged(self, cycle: int) -> tuple[dict[str, float], dict[str, list[str]]]:
        """One walk, both answers: the weeks charged and the records that could
        not be.

        Two methods over one loop rather than two loops, because the three gates
        that decide whether a record is charged at all — `counts_in`, having
        somebody on it, and not being a rollup of its own children — are what a
        second walk would get subtly wrong, and a person's load disagreeing with
        the count of what is missing from it is worse than either number alone.

        Which is why running-but-unsized work was answered by widening
        `counts_in` rather than by giving `unsized_in` a question of its own. A
        badge drawn over a wider set than the bar beside it, and than the
        carryover list the page prints underneath to explain the bar, is the same
        disagreement the carryover arm was just fixed for, moved one method along
        — and a count of records nothing on the page names is a number you cannot
        act on.
        """
        held: dict[str, float] = {}
        unsized: dict[str, list[str]] = {}
        for record in self.plan.values():
            if not self.counts_in(record, cycle):
                continue
            people = workers_on(record)
            if not people or self.children.get(record.id):
                continue
            size = size_weeks(record)
            for who in people:
                if size is None:
                    unsized.setdefault(who, []).append(record.id)
                else:
                    held[who] = held.get(who, 0.0) + size / len(people)
        return held, {who: sorted(ids) for who, ids in unsized.items()}

    def carried_into(self, cycle: int) -> list[str]:
        """Ids counted against this cycle that were bet in an earlier one."""
        return sorted(
            record.id
            for record in self.plan.values()
            if cycle_of(record, self.plan) != cycle and self.counts_in(record, cycle)
        )


def _project_of(record: Record, by_id: dict[str, Record]) -> str | None:
    """The project a record belongs to, walking up the parent chain."""
    return _holder_of(record, by_id, "project")


def _product_of(record: Record, by_id: dict[str, Record]) -> str | None:
    """The product a record belongs to. Same walk, one rung further up."""
    return _holder_of(record, by_id, "product")


def _holder_of(record: Record, by_id: dict[str, Record], kind: str) -> str | None:
    """The nearest ancestor of this kind, walking up the parent chain.

    A task names its pitch, never its project, so grouping by either is empty
    unless the chain is followed.

    One walk asked for a kind rather than one walk per kind: `product` was added
    above `project` and this was the function that would otherwise have been
    copied, with the copy free to disagree about what an unresolvable parent
    means.
    """
    if record.kind == kind:
        return record.id
    for ancestor in ancestors(record.id, by_id):
        # `.get`, not `[]`. `ancestors` returns the chain as it is *named*, so its
        # last link can be an id no file was ever written for — and a dangling
        # parent is deliberately not a validation problem (see the `task()` helper
        # in test_validate), so a plan is allowed to contain one. Indexing it
        # raised KeyError out of `build_index`, which is the read path of `/`,
        # `/detail/<id>`, `/graph`, `/timeline`, `/people` and `/api/index.json`
        # alike: one committed `parent` field, sent by any signed-in member and
        # accepted with a 200, answered 500 to every reader on every page from
        # then on. Branch protection means that commit cannot be force-pushed
        # away, and the 500ing pages will not give you the sha to repair against.
        #
        # Unresolvable is answered the same way as no parent at all: no project.
        # Inventing one would put a node in the facet menu that the graph and the
        # table cannot agree exists, which is the failure the `blocked_by` edge
        # map already refuses next door.
        named = by_id.get(ancestor)
        if named is not None and named.kind == kind:
            return ancestor
    return None


# The one option in a facet menu that is not a value out of the data: it selects
# the records where the field is empty.
#
# "Which pitches are not in a cycle yet" and "what has no reviewer" are the two
# questions a betting table actually asks, and neither could be asked at all —
# an unset field produces no facet value, so it could never be selected, and the
# blank option at the top of every menu means "no constraint" rather than
# "empty". Spelled in brackets, because a facet value is a login, a tag, a cycle
# number or a status, and none of those is ever written like this.
NO_VALUE = "(none)"

# What the search box searches, in one place, for both halves of the app.
#
# It used to be two definitions: this file swept title, tags, PR references *and
# the whole shaping document* into one blob, while the browser searched
# `row.title + ' ' + row.tags`. A word in a body found rows through a pasted link
# and nothing in the box in front of you; `#1364` found the record on the server
# and nothing in the table — and neither side erred, which is the shape of every
# divergence this repository has shipped. The blob is built here now and travels
# on the row (`_row` in `render.py`), so the browser searches the string the
# server searched rather than a second idea of what a record says.
#
# **Fields, not bodies** — jcanton, 2026-08-19. The shaping document IS the
# record, but it is not the record's index: a 900-word pitch in a substring
# search makes every long word in the plan a match for something, and the reader
# cannot see why a row was kept. The document is read on the detail page, which
# is where a document is read.
#
# These and not every field: they are what a person names a record BY — its
# id, what it is called, the labels somebody put on it, the pull requests it is
# argued in, and the people whose names are on it. `reported_by` and `written_by`
# are people fields like `owner`: the two inbox list pages this blob replaced
# matched an issue by its reporter and a note by its writer, and "the issue
# halungge reported" is how those records get asked for. On a kind without the
# field, `searchable`'s `getattr` answers None and the blob is unchanged.
# `status`, `kind`, `priority` and `cycle` are deliberately absent: each has a
# dropdown that says which values exist, and sweeping them in means typing
# `ready` matches half the plan through a box that cannot say which field it
# matched.
#
# What those inbox pages matched that this deliberately does NOT: the BODY.
# Their blobs were `id + title + tags + author + body`, so a word that appears
# only in an issue's prose found the issue there and finds nothing anywhere now
# — a known capability regression, not an oversight. It is not restored because
# this blob rides every row of /table and the landing, and "Fields, not bodies"
# above is the standing ruling for exactly that cost: putting `body` in would
# inline every shaping document into every table page load. The decision was
# deferred to the branch that widened the landing row and it was decided there:
# the widened row already carries every query field, so the blob is the one
# remaining place a body could ride, at the same cost that ruled it out of the
# table — the inbox kinds earn no exception. Anyone reopening this reopens it
# for the query language (`body:` as a field), not for the blob.
SEARCH_FIELDS = (
    "id",
    "title",
    "tags",
    "prs",
    "owner",
    "assignees",
    "reviewers",
    "reported_by",
    "written_by",
)


def searchable(record: Record) -> str:
    """One record's searchable text: every value in `SEARCH_FIELDS`, lowered.

    Lowered here rather than at each comparison, because the browser holds this
    string and compares a lowered needle against it; a second `.toLowerCase()`
    per row per keystroke is the same answer computed fifteen thousand times.
    """
    said: list[str] = []
    for field in SEARCH_FIELDS:
        value = getattr(record, field, None)
        said += value if isinstance(value, list) else [value] if value else []
    return " ".join(said).lower()


def _ordered(field: str, values: set[str]) -> list[str]:
    """Alphabetical, except where the values are a sequence rather than a set.

    Sorting a status alphabetically puts `done` at the top of the menu and
    `shaping` second from the bottom — the exact reverse of the order work moves
    in, for the first four of five. Priority reads `high, low, medium`, which is
    not an order anybody means by priority.
    """
    # `(none)` first wherever it appears, because it is not one of the values —
    # it is the question "which of these has nobody in it", and sorted with the
    # rest it lands under the bracket's ASCII position, above every login, where
    # it reads as somebody's name.
    rest = values - {NO_VALUE}
    head = [NO_VALUE] if NO_VALUE in values else []
    ranked = {"status": STATUS_ORDER, "priority": tuple(PRIORITY_RANK)}.get(field)
    if ranked is None:
        return head + sorted(rest)
    known = [v for v in ranked if v in rest]
    return head + known + sorted(v for v in rest if v not in ranked)


# The facets that are not a field on the record but an ancestor of it: a task
# names its pitch and nothing else, so "which project" and "which product" are
# both answers to a walk up the chain. Written once because three call sites ask
# the same question — `build_index`, `query_fields` and `matching` — and a list
# that grew a rung in two of them would offer a menu that filters nothing.
_HOLDER_FACETS = ("product", "project")


def _facet_values(record: Record, field: str, by_id: dict[str, Record]) -> list[str]:
    """Every value of `field` on this record, as strings. Absent values yield none.

    An unset field is not a facet value: emptiness is selected with `NO_VALUE`,
    which is a menu option rather than a fake owner named "unowned".
    """
    if field in _HOLDER_FACETS:
        holder = _holder_of(record, by_id, field)
        return [holder] if holder else []
    # A field this rung does not read has no value to offer, whatever the model
    # defaults it to. `status` defaults to `shaping` on every record, so without
    # this a product — which has no status at all — answered the Status menu as
    # if somebody had shaped it, and filtering to `shaping` brought back a
    # codebase.
    if field in unread_fields(record.kind):
        return []
    value = getattr(record, field, None)
    if isinstance(value, list):
        return [str(item) for item in value]
    return [] if value is None else [str(value)]


def build_index(
    parsed: list[Record],
    config: Config,
    today: date,
    unreadable: Iterable[Unreadable] = (),
) -> Index:
    records = {record.id: record for record in parsed}
    # THE INVERSION (spec §2). Filtered here, once, and nowhere else: every
    # consumer takes `plan` or `records` off the Index by the name that states
    # its population, and the model_validator on Index refuses a plan holding
    # an unplanned kind — so this comprehension is the single place the
    # narrowing can happen, or go wrong.
    plan = {rid: record for rid, record in records.items() if RUNG[record.kind].planned}
    children: dict[str, list[str]] = {record_id: [] for record_id in records}
    blocked_by: dict[str, list[str]] = {}
    # Total over records, not over the plan: the record page draws fact rows for
    # every kind, and a map missing a key there is a KeyError on a page, not a
    # smaller answer.
    blocks: dict[str, list[str]] = {record_id: [] for record_id in records}

    for record in parsed:
        if record.parent in children:
            children[record.parent].append(record.id)
        blocked_by[record.id] = [target for target in record.depends_on if target in records]
        for target in blocked_by[record.id]:
            blocks[target].append(record.id)

    spans, explanations = schedule(parsed, config, today)

    facets: dict[str, set[str]] = defaultdict(set)
    search_blob: dict[str, str] = {}
    progress: dict[str, Progress] = {}
    for_later: list[str] = []
    # The blob is total: the landing list searches every record, and a record
    # missing from it is one its own page cannot find. PR references included —
    # "which record is #1364?" is asked in front of a screen, and the answer was
    # only findable if the number also appeared in the prose. What goes in is
    # `SEARCH_FIELDS`, which is also what a row carries to the browser.
    for record in records.values():
        search_blob[record.id] = searchable(record)
    # Progress is computed depth-first and memoised, because a container's weight
    # is what is under it and that is not known when `plan.values()` happens to
    # reach it. The memo doubles as the cycle guard: a record already being
    # computed answers None rather than recursing, so a hand-written parent loop
    # in somebody's file costs a missing fraction and not a RecursionError. The
    # graph's own cycle check reports the loop; this only has to survive it.
    rolling: dict[str, Progress | None] = {}

    def _rolled(record_id: str) -> Progress | None:
        if record_id in rolling:
            return rolling[record_id]
        rolling[record_id] = None
        # A shelved child is not work anybody is waiting for, so it counts in
        # neither half of the fraction — otherwise parking a task makes a pitch
        # look less finished than it was the day before. Looked up in `plan`,
        # not `records`: an unplanned record with a hand-written `parent` is
        # already a containment problem, and counting it into a pitch's progress
        # would let the bad file move a number on the table.
        kids = [plan[k] for k in children[record_id] if k in plan and plan[k].status != "shelved"]
        rolling[record_id] = _progress_of(plan[record_id], kids, _rolled)
        return rolling[record_id]

    # Facets, progress and deferred scope are PLAN facts: an unplanned kind in a
    # facet menu is a dead option on the table.
    for record in plan.values():
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS):
            values = _facet_values(record, field, records)
            # `NO_VALUE` is offered only where something is actually missing, so
            # a menu never carries an option that can select nothing. Every
            # status has a value, so Status never grows one; Cycle grows one the
            # moment a pitch is written and not yet bet.
            facets[field].update(values or [NO_VALUE])
        counted = _rolled(record.id)
        if counted is not None:
            progress[record.id] = counted
        if sections(record.body).get(_FOR_LATER):
            for_later.append(record.id)

    return Index(
        plan=plan,
        records=records,
        children=children,
        blocked_by=blocked_by,
        blocks=blocks,
        spans=spans,
        explanations=explanations,
        # With the spans, which is what turns `_rollup_problems` on: whether a
        # pitch's tasks fit is a comparison between two numbers the scheduler
        # computed, and `model.py` cannot reach the scheduler to compute them.
        # `schedule` ran above, so this costs nothing beyond passing the dict.
        # `today` for the same reason, and it is not `date.today()`'s business to
        # answer here: this index may be drawn around a pinned day — `openproj
        # demo` pins one — and a rule that asked the clock instead would report a
        # start date as passed on a plan whose whole calendar says otherwise.
        problems=validate_all(parsed, config, spans, today),
        unreadable=list(unreadable),
        facets={field: _ordered(field, values) for field, values in facets.items()}
        | {"predicate": sorted(COMPUTED_PREDICATES)},
        search_blob=search_blob,
        cycles=config.cycles,
        plans=config.plans,
        nominal_availability=config.nominal_availability,
        cooldown_weeks=config.cooldown_weeks,
        known_people=config.known_people,
        repositories=config.repositories,
        icons={login: person.icon for login, person in config.people.items() if person.icon},
        today=today,
        holidays=config.holidays,
        progress=progress,
        for_later=for_later,
    )


def _is_blocked(index: Index, record_id: str) -> bool:
    """Blocked means waiting on work that is not over.

    Reading a non-empty `depends_on` as "blocked" would park a live task behind
    something finished months ago. The blocker is looked up in `records`:
    `blocked_by` is total over records, so its targets are there by
    construction, and a hand-written edge to an unplanned kind must not 500 the
    page that draws it.
    """
    return any(
        index.records[blocker].status not in ("done", "shelved")
        for blocker in index.blocked_by[record_id]
    )


# Looked up in `records`, never `plan`: predicates run over whichever
# population `apply_filters` was handed, and the landing search hands it the
# whole one. `plan` ⊂ `records`, so the total map is always the safe door.
def _matches_predicate(index: Index, record_id: str, predicate: str) -> bool:
    if predicate == "blocked":
        return _is_blocked(index, record_id)
    if predicate == "unblocked":
        return not _is_blocked(index, record_id)
    if predicate == "overruns_cycle":
        span = index.spans.get(record_id)
        return span is not None and span.overruns_cycle_weeks is not None
    if predicate == "missing_required_fields":
        return any(problem.record_id == record_id for problem in index.problems)
    if predicate == "has_blocker":
        return any(
            problem.record_id == record_id and problem.severity == "blocker"
            for problem in index.problems
        )
    if predicate == "review_waived":
        return index.records[record_id].review_waived
    if predicate == "past_cycle_build":
        record = index.records[record_id]
        span = index.spans.get(record_id)
        window = index.cycles.get(record.cycle) if record.cycle is not None else None
        if record.status != "in_progress" or span is None or window is None:
            return False
        return span.end > index.build_end(record.cycle)
    if predicate == "in_progress_without_prs":
        record = index.records[record_id]
        return record.status == "in_progress" and not record.prs
    if predicate == "untracked":
        # Live work that says nothing about how far along it is: no tasks under
        # it and no checklist in it. A pitch with tasks is tracked by them.
        return (
            index.records[record_id].status in ("ready", "in_progress")
            and record_id not in index.progress
        )
    if predicate == "for_later":
        return record_id in index.for_later
    return False


def predicates_of(index: Index, record_id: str) -> list[str]:
    """Every computed predicate that holds for this record, in ladder order.

    One spelling for the three payloads that carry a record's flags — this
    module's `query_fields`, the table's `_row` and the landing's
    `_record_row` — because the browser's `matches()` and the server's
    `apply_filters` answer `predicate:` from these lists, and a site that
    filtered `COMPUTED_PREDICATES` its own way would disagree silently.
    """
    return [name for name in COMPUTED_PREDICATES if _matches_predicate(index, record_id, name)]


def query_fields(index: Index, record_id: str) -> dict[str, list[str]]:
    """One record's values per field, lowered — what `query.evaluate` asks about.

    The browser builds the same map out of the row it was shipped (`queryFields`
    in `_FILTER_JS`), so the two parsers are handed identical data and a
    disagreement between them is the language rather than the plan.
    """
    record = index.records[record_id]
    fields = {
        field: [value.lower() for value in _facet_values(record, field, index.records)]
        for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS)
    }
    fields["id"] = [record.id.lower()]
    fields["title"] = [record.title.lower()]
    fields["prs"] = [pr.lower() for pr in record.prs]
    fields["predicate"] = predicates_of(index, record_id)
    return fields


def cascade_of(index: Index, record_id: str) -> tuple[list[str], list[str]]:
    """What deleting this record takes with it: (also deleted, edited).

    Two different consequences, and conflating them would be the destructive
    mistake. A record filed UNDER this one has nowhere to be once it is gone, so
    it goes too — the whole subtree, however deep. A record that DEPENDS on this
    one is unrelated work that merely waits for it: deleting that would be a
    two-click gesture reaching across the plan into somebody else's task. It
    keeps its file and loses the dependency.

    Shelved work is in both lists. It is parked, not exempt: a shelved task under
    a deleted pitch is orphaned exactly as much as a ready one.

    Computed here rather than in the handler because the page has to show the same
    two lists before anybody presses anything, and a confirmation built from a
    second derivation of this is a confirmation that can be wrong.
    """
    doomed = under(record_id, index.children)
    going = {record_id, *doomed}
    edited = sorted(
        other
        for other, record in index.records.items()
        if other not in going and going.intersection(record.depends_on)
    )
    return sorted(doomed), edited


def apply_filters(
    index: Index,
    filters: dict[str, list[str]],
    query: str,
    over: dict[str, Record] | None = None,
) -> list[str]:
    """AND across fields, OR within a field, then the query language.

    `over` picks the population and defaults to the plan: every caller that
    existed before the landing page is a PM surface, so a caller that forgets
    to ask for more fails closed. The landing list passes `index.records`.

    An unknown field or predicate matches nothing rather than everything: filter
    state comes from a hand-editable query string, and a typo that silently widens
    the result set is worse than one that visibly empties it.

    A query that cannot be read matches nothing, for the same reason and one
    more: half a query is a query somebody is still typing, and a table that
    widens to everything on the way to `kind:task and (` flickers through the
    whole plan at every keystroke. The sentence is not shown from here — this
    function answers with rows — so the caller that has a reader in front of it
    asks `parse` itself. See `render.py`'s `queryError`.
    """
    try:
        asked = parse(query)
    except QueryError:
        return []
    matched = []
    for record_id, record in (index.plan if over is None else over).items():
        fields = query_fields(index, record_id)
        if not evaluate(asked, fields, index.search_blob[record_id], NO_VALUE):
            continue
        for field, wanted in filters.items():
            if not wanted:
                continue
            if field == "predicate":
                found = any(_matches_predicate(index, record_id, value) for value in wanted)
            elif field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS):
                # Empty is selectable, and it is the absence of every value
                # rather than one more of them — so it is asked of the list
                # itself, not looked up in it. Resolved against `records`, like
                # the menu these values came from and `query_fields` four lines
                # up — the holder walk starts at the record itself, so a plan
                # lookup answers None for any record the plan does not hold.
                values = _facet_values(record, field, index.records)
                found = bool(set(values) & set(wanted)) or (NO_VALUE in wanted and not values)
            else:
                found = False
            if not found:
                break
        else:
            matched.append(record_id)
    return sorted(matched)
