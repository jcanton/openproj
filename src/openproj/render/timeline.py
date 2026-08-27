"""The plan as a Gantt chart."""

from __future__ import annotations

from datetime import date

from ..index import Index
from ..model import RUNG, Config, days_after, size_weeks
from ..schedule import build_end
from .controls import _FILTER_JS, _facets_html, _summary_html
from .env import _compiled, _fragment
from .rows import _row
from .shell import STATIC, Links, _page, _titles
from .tokens import HUMAN, STATUS_GLYPH, STATUSES, _human, _status_class

_DAY_PX = 6
_ROW_PX = 22
_LEFT_PX = 250
_PLOT_PX = 1100
# The widest window the plot will draw over. Past the day-width floor below the
# SVG simply gets wider, so a window reaching the end of the calendar — one
# `done` record dated 9999-12-31, or a `?to=` anybody can type — came out as
# 4.7 million pixels of drawing and 95,686 month ticks, fourteen megabytes that
# is a hung tab rather than a page. Forty years is longer than any plan this
# tool will hold and still twenty screens of scrolling at the default scale;
# bars outside it are dropped the way any bar outside the window is, and the
# page already reports how many it is not showing.
_MAX_PLOT_DAYS = 40 * 366
# The header is two bands, not one. Cycle labels used to be drawn at y=10 and month
# labels at y=18 inside the same 26px strip, so a cycle boundary landing near the
# first of a month wrote one word on top of the other.
_BAND_PX = 18
_HEADER_PX = _BAND_PX + 22
# Room under the last bar, so the today rule's label has somewhere to sit and the
# last row is not flush against the frame. Named because three places have to
# agree on it: the plot's height here, the height the filter script recomputes
# after hiding rows, and the label column beside the plot — which is a separate
# element and would otherwise end 20px short of the bars it names.
_PLOT_FOOT_PX = 20
# A one-day span at the fitted day width is 1.6px of target. Nobody hovers that,
# and nobody clicks it either, so the shortest bar is still a thing you can hit.
_MIN_BAR_PX = 3
# A bar is shorter than its row, so it is centred in it. Drawn at the top of the
# row it sat four pixels above the label naming it, all the way down the chart.
_BAR_PX = 14
_BAR_TOP = (_ROW_PX - _BAR_PX) // 2
# The status glyph sits on a baseline inside the bar, not at its top edge, so the
# server and the filter script both have to place it from the same offset. A 9px
# glyph is about 6.5px of cap height, centred in a 14px bar.
_GLYPH_DY = 10.5
# Narrower than this and the glyph is wider than the bar it names, so it spills
# onto the page — a mark in a status colour sitting on no status colour. A bar
# that short has already lost its fill as a channel too; the tooltip and the label
# beside it are what is left, and both still say the status in words.
_GLYPH_MIN_PX = 11
_LABEL_CHARS = 40
# What the hatching over a bar means, in the words the legend uses for it. The
# hatch is a texture and the outline is a stroke, so neither reaches a reader who
# is not looking at the plot — the row beside it has to say them.
_MARK_WORDS = {"estimated": "appetite assumed", "unowned": "nobody on it"}
# Per level of containment. Enough to read as a step at 11px, small enough that a
# task three deep still has most of the 250px label column to write its name in.
_INDENT_PX = 12


def _clip(text: str) -> str:
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "\u2026"


def _containment_rows(index: Index, drawn: set[str]) -> list[tuple[str, int]]:
    """Ids in reading order — a project, then its pitches, then their tasks — and
    the depth each one sits at.

    Sorted by start date, the rows said nothing the table's start column does not
    say better, and threw away the one thing a Gantt has that a table has not: a
    project's work as a block you can see at once. Siblings still order by date,
    so within a parent the reading is unchanged.

    Depth is counted through the whole containment chain, not only the drawn part
    of it: a parent whose span fell outside the window still holds its children,
    and a task that jumps to the left margin when you narrow the dates reads as a
    task that changed parents.
    """
    kids: dict[str, list[str]] = {i: [] for i in index.plan}
    roots: list[str] = []
    for record_id, record in index.plan.items():
        # `parent not in plan` covers both a root and an orphan pointing at an
        # id that no longer exists. Dropping the orphan would lose a real bar.
        if record.parent in index.plan:
            kids[record.parent].append(record_id)
        else:
            roots.append(record_id)

    when: dict[str, date] = {}

    def earliest(record_id: str, seen: frozenset[str]) -> date:
        """When a subtree starts, so a parent sorts with the work inside it."""
        if record_id in when:
            return when[record_id]
        if record_id in seen:  # a parent cycle in the files, not a tree
            return date.max
        seen = seen | {record_id}
        span = index.spans.get(record_id)
        best = span.start if span and record_id in drawn else date.max
        for kid in kids[record_id]:
            best = min(best, earliest(kid, seen))
        when[record_id] = best
        return best

    def ordered(ids: list[str]) -> list[str]:
        return sorted(ids, key=lambda i: (earliest(i, frozenset()), i))

    rows: list[tuple[str, int]] = []

    def walk(record_id: str, depth: int) -> None:
        if record_id in drawn:
            rows.append((record_id, depth))
        for kid in ordered(kids[record_id]):
            # A rung the scheduler never sees indents nothing. The rule above —
            # depth through the whole chain — is about a parent whose span fell
            # outside the *window*, which is a bar that exists and is not drawn
            # today. A product has no span ever, so counting it would push every
            # project inside one a level right against every project outside one,
            # to mark a row that is never on this page.
            held = index.plan.get(record_id)
            deeper = held is None or RUNG[held.kind].schedules
            walk(kid, depth + (1 if deeper else 0))

    for record_id in ordered(roots):
        walk(record_id, 0)
    # Anything the walk could not reach is in a parent cycle. It still has a span
    # and still belongs on the chart; a row silently missing from a plan is worse
    # than a row drawn at the margin.
    placed = {i for i, _ in rows}
    return rows + [(i, 0) for i in sorted(drawn - placed)]


