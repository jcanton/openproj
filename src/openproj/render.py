"""The three static pages: a filterable table, a dependency graph, a timeline.

Each page is one self-contained file. Libraries are inlined from `static/` rather
than linked, so a page works on a train and cannot be broken by a CDN. There is no
build step and no npm; the only JavaScript written here is vanilla.

Filter state lives in the query string. That makes every view a shareable URL,
makes the back button work, and deletes the entire saved-views feature request.

Derived values are drawn differently from stated ones throughout. A date the tool
computed, a size it guessed and work nobody owns are all forecasts, and a forecast
that looks like a commitment is how a timeline stops being believed.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment
from markdown_it import MarkdownIt
from markupsafe import Markup
from pydantic import BaseModel

from .index import COMPUTED_PREDICATES, Index, _matches_predicate, _project_of
from .model import Config, Cycle, Entity, Pitch, Project, Task, size_weeks


def _static_dir() -> Path:
    """Where the vendored JS lives, in a checkout or in a container.

    `parents[2]/static` is right for a source tree and wrong for an installed
    wheel, where it resolves past site-packages to a directory that does not
    exist — and `_inline` is a bare read_text, so the first GET /graph became an
    uncaught FileNotFoundError. Found by building a wheel rather than by reading
    the path. OPENPROJ_STATIC exists so a deployment can say where they are
    instead of hoping.
    """
    candidates = [
        Path(os.environ["OPENPROJ_STATIC"]) if "OPENPROJ_STATIC" in os.environ else None,
        Path(__file__).resolve().parents[2] / "static",
        Path(__file__).resolve().parent / "static",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    raise RuntimeError(
        "the vendored static/ directory is missing. It is not part of the wheel, so an "
        "installed layout must be told where it is with OPENPROJ_STATIC."
    )

_DAY_PX = 6
_ROW_PX = 22
_LEFT_PX = 250
_PLOT_PX = 1100
# The header is two bands, not one. Cycle labels used to be drawn at y=10 and month
# labels at y=18 inside the same 26px strip, so a cycle boundary landing near the
# first of a month wrote one word on top of the other.
_BAND_PX = 18
_HEADER_PX = _BAND_PX + 22
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
# A status is a class, not a colour baked into the markup: the same rect has to
# be one colour on a white ground and another on a dark one, and a `fill`
# attribute written at render time cannot change when somebody flips the toggle.
def _status_class(status: str) -> str:
    return f"st-{status}" if status in STATUSES else "st-ready"


def _inline(name: str) -> str:
    return (_static_dir() / name).read_text(encoding="utf-8")


def _json(data: object) -> str:
    """JSON for a `<script>` block, with the characters that can end one escaped.

    Every page ships its data inlined, and `json.dumps` leaves `<` alone — so an
    entity titled `</script>...` closed the block it was sitting in and everything
    after it became live markup on the page. `\\u003c` is ordinary JSON: the parser
    reads back the same string, and the character never reaches the HTML tokeniser.

    U+2028 and U+2029 need no handling here: they are line terminators in
    JavaScript source and legal inside a JSON string, and `json.dumps` escapes
    them already because it escapes everything outside ASCII.
    """
    return (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _inline_font(name: str) -> str:
    """A woff2 as a data: URI. Binary, so not _inline's read_text.

    Linked the ordinary way this would be one more thing a CDN, a proxy or a
    train tunnel can take away, and the static export has to work from file://
    where a relative font URL resolves against whatever directory somebody
    dropped the page in. Base64 costs a third more bytes than the file; the
    whole face is 48 KB, and the pages already inline 650 KB of graph library.
    """
    raw = (_static_dir() / name).read_bytes()
    return "data:font/woff2;base64," + base64.b64encode(raw).decode("ascii")


@lru_cache(maxsize=1)
def _font_uri() -> str:
    """Cached, because every served page carries it and the encode is not free."""
    return _inline_font("inter-latin-wght-normal.woff2")


def _row(index: Index, entity_id: str) -> dict:
    entity = index.entities[entity_id]
    span = index.spans.get(entity_id)
    size, defaulted = size_weeks(entity, Config(default_task_effort=index.default_task_effort))
    return {
        "id": entity.id,
        "title": entity.title,
        "kind": entity.kind,
        "status": entity.status,
        "owner": entity.owner,
        "assignees": entity.assignees,
        "reviewers": entity.reviewers,
        "review_waived": entity.review_waived,
        "priority": entity.priority,
        "cycle": entity.cycle,
        "size": None if defaulted else size,
        "start": span.start.isoformat() if span else None,
        "end": span.end.isoformat() if span else None,
        # Every date on this page was computed. Saying so in the payload keeps the
        # column able to style itself differently from anything a human typed.
        "derived": span is not None,
        "estimated": bool(span and span.estimated),
        "unowned": bool(span and span.unowned),
        "overruns": span.overruns_cycle_weeks if span else None,
        "blocked_by": len(index.blocked_by[entity_id]),
        "prs": entity.prs,
        "tags": entity.tags,
        # Not a column, but the control bar offers it: a dropdown whose value the
        # client cannot see is a filter that changes the URL and does nothing.
        "project": _project_of(entity, index.entities),
        "predicates": [p for p in COMPUTED_PREDICATES if _matches_predicate(index, entity_id, p)],
    }


# Columns the table shows that are computed rather than owned. `size` is the least
# obvious: it shows effort_weeks *or an assumed default*, so a control on it would
# let somebody commit the assumption without meaning to.
_TABLE_DERIVED = ("size", "start", "end", "blocked_by")


def _payload(index: Index) -> dict:
    return {
        "rows": {i: _row(index, i) for i in index.entities},
        "facets": index.facets,
        "predicates": list(index.facets["predicate"]),
        # Flat, exactly as the validator produced them, and grouped by the page.
        # Grouped here as well, the table would have carried two copies of one
        # aggregation — the one rendered into the rows and the one it has to
        # rebuild after every save from /api/index.json, which returns this same
        # flat list. Only the first would ever have been tested.
        "problems": [p.model_dump() for p in index.problems],
        # One list of what a person may change, shared with the detail page. Two
        # lists drift the first time a field is added, and silently.
        "editable": {k: v for k, v in EDITABLE.items() if k not in _TABLE_DERIVED},
        "suggests": SUGGESTS,
        "choices": {"status": list(STATUSES), "priority": list(PRIORITIES)},
        # The word a reader gets, shipped rather than baked into the cells: the
        # rows are drawn by script, and a status the script renders has to reach
        # the same map the server-rendered pages read.
        "human": HUMAN,
        "labels": LABELS,
    }


def _elements(index: Index) -> list[dict]:
    elements: list[dict] = []
    for entity_id, entity in index.entities.items():
        # The same row the table filters on, not a graph-shaped subset of it. The
        # facet bar is one control bar over one `matches()`, and a node carrying
        # only what cytoscape draws is how a dropdown ends up filtering the table
        # and quietly doing nothing here.
        data = _row(index, entity_id) | {
            # The title alone, under the key cytoscape draws. The id is on every
            # other page and in the URL the node opens; on a box 150px wide it
            # cost a line of the only text anybody reads the graph for.
            "label": entity.title,
            # Carried so a new edge is added to what is there rather than replacing
            # it: a PATCH sends the whole field, and depends_on is a list.
            "depends_on": index.blocked_by[entity_id],
        }
        if entity.parent in index.entities:
            data["parent"] = entity.parent
        elements.append({"data": data})
    for entity_id in index.entities:
        for blocker in index.blocked_by[entity_id]:
            elements.append(
                {"data": {"source": blocker, "target": entity_id, "kind": "depends"}}
            )
    return elements


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
    kids: dict[str, list[str]] = {i: [] for i in index.entities}
    roots: list[str] = []
    for entity_id, entity in index.entities.items():
        # `parent not in entities` covers both a root and an orphan pointing at an
        # id that no longer exists. Dropping the orphan would lose a real bar.
        if entity.parent in index.entities:
            kids[entity.parent].append(entity_id)
        else:
            roots.append(entity_id)

    when: dict[str, date] = {}

    def earliest(entity_id: str, seen: frozenset[str]) -> date:
        """When a subtree starts, so a parent sorts with the work inside it."""
        if entity_id in when:
            return when[entity_id]
        if entity_id in seen:               # a parent cycle in the files, not a tree
            return date.max
        seen = seen | {entity_id}
        span = index.spans.get(entity_id)
        best = span.start if span and entity_id in drawn else date.max
        for kid in kids[entity_id]:
            best = min(best, earliest(kid, seen))
        when[entity_id] = best
        return best

    def ordered(ids: list[str]) -> list[str]:
        return sorted(ids, key=lambda i: (earliest(i, frozenset()), i))

    rows: list[tuple[str, int]] = []

    def walk(entity_id: str, depth: int) -> None:
        if entity_id in drawn:
            rows.append((entity_id, depth))
        for kid in ordered(kids[entity_id]):
            walk(kid, depth + 1)

    for entity_id in ordered(roots):
        walk(entity_id, 0)
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
    total = len(index.entities)
    drawn = {i: s for i, s in index.spans.items() if not s.unscheduled}
    if not drawn:
        # An empty plot and a plot that failed are the same picture, and which one
        # it is decides what to do next. Nothing here is about the filters, so
        # neither copy offers to clear them.
        blank = (
            {"headline": "This plan has no entities yet.",
             "detail": "Nothing has been pitched, shaped or scheduled."}
            if not total
            else {"headline": "Nothing in this plan has dates.",
                  "detail": "Every entity is done, shelved, or waiting on something "
                            "that has not been scheduled."}
        )
        return {
            "bars": [], "cycles": [], "months": [], "today_x": None, "header": _HEADER_PX,
            "band": _BAND_PX, "width": _LEFT_PX, "height": _ROW_PX, "origin": None,
            "last": None, "zoom": "", "rows": {}, "total": total, "offscreen": total,
            "blank": blank,
        }

    starts = [s.start for s in drawn.values()] + [w[0] for w in index.cycles.values()]
    ends = [s.end for s in drawn.values()] + [w[1] for w in index.cycles.values()]
    origin, last = min(*starts, index.today), max(*ends, index.today)
    origin, last = window[0] or origin, window[1] or last
    if last <= origin:                      # a backwards window would invert every bar
        last = origin + timedelta(days=1)
    drawn = {i: s for i, s in drawn.items() if s.end >= origin and s.start <= last}

    # A corpus can span ten months. At a fixed day width that is 1800px of
    # coordinate space, and an SVG with no viewBox CLIPS rather than scales, so
    # everything past the fold silently vanished. Scale the day instead, floored
    # so a short plan does not turn into a hairline.
    days = max((last - origin).days, 1)
    day_px = zoom if zoom else max(1.6, min(_DAY_PX, _PLOT_PX / days))

    def x(day: date) -> float:
        # Plot coordinates only. The label column is HTML beside the SVG, not
        # inside it, so that it can stay put while the plot scrolls.
        return round((day - origin).days * day_px, 1)

    config = Config(default_task_effort=index.default_task_effort)
    bars, rows = [], {}
    for row, (entity_id, depth) in enumerate(_containment_rows(index, set(drawn))):
        span = drawn[entity_id]
        visible_start, visible_end = max(span.start, origin), min(span.end, last)
        entity = index.entities[entity_id]
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
            max(_MIN_BAR_PX, day_px, x(visible_end + timedelta(days=1)) - x(visible_start)),
            1,
        )
        explanation = index.explanations.get(entity_id)
        why = explanation.text if explanation else "Starts as soon as it can."
        # Everything the drawing says, in words, for the list beside the plot.
        # A fill, a width, a hatch and an outline are four channels a screen
        # reader has none of, and the dates are the entity's own rather than the
        # clipped ones: a window narrower than the plan does not move a deadline.
        notes = [_MARK_WORDS[name] for name in marks]
        if span.overruns_cycle_weeks:
            notes.append("overruns its cycle")
        bars.append(
            {
                "id": entity_id,
                "label": _clip(entity.title),
                "full": f"{entity.title} ({entity_id})",
                "reads": " ".join(
                    part
                    for part in (
                        f"{entity.title} ({entity_id}).",
                        f"{_human(entity.status)}.",
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
                "colour": _status_class(entity.status),
                # The channel that is not colour. Five fills on a luminance ladder
                # are separable; they are not nameable, and nothing on a bar says
                # the word. Empty on a bar too narrow to hold the mark inside it.
                "glyph": STATUS_GLYPH.get(entity.status, "") if width >= _GLYPH_MIN_PX else "",
            }
        )
        size, _ = size_weeks(entity, config)
        # The table's own row, so the shared `matches()` reads the same fields on
        # this page as on the other two, plus the two things only a bar wants to
        # say: what it is holding, and why it starts when it does.
        rows[entity_id] = _row(index, entity_id) | {"weeks": round(size, 2), "tip": why}
    cycles = []
    for number, (opens, closes) in sorted(index.cycles.items()):
        if closes < origin or opens > last:
            continue
        left = x(max(opens, origin))
        cycles.append(
            {
                "number": number,
                "label": f"cycle {number}",
                "x": left,
                "width": round(max(1.0, x(min(closes, last) + timedelta(days=1)) - left), 1),
                # The dashed rule only where the cycle really closes. Drawn at a
                # clamped edge it would claim a cycle ends where the window does.
                "rule_x": x(closes) if origin <= closes <= last else None,
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
        "height": len(bars) * _ROW_PX + _HEADER_PX + 20,
        "total": total,
        "offscreen": total - len(bars),
        # Which emptiness this page can arrive at. With bars on it the only way to
        # empty it is the control bar, and that is the one emptiness a button can
        # undo; with none, the dates are what is wrong and clearing a filter would
        # not bring a single one back.
        "blank": {
            "headline": "No entity matches these filters.",
            "detail": "Every bar is filtered out by the controls above.",
        } if bars else {
            "headline": "Nothing is scheduled in this window.",
            "detail": "Every dated entity in this plan falls outside it.",
        },
    }


def _month_ticks(origin: date, last: date, x) -> list[dict]:
    """A bar chart with no dates on it is a picture, not a plan.

    The year only where it changes: "Aug 2026" on every tick spends a third of a
    narrow month restating what the tick before it already said.
    """
    ticks, cursor = [], date(origin.year, origin.month, 1)
    while cursor <= last:
        if cursor >= origin:
            year = not ticks or cursor.month == 1
            ticks.append({"x": x(cursor), "label": cursor.strftime("%b %Y" if year else "%b")})
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return ticks


class Links(BaseModel):
    """Where the pages point at each other.

    Static output links to sibling files; the server links to routes. Everything
    else about the pages is identical, so this is the only thing that knows which
    mode it is in.
    """

    table: str = "index.html"
    detail: str = "detail.html"
    graph: str = "graph.html"
    timeline: str = "timeline.html"
    people: str = "people.html"
    entity: str = "detail.html#"  # prefix, then the entity id
    new: str = ""  # only the server can create; a rendered file has nowhere to post
    cycles: str = "cycles.html"
    cycle: str = "cycles.html#"  # prefix, then the cycle number
    asset: str = "assets/"  # a rendered file sits beside the assets it names


STATIC = Links()
ROUTES = Links(
    table="/", detail="/detail", graph="/graph", timeline="/timeline",
    entity="/detail/", new="/new", people="/people",
    cycles="/cycles", cycle="/cycle/", asset="/assets/",
)

_MD = MarkdownIt("commonmark", {"html": False}).enable("table")
_PR = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


def _pr_link(ref: str) -> str:
    """A dead PR reference teaches people the field is decorative."""
    repo, _, number = ref.partition("#")
    return f'<a href="https://github.com/{repo}/pull/{number}">{ref}</a>'


_REMOTE_IMG = re.compile(r'<img\s+src="(https?://[^"]+)"(?:[^>]*?alt="([^"]*)")?[^>]*>')
# Written as a repository-relative path so the markdown reads the same in git, on
# GitHub and in the tool; only the prefix in front of it changes.
_ASSET_IMG = re.compile(r'<img\s+src="assets/([0-9a-f]{16}\.(?:png|jpg|gif|webp))"')


# A leading `# Title` line, with the optional closing hashes ATX headings allow.
_LEADING_HEADING = re.compile(r"\A\s*#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n|\Z)")


def _drop_repeated_title(body: str, title: str) -> str:
    """The shaping document's own first heading, when the page already is it.

    Nearly every doc in the corpus opens by restating its title, because in git
    that heading is the only thing naming the file. On the page it lands directly
    under an `<h1>` saying the same words at the same weight, which reads as a
    rendering fault rather than as a convention. The file keeps its heading — that
    is what git holds and what the editor shows — and only the reading view drops
    it. Whitespace is normalised before comparing so a wrapped or double-spaced
    heading still counts; anything else is somebody's real first section.
    """
    match = _LEADING_HEADING.match(body)
    if not match:
        return body
    same = " ".join(match.group(1).split()).casefold() == " ".join(title.split()).casefold()
    return body[match.end() :].lstrip("\n") if same else body


def _body_html(entity: Entity, links: Links = STATIC) -> str:
    """The shaping document, rendered, with PR references made clickable.

    A remote image would make the page fetch from the network, which is exactly
    what inlining every library was for. Remote images become links instead: the
    reference survives, the dependency does not.

    An image stored in the plan is a different thing — it is in the repository,
    it travels with the clone, and it is served from the same origin as the page.
    Those are drawn.
    """
    return _after_markdown(_MD.render(_drop_repeated_title(entity.body, entity.title)), links)


def _after_markdown(html: str, links: Links) -> str:
    """What every renderer does to markdown once it is HTML.

    One function because the preview has to show what the page will show. Written
    twice, the preview drew an uploaded image against the current URL — so a
    figure that renders fine on `/detail/task-x` was a broken image in the preview
    of that same document, which is the one place somebody checks it.
    """
    html = _REMOTE_IMG.sub(
        lambda m: f'<a href="{m.group(1)}">{m.group(2) or "image"} (external image)</a>', html
    )
    html = _ASSET_IMG.sub(lambda m: f'<img src="{links.asset}{m.group(1)}"', html)
    return _PR.sub(lambda m: _pr_link(m.group(0)), html)


_ENV = Environment(autoescape=True)

_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<script>
// Before the first paint, or the page renders light and then turns dark in front
// of whoever chose dark — which is worse than not having the choice.
try {
  const stored = localStorage.getItem('openproj:theme');
  if (stored) document.documentElement.dataset.theme = stored;
} catch (e) { /* a browser with storage denied still gets the system theme */ }
</script>
<style>
/* Inlined, not linked: a linked face is one more thing a CDN, a proxy or a train
   tunnel can take away, tests/test_render.py asserts no page reaches the network,
   and the static export has to work from file:// where a relative font URL
   resolves against whatever directory somebody dropped the page in. One variable
   file covers 100..900, so this is 48 KB for every weight the app uses. */
@font-face {
  font-family: "Inter var";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("{{ font }}") format("woff2-variations");
}
/* Three states, not two: an explicit choice stamps data-theme, and the default
   is no stamp at all, where only the media query separates one from the other.
   Every colour is a token so that nothing has its only definition inside a
   block that half the readers never match. */
:root {
  /* Named, not `light dark`: that means "follow the system", so a page stamped
     dark against a light system kept rendering its buttons, scrollbars and date
     pickers light — the parts of the page the stylesheet does not draw. */
  color-scheme: light;
  --font-sans: "Inter var", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --bg: #ffffff; --fg: #14211f; --surface: #ffffff; --surface-2: #f5f8f8;
  /* --line-strong is the only boundary of every drawn input, button and popup,
     so it is a UI boundary and owes 3:1. It was #b4c3c7 — 1.81:1 — which drew a
     text field as a rumour. */
  --line: #dce4e5; --line-strong: #879398; --muted: #5a6b70;
  --accent: #0f5c6b; --on-accent: #ffffff;
  --danger: #9a3327; --warn: #8a5308; --ok: #2f7248;
  /* The em dash that means "no value" is *text*, so it owes 4.5:1 and not the
     3.45 it was first given. Whether a field is empty is a fact, not a hint. */
  --empty: #5f7176; --focus: #0f5c6b;
  /* Four tokens per status, not one. Fill and ink draw *shapes* — a graph node,
     a timeline bar. Soft and text draw *chips* — the pill in a table cell, which
     needs a ground light enough to sit inside a row of running text.
     The five fills are a *luminance ladder*, not five hues at one lightness:
     hue is the channel a dichromat loses, and on the graph and the timeline the
     fill used to be the only channel there was. Work gets more solid as it
     advances — parked is the faintest, done the darkest — so the order survives
     every kind of colour vision. Which is why the ink is no longer white
     everywhere: it flips with the rung its fill sits on. */
  --st-shaping: #7e61c2; --st-shaping-ink: #ffffff;
  --st-shaping-soft: #efedf5; --st-shaping-text: #5e3eaa;
  --st-ready: #275e92; --st-ready-ink: #ffffff;
  --st-ready-soft: #ecf1f6; --st-ready-text: #22578a;
  --st-in_progress: #603a04; --st-in_progress-ink: #ffffff;
  --st-in_progress-soft: #f7f2eb; --st-in_progress-text: #734f1b;
  --st-done: #0d311f; --st-done-ink: #ffffff;
  --st-done-soft: #ecf6f1; --st-done-text: #18633d;
  --st-shelved: #8a979f; --st-shelved-ink: #101416;
  --st-shelved-soft: #eff2f3; --st-shelved-text: #495760;
  /* Kind is drawn in ink, never in hue: two colour languages on one row and
     neither one is read. The hairline is the same boundary every input has —
     written as a reference rather than a second copy of the value, because the
     copy is how a boundary token gets fixed in one place and not the other. */
  --kind-ink: var(--muted); --kind-line: var(--line-strong);
  --sev-blocker: #9a3327; --sev-blocker-soft: #f9e9e6;
  --sev-warn: #8a5308; --sev-warn-soft: #f8eedc;
  /* The ground a cycle runs over on the timeline. It was --surface-2, which is
     1.07:1 against the page — a band nobody could see, keyed in the legend by a
     different token again. One token, 1.50:1 against the page in both themes,
     and still light enough to carry an accent-coloured cycle number at 5:1. */
  --band: #c3d6de;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
    --line: #263336; --line-strong: #5c7076; --muted: #93a6aa;
    --accent: #5cb9ca; --on-accent: #0b1214;
    --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
    --empty: #84969c; --focus: #5cb9ca;
    /* The same ladder, climbed the other way: parked is the darkest rung here
       and done the lightest, so a shape is always the *more* solid the further
       the work has got. The ink flips rung by rung with it — one label colour
       for all five was only ever true while all five fills were one lightness. */
    --st-shaping: #9077cb; --st-shaping-ink: #101416;
    --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
    --st-ready: #7aacdc; --st-ready-ink: #101416;
    --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
    --st-in_progress: #f9c275; --st-in_progress-ink: #101416;
    --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
    --st-done: #d7f4e6; --st-done-ink: #101416;
    --st-done-soft: #1d372b; --st-done-text: #5cce97;
    --st-shelved: #5e6a73; --st-shelved-ink: #ffffff;
    --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
    --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
    --sev-warn: #d9a557; --sev-warn-soft: #332409;
    --band: #2a3941;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
  --line: #263336; --line-strong: #5c7076; --muted: #93a6aa;
  --accent: #5cb9ca; --on-accent: #0b1214;
  --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
  --empty: #84969c; --focus: #5cb9ca;
  --st-shaping: #9077cb; --st-shaping-ink: #101416;
  --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
  --st-ready: #7aacdc; --st-ready-ink: #101416;
  --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
  --st-in_progress: #f9c275; --st-in_progress-ink: #101416;
  --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
  --st-done: #d7f4e6; --st-done-ink: #101416;
  --st-done-soft: #1d372b; --st-done-text: #5cce97;
  --st-shelved: #5e6a73; --st-shelved-ink: #ffffff;
  --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
  --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
  --sev-warn: #d9a557; --sev-warn-soft: #332409;
  --band: #2a3941;
}
/* cv05 gives the l a tail, so l/1/I are three shapes in a login; ss03 fixes the
   spacing of the curly quotes and slashes that PR refs and paths are full of. */
body { font-family: var(--font-sans); font-size: 14px; line-height: 1.5;
       font-feature-settings: "cv05" 1, "ss03" 1;
       margin: 0; padding: 1rem 1.25rem 3rem;
       background: var(--bg); color: var(--fg); }
nav { display: flex; gap: 1rem; margin-bottom: 1rem; font-size: 13px; align-items: center; }
/* Every link, not only the nav. The browser's default blue and its visited
   purple are both close to unreadable on a dark ground, and a link is the most
   clicked thing on every one of these pages. */
a, a:visited { color: var(--accent); }
/* The page's own name. Four of the six pages had no heading at all, which leaves
   a screen reader with nothing to say the page IS and a skip link with nowhere
   to land. Sized down from the browser's 2em: these are dense pages and the
   heading is a signpost, not a banner. */
h1 { font-size: 1.35rem; margin: .2rem 0 .6rem; }
/* The first stop in the tab order, drawn only once it is reached. Between the
   nav and the content of the table page sit fourteen sort buttons and ten
   dropdowns, and walking them on every visit is what a skip link exists to
   spare. `<main>` carries no tabindex: following a fragment moves the sequential
   focus starting point to the target on its own, and a tabindex there would put
   `main` in the focus-ring rule below — a 2px outline round the whole page. */
.skip { position: absolute; left: .5rem; top: -3rem; z-index: 50;
        background: var(--surface); color: var(--fg); font-size: 13px;
        border: 1px solid var(--line-strong); border-radius: 3px;
        padding: .35rem .6rem; text-decoration: none; }
.skip:focus { top: .5rem; }
/* Announced, not drawn. `display: none` and `visibility: hidden` both take an
   element out of the accessibility tree, so a live region that must stay
   readable to a screen reader and invisible to everybody else is clipped. */
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
           overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
#theme {
  margin-left: auto; width: 28px; height: 28px; border-radius: 50%;
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--fg);
  /* The glyphs are small inside their em box — the sun especially — so the box
     is grown until the drawing fills the button rather than floating in it. */
  font-size: 19px; line-height: 26px; cursor: pointer; padding: 0;
  display: flex; align-items: center; justify-content: center;
}
#theme:hover { border-color: var(--accent); color: var(--accent); }
.derived { color: var(--muted); font-variant-numeric: tabular-nums; font-style: italic; }
#controls { margin: .75rem 0; }
#controls .facets { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: baseline;
                    margin-top: .5rem; }
.facet { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.facet select { display: block; font: inherit; font-size: 13px; text-transform: none;
                letter-spacing: 0; color: inherit; }
#q { font: inherit; font-size: 13px; padding: .15rem .3rem; min-width: 16rem; }
.hint { color: var(--muted); font-size: 12px; }
.empty { color: var(--empty); }
.num { font-variant-numeric: tabular-nums; }
/* One meter for the whole app: weeks bet against weeks available. It was a rule
   on the cycle page until the cycles index and then the people page needed the
   same picture, and a second copy of a meter is two meters that disagree about
   what full looks like.
   `span.bar` and not `.bar`, because this stylesheet is on every page and every
   timeline bar is a rect wearing the same class. In SVG2 `width` and `height`
   are CSS geometry properties on a rect, and any author rule beats a
   presentation attribute — so a bare `.bar` here drew all seventeen Gantt bars
   at 140x8 and the chart stopped being about dates. Every meter site is a span;
   the element name is the whole of what keeps the two apart. */
span.bar { display: inline-block; width: 140px; height: 8px; background: var(--line);
           border-radius: 4px; overflow: hidden; vertical-align: middle; }
span.bar > span { display: block; height: 100%; background: var(--accent); }
.over span.bar > span { background: var(--danger); }
/* One chip everywhere a status or a kind is named, defined here rather than per
   page because the table, the detail page, the people page and the cycle bet
   table were four different ways of saying the same word. The word is always
   inside the chip, so the colour is redundant encoding and a reader who cannot
   separate the hues loses nothing. */
.chip { display: inline-block; font-family: var(--font-mono); font-size: 11px;
        line-height: 1.45; text-transform: uppercase; letter-spacing: .04em;
        padding: .1rem .4rem; border-radius: 2px; white-space: nowrap; }
{#- Written by the loop rather than by hand: five statuses times four tokens is
    twenty values to keep in step, and the pair that drifts is the pair nobody
    reads until a chip turns white on white. -#}
{% for s in statuses %}
.chip.st-{{ s }} { background: var(--st-{{ s }}-soft); color: var(--st-{{ s }}-text); }
{%- endfor %}
/* Kind never competes with status for attention: no hue, only a weight and a
   hairline. A project is the only one that gets the accent, because it is the
   only one there are ever a handful of. */
.chip.kind-project { color: var(--fg); font-weight: 650; border: 1px solid var(--accent); }
.chip.kind-pitch { color: var(--kind-ink); border: 1px solid var(--kind-line); }
.chip.kind-task { color: var(--kind-ink); }
/* A problem reads the same on every page: a bar down the left of the row, a soft
   ground on the cell that caused it, a glyph carrying the message. Three classes
   rather than one, so a row can be marked without tinting every cell in it. */
.sev-row-blocker { border-left: 3px solid var(--sev-blocker); }
.sev-row-warn { border-left: 3px solid var(--sev-warn); }
.sev-cell-blocker { background: var(--sev-blocker-soft); }
.sev-cell-warn { background: var(--sev-warn-soft); }
.sev-mark { font-family: var(--font-mono); font-size: 11px; cursor: help; }
.sev-mark-blocker { color: var(--sev-blocker); }
.sev-mark-warn { color: var(--sev-warn); }
/* Every interactive thing, and :focus-visible rather than :focus so a mouse
   click does not leave a ring behind it. :where() keeps the specificity at zero,
   so a page stylesheet loaded after this one still wins on colour. */
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
  border-radius: 2px;
}
/* The key to the one thing on a page that is not a word. Shared, because the
   graph and the timeline draw the same statuses in the same tokens, and every
   swatch is the token the shape is actually filled with — a legend naming a
   different colour from the one on screen is worse than no legend, because it
   is believed. The swatch carries the glyph too: colour is no longer the only
   channel on a bar or a node, so a key to the colour alone keys half the
   drawing. */
.legend { display: flex; flex-wrap: wrap; gap: .25rem 1rem; align-items: center;
          list-style: none; margin: .75rem 0 0; padding: 0;
          font-size: 12px; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: .35rem; }
.legend .swatch { width: 20px; height: 11px; border-radius: 2px; flex: none; }
/* inline-flex on the span only. Two of these swatches are <svg>, where a flex
   display on the root would be laying out a replaced element as a box. */
.legend span.swatch { display: inline-flex; align-items: center; justify-content: center;
                      font-family: var(--font-sans); font-weight: 700;
                      font-size: 9px; line-height: 1; }
{% for s in statuses %}
.legend .swatch.st-{{ s }} { background: var(--st-{{ s }}); color: var(--st-{{ s }}-ink); }
{%- endfor %}
/* The way out of a filter, on every page that has one. Three pages were drawing
   this button themselves, which is three chances for the way out of a filter to
   look like something else. */
#clear-filters { font: inherit; font-size: 13px; padding: .2rem .6rem; border-radius: 2px;
                 border: 1px solid var(--line-strong); background: var(--surface);
                 color: var(--fg); cursor: pointer; }
#clear-filters:hover { border-color: var(--accent); color: var(--accent); }
/* The one action that writes, on every page that writes. It follows the form it
   commits instead of sitting above it, and it is sticky rather than merely last:
   these forms are the length of the plan, and a Save at the far end of one is a
   Save you go looking for while holding an unsaved decision in your head.
   Defined here rather than per page because four pages have one, and four copies
   of a commit bar is four answers to "have I saved this yet". */
.commitbar {
  /* Under the suggestion popup (20) and under the shell's banner (40): a bar
     that is always on screen is always in front of something. */
  position: sticky; bottom: 0; z-index: 10;
  display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap;
  margin: 1.5rem 0 0; padding: .5rem .75rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: 3px;
}
/* Unsaved work is a warning, not decoration: this is the state in which closing
   the tab loses something. */
.commitbar.dirty { border-color: var(--warn); }
#unsaved { font-size: 12px; color: var(--muted); }
.commitbar.dirty #unsaved { color: var(--warn); font-weight: 600; }
#save, .commitbar button { font: inherit; font-size: 13px; padding: .25rem .8rem;
        border-radius: 2px; border: 1px solid var(--line-strong);
        background: var(--surface); color: var(--fg); cursor: pointer; }
#save:disabled { color: var(--muted); cursor: default; }
#save:not(:disabled) { border-color: var(--accent); color: var(--accent); }
/* What the status chosen in this form will make the server refuse it without.
   A warning colour because it is a refusal waiting to happen, and a word rather
   than an asterisk because an asterisk means "required" only to people who have
   already been told. */
.req { font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
       color: var(--sev-warn); font-weight: 600; }
/* Every date the plan renders is ISO; every `<input type=date>` renders in the
   browser's locale. So one reader edits 2026-09-01 as 01/09/2026 and the next as
   09/01/2026, and neither can tell which. The box keeps its locale — that is
   what it is typed in — and the value the file holds is echoed beside it. */
.iso { display: block; font-family: var(--font-mono); font-size: 11px;
       color: var(--muted); font-variant-numeric: tabular-nums; }
/* Inside the body, not above it or beside it: an empty table with the message
   somewhere else is still a header row over a void. Two tables draw one now —
   the plan's rows and the people's — so the shape of "there is nothing here"
   lives with the button that gets you out of it. */
tr.nothing td { padding: 2.5rem .5rem; text-align: center; }
tr.nothing .headline { margin: 0 0 .25rem; color: var(--fg); font-size: 15px; }
tr.nothing .hint { margin: 0 0 .75rem; }
/* Above everything a page can stick to its own edges — the cycle page's commit
   bar sits in exactly this corner — because news that the plan moved under you
   is the one thing on screen that must not be behind something else. */
#moved { position: fixed; right: 1rem; bottom: 1rem; z-index: 40;
         background: var(--accent); color: var(--on-accent);
         padding: .5rem .8rem; font-size: 13px; border-radius: 3px; }
#moved a { color: var(--on-accent); }
#moved .sha { font-family: var(--font-mono); opacity: .7; }
{{ style }}
</style></head><body>
<a class="skip" href="#main">Skip to the content</a>
<nav><a href="{{ links.table }}">Table</a><a href="{{ links.graph }}">Graph</a>
<a href="{{ links.timeline }}">Timeline</a><a href="{{ links.cycles }}">Cycles</a>
<a href="{{ links.people }}">People</a>
<a href="{{ links.detail }}">Detail</a>
<button type="button" id="theme"></button></nav>
{#- The home for a message on the pages that have nowhere to put one. Every page
    that announces anything had a `#state` of its own and every one of those was
    inside `{% if editable %}`, so a page you can only read carried no live
    region at all — and a save, a refusal or an explanation that is only drawn is
    one nobody is told about. -#}
<p id="announce" class="sr-only" role="status" aria-live="polite"></p>
<script>
// Declared before the content, because the pages' own scripts are inside it and
// some of them announce while loading — the cycle page's receipt, the detail
// page's restored draft. A function in a later <script> is not hoisted into an
// earlier one, so defining this alongside the theme toggle below would have made
// those two messages a ReferenceError instead.
const ANNOUNCE = document.getElementById('announce');

// `announce` and not `say`: two classic scripts on one page share one global
// scope, and the graph and the cycle page each already own a `say`.
function announce(message) {
  // The page's own place for a message where it has one, which is visible and is
  // already a live region — announcing into both would say everything twice.
  const where = document.getElementById('state') || ANNOUNCE;
  if (where.textContent === message) {
    // A live region speaks when its contents CHANGE, so refusing the same cell
    // twice would have been announced once. Cleared and re-set on a timer rather
    // than a frame, because a frame never comes in a tab nobody is looking at —
    // and the two-minute autosave says its receipt into exactly that tab.
    where.textContent = '';
    setTimeout(() => { where.textContent = message; }, 0);
    return;
  }
  where.textContent = message;
}
</script>
<main id="main">
{{ content }}
</main>
<script>
// No third state to cycle through: with nothing stored the page follows the
// system, and the first click stores the opposite of whatever is on screen.
const THEME = document.getElementById('theme');

function theme() {
  return document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function labelTheme() {
  const dark = theme() === 'dark';
  THEME.textContent = dark ? '\u2600' : '\u263e';
  THEME.title = dark ? 'Light mode' : 'Dark mode';
  THEME.setAttribute('aria-label', THEME.title);
}

THEME.onclick = () => {
  const next = theme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('openproj:theme', next); } catch (e) { /* still switches */ }
  labelTheme();
  // Anything painted by script rather than by the stylesheet — the graph — has
  // to be told, because its colours were read once when it was built.
  dispatchEvent(new Event('themechange'));
};

// A page opened while the system is dark and never clicked has no stored value,
// so it follows the system as it changes.
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', labelTheme);
labelTheme();

// The one format that never moves. A date box is drawn by the browser in the
// reader's locale, so the same stored 2026-09-01 reads as 01/09/2026 here and
// 09/01/2026 one desk over, while every date the plan *prints* is ISO. The echo
// carries the class the box carries, so it appears and disappears with it rather
// than repeating a value that is already on screen in read mode.
for (const box of document.querySelectorAll('input[type=date]')) {
  const echo = document.createElement('span');
  echo.className = box.classList.contains('field') ? 'iso field' : 'iso';
  const show = () => { echo.textContent = box.value || '—'; };
  show();
  box.addEventListener('input', show);
  box.addEventListener('change', show);
  box.insertAdjacentElement('afterend', echo);
}
</script>
{% if live %}
{#- role="status" and not a bare div: news that somebody else moved the plan
    under you is the one thing on screen that must reach a reader who is not
    looking at that corner. Polite, because it is not an emergency — the banner
    deliberately does nothing until you press reload. -#}
<div id="moved" role="status" aria-live="polite" hidden></div>
<script>
// Somebody else committed. Say so and get out of the way: reloading over an open
// editor would throw away work that is not in git yet, and the whole point of one
// Save being one commit is that nothing moves under you until you ask.
const moved = document.getElementById('moved');
// Commits this tab produced. Every commit comes back down this stream including
// your own, and being told "the plan changed" one keystroke after changing it is
// how a banner becomes wallpaper.
const movedOurs = new Set();
// A write is announced to the stream before the request that made it is
// answered, so the news of your own save can arrive before you know its sha.
// Anything that lands mid-write waits until it does.
let movedWriting = 0;
const movedHeld = [];
addEventListener('openproj:writing', () => { movedWriting++; });
addEventListener('openproj:wrote', event => {
  movedWriting = Math.max(0, movedWriting - 1);
  if (event.detail) movedOurs.add(event.detail);
  if (!movedWriting) while (movedHeld.length) showMoved(movedHeld.shift());
});

function showMoved({commit, changed}) {
  if (movedOurs.has(commit)) return;
  // What this page is looking at. A page showing one entity has it in its URL;
  // the table shows all of them and has nothing in its URL, so it says so — and
  // said nothing, every write anywhere read as unrelated to what was on screen.
  const here = location.pathname.split('/').pop();
  const showing = window.SHOWING || (here ? [here] : []);
  const seen = changed.some(id => showing.includes(id));
  moved.hidden = false;
  moved.innerHTML = (seen ? 'This was just changed by somebody else. ' : 'The plan changed. ')
    + `<a href="">reload</a> <span class="sha">${commit.slice(0, 7)}</span>`;
}

const source = new EventSource('/api/events');
source.onmessage = event => {
  const message = JSON.parse(event.data);
  if (movedWriting) movedHeld.push(message); else showMoved(message);
};
</script>
{% endif %}
</body></html>
"""

