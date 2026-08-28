"""One record as the pages see it: the view model the table, graph and timeline share."""

from __future__ import annotations

from ..index import Index, _product_of, _project_of, predicates_of
from ..model import RUNG, size_weeks, unread_fields, workers_on

# The record page's own reading of what a pitch's tasks come to, imported rather
# than repeated. It is the wrong way up as a dependency — this module is the view
# model three pages share and that one is a page — and it is still the right
# import: the alternative is a second gate and a second read of the same span
# beside a comment promising they agree, which is the exact shape of the defect
# `_tasks_add_up_to` was itself fixed for. `detail` reaches nothing here, so the
# graph stays acyclic; the day something else needs this number as well, the
# function moves down here and the record page imports it back.
from .detail import _tasks_add_up_to, _tasks_under
from .tokens import _SIZE_FIELD_NAME


def _reviewers_under(index: Index, record_id: str) -> list[str]:
    """`model.reviewers_under`, over the index's own child map.

    The map the validator walks is built from records and skips shelved ones;
    this one is `index.children`, which is ids. Two shapes of the same fact, so
    the walk is here and the rule is there — and the rule is the one that decides
    whether anything is wrong, which is why this function only draws.

    A `seen` set for the same reason `reviewers_under` has one: a parent cycle is
    a blocker this tool reports rather than a plan it refuses to load, so this map
    really can hold A whose child is B whose child is A — and a walk without it
    never comes back.
    """
    found: list[str] = []
    seen: set[str] = {record_id}
    stack = list(index.children.get(record_id, []))
    while stack:
        child = index.plan.get(stack.pop())
        if child is None or child.status == "shelved" or child.id in seen:
            continue
        seen.add(child.id)
        found += child.reviewers
        stack += index.children.get(child.id, [])
    return list(dict.fromkeys(found))