def _timeline(
    index: Index, window: tuple[date | None, date | None] = (None, None), zoom: float | None = None
) -> dict:
    """Geometry for the hand-rolled SVG Gantt.

    No Gantt library: hatching, cycle rules and per-bar explanations are all custom,
    and the scheduler emits exact spans, so the renderer is the small part.

    Zoom is a day width the server draws at, not a transform the browser applies.
    Scaling the finished SVG horizontally would stretch every month label and every
    rounded corner with it; recomputing costs one render and keeps the text upright.
    A bar reaching past the window is clipped to it rather than dropped — a row that
    disappears when you narrow the dates reads as work that went away.
    """
    total = len(index.plan)
    drawn = {i: s for i, s in index.spans.items() if not s.unscheduled}
    if not drawn:
        # An empty plot and a plot that failed are the same picture, and which one
        # it is decides what to do next. Nothing here is about the filters, so
        # neither copy offers to clear them.
        blank = (
            {
                "headline": "This plan has no records yet.",
                "detail": "Nothing has been pitched, shaped or scheduled.",
            }
            if not total
            else {
                "headline": "Nothing in this plan has dates.",
                "detail": "Every record is done, shelved, or waiting on something "
                "that has not been scheduled.",
            }
        )
        return {
            "bars": [],
            "cycles": [],
            "months": [],
            "today_x": None,
            "header": _HEADER_PX,
            "band": _BAND_PX,
            "width": _LEFT_PX,
            "height": _ROW_PX,
            "origin": None,
            "last": None,
            "zoom": "",
            "rows": {},
            "total": total,
            "offscreen": total,
            "blank": blank,
        }

    starts = [s.start for s in drawn.values()] + [w[0] for w in index.cycles.values()]
    ends = [s.end for s in drawn.values()] + [w[1] for w in index.cycles.values()]
    origin, last = min(*starts, index.today), max(*ends, index.today)
    origin, last = window[0] or origin, window[1] or last
    if last <= origin:  # a backwards window would invert every bar
        # `days_after`, because `from` is a query parameter: `?from=9999-12-31`
        # is a link anybody can send and it walked one day off the calendar,
        # which was a 500 on `/timeline` with nothing committed at all.
        last = days_after(origin, 1)
    last = min(last, days_after(origin, _MAX_PLOT_DAYS))
    drawn = {i: s for i, s in drawn.items() if s.end >= origin and s.start <= last}

    # A corpus can span ten months. At a fixed day width that is 1800px of
    # coordinate space, and an SVG with no viewBox CLIPS rather than scales, so
    # everything past the fold silently vanished. Scale the day instead, floored
    # so a short plan does not turn into a hairline.
    days = max((last - origin).days, 1)
    day_px = zoom if zoom else max(1.6, min(_DAY_PX, _PLOT_PX / days))

    def x(day: date, plus_days: int = 0) -> float:
        # Plot coordinates only. The label column is HTML beside the SVG, not
        # inside it, so that it can stay put while the plot scrolls.
        #
        # `plus_days` rather than handing this `day + timedelta(days=1)`: a bar
        # and a cycle band are both inclusive of their last day, and building
        # that day as a `date` raises OverflowError once a span reaches
        # `date.max` — which it does the moment somebody commits a size larger
        # than the calendar, and the timeline was the one page that still 500'd
        # after the scheduler stopped raising. The offset is a coordinate, so it
        # is added in days instead of by naming a date that cannot exist.
        return round(((day - origin).days + plus_days) * day_px, 1)

    config = Config(default_task_effort=index.default_task_effort)
    bars, rows = [], {}
    for row, (record_id, depth) in enumerate(_containment_rows(index, set(drawn))):
        span = drawn[record_id]
        visible_start, visible_end = max(span.start, origin), min(span.end, last)
        record = index.plan[record_id]
        # Hatched, not outlined: the outline says "overruns its cycle", and one
        # channel carrying three different facts is a channel that says none of
        # them. A guess and a commitment have to be told apart at a glance. The
        # hatch is a second rect over the bar, so the class on the bar stays a
        # statement about the span rather than an instruction about paint.
        marks = [name for name in ("estimated", "unowned") if getattr(span, name)]
        classes = ["bar", *marks]
        if span.overruns_cycle_weeks:
            classes.append("late")
        width = round(
            max(_MIN_BAR_PX, day_px, x(visible_end, 1) - x(visible_start)),
            1,
        )
        explanation = index.explanations.get(record_id)
        why = explanation.text if explanation else "Starts as soon as it can."
        # Everything the drawing says, in words, for the list beside the plot.
        # A fill, a width, a hatch and an outline are four channels a screen
        # reader has none of, and the dates are the record's own rather than the
        # clipped ones: a window narrower than the plan does not move a deadline.
        notes = [_MARK_WORDS[name] for name in marks]
        if span.overruns_cycle_weeks:
            notes.append("overruns its cycle")
        bars.append(
            {
                "id": record_id,
                "label": _clip(record.title),
                "full": f"{record.title} ({record_id})",
                "reads": " ".join(
                    part
                    for part in (
                        f"{record.title} ({record_id}).",
                        f"{_human(record.status)}.",
                        f"{span.start} to {span.end}.",
                        f"{', '.join(notes).capitalize()}." if notes else "",
                        why,
                    )
                    if part
                ),
                "depth": depth,
                "indent": depth * _INDENT_PX,
                "classes": " ".join(classes),
                "marks": marks,
                "x": x(visible_start),
                "y": row * _ROW_PX + _HEADER_PX + _BAR_TOP,
                "width": width,
                "colour": _status_class(record.status),
                # The channel that is not colour. Five fills on a luminance ladder
                # are separable; they are not nameable, and nothing on a bar says
                # the word. Empty on a bar too narrow to hold the mark inside it.
                "glyph": STATUS_GLYPH.get(record.status, "") if width >= _GLYPH_MIN_PX else "",
            }
        )
        size, _ = size_weeks(record, config)
        # The table's own row, so the shared `matches()` reads the same fields on
        # this page as on the other two, plus the two things only a bar wants to
        # say: what it is holding, and why it starts when it does.
        rows[record_id] = _row(index, record_id) | {"weeks": round(size, 2), "tip": why}
    cycles = []
    config = Config(cooldown_weeks=index.cooldown_weeks, plans=index.plans)
    for number, (opens, closes) in sorted(index.cycles.items()):
        if closes < origin or opens > last:
            continue
        left = x(max(opens, origin))
        # Where building stops. This is the date an overrun is measured against
        # (`schedule._overrun`), and the chart used to draw its only rule at the
        # end of the *window* — two weeks of cool-down further right. A bar could
        # finish visibly before the line and still be flagged amber, which is the
        # kind of contradiction that ends a timeline's credit with a room.
        builds_until = build_end(number, (opens, closes), config)
        cycles.append(
            {
                "number": number,
                "label": f"cycle {number}",
                "x": left,
                "width": round(max(1.0, x(min(closes, last), 1) - left), 1),
                "build_x": x(builds_until) if origin <= builds_until <= last else None,
                # The dashed rule only where the cycle really closes. Drawn at a
                # clamped edge it would claim a cycle ends where the window does.
                "rule_x": x(closes) if origin <= closes <= last else None,
                # The cool-down runs from the build rule to the closing rule, and
                # is shaded: work is not meant to land there, and an unmarked
                # fortnight at the end of every cycle reads as more building time.
                "cool_x": x(builds_until) if builds_until < closes else None,
                "cool_width": round(max(0.0, x(min(closes, last), 1) - x(builds_until)), 1),
            }
        )
    return {
        "bars": bars,
        "rows": rows,
        "cycles": cycles,
        "months": _month_ticks(origin, last, x),
        # A window that excludes today has no today line. Drawing it at a clamped
        # coordinate would put "now" on an edge it is not on.
        "today_x": x(index.today) if origin <= index.today <= last else None,
        "origin": origin.isoformat(),
        "last": last.isoformat(),
        "zoom": zoom or "",
        "header": _HEADER_PX,
        "band": _BAND_PX,
        "width": x(last) + 24,
        "height": len(bars) * _ROW_PX + _HEADER_PX + _PLOT_FOOT_PX,
        "total": total,
        "offscreen": total - len(bars),
        # Which emptiness this page can arrive at. With bars on it the only way to
        # empty it is the control bar, and that is the one emptiness a button can
        # undo; with none, the dates are what is wrong and clearing a filter would
        # not bring a single one back.
        "blank": {
            "headline": "No record matches these filters.",
            "detail": "Every bar is filtered out by the controls above.",
        }
        if bars
        else {
            "headline": "Nothing is scheduled in this window.",
            "detail": "Every dated record in this plan falls outside it.",
        },
    }