_FACETS = """
<div id="controls">
  {#- A placeholder is not a name: it is gone the moment anything is typed, and
      it never reaches the accessibility tree as one. Every dropdown beside this
      box is wrapped in its `<label>`; the search box was the one control in the
      bar that had nothing to say what it searches. -#}
  <input id="q" type="search" aria-label="Search title, tags, body"
         placeholder="Search title, tags, body">
  <div class="facets">
  {% for field in ['kind','priority','status','owner','assignees','reviewers',
                   'cycle','project','tags'] %}
  <label class="facet">{{ label(field) }}
    <select data-field="{{ field }}"><option value="">all</option>
      {% for value in facets.get(field, []) %}
      <option value="{{ value }}">{{ value|human }}</option>{% endfor %}
    </select>
  </label>
  {% endfor %}
  <label class="facet">{{ label('predicate') }}
    <select data-field="predicate"><option value="">all</option>
      {% for p in predicates %}<option value="{{ p }}">{{ p|human }}</option>{% endfor %}
    </select>
  </label>
  </div>
</div>
"""

# The filter model itself, shared by every view that offers the bar above. The
# README has always said three views filter the same plan the same way; while
# `matches` lived inside the table's script, that was true of one of them, and a
# second copy of it is how a facet comes to mean something different per page.
_FILTER_JS = """
<script>
const params = new URLSearchParams(location.search);

// Every field the control bar offers. A field in one list and not the other is a
// dropdown that changes the URL and filters nothing.
const FILTERS = ['kind','status','owner','assignees','reviewers','priority',
                 'cycle','project','tags'];

function wanted(field) { return params.getAll(field).filter(Boolean); }

// AND between fields, OR inside one: two owners means either of them, an owner
// and a status means both. Anything shaped like a table row can be asked — the
// graph hands it a node's data, which is that same row.
function matches(row) {
  const q = (params.get('q') || '').trim().toLowerCase();
  if (q && !(row.title + ' ' + row.tags.join(' ')).toLowerCase().includes(q)) return false;
  for (const field of FILTERS) {
    const values = wanted(field);
    if (!values.length) continue;
    const held = [].concat(row[field] ?? []).map(String);
    if (!values.some(v => held.includes(v))) return false;
  }
  const preds = wanted('predicate');
  if (preds.length && !preds.some(p => row.predicates.includes(p))) return false;
  return true;
}

// The controls take their state from the query string rather than from
// themselves, so a filtered view somebody pasted to you opens with its dropdowns
// already set.
function syncFilters() {
  for (const select of document.querySelectorAll('select[data-field]'))
    select.value = params.get(select.dataset.field) || '';
  document.getElementById('q').value = params.get('q') || '';
}

// replaceState rather than pushState: a filter is not a page you want to walk
// back out of one dropdown at a time. The view redraws on the event instead of
// being called from here, because each one draws something different out of the
// same answer.
function settled() {
  history.replaceState(null, '', '?' + params.toString());
  syncFilters();
  dispatchEvent(new Event('openproj:filter'));
}

function update(field, value) {
  if (value) params.set(field, value); else params.delete(field);
  settled();
}

function clearFilters() {
  // Every control the page actually draws, and not only the entity fields above:
  // the people page filters by role, which is not a field of an entity, and a
  // Clear that left it set is a Clear that did not clear.
  const onPage = [...document.querySelectorAll('select[data-field]')]
    .map(select => select.dataset.field);
  // Not the sort order: clearing the filters and losing the column somebody
  // sorted by is a second surprise on top of the one they were undoing.
  for (const field of [...FILTERS, ...onPage, 'predicate', 'q']) params.delete(field);
  settled();
}

document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
for (const select of document.querySelectorAll('select[data-field]'))
  select.addEventListener('change', e => update(e.target.dataset.field, e.target.value));
syncFilters();
</script>
"""