def _rollup(index: Index, record_id: str) -> dict | None:
    """What the work under this record occupies, and how that reads against its bet.

    None wherever there is nothing to say: on a rung that reads no appetite at
    all (see below) and on every leaf. `_tasks_add_up_to` is what answers the
    number and is called rather than re-derived, so the sentence the record page
    prints under Appetite and the cell the table draws are the same fact read
    once. They said different numbers for a while — the page summed
    `index.progress[id].total` while `check` summed only the sized children —
    and then they went on disagreeing about which records had a number at all,
    because the page kept `index.progress` as its GATE after the arithmetic had
    moved to the span. Both halves are `tasks_occupy` (`model.py`) now, and
    `kids` below is the same list the number was computed over rather than a
    second reading of the child map.

    **Having children is what decides whether there is a cell at all, and it
    used to be having a NUMBER.** `_tasks_add_up_to` answers None for a pitch
    none of whose tasks has a length, and returning None with it took the fourth
    state away from the one plan it was written about: a bet over three `shaping`
    tasks has nothing sized under it at all, which is strictly worse than the
    three-sized-and-four-unsized case that did get the `?`, and it drew its bet
    plainly with no mark, no muted ground and no sentence. So the gate is `kids`
    — the work under this record — and the missing number is a reading rather
    than a reason to say nothing. Shelved children are not in that list, so a
    pitch whose every task is parked still falls out here exactly as it did when
    the number was the gate: `_progress_of` leaves shelved work out of the
    rollup, so there was never a number for one of those either.

    **One value, so that the tint and the mark cannot disagree.** The state below
    is `Span.budget_weeks` against `Span.elapsed_weeks`, which is exactly the
    comparison `_rollup_problems` (`model.py`) makes and the ONLY one drawn
    anywhere on this row: the browser is handed a word and looks up a glyph and a
    class for it, rather than being handed two numbers and asked to compare them
    a second time. A second comparison would be a second implementation of the
    rule this repository has already been bitten four times by writing twice, and
    it would drift in the worst possible direction — a cell painted green over a
    warning triangle explaining why the bet does not fit.

    The `over` state is the one that carries no tint of its own, and that is the
    same argument seen from the other side. `_rollup_problems` fires on exactly
    `elapsed > budget`, `MARK_COLUMN` routes its `person_weeks` field to this
    column, and `cell()` grounds a cell carrying a warning in `--sev-warn-soft`.
    Painting a second warn ground from this state would be a second copy of one
    colour whose only possible future is to disagree with the first.

    **Four states and not three.** With no default appetite left, a pitch holding
    three sized tasks and four unsized ones occupies only the days of the three —
    a real number, under the box, and green would say the bet is known to fit
    when nobody has estimated more than half of it. So a child that adds nothing
    to the union takes the reading away rather than flattering it, and the
    sentence says how many did. The same state covers the case where EVERY child
    adds nothing, and there the cell has no number to print at all — `?` over "no
    length yet", which is the whole of what is known about that bet.

    A child adds nothing when it has no span at all (nobody sized it, §2 of
    `design/time-model.md`) or a span with no length (a `done` record written
    before `end_date` was asked for). Both are read off the span rather than off
    `person_weeks`, because the span is what the number in the cell was measured
    from — asking the field would let a child that is sized but contributes
    nothing pass as though it had been counted.

    Shelved children are not in that count, and the list is the same one
    `_progress_of` rolls up: parked work is not work anybody is waiting on, and
    counting it would put a permanent `?` on every pitch that has ever shelved a
    task.

    And a fifth state for the pitch nobody has bet on yet, which the design's
    table does not enumerate because it is not a reading of the box — there is no
    box. It says what its tasks come to and offers no verdict: warning-colouring
    a record `check` is silent about is how a reader learns that one of the two
    is lying to them.
    """
    record = index.plan[record_id]
    # Only on a rung that reads an appetite at all. A project has work under it
    # and no `person_weeks` of its own — `_rollup_problems` says so in as many
    # words, "a project is not bet, its pitches are" — so a number in its
    # appetite column would be a box nobody bought, in a column the row's own
    # rule already says it does not hold. `unread_fields` is that rule, and it is
    # the same list `_row` below empties every other cell of a container by.
    #
    # It is also what keeps this cell and the record page saying the same thing:
    # `_fact_rows` draws an Appetite row out of the model's fields, so a project
    # has none there and would have had one here.
    if _SIZE_FIELD_NAME in unread_fields(record.kind):
        return None
    kids = _tasks_under(index, record_id)
    if not kids:
        return None
    silent = [
        child
        for child in kids
        if index.spans.get(child) is None or index.spans[child].elapsed_weeks is None
    ]
    contents = _tasks_add_up_to(index, record)
    # `.get`, because a pitch whose children are ALL unsized is scheduled
    # nowhere: the rollup branch of `_schedule` takes `min`/`max` over the spans
    # its children came back with and `continue`s when there are none. That
    # record has no box either — `budget_weeks` travels on the span — so the
    # sentence below can name the bet and the people and stops there.
    span = index.spans.get(record_id)
    box = span.budget_weeks if span is not None else None
    # The bet as the FILE states it, and the people the scheduler divided it by
    # to get the box. Both are named because the box alone is not recoverable
    # from either: this row printed `bet 4.0 weeks` on a record whose file says
    # `person_weeks: 8`, which invites somebody to go looking for a 4 that is
    # written nowhere. The appetite is in person-weeks and the box is in calendar
    # ones, and the sentence has to carry the conversion or it is two units with
    # the reader left to notice — the defect the record page carried in the same
    # words. `workers_on` and not `assignees`, because that is the list
    # `_duration_weeks` divided by; `_rollup_problems` counts the same names in
    # the sentence it yields about this same comparison, and two counts of two
    # different sets of people explaining one number is how they come apart.
    stated = size_weeks(record)
    people = len(workers_on(record)) or 1
    bet = (
        f"Bet {stated:g} over {'1 person' if people == 1 else f'{people} people'}"
        if stated is not None
        else "No bet on this yet"
    )
    if contents is None:
        # Nothing underneath has a length, so there is no reading to give — only
        # the bet, and the fact that nobody has estimated what is meant to go in
        # it. No count of the silent children, unlike the partial state below:
        # they are all of them, and "1 of its 1 have no length yet" is a sentence
        # about one task written as arithmetic.
        state = "unsized"
        text = "no length yet"
        why = (
            f"{bet}. Nothing under it has a length yet, "
            "so nothing can be said about whether it fits."
        )
    else:
        text = f"{contents:.1f} in tasks"
        if box is None:
            state = "unbet"
            why = f"{bet}. Its tasks need {contents:.1f} weeks."
        else:
            # Three facts in one clause, in the order somebody reads them: what
            # was bet, over how many people, and what that buys. The last is the
            # only one of the three the comparison is made against, and it is
            # quoted in the words `_rollup_problems` uses for it — "the 4.0 the
            # bet buys" — so the warning in `check` and the sentence on this row
            # name the same number the same way.
            held = f"{bet}, which buys {box:.1f} weeks; its tasks need {contents:.1f}"
            if contents > box:
                state = "over"
                why = f"{held} — over the box."
            elif silent:
                state = "unsized"
                why = (
                    f"{held} — but {len(silent)} of its {len(kids)} have no length yet, "
                    "so that can only grow."
                )
            elif contents == box:
                state = "level"
                why = f"{held} — exactly the box."
            else:
                state = "under"
                why = f"{held} — inside the box."
    return {
        # Two keys for one number, exactly as `progress` and `progress_text`
        # below are: the number is what a column sorts by, the text is what the
        # cell prints. `5.6 in tasks` is the record page's own wording for it,
        # and a test holds the two together.
        #
        # None on both where nothing under this has a length. The column sorts
        # such a row where it sorts an unsized leaf — `shownBy` reads this key
        # and `String(null ?? '')` is the empty string — which is the right
        # company for it, and the alternative was sorting a row by a bet its own
        # cell no longer shows.
        "weeks": contents,
        "text": text,
        "state": state,
        "why": why,
    }