def _month_ticks(origin: date, last: date, x) -> list[dict]:
    """A bar chart with no dates on it is a picture, not a plan.

    The year only where it changes: "Aug 2026" on every tick spends a third of a
    narrow month restating what the tick before it already said.

    December 9999 has no month after it, and building one raised ValueError —
    twelve lines after the `x()` helper that was fixed for this exact failure.
    `start_date: 9999-12-31` on a done record, typed into the detail page,
    committed and then answered 500 on `/timeline` for good, with `openproj
    check` reporting nothing wrong and `openproj render` writing no files at
    all, so neither tool you would reach for could tell you why. The walk stops
    at the last month the calendar has instead; the loop would end there anyway,
    since the month after it is past `last` by construction.
    """
    ticks, cursor = [], date(origin.year, origin.month, 1)
    while cursor <= last:
        if cursor >= origin:
            year = not ticks or cursor.month == 1
            ticks.append({"x": x(cursor), "label": cursor.strftime("%b %Y" if year else "%b")})
        if (cursor.year, cursor.month) == (date.max.year, date.max.month):
            break
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return ticks


# What this chart is showing and how to move through it — at the far end of the
# search box's line, the same slot the graph's pan/zoom sentence sits in. It was a
# row of its own between the window controls and the key, and the timeline stacked
# eight rows before the first bar. What it says is not a control of the view, it
# is a description of it, and a description does not earn a row.
_TIMELINE_HINT = """<p class="hint">{% if windowed %}Showing {{ t.origin }} to {{ t.last }},
  a window of the plan — Reset goes back to all of it.{% endif %}
  Drag sideways or scroll to move through it. Bars reaching past the window are
  clipped to it, never dropped.</p>"""