_TABLE = """
<h1>Table</h1>
{#- Both of these used to be on the rendered files too, where `links.new` is the
    empty string — so the button was a link back to the page you were already on,
    and the hint promised an editor that has no server to save to. A read-only
    export must not offer a control that cannot work: the first time one of them
    does nothing is the moment the rest of the page stops being believed. -#}
<p class="editbar">{% if editable %}<a class="button" href="{{ links.new }}">New entity</a>
   <span class="hint">double-click a cell, or press Enter on it, to edit it</span>
   {% endif %}<span id="state" role="status"></span></p>
<div id="summary">
  {#- Two numbers, because the count is of problems and the link filters
      entities: "3 blocking problems" opening a table of 2 rows is the exact way
      a count stops being believed. The second number is the one the link keeps
      its promise about. -#}
  <a id="blockers" href="?predicate=has_blocker"><strong id="blocker-count">{{ blockers
    }}</strong> <span id="blocker-word">blocking problem{{
    "" if blockers == 1 else "s" }}{% if blockers %} on {{ blocked }} {{
    "entity" if blocked == 1 else "entities" }}{% endif %}</span></a> ·
  <span id="shown">{{ payload.rows|length }}</span> of {{ payload.rows|length }} shown
</div>
{{ facets|safe }}
{#- role="grid" only where the cells are editable. It is a claim about who owns
    the arrow keys — a screen reader hands them to the page inside a grid and
    keeps them for its own cursor inside a table — and on a rendered file there
    is no editor for them to reach. -#}
<div class="table-scroll"><table id="rows"{% if editable %} role="grid"{% endif %}><thead><tr>
  {#- A real button inside every sortable header, not a click handler on the cell:
      there is no way to tab to a table cell, so sorting was mouse-only. The
      columns that cannot be sorted have no button, which is the difference said
      out loud. data-col names the field the column stands for, so the narrow
      breakpoint and the sticky rules pick columns by name rather than by
      counting them. -#}
  {% for column, header, sortable in [
      ('id', 'id', true), ('title', 'title', true), ('priority', 'priority', true),
      ('status', 'status', true), ('owner', 'owner', true), ('assignees', 'assignees', true),
      ('reviewers', 'reviewers', true), ('cycle', 'cycle', true), ('size', 'appetite', true),
      ('start', 'start', true), ('end', 'end', true), ('blocked_by', 'blockers', true),
      ('prs', 'prs', false), ('tags', 'tags', false)] %}
  {%- if sortable %}<th data-col="{{ column }}" data-sort="{{ column }}" aria-sort="none"
    ><button type="button">{{ header }}<span class="dir" aria-hidden="true"></span></button></th>
  {%- else %}<th data-col="{{ column }}">{{ header }}</th>{% endif %}
  {%- endfor %}
</tr></thead><tbody></tbody></table></div>
{% if editable %}
<input type="hidden" name="base_commit" id="base" value="{{ base_commit }}">
{#- A conflict is the one answer that means the save did not land. It was a
    box that appeared, and nothing more. -#}
<div id="row-conflict" role="status" aria-live="polite" hidden></div>
{% endif %}
<script id="payload" type="application/json">PAYLOAD_JSON</script>
{% if editable %}{{ combobox|safe }}{% endif %}
{{ filters|safe }}
<script>
// A payload that did not survive the trip is a third kind of empty, and it used
// to look exactly like the other two: a header row over a void. A truncated
// response is a different thing to do next from an empty plan, so the page has
// to be able to tell them apart rather than rendering nothing three ways.
let DATA = null;
try {
  DATA = JSON.parse(document.getElementById('payload').textContent);
} catch (error) { DATA = null; }
const LOADED = DATA !== null;
if (!LOADED) DATA = {rows: {}, problems: [], choices: {}, suggests: {}, human: {},
                     labels: {}, editable: null};

const tbody = document.querySelector('#rows tbody');
const HUMAN = DATA.human;
const FIELD_LABELS = DATA.labels;

// The reader's word for a stored identifier. Anything unknown comes back
// unchanged, so a status added to the model still renders — badly, but it
// renders, which beats a blank cell.
const human = value => HUMAN[value] ?? (value ?? '');

// Stored text into markup. Every row on this page is built by string
// concatenation from a file in the plan repository, and a title is a sentence
// somebody typed: `<` opens a tag on everybody else's screen and `"` ends the
// attribute it is sitting in. One helper for cells and attributes both, and the
// same four characters the timeline escapes — it is the same data, so it gets
// the same care.
const esc = value => String(value ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// Index-parallel with the header row above. Nothing enforces that at runtime,
// so the two are edited together or every cell shifts one column left.
const keys = ['id','title','priority','status','owner','assignees','reviewers','cycle',
              'size','start','end','blocked_by','prs','tags'];

// Which column carries a complaint about a field the table has no column for.
// Anything still unplaced falls to the id cell, because a row that says
// something is wrong and will not say what is worse than no marker at all.
const MARK_COLUMN = {effort_weeks: 'size', appetite_weeks: 'size', depends_on: 'blocked_by'};
const SEV_CLASS = {blocker: 'blocker', warning: 'warn'};

let MARKS = {};     // entity id -> column -> {severity, messages}
let TROUBLE = {};   // entity id -> the worst severity found on it
let BLOCKERS = 0;   // blocking problems
let BLOCKED = 0;    // entities carrying at least one of them — what the link opens

// The problems arrive flat, exactly as the validator produced them, and are
// grouped here rather than on the server: /api/index.json hands back the same
// flat list after a save, so one grouping serves both and the after-a-save path
// cannot drift from the at-load one.
function regroup(problems) {
  MARKS = {};
  TROUBLE = {};
  BLOCKERS = problems.filter(problem => problem.severity === 'blocker').length;
  for (const problem of problems) {
    const id = problem.entity_id;
    if (problem.severity === 'blocker' || !TROUBLE[id]) TROUBLE[id] = problem.severity;
    const column = MARK_COLUMN[problem.field]
      || (keys.includes(problem.field) ? problem.field : 'id');
    const columns = MARKS[id] || (MARKS[id] = {});
    const mark = columns[column]
      || (columns[column] = {severity: problem.severity, messages: []});
    if (problem.severity === 'blocker') mark.severity = 'blocker';
    mark.messages.push(problem.message);
  }
  // Two predicates are read straight off this list (index.py,
  // `_matches_predicate`), so they are the two a save can change. Recomputed
  // here, filling in a missing owner takes the row out of the filter that caught
  // it instead of leaving it there until somebody reloads.
  for (const [id, row] of Object.entries(DATA.rows)) {
    row.predicates = row.predicates
      .filter(name => name !== 'missing_required_fields' && name !== 'has_blocker');
    if (MARKS[id]) row.predicates.push('missing_required_fields');
    if (TROUBLE[id] === 'blocker') row.predicates.push('has_blocker');
  }
  // Counted off the same pass that decides the predicate, so the number beside
  // the link and the rows behind it cannot come apart.
  BLOCKED = Object.values(TROUBLE).filter(severity => severity === 'blocker').length;
}

function summarise() {
  document.getElementById('blocker-count').textContent = BLOCKERS;
  // The count is of problems and the link filters entities. One entity can hold
  // three of them, so the population the link opens is named as well — a count
  // that opens a table of a different size is a count nobody trusts again.
  document.getElementById('blocker-word').textContent = BLOCKERS
    ? `blocking problem${BLOCKERS === 1 ? '' : 's'} on ${BLOCKED} ` +
      `${BLOCKED === 1 ? 'entity' : 'entities'}`
    : 'blocking problems';
  // Danger at zero is danger nobody reads. A plan with nothing wrong with it was
  // shouting in the same colour as one that is on fire.
  document.getElementById('blockers').classList.toggle('none', BLOCKERS === 0);
}

// What the cell holds, as opposed to what it shows. A status cell shows a chip
// reading "In progress" and a tags cell shows one tag and a count; both used to
// be read back off the DOM when the editor opened, which would now save the
// label in place of the value.
function stored(row, key) {
  const value = row[key];
  return Array.isArray(value) ? value.join(', ') : (value ?? '');
}

// Why a computed column refuses a double-click. A cell that silently ignores one
// is indistinguishable from a cell that is broken, and every one of these is the
// scheduler's output: typing over a forecast is how a plan stops being believed.
const WHY = {
  size: 'Derived from the pitch appetite or the task effort, and from the default '
    + 'when neither is set.',
  start: 'Derived from assigned_on, from what blocks it, and from what the people '
    + 'on it are already doing.',
  end: 'Derived from the start and the appetite.',
  blocked_by: 'Counted from depends_on.',
};

function tagsHtml(list) {
  const tags = (list || []).map(esc);
  if (tags.length < 2) return tags.join('');
  // Five tags wrapped to five lines and every row on screen grew to match, so
  // one line and a count. The count is exact: "+2" means two you cannot see, not
  // two the browser might have fitted in anyway.
  const [first, ...rest] = tags;
  return `${first}<span class="rest">, ${rest.join(', ')}</span>` +
    `<button type="button" class="more" aria-label="Show ${rest.length} more tag` +
    `${rest.length === 1 ? '' : 's'}">+${rest.length}</button>`;
}

function shown(row, key) {
  const value = row[key];
  // The title is the way into the shaping doc; the id is the way to cite it.
  // A cell can be a link and still be editable. Making everything editable first
  // is what silently turned the PR column into plain text.
  if (key === 'title') return `<a href="ENTITY_HREF${esc(row.id)}">${esc(row.title)}</a>`;
  if (key === 'prs') return (value || []).map(prLink).join(', ');
  // Kind is filterable everywhere and visible nowhere. It rides with the id,
  // which was already carrying it in a prefix nobody should have to decode.
  if (key === 'id')
    return `<span class="chip kind-${esc(row.kind)}">${esc(human(row.kind))}</span>` +
      ` <span class="eid">${esc(row.id)}</span>`;
  if (key === 'status')
    return `<span class="chip st-${esc(row.status)}">${esc(human(row.status))}</span>`;
  if (key === 'priority') return esc(human(row.priority));
  if (key === 'tags') return tagsHtml(value);
  return esc(stored(row, key));
}

function cell(row, key) {
  const mark = (MARKS[row.id] || {})[key];
  const note = mark ? mark.messages.join(' · ') : '';
  const ground = mark ? 'sev-cell-' + SEV_CLASS[mark.severity] : '';
  // role="img" with a name, not a bare character: the message was reachable only
  // by hovering the row, and a tooltip is not something a table gets hovered for.
  const glyph = mark
    ? ` <span class="sev-mark sev-mark-${SEV_CLASS[mark.severity]}" role="img"` +
      ` aria-label="${esc(note)}" title="${esc(note)}">⚠</span>`
    : '';
  const body = shown(row, key) + glyph;
  const editable = EDITABLE && key in EDITABLE;
  // One class list rather than three returns. The tags clamp used to be written
  // only into the editable branch, so on a rendered file the column kept the
  // reveal button and showed every tag beside it anyway.
  const classes = [
    editable ? 'edit' : '',
    !editable && key in WHY ? 'derived' : '',
    key === 'tags' ? 'tags' : '',
    ground,
  ].filter(Boolean).join(' ');
  const named = (FIELD_LABELS[key] || key).toLowerCase();
  const tip = note || (editable ? 'Double-click to edit ' + named : WHY[key] || '');
  // Reachable without a mouse. This table is the app's primary editing surface
  // and it was double-click-only, so half the room could not change a single
  // field on it. `-1` rather than `0`: `rove()` promotes exactly one cell, so
  // the grid is one tab stop with the arrows moving inside it — fourteen columns
  // times forty rows is 560 stops if every cell takes one, which is not a
  // keyboard path, it is a maze.
  const reachable = EDITABLE && (editable || key in WHY);
  return `<td data-col="${key}"${editable ? ` data-entity="${row.id}" data-field="${key}"` : ''}` +
    `${!editable && key in WHY ? ` data-why="${esc(WHY[key])}"` : ''}` +
    `${reachable ? ' tabindex="-1"' : ''}` +
    ` class="${classes}"${tip ? ` title="${esc(tip)}"` : ''}>${body}</td>`;
}

function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${esc(repo)}/pull/${esc(number)}">${esc(ref)}</a>`;
}

function rowHtml(row) {
  // The stripe says "something on this row is wrong" before a single cell is
  // read; the glyph in the cell says which thing. The message used to live only
  // in a native tooltip on the row, where it was found by accident or not at all.
  const worst = TROUBLE[row.id];
  return `<tr data-id="${row.id}"${worst ? ` class="sev-row-${SEV_CLASS[worst]}"` : ''}>` +
    keys.map(key => cell(row, key)).join('') + '</tr>';
}

// Three ways for a table to be empty, and they rendered identically: a header
// row over nothing, which reads as a broken app whichever one it is. Which one
// it is decides what to do next, so the table says which one it is.
function emptyRow() {
  let headline = 'No entity matches these filters.';
  let detail = 'Every row is filtered out by the controls above.';
  let clearable = true;
  if (!LOADED) {
    headline = 'The plan could not be loaded.';
    detail = 'This page arrived without its data, so there is nothing to filter or sort.';
    clearable = false;
  } else if (!Object.keys(DATA.rows).length) {
    headline = 'This plan has no entities yet.';
    detail = 'Nothing has been pitched, shaped or scheduled.';
    clearable = false;
  }
  return `<tr class="nothing"><td colspan="${keys.length}">` +
    `<p class="headline">${headline}</p><p class="hint">${detail}</p>` +
    (clearable ? '<button type="button" id="clear-filters">Clear filters</button>' : '') +
    '</td></tr>';
}

function draw() {
  const sort = params.get('sort') || 'id';
  const descending = params.get('desc') === '1';
  // A status and a priority are sequences, not words: sorted as text, `done`
  // heads the status column and `high, low, medium` is not an order anybody
  // means by priority. Everything else really is alphabetical.
  const rank = DATA.choices[sort];
  const key = rank
    ? row => String(rank.indexOf(row[sort])).padStart(3, '0')
    : row => String(row[sort] ?? '');
  const rows = Object.values(DATA.rows).filter(matches)
    .sort((a, b) => key(a).localeCompare(key(b)));
  if (descending) rows.reverse();
  // Where the keyboard is, asked before `innerHTML` detaches the cell holding
  // it. A save redraws twice, so without this every commit dropped a keyboard
  // reader at the top of the page. Asked of the document rather than assumed:
  // the cell somebody has moved to since is where they are, and pulling them
  // back to the one that was edited is a second surprise on top of the redraw.
  // Except when a key closed the editor — Tab already said where to go.
  const focused = EDITABLE && tbody.contains(document.activeElement)
    ? document.activeElement.closest('td[tabindex]') : null;
  const held = EDITABLE && (RETURN || !!focused);
  if (focused && !RETURN) rove(focused);
  tbody.innerHTML = rows.length ? rows.map(rowHtml).join('') : emptyRow();
  if (EDITABLE) { rove(null, held); RETURN = false; }
  document.getElementById('shown').textContent = rows.length;
  // Sorting redraws without reloading, so the marker has to move with it. Set
  // once at load, it stayed on whatever the URL said when the page opened.
  for (const th of headers) {
    th.classList.toggle('sorted', th.dataset.sort === sort);
    if (!th.dataset.sort) continue;
    // The direction was invisible, so a column looked the same sorted either
    // way. Announced as well as drawn: aria-sort is all a screen reader has.
    const here = th.dataset.sort === sort;
    th.setAttribute('aria-sort', here ? (descending ? 'descending' : 'ascending') : 'none');
    th.querySelector('.dir').textContent = here ? (descending ? '▾' : '▴') : '';
  }
}
// The control bar changed the query string; what that means to a table is a
// redraw, and to the graph beside it a different set of nodes.
addEventListener('openproj:filter', draw);

{% if not editable %}
// A rendered file has no server to save to, so the table is a table.
const EDITABLE = null;
{% else %}
const BASE = document.getElementById('base');
const EDITABLE = DATA.editable;
const SUGGESTS = DATA.suggests;
const CHOICES = DATA.choices;

function coerce(type, raw) {
  raw = raw.trim();
  if (type === 'bool') return raw === 'true';
  // Deduplicated: picking a name already in the list is a slip, not an intent to
  // have it twice, and a duplicate reviewer reads as two people.
  if (type === 'list')
    return raw ? [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))] : [];
  if (type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    if (Number.isNaN(n)) throw new Error(`must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

// The validator and the scheduler run on the server, so what a save did to the
// problems is not something this page can work out for itself: it used to leave
// the count and the row markers stale until somebody reloaded, which is exactly
// when a count stops being read. Only the problems are re-read — dates are a
// forecast, and re-forecasting under somebody who is mid-edit is worse than
// being one reload behind.
async function refreshProblems() {
  const response = await fetch('/api/index.json');
  if (!response.ok) return;
  regroup((await response.json()).problems);
  summarise();
}

async function saveCell(cell, value) {
  const field = cell.dataset.field;
  let coerced;
  try {
    coerced = coerce(EDITABLE[field], value);
  } catch (error) {
    announce(`${field} ${error.message}`);
    return;
  }
  // The banner in the shell has to know a write is in the air before it starts:
  // the server announces a commit to the event stream before it answers the
  // request that made it, so the news of your own save can arrive before you
  // know its sha.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    // One key, taken from the cell. Sending the row would overwrite whatever
    // somebody else changed while this tab was open, and would turn two people
    // editing two different columns into a conflict field-level merge exists to
    // make invisible. No body: an empty string is a replacement, not an omission,
    // and would blank the shaping doc attached to the row.
    const response = await fetch(`/api/entity/${cell.dataset.entity}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: {[field]: coerced}, body: null}),
    });
    const answer = await response.json();
    const box = document.getElementById('row-conflict');
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = answer.conflict;
      return;
    }
    if (!response.ok) {
      announce(answer.detail || 'refused');
      return;
    }
    // The page moves forward with the repository, or its next save collides with
    // the commit it just made.
    committed = answer.commit;
    BASE.value = answer.commit;
    DATA.rows[cell.dataset.entity][field] = coerced;
    // Twice: once to put the typed value back into the cell rather than leaving
    // an open editor sitting there for the length of a second round trip, and
    // once when the server has said what that value did to the problems.
    draw();
    await refreshProblems();
    draw();
  } finally {
    // Announced even when the save was refused, or one 409 leaves every event
    // after it held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// Where the keyboard is in the grid, kept across the redraw a save triggers.
// `AT` is a row id and a column rather than an element, because `draw()` replaces
// every cell and the element that had focus no longer exists by the time the
// keyboard needs to go back to it.
let AT = null;
// Whether it should go back. `blur()` moves focus to <body> before the save it
// causes has even started, so this cannot be read off the document at redraw
// time — it is decided by the key that closed the editor.
let RETURN = false;

function stops() { return [...tbody.querySelectorAll('td[tabindex]')]; }

// One tab stop for the whole grid: exactly one cell is tabbable and the arrows
// move it. `rove` is the only thing that writes tabIndex, so the invariant
// cannot come apart across a redraw.
function rove(cell, focus) {
  const all = stops();
  if (!all.length) { AT = null; return; }
  const at = cell
    || (AT && all.find(td => td.dataset.col === AT.col
                             && td.parentNode.dataset.id === AT.id))
    || all[0];
  for (const td of all) td.tabIndex = td === at ? 0 : -1;
  AT = {id: at.parentNode.dataset.id, col: at.dataset.col};
  if (focus) at.focus();
}

function openEditor(cell) {
  // A computed column answers rather than swallowing the key, exactly as it
  // answers a double-click: a cell that ignores Enter is indistinguishable from
  // a cell that is broken.
  if (!cell.classList.contains('edit')) { refuse(cell); return; }
  if (cell.querySelector('input, select')) return;
  rove(cell);
  const field = cell.dataset.field;
  const was = stored(DATA.rows[cell.dataset.entity], field);
  const suggest = SUGGESTS[field];
  const closed = CHOICES[EDITABLE[field]];
  // The name the editor answers to. The cell it replaces carries its column in
  // a header a screen reader reads on the way in; a box conjured inside that
  // cell carries nothing at all unless it is told what it is editing.
  const named = esc(FIELD_LABELS[field] || field);
  // A closed set is chosen, never typed. Free text over three options is a way
  // to write `in progres` into the corpus. The option's value is the stored
  // identifier and its text is the word for it, so picking "In progress"
  // still writes `in_progress`.
  cell.innerHTML = closed
    ? `<select data-type="text" aria-label="${named}">${closed.map(o =>
        `<option value="${o}" ${o === was ? 'selected' : ''}>${human(o)}</option>`
      ).join('')}</select>`
    : `<input value="${esc(was)}" data-type="${EDITABLE[field]}" aria-label="${named}"` +
      `${suggest ? ` data-suggest="${suggest}"` : ''} autocomplete="off">`;
  const input = cell.querySelector('select, input');
  // The table gets the autocomplete the detail page has. Suggestions that only
  // appear in one of the two places are suggestions nobody relies on.
  if (suggest) attachSuggest(input);
  input.focus();
  // A single-value cell selects everything, because a double-click leaves the
  // caret where it landed and typing would interleave. A list must NOT: typing
  // over a selected "jcanton, halungge" deletes both reviewers to write one.
  if (EDITABLE[field] !== 'list' && input.select) input.select();
  else if (input.setSelectionRange)
    input.setSelectionRange(input.value.length, input.value.length);

  let abandoned = false;
  input.onblur = () => {
    if (abandoned || input.value === was) draw();
    else saveCell(cell, input.value);
  };
  input.onkeydown = e => {
    if (e.key === 'Enter') { RETURN = true; input.blur(); }
    if (e.key === 'Escape') {
      // Escape means discard. Redrawing first would fire blur with the partial
      // value still in the box, and the edit somebody just abandoned gets saved.
      abandoned = true;
      RETURN = true;
      draw();
    }
    if (e.key === 'Tab') {
      // Commit and move, the way every grid does. Left to the browser, Tab
      // blurs — which saves — and the redraw the save causes throws the focus
      // away, so the cell to land on is chosen here and `draw()` puts the
      // keyboard on it once the rows exist again.
      e.preventDefault();
      const line = [...cell.parentNode.cells].filter(td => td.hasAttribute('tabindex'));
      const wanted = line.indexOf(cell) + (e.shiftKey ? -1 : 1);
      AT = {id: cell.parentNode.dataset.id,
            col: line[Math.max(0, Math.min(line.length - 1, wanted))].dataset.col};
      RETURN = true;
      input.blur();
    }
  };
}

if (EDITABLE) {
  tbody.addEventListener('dblclick', event => {
    const cell = event.target.closest('td.edit');
    // The tag reveal is a control inside an editable cell, so a double-click on
    // it would both open the list and open the editor over it.
    if (!cell || event.target.closest('button.more')) return;
    openEditor(cell);
  });

  tbody.addEventListener('keydown', event => {
    const cell = event.target.closest('td[tabindex]');
    // Only a cell's own keys. Once an editor is open the keys belong to it — its
    // Escape discards and its Tab commits — and the grid must not act as well.
    if (!cell || event.target !== cell) return;
    if (event.key === 'Enter' || event.key === 'F2') {
      // F2 as well as Enter, because that is the key every spreadsheet uses and
      // Enter is the one everybody tries first.
      event.preventDefault();
      openEditor(cell);
      return;
    }
    const step = {ArrowLeft: [0, -1], ArrowRight: [0, 1],
                  ArrowUp: [-1, 0], ArrowDown: [1, 0]}[event.key];
    if (!step) return;
    event.preventDefault();
    const rows = [...tbody.rows].filter(tr => tr.dataset.id);
    const line = tr => [...tr.cells].filter(td => td.hasAttribute('tabindex'));
    const clamp = (i, n) => Math.max(0, Math.min(n - 1, i));
    // Clamped rather than wrapped: an arrow at the edge of a plan should stop,
    // not jump to the far corner of it.
    const row = rows[clamp(rows.indexOf(cell.parentNode) + step[0], rows.length)];
    const across = line(row);
    rove(across[clamp(line(cell.parentNode).indexOf(cell) + step[1], across.length)], true);
  });
}
{% endif %}
tbody.addEventListener('click', event => {
  if (event.target.id === 'clear-filters') { clearFilters(); return; }
  const more = event.target.closest('button.more');
  if (more) more.closest('td').classList.add('open');
});
// A derived cell that ignores a double-click looks exactly like a cell that is
// broken. It answers instead, in the same place a refused save answers — and
// through `announce`, so the answer reaches a reader who cannot see that place.
function refuse(cell) {
  announce(cell.dataset.why);
  cell.classList.add('refused');
  setTimeout(() => cell.classList.remove('refused'), 1500);
}
tbody.addEventListener('dblclick', event => {
  const computed = event.target.closest('td[data-why]');
  if (computed) refuse(computed);
});
document.getElementById('blockers').addEventListener('click', event => {
  // A real href, so the count can be copied, shared and opened in a tab. Handled
  // here as well so that following it keeps whatever else was already filtered.
  event.preventDefault();
  update('predicate', 'has_blocker');
});
// The banner in the shell has no id in its URL to compare against on this page,
// because the table shows every entity rather than one. So the table says what
// it is looking at, and "somebody changed the thing in front of you" stays
// distinguishable from "somebody changed something".
window.SHOWING = Object.keys(DATA.rows);
// Column widths, dragged and remembered. The defaults are whatever the browser
// works out from the content, and are only frozen once somebody drags: measuring
// them all at that moment is what keeps the other columns where they were.
// Bumped when the columns changed: widths stored against the old positional
// keys would land on the wrong columns rather than simply being ignored. Bumped
// again when the cells did — id and status grew a chip and tags shrank to one
// line, so a width dragged for the old contents clips the new ones, and a stored
// width is exactly the thing the automatic fit is not allowed to overrule.
const WIDTH_KEY = 'openproj:widths:3';
const WIDTHS = JSON.parse(localStorage.getItem(WIDTH_KEY) || '{}');
let dragging = false;
const table = document.getElementById('rows');
const headers = [...table.querySelectorAll('th')];

// Columns that may wrap. Everything else is sized so that it never has to: a
// column one character narrower than its widest value costs a second line on
// every row that holds that value.
const WRAPS = new Set(['prs', 'tags']);

// A column's identity is its sort key, or its label where it has none. It used
// to be the column's POSITION for those two, so inserting a column anywhere to
// their left silently handed prs the width somebody had dragged for blockers.
const keyOf = (th, i) => th.dataset.sort || th.textContent.trim();
const FLOOR = 110;      // narrower than this and a wrapping column is unreadable
const LONGEST = 200;    // and this is as far as the borrowing may squeeze a sentence

// Size every column to its content and the table to the window, once, when
// nothing has been dragged yet. Measured with every cell on one line, so a
// column ends up as wide as its widest value needs and not one character more.
// What each column would need with every cell on one line. Measured from a
// layout that has forgotten the widths already applied, or a column can only
// ever be measured wider than it currently is.
function naturalWidths() {
  const applied = headers.map(th => th.style.width);
  headers.forEach(th => { th.style.width = ''; });
  table.classList.add('measuring');
  table.style.tableLayout = 'auto';
  table.style.width = 'max-content';
  const natural = headers.map(th => th.getBoundingClientRect().width);
  table.classList.remove('measuring');
  headers.forEach((th, i) => { th.style.width = applied[i]; });
  return natural;
}

function fitWidths() {
  const scroll = table.parentElement;
  const natural = naturalWidths();

  const wrapping = headers.map(th => WRAPS.has(keyOf(th, 0)));
  const fixed = natural.map((w, i) => wrapping[i] ? 0 : Math.ceil(w * 1.1));
  let spare = scroll.clientWidth - fixed.reduce((a, b) => a + b, 0);

  // The columns that never wrap can want more than the window on their own, and
  // then the wrapping ones are left with nothing. Take the difference out of the
  // widest of them — in practice title, the only one whose content is a sentence
  // — rather than letting prs and tags collapse to a column of one character.
  const need = FLOOR * wrapping.filter(Boolean).length - spare;
  if (need > 0) {
    let widest = 0;
    fixed.forEach((w, i) => { if (w > fixed[widest]) widest = i; });
    const give = Math.min(need, Math.max(0, fixed[widest] - LONGEST));
    fixed[widest] -= give;
    spare += give;
  }

  // Floor first and split only what is over it. Taking the larger of the floor
  // and a proportional share instead hands out more than there is: each column
  // separately clears the floor, and their sum quietly exceeds the window.
  const share = natural.filter((w, i) => wrapping[i]).reduce((a, b) => a + b, 0) || 1;
  const extra = Math.max(0, spare - FLOOR * wrapping.filter(Boolean).length);
  headers.forEach((th, i) => {
    const key = keyOf(th, i);
    WIDTHS[key] = wrapping[i] ? FLOOR + Math.floor(extra * natural[i] / share) : fixed[i];
  });
  applyWidths();
}

function applyWidths() {
  if (!Object.keys(WIDTHS).length) return;
  table.style.tableLayout = 'fixed';
  let total = 0;
  headers.forEach((th, i) => {
    // A column the narrow breakpoint dropped is not part of the total. Counted
    // in, the table is set wider than the columns it actually draws and the last
    // one floats away from the right edge of nothing.
    if (th.offsetParent === null) { th.style.width = ''; return; }
    const key = keyOf(th, i);
    if (WIDTHS[key]) { th.style.width = WIDTHS[key] + 'px'; total += WIDTHS[key]; }
  });
  // The table stops being 100% wide once the columns are explicit. Left at 100%,
  // a fixed layout divides the space it is given, so widening one column silently
  // squeezes every other — which is precisely what freezing them was meant to
  // prevent. It scrolls sideways in its own container instead.
  table.style.width = total + 'px';
  stickyOffset();
}

// The title column has to begin exactly where the id column ends, and that width
// is dragged, remembered and re-fitted — so it is measured after layout rather
// than written into the stylesheet, where it would be wrong the first time
// somebody moved a grip.
function stickyOffset() {
  table.style.setProperty('--sticky-1', headers[0].getBoundingClientRect().width + 'px');
}

headers.forEach((th, i) => {
  const grip = document.createElement('span');
  grip.className = 'grip';
  th.append(grip);
  grip.onclick = event => event.stopPropagation();
  // Double-click a grip and the column shrinks to what its widest cell needs on
  // one line — the width you would have dragged to, without the dragging.
  grip.ondblclick = event => {
    event.stopPropagation();
    const key = keyOf(th, i);
    WIDTHS[key] = Math.ceil(naturalWidths()[i]);
    localStorage.setItem(WIDTH_KEY, JSON.stringify(WIDTHS));
    applyWidths();
  };
  grip.onpointerdown = event => {
    event.stopPropagation();
    event.preventDefault();
    // The click that follows a drag lands on the header, not the grip, so
    // stopping propagation here is not enough — the sort handler checks this.
    dragging = true;
    grip.classList.add('dragging');
    // Freeze every column first, or resizing one reflows all the others.
    headers.forEach((other, j) => {
      const key = keyOf(other, j);
      WIDTHS[key] = WIDTHS[key] || Math.round(other.getBoundingClientRect().width);
    });
    table.style.tableLayout = 'fixed';
    const key = keyOf(th, i);
    const from = event.clientX;
    const was = WIDTHS[key];
    const move = e => {
      WIDTHS[key] = Math.max(40, was + e.clientX - from);
      applyWidths();
    };
    const stop = () => {
      grip.classList.remove('dragging');
      setTimeout(() => { dragging = false; }, 0);   // after the click it caused
      localStorage.setItem(WIDTH_KEY, JSON.stringify(WIDTHS));
      removeEventListener('pointermove', move);
      removeEventListener('pointerup', stop);
    };
    addEventListener('pointermove', move);
    addEventListener('pointerup', stop);
  };
});

for (const th of document.querySelectorAll('th[data-sort]')) {
  // On the header, not on the button inside it: a click anywhere in the cell
  // still sorts, and the button's own Enter and Space arrive here by bubbling —
  // which is the whole reason it is a button and not a click handler on a cell
  // nobody can tab to.
  th.addEventListener('click', () => {
    if (dragging) return;
    // Clicking the column you are already sorted by reverses it, which is what
    // every table anybody has used does.
    const already = (params.get('sort') || 'id') === th.dataset.sort;
    params.set('sort', th.dataset.sort);
    update('desc', already && params.get('desc') !== '1' ? '1' : '');
  });
}
regroup(DATA.problems);
summarise();
draw();
// After the first draw, because there is nothing to measure before the rows
// exist. Stored widths win: they were set by hand, on purpose.
if (Object.keys(WIDTHS).length) applyWidths(); else fitWidths();
// The breakpoint drops columns as the window narrows, and the sticky title
// column starts where the id column ends — both are facts about a layout that
// only exists once it has been laid out.
addEventListener('resize', () => { applyWidths(); stickyOffset(); });
</script>
"""

_TABLE_STYLE = """
/* Where a refused save and a refused edit both answer. It stays on screen
   because the rows scroll inside their own box rather than scrolling the page
   out from under the bar that is talking to you. */
#state { color: var(--muted); font-size: 12px; }
#summary { color: var(--muted); }
/* The whole phrase, not the digit: "1 blocking problems" in danger red with the
   count black beside it read as two separate facts. And the colour has to mean
   something — at zero it is muted, because danger nobody can act on is danger
   nobody reads. */
#blockers { color: var(--sev-blocker); text-decoration: none; }
#blockers:hover { text-decoration: underline; }
#blockers.none { color: var(--muted); }
/* The table body scrolls in here rather than in the page. `position: sticky` on
   a header needs a scroll container to hold against, and a container the height
   of its own content gives `top: 0` nothing to do. */
/* The stack above the rows: nav, heading, edit bar, summary, facets. Grown by
   the heading the page did not use to have — left at 13rem the box ran past the
   bottom of the window, and the page scrolled the sticky header out of reach. */
.table-scroll { overflow: auto; max-height: calc(100vh - 15rem); min-height: 9rem;
                overscroll-behavior: contain; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td {
  border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left;
  /* Border-box, or a width set from a measured box gains the padding again and
     every column grows by exactly one cell's worth on the first drag. */
  box-sizing: border-box;
  /* A PR reference has no space in it, so at a narrow width it hangs over the
     next column instead of wrapping inside its own. */
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 400;
     text-transform: uppercase; letter-spacing: .04em; font-size: 11px; }
th[data-sort] { cursor: pointer; user-select: none; }
th.sorted { color: inherit; font-weight: 700; }
th { position: relative; }
/* The button is the header: it takes the cell's type so the column still reads
   as a label, and only the focus ring says it is a control. */
th button { font: inherit; color: inherit; letter-spacing: inherit;
            text-transform: inherit; background: none; border: 0; padding: 0;
            cursor: pointer; }
/* Reserved whether or not this is the sorted column, so sorting does not shove
   every header one glyph to the left. */
th .dir { display: inline-block; width: .8em; color: var(--accent); }
thead th {
  position: sticky; top: 0; z-index: 3; background: var(--surface);
  /* A collapsed border is not painted on a sticky cell — the first row scrolls
     straight over the top of it — so the rule is drawn inside the box instead. */
  box-shadow: inset 0 -1px 0 var(--line);
}
/* The two columns that say which row you are looking at. Scrolled right without
   them, fourteen columns of values belong to nobody. They need a ground of their
   own and a layer above the cells passing underneath. */
[data-col="id"] { position: sticky; left: 0; z-index: 1; background: var(--surface); }
[data-col="title"] { position: sticky; left: var(--sticky-1, 0px); z-index: 1;
                     background: var(--surface); box-shadow: 1px 0 0 var(--line); }
thead [data-col="id"], thead [data-col="title"] { z-index: 4; }
thead [data-col="title"] { box-shadow: inset 0 -1px 0 var(--line), 1px 0 0 var(--line); }
/* After the sticky rules and at the same weight, or a problem in the id or the
   title column loses its ground to the sticky one. */
td.sev-cell-blocker { background: var(--sev-blocker-soft); }
td.sev-cell-warn { background: var(--sev-warn-soft); }
/* Editable and derived cells looked identical, and the only thing that said
   otherwise was a 12px hint at the top of the page. */
td.edit { cursor: cell; }
td.edit:hover { background: var(--surface-2); box-shadow: inset 0 -1px 0 var(--line-strong); }
td.refused { background: var(--surface-2); }
td.tags { white-space: nowrap; overflow: hidden; }
td.tags .rest { display: none; }
td.tags .more { font: inherit; font-size: 11px; line-height: 1.2; margin-left: .3rem;
                padding: 0 .25rem; border: 1px solid var(--line-strong); border-radius: 2px;
                background: none; color: var(--muted); cursor: pointer; }
td.tags.open { white-space: normal; }
td.tags.open .rest { display: inline; }
td.tags.open .more { display: none; }
td .sev-mark { margin-left: .25rem; }
.eid { font-family: var(--font-mono); }
td[data-col="cycle"], td[data-col="size"], td[data-col="start"], td[data-col="end"],
td[data-col="blocked_by"] { font-variant-numeric: tabular-nums; }
th .grip {
  position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize;
}
th .grip::before {
  content: ""; position: absolute; top: 20%; bottom: 20%; right: 3px; width: 1px;
  background: var(--line-strong);
}
th .grip:hover::before, th .grip.dragging::before { background: var(--accent); width: 2px; }
.measuring th, .measuring td { white-space: nowrap; }
/* One screen is not one width. Fourteen columns below this and every one of them
   is too narrow to read, so the three that are lookups rather than answers go —
   they are all reachable on the detail page, and the filters above still see
   them. */
@media (max-width: 1100px) {
  [data-col="reviewers"], [data-col="prs"], [data-col="tags"] { display: none; }
}
"""