def _row(index: Index, record_id: str) -> dict:
    record = index.plan[record_id]
    span = index.spans.get(record_id)
    size = size_weeks(record)
    counted = index.progress.get(record_id)
    # What this rung does not read is not on its row. The model defaults `status`
    # to `shaping` and `priority` to `medium` for every record, so a product —
    # which has neither — arrived at the table as a shaping, medium-priority
    # record and was drawn with both chips. `unread_fields` is the same list the
    # validator reports from and the editors decline to offer.
    unread = unread_fields(record.kind)
    # Whether this rung is work at all, as against a grouping something is filed
    # under. `unread_fields` answers per FIELD and progress is not a field — it
    # is counted — so the ladder is asked directly for the one thing that decides
    # it. See `progress` below.
    works = RUNG[record.kind].schedules

    def read(name, value):
        return None if name in unread else value

    return {
        "id": record.id,
        "title": record.title,
        "kind": record.kind,
        # Not a column — the tree is drawn by the graph and the project facet —
        # and the row needs it anyway, because a row is now something you can
        # drop another one onto. Without it the page cannot tell a move from a
        # gesture that changes nothing, and cannot offer to take a row out of
        # something it is not in.
        #
        # Only when the plan can resolve it, exactly as `depends_on` below:
        # a hand-written `parent: issue-…` carried the inbox id into every
        # payload this row feeds — /table, /graph, /timeline, /api/table.json —
        # and the move bar drew "Take task-… out of issue-…" over a record no
        # plan page can show. A parent this page cannot resolve (unplanned, or
        # dangling) is nulled here and flagged below, and the flag is a boolean
        # and never the id, because the exclusion sweep forbids an inbox id in
        # these pages' bytes.
        "parent": record.parent if record.parent in index.plan else None,
        # Whether the stored field holds a parent the line above could not
        # carry — `off_plan_deps`' twin, and read the same way: it is what lets
        # the table refuse the move gesture that would overwrite a line it
        # never drew (see `movable`/`moveTip` in the table script).
        "off_plan_parent": bool(record.parent) and record.parent not in index.plan,
        "status": read("status", record.status),
        "owner": read("owner", record.owner),
        "assignees": read("assignees", record.assignees),
        "reviewers": read("reviewers", record.reviewers),
        "review_waived": read("review_waived", record.review_waived),
        "priority": read("priority", record.priority),
        "cycle": read("cycle", record.cycle),
        # The size somebody stated, and None where nobody has. It used to be
        # `None if defaulted else size` — the same value, reached by throwing
        # away an invented half-week the line above had just made up, and the
        # hover card in `shell.py` read `row.weeks ?? row.size` so the timeline's
        # copy of this row showed 0.5 for a bet nobody had sized while the
        # table's showed nothing. One question, one answer, on every page.
        "size": size,
        # How the work under this record reads against the box its bet bought,
        # on every row that has work under it — including the one where nothing
        # underneath has a length yet, which carries the reading and no number.
        # The size column draws THIS instead of the bet on such a row, and
        # refuses to be edited while it does. A cell showing a derived number and
        # opening an editor on the stored one asks a person to type at a value they cannot
        # see, which is the rule the two derived-value columns were closed to
        # editing for in the first place. The bet is still typed on the record's
        # own page, and on the betting table, which is where a pitch's tasks are
        # argued about. See `_rollup`.
        "rollup": _rollup(index, record_id),
        "start": span.start.isoformat() if span else None,
        "end": span.end.isoformat() if span else None,
        # Every date on this page was computed. Saying so in the payload keeps the
        # column able to style itself differently from anything a human typed.
        "derived": span is not None,
        "unowned": bool(span and span.unowned),
        "overruns": span.overruns_cycle_weeks if span else None,
        # What is still in the way, not what was ever in the way — jcanton,
        # 2026-08-20: "make sure the counter gets updated if blocking tasks are
        # marked as done". A record whose one dependency finished last week is
        # not blocked by anything, and a column headed "Blockers" that says 1
        # about it is a column people learn to ignore.
        #
        # `done` and `shelved` both stop counting, for the same reason by two
        # routes: one is finished and the other is parked, and neither is work
        # anybody is waiting on. `depends_on` itself is untouched — the fact that
        # this waited for that is history worth keeping, and it is what the graph
        # draws.
        # Looked up in `records`, never `plan`: `blocked_by` is total over
        # records, so a planned task whose hand-written `depends_on` names an
        # unplanned record keeps that edge — and the plan-only lookup was a
        # KeyError that 500ed /table over one hand-edited file.
        #
        # And `None` — not `0` — on a rung that cannot depend on anything. The
        # count is of `depends_on`, which is one of the fields `unread` already
        # names for a product, so a `0` here was the table drawing a field the
        # rest of this function had just refused to draw: jcanton, 2026-08-25,
        # of the product row, "nor should any of the other cells contain
        # anything (currently I see blockers and progress)". `stored()` in the
        # table's script renders `null` as the empty cell and `0` as a nought,
        # which is the whole of the difference on screen.
        "blocked_by": read(
            "depends_on",
            sum(
                1
                for blocker in index.blocked_by[record_id]
                if index.records[blocker].status not in ("done", "shelved")
            ),
        ),
        # Two keys for one fact: the ratio is what a column sorts by, the text is
        # what it prints. Sorting on "7/12" as a string puts 10/12 before 7/12.
        #
        # Counted only for a rung that is work. `index.progress` rolls a
        # container's children up in weeks, and it does that for a product too —
        # correctly, since 2026-08-20, when a product holding a five-week project
        # reported `0/0.5 wk` against a denominator nobody typed. Correct and
        # still not this row's to draw: a product groups the codebases a plan
        # spans, and "42% done" beside a codebase is a sentence about the plan
        # wearing the name of the thing it is filed under. `Rung.schedules` is
        # the ladder's own word for "the scheduler gives it dates", which is the
        # same question as "is this work"; a seventh rung needs no edit here.
        # The rollup itself is untouched — the deck, the record page and the
        # column's own existence still read `index.progress`.
        "progress": round(counted.fraction, 4) if counted and works else None,
        "progress_text": counted.text if counted and works else "",
        "prs": read("prs", record.prs),
        "tags": record.tags,
        # Who reviews the work filed under this record, when it names nobody
        # itself. A pitch with reviewed tasks under it IS reviewed — the rule in
        # `model.py` says so and stops asking — and this is the same fact drawn
        # rather than enforced. Kept separate from `reviewers` on purpose: that
        # key is what the file holds and what the cell editor starts from, and
        # merging the two would make opening the editor an accidental way to
        # write somebody else's name into this record.
        "reviewers_from": (
            _reviewers_under(index, record_id)
            if not record.reviewers and "reviewers" not in unread
            # A container reads no reviewers, its own or anybody's: a product row
            # was drawing "the people who review the work under this" in a column
            # it has no stake in, which reads as a field it holds.
            else []
        ),
        # Three fields that are not columns and are not drawn anywhere on this
        # page. They are here because the gate names them: a status the table can
        # set demands them, and a row has to be able to answer whether it already
        # holds one. The two dates are on no column at all, and `person_weeks` is
        # answered under its own name because that is the name the gate's message
        # carries — `size` above holds the same number now that there is no
        # default standing in for it, but the field a blocker names and the
        # column a page draws are two vocabularies, and the row answers in both
        # rather than making the script translate between them.
        "start_date": record.start_date.isoformat() if record.start_date else None,
        # And the end, for the same reason and one more: `done` is a status the
        # table can set, the gate demands this field at it, and unlike the two
        # beside it this one is empty on EVERY row somebody is about to mark
        # done. Without it here `missingFor` cannot tell a row that has already
        # been answered from one that has not, so the panel would ask again for
        # a date the file already holds.
        "end_date": record.end_date.isoformat() if record.end_date else None,
        "person_weeks": getattr(record, "person_weeks", None),
        # Not a column, but the control bar offers it: a dropdown whose value the
        # client cannot see is a filter that changes the URL and does nothing.
        "project": _project_of(record, index.plan),
        "product": _product_of(record, index.plan),
        "predicates": predicates_of(index, record_id),
        # What the box searches, built once by `searchable` (`index.py`) and
        # carried rather than rebuilt: the browser used to search
        # `row.title + ' ' + row.tags` while the server searched four fields and
        # every shaping document, so the same query answered differently
        # depending on whether it arrived in a link or through the keyboard.
        # `search` is the key the people rows already use for exactly this,
        # which is why it is spelled that way here.
        "search": index.search_blob[record_id],
    }
