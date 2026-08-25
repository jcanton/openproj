"""One record as the pages see it: the view model the table, graph and timeline share."""

from __future__ import annotations

from ..index import Index, _product_of, _project_of, predicates_of
from ..model import RUNG, Config, size_weeks, unread_fields


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


def _row(index: Index, record_id: str) -> dict:
    record = index.plan[record_id]
    span = index.spans.get(record_id)
    size, defaulted = size_weeks(record, Config(default_task_effort=index.default_task_effort))
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
        "size": None if defaulted else size,
        "start": span.start.isoformat() if span else None,
        "end": span.end.isoformat() if span else None,
        # Every date on this page was computed. Saying so in the payload keeps the
        # column able to style itself differently from anything a human typed.
        "derived": span is not None,
        "estimated": bool(span and span.estimated),
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
        # Two fields that are not columns and are not drawn anywhere on this
        # page. They are here because the gate names them: a status the table can
        # set demands them, and a row has to be able to answer whether it already
        # holds one — `size` is the appetite *or the default*, so it cannot
        # answer for `person_weeks`, and `assigned_on` is on no row at all.
        "assigned_on": record.assigned_on.isoformat() if record.assigned_on else None,
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