_GRAPH = """
<h1>Graph</h1>
{% if editable %}
<p class="editbar">
  <button type="button" id="connect">Edit dependencies</button>
  <button type="button" id="save" hidden>Save</button>
  <button type="button" id="discard" hidden>Reset</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</p>
{% endif %}
<p class="hint" id="panhint">Double-click a node to open it. Drag to pan, scroll to zoom,
  drag a node to move it.</p>
{% if editable %}
<p class="hint" id="howto" hidden>Click what must finish first and then what waits for
  it. Draw as many as you like; nothing is written until you press Save.
  <strong>Reset</strong> clears what you have drawn and stays in edit mode.</p>
{% endif %}
{{ facets|safe }}
{#- The one thing on this canvas that is not a word. Every swatch is the token
    the node is actually filled with and carries the glyph the node's title is
    prefixed with, so the legend cannot drift from the graph and it keys both
    channels rather than only the one a dichromat cannot use. -#}
<ul class="legend" aria-label="What a node's colour and mark mean">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
<div id="summary"><span id="shown">{{ total }}</span> of {{ total }} shown<span
  id="context"></span></div>
<div class="canvas">
  <div id="cy"></div>
  <div id="nothing" hidden>
    <p class="headline">No entity matches these filters.</p>
    <p class="hint">Every node is filtered out by the controls above.</p>
    <button type="button" id="clear-filters">Clear filters</button>
  </div>
</div>
<script id="elements" type="application/json">ELEMENTS_JSON</script>
<script>@@cytoscape.min.js@@</script>
<script>@@dagre.min.js@@</script>
<script>@@cytoscape-dagre.js@@</script>
{{ filters|safe }}
<script>
cytoscape.use(cytoscapeDagre);

// Read from the stylesheet rather than repeated here, so one token set decides
// what a status looks like on the timeline, in the table and on this canvas.
const token = name => getComputedStyle(document.documentElement)
  .getPropertyValue(name).trim();
const COLOUR = () => ({
  shaping: token('--st-shaping'), ready: token('--st-ready'),
  in_progress: token('--st-in_progress'), done: token('--st-done'),
  shelved: token('--st-shelved'),
});
// A label's colour belongs to the fill it sits on, not to the page. In dark mode
// these fills are light shapes carrying dark ink, so the text on a node flips
// with its own background rather than with the theme's foreground — white on
// them would be exactly the failure the light theme avoids.
const INK = () => ({
  shaping: token('--st-shaping-ink'), ready: token('--st-ready-ink'),
  in_progress: token('--st-in_progress-ink'), done: token('--st-done-ink'),
  shelved: token('--st-shelved-ink'),
});
// The fill is the only status channel on this canvas, and five fills on a
// luminance ladder are separable without being nameable: you can see that one
// box is darker than the next and still not know which state that is. So a
// node's own title carries the status glyph in front of it — the same glyph the
// timeline draws at a bar's left edge and the legend below shows in its swatch.
// Not a token: a shape, so it survives a screenshot, a projector and deuteranopia.
const GLYPH = {{ glyphs|tojson }};
const labelOf = node =>
  (GLYPH[node.data('status')] || '') + ' ' + (node.data('label') || '');

// Cytoscape aligns a left-aligned label by its RIGHT edge against the box's left
// edge, so putting a group's name inside its own box means knowing how wide the
// name is. There is no API for that and character counts put an "i" and a "W" in
// different places, so it is measured on a canvas in the font the graph draws in.
const ruler = document.createElement('canvas').getContext('2d');
const GROUP_SIZE = 12;
const GROUP_MAX = 300;    // the width the label is told to ellipsise at
function groupWidth(node) {
  ruler.font = `600 ${GROUP_SIZE}px ${token('--font-sans')}`;
  // The string the box is actually labelled with, glyph included. Measuring the
  // bare title put every group name a glyph's width off the box it belongs to.
  return Math.min(GROUP_MAX, ruler.measureText(labelOf(node)).width);
}

// Named once: filtering re-runs it, and a second copy of the options is how the
// graph comes to lay itself out one way at load and another way afterwards.
const LAYOUT = {"name": "dagre", "rankDir": "LR", "nodeSep": 18, "rankSep": 70};

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements: JSON.parse(document.getElementById('elements').textContent),
  layout: LAYOUT,
  // Filtering re-fits what is left to the window, and two boxes fitted to a
  // 1400px canvas came out at nearly 3x — the same graph reading as a different
  // app. Zooming in by hand stops at the same place, which at a 10px label is
  // still twice as large as anybody needs.
  maxZoom: 2,
  style: [
    { selector: 'node', style: {
        'label': labelOf, 'font-size': 10, 'shape': 'round-rectangle',
        // One typeface for the whole app, this canvas included — and the ruler
        // above measures group labels in it, so a second stack here would put
        // every group label a few pixels off the box it belongs to.
        'font-family': token('--font-sans'),
        // text-wrap alone does nothing: without a max width the label just
        // overflows the box it is supposed to sit inside.
        'text-wrap': 'wrap', 'text-max-width': 136,
        'background-color': e => COLOUR()[e.data('status')],
        // A rank, not arithmetic on the value: priority became a word, and
        // `4 - 'high'` is NaN, which cytoscape draws as no border at all.
        'border-width': e => ({high: 4, medium: 2, low: 1})[e.data('priority')] ?? 2,
        // The fill's own ink, not the accent. The fills are a luminance ladder,
        // so one border colour for all five is 2:1 against the darkest of them —
        // and the border is how priority is drawn, which makes it a channel that
        // has to be legible on every rung, not only on the middle ones.
        'border-color': e => INK()[e.data('status')],
        'color': e => INK()[e.data('status')], 'text-valign': 'center',
        'width': 150, 'height': 44 } },
    { selector: '.picked', style: {
        'border-color': token('--danger'), 'border-width': 5 } },
    // The name of a group used to be 9px of --muted sitting ON the box's border,
    // where every edge crossing the box ran straight through it. Inside, top
    // left, on its own ground: a box whose name you cannot read is a box that
    // says only that something is grouped, not what by.
    { selector: ':parent', style: {
        'background-opacity': .08, 'padding': 20,
        'font-size': GROUP_SIZE, 'font-weight': 600, 'color': token('--fg'),
        // Ellipsis rather than wrap: the offset below is measured on one line,
        // and a label that wrapped would be positioned as if it had not.
        'text-wrap': 'ellipsis', 'text-max-width': GROUP_MAX,
        'text-valign': 'top', 'text-halign': 'left',
        'text-margin-x': e => groupWidth(e) + 12, 'text-margin-y': 17,
        'text-background-color': token('--surface'), 'text-background-opacity': 1,
        'text-background-padding': 3, 'text-background-shape': 'roundrectangle' } },
    // On the canvas only because something that did match points at it. Faded
    // rather than removed, so no arrow leaves for a box you cannot see.
    { selector: 'node.aside', style: { 'opacity': .32 } },
    { selector: 'edge', style: {
        // Orthogonal with rounded corners, not bezier: dagre ranks left to right,
        // so an edge that leaves horizontally and turns once reads as a route
        // between ranks instead of a curve drawn over whatever is in between.
        // taxi-direction is set per edge by route(); this is only the fallback
        // for an edge added before the first routing pass.
        'width': 1.5, 'curve-style': 'round-taxi', 'taxi-direction': 'horizontal',
        'taxi-turn': '50%', 'taxi-turn-min-distance': 12, 'taxi-radius': 8,
        // The default is outside-to-LINE, which trims the ends along the straight
        // line between the two centres — so however cleanly the middle is routed,
        // both stubs come out at an angle. outside-to-node trims towards the next
        // control point instead, which is the whole difference between an
        // orthogonal edge and one that only looks orthogonal in the middle.
        'source-endpoint': 'outside-to-node', 'target-endpoint': 'outside-to-node',
        'target-arrow-shape': 'triangle',
        'line-color': token('--st-ready'), 'target-arrow-color': token('--st-ready') } },
    { selector: 'edge.pending', style: {
        'line-color': token('--danger'), 'target-arrow-color': token('--danger'),
        'line-style': 'dashed', 'width': 2 } },
  ],
});

// Which way an edge is allowed to turn, decided from where the boxes actually
// are rather than fixed in the stylesheet. Cytoscape computes a taxi turn from
// node CENTRES, so when two boxes overlap in x — which compound containers
// routinely do, being hundreds of pixels wide — the horizontal turn lands inside
// the source box and the trimmed stub comes out at an angle. Up or down is then
// the only right-angled way between them. Recomputed after every layout and
// every drag, so an edge that is orthogonal stays orthogonal when nodes move.
function route() {
  cy.edges().forEach(edge => {
    const from = edge.source().boundingBox(), to = edge.target().boundingBox();
    const overlapsInX = from.x1 < to.x2 && to.x1 < from.x2;
    edge.style('taxi-direction', overlapsInX ? 'vertical' : 'horizontal');
  });
}
// The style above was resolved from tokens once, at build time. Flipping the
// theme changes the tokens, not the resolved values, so every one of them is
// re-read — the ink with the fill, because a light fill needs dark text on it
// and the two are not the same token any more.
function paint() {
  cy.style()
    .selector('node').style({'background-color': e => COLOUR()[e.data('status')],
                             'border-color': e => INK()[e.data('status')],
                             'color': e => INK()[e.data('status')]})
    .selector('.picked').style({'border-color': token('--danger')})
    .selector(':parent').style({'color': token('--fg'),
                                'text-background-color': token('--surface'),
                                'text-margin-x': e => groupWidth(e) + 12})
    .selector('edge').style({'line-color': token('--st-ready'),
                             'target-arrow-color': token('--st-ready')})
    .selector('edge.pending').style({'line-color': token('--danger'),
                                     'target-arrow-color': token('--danger')})
    .update();
  route();
}
addEventListener('themechange', paint);
// The face is inlined but still swaps in asynchronously, and a group label
// measured against the fallback stays where the fallback put it.
if (document.fonts) document.fonts.ready.then(paint);

cy.on('layoutstop', route);
cy.on('position', 'node', route);
route();

// One filter model, three views — the graph's answer to it is which boxes are on
// the canvas. Hiding a node takes its edges with it, and an arrow leaving for
// something you filtered out is the one thing a dependency graph must not draw,
// so: a node that matches is drawn; anything it depends on or that depends on it
// is drawn faded, because "this is blocked by something you filtered out" is
// exactly the fact you were filtering for; a box containing either is kept, or
// its contents float outside the group they belong to. Everything else leaves
// the layout, and an edge is drawn when both of its ends are still on the
// canvas — which, by construction, every edge of a matching node is.
let laidOut = cy.nodes().map(node => node.id()).sort().join(',');

function applyFilter() {
  const keep = new Set();
  cy.nodes().forEach(node => { if (matches(node.data())) keep.add(node.id()); });
  const aside = new Set();
  for (const id of keep)
    cy.getElementById(id).neighborhood('node').forEach(near => {
      if (!keep.has(near.id())) aside.add(near.id());
    });
  // A container earns its place by what it holds, so it is never the faded one:
  // the group's name is how you know where the boxes inside it live.
  const boxes = new Set();
  for (const id of [...keep, ...aside])
    cy.getElementById(id).ancestors().forEach(box => {
      if (!keep.has(box.id()) && !aside.has(box.id())) boxes.add(box.id());
    });
  const on = id => keep.has(id) || aside.has(id) || boxes.has(id);

  cy.batch(() => {
    cy.nodes().forEach(node => {
      node.style('display', on(node.id()) ? 'element' : 'none');
      node.toggleClass('aside', aside.has(node.id()));
    });
    cy.edges().forEach(edge => {
      const both = on(edge.source().id()) && on(edge.target().id());
      edge.style('display', both ? 'element' : 'none');
    });
  });

  document.getElementById('shown').textContent = keep.size;
  document.getElementById('context').textContent = aside.size
    ? ` · ${aside.size} more faded, because what is shown depends on ` +
      (aside.size === 1 ? 'it' : 'them')
    : '';
  // An empty canvas is indistinguishable from a graph that failed to draw.
  document.getElementById('nothing').hidden = keep.size > 0;

  // Only when the set actually changed: re-running dagre on every keystroke in
  // the search box moves every box under the hand that is typing.
  const now = cy.nodes(':visible').map(node => node.id()).sort().join(',');
  if (now === laidOut || !keep.size) return;
  laidOut = now;
  cy.elements(':visible').layout({...LAYOUT, fit: true}).run();
}

addEventListener('openproj:filter', applyFilter);
document.getElementById('clear-filters').onclick = clearFilters;
applyFilter();

const CONNECT = document.getElementById('connect');
const SAVE = document.getElementById('save');
const DISCARD = document.getElementById('discard');
const PANHINT = document.getElementById('panhint');
let connecting = false;
// `blocker`, not `source`: two classic scripts on one page share one global
// scope, and the shell's `const source = new EventSource(...)` below threw on a
// name this file had already taken — which killed the plan-changed banner on
// this page and nowhere else.
let blocker = null;

// The shell's live region does the placing: `#state` where the page has one — a
// rendered file has no edit mode and so no bar to put it in — and the hidden
// region on every page otherwise. Drawing it without announcing it is how a
// refused dependency became a sentence only half the room could read.
function say(message) { announce(message); }

function pending() {
  return cy.edges('.pending');
}

function tally(extra) {
  const n = pending().length;
  SAVE.hidden = DISCARD.hidden = !connecting;
  SAVE.disabled = n === 0;
  const drawn = n === 0 ? 'nothing drawn yet' :
                n === 1 ? '1 dependency drawn — press Save to commit it' :
                `${n} dependencies drawn — press Save to commit them`;
  say(connecting ? (extra ? extra + ' · ' + drawn : drawn) : (extra || ''));
}

// Opening is on double-click: a single tap is also the first half of drawing an
// edge, and on a graph you drag around, one stray click should not navigate away.
cy.on('dbltap', 'node', evt => {
  if (!connecting) location.href = 'ENTITY_HREF' + evt.target.id();
});

if (CONNECT) {
  CONNECT.onclick = () => {
    const dropped = connecting ? pending().length : 0;
    if (dropped) cy.remove(pending());
    connecting = !connecting;
    blocker = null;
    cy.nodes().removeClass('picked');
    CONNECT.textContent = connecting ? 'Discard and exit' : 'Edit dependencies';
    // Instructions for a mode you are not in are noise on every other visit.
    document.getElementById('howto').hidden = !connecting;
    // One hint or the other, never both: in edit mode a click picks a node, so
    // the standing hint was telling you to drag what you are meant to click.
    PANHINT.hidden = connecting;
    tally(connecting ? 'click what must finish first, then what waits for it'
                     : dropped ? `discarded ${dropped}` : '');
  };

  DISCARD.onclick = () => {
    cy.remove(pending());
    blocker = null;
    cy.nodes().removeClass('picked');
    tally('reset');
  };

  // One PATCH per dependent, because depends_on lives on the entity that waits.
  // Each write moves HEAD, so the base for the next one is the commit this one
  // returned — reusing the page's base would make every write after the first a
  // conflict against a commit this same button just created.
  SAVE.onclick = async () => {
    SAVE.disabled = true;
    const wanted = new Map();
    for (const edge of pending()) {
      const target = edge.target().id();
      wanted.set(target, [...(wanted.get(target) || []), edge.source().id()]);
    }
    const base = document.getElementById('base');
    let written = 0;
    for (const [id, sources] of wanted) {
      const node = cy.getElementById(id);
      const fields = {depends_on: [...new Set([...(node.data('depends_on') || []), ...sources])]};
      // Declared before the request and answered in `finally`, because the server
      // announces a commit to the event stream before it answers the request that
      // made it — so this tab can hear about its own write first. Announced even
      // on a refusal, or one rejected edge holds every later event forever.
      dispatchEvent(new Event('openproj:writing'));
      let committed = null;
      try {
        const response = await fetch(`/api/entity/${id}`, {
          method: 'PATCH', headers: {'content-type': 'application/json'},
          body: JSON.stringify({base_commit: base.value, fields, body: null}),
        });
        const answer = await response.json();
        if (!response.ok) {
          // The validator refuses an edge onto an ancestor, and a cycle. Say which,
          // and say what did get written: stopping silently after three of five
          // would leave the page disagreeing with the repository.
          const why = answer.detail || (answer.problems || []).map(p => p.message).join('; ');
          say(`${id}: ${why || 'refused'}${written ? ` — ${written} already saved` : ''}`);
          SAVE.disabled = false;
          return;
        }
        committed = answer.commit;
        base.value = answer.commit;
        written += 1;
      } finally {
        dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
      }
    }
    location.reload();
  };
}

cy.on('tap', 'node', evt => {
  const node = evt.target;
  if (!connecting) return;
  if (!blocker) {
    blocker = node;
    node.addClass('picked');
    tally(`${node.id()} must finish first — now click what waits for it`);
    return;
  }
  const from = blocker;
  blocker = null;
  from.removeClass('picked');

  if (from.id() === node.id()) { tally('an entity cannot wait for itself'); return; }
  if (cy.edges().some(e => e.source().id() === from.id() && e.target().id() === node.id())) {
    tally('that dependency is already there');
    return;
  }
  // Checked here as well as on the server so a batch fails while you are drawing
  // it rather than at Save, when some of it has already been committed.
  if (node.successors().some(e => e.id() === from.id())) {
    tally(`${node.id()} already has to finish before ${from.id()}`);
    return;
  }
  if (node.ancestors().some(e => e.id() === from.id())) {
    tally('an entity cannot wait for what contains it');
    return;
  }

  cy.add({group: 'edges', classes: 'pending',
          data: {source: from.id(), target: node.id(), kind: 'depends'}});
  route();
  tally();
});
</script>
"""

_GRAPH_STYLE = """
#state { color: var(--muted); font-size: 12px; }
#summary { color: var(--muted); font-size: 13px; margin: .5rem 0 .25rem; }
#shown { font-variant-numeric: tabular-nums; }
.canvas { position: relative; }
#cy { height: 78vh; border: 1px solid var(--line); }
/* Over the canvas rather than instead of it: cytoscape measures its container
   when it is built, and a container that was display:none at that moment comes
   back sized zero. */
#nothing { position: absolute; inset: 0; display: flex; flex-direction: column;
           align-items: center; justify-content: center;
           background: var(--bg); text-align: center; }
#nothing[hidden] { display: none; }
#nothing .headline { margin: 0 0 .25rem; font-size: 15px; }
#nothing .hint { margin: 0 0 .75rem; }
"""

_TIMELINE = """
<h1>Timeline</h1>
{{ facets|safe }}
<form class="tl-controls" method="get" action="{{ links.timeline }}">
  {#- Prefilled with the window on screen, not the one that was asked for. Two
      empty boxes under a sentence reading "Showing 2026-02-02 to 2026-11-27" ask
      the reader to believe the page over the controls; Reset is what says the
      window is the default one. -#}
  <label class="facet">from <input type="date" name="from" value="{{ t.origin or '' }}"></label>
  <label class="facet">to <input type="date" name="to" value="{{ t.last or '' }}"></label>
  <label class="facet">zoom
    <select name="zoom">
      <option value="">fit to window</option>
      {% for px, label in zooms %}
      <option value="{{ px }}"{{ ' selected' if chosen == px else '' }}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
  <button type="submit" class="button primary">Apply</button>
  <a class="button reset" href="{{ links.timeline }}">Reset</a>
</form>
<p class="hint">{% if windowed %}Showing {{ t.origin }} to {{ t.last }}, a window of the
  plan — Reset goes back to all of it.{% else %}Showing the whole plan{% if t.origin %},
  {{ t.origin }} to {{ t.last }}{% endif %}.{% endif %}
  Drag sideways or scroll to move through it. Bars reaching past the window are
  clipped to it, never dropped.</p>
{#- Statuses first and marks second, because they are two questions: what state
    is this in, and how much of this bar is a guess. Every swatch is drawn from
    the same token or the same pattern the plot uses — including the glyph, which
    is the half of the status channel that is not colour. -#}
<ul class="legend" aria-label="What a bar's colour and mark mean">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
<ul class="legend" aria-label="What a bar marking means">
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="st-ready" width="20" height="11"/><rect
        class="mark mark-estimated st-ready" width="20" height="11"/></svg>appetite assumed</li>
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="st-ready" width="20" height="11"/><rect
        class="mark mark-unowned st-ready" width="20" height="11"/></svg>nobody on it</li>
  <li><span class="swatch outline late"></span>overruns its cycle</li>
  <li><span class="swatch rule today"></span>today</li>
  <li><span class="swatch rule boundary"></span>a cycle closes</li>
  <li><span class="swatch band"></span>a cycle, build and cooldown</li>
</ul>
<div id="summary"><span id="shown">{{ t.bars|length }}</span> of {{ t.bars|length }}
  drawn{% if t.offscreen %} · {{ t.offscreen }} with no dates in this
  window{% endif %}</div>
<div class="tl"{% if not t.bars %} hidden{% endif %}>
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
    <a href="{{ links.entity }}{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a
    ><span class="sr-only">{{ bar.reads }}</span></div>
  {% endfor %}
</div>
<div class="scroll">
<svg width="{{ t.width }}" height="{{ t.height }}"
     viewBox="0 0 {{ t.width }} {{ t.height }}" role="img"
     aria-label="Every scheduled entity as a bar. The same rows are listed beside it.">
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
  <text class="cycle-label" x="{{ cycle.x + 4 }}" y="12">{{ cycle.label }}</text>
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
  <a href="{{ links.entity }}{{ bar.id }}" tabindex="-1" aria-label="{{ bar.full }}"
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
<div id="tip" role="tooltip" hidden></div>
<script id="bars" type="application/json">BARS_JSON</script>
{{ filters|safe }}
<script>
const scroller = document.querySelector('.scroll');
const svg = scroller.querySelector('svg');
const plot = document.querySelector('.tl');
const nothing = document.getElementById('nothing');
const ROW_PX = {{ row_px }}, HEADER = {{ t.header }}, WIDTH = {{ t.width }};
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

const TIP = document.getElementById('tip');
const human = value => (DATA && DATA.human[value]) || value;
// A title comes out of a file in the plan repository and is written into markup
// here, which is the one place on this page that turns stored text into HTML.
const esc = text => String(text ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const DASH = '<span class="empty">—</span>';

function tipHtml(row) {
  // An owner who is also an assignee is one person, not two. The scheduler
  // already reads them that way — `_people_on` dedupes — and a box that says
  // "ann, ann" is a box nobody trusts the rest of.
  const others = (row.assignees || []).filter(who => who && who !== row.owner);
  const facts = [
    ['Owner', row.owner ? esc(row.owner) : DASH],
    ...(others.length ? [['With', esc(others.join(', '))]] : []),
    ['Appetite', row.weeks + (row.weeks === 1 ? ' week' : ' weeks')
      + (row.estimated ? ' <span class="guess">(assumed)</span>' : '')],
    ['Scheduled', row.start && row.end
      ? `<span class="num">${row.start}</span> to <span class="num">${row.end}</span>` : DASH],
  ];
  return `<p class="tip-title">${esc(row.title)}</p>` +
    `<p class="tip-chips"><span class="chip st-${row.status}">${esc(human(row.status))}</span> ` +
    `<span class="chip kind-${row.kind}">${esc(human(row.kind))}</span></p>` +
    '<dl>' + facts.map(([name, value]) => `<dt>${name}</dt><dd>${value}</dd>`).join('') +
    '</dl>' + `<p class="tip-why">${esc(row.tip)}</p>`;
}

// A bar carried its dates, its owner and its appetite nowhere: the only thing
// hoverable was a native tooltip holding one sentence about why it starts when
// it does. That sentence is still here, at the bottom, where it reads as the
// answer to a question the rest of the box has just raised.
function showTip(id, x, y) {
  const row = DATA && DATA.rows[id];
  if (!row) return;
  TIP.innerHTML = tipHtml(row);
  TIP.hidden = false;
  place(x, y);
}

function place(x, y) {
  const box = TIP.getBoundingClientRect();
  const left = x + 14 + box.width > innerWidth - 8 ? x - 14 - box.width : x + 14;
  const top = y + 14 + box.height > innerHeight - 8 ? y - 14 - box.height : y + 14;
  TIP.style.left = Math.max(8, left) + 'px';
  TIP.style.top = Math.max(8, top) + 'px';
}

svg.addEventListener('pointerover', event => {
  const rect = event.target.closest('rect[data-id]');
  if (rect) showTip(rect.dataset.id, event.clientX, event.clientY);
});
svg.addEventListener('pointermove', event => {
  if (!TIP.hidden) place(event.clientX, event.clientY);
});
svg.addEventListener('pointerout', event => {
  if (event.target.closest('rect[data-id]')) TIP.hidden = true;
});
// The keyboard reaches a row through the label beside it: an SVG anchor is not
// focusable in Chrome, and giving every bar a tabindex would put two stops on
// one row for the sake of the second one. So the label opens the same box.
for (const [id, row] of LABELS) {
  const link = row.querySelector('a');
  link.addEventListener('focus', () => {
    const box = link.getBoundingClientRect();
    showTip(id, box.right, box.bottom);
  });
  link.addEventListener('blur', () => { TIP.hidden = true; });
}
// The native tooltip holds the same sentence, arrives a second later and lands
// somewhere else. The markup keeps it so a page without script still explains
// itself; the anchor carries the accessible name either way.
if (DATA) for (const title of svg.querySelectorAll('title')) title.remove();

// One filter model, three views: the timeline's answer to it is which rows
// are on the chart. A hidden row leaves no gap: the rows below it move up, the
// drawing shrinks to what is left, and the rules that span the whole plot are
// cut to the new height.
const FULL_HEIGHT = svg.querySelectorAll('.cycle-rule, .month-rule, .today');
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
  const height = row * ROW_PX + HEADER + 20;
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
.tl-controls { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: end;
               margin: .75rem 0 .25rem; }
.tl-controls input, .tl-controls select {
  display: block; font: inherit; font-size: 13px; text-transform: none; letter-spacing: 0;
}
/* Apply was a button and Reset was a bare link, which reads as one control and
   one afterthought. They are the same pair of scissors pointed two ways, so they
   are the same size and shape; only the fill says which one is the verb. */
.tl-controls .button { font: inherit; font-size: 13px; line-height: 1.4;
                       padding: .2rem .7rem; border-radius: 2px; cursor: pointer;
                       border: 1px solid var(--line-strong); background: var(--surface);
                       color: var(--fg); text-decoration: none; }
.tl-controls .button:hover { border-color: var(--accent); color: var(--accent); }
.tl-controls .button.primary { background: var(--accent); border-color: var(--accent);
                               color: var(--on-accent); }
.tl-controls .button.primary:hover { color: var(--on-accent); opacity: .9; }
#summary { color: var(--muted); font-size: 13px; margin: .5rem 0 .25rem; }
#shown { font-variant-numeric: tabular-nums; }
/* The three markings, drawn the way the plot draws them: a hatch over a real
   status fill, an outline, a rule. A legend that redraws a mark in its own way
   is a legend that can be wrong about the picture beside it — which is how the
   band key came to be a bordered --surface-2 swatch standing in for an unbordered
   --surface-2 band, two wrong answers agreeing with each other. */
.legend .swatch.outline { background: var(--surface-2); }
.legend .swatch.late { border: 1.5px solid var(--danger); }
.legend .swatch.rule { width: 2px; height: 13px; border-radius: 0; }
.legend .swatch.today { background: var(--danger); }
.legend .swatch.boundary { background: none; border-left: 2px dashed var(--line-strong); }
.legend .swatch.band { background: var(--band); }
.tl { display: flex; border: 1px solid var(--line); align-items: stretch; }
.tl[hidden] { display: none; }
.labels { flex: 0 0 250px; border-right: 1px solid var(--line); }
.labels .row {
  /* Fixed, not min: the row carries a clipped title and a clipped-off sentence
     of what the bar draws, and the second one must not add a pixel of height —
     every row here lines up with a bar 22px down the plot beside it. */
  height: 22px; line-height: 22px; font-size: 11px; color: var(--muted);
  padding: 0 .5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scroll { overflow-x: auto; flex: 1 1 auto; min-width: 0; }
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
.cycle-label { font-size: 10px; fill: var(--accent); font-weight: 600; }
.today { stroke: var(--danger); stroke-width: 1.5; }
.today-label { font-size: 10px; fill: var(--danger); font-weight: 600; }
rect.bar { rx: 3; }
/* An assumed appetite and work nobody is on are hatched, not outlined: the
   outline says "overruns its cycle", and one channel carrying three facts says
   none of them. Drawn as a second rect over the bar so the status colour stays
   underneath, and transparent to the pointer so the bar is still what you hover. */
rect.mark { rx: 3; pointer-events: none; }
rect.late { stroke: var(--danger); stroke-width: 1.5; }
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
/* Follows the pointer, so it cannot be hovered itself and never becomes the
   thing under the cursor. */
#tip { position: fixed; z-index: 5; max-width: 22rem; pointer-events: none;
       background: var(--surface); color: var(--fg); font-size: 12px;
       border: 1px solid var(--line-strong); border-radius: 3px;
       padding: .4rem .55rem; box-shadow: 0 2px 8px rgb(0 0 0 / .18); }
#tip[hidden] { display: none; }
#tip .tip-title { margin: 0; font-size: 13px; font-weight: 600; }
#tip .tip-chips { margin: .25rem 0 .35rem; }
#tip dl { display: grid; grid-template-columns: auto 1fr; gap: 0 .6rem; margin: 0; }
#tip dt { color: var(--muted); font-size: 11px; text-transform: uppercase;
          letter-spacing: .04em; }
#tip dd { margin: 0; }
#tip .num { font-variant-numeric: tabular-nums; }
#tip .guess { color: var(--muted); font-style: italic; }
#tip .tip-why { margin: .35rem 0 0; color: var(--muted); font-style: italic; }
"""