_TIMELINE = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Timeline</h1>
{{ facets }}
{#- **The window controls fold too, and that is the third fold on this page.**
    From, to, zoom, Apply and Reset are 98px at a 390px viewport, above a chart
    that had 310 left after the filter bar and the key were folded. Three handles
    at 31px each is 93px of furniture where there were 392, and the drawing goes
    from a sixth of the window to more than half of it.

    Three and not one, because they are three different questions and folding
    them together would mean opening the key to change the zoom. `Window` names
    what it holds the way `Filters` and `Key` do — what these controls set is
    which slice of the calendar is on screen, which is the word the aside beside
    the search box already uses. -#}
<details class="windowfold" open>
<summary>Window</summary>
<form class="tl-controls" method="get" action="{{ links.timeline }}">
  {#- Prefilled with the window on screen, not the one that was asked for. Two
      empty boxes under a sentence reading "Showing 2026-02-02 to 2026-11-27" ask
      the reader to believe the page over the controls; Reset is what says the
      window is the default one. -#}
  {#- Each label is beside its control rather than wrapped around it, because the
      row is laid out as a grid and the caption, the box and the ISO echo under
      the box are three rows of it. A wrapping `<label>` is one grid item and
      cannot put its own contents in three. `for`/`id` says the same thing to the
      accessibility tree that wrapping said. -#}
  <label class="facet" for="tl-from">from</label>
  <input type="date" id="tl-from" name="from" value="{{ t.origin or '' }}">
  <label class="facet" for="tl-to">to</label>
  <input type="date" id="tl-to" name="to" value="{{ t.last or '' }}">
  <label class="facet" for="tl-zoom">zoom</label>
  <select id="tl-zoom" name="zoom">
    <option value="">fit to window</option>
    {% for px, label in zooms %}
    <option value="{{ px }}"{{ ' selected' if chosen == px else '' }}>{{ label }}</option>
    {% endfor %}
  </select>
  <span class="acts"><button type="submit" class="button primary">Apply</button>
    <a class="button reset" href="{{ links.timeline }}">Reset</a></span>
</form>
</details>
{#- **One row, both keys.** Statuses lead on the left and the marks hang off the
    right end — jcanton, 2026-08-25: "the timeline can then have its legend on one
    line only: left-aligned for status and right aligned the others". They are two
    questions, which is why they stay two labelled lists: what state is this in,
    and how much of this bar is a guess. Every swatch is drawn from the same token
    or the same pattern the plot uses — including the glyph, which is the half of
    the status channel that is not colour.

    `.keyrow` is the shell's and already meant "first item left, last item
    right"; the count it used to push right is in the control bar now with the
    other two views' (`_summary_html`), so what it pushes right is the second key.

    `bar`, and inset by half a pixel: two of these keys are bars, so they carry
    the stroke every bar carries — and an SVG stroke is centred on the edge, so a
    rect filling its own viewBox would have had half of its border clipped
    away. -#}
{#- **The key folds on a phone, the same way the filters do.** Eleven markings
    wrap to four rows at a 390px viewport — 106px above a chart that has 310 —
    and a legend is a thing you consult once and then stop reading, which is the
    opposite of the plot it explains. `<details open>` for the same reason the
    filter bar is one: the fold is taken away by the script and only below 40rem,
    so a reader without JavaScript keeps the key it has always had.

    The summary says `Key` and carries no count, and that is the difference from
    the filter bar's: a folded filter is state the page is in and has to confess
    to, a folded key is a reference that says the same thing whenever it is
    opened. -#}
<details class="keyfold" open>
<summary>Key</summary>
<div class="keyrow">
<ul class="legend" aria-label="What a bar's colour and mark mean">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
<ul class="legend" aria-label="What a bar marking means">
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="bar st-ready" x=".5" y=".5" width="19" height="10"/><rect
        class="mark mark-estimated st-ready" x=".5" y=".5" width="19"
        height="10"/></svg>appetite assumed</li>
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="bar st-ready" x=".5" y=".5" width="19" height="10"/><rect
        class="mark mark-unowned st-ready" x=".5" y=".5" width="19"
        height="10"/></svg>nobody on it</li>
  <li><span class="swatch outline late"></span>overruns its cycle</li>
  <li><span class="swatch rule today"></span>today</li>
  <li><span class="swatch rule boundary"></span>a cycle closes</li>
  <li><span class="swatch band"></span>a cycle, build and cooldown</li>
</ul>
</div>
</details>
{#- `data-fills`: the box the shell measures the window into, capped rather than
    filled — a plan with three bars is three bars tall. -#}
<div class="tl" data-fills{% if not t.bars %} hidden{% endif %}>
{#- The column beside the plot is the plot's accessible half, not a caption for
    it: `role="img"` on the SVG prunes everything inside it, which is right —
    seventeen bar links announced twice is worse than none — but only once what
    it prunes exists somewhere else. So every row carries what its bar draws:
    the status the fill means, the dates the width means, the marks the hatching
    means, and the sentence the tooltip holds. -#}
<div class="labels" role="list"
     aria-label="Every bar on the chart, with its status and its dates">
  <div class="spacer" aria-hidden="true" style="height: {{ t.header }}px"></div>
  {#- Indented by containment, so a project's work reads as a block. The clipped
      label is what fits in 250px; the whole title is on the anchor. -#}
  {% for bar in t.bars %}
  <div class="row" role="listitem" data-id="{{ bar.id }}" data-depth="{{ bar.depth }}"
       style="padding-left: {{ 8 + bar.indent }}px">
    <a href="{{ links.record }}{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a
    ><span class="sr-only">{{ bar.reads }}</span></div>
  {% endfor %}
</div>
<div class="scroll">
<svg width="{{ t.width }}" height="{{ t.height }}"
     viewBox="0 0 {{ t.width }} {{ t.height }}" role="img"
     aria-label="Every scheduled record as a bar. The same rows are listed beside it.">
  {#- One pair of patterns per status, not one pair in all. A pattern resolves
      its own custom properties against the tree it is declared in, never against
      the shape that references it, so a single --hatch could only ever be right
      for one rung of the ladder — white lines over a near-white "done" bar, or
      near-black ones over a dark "shelved" one. The stroke is the fill's own ink,
      which is the token that already means "what reads on this". -#}
  <defs>
    {% for status in statuses %}
    <pattern id="hatch-estimated-st-{{ status }}" width="6" height="6"
             patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--st-{{ status }}-ink)"
            stroke-opacity=".55" stroke-width="3"/>
    </pattern>
    <pattern id="hatch-unowned-st-{{ status }}" width="8" height="8"
             patternTransform="rotate(-45)" patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="0" y2="8" stroke="var(--st-{{ status }}-ink)"
            stroke-opacity=".7" stroke-width="4"/>
    </pattern>
    {% endfor %}
  </defs>
  {#- A band of its own above the months. A cycle label used to be drawn at y=10
      and a month label at y=18 inside one 26px strip, so a cycle closing near the
      first of a month wrote one word over the other. -#}
  {% for cycle in t.cycles %}
  <rect class="cycle-band" x="{{ cycle.x }}" y="0"
        width="{{ cycle.width }}" height="{{ t.band }}"/>
  {#- The cool-down, shaded inside the band. Nothing is supposed to be built in
      it, so the band cannot show one flat stretch for the whole window. -#}
  {% if cycle.cool_x is not none %}
  <rect class="cycle-cooldown" x="{{ cycle.cool_x }}" y="0"
        width="{{ cycle.cool_width }}" height="{{ t.band }}"/>
  {% endif %}
  <text class="cycle-label" x="{{ cycle.x + 4 }}" y="12">{{ cycle.label }}</text>
  {#- The solid rule is the end of BUILD, because that is the date an overrun is
      measured against. The dashed one is the end of the window. -#}
  {% if cycle.build_x is not none %}
  <line class="build-rule" x1="{{ cycle.build_x }}" y1="0" x2="{{ cycle.build_x }}"
        y2="{{ t.height }}"><title>cycle {{ cycle.number }} stops building here</title></line>
  {% endif %}
  {% if cycle.rule_x is not none %}
  <line class="cycle-rule" x1="{{ cycle.rule_x }}" y1="0" x2="{{ cycle.rule_x }}"
        y2="{{ t.height }}"/>
  {% endif %}
  {% endfor %}
  <line class="band-rule" x1="0" y1="{{ t.band }}" x2="{{ t.width }}" y2="{{ t.band }}"/>
  {% for month in t.months %}
  <line class="month-rule" x1="{{ month.x }}" y1="{{ t.band }}" x2="{{ month.x }}"
        y2="{{ t.height }}"/>
  <text class="month-label" x="{{ month.x + 3 }}" y="{{ t.header - 8 }}">{{ month.label }}</text>
  {% endfor %}
  {#- Drawn over the grid and under today. A bar is the subject of the page; the
      rules behind it are furniture, and the one line that must never be hidden
      by a bar is the one saying where now is. -#}
  {#- The glyph is the bar's second channel, drawn in the fill's own ink at the
      left edge. It is dropped on a bar too narrow to hold it rather than left to
      spill onto the page, where it would be a mark in a status colour sitting on
      no status colour at all. -#}
  {#- tabindex="-1" because the anchor is inside a `role="img"` subtree: Chrome
      does not focus an SVG anchor and Firefox does, so without it the keyboard
      stopped on seventeen links that the accessibility tree had already pruned
      and announced nothing at each one. The mouse keeps the href. -#}
  {% for bar in t.bars %}
  <a href="{{ links.record }}{{ bar.id }}" tabindex="-1" aria-label="{{ bar.full }}"
     ><rect data-id="{{ bar.id }}" class="{{ bar.classes }} {{ bar.colour }}"
        x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="{{ bar_px }}"
        ><title>{{ t.rows[bar.id].tip }} — click to open</title></rect>{% for mark in
        bar.marks %}<rect class="mark mark-{{ mark }} {{ bar.colour }}" x="{{ bar.x }}"
        y="{{ bar.y }}" width="{{ bar.width }}" height="{{ bar_px }}"/>{% endfor %}{% if
        bar.glyph %}<text class="bar-glyph {{ bar.colour }}" aria-hidden="true"
        x="{{ bar.x + 3 }}" y="{{ bar.y + glyph_dy }}">{{ bar.glyph }}</text>{% endif %}</a>
  {% endfor %}
  {% if t.today_x is not none %}
  <line class="today" x1="{{ t.today_x }}" y1="0" x2="{{ t.today_x }}" y2="{{ t.height }}"/>
  {#- In the gutter under the last row: the two bands above are full of cycle and
      month labels, and there is exactly one today line to name. -#}
  <text class="today-label" x="{{ t.today_x + 4 }}" y="{{ t.height - 6 }}">today</text>
  {% endif %}
</svg>
</div>
</div>
<div id="nothing"{% if t.bars %} hidden{% endif %}>
  <p class="headline">{{ t.blank.headline }}</p>
  <p class="hint">{{ t.blank.detail }}</p>
  <button type="button" id="clear-filters"{% if not t.bars %} hidden{% endif %}>Clear
    filters</button>
</div>
<script id="bars" type="application/json">{{ bars|tojson }}</script>
{{ filters }}
<script>
const scroller = document.querySelector('.scroll');
const svg = scroller.querySelector('svg');
const plot = document.querySelector('.tl');
const nothing = document.getElementById('nothing');
const ROW_PX = {{ row_px }}, HEADER = {{ t.header }}, WIDTH = {{ t.width }};
const FOOT = {{ foot_px }};
const BAR_TOP = {{ bar_top }}, GLYPH_DY = {{ glyph_dy }};
const RECTS = [...svg.querySelectorAll('rect[data-id]')];
const LABELS = new Map([...document.querySelectorAll('.labels .row')]
  .map(row => [row.dataset.id, row]));
// The bars are drawn by the server, so a payload that will not parse costs the
// filters and not the chart. Everything below asks whether it is there.
let DATA = null;
try { DATA = JSON.parse(document.getElementById('bars').textContent); } catch (e) { DATA = null; }

// Open on today rather than on the oldest finished work. The plan is scrollable
// so history stays reachable, but "now" is what the page is for.
{% if t.today_x is not none %}
scroller.scrollLeft = Math.max(0, {{ t.today_x }} - 320);
{% endif %}

// The window is re-rendered by the server, so zoom keeps its labels upright and
// its corners round. Changing a control just submits; the button stays for
// anybody without JavaScript, and the URL stays shareable either way.
const form = document.querySelector('.tl-controls');
form.addEventListener('submit', event => {
  // The window belongs to the server and the facets to the page, and both live
  // in one query string. A plain submit carries only this form's own fields, so
  // applying a date range used to clear every dropdown above it.
  event.preventDefault();
  for (const control of form.elements) {
    if (!control.name) continue;
    if (control.value) params.set(control.name, control.value);
    else params.delete(control.name);
  }
  location.search = params.toString();
});
form.querySelectorAll('input, select').forEach(control => {
  control.onchange = () => form.requestSubmit();
});
form.querySelector('.reset').onclick = event => {
  // The window, not the filters: a button that undoes two things while naming
  // one is a button nobody presses twice.
  event.preventDefault();
  for (const field of ['from', 'to', 'zoom']) params.delete(field);
  location.search = params.toString();
};

// Drag to pan, which is what everybody tries first on a Gantt.
let panning = null;
scroller.onpointerdown = event => {
  if (event.target.closest('a')) return;      // still let a bar be clicked
  panning = {x: event.clientX, left: scroller.scrollLeft};
  scroller.setPointerCapture(event.pointerId);
  scroller.style.cursor = 'grabbing';
};
scroller.onpointermove = event => {
  if (panning) scroller.scrollLeft = panning.left - (event.clientX - panning.x);
};
scroller.onpointerup = () => { panning = null; scroller.style.cursor = ''; };

const human = value => (DATA && DATA.human[value]) || value;

// A bar carried its dates, its owner and its appetite nowhere: the only thing
// hoverable was a native tooltip holding one sentence about why it starts when
// it does. That sentence is still here, at the bottom of the card, where it reads
// as the answer to a question the rest of the box has just raised — `row.tip`,
// which the shared card draws for whoever puts one on a row.
//
// `showCard` is the shell's, and this is the view it was written for. The graph
// and the table draw the same one now; see the card block in `_SHELL`.
function showTip(id, x, y, now) {
  const row = DATA && DATA.rows[id];
  // `now` for the keyboard: focus is a deliberate act and a delay after one is a
  // page ignoring you. A pointer crossing the plot is not deliberate, so it
  // waits like everywhere else.
  if (row) (now ? showCard : queueCard)(row, x, y);
}

svg.addEventListener('pointerover', event => {
  const rect = event.target.closest('rect[data-id]');
  if (rect) showTip(rect.dataset.id, event.clientX, event.clientY);
});
svg.addEventListener('pointerout', event => {
  if (event.target.closest('rect[data-id]')) hideCard();
});
// The keyboard reaches a row through the label beside it: an SVG anchor is not
// focusable in Chrome, and giving every bar a tabindex would put two stops on
// one row for the sake of the second one. So the label opens the same box.
for (const [id, row] of LABELS) {
  const link = row.querySelector('a');
  link.addEventListener('focus', () => {
    const box = link.getBoundingClientRect();
    showTip(id, box.right, box.bottom, true);
  });
  link.addEventListener('blur', hideCardNow);
}
// The native tooltip holds the same sentence, arrives a second later and lands
// somewhere else. The markup keeps it so a page without script still explains
// itself; the anchor carries the accessible name either way.
if (DATA) for (const title of svg.querySelectorAll('title')) title.remove();

// One filter model, three views: the timeline's answer to it is which rows
// are on the chart. A hidden row leaves no gap: the rows below it move up, the
// drawing shrinks to what is left, and the rules that span the whole plot are
// cut to the new height.
const FULL_HEIGHT = svg.querySelectorAll('.cycle-rule, .build-rule, .month-rule, .today');
const TODAY_LABEL = svg.querySelector('.today-label');

function applyFilter() {
  if (!DATA) return;
  let row = 0;
  for (const rect of RECTS) {
    const on = matches(DATA.rows[rect.dataset.id]);
    rect.parentNode.style.display = on ? '' : 'none';
    LABELS.get(rect.dataset.id).hidden = !on;
    if (!on) continue;
    // The bar, whatever is hatched over it and the glyph naming its status are
    // one row and move together. The glyph is a <text>, so it sits on a baseline
    // rather than at the rect's top edge — moved by the same amount, from the
    // same offset the server drew it at.
    const y = row * ROW_PX + HEADER + BAR_TOP;
    for (const shape of rect.parentNode.querySelectorAll('rect'))
      shape.setAttribute('y', y);
    const glyph = rect.parentNode.querySelector('text.bar-glyph');
    if (glyph) glyph.setAttribute('y', y + GLYPH_DY);
    row++;
  }
  const height = row * ROW_PX + HEADER + FOOT;
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${WIDTH} ${height}`);
  for (const line of FULL_HEIGHT) line.setAttribute('y2', height);
  if (TODAY_LABEL) TODAY_LABEL.setAttribute('y', height - 6);
  document.getElementById('shown').textContent = row;
  // A chart with no bars in it is a grid, which reads as an app that failed
  // rather than as a filter that matched nothing.
  plot.hidden = row === 0;
  nothing.hidden = row > 0;
}

addEventListener('openproj:filter', applyFilter);
document.getElementById('clear-filters').onclick = clearFilters;
applyFilter();
</script>
"""

_TIMELINE_STYLE = """
/* FROM, TO, ZOOM, Apply and Reset are one line, and the ISO echo stays under the
   date box it belongs to. A flex row could not do both: the echo makes the two
   date labels a line taller than the zoom label, so `align-items: end` dropped
   ZOOM and both buttons a full line below the boxes and the bar read as two
   rows. Three explicit grid rows — caption, control, echo — say it directly:
   every caption on the first, every control on the second, an echo on the third
   under the box it came from, with the zoom column and the buttons leaving the
   third row empty. `grid-auto-flow: column` fills a column top to bottom before
   starting the next, so the echo the shell inserts after each date input lands
   in that input's own column and nothing here has to know it exists. */
.tl-controls { display: grid; grid-auto-flow: column; grid-auto-columns: max-content;
               align-items: end; column-gap: 1rem; row-gap: .15rem;
               margin: .75rem 0 .25rem; }
.tl-controls > .facet { grid-row: 1; }
.tl-controls > input, .tl-controls > select, .tl-controls > .acts { grid-row: 2; }
/* The `.iso` echo this row reserved a third grid line for is gone — see the
   note in `shell.py`. The row keeps three lines: the third is now simply
   empty, which costs nothing and is one rule fewer than re-deriving the
   grid for a control that may grow an echo again. */
.tl-controls .acts { display: flex; gap: .5rem; align-items: baseline; }
.tl-controls input, .tl-controls select {
  display: block; font: inherit; font-size: 13px; text-transform: none; letter-spacing: 0;
  color: inherit;
}
/* Narrower than the row itself, and one line is no longer on offer. The grid goes
   rather than overflowing the page, and the same controls wrap as a flex row —
   the echo beside its box instead of under it, which is the one thing that has
   to give. */
@media (max-width: 620px) {
  .tl-controls { display: flex; flex-wrap: wrap; align-items: baseline; gap: .35rem .75rem; }
}
/* **A caption can end up on the row above the box it names here, and that is
   left alone deliberately.** Measured as it shipped, at 430, 480 and 560: `zoom`
   is the last thing on one line and the select it names is the first thing on
   the next. It looks like a defect and it was nearly fixed as one.

   Two things stopped that. The row reads as a SENTENCE — "from [date] to [date]
   zoom [fit to window]" — and a sentence is allowed to wrap; the caption is not
   orphaned so much as carried over. And the fix is expensive in the one currency
   this page has least of. `flex: 1 1 auto` does not work: flex-wrap is decided
   from the basis, before any growing, so the caption still fits on the line it
   was going to fit on and only the box before it gets wider — measured. What
   does work is `flex-basis: 100%` on the controls, which puts every box on a
   line of its own and takes the row from three lines to seven, above a chart
   that has 220px of window left. That is the trade, written down so the next
   person meets the measurement rather than the idea. */
/* `.button` and `.button.primary` are the shell's. They were written here, in a
   rule scoped to this filter bar, and the table's create action wore the class
   with nothing behind it. */
/* The three markings, drawn the way the plot draws them: a hatch over a real
   status fill, an outline, a rule. A legend that redraws a mark in its own way
   is a legend that can be wrong about the picture beside it — which is how the
   band key came to be a bordered --surface-2 swatch standing in for an unbordered
   --surface-2 band, two wrong answers agreeing with each other. */
.legend .swatch.outline { background: var(--surface-2); }
/* 2.5px, the width the plot draws it at. It was 1.5 while an overrunning bar was
   the only bar with a stroke on it; every bar has one now, and a key drawn at
   the old width would be keying the ordinary border rather than the alarm. */
.legend .swatch.late { border: 2.5px solid var(--danger); }
.legend .swatch.rule { width: 2px; height: 13px; border-radius: 0; }
.legend .swatch.today { background: var(--danger); }
.legend .swatch.boundary { background: none; border-left: 2px dashed var(--line-strong); }
.legend .swatch.band { background: var(--band); }
/* Capped at the room the window has left, and scrolling inside that cap. The same
   measurement the table's rows and the graph's canvas take, for the same reason:
   a plan of two hundred bars used to push the filters, the window controls and
   both keys off the top of the window, so the only way to change what you were
   looking at was to scroll back up past the chart to the controls that change it.
   `max-height` like the table and not `height` like the graph — the plot has a
   height of its own, one row per bar, and stretching seventeen bars over a
   thousand pixels of white is an answer to a question nobody asked. No floor
   either: an empty plan draws `#nothing` outside this box, so there is nothing
   here for a floor to leave room for.
   The scroll is on `.tl` and not on the plot inside it, or the labels would hold
   still while the bars they name scrolled away.
   `flex-start`, and this is the part that is not cosmetic: under `stretch` both
   columns take the *clamped* height of this box and their contents spill out of
   it — visibly clipped, and still counted, so the page grew a scrollbar for rows
   that were already scrollable here. At `flex-start` each column is as tall as
   its own content, the cap has something taller than itself to scroll, and the
   two move together. */
.tl { display: flex; border: 1px solid var(--line); align-items: flex-start;
      max-height: var(--room); overflow: auto; }
.tl[hidden] { display: none; }
/* The plot leaves `_PLOT_FOOT_PX` under the last bar; the label column is a
   separate element and has to leave the same, or its dividing rule stops short of
   the bars it is dividing. Rendered from the constant rather than typed, because
   a fourth copy of that number is a rule that ends 20px early on a chart nobody
   is measuring. */
.labels { flex: 0 0 250px; border-right: 1px solid var(--line);
          padding-bottom: {{ foot_px }}px; }
.labels .row {
  /* Positioned, so that the `.sr-only` sentence inside it is positioned against
     the row. `.sr-only` is `position: absolute`, and with no positioned ancestor
     its containing block is the page itself — which means the plot's scroll
     container does not clip it, seventeen of them landed wherever the rows would
     have been if nothing had been capped, and the page grew a scrollbar for
     content that was already scrollable inside the chart. Nothing moves visually:
     the span is clipped to nothing either way. */
  position: relative;
  /* Fixed, not min: the row carries a clipped title and a clipped-off sentence
     of what the bar draws, and the second one must not add a pixel of height —
     every row here lines up with the bar the scheduler placed beside it. Written
     from `_ROW_PX`, which is the number the plot is laid out with: as a literal
     it was a third copy, and one that would only ever be found by noticing that
     the labels had drifted a row out of step halfway down a long plan. */
  height: {{ row_px }}px; line-height: {{ row_px }}px; font-size: 11px;
  color: var(--muted);
  padding: 0 .5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scroll { overflow-x: auto; flex: 1 1 auto; min-width: 0; }
/* **A share of the box, not 250 pixels of it.** `.labels` is `flex: 0 0 250px`
   above and `.scroll` is whatever is left, which is a fine bargain on a laptop
   and an absurd one on a phone: measured at a 390px viewport, the label column
   took 261px and the chart it labels got 87. A Gantt drawn 87px wide is not a
   chart that needs scrolling sideways, it is a chart with no room to show a
   single bar in.

   **Below the rule it overrides, and that is the whole of a defect this already
   had.** Written into the `@media (max-width: 620px)` block further up — the one
   the controls wrap in — it is `.labels` against `.labels`, (0,1,0) both ways,
   and the base rule is 40 lines LATER in the same sheet. It took the tie on
   order and the column stayed 261px wide with the query applying and doing
   nothing. A media query buys no specificity; only its position does.

   Only the basis is overridden. `flex-shrink` stays 0, which is what keeps this
   exact: the labels take 40% of `.tl`, `.scroll`'s `min-width: 0` lets it have
   the rest, and the split is stated once with no second rule that has to agree
   with it. 40% of a 390px viewport is 139px of labels against 209px of chart —
   still the narrower half, because a bar you cannot see is worse than a title
   you have to guess the end of, and the row already ellipsises.

   A percentage and not a smaller constant, so the two halves stay in proportion
   across every width below the query rather than meeting correctly at one.

   **`min-width: 0` IS load-bearing here**, which is the opposite of what it was
   where `.marks` wraps and the note there says so explicitly — so this is worth
   being exact about rather than copying either way. A flex item's automatic
   minimum size is its MIN-CONTENT size, and `.labels`'s children are
   `white-space: nowrap`: `overflow: hidden` and `text-overflow: ellipsis` clip
   what is drawn and change nothing about what the box asks for, so min-content
   is the full width of the longest title. Measured with the basis set and this
   line missing: `flex-basis` resolved to `40%` and the column was still
   261.4px — the minimum winning outright, the query applying, and the chart
   still 86.6px. `.marks` is the case where the container wraps and its
   min-content is one 40px button; this is the case where it does not. */
@media (max-width: 620px) {
  .labels { flex-basis: 40%; min-width: 0; }
}
svg { display: block; }
.month-rule { stroke: var(--line); }
.month-label { font-size: 9px; fill: var(--muted); }
/* The band a cycle runs for, start of build to end of cooldown. It carries its
   own number, so the ground only has to say "there is a cycle here"; the dashed
   rule inside it is where one closes. --band and not --surface-2: a panel tint
   behind a panel is a panel, but behind the page it is 1.07:1 and there is no
   band at all. Same token as the legend key, because they are the same band. */
.cycle-band { fill: var(--band); }
.band-rule { stroke: var(--line); }
/* Where a cycle closes — the one rule on this chart that is a fact about the
   plan rather than grid furniture, so it is drawn in the boundary token and not
   the hairline one. The legend already keyed it as --line-strong while the plot
   drew it in --line, which is a legend describing a line nobody could see. */
.cycle-rule { stroke: var(--line-strong); stroke-dasharray: 3 3; }
/* Solid, because it is the deadline the amber flag is measured against; the
   dashed rule beside it is only where the window closes. */
.build-rule { stroke: var(--line-strong); }
.cycle-cooldown { fill: var(--line); fill-opacity: .5; }
.cycle-label { font-size: 10px; fill: var(--accent); font-weight: 600; }
.today { stroke: var(--danger); stroke-width: 1.5; }
.today-label { font-size: 10px; fill: var(--danger); font-weight: 600; }
rect.bar { rx: 3; }
/* An assumed appetite and work nobody is on are hatched, not outlined: the
   outline says "overruns its cycle", and one channel carrying three facts says
   none of them. Drawn as a second rect over the bar so the status colour stays
   underneath, and transparent to the pointer so the bar is still what you hover. */
rect.mark { rx: 3; pointer-events: none; }
/* `rect.late` used to live here. It is written by _status_paint_css() now,
   after the per-status strokes: both selectors are (0,2,1), so document order
   is the only thing left to decide the tie, and the tie decides whether a bar
   that overruns its cycle still says so. */
/* The bar's second channel: which status this is, said as a shape. Drawn in the
   fill's own ink, and transparent to the pointer so the thing under the cursor
   at the left end of a bar is still the bar.
   The face is the inlined one, not the mono stack: the mono stack is whatever
   the reader's machine happens to have, and this glyph is the channel that has
   to survive when the colour does not. */
text.bar-glyph { font-family: var(--font-sans); font-size: 9px; font-weight: 700;
                 pointer-events: none; }
/* Beside the plot rather than over it: the plot is as tall as its rows, and an
   overlay on an empty one has nothing to cover. */
#nothing { border: 1px solid var(--line); padding: 2.5rem 1rem; text-align: center; }
#nothing .headline { margin: 0 0 .25rem; font-size: 15px; }
#nothing .hint { margin: 0 0 .75rem; }
"""


def _timeline_css() -> str:
    """The timeline's whole stylesheet: the written half and the two derived ones.

    Rendered rather than concatenated because two rules in it are geometry the
    server already decided — the label column's row height has to be `_ROW_PX` or
    the names walk out of step with the bars they name, one pixel per row, and its
    foot has to be `_PLOT_FOOT_PX` or the rule between labels and bars stops short
    of the last of them.
    """
    return (
        _compiled(_TIMELINE_STYLE).render(row_px=_ROW_PX, foot_px=_PLOT_FOOT_PX)
        + _status_paint_css()
    )


def _status_paint_css() -> str:
    """The per-status half of the timeline's stylesheet.

    Twenty-five rules — a fill, a border, a glyph ink and two hatch references
    for each status — so it is written by a loop. Spelled out by hand, the one
    that goes missing is a hatch, and a missing hatch does not look broken: it
    looks like a bar that has stopped being a guess.

    The overrun outline is written here too, at the end, and not with the rest of
    the timeline's rules. It has to beat the per-status stroke below and the two
    selectors weigh the same, so the only thing that decides it is which comes
    last in the sheet.
    """
    rules = [f"rect.st-{s} {{ fill: var(--st-{s}); }}" for s in STATUSES]
    # On the bar, never on the hatch rect stacked over it: the two are the same
    # rectangle, so a stroke on both draws the border twice — and on an
    # overrunning bar the second one would paint the status colour straight down
    # the middle of the danger outline that is the whole point of it.
    rules += [
        f"rect.bar.st-{s} {{ stroke: var(--st-{s}-line); stroke-width: 1; }}" for s in STATUSES
    ]
    # The label on a shape belongs to the fill it sits on, not to the page: on the
    # dark theme's top rungs the fill is nearly white, and --fg on it is nothing.
    rules += [f"text.bar-glyph.st-{s} {{ fill: var(--st-{s}-ink); }}" for s in STATUSES]
    rules += [
        f"rect.mark-{mark}.st-{s} {{ fill: url(#hatch-{mark}-st-{s}); }}"
        for mark in ("estimated", "unowned")
        for s in STATUSES
    ]
    # Overruns its cycle. It was the only stroke on the chart and 1.5px was
    # plenty; now every bar carries one, so this has to be the heavier of the two
    # as well as the redder — 2.5px against 1px on a 14px bar, which reads as a
    # ring round the bar rather than as an edge on it.
    rules.append("rect.bar.late { stroke: var(--danger); stroke-width: 2.5; }")
    return "\n".join(rules) + "\n"


_ZOOMS = (("2", "months"), ("6", "weeks"), ("14", "days"), ("30", "close"))


def render_timeline(
    index: Index,
    links: Links = STATIC,
    window: tuple[date | None, date | None] = (None, None),
    zoom: float | None = None,
) -> str:
    timeline = _timeline(index, window, zoom)
    body = _compiled(_TIMELINE).render(
        t=timeline,
        links=links,
        zooms=_ZOOMS,
        chosen=f"{zoom:g}" if zoom else "",
        # Whether this is a window or the whole plan. The date boxes echo what is
        # on screen either way — they used to echo the request, so the default view
        # showed two empty boxes under a sentence naming the dates it was drawing,
        # and the controls disagreed with the picture. What is lost by filling them
        # in is the answer to "am I looking at everything", and that is a sentence,
        # not two empty boxes.
        windowed=bool(window[0] or window[1]),
        statuses=STATUSES,
        row_px=_ROW_PX,
        bar_px=_BAR_PX,
        bar_top=_BAR_TOP,
        foot_px=_PLOT_FOOT_PX,
        glyph_dy=_GLYPH_DY,
        facets=_facets_html(
            index.facets,
            aside=_fragment(_TIMELINE_HINT, t=timeline, windowed=bool(window[0] or window[1])),
            titles=_titles(index),
            # The bars this window holds, not the plan: a timeline saying
            # "37 of 37" over eleven bars is a number about a different page.
            summary=_summary_html(index, len(timeline["bars"])),
        ),
        filters=_FILTER_JS,
        # The rows the shared `matches()` reads, for the bars that were drawn. Not
        # the whole plan: a bar that is not on this window cannot be filtered onto it.
        bars={"rows": timeline["rows"], "human": HUMAN},
    )
    return _page("openproj — timeline", body, _timeline_css(), links, "timeline", index.unreadable)