def _status_paint_css() -> str:
    """The per-status half of the timeline's stylesheet.

    Twenty rules — a fill, a glyph ink and two hatch references for each status —
    so it is written by a loop. Spelled out by hand, the one that goes missing is
    a hatch, and a missing hatch does not look broken: it looks like a bar that
    has stopped being a guess.
    """
    rules = [f"rect.st-{s} {{ fill: var(--st-{s}); }}" for s in STATUSES]
    # The label on a shape belongs to the fill it sits on, not to the page: on the
    # dark theme's top rungs the fill is nearly white, and --fg on it is nothing.
    rules += [f"text.bar-glyph.st-{s} {{ fill: var(--st-{s}-ink); }}" for s in STATUSES]
    rules += [
        f"rect.mark-{mark}.st-{s} {{ fill: url(#hatch-{mark}-st-{s}); }}"
        for mark in ("estimated", "unowned")
        for s in STATUSES
    ]
    return "\n".join(rules) + "\n"


# Raw, because the JS in here contains regex escapes. `\\.` is not a Python escape,
# so it survived as a literal backslash and the widget worked — while emitting a
# SyntaxWarning on every fresh compile, and Python 3.14 turns that into an error.
_COMBOBOX = r"""
<script id="suggest" type="application/json">SUGGEST_JSON</script>
<script>
// Paste or drop an image and it goes into the plan repository, content-addressed,
// and the markdown that names it is inserted where the cursor is. The path is
// written repository-relative so the same text reads correctly in git, on GitHub
// and here — only the prefix in front of it differs.
function attachUploads(area, status) {
  function insert(markdown) {
    const at = area.selectionStart;
    area.value = area.value.slice(0, at) + markdown + area.value.slice(area.selectionEnd);
    area.selectionStart = area.selectionEnd = at + markdown.length;
    area.dispatchEvent(new Event('input', {bubbles: true}));
  }

  async function send(file) {
    if (!file || !file.type.startsWith('image/')) return;
    status.textContent = `uploading ${file.name || 'image'}…`;
    // A placeholder first, so a slow upload does not look like nothing happened
    // and the text cannot be typed over the spot it is going to land in.
    const token = `![uploading ${file.name || 'image'}…]()`;
    insert(token);
    // An upload is a commit like any other, so the shell's banner is told before
    // it starts and told its sha afterwards. Without this the server announced
    // the paste to every tab including this one, and "The plan changed." landed
    // over your own image with nothing left to take it away again.
    dispatchEvent(new Event('openproj:writing'));
    let committed = null;
    try {
      const response = await fetch('/api/asset', {
        method: 'POST', headers: {'content-type': file.type}, body: file,
      });
      const answer = await response.json();
      // Only a fresh upload made a commit. Claiming the sha of one that was
      // already in the plan would swallow a banner about somebody else's write.
      if (response.ok && answer.fresh) committed = answer.commit;
      const alt = (file.name || 'image').replace(/\.[^.]+$/, '').replace(/[\[\]]/g, '');
      area.value = area.value.replace(
        token, response.ok ? `![${alt}](${answer.path})` : ''
      );
      area.dispatchEvent(new Event('input', {bubbles: true}));
      status.textContent = response.ok
        ? (answer.fresh ? `${answer.path} uploaded` : `${answer.path} — already in the plan`)
        : (answer.detail || 'that upload was refused');
    } finally {
      dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
    }
  }

  area.addEventListener('paste', event => {
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    files.forEach(send);
  });
  area.addEventListener('dragover', event => {
    event.preventDefault();
    area.classList.add('dropping');
  });
  area.addEventListener('dragleave', () => area.classList.remove('dropping'));
  area.addEventListener('drop', event => {
    event.preventDefault();
    area.classList.remove('dropping');
    [...(event.dataTransfer?.files || [])].forEach(send);
  });
}

// Type-to-filter, not a picker beside the field. A datalist only completes a whole
// value, so on a comma-separated field it stops helping after the first name — and
// a separate "add" control is a second place to look for one job.
const SUGGEST = JSON.parse(document.getElementById('suggest').textContent);

// One counter for the whole page, because `aria-controls` and
// `aria-activedescendant` are references by id and a page can carry a dozen of
// these — every fact on the detail form, every cell of the betting table.
let SUGGEST_N = 0;

function attachSuggest(input) {
  const source = SUGGEST[input.dataset.suggest] || [];
  const multi = input.dataset.type === 'list';
  const list = document.createElement('ul');
  const id = 'suggest-' + (++SUGGEST_N);
  list.className = 'suggest';
  list.hidden = true;
  // The combobox contract, none of which this widget had. The keyboard already
  // worked — arrows moved a highlight, Enter picked it — but a highlight drawn
  // with a class is a highlight only a sighted reader can follow, and a popup
  // that is a bare <ul> is a popup nobody is told opened. The four attributes
  // below are the whole of the difference: what this control is, whether its
  // list is open, which list, and which option is current.
  list.id = id;
  list.setAttribute('role', 'listbox');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', id);
  input.setAttribute('aria-expanded', 'false');
  input.insertAdjacentElement('afterend', list);
  let active = -1;

  // `aria-activedescendant` is how a combobox says which option is current
  // without moving focus off the input — which it must not do, because the
  // input is still being typed into.
  function highlight() {
    const items = [...list.children];
    items.forEach((item, i) => {
      item.classList.toggle('on', i === active);
      item.setAttribute('aria-selected', String(i === active));
    });
    if (active >= 0) input.setAttribute('aria-activedescendant', items[active].id);
    else input.removeAttribute('aria-activedescendant');
  }

  const tokens = () => input.value.split(',').map(s => s.trim());
  const typed = () => (multi ? tokens()[tokens().length - 1] : input.value).trim().toLowerCase();

  function choose(value) {
    // `C2SM/icon4py#` is half a reference. Appending the separator after one would
    // end the entry at the point where the number still has to be typed.
    const partial = value.endsWith('#');
    if (multi) {
      const held = tokens();
      held[held.length - 1] = value;
      input.value = held.filter(Boolean).join(', ') + (partial ? '' : ', ');
    } else {
      input.value = value;
    }
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.focus();
    if (partial) { open(); return; }
    close();
  }

  function close() {
    list.hidden = true;
    list.innerHTML = '';
    active = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }

  function open() {
    const needle = typed();
    const matches = source
      .filter(item => (item.value + ' ' + item.label).toLowerCase().includes(needle))
      .filter(item => !multi || !tokens().slice(0, -1).includes(item.value))
      .slice(0, 8);
    list.innerHTML = matches
      .map((m, i) => `<li id="${id}-${i}" role="option" data-value="${m.value}">` +
        `${m.value}${m.label ? ` <span class="dim">${m.label}</span>` : ''}</li>`).join('');
    active = matches.length ? 0 : -1;
    list.hidden = !matches.length;
    input.setAttribute('aria-expanded', String(!list.hidden));
    highlight();
  }

  input.addEventListener('input', open);
  input.addEventListener('focus', () => {
    // A list that already holds a name needs a separator before the next one, or
    // the first thing typed lands inside the previous value and matches nothing.
    if (multi && input.value.trim() && !input.value.trim().endsWith(',')) {
      input.value = input.value.trim() + ', ';
      input.setSelectionRange(input.value.length, input.value.length);
    }
    open();
  });
  input.addEventListener('blur', () => setTimeout(close, 150));
  list.addEventListener('mousedown', event => {
    const item = event.target.closest('li');
    if (item) { event.preventDefault(); choose(item.dataset.value); }
  });
  input.addEventListener('keydown', event => {
    if (list.hidden) return;
    const items = [...list.children];
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      highlight();
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      choose(items[active].dataset.value);
    } else if (event.key === 'Escape') {
      close();
    }
  });
}

for (const input of document.querySelectorAll('[data-suggest]')) attachSuggest(input);
</script>
"""

_SUGGEST_STYLE = """
.suggest { position: absolute; z-index: 20; margin: 0; padding: 0; list-style: none;
           background: var(--surface); border: 1px solid var(--line-strong);
           border-radius: 3px; min-width: 14rem; max-height: 16rem; overflow-y: auto;
           box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.suggest li { padding: .25rem .5rem; cursor: pointer; }
.suggest li.on { background: var(--accent); color: var(--on-accent); }
textarea.dropping { outline: 2px dashed var(--accent); outline-offset: -2px; }
.doc img { max-width: 100%; height: auto; }
.suggest .dim { opacity: .6; }
.suggest li.on .dim { opacity: .85; }
dd, td.edit { position: relative; }
"""

# Every branch carries an `id`, and every `<dt>` that renders one of these carries
# a `<label for>` pointing at it. A `<dt>`/`<dd>` pair is a name and a value to a
# reader and nothing at all to the accessibility tree, so before this not one
# control on the detail page or the create page had a name.
_CONTROL = """
{% if f.type in ("status", "priority") %}
<select name="{{ f.name }}" id="{{ f.id }}" data-type="text" class="field"
        {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
  {% for s in (statuses if f.type == "status" else priorities) %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{ s|human }}</option>
  {% endfor %}
</select>
{% elif f.type == "bool" %}
<input type="checkbox" name="{{ f.name }}" id="{{ f.id }}" data-type="bool" class="field"
       {% if f.value %}checked{% endif %}>
{% elif f.type == "date" %}
<input type="date" name="{{ f.name }}" id="{{ f.id }}" data-type="date" value="{{ f.text }}"
       class="field"
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% else %}
<input name="{{ f.name }}" id="{{ f.id }}" data-type="{{ f.type }}" value="{{ f.text }}"
       class="field" autocomplete="off"
       {% if f.list %}data-suggest="{{ f.list }}"{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% endif %}
"""

# One script for both forms that carry a status. Written once because the create
# page and the detail page ask the same question of the same controls, and two
# copies of a validation courtesy is one copy that quietly stops matching.
_REQUIRED_JS = """
// The word printed beside a control, which is the word somebody is looking at.
// The `<dt>` holds the label and then the mark, so its first node is the name.
function labelOf(control) {
  const dt = control.closest('dd')?.previousElementSibling;
  return dt ? dt.childNodes[0].textContent.trim() : control.name;
}

// What the chosen status will make the server refuse this form without. Marked
// on the label rather than announced after a rejected save: which fields a
// status demands is the thing you need before you fill the form in, and the
// rules change under you the moment the status select does.
function markRequired(form) {
  const status = form.querySelector('[name=status]')?.value || 'shaping';
  const waived = form.querySelector('[name=review_waived]')?.checked;
  for (const control of form.querySelectorAll('[data-required-at]')) {
    // review_waived is the escape hatch from the reviewer rule, so honouring it
    // here is the difference between a mark and a nag.
    const demanded = control.dataset.requiredAt.split(' ').includes(status)
      && !(control.name === 'reviewers' && waived);
    if (demanded) control.setAttribute('aria-required', 'true');
    else control.removeAttribute('aria-required');
    const mark = control.closest('dd')?.previousElementSibling?.querySelector('.req');
    if (mark) mark.hidden = !demanded;
  }
}

// `change` and not `input`: the two controls that move the gates are a select
// and a checkbox, and both report on change. It listens on the form so a control
// that appears later — a kind switch unhides three — is covered without rewiring.
function watchRequired(form) {
  form.addEventListener('change', () => markRequired(form));
  markRequired(form);
}
"""


def _control_html(field: dict) -> str:
    return _ENV.from_string(_CONTROL).render(
        f=field, statuses=STATUSES, priorities=PRIORITIES
    )


# `_FIELDS` and `_fields_html` were the flat list of `<label>field</label>` this
# replaced, and nothing has called them since the create page became the detail
# page with nothing in it. They were the last place a raw field name reached a
# reader, and dead code that still renders is code somebody wires back up.


_NEW = """
<article class="entity editing">
  <p class="back"><a href="{{ links.table }}">← table</a></p>
  {#- The heading names the page; the title box below it is a control. It used to
      BE the heading — an `<h1>` whose only content was an empty input, which is
      a page with no name at all and a box with no name either. `aria-label`
      rather than a `<label for>` because the visible word is the placeholder,
      and a placeholder disappears the moment anything is typed. -#}
  <h1>New entity</h1>
  <input name="title" data-type="text" form="edit" value="" aria-label="Title"
         class="field title-field" placeholder="Title">
  <p class="meta">
    <label class="kindpick">kind
      <select id="kind">
        {% for k in kinds %}<option value="{{ k }}"
          {% if k == kind %}selected{% endif %}>{{ k|human }}</option>{% endfor %}
      </select>
    </label>
    · the id and the file are the server's to choose</p>
  <form id="edit" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <div class="panes">
      <aside class="facts">
        <dl id="facts">
          {% for row in rows %}
          <dt data-kinds="{{ row.kinds }}"><label for="{{ row.for
            }}">{{ row.label }}</label>{% if row.gates %}
            <span class="req" hidden>required</span>{% endif %}</dt>
          <dd data-kinds="{{ row.kinds }}">{{ row.control|safe }}</dd>
          {% endfor %}
        </dl>
      </aside>
      <div class="main">
        {#- What the form or the server refused this with. Filled by script, so
            it is news arriving on a page that is already open. -#}
        <ul id="problems" class="problems" role="status" aria-live="polite" hidden></ul>
        <p class="field bodybar">
          <button type="button" id="preview">Preview the body</button>
          <span class="hint">paste or drop an image to put it in the plan</span>
          <span class="hint" id="upload" role="status" aria-live="polite"></span>
        </p>
        <textarea name="body" class="field body-field" rows="14"
                  aria-label="Shaping document"
                  placeholder="The shaping document."></textarea>
        <div class="doc" hidden></div>
      </div>
    </div>
  </form>
  <div class="commitbar" id="commitbar">
    <span id="unsaved">Nothing is written until you press Create</span>
    <button type="button" id="save">Create</button>
    <span id="state" role="status"></span>
  </div>
</article>
{{ combobox|safe }}
<script>{{ required|safe }}</script>
<script>
const FORM = document.getElementById('edit');
const PROBLEMS = document.getElementById('problems');
const KIND = document.getElementById('kind');

// Every kind's fields are on the page and the ones this kind does not have are
// hidden, rather than each kind being its own round trip. Switching kind after
// typing a title used to mean typing it again.
function showKind() {
  for (const element of FORM.querySelectorAll('[data-kinds]'))
    element.hidden = !element.dataset.kinds.split(' ').includes(KIND.value);
}
KIND.onchange = showKind;
showKind();
// The status select is inside the form, so one listener on the form catches both
// it and the review_waived checkbox that lets one of its rules off.
watchRequired(FORM);

function read(control) {
  if (control.dataset.type === 'bool') return control.checked;
  const raw = control.value.trim();
  if (control.dataset.type === 'list')
    return raw ? raw.split(',').map(s => s.trim()).filter(Boolean) : [];
  if (control.dataset.type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    if (Number.isNaN(n)) throw new Error(`${control.name} must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

const PREVIEW = document.getElementById('preview');
const DOC = document.querySelector('.doc');
const BODY = FORM.querySelector('[name=body]');
attachUploads(BODY, document.getElementById('upload'));

PREVIEW.onclick = async () => {
  if (!DOC.hidden) {
    DOC.hidden = true;
    BODY.hidden = false;
    PREVIEW.textContent = 'Preview the body';
    return;
  }
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: BODY.value}),
  });
  DOC.innerHTML = (await response.json()).html;
  DOC.hidden = false;
  BODY.hidden = true;
  PREVIEW.textContent = 'Back to the source';
};

document.getElementById('save').onclick = async () => {
  const fields = {kind: KIND.value};
  const status = FORM.querySelector('[name=status]')?.value || 'shaping';
  const missing = [];
  for (const control of FORM.querySelectorAll('[data-type]')) {
    // A field this kind does not have is not empty, it is absent — sending it
    // would ask the server to set an attribute the model does not define.
    if (control.closest('[data-kinds]')?.hidden) continue;
    let value;
    try { value = read(control); } catch (error) { announce(error.message); return; }
    const empty = value === null || (Array.isArray(value) && !value.length);
    const waived = control.name === 'reviewers' &&
      FORM.querySelector('[name=review_waived]')?.checked;
    // The same gates the labels are marked from, so what the form refuses and
    // what it warned you about cannot be two different lists.
    const gates = control.dataset.requiredAt;
    if (gates && empty && !waived && gates.split(' ').includes(status))
      missing.push(labelOf(control));
    if (!empty) fields[control.name] = value;
  }
  const title = document.querySelector('.title-field');
  if (title.value.trim()) fields.title = title.value.trim(); else missing.push('Title');
  if (missing.length) {
    // The words on the page, not the words in the file: `appetite_weeks` and
    // `in_progress` are what git holds, and a refusal that names them sends
    // somebody looking for a field with that label.
    const chosen = FORM.querySelector('[name=status]');
    PROBLEMS.hidden = false;
    PROBLEMS.innerHTML = `<li>still needed at status ` +
      `${chosen?.selectedOptions[0]?.textContent.trim() || status}: ` +
      `${missing.join(', ')}</li>`;
    return;
  }
  // The shell's banner is told before the request goes and told the sha after,
  // because the server announces a commit to the event stream before it answers
  // the request that made it. Creating an entity is a write like any other, and
  // an unannounced one comes back to this tab as somebody else's news.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/entity', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: FORM.querySelector('[name=base_commit]').value, fields,
        body: BODY.value || '',
      }),
    });
    const answer = await response.json();
    if (!response.ok) {
      // The client check is a courtesy; this is the truth, and swallowing it leaves
      // somebody staring at a form that looks fine.
      PROBLEMS.hidden = false;
      PROBLEMS.innerHTML = (answer.problems || [])
        .map(p => `<li>${p.field}: ${p.message}</li>`).join('')
        || `<li>${answer.detail || 'refused'}</li>`;
      return;
    }
    committed = answer.commit;
    location.href = '/detail/' + answer.id;
  } finally {
    // Announced even when refused, or one rejected form leaves every later event
    // held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
};
</script>
"""

_DETAIL = """
{#- The index view is one of the views this page routes between, and it had no
    heading of its own — so with no hash in the URL the page was a list of links
    under nothing. Each `<article>` below carries its own `<h1>`, because each of
    them is a document and exactly one of them is ever displayed. -#}
{% if not single %}<div class="toc">
  <h1>Every entity in this plan</h1>
  {% for group in groups %}
  <h2 class="tocgroup">{{ group.status|human }}
    <span class="tally">{{ group.entities|length }}</span></h2>
  <ul>
    {% for e in group.entities %}
    <li><a href="{{ links.entity }}{{ e.id }}">{{ e.title }}</a>
        <span class="tocmeta"><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span>
          {{ e.owner or "unowned" }}</span></li>
    {% endfor %}
  </ul>
  {% endfor %}
</div>{% endif %}
{% for e in entities %}
<article id="{{ e.id }}" class="entity">
  <p class="back"><a href="{{ links.detail }}">← all</a></p>
  <h1><span class="read">{{ e.title }}</span></h1>
  <p class="meta"><code>{{ e.id }}</code>
     <span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span>
     <span class="chip st-{{ e.status }}">{{ e.status|human }}</span>
     {% if e.parent %}· in {{ e.parent_link|safe }}{% endif %}</p>
  {% if editable %}
  <form id="edit" data-id="{{ e.id }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <input name="title" data-type="text" value="{{ e.title }}" aria-label="Title"
           class="field title-field">
  {% endif %}
  <div class="panes">
    <aside class="facts">
      <dl id="facts">
        {#- The label only where the control it names is on the page. In read
            mode there is no control and a `<label for>` would point at nothing;
            in edit mode it is the only thing giving the box a name, because a
            `<dt>`/`<dd>` pair reads as a caption to a person and as two
            unrelated blocks of text to everything else. -#}
        {% for row in e.rows %}
        <dt class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">{% if
          editable and row.control %}<label for="{{ row.for }}">{{ row.label }}</label>{%
          else %}{{ row.label }}{% endif %}{% if
          editable and row.gates %} <span class="req" hidden>required</span>{% endif %}</dt>
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display|safe }}</span>
          {% if editable and row.control %}{{ row.control|safe }}{% endif %}
        </dd>
        {% endfor %}
      </dl>
    </aside>
    <div class="main">
      {% if e.problems %}<ul class="problems">
        {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
      <div class="doc read">{{ e.body|safe }}</div>
      {% if editable %}
      <p class="field bodybar">
        <button type="button" id="preview">Preview the body</button>
        <span class="hint">paste or drop an image to put it in the plan</span>
        <span class="hint" id="upload" role="status" aria-live="polite"></span>
      </p>
      <textarea name="body" class="field body-field"
                aria-label="Shaping document">{{ e.raw_body }}</textarea>
      <div id="body-preview" class="field doc" hidden></div>
      <div id="conflict" role="status" aria-live="polite" hidden></div>
      {% endif %}
    </div>
  </div>
  {% if editable %}
  </form>
  <div class="commitbar" id="commitbar">
    <span id="unsaved">Nothing to save</span>
    <button type="button" id="toggle">Edit</button>
    <button type="button" id="save" hidden>Save</button>
    <span id="state" role="status"></span>
  </div>
  {% endif %}
</article>
{% endfor %}
<div id="grip" title="drag to set the width"></div>
<script>
// What this page is looking at, for the shell's "somebody else changed this"
// banner. The shell falls back to the last segment of the URL, which is the id
// on /detail/<id> and the word "detail" on every other shape this page takes —
// the static export holds all of them in one file, and a write to any of them
// read as a write to nothing.
window.SHOWING = {{ showing|tojson }};

// The reader decides how wide prose should be. Remembered per browser rather than
// per entity: it is a property of the screen it is being read on, not of the plan.
const grip = document.getElementById('grip');
const root = document.documentElement;
const saved = localStorage.getItem('openproj:measure');
if (saved) root.style.setProperty('--measure', saved);

function place() {
  // The visible one. On the index view every article is hidden, and measuring a
  // hidden element gives zero — which parked the handle against the left edge of
  // the page, a rule down the side of a list it has nothing to do with.
  const article = [...document.querySelectorAll('article.entity')]
    .find(candidate => candidate.offsetParent !== null);
  grip.hidden = !article;
  if (article) grip.style.left = article.getBoundingClientRect().right + 'px';
}
place();
addEventListener('resize', place);

grip.onpointerdown = event => {
  grip.setPointerCapture(event.pointerId);
  grip.classList.add('dragging');
  const move = e => {
    // The column is centred, so its right edge is half a width from the middle of
    // the window: dragging that edge out by one pixel is two pixels of column.
    const width = Math.max(320, (e.clientX - innerWidth / 2) * 2);
    root.style.setProperty('--measure', width + 'px');
    place();
  };
  const stop = () => {
    grip.classList.remove('dragging');
    localStorage.setItem('openproj:measure', root.style.getPropertyValue('--measure'));
    removeEventListener('pointermove', move);
    removeEventListener('pointerup', stop);
  };
  addEventListener('pointermove', move);
  addEventListener('pointerup', stop);
};
</script>
{% if editable %}{{ combobox|safe }}{% endif %}
{% if editable %}<script>{{ required|safe }}</script>{% endif %}
{% if editable %}<script>
// Only what changed travels. Serialising the whole form would send back every
// field as this tab last saw it, overwriting whatever somebody else changed while
// it sat open — which is exactly what scoped compare-and-swap exists to prevent.
const FORM = document.getElementById('edit');
const ORIGINAL = {};
const CONTROLS = [...FORM.querySelectorAll('[data-type]')];
const BODY = FORM.querySelector('[name=body]');
attachUploads(BODY, document.getElementById('upload'));
const DRAFT = `openproj:${FORM.dataset.id}`;

function read(control) {
  const type = control.dataset.type;
  if (type === 'bool') return control.checked;
  const raw = control.value.trim();
  // Deduplicated: picking a name already in the list is a slip, not an intent to
  // have it twice, and a duplicate reviewer reads as two people.
  if (type === 'list')
    return raw ? [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))] : [];
  if (type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    // A form returns strings, and `priority: soon` is valid YAML that breaks the
    // scheduler on the next read. Refuse it here rather than commit it.
    if (Number.isNaN(n)) throw new Error(`${control.name} must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

for (const control of CONTROLS) ORIGINAL[control.name] = JSON.stringify(read(control));
const ORIGINAL_BODY = BODY.value;

function changed() {
  const fields = {};
  for (const control of CONTROLS) {
    const now = read(control);
    if (JSON.stringify(now) !== ORIGINAL[control.name]) fields[control.name] = now;
  }
  return fields;
}

// What has been typed and not committed, said out loud in the bar that commits
// it. An editor whose only signal is a button that always looks the same is an
// editor you close with work in it.
const BAR = document.getElementById('commitbar');
const UNSAVED = document.getElementById('unsaved');

function dirty() {
  let fields = {};
  // A number typed as a word throws in `read`; that is Save's message to deliver,
  // not a reason for the counter to stop counting the rest.
  try { fields = changed(); } catch (error) { fields = {}; }
  const count = Object.keys(fields).length + (BODY.value === ORIGINAL_BODY ? 0 : 1);
  const editing = document.querySelector('article.entity').classList.contains('editing');
  BAR.classList.toggle('dirty', count > 0);
  UNSAVED.textContent = count
    ? `${count} unsaved change${count === 1 ? '' : 's'}`
    : (editing ? 'Nothing changed yet' : 'Nothing to save');
}
FORM.addEventListener('input', dirty);
FORM.addEventListener('change', dirty);
// The status select decides which fields the server will refuse this without,
// and the checkbox beside it lets one of those rules off.
watchRequired(FORM);

function show(editing) {
  // One class on the article. Each fact is a single row whose value swaps for its
  // control, so nothing is shown twice and the page does not jump when you start.
  document.querySelector('article.entity').classList.toggle('editing', editing);
  document.getElementById('save').hidden = !editing;
  document.getElementById('toggle').textContent = editing ? 'Cancel' : 'Edit';
  dirty();
}

document.getElementById('toggle').onclick = () => {
  const editing = !document.querySelector('article.entity').classList.contains('editing');
  show(editing);
  if (!editing) localStorage.removeItem(DRAFT);
};

document.getElementById('preview').onclick = async () => {
  // Only the body, and without leaving edit mode. It used to swap the whole page
  // back to the read view, which showed the *stored* fields — so adding a reviewer
  // and pressing Preview appeared to lose the change.
  const pane = document.getElementById('body-preview');
  const button = document.getElementById('preview');
  if (!pane.hidden) {
    pane.hidden = true;
    BODY.hidden = false;
    button.textContent = 'Preview the body';
    return;
  }
  // A round trip, not a second markdown implementation: two renderers disagree
  // eventually, and the one people trust would not be the one that gets committed.
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: BODY.value}),
  });
  pane.innerHTML = (await response.json()).html;
  pane.hidden = false;
  BODY.hidden = true;
  button.textContent = 'Back to the source';
};

async function save() {
  let fields;
  try {
    fields = changed();
  } catch (error) {
    announce(error.message);
    return;
  }
  const body = BODY.value === ORIGINAL_BODY ? null : BODY.value;
  if (!Object.keys(fields).length && body === null) {
    announce('nothing changed');
    return;
  }

  announce('saving…');
  // The shell's banner has to know a write is in the air before it starts: the
  // server announces a commit to the event stream before it answers the request
  // that made it, so the news of your own save can arrive before you know its
  // sha. Without this, saving this page told you this page had just been changed
  // by somebody else.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/entity/${FORM.dataset.id}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: FORM.querySelector('[name=base_commit]').value, fields, body,
      }),
    });
    const answer = await response.json();
    const box = document.getElementById('conflict');
    if (response.status === 409) {
      // Into its own box, never into the textarea: text pasted into the editing
      // surface is text somebody saves back.
      box.hidden = false;
      box.textContent = answer.conflict;
      announce('not saved');
      return;
    }
    if (!response.ok) { announce(answer.detail || 'refused'); return; }
    committed = answer.commit;
    localStorage.removeItem(DRAFT);
    location.reload();
  } finally {
    // Announced even when refused, or one 409 leaves every event after it held
    // back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}



document.getElementById('save').onclick = save;
addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); save(); }
});

// One Save is one commit, so an unsaved draft is the only thing git cannot get
// back. It survives a closed tab and is dropped the moment it is committed.
BODY.addEventListener('input', () => localStorage.setItem(DRAFT, BODY.value));
const draft = localStorage.getItem(DRAFT);
if (draft !== null && draft !== BODY.value) {
  announce('unsaved draft restored');
  BODY.value = draft;
  show(true);
}
</script>{% endif %}
{% if not single %}<script>
// One page, hash-routed: a stable shareable link per entity without a file each.
// With no hash you get an index; with a hash you get exactly one document. Never
// every document at once — that is a wall of text, not a detail view.
function show() {
  const wanted = location.hash.slice(1);
  let found = false;
  for (const article of document.querySelectorAll('article.entity')) {
    const match = article.id === wanted;
    article.style.display = match ? '' : 'none';
    found = found || match;
  }
  document.querySelector('.toc').style.display = found ? 'none' : '';
  if (found) scrollTo(0, 0);
  // The width handle belongs to whichever document is on screen, and to no
  // document when the page is the index.
  place();
}
addEventListener('hashchange', show);
show();
</script>{% endif %}
"""

_DETAIL_STYLE = """
.tocgroup { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
            color: var(--muted); font-weight: 600; margin: 1.4rem 0 .3rem; }
.tocgroup .tally { font-weight: 400; letter-spacing: 0; }
.toc ul { margin: 0; }
/* Centred, and a container so the panes below can ask how wide the column
   actually is. It sat flush left with a full-height rule down its right edge,
   which on a wide screen is not a document — it is the left half of a two-pane
   layout whose right half failed to load. */
article.entity {
  width: var(--measure, 64rem); max-width: 100%; margin: 0 auto 3rem; position: relative;
  container-type: inline-size;
}
/* The facts beside the document rather than stacked on top of it: the reader
   comes for the shaping doc and glances at the facts, and a screen-and-a-half of
   metadata before the first sentence is the wrong way round. A container query
   and not a media query, because the width that decides this is the column's,
   which the reader sets with the grip — not the window's. */
.panes { display: grid; gap: 0 2.5rem; }
@container (min-width: 56rem) {
  /* 20rem and not less: these are the controls the entity is edited through, and
     a reviewers box too narrow to show three logins is a sidebar that looks
     tidier than the page it replaced and is worse to use. */
  .panes { grid-template-columns: minmax(0, 1fr) 20rem; align-items: start; }
  .panes > .main { grid-column: 1; grid-row: 1; }
  .panes > .facts { grid-column: 2; grid-row: 1; border-left: 1px solid var(--line);
                    padding-left: 1.5rem; }
  /* Half a sidebar is not two columns. Stacked, each fact is a caption over its
     value and reads down the edge of the page. */
  .panes > .facts dl { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .panes > .facts dt { padding-top: .7rem; }
  .panes > .facts dt:first-child { padding-top: 0; }
}
/* A handle, not a border. It was a full-height 2px rule in --line, which is
   exactly how a page draws the edge of a pane; this is a short grip that says
   what it is when you reach for it. */
#grip {
  position: fixed; top: 0; bottom: 0; width: 10px; cursor: col-resize; z-index: 30;
}
#grip::before {
  content: ""; position: absolute; left: 3px; right: 3px; top: 50%; height: 48px;
  transform: translateY(-50%); border-radius: 2px; background: var(--line-strong);
  opacity: .35; transition: opacity .15s, background .15s;
}
#grip:hover::before, #grip.dragging::before { opacity: 1; background: var(--accent); }
article.entity h1 { font-size: 1.5rem; margin: .2rem 0; }
.meta { color: var(--muted); margin-top: 0; display: flex; flex-wrap: wrap;
        gap: .4rem; align-items: baseline; }
.meta code { font-family: var(--font-mono); font-size: 12px; }
.back { margin: 0 0 .5rem; font-size: 12px; }
.editbar { display: flex; gap: .4rem; align-items: center; margin: .4rem 0 1rem; }
#state { color: var(--muted); font-size: 12px; }

dl { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: .45rem 1rem; margin: 1rem 0; }
dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
     padding-top: .35rem; }
dd { margin: 0; }
dt.derived, dd.derived { font-style: italic; }
/* Still italic, because it is still computed and typing over it would change
   nothing. Coloured, because it is the one computed line that is a problem. */
.overrun { color: var(--sev-warn); font-weight: 600; }
/* The marks belong to the form, so they are not on the page when there is no
   form on it — in read mode a row saying REQUIRED beside a filled-in value is
   an instruction with nothing to do. */
article.entity:not(.editing) .req { display: none; }
.problems { color: var(--warn); padding-left: 1.1rem; }

/* The two modes of the same rows. Controls are hidden until the article is
   editing, and the values they replace are hidden once it is. */
.field { display: none; }
.entity.editing .field { display: block; }
.entity.editing .field[hidden] { display: none; }
.bodybar { display: none; gap: .6rem; align-items: baseline; margin: 1rem 0 .3rem; }
.entity.editing .bodybar { display: flex; }
.editing-only { display: none; }
.entity.editing .editing-only { display: block; }
.entity.editing .read { display: none; }
.entity.editing dd .field[type=checkbox] { display: inline-block; }
label { display: block; }
/* Except in a fact list, where the label is one word in a line that also carries
   the REQUIRED mark. Block, the mark dropped onto a line of its own beside every
   gated field — an instruction shouting from its own row. */
dt > label { display: inline; }
/* The kind picker sits in the meta line, so it is a word in a sentence rather
   than a block that pushes the rest of the sentence onto its own row. */
.kindpick { display: inline; }
.kindpick select { font: inherit; }
input.field, select.field, textarea.field {
  width: 100%; box-sizing: border-box; font: inherit; padding: .25rem .4rem;
  border: 1px solid var(--line-strong); border-radius: 3px;
  background: var(--surface); color: inherit;
}
input.title-field { font-size: 1.4rem; font-weight: 600; margin-bottom: .6rem; }
textarea.body-field {
  min-height: 60vh; font-family: var(--font-mono);
  font-size: 13px; line-height: 1.55; resize: vertical;
}
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2); padding: 0 .25em; }
#conflict { border-left: 3px solid var(--danger); padding: .5rem .8rem; margin-top: 1rem;
            white-space: pre-wrap; font-size: 13px; }
"""


# What a person owns, in the order they think about it. Everything not named here
# is either derived (start, end, blocks, any rollup) or authoritative (id), and
# neither belongs in a form: a derived value typed by hand is a lie the next
# reschedule contradicts, and an edited id orphans the file from every reference.
EDITABLE: dict[str, str] = {
    "title": "text",
    "status": "status",
    "owner": "text",
    "assignees": "list",
    "reviewers": "list",
    "review_waived": "bool",
    "assigned_on": "date",
    "priority": "priority",
    "cycle": "number",
    "parent": "text",
    "depends_on": "list",
    "tags": "list",
    "prs": "list",
    "appetite_weeks": "number",
    "shaped_by": "text",
    "effort_weeks": "number",
}
STATUSES = ("shaping", "ready", "in_progress", "done", "shelved")
PRIORITIES = ("high", "medium", "low")

# The redundant channel. On the graph and the timeline a fill is the only thing
# telling two shapes apart, and a luminance ladder makes five fills *separable*
# without making any one of them *nameable* — you can see that a bar is darker
# than its neighbour and still not know which state that is. So every status also
# owns a mark that is not colour: drawn at a bar's left edge, prefixed to a node's
# title, and shown inside the legend swatch beside the word it stands for.
#
# All five are in the vendored face's latin subset, so a page that falls back to
# no webfont at all still draws five different shapes rather than five boxes.
# Chosen to be different SHAPES, not different weights of one shape: a small dot
# and a large dot are two glyphs a reader has to compare, which is the failure
# the ladder was already meant to fix.
STATUS_GLYPH = {
    "shaping": "?",              # still a question
    "ready": "»",           # queued at the gate
    "in_progress": "↑",     # under way
    "done": "•",            # solid, settled
    "shelved": "−",         # parked, nothing moving
}

def _required_at() -> dict[str, tuple[str, ...]]:
    """Which statuses demand each field, asked of the validator rather than copied.

    An HTML `required` attribute cannot express this: what a form must hold depends
    on the status chosen in that same form a moment ago. So the page carries the
    gates itself — and the previous version of this map carried them as "the first
    status that demands it", read cumulatively, which is not what the rules say.
    `_status_problems` is a chain of `elif`: `done` wants a PR and forgives the
    owner that `ready` insists on, deliberately, because migrated history often
    cannot name who owned something in 2025. Read cumulatively the form refused to
    create exactly the entity the server would have accepted.

    Derived by running the validator's own gate over a blank entity of each kind at
    each status and collecting the fields it names. It cannot drift from the rule
    it mirrors, because it *is* the rule. It is still only a courtesy: the server's
    answer is the truth, and `test_the_server_refusal_is_shown_and_not_swallowed`
    is what says so.
    """
    from .model import _status_problems

    gates: dict[str, list[str]] = {}
    for kind, model in (("project", Project), ("pitch", Pitch), ("task", Task)):
        for status in STATUSES:
            blank = model(id=f"{PREFIX[kind]}-000000", kind=kind, title="", status=status)
            for _, field, _, _ in _status_problems(blank):
                if field and status not in gates.setdefault(field, []):
                    gates[field].append(status)
    return {field: tuple(statuses) for field, statuses in gates.items()}


# Fields only one kind has, so the create form can hide the rest.
KIND_ONLY = {"appetite_weeks": "pitch", "shaped_by": "pitch", "effort_weeks": "task"}
PREFIX = {"project": "proj", "pitch": "pitch", "task": "task"}
REQUIRED_AT = _required_at()

# The reader's name for a field. `effort_weeks` and `appetite_weeks` are two
# storage fields holding one quantity, and calling it Effort here, Appetite on the
# detail page and weeks in the table made it look like three different numbers
# nobody could reconcile. Appetite is the domain's word and the spec's; the field
# names stay as they are, because those are what git holds.
LABELS = {
    "title": "Title", "status": "Status", "owner": "Owner", "assignees": "Assignees",
    "reviewers": "Reviewers", "review_waived": "Review waived", "assigned_on": "Assigned on",
    "priority": "Priority", "cycle": "Cycle", "parent": "Parent", "depends_on": "Blocked by",
    "tags": "Tags", "prs": "PRs", "appetite_weeks": "Appetite (weeks)",
    "shaped_by": "Shaped by", "effort_weeks": "Appetite (weeks)",
    # Not stored fields: a facet and a derived column. They are read by the same
    # people in the same control bar, so they take their words from here too.
    "kind": "Kind", "project": "Project", "size": "Appetite", "blocked_by": "Blockers",
    "start": "Start", "end": "End", "id": "Id", "predicate": "Flags",
    # The people page's own facet. Which hat somebody is wearing is not stored on
    # an entity at all — it is which field their name is in — but it is read in
    # the same control bar as the rest, so it takes its word from the same map.
    "role": "Role",
}

# The reader's word for a value. `in_progress`, `missing_required_fields` and
# `overruns_cycle` are identifiers: they belong in a `value=`, a class and a
# `data-*` attribute, and nowhere a person reads. One map rather than one per
# page, because five pages inventing their own is how `in_progress` became
# "In progress", "in progress" and "in_progress" on the same screen.
#
# Statuses, priorities, kinds and predicates share it: their identifiers do not
# collide, and a caller rendering an option has no reason to know which family a
# value came from. Anything unknown comes back unchanged, so a value added to the
# model still renders — badly, but it renders.
HUMAN = {
    # statuses
    "shaping": "Shaping",
    "ready": "Ready",
    "in_progress": "In progress",
    "done": "Done",
    "shelved": "Shelved",
    # priorities
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    # kinds
    "project": "Project",
    "pitch": "Pitch",
    "task": "Task",
    # predicates, as COMPUTED_PREDICATES spells them. `missing_required_fields`
    # is not what it does — it matches any problem of any severity — so it says so.
    "blocked": "Blocked",
    "unblocked": "Not blocked",
    "overruns_cycle": "Overruns its cycle",
    "missing_required_fields": "Has a problem",
    "has_blocker": "Has a blocking problem",
    "review_waived": "Review waived",
    # roles, which the people page filters by. Already English, but a dropdown
    # reading "owner, Pitch, Ready" is three labelling conventions in one bar.
    "owner": "Owner",
    "assignee": "Assignee",
    "reviewer": "Reviewer",
    "shaper": "Shaper",
}


def _human(value: object) -> str:
    """The word a reader gets for an identifier the data model uses."""
    if value is None:
        return ""
    return HUMAN.get(str(value), str(value))


# Available to every template as both `human(x)` and `x|human`, so no page has to
# be handed the map, and as `label(field)` for a field name.
_ENV.globals["human"] = _human
_ENV.filters["human"] = _human
# The mark that says the same thing the colour says, for every legend and every
# shape that draws one. Unknown values get nothing rather than a box glyph.
_ENV.globals["glyph"] = lambda status: STATUS_GLYPH.get(str(status), "")
_ENV.globals["label"] = lambda field: LABELS.get(field, field)
# Fields that name a person. They get a datalist of everyone already in the corpus,
# so a typo shows up as "not in the list" rather than as a reviewer who does not exist.
PEOPLE_FIELDS = ("owner", "assignees", "reviewers", "shaped_by")
# Which suggestion list each field draws from. A datalist only completes a whole
# value, so the comma-separated ones also get an "add" picker that appends a token
# — otherwise the suggestions are useless the moment there is more than one name.
SUGGESTS = {
    "owner": "people", "assignees": "people", "reviewers": "people", "shaped_by": "people",
    "parent": "entities", "depends_on": "entities", "tags": "tags", "prs": "prs",
    # A cycle number is a reference too. Typed from memory it is off by one as
    # often as it is right, and an entity bet into a cycle nobody has named is
    # weeks that never appear on anybody's capacity.
    "cycle": "cycles",
}


def _editable_for(entity: Entity, prefix: str = "field") -> list[dict]:
    """The fields this kind actually has, with the type a form must coerce back to.

    The prefix is what makes a control's id unique on the page it lands on: the
    static detail export holds every entity in one file, so `owner` alone would
    be the same id sixteen times over and every `<label for>` on the page would
    point at the first of them.
    """
    return [
        {
            "name": name,
            "id": f"{prefix}-{name}",
            "type": kind,
            "value": getattr(entity, name),
            "gates": REQUIRED_AT.get(name, ()),
            "list": SUGGESTS.get(name),
            "text": ", ".join(str(v) for v in getattr(entity, name))
            if kind == "list"
            else ("" if getattr(entity, name) is None else getattr(entity, name)),
        }
        for name, kind in EDITABLE.items()
        if name in type(entity).model_fields
    ]


def _links(ids: list[str], index: Index, links: Links = STATIC) -> str:
    return ", ".join(
        f'<a href="{links.entity}{i}">'
        f"{index.entities[i].title if i in index.entities else i}</a>"
        for i in ids
    )


def _fact_rows(index: Index, entity: Entity, links: Links) -> list[dict]:
    """The rows of the facts list, each carrying both how it reads and how it edits.

    One row per fact, not two lists: the edit view is the read view with the values
    swapped for controls, so nothing is ever shown twice and the layout does not
    move when you press Edit.
    """
    span = index.spans.get(entity.id)
    why = index.explanations.get(entity.id)
    rows = []
    # One mark for "there is nothing here", everywhere. Spelled-out words —
    # `nothing`, `none`, `no` — sit at the same weight as a real value and have
    # to be read before you know the row is empty; a dash is empty at a glance.
    empty = '<span class="empty">—</span>'
    for field in _editable_for(entity, entity.id):
        name = field["name"]
        if name == "title":
            continue
        if name == "depends_on":
            display = _links(index.blocked_by[entity.id], index, links) or empty
        elif name == "parent":
            # By title and linked, the way blockers already read. An id is what
            # the field stores; it is not what anybody is looking for when they
            # ask what this belongs to.
            display = _links([entity.parent], index, links) if entity.parent else empty
        elif name == "prs":
            display = ", ".join(_pr_link(ref) for ref in entity.prs) or empty
        elif name == "review_waived":
            display = "waived" if entity.review_waived else empty
        elif name == "status":
            # The same chip the table, the people page and the bet table wear. A
            # status is the one field on this page every other view colours.
            display = f'<span class="chip st-{entity.status}">{_human(entity.status)}</span>'
        elif name == "priority":
            display = _human(entity.priority)
        elif field["type"] == "list":
            display = field["text"] or empty
        else:
            display = str(field["text"]) if field["text"] not in ("", None) else empty
        rows.append(
            {
                "label": LABELS.get(name, name),
                # What the `<dt>`'s label points at. The derived rows below have
                # no control, so they get no label — a `for` naming nothing is a
                # label the reader is told about and cannot reach.
                "for": field["id"],
                "display": display,
                "control": _control_html(field),
                "gates": field["gates"],
                "derived": False,
                # "Review waived: no" is a line that says nothing. The row still
                # exists while editing, because turning the waiver on is the whole
                # point of having it; it just does not clutter the read view.
                "editing_only": name == "review_waived" and not entity.review_waived,
            }
        )
    # The one derived line on the page that is a decision and not a fact. It wore
    # the same muted italic as every other computed value, so the sentence that
    # says this bet does not fit read exactly like the sentence saying when it
    # starts. It keeps the italic — it is still computed, and pretending otherwise
    # would invite somebody to edit it — and gains the warning colour on top.
    overrun = (
        f' · <span class="overrun"><span class="sev-mark sev-mark-warn"'
        f' aria-hidden="true">▲</span> overruns cycle {entity.cycle}'
        f" by {span.overruns_cycle_weeks:.1f} weeks</span>"
        if span and span.overruns_cycle_weeks
        else ""
    )
    rows.append(
        {
            "label": "Scheduled",
            "for": "",
            "display": (f"{span.start} → {span.end}{overrun}" if span else empty),
            "control": "",
            "gates": (),
            "derived": True,
            "editing_only": False,
        }
    )
    if why:
        rows.append(
            {
                "label": "Why then",
                "for": "",
                "display": why.text,
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    rows.append(
        {
            "label": "Blocks",
            "for": "",
            "display": _links(index.blocks[entity.id], index, links) or empty,
            "control": "",
            "gates": (),
            "derived": True,
            "editing_only": False,
        }
    )
    return rows


def _detail_rows(index: Index, links: Links = STATIC) -> list[dict]:
    rows = []
    for entity_id, entity in sorted(index.entities.items()):
        span = index.spans.get(entity_id)
        why = index.explanations.get(entity_id)
        size, defaulted = size_weeks(entity, Config(default_task_effort=index.default_task_effort))
        rows.append(
            {
                "id": entity_id,
                "title": entity.title,
                "kind": entity.kind,
                "status": entity.status,
                "parent": entity.parent,
                "owner": entity.owner,
                "reviewers": entity.reviewers,
                "review_waived": entity.review_waived,
                "size_label": "Appetite",
                "size": f"{size:g} weeks" + (" (assumed)" if defaulted else ""),
                "assigned_on": entity.assigned_on,
                "cycle": entity.cycle,
                "span": f"{span.start} → {span.end}" if span else "—",
                "overrun": (
                    f"overruns cycle {entity.cycle} by {span.overruns_cycle_weeks:.1f} weeks"
                    if span and span.overruns_cycle_weeks
                    else ""
                ),
                "why": why.text if why else "",
                "blocked_by": _links(index.blocked_by[entity_id], index),
                "blocks": _links(index.blocks[entity_id], index),
                "parent_link": _links([entity.parent], index, links) if entity.parent else "",
                "prs": ", ".join(_pr_link(ref) for ref in entity.prs),
                "tags": entity.tags,
                "problems": [p.message for p in index.problems if p.entity_id == entity_id],
                "body": _body_html(entity, links),
            }
        )
    return rows


KINDS = ("project", "pitch", "task")


def _new_rows() -> list[dict]:
    """One row per field any kind has, each saying which kinds have it.

    The union rather than one kind's worth, because the page carries all three and
    hides what does not apply. Rendering only the chosen kind meant switching kind
    was a fresh page, and a title typed before switching was gone.
    """
    rows: dict[str, dict] = {}
    for kind in KINDS:
        blank = {"project": Project, "pitch": Pitch, "task": Task}[kind](
            id=f"{PREFIX[kind]}-000000",
            kind=kind,
            title="",
            # Today, because a date field that starts empty is a date field
            # somebody leaves empty. This is a blank; nothing is overwritten.
            assigned_on=date.today(),
        )
        # One form on the page, so one prefix. The detail page's is the entity's
        # id, because that page can hold sixteen of them at once.
        for field in _editable_for(blank, "new"):
            if field["name"] == "title":
                continue          # the title is the heading, not a row
            row = rows.setdefault(
                field["name"],
                {"label": LABELS.get(field["name"], field["name"]), "for": field["id"],
                 "control": _control_html(field), "gates": field["gates"], "kinds": []},
            )
            row["kinds"].append(kind)
    return [{**row, "kinds": " ".join(row["kinds"])} for row in rows.values()]


def render_new(
    kind: str, base_commit: str, links: Links = ROUTES, index: Index | None = None
) -> str:
    """The create page, which is the detail page in edit mode with nothing in it.

    A second, differently-shaped form for creating was the thing that made the
    tool feel like two tools, so this is the same markup, the same controls and
    the same stylesheet — a blank entity rather than a stored one.
    """
    body = _ENV.from_string(_NEW).render(
        kind=kind,
        kinds=KINDS,
        rows=_new_rows(),
        base_commit=base_commit,
        links=links,
        combobox=_combobox_html(index),
        required=_REQUIRED_JS,
    )
    return _page(f"openproj — new {kind}", body, _DETAIL_STYLE + _SUGGEST_STYLE, links)


def _pr_sort(ref: str) -> tuple[str, int]:
    """Newest first within a repository. A PR number is a number, and sorting the
    references as text puts #999 above #1400."""
    repo, _, number = ref.partition("#")
    return repo, int(number) if number.isdigit() else 0


def _suggestions(index: Index) -> dict:
    """What already exists, offered rather than remembered.

    A reviewer who is not in this list is a typo far more often than a new
    colleague, and an id typed from memory is a dangling reference the validator
    will reject after the save rather than before it.
    """
    people: set[str] = set()
    tags: set[str] = set()
    for entity in index.entities.values():
        for name in PEOPLE_FIELDS:
            value = getattr(entity, name, None)
            people.update(value if isinstance(value, list) else [value] if value else [])
        tags.update(entity.tags)
    # A login has no comma and no space in it. An early version of the table wrote
    # a whole comma-separated string into a list field, and the picker then offered
    # "jcanton, halungge" as if it were one person — garbage in the corpus became
    # garbage suggested to the next person, which is how it spreads.
    people = {p for p in people if p and "," not in p and " " not in p}
    tags = {g for g in tags if g and "," not in g}
    # {value, label}: the value is what gets written to the file, the label is the
    # human hint beside it. An id typed from memory is a dangling reference the
    # validator rejects after the save; offered, it cannot be mistyped at all.
    # Two kinds of entry for one field. A whole reference completes a PR already
    # cited somewhere in the plan; a bare `org/repo#` completes the half nobody
    # remembers — which org, and whether it is icon4py or icon4pygen — and leaves
    # the number to be typed. Everything here comes from the corpus, so it costs
    # no network and cannot be stale in a way the plan is not already stale.
    refs = {ref for entity in index.entities.values() for ref in entity.prs}
    repos = {ref.split("#")[0] + "#" for ref in refs if "#" in ref}
    return {
        "prs": (
            [{"value": r, "label": "any pull request"} for r in sorted(repos)]
            + [
                {"value": r, "label": ""}
                for r in sorted(refs, key=_pr_sort, reverse=True)
            ]
        ),
        "people": [{"value": p, "label": ""} for p in sorted(people)],
        "entities": [
            {"value": i, "label": e.title} for i, e in sorted(index.entities.items())
        ],
        "tags": [{"value": t, "label": ""} for t in sorted(tags)],
        # Newest first: the cycle being bet into is nearly always the highest
        # number, and the label is the window, because 37 means nothing and
        # "2026-08-24 → 2026-10-04" is the thing being agreed to.
        "cycles": [
            {
                "value": str(number),
                "label": (
                    f"{index.cycles[number][0]} → {index.cycles[number][1]}"
                    if number in index.cycles
                    else "no dates"
                ),
            }
            for number in sorted(_cycle_numbers(index), reverse=True)
        ],
    }


_CYCLE = """
<p class="editbar">
  <a href="{{ links.cycles }}">← all cycles</a>
</p>
<h1>Cycle {{ c.number }}</h1>
{% if c.recorded %}
<p class="meta">{{ c.starts_on }} → builds until <b>{{ c.builds_until }}</b>
   → cool-down ends {{ c.ends_on }}</p>
{% else %}
<p class="meta">No record yet{% if c.dated %} — config/cycles.yaml puts this cycle at
   {{ c.starts_on }} → {{ c.ends_on }}{% endif %}. Nothing holds these weeks: what is
   below is the record Save would write.</p>
{% endif %}

{#- Three boxes that decide when the cycle runs and how long for, and not one of
    them had a name: the word beside each is a `<dt>`, which is a caption to a
    reader and nothing to the accessibility tree. -#}
<form id="setup" onsubmit="return false">
  <dl id="facts">
    <dt><label for="starts_on">Starts on</label></dt>
    <dd><span class="read">{{ c.starts_on }}</span>
        <input type="date" id="starts_on" name="starts_on" data-type="date"
               value="{{ c.starts_on }}" class="field"></dd>
    <dt><label for="build_weeks">Build weeks</label></dt>
    <dd><span class="read">{{ c.build_weeks }}</span>
        <input id="build_weeks" name="build_weeks" data-type="number"
               value="{{ c.build_weeks }}" class="field"></dd>
    <dt><label for="cooldown_weeks">Cool-down weeks</label></dt>
    <dd><span class="read">{{ c.cooldown_weeks }}</span>
        <input id="cooldown_weeks" name="cooldown_weeks" data-type="number"
               value="{{ c.cooldown_weeks }}" class="field"></dd>
  </dl>
</form>

<h2>Who is in this cycle</h2>
<p class="hint">Availability is a fraction of the {{ c.build_weeks }} build weeks.
  Only the people named here are in the cycle.</p>
<table class="load"><thead><tr>
  <th></th><th>person</th><th>available</th><th>capacity</th><th>bet</th><th>load</th>
  <th>scheduled until</th></tr></thead>
<tbody id="roster">
  {% for row in c.people %}
  <tr data-login="{{ row.login }}" data-held="{{ row.held }}"
      class="{{ 'over' if row.over else '' }}">
    {% if editable %}<td class="dropcell"><button type="button" class="drop"
      title="Take {{ row.login }} out of this cycle"
      aria-label="Take {{ row.login }} out of this cycle">&#128465;</button><span
      class="confirm" hidden>out?<button type="button" class="yes">yes</button><button
      type="button" class="no">no</button></span></td>{% else %}<td></td>{% endif %}
    <td>{{ row.login }}</td>
    <td><span class="read">{{ (row.rate * 100)|round|int }}%</span>
        <input class="field rate" data-login="{{ row.login }}" value="{{ row.rate }}"
               aria-label="{{ row.login }} availability" autocomplete="off"></td>
    <td class="derived capacity">{{ '%.1f'|format(row.capacity) }} wk</td>
    <td class="derived">{{ '%.1f'|format(row.held) }} wk</td>
    <td><span class="bar"><span style="width: {{ row.percent }}%"></span></span></td>
    <td class="derived">{{ row.until }}</td>
  </tr>
  {% endfor %}
</tbody></table>
{% if editable %}
<p class="editbar"><label for="joining" class="hint">add somebody</label>
   <input id="joining" placeholder="login" data-suggest="people" autocomplete="off">
   <button type="button" id="add">+ add to the cycle</button>
   <span class="hint">added here, saved with the setup</span></p>
{% endif %}
{% if c.strangers %}
<p class="problems" id="strangers">Bet into this cycle but not in it:
  {{ c.strangers|join(', ') }}. Their work still counts against the plan; add them
  or take the work out.</p>
{% endif %}
<p class="problems" id="over" {{ '' if c.over else 'hidden' }}>Over capacity:
  {{ c.over|join(', ') }}. The room can still bet it — this is a number, not a
  refusal.</p>

<h2>The bet</h2>
<p class="hint">Everything ready or in progress. Ticking one stamps it with cycle
  {{ c.number }}; an item already in progress from an earlier cycle keeps the cycle it
  was bet in, so its overrun keeps counting.</p>
<div class="table-scroll"><table id="bets" autocomplete="off"><thead><tr>
  <th>in {{ c.number }}</th><th>title</th><th>kind</th><th>status</th>
  <th>appetite</th><th>assignees</th><th>reviewers</th><th>bet in</th>
</tr></thead><tbody>
  {#- Every box in this table is named after the row it is in, not after its
      column. A column header names a cell to somebody reading down the page; to
      a reader who arrives at one control out of four hundred, "appetite" without
      "for what" is not a name. -#}
  {% for row in c.candidates %}
  <tr data-id="{{ row.id }}" class="{{ 'carried' if row.carried else '' }}">
    <td><input type="checkbox" class="bet" autocomplete="off"
               aria-label="Bet {{ row.title }} into cycle {{ c.number }}"
               {{ 'checked' if row.in_cycle else '' }}
               {{ 'disabled' if row.carried else '' }}></td>
    <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
    <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
    <td><span class="chip st-{{ row.status }}">{{ row.status|human }}</span></td>
    <td><input class="live" data-field="{{ row.size_field }}" data-type="number"
               aria-label="{{ row.title }} appetite in weeks"
               autocomplete="off" value="{{ row.size }}"
               placeholder="{{ row.size_hint }}"></td>
    <td><input class="live wide" data-field="assignees" data-type="list"
               aria-label="{{ row.title }} assignees"
               data-suggest="people" autocomplete="off" value="{{ row.assignees }}"></td>
    <td><input class="live wide" data-field="reviewers" data-type="list"
               aria-label="{{ row.title }} reviewers"
               data-suggest="people" autocomplete="off" value="{{ row.reviewers }}"></td>
    <td class="derived">{{ row.cycle }}</td>
  </tr>
  {% endfor %}
</tbody></table></div>
<div class="doc">{{ c.body|safe }}</div>
{% if editable %}
<div class="commitbar" id="commitbar">
  <span id="unsaved">Nothing to save</span>
  <button type="button" id="save" disabled>Save</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</div>
{{ combobox|safe }}
<script>
const BASE = document.getElementById('base');
const BAR = document.getElementById('commitbar');
const UNSAVED = document.getElementById('unsaved');
const NUMBER = {{ c.number }};
// What is on this page, so the shell's banner can tell a write that lands here
// from one that lands somewhere else. The cycle record and every entity that can
// be bet into it: those are the ids the server announces.
window.SHOWING = ['cycle-' + NUMBER].concat(
  [...document.querySelectorAll('#bets tbody tr')].map(tr => tr.dataset.id));

// Through the shell's live region, which is what puts it in `#state` as well.
// A receipt that is only drawn is a save nobody is told landed.
function say(message) { announce(message); }

async function put(fields) {
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/cycle/${NUMBER}`, {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
    });
    const answer = await response.json();
    if (!response.ok) { say(answer.detail || 'refused'); return null; }
    committed = answer.commit;
    BASE.value = answer.commit || BASE.value;
    return answer;
  } finally {
    // Announced even when the write was refused, or one refusal leaves every
    // later event held back and the shell's banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

const SAVE = document.getElementById('save');
let ROSTER_DIRTY = false;

// The receipt has to outlive the reload that proves it. Saving reloads, because
// half the numbers on this page — capacity, load, the scheduled-until column —
// are derived from what was just written; a confirmation that only lived in the
// DOM would be thrown away by the very thing it is confirming.
const RECEIPT = 'openproj:cycle-saved';
let receipt = '';

try {
  const landed = sessionStorage.getItem(RECEIPT);
  if (landed) { say(landed); sessionStorage.removeItem(RECEIPT); }
} catch (e) { /* the save still landed; only the sentence about it is missing */ }

// The whole roster in one write. A name left out means somebody was taken off,
// which per-field merging would silently undo.
async function saveSetup() {
  const setup = document.getElementById('setup');
  const availability = {};
  for (const input of document.querySelectorAll('input.rate')) {
    const rate = Number(input.value);
    if (rate > 0) availability[input.dataset.login] = rate;
  }
  const fields = {
    starts_on: setup.querySelector('[name=starts_on]').value,
    build_weeks: Number(setup.querySelector('[name=build_weeks]').value),
    cooldown_weeks: Number(setup.querySelector('[name=cooldown_weeks]').value),
    availability,
  };
  if (!(await put(fields))) return false;
  ROSTER_DIRTY = false;
  return true;
}

// Ticking is a write to the ENTITY, not to the cycle: `cycle` lives on the thing
// being bet, and one row is one commit so a half-finished betting table is still
// a readable history rather than one commit nobody can unpick.
for (const box of document.querySelectorAll('input.bet')) {
  box.onchange = () => {
    const row = box.closest('tr');
    pend(row.dataset.id, 'cycle', box.checked ? NUMBER : null);
    row.querySelector('td:last-child').textContent = box.checked ? NUMBER : '—';
  };
}

// Nothing is written until Save. A betting table is a conversation — a row gets
// staffed, argued about and restaffed inside a minute — and one commit per
// keystroke turns that into a git history nobody can read and a plan that is
// briefly wrong in public between two halves of one decision.
const PENDING = new Map();   // entity id -> {field: value}

function pend(id, field, value) {
  PENDING.set(id, {...(PENDING.get(id) || {}), [field]: value});
  // A new edit makes the last receipt untrue: "saved 3" sitting beside "2
  // unsaved changes" reads as though the three came back.
  say('');
  mark();
}

function mark() {
  // Counted in edits rather than in commits: two fields on one row is two things
  // somebody changed, even though it is one write.
  let edits = ROSTER_DIRTY ? 1 : 0;
  for (const fields of PENDING.values()) edits += Object.keys(fields).length;
  SAVE.disabled = edits === 0;
  SAVE.textContent = edits ? `Save ${edits} change${edits === 1 ? '' : 's'}` : 'Save';
  // Said in words next to the button rather than only by the button's own
  // label, because the label is what will happen and this is what is true now.
  UNSAVED.textContent = edits
    ? `${edits} unsaved change${edits === 1 ? '' : 's'}` : 'Nothing to save';
  BAR.classList.toggle('dirty', edits > 0);
  for (const tr of document.querySelectorAll('#bets tbody tr'))
    tr.classList.toggle('pending', PENDING.has(tr.dataset.id));
}

// The browser's own warning, which is the only one that can stop a tab closing.
addEventListener('beforeunload', event => {
  if (!PENDING.size && !ROSTER_DIRTY) return;
  event.preventDefault();
  event.returnValue = '';
});

async function flush(quiet) {
  if (!PENDING.size && !ROSTER_DIRTY) return true;
  SAVE.disabled = true;
  // Counted in edits, the unit `mark()` counts, and not in commits. Two fields on
  // one row is one write, so counting writes said "2 unsaved changes" and then
  // "Saved 1 change" about the same two edits — and a save you have to reconcile
  // against its own receipt is a save you do not believe.
  let saved = 0;
  if (ROSTER_DIRTY) {
    if (!(await saveSetup())) { mark(); return false; }
    saved += 1;      // the whole roster is one edit to `mark()` too
  }
  // One entity per commit, each against the commit the last one returned: a
  // batch that fails half way is still a readable history rather than one commit
  // nobody can unpick.
  for (const [id, fields] of [...PENDING]) {
    dispatchEvent(new Event('openproj:writing'));
    let committed = null;
    try {
      const response = await fetch(`/api/entity/${id}`, {
        method: 'PATCH', headers: {'content-type': 'application/json'},
        body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
      });
      const answer = await response.json();
      if (!response.ok) {
        say(`${id}: ${answer.detail
              || (answer.problems || []).map(p => p.message).join('; ') || 'refused'}`
            + (saved ? ` — ${saved} already saved` : ''));
        mark();
        return false;
      }
      committed = answer.commit;
      BASE.value = answer.commit || BASE.value;
      PENDING.delete(id);
      saved += Object.keys(fields).length;
    } finally {
      dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
    }
  }
  mark();
  receipt = `${quiet ? 'Autosaved' : 'Saved'} ${saved} change${saved === 1 ? '' : 's'}`;
  say(receipt);
  return true;
}

SAVE.onclick = async () => {
  if (await flush(false)) {
    // Reloaded because capacity, load and the scheduled-until column are all
    // derived from what was just written, and the receipt is handed across the
    // reload so that pressing Save says something rather than blinking.
    try { sessionStorage.setItem(RECEIPT, receipt); } catch (e) { /* still saved */ }
    location.reload();
  }
};

// Every two minutes, so a dropped connection or a closed laptop costs the last
// two minutes rather than the whole meeting. Quiet when there is nothing to say.
setInterval(() => { if (PENDING.size || ROSTER_DIRTY) flush(true); }, 120000);

// Every editable cell is an input already: a betting table is filled in, not
// inspected, and a double-click to reach a field somebody is about to type in is
// a step that only exists because the table also had to be readable.
for (const input of document.querySelectorAll('#bets input.live')) {
  if (input.dataset.suggest) attachSuggest(input);
  let was = input.value;
  // Saving on blur alone is not safe when the field is already an input: the
  // browser restores form values across a reload, autofills, and the picker
  // rewrites the field to add a separator — none of which is a person deciding
  // something. A cell is only staged if somebody typed in it or picked from it,
  // which is what an `input` event means.
  let edited = false;
  input.addEventListener('input', () => { edited = true; });
  input.onkeydown = event => {
    if (event.key === 'Escape') { input.value = was; edited = false; input.blur(); }
    if (event.key === 'Enter') input.blur();
  };
  input.onblur = () => {
    const value = input.value.trim();
    if (!edited || value === was.trim()) { edited = false; return; }
    const id = input.closest('tr').dataset.id;
    const field = input.dataset.field;
    let staged;
    if (input.dataset.type === 'list') {
      staged = value ? [...new Set(value.split(',').map(s => s.trim()).filter(Boolean))] : [];
    } else if (value === '') {
      staged = null;
    } else if (Number.isNaN(Number(value))) {
      say(`${field} must be a number, not "${value}"`);
      input.value = was;
      edited = false;
      return;
    } else {
      staged = Number(value);
    }
    was = input.value;
    edited = false;
    pend(id, field, staged);
  };
}

// Capacity is what a rate BUYS, so it has to move while the rate is being typed.
// Left to the next page load, the number somebody is setting is invisible at the
// moment they are setting it — which is most of the moment that matters.
function recount() {
  const build = Number(document.querySelector('[name=build_weeks]').value) || 0;
  const over = [];
  for (const row of document.querySelectorAll('#roster tr')) {
    const rate = Number(row.querySelector('input.rate').value) || 0;
    const held = Number(row.dataset.held) || 0;
    const capacity = rate * build;
    row.querySelector('.capacity').textContent = capacity.toFixed(1) + ' wk';
    row.querySelector('.bar > span').style.width =
      capacity ? Math.min(100, Math.round(100 * held / capacity)) + '%' : '0%';
    row.classList.toggle('over', capacity > 0 && held > capacity);
    if (capacity > 0 && held > capacity) over.push(row.dataset.login);
  }
  const line = document.getElementById('over');
  if (line) {
    line.hidden = !over.length;
    line.textContent = over.length
      ? `Over capacity: ${over.join(', ')}. The room can still bet it — this is a `
        + 'number, not a refusal.'
      : '';
  }
}
document.addEventListener('input', event => {
  if (event.target.matches('input.rate, [name=build_weeks]')) recount();
  if (event.target.closest('#setup') || event.target.matches('input.rate')) dirty();
});

function dirty() {
  ROSTER_DIRTY = true;
  mark();
}

// The roster is edited in the page and written by Save, so adding somebody and
// setting their availability is one decision and one commit rather than two.
const HELD = HELD_JSON;
const JOINING = document.getElementById('joining');
if (JOINING) attachSuggest(JOINING);

// Two clicks, and the second one answers a question rather than repeating the
// gesture that asked it. Taking somebody out of a cycle takes their capacity out
// with them, and the glyph that did it was one unlabelled pixel target away from
// the availability field next to it.
function dropRow(button) {
  const cell = button.closest('td');
  const asking = cell.querySelector('.confirm');
  button.onclick = () => { button.hidden = true; asking.hidden = false; };
  asking.querySelector('.no').onclick = () => { asking.hidden = true; button.hidden = false; };
  asking.querySelector('.yes').onclick = () => {
    const row = button.closest('tr');
    say(`${row.dataset.login} taken out — Save writes it`);
    row.remove();
    recount();
    dirty();
  };
}
document.querySelectorAll('#roster .drop').forEach(dropRow);

// The same cell the roster loop above renders. Kept as one string rather than
// built up, so that the two copies of it can be read against each other; a test
// asserts both carry the name and the question.
function dropCell(login) {
  return `<td class="dropcell"><button type="button" class="drop"`
    + ` title="Take ${login} out of this cycle"`
    + ` aria-label="Take ${login} out of this cycle">&#128465;</button>`
    + `<span class="confirm" hidden>out?<button type="button" class="yes">yes</button>`
    + `<button type="button" class="no">no</button></span></td>`;
}

document.getElementById('add').onclick = () => {
  const login = JOINING.value.trim().replace(/,$/, '');
  if (!login) return;
  if (document.querySelector(`#roster tr[data-login="${login}"]`)) {
    say(`${login} is already in this cycle`);
    return;
  }
  const row = document.createElement('tr');
  row.dataset.login = login;
  // Somebody added to the cycle may already be bet into it — that is exactly why
  // the page named them below the table. Their load comes with them.
  row.dataset.held = (HELD[login] || 0);
  row.innerHTML = dropCell(login)
    + `<td>${login}</td>`
    + `<td><input class="field rate" data-login="${login}" value="1.0"`
    + ` aria-label="${login} availability" autocomplete="off"></td>`
    + `<td class="derived capacity">—</td>`
    + `<td class="derived">${(HELD[login] || 0).toFixed(1)} wk</td>`
    + `<td><span class="bar"><span style="width: 0%"></span></span></td>`
    + `<td class="derived">—</td>`;
  document.getElementById('roster').append(row);
  dropRow(row.querySelector('.drop'));
  JOINING.value = '';
  recount();
  dirty();
  say(`${login} added — Save writes it`);
};
</script>
{% endif %}
"""

_CYCLE_STYLE = """
/* .commitbar, #unsaved and #save are the shell's: the cycle page was the first
   to need a bar that says whether the page is saved, and then the detail page
   and the create page needed the same one. */
/* A destructive control asks before it acts, and the question replaces the
   glyph rather than appearing beside it, so the row does not jump. */
.confirm { font-size: 12px; color: var(--warn); }
td .confirm { white-space: nowrap; }
.confirm button { font: inherit; font-size: 12px; margin-left: .25rem;
                  padding: 0 .35rem; border-radius: 2px;
                  border: 1px solid var(--line-strong); background: var(--surface);
                  color: var(--fg); cursor: pointer; }
.confirm button.yes { border-color: var(--danger); color: var(--danger); }
#setup .field, table.load .field { display: inline-block; }
#setup .field { width: 12rem; }
#setup .read, table.load .read { display: none; }
table.load { border-collapse: collapse; font-size: 13px; margin: .5rem 0 1rem; }
table.load th, table.load td {
  border-bottom: 1px solid var(--line); padding: .3rem .6rem; text-align: left;
}
table.load th { color: var(--muted); font-weight: 400; font-size: 11px;
                text-transform: uppercase; letter-spacing: .04em; }
tr.over td { color: var(--danger); }
input.rate { width: 4rem; }
#bets input.live { font: inherit; font-size: 13px; width: 5rem;
                   background: var(--surface); color: inherit;
                   border: 1px solid transparent; border-radius: 3px; padding: .1rem .3rem; }
#bets input.live.wide { width: 11rem; }
#bets input.live:hover { border-color: var(--line); }
/* The border is the hover affordance, not the focus one. Suppressing the outline
   here left the only keyboard-reachable cell on the page with nothing to say it
   had focus; the shell's :focus-visible ring draws it now. */
#bets input.live:focus { border-color: var(--accent); }
#bets td { position: relative; }
button.drop { border: none; background: none; cursor: pointer; padding: 0 .2rem;
              color: var(--muted); font-size: 13px; line-height: 1; }
button.drop:hover { color: var(--danger); }
#joining { font: inherit; font-size: 13px; width: 10rem; }
#bets { border-collapse: collapse; width: 100%; font-size: 13px; }
#bets th, #bets td { border-bottom: 1px solid var(--line); padding: .3rem .5rem;
                     text-align: left; }
#bets th { color: var(--muted); font-weight: 400; font-size: 11px;
           text-transform: uppercase; letter-spacing: .04em; }
tr.carried td { color: var(--muted); }
#bets tr.pending td { box-shadow: inset 3px 0 0 -1px var(--accent); }
#bets tr.pending td:first-child { box-shadow: inset 3px 0 0 0 var(--accent); }

/* The cycles index. One card per cycle, and the sentence the method turns on —
   this much bet, that much to bet with — is the largest thing on it. */
.cards { list-style: none; margin: 1rem 0 0; padding: 0; display: grid; gap: .75rem;
         grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); }
.card { border: 1px solid var(--line); border-radius: 3px; padding: .6rem .8rem;
        background: var(--surface); }
.card h2 { font-size: 1.05rem; margin: 0; }
.card .window { color: var(--muted); font-size: 12px; margin: .1rem 0 .5rem; }
.card .bet { margin: 0 0 .35rem; font-size: 13px; }
.card .bet b { font-size: 1.15rem; font-variant-numeric: tabular-nums; }
.card span.bar { display: block; width: 100%; height: 10px; }
.card.over .bet b { color: var(--danger); }
.card .note { margin: .35rem 0 0; }
/* The create form is not another cycle in the list, and it writes a record. The
   rule and the heading are what say so before the button does. */
#create { border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1rem; }
#create h2 { font-size: 1.05rem; margin: 0 0 .2rem; }
#start { font: inherit; font-size: 13px; padding: .25rem .8rem; border-radius: 2px;
         border: 1px solid var(--accent); background: var(--surface);
         color: var(--accent); cursor: pointer; }
#confirm { margin: .6rem 0 0; font-size: 13px; }
"""

_CYCLES = """
<h1>Cycles</h1>
<p class="hint">Every cycle the plan names — the ones with a record, the ones
  config/cycles.yaml dates, and the ones something has been bet into. A cycle sets
  the build and cool-down weeks and who is available for it.</p>
{% if cycles %}
<ul class="cards">
  {#- A link only where the page it opens exists. `render_static` writes six
      files and none of them is a cycle, so on a rendered plan every one of these
      headings was an anchor to a fragment that is not on the page — a control
      that does nothing, which is how a reader learns to stop pressing them. -#}
  {% for c in cycles %}
  <li class="card{{ ' over' if c.over else '' }}">
    <h2>{% if per_cycle_page %}<a href="{{ links.cycle }}{{ c.number }}">Cycle {{ c.number
      }}</a>{% else %}Cycle {{ c.number }}{% endif %}</h2>
    <p class="window">{% if c.recorded %}{{ c.starts_on }} → builds until
      {{ c.builds_until }}{% elif c.starts_on %}{{ c.starts_on }} → {{ c.ends_on }}
      {% else %}no dates{% endif %}
      · {{ c.people }} {{ 'person' if c.people == 1 else 'people' }}</p>
    {% if c.recorded %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> of
      <b class="num">{{ '%.1f'|format(c.capacity) }}</b> weeks bet</p>
    <span class="bar"><span style="width: {{ c.percent }}%"></span></span>
    {% else %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> weeks bet against
      no roster</p>
    <p class="hint note">No record yet, so there is no capacity to bet against.</p>
    {% endif %}
  </li>
  {% endfor %}
</ul>
{% else %}
<p class="hint">No cycle has been named yet — not in a record, not in
  config/cycles.yaml, and nothing has been bet into one. Start one below.</p>
{% endif %}
{% if editable %}
<section id="create">
  <h2>Start a cycle</h2>
  <p class="hint">This writes a cycle record. The dates and the roster are carried
    from the last cycle and corrected on the new cycle's own page.</p>
  <p class="editbar">
    <label class="facet">number
      <input id="number" type="number" value="{{ next.number }}" min="0" max="9999"></label>
    <label class="facet">starts
      <input id="starts" type="date" value="{{ next.starts_on }}"></label>
    <label class="facet">build weeks
      <input id="build" type="number" value="{{ next.build_weeks }}" step="0.5"></label>
    <label class="facet">cool-down
      <input id="cooldown" type="number" value="{{ next.cooldown_weeks }}" step="0.5"></label>
  </p>
  <p class="editbar">
    <button type="button" id="start">Start it</button>
    {% if next.roster %}
    <span class="hint">{{ next.roster|length }} people carried from cycle
      {{ next.from_cycle }}</span>
    {% else %}
    <span class="hint">no roster to carry over — set availability on the new
      cycle's own page</span>
    {% endif %}
    <span id="state" role="status"></span>
    <input type="hidden" id="base" value="{{ base_commit }}">
  </p>
  <p class="confirm" id="confirm" hidden>Start cycle <b id="confirm-number"></b> on
    <b id="confirm-starts"></b>, <b id="confirm-length"></b>, with
    <b id="confirm-people"></b>? This commits a cycle record.
    <button type="button" id="yes">Yes, start it</button>
    <button type="button" id="no">Cancel</button></p>
</section>
<script>
const ROSTER = ROSTER_JSON;
const START = document.getElementById('start');
const CONFIRM = document.getElementById('confirm');
const field = id => document.getElementById(id);

// Starting a cycle writes a file and moves every date on every page that reads
// it. It was one click on a button beside four inputs somebody had just been
// typing in, with no sentence anywhere saying what the click would do.
START.onclick = () => {
  const people = Object.keys(ROSTER).length;
  field('confirm-number').textContent = field('number').value;
  field('confirm-starts').textContent = field('starts').value;
  field('confirm-length').textContent =
    `${field('build').value} build weeks + ${field('cooldown').value} cool-down`;
  field('confirm-people').textContent =
    `${people} ${people === 1 ? 'person' : 'people'} carried over`;
  CONFIRM.hidden = false;
  START.hidden = true;
  announce('');
};

document.getElementById('no').onclick = () => {
  CONFIRM.hidden = true;
  START.hidden = false;
};

// Defaults carried from the last cycle: the length rarely changes, the next one
// starts when the last one ends, and mostly the same people are in it at mostly
// the same rates. All of it is corrected on the cycle's own page afterwards.
document.getElementById('yes').onclick = async () => {
  const number = Number(field('number').value);
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/cycle/${number}`, {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: field('base').value,
        fields: {
          starts_on: field('starts').value,
          build_weeks: Number(field('build').value),
          cooldown_weeks: Number(field('cooldown').value),
          availability: ROSTER,
        },
        body: null,
      }),
    });
    const answer = await response.json();
    if (!response.ok) {
      announce(answer.detail || 'refused');
      CONFIRM.hidden = true;
      START.hidden = false;
      return;
    }
    committed = answer.commit;
    location.href = '/cycle/' + number;
  } finally {
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
};
</script>
{% endif %}
"""

_PEOPLE = """
<h1>People</h1>
<p class="hint">Everyone named anywhere in the plan, and what they are on the hook
  for.
  {%- if load.cycle is none %}
  {%- elif load.recorded %} The weeks are cycle {{ load.cycle }}'s: what is bet on
  somebody there, against what they are available for. Weeks bet into another cycle
  are counted beside them, and work bet into no cycle at all is in the rows and in no
  number.
  {%- else %} The weeks are cycle {{ load.cycle }}'s: what is bet on somebody there.
  That cycle has no record, so there is no availability to bet it against.
  {%- endif %}</p>
<div id="controls">
  <input id="q" type="search" aria-label="Search person, entity, id"
         placeholder="Search person, entity, id">
  <div class="facets">
  {% for field in ['role', 'kind', 'status'] %}
  <label class="facet">{{ label(field) }}
    <select data-field="{{ field }}"><option value="">all</option>
      {% for value in facets[field] %}
      <option value="{{ value }}">{{ value|human }}</option>{% endfor %}
    </select>
  </label>
  {% endfor %}
  </div>
</div>
<div id="summary"><span id="shown">{{ people|length }}</span> of {{ people|length }} people</div>
{#- One table for the whole page. Fifteen tables meant fifteen headers, and a
    column of statuses that started at a different x for every person cannot be
    read down. The person is a group row inside it instead of a heading above a
    table of their own. -#}
<table id="roles">
  <thead><tr><th scope="col">role</th><th scope="col">entity</th><th scope="col">kind</th>
    <th scope="col">status</th><th scope="col">scheduled</th></tr></thead>
  {% for person in people %}
  <tbody class="person" data-login="{{ person.login }}">
    <tr class="group{{ ' over' if person.over else '' }}">
      <th colspan="5" scope="colgroup"><div class="groupline">
        {%- if person.link %}
        <a class="who" href="{{ links.table }}?{{ person.link.field }}={{ person.login|urlencode }}"
           title="{{ person.link.says }}">{{ person.login }}</a>
        {%- else %}
        <span class="who">{{ person.login }}</span>
        {%- endif %}
        {%- if person.capacity %}
        <span class="load"><b class="num held">{{ '%.1f'|format(person.held) }}</b> of
          <b class="num">{{ '%.1f'|format(person.capacity) }}</b> weeks
          <span class="bar"><span style="width: {{ person.percent }}%"></span></span></span>
        {%- elif person.held and load.recorded %}
        <span class="load stranger"><b class="num held">{{ '%.1f'|format(person.held) }}</b>
          weeks bet, and not on cycle {{ load.cycle }}'s roster</span>
        {%- elif person.held %}
        <span class="load"><b class="num held">{{ '%.1f'|format(person.held) }}</b>
          weeks bet against no roster</span>
        {%- elif load.cycle is not none %}
        <span class="load none">nothing bet in cycle {{ load.cycle }}</span>
        {%- endif %}
        {%- if person.elsewhere %}
        <span class="elsewhere">+<span class="num">{{ '%.1f'|format(person.elsewhere) }}</span>
          weeks in other cycles</span>
        {%- endif %}
        {#- The counts keep their old job and take on the way in: three of the
            four roles are a filter the table has, so a count is a link to the
            rows it counts. -#}
        <span class="tally">
          {%- for t in person.tally -%}
            {%- if t.field %}<a href="{{ links.table }}?{{ t.field }}={{ person.login|urlencode
              }}">{{ t.n }} as {{ t.role }}</a>{% else %}{{ t.n }} as {{ t.role }}{% endif -%}
            {{- ' · ' if not loop.last else '' -}}
          {%- endfor -%}
        </span>
      </div></th>
    </tr>
    {% for row in person.rows %}
    <tr data-role="{{ row.role }}" data-kind="{{ row.kind }}" data-status="{{ row.status }}"
        data-text="{{ row.search }}">
      <td class="role">{{ row.role }}</td>
      <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
      <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
      <td><span class="chip st-{{ row.status }}">{{ row.status|human }}</span></td>
      <td class="derived">{{ row.span }}</td>
    </tr>
    {% endfor %}
  </tbody>
  {% endfor %}
  {#- Which emptiness this is decides what to do about it, so the page says which
      one it is rather than leaving a header row over a void. -#}
  <tbody id="nothing"{% if people %} hidden{% endif %}>
    <tr class="nothing"><td colspan="5">
      {% if people %}
      <p class="headline">No person matches these filters.</p>
      <p class="hint">Every row is filtered out by the controls above.</p>
      <button type="button" id="clear-filters">Clear filters</button>
      {% else %}
      <p class="headline">Nobody is named in this plan yet.</p>
      <p class="hint">People appear here as soon as they own, are assigned, review or
        shape something.</p>
      {% endif %}
    </td></tr>
  </tbody>
</table>
{{ filters|safe }}
<script>
// A person whose own name matches keeps all their rows: searching for somebody is
// asking what they are on the hook for, not asking to see only the rows that
// happen to repeat their name.
const GROUPS = [...document.querySelectorAll('tbody.person')];
const NOTHING = document.getElementById('nothing');
const COUNT = document.getElementById('shown');

// Hidden, not removed: the rows are rendered once by the server, and rebuilding
// them here to show twelve of fifteen is a second copy of the markup that has to
// keep agreeing with the first.
function apply() {
  const text = (params.get('q') || '').trim().toLowerCase();
  const want = ['role', 'kind', 'status']
    .map(field => [field, params.get(field)]).filter(([, value]) => value);
  let visible = 0;
  for (const group of GROUPS) {
    const person = group.dataset.login.toLowerCase();
    let kept = 0;
    for (const row of group.querySelectorAll('tr[data-role]')) {
      const keep = want.every(([field, value]) => row.dataset[field] === value)
        && (!text || person.includes(text) || row.dataset.text.includes(text));
      row.hidden = !keep;
      kept += keep ? 1 : 0;
    }
    group.hidden = kept === 0;
    visible += kept > 0 ? 1 : 0;
  }
  COUNT.textContent = visible;
  NOTHING.hidden = visible > 0;
}

addEventListener('openproj:filter', apply);
// Absent on a plan nobody is named in, where there is no filter to clear.
const CLEAR = document.getElementById('clear-filters');
if (CLEAR) CLEAR.onclick = clearFilters;
apply();
</script>
"""

_PEOPLE_STYLE = """
.hint { max-width: 46rem; font-size: 13px; }
#summary { color: var(--muted); font-size: 13px; margin: .5rem 0 .25rem; }
#shown { font-variant-numeric: tabular-nums; }
#roles { border-collapse: collapse; width: 100%; max-width: 72rem; font-size: 13px; }
#roles th, #roles td { border-bottom: 1px solid var(--line); padding: .3rem .5rem;
                       text-align: left; }
/* The id selector above outranks the shell's centred empty row, which is how the
   message ended up hugging the left edge of a table with nothing in it. */
#roles tr.nothing td { text-align: center; }
/* Sticky against the page rather than a scroll box: five columns fit any screen,
   so the page itself scrolls and the header rides down it. A collapsed border is
   not painted on a sticky cell — the first row scrolls straight over the top of
   it — so the rule is drawn inside the box instead. */
#roles thead th { position: sticky; top: 0; z-index: 2; background: var(--surface);
                  box-shadow: inset 0 -1px 0 var(--line);
                  color: var(--muted); font-weight: 400; font-size: 11px;
                  text-transform: uppercase; letter-spacing: .04em; }
/* A ground, not only a bold name: the group row is the only thing separating one
   person's rows from the next person's now that they share a table, and a run of
   twelve review rows is long enough to lose the boundary in. */
tr.group > th { font-weight: 400; background: var(--surface-2);
                border-top: 1px solid var(--line-strong); }
.groupline { display: flex; flex-wrap: wrap; align-items: baseline; gap: .15rem .75rem; }
.who { font-size: 15px; font-weight: 650; }
.load { color: var(--muted); font-size: 12px; }
.load b { color: var(--fg); font-size: 13px; font-weight: 600; }
/* The number that says the person is over, in the colour that says so. The bar
   beside it turns with the row through the shell's `.over` rule. */
tr.group.over .load b.held { color: var(--danger); }
.load.stranger { color: var(--warn); }
.load.stranger b { color: var(--warn); }
.elsewhere { color: var(--muted); font-size: 12px; }
.tally { color: var(--muted); font-size: 12px; margin-left: auto; }
/* Muted and not accent: the accent is what a link is on every other page, and a
   column of teal words beside a column of teal links reads as twelve dead links. */
td.role { color: var(--muted); font-size: 12px; text-transform: uppercase;
          letter-spacing: .04em; white-space: nowrap; }
"""

_ROLES = (("owner", "owner"), ("assignees", "assignee"), ("reviewers", "reviewer"),
          ("shaped_by", "shaper"))

# Most answerable first. Grouped by entity — which is what building the rows one
# entity at a time gave you — a person with twenty rows had their four ownerships
# scattered through it, and ownership is the thing being on the page is for.
_ROLE_ORDER = ("owner", "assignee", "shaper", "reviewer")

# Which table filter answers "show me this person's <role>", and the words for
# what that link opens. The table facets three of the four fields a person's name
# can sit in; `shaped_by` is not one of them, so a shaper count stays a count
# rather than becoming a link to a filter the table does not have.
_ROLE_FILTER = {
    "owner": ("owner", "owns"),
    "assignee": ("assignees", "is assigned"),
    "reviewer": ("reviewers", "reviews"),
}


def _cycle_view(index: Index, number: int) -> dict:
    """Everything the cycle page shows, computed once so the markup only lays out.

    A person's scheduled end date sits beside their capacity bar deliberately: a
    green bar next to a timeline that runs a month past the cycle is the failure
    that stops a room trusting the tool, and the two numbers come from different
    subsystems. Put together, they cannot quietly disagree.
    """
    plan = index.plans.get(number)
    held = index.load(number)
    nominal = index.nominal_availability
    window = index.cycles.get(number)
    # A cycle with no record has a page too, because the index links to every
    # cycle the plan names and not only to the ones somebody wrote down. That
    # page is a form: everything on it is the record Save would write — the
    # model's own default length, the config window's start if there is one, and
    # the team list as a roster to correct. An empty table with an add box next
    # to it is a form nobody can tell is working.
    proposed = plan or Cycle(cycle=number, starts_on=window[0] if window else index.today)
    build_weeks = proposed.build_weeks
    listed = list(plan.availability) if plan else list(index.known_people)
    ends_on = plan.ends_on.isoformat() if plan else (window[1].isoformat() if window else "")

    # Exactly who was named. Being on the roster IS being in the cycle, so a name
    # is added deliberately rather than appearing because somebody was assigned
    # something — which would make the roster a report instead of a decision.
    people = []
    for login in sorted(listed, key=str.lower):
        rate = proposed.availability.get(login, nominal)
        capacity = rate * build_weeks
        mine = [
            index.spans[i].end
            for i, e in index.entities.items()
            if e.cycle == number and login in (e.assignees + ([e.owner] if e.owner else []))
            and i in index.spans
        ]
        people.append(
            {
                "login": login,
                "rate": rate,
                "capacity": capacity,
                "held": held.get(login, 0.0),
                "over": capacity and held.get(login, 0.0) > capacity,
                "percent": min(100, round(100 * held.get(login, 0.0) / capacity))
                if capacity
                else 0,
                "until": max(mine).isoformat() if mine else "—",
            }
        )

    # Bet into this cycle and not on its roster. Dropping them silently would
    # hide load from the one page that exists to add load up.
    strangers = sorted(set(held) - set(listed), key=str.lower)

    candidates = []
    # Ready first, then in progress, and by id inside each: the question at a
    # betting table is what to pick up, and what is already running is context.
    order = ("ready", "in_progress")
    for entity_id, entity in sorted(
        index.entities.items(), key=lambda kv: (order.index(kv[1].status)
                                                if kv[1].status in order else len(order),
                                                kv[0])
    ):
        if entity.status not in order:
            continue
        size, defaulted = size_weeks(
            entity, Config(default_task_effort=index.default_task_effort)
        )
        candidates.append(
            {
                "id": entity_id,
                "title": entity.title,
                "kind": entity.kind,
                "status": entity.status,
                "size": "" if defaulted else f"{size:g}",
                "size_field": "appetite_weeks" if entity.kind == "pitch" else "effort_weeks",
                "size_hint": f"{size:g} assumed" if defaulted else "",
                "assignees": ", ".join(entity.assignees),
                "reviewers": ", ".join(entity.reviewers),
                "cycle": entity.cycle if entity.cycle is not None else "—",
                "in_cycle": entity.cycle == number,
                # Bet in an earlier cycle and still running: shown, counted, and
                # not re-stampable. Overwriting its cycle would move the deadline
                # its overrun is measured against and forgive the slip.
                "carried": entity.status == "in_progress"
                and entity.cycle is not None
                and entity.cycle < number,
            }
        )

    return {
        "number": number,
        "recorded": plan is not None,
        "dated": window is not None,
        "starts_on": proposed.starts_on.isoformat(),
        "builds_until": plan.builds_until.isoformat() if plan else "",
        "ends_on": ends_on,
        "build_weeks": f"{proposed.build_weeks:g}",
        "cooldown_weeks": f"{proposed.cooldown_weeks:g}",
        "nominal": nominal,
        "people": people,
        "held": held,
        "strangers": strangers,
        "over": [p["login"] for p in people if p["over"]],
        "candidates": candidates,
        "body": _MD.render(plan.body) if plan else "",
    }


def render_cycle(
    index: Index, number: int, links: Links = ROUTES, base_commit: str | None = None
) -> str:
    view = _cycle_view(index, number)
    body = _ENV.from_string(_CYCLE).render(
        c=view,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        combobox=_combobox_html(index),
    )
    body = body.replace("HELD_JSON", _json(view["held"]))
    return _page(
        f"openproj — cycle {number}",
        body,
        _DETAIL_STYLE + _CYCLE_STYLE + _SUGGEST_STYLE,
        links,
    )


def _cycle_numbers(index: Index) -> set[int]:
    """Every cycle the plan names.

    Three sets that are not the same set: the cycles with a record, the cycles
    config/cycles.yaml dates, and the cycles entities point at. A page that asks
    only one of them loses exactly the cycle somebody is looking for — the one
    holding work with nothing written down behind it.
    """
    return (
        set(index.plans)
        | set(index.cycles)
        | {e.cycle for e in index.entities.values() if e.cycle is not None}
    )


def _current_cycle(index: Index) -> int | None:
    """The cycle the plan is in now, or the nearest thing to one.

    The cycle whose window holds today; failing that the next one to start,
    because between two cycles the live question is the one coming; failing that
    the last one there was, because work bet into a cycle that has ended is still
    work somebody is holding. A cycle with no dates cannot be any of the three.
    """
    dated = sorted(index.cycles.items(), key=lambda pair: pair[1][0])
    for number, (starts, ends) in dated:
        if starts <= index.today <= ends:
            return number
    for number, (starts, _) in dated:
        if starts > index.today:
            return number
    return dated[-1][0] if dated else None


def _cycle_totals(index: Index, number: int) -> dict:
    """One cycle's card: what is bet against what there is to bet with.

    The bet counts every week charged to the cycle, including work belonging to
    somebody the roster does not name. Summing only the roster's rows made a
    cycle look emptier the more of it was bet by people nobody had added — which
    is the direction the number must never be wrong in.
    """
    plan = index.plans.get(number)
    window = index.cycles.get(number)
    bet = sum(index.load(number).values())
    capacity = (
        sum(plan.capacity(who, index.nominal_availability) for who in plan.availability)
        if plan
        else 0.0
    )
    return {
        "number": number,
        "recorded": plan is not None,
        "starts_on": plan.starts_on.isoformat()
        if plan
        else (window[0].isoformat() if window else ""),
        "builds_until": plan.builds_until.isoformat() if plan else "",
        "ends_on": plan.ends_on.isoformat()
        if plan
        else (window[1].isoformat() if window else ""),
        "people": len(plan.availability) if plan else 0,
        "bet": bet,
        "capacity": capacity,
        "percent": min(100, round(100 * bet / capacity)) if capacity else 0,
        "over": bool(capacity) and bet > capacity,
    }


def render_cycles(
    index: Index, links: Links = STATIC, base_commit: str | None = None
) -> str:
    # Every cycle the plan names, not only the ones with a file. A cycle dated in
    # config, or one that entities point at with nothing behind it, is exactly
    # the cycle somebody needs to find: it holds work and holds no record.
    numbers = _cycle_numbers(index)
    rows = [_cycle_totals(index, number) for number in sorted(numbers, reverse=True)]
    last = index.plans[max(index.plans)] if index.plans else None
    # The number to propose comes from the cycles the plan has *decided* — the
    # ones with a record and the ones config/cycles.yaml dates — and not from
    # every number an entity happens to mention. A plan whose cycles live only in
    # config would otherwise be offered cycle 1 while it is running cycle 37; but
    # unioning `entity.cycle` in overshoots the other way, and worse. One bet into
    # a cycle nobody has written down — which the listing above actively invites —
    # made the form propose the number after *that*, with no dates behind it, so
    # the real last cycle's end date was thrown away and the proposal started
    # today. Entity-referenced numbers belong to the listing; they are not a
    # decision about when the next cycle begins.
    decided = set(index.plans) | set(index.cycles)
    top = max(decided) if decided else 0
    ends = index.cycles.get(top)
    body = _ENV.from_string(_CYCLES).render(
        cycles=rows,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        # Whether there is a page per cycle to link a card to. Only the server
        # serves one; `render_static` writes six files and no cycle is among
        # them, so on a rendered plan the card names its cycle and stops there.
        per_cycle_page=links.cycle.startswith("/"),
        # The next cycle starts when the last one ends and is the same length,
        # because both are true far more often than not.
        next={
            "number": top + 1,
            "starts_on": (ends[1] + timedelta(days=1)).isoformat()
            if ends
            else index.today.isoformat(),
            "build_weeks": f"{last.build_weeks:g}" if last else "4",
            "cooldown_weeks": f"{last.cooldown_weeks:g}" if last else "2",
            # Which cycle the roster below was taken from, which is the last one
            # with a record and not necessarily the last one that exists.
            "from_cycle": max(index.plans) if index.plans else top,
            # The people who worked the last cycle, at the rates they worked it
            # at. A team changes slowly and availability changes every cycle, so
            # this is a starting point to correct rather than a claim — and it
            # beats retyping fifteen names to change three of them.
            "roster": dict(sorted(last.availability.items(), key=lambda kv: kv[0].lower()))
            if last
            else {},
        },
    )
    body = body.replace(
        "ROSTER_JSON", _json(last.availability if last else {})
    )
    return _page("openproj — cycles", body, _DETAIL_STYLE + _CYCLE_STYLE, links)


def _person_load(index: Index, logins: list[str]) -> dict:
    """What each person is on the hook for in weeks, against what they have.

    Counts were the old answer — "1 as owner, 2 as assignee, 12 as reviewer" adds
    a half-hour review to a six-week build and calls the sum a workload. The
    weeks come from `index.load`, the same function the cycle page bets with, so
    the two pages cannot come to different conclusions about the same person.

    One cycle, named on the page, rather than every cycle summed: availability is
    recorded per cycle, so adding up five cycles of it against a plan that only
    ever bets the current one makes everybody look idle. Weeks bet into any other
    cycle are carried separately instead of dropped — that number is usually the
    reason somebody is busier than this cycle says they are.
    """
    number = _current_cycle(index)
    plan = index.plans.get(number) if number is not None else None
    here = index.load(number) if number is not None else {}
    elsewhere: dict[str, float] = {}
    for other in _cycle_numbers(index) - {number}:
        for login, weeks in index.load(other).items():
            elsewhere[login] = elsewhere.get(login, 0.0) + weeks

    people = {}
    for login in logins:
        held = here.get(login, 0.0)
        # Being on the roster is being in the cycle, which is the cycle page's
        # rule. Falling back to the nominal rate for somebody nobody added would
        # invent availability out of a default and hide the fact that the bet is
        # off the books.
        rostered = plan is not None and login in plan.availability
        capacity = plan.capacity(login, index.nominal_availability) if rostered else 0.0
        people[login] = {
            "held": held,
            "capacity": capacity,
            "over": bool(capacity) and held > capacity,
            "percent": min(100, round(100 * held / capacity)) if capacity else 0,
            "elsewhere": elsewhere.get(login, 0.0),
        }
    return {"cycle": number, "recorded": plan is not None, "people": people}


def render_people(index: Index, links: Links = STATIC) -> str:
    """Everyone in the plan, and what they are on the hook for.

    Built from the fields rather than from a roster: a page that reads a separate
    list of members shows people who have nothing to do and misses whoever was
    added this morning.
    """
    held: dict[str, list[dict]] = {}
    for entity_id, entity in sorted(index.entities.items()):
        span = index.spans.get(entity_id)
        for field, role in _ROLES:
            value = getattr(entity, field, None)
            for login in value if isinstance(value, list) else [value] if value else []:
                held.setdefault(login, []).append(
                    {
                        "role": role,
                        "id": entity_id,
                        "title": entity.title,
                        "kind": entity.kind,
                        "status": entity.status,
                        "span": f"{span.start} → {span.end}" if span else "—",
                        "search": f"{entity_id} {entity.title}".lower(),
                    }
                )

    for rows_for_person in held.values():
        rows_for_person.sort(key=lambda r: (_ROLE_ORDER.index(r["role"]), r["title"]))

    load = _person_load(index, list(held))
    people = []
    # Case-folded, or every capitalised login sorts ahead of the lowercase ones and
    # "alphabetical" means ASCII to the page and nothing to the reader.
    for login, rows in sorted(held.items(), key=lambda pair: pair[0].lower()):
        counts = {role: sum(1 for r in rows if r["role"] == role) for _, role in _ROLES}
        tally = [
            {"role": role, "n": counts[role], "field": _ROLE_FILTER.get(role, ("",))[0]}
            for role in _ROLE_ORDER
            if counts[role]
        ]
        # Which filter the name itself opens. The most answerable role they
        # actually hold, because a link to what somebody owns is an empty table
        # for somebody who owns nothing — and a link that lands on an empty table
        # teaches people the link is broken.
        opens = next((t["role"] for t in tally if t["field"]), None)
        people.append(
            {
                "login": login,
                "rows": rows,
                "tally": tally,
                "link": {
                    "field": _ROLE_FILTER[opens][0],
                    "says": f"Everything {login} {_ROLE_FILTER[opens][1]}, in the table",
                }
                if opens
                else None,
                **load["people"][login],
            }
        )
    # Only values that are actually on the page: a filter offering a status
    # nobody holds is a dead end that looks like a bug.
    facets = {
        key: sorted({row[key] for rows in held.values() for row in rows})
        for key in ("role", "kind", "status")
    }
    body = _ENV.from_string(_PEOPLE).render(
        people=people, links=links, facets=facets, load=load, filters=_FILTER_JS
    )
    return _page("openproj — people", body, _PEOPLE_STYLE, links)


def _by_status(rows: list[dict]) -> list[dict]:
    """The index, in the order work moves through: shaping first, done last.

    A status nobody uses is left out rather than shown empty, and a status the
    validator does not know still gets a heading — the index is a way in, and an
    entity missing from it because its status is misspelt is invisible.
    """
    known = list(STATUSES)
    seen = sorted({row["status"] for row in rows}, key=lambda s: (s not in known, s))
    order = [s for s in known if s in seen] + [s for s in seen if s not in known]
    return [
        {"status": status, "entities": [r for r in rows if r["status"] == status]}
        for status in order
    ]


def render_detail(
    index: Index,
    links: Links = STATIC,
    only: str | None = None,
    base_commit: str | None = None,
) -> str:
    """Every entity, or exactly one.

    The server serves one per route; the static build serves them all in a page
    that hides everything but the hash. Same markup, so the two cannot drift.
    """
    rows = _detail_rows(index, links)
    if only is not None:
        rows = [row for row in rows if row["id"] == only]
    # Every entity gets its facts, not only the one being served on its own route:
    # the static export renders them all, and it is the same page.
    for row in rows:
        entity = index.entities[row["id"]]
        row["rows"] = _fact_rows(index, entity, links)
        row["raw_body"] = entity.body
    body = _ENV.from_string(_DETAIL).render(
        entities=rows,
        groups=_by_status(rows),
        # Every entity this page holds, not the one in the URL: the static export
        # is all of them in one file, and the shell's banner has no other way to
        # tell "somebody changed what you are reading" from "somebody changed
        # something".
        showing=[row["id"] for row in rows],
        single=only is not None,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        statuses=STATUSES,
        combobox=_combobox_html(index),
        required=_REQUIRED_JS,
    )
    return _page("openproj — detail", body, _DETAIL_STYLE + _SUGGEST_STYLE, links)


def _facets_html(index: Index) -> str:
    """The control bar, for any view that filters the plan.

    One bar and one `matches()` in `_FILTER_JS`, rather than a copy per page: the
    table's dropdowns and the graph's have to mean the same thing, or a link
    somebody pasted filters differently depending on which view it opens in.
    """
    return _ENV.from_string(_FACETS).render(
        facets=index.facets, predicates=list(index.facets["predicate"])
    )


def _combobox_html(index: Index | None) -> str:
    """The suggestion data and the widget that filters it, for any page with inputs."""
    data = (
        _suggestions(index)
        if index
        else {"people": [], "entities": [], "tags": [], "prs": [], "cycles": []}
    )
    return _COMBOBOX.replace("SUGGEST_JSON", _json(data))


def _page(title: str, content: str, style: str = "", links: Links = STATIC) -> str:
    """Autoescaping protects entity titles inside the inner templates; the already
    rendered body and stylesheet are marked safe here so the shell does not escape
    them a second time."""
    return _ENV.from_string(_SHELL).render(
        title=title,
        content=Markup(content),
        style=Markup(style),
        font=_font_uri(),
        links=links,
        # The shell writes the chip and legend rules for every status, so a
        # status added to the model cannot arrive with three of its four tokens
        # wired up and the fourth still spelled out on a line nobody edited.
        statuses=STATUSES,
        # Only the server has an event stream to listen to. A static page opening a
        # connection to nothing would retry forever in the console.
        live=links.table.startswith("/"),
    )


def preview_html(body: str, links: Links = ROUTES) -> str:
    """Markdown rendered for the preview pane, with HTML disabled.

    markdown-it-py leaves raw HTML alone by default. The body is written by
    signed-in members and rendered back to every reader, so a script tag in a
    shaping doc would run in everybody's browser.

    Routes by default: the only thing that asks for a preview is the server.
    """
    return _after_markdown(MarkdownIt("commonmark", {"html": False}).render(body), links)


def render_table(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
    payload = _payload(index)
    blocking = [p for p in index.problems if p.severity == "blocker"]
    body = _ENV.from_string(_TABLE).render(
        payload=payload,
        blockers=len(blocking),
        # The population `?predicate=has_blocker` matches. One entity can carry
        # three problems, so the count and the filter it links to were counting
        # different things and the table opened shorter than the number promised.
        blocked=len({p.entity_id for p in blocking}),
        editable=base_commit is not None,
        base_commit=base_commit or "",
        links=links,
        facets=_facets_html(index),
        filters=_FILTER_JS,
        combobox=_combobox_html(index),
    )
    body = body.replace("PAYLOAD_JSON", _json(payload)).replace("ENTITY_HREF", links.entity)
    return _page("openproj — table", body, _TABLE_STYLE + _SUGGEST_STYLE, links)


def render_graph(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
    """Inline the libraries in one pass, keyed by filename.

    Sequential `str.replace` calls were wrong here and silently so: `DAGRE_JS` is a
    substring of `CYTOSCAPE_DAGRE_JS`, so replacing the shorter marker first ate
    the tail of the longer one. dagre was inlined twice, cytoscape-dagre never,
    and the page rendered blank with a stray identifier. One regex pass over
    delimited markers cannot collide however the names are chosen.
    """
    body = _ENV.from_string(_GRAPH).render(
        editable=base_commit is not None,
        base_commit=base_commit or "",
        facets=_facets_html(index),
        filters=_FILTER_JS,
        statuses=STATUSES,
        glyphs=STATUS_GLYPH,
        total=len(index.entities),
    )
    body = body.replace("ELEMENTS_JSON", _json(_elements(index)))
    wanted = {"cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js"}
    body = re.sub(
        r"@@([\w.-]+)@@",
        # Only known filenames are substituted: minified sources contain things
        # like `e["@@iterator"]`, and a blind pattern would try to inline them.
        lambda m: _inline(m.group(1)) if m.group(1) in wanted else m.group(0),
        body,
    )
    body = body.replace("ENTITY_HREF", links.entity)
    return _page("openproj — graph", body, _GRAPH_STYLE, links)


_ZOOMS = (("2", "months"), ("6", "weeks"), ("14", "days"), ("30", "close"))


def render_timeline(
    index: Index,
    links: Links = STATIC,
    window: tuple[date | None, date | None] = (None, None),
    zoom: float | None = None,
) -> str:
    timeline = _timeline(index, window, zoom)
    body = _ENV.from_string(_TIMELINE).render(
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
        glyph_dy=_GLYPH_DY,
        facets=_facets_html(index),
        filters=_FILTER_JS,
    )
    # The rows the shared `matches()` reads, for the bars that were drawn. Not the
    # whole plan: a bar that is not on this window cannot be filtered onto it.
    payload = {"rows": timeline["rows"], "human": HUMAN}
    body = body.replace("BARS_JSON", _json(payload))
    return _page("openproj — timeline", body, _TIMELINE_STYLE + _status_paint_css(), links)


def render_static(index: Index, out_dir: Path, repo: Path | None = None) -> None:
    """The pages, and the images they name.

    Without the copy an exported plan renders every uploaded figure as a broken
    image — the markdown points at `assets/…` relative to the page, which is
    exactly right and exactly useless if the directory is not there.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = (repo / "assets") if repo else None
    if assets and assets.is_dir():
        shutil.copytree(assets, out_dir / "assets", dirs_exist_ok=True)
    for name, html in (
        ("index.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("people.html", render_people(index)),
        ("cycles.html", render_cycles(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
