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
from .model import Config, Entity, Pitch, Project, Task, size_weeks


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
_LABEL_CHARS = 40
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
        bars.append(
            {
                "id": entity_id,
                "label": _clip(entity.title),
                "full": f"{entity.title} ({entity_id})",
                "depth": depth,
                "indent": depth * _INDENT_PX,
                "classes": " ".join(classes),
                "marks": marks,
                "x": x(visible_start),
                "y": row * _ROW_PX + _HEADER_PX + _BAR_TOP,
                "width": round(
                    max(
                        _MIN_BAR_PX, day_px,
                        x(visible_end + timedelta(days=1)) - x(visible_start),
                    ),
                    1,
                ),
                "colour": _status_class(entity.status),
            }
        )
        size, _ = size_weeks(entity, config)
        explanation = index.explanations.get(entity_id)
        # The table's own row, so the shared `matches()` reads the same fields on
        # this page as on the other two, plus the two things only a bar wants to
        # say: what it is holding, and why it starts when it does.
        rows[entity_id] = _row(index, entity_id) | {
            "weeks": round(size, 2),
            "tip": explanation.text if explanation else "Starts as soon as it can.",
        }
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


def _body_html(entity: Entity, links: Links = STATIC) -> str:
    """The shaping document, rendered, with PR references made clickable.

    A remote image would make the page fetch from the network, which is exactly
    what inlining every library was for. Remote images become links instead: the
    reference survives, the dependency does not.

    An image stored in the plan is a different thing — it is in the repository,
    it travels with the clone, and it is served from the same origin as the page.
    Those are drawn.
    """
    return _after_markdown(_MD.render(entity.body), links)


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
  --line: #dce4e5; --line-strong: #b4c3c7; --muted: #5a6b70;
  --accent: #0f5c6b; --on-accent: #ffffff;
  --danger: #9a3327; --warn: #8a5308; --ok: #2f7248;
  /* The em dash that means "no value" was #b7c5c9 against white: 1.77:1, which
     is not a colour, it is an absence. It is a real piece of information. */
  --empty: #7c8d93; --focus: #0f5c6b;
  /* Four tokens per status, not one. Fill and ink draw *shapes* — a graph node,
     a timeline bar. Soft and text draw *chips* — the pill in a table cell, which
     needs a ground light enough to sit inside a row of running text. */
  --st-shaping: #5b4b9e; --st-shaping-ink: #ffffff;
  --st-shaping-soft: #ede9f8; --st-shaping-text: #4a3c86;
  --st-ready: #2c5f8f; --st-ready-ink: #ffffff;
  --st-ready-soft: #e4eef8; --st-ready-text: #23507a;
  --st-in_progress: #8a5308; --st-in_progress-ink: #ffffff;
  --st-in_progress-soft: #f8eedc; --st-in_progress-text: #774606;
  --st-done: #2f7248; --st-done-ink: #ffffff;
  --st-done-soft: #e3f1e8; --st-done-text: #256040;
  --st-shelved: #566a72; --st-shelved-ink: #ffffff;
  --st-shelved-soft: #ebeff1; --st-shelved-text: #465861;
  /* Kind is drawn in ink, never in hue: two colour languages on one row and
     neither one is read. */
  --kind-ink: #5a6b70; --kind-line: #b4c3c7;
  --sev-blocker: #9a3327; --sev-blocker-soft: #f9e9e6;
  --sev-warn: #8a5308; --sev-warn-soft: #f8eedc;
  /* One label colour for every status fill, because in each theme all five inks
     are the same. The graph reads it for node text and the timeline for the
     hatch that marks a guess. */
  --on-status: #ffffff; --hatch: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
    --line: #263336; --line-strong: #3a4d53; --muted: #93a6aa;
    --accent: #5cb9ca; --on-accent: #0b1214;
    --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
    --empty: #7e9199; --focus: #5cb9ca;
    /* Dark fills invert: a light shape carrying dark ink pops off a dark canvas
       instead of sinking into it. So --on-status and --hatch flip with them —
       white text on these fills would be the failure the light theme avoids. */
    --st-shaping: #a79ae6; --st-shaping-ink: #0f1416;
    --st-shaping-soft: #252041; --st-shaping-text: #b8aaf0;
    --st-ready: #7fb2de; --st-ready-ink: #0f1416;
    --st-ready-soft: #152b3e; --st-ready-text: #8fbeea;
    --st-in_progress: #d9a557; --st-in_progress-ink: #0f1416;
    --st-in_progress-soft: #332409; --st-in_progress-text: #e2b268;
    --st-done: #6fc095; --st-done-ink: #0f1416;
    --st-done-soft: #14301f; --st-done-text: #7ecda2;
    --st-shelved: #9daeb6; --st-shelved-ink: #0f1416;
    --st-shelved-soft: #1e262a; --st-shelved-text: #a6b7bf;
    --kind-ink: #93a6aa; --kind-line: #3a4d53;
    --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
    --sev-warn: #d9a557; --sev-warn-soft: #332409;
    --on-status: #0f1416; --hatch: #0f1416;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
  --line: #263336; --line-strong: #3a4d53; --muted: #93a6aa;
  --accent: #5cb9ca; --on-accent: #0b1214;
  --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
  --empty: #7e9199; --focus: #5cb9ca;
  --st-shaping: #a79ae6; --st-shaping-ink: #0f1416;
  --st-shaping-soft: #252041; --st-shaping-text: #b8aaf0;
  --st-ready: #7fb2de; --st-ready-ink: #0f1416;
  --st-ready-soft: #152b3e; --st-ready-text: #8fbeea;
  --st-in_progress: #d9a557; --st-in_progress-ink: #0f1416;
  --st-in_progress-soft: #332409; --st-in_progress-text: #e2b268;
  --st-done: #6fc095; --st-done-ink: #0f1416;
  --st-done-soft: #14301f; --st-done-text: #7ecda2;
  --st-shelved: #9daeb6; --st-shelved-ink: #0f1416;
  --st-shelved-soft: #1e262a; --st-shelved-text: #a6b7bf;
  --kind-ink: #93a6aa; --kind-line: #3a4d53;
  --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
  --sev-warn: #d9a557; --sev-warn-soft: #332409;
  --on-status: #0f1416; --hatch: #0f1416;
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
/* One chip everywhere a status or a kind is named, defined here rather than per
   page because the table, the detail page, the people page and the cycle bet
   table were four different ways of saying the same word. The word is always
   inside the chip, so the colour is redundant encoding and a reader who cannot
   separate the hues loses nothing. */
.chip { display: inline-block; font-family: var(--font-mono); font-size: 11px;
        line-height: 1.45; text-transform: uppercase; letter-spacing: .04em;
        padding: .1rem .4rem; border-radius: 2px; white-space: nowrap; }
.chip.st-shaping { background: var(--st-shaping-soft); color: var(--st-shaping-text); }
.chip.st-ready { background: var(--st-ready-soft); color: var(--st-ready-text); }
.chip.st-in_progress { background: var(--st-in_progress-soft);
                       color: var(--st-in_progress-text); }
.chip.st-done { background: var(--st-done-soft); color: var(--st-done-text); }
.chip.st-shelved { background: var(--st-shelved-soft); color: var(--st-shelved-text); }
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
   is believed. */
.legend { display: flex; flex-wrap: wrap; gap: .25rem 1rem; align-items: center;
          list-style: none; margin: .75rem 0 0; padding: 0;
          font-size: 12px; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: .35rem; }
.legend .swatch { width: 20px; height: 11px; border-radius: 2px; flex: none; }
.legend .swatch.st-shaping { background: var(--st-shaping); }
.legend .swatch.st-ready { background: var(--st-ready); }
.legend .swatch.st-in_progress { background: var(--st-in_progress); }
.legend .swatch.st-done { background: var(--st-done); }
.legend .swatch.st-shelved { background: var(--st-shelved); }
/* The way out of a filter, on every page that has one. Three pages were drawing
   this button themselves, which is three chances for the way out of a filter to
   look like something else. */
#clear-filters { font: inherit; font-size: 13px; padding: .2rem .6rem; border-radius: 2px;
                 border: 1px solid var(--line-strong); background: var(--surface);
                 color: var(--fg); cursor: pointer; }
#clear-filters:hover { border-color: var(--accent); color: var(--accent); }
#moved { position: fixed; right: 1rem; bottom: 1rem; background: var(--accent);
         color: var(--on-accent);
         padding: .5rem .8rem; font-size: 13px; border-radius: 3px; }
#moved a { color: var(--on-accent); }
#moved .sha { font-family: var(--font-mono); opacity: .7; }
{{ style }}
</style></head><body>
<nav><a href="{{ links.table }}">Table</a><a href="{{ links.graph }}">Graph</a>
<a href="{{ links.timeline }}">Timeline</a><a href="{{ links.cycles }}">Cycles</a>
<a href="{{ links.people }}">People</a>
<a href="{{ links.detail }}">Detail</a>
<button type="button" id="theme"></button></nav>
{{ content }}
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
</script>
{% if live %}
<div id="moved" hidden></div>
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
  <input id="q" type="search" placeholder="Search title, tags, body">
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
  // Not the sort order: clearing the filters and losing the column somebody
  // sorted by is a second surprise on top of the one they were undoing.
  for (const field of [...FILTERS, 'predicate', 'q']) params.delete(field);
  settled();
}

document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
for (const select of document.querySelectorAll('select[data-field]'))
  select.addEventListener('change', e => update(e.target.dataset.field, e.target.value));
syncFilters();
</script>
"""

_TABLE = """
<p class="editbar"><a class="button" href="{{ links.new }}">New entity</a>
   <span class="hint">double-click a cell to edit it</span>
   <span id="state"></span></p>
<div id="summary">
  <a id="blockers" href="?predicate=has_blocker"><strong id="blocker-count">{{ blockers
    }}</strong> <span id="blocker-word">blocking problem{{
    "" if blockers == 1 else "s" }}</span></a> ·
  <span id="shown">{{ payload.rows|length }}</span> of {{ payload.rows|length }} shown
</div>
{{ facets|safe }}
<div class="table-scroll"><table id="rows"><thead><tr>
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
<div id="row-conflict" hidden></div>
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

// Attribute text. A problem message quotes the field it is about, so a stored
// value with a quote in it would close the attribute and let the rest become
// markup on everybody else's screen.
const attr = value => String(value)
  .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

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
let BLOCKERS = 0;

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
}

function summarise() {
  document.getElementById('blocker-count').textContent = BLOCKERS;
  document.getElementById('blocker-word').textContent =
    BLOCKERS === 1 ? 'blocking problem' : 'blocking problems';
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
  const tags = list || [];
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
  if (key === 'title') return `<a href="ENTITY_HREF${row.id}">${row.title}</a>`;
  if (key === 'prs') return (value || []).map(prLink).join(', ');
  // Kind is filterable everywhere and visible nowhere. It rides with the id,
  // which was already carrying it in a prefix nobody should have to decode.
  if (key === 'id')
    return `<span class="chip kind-${row.kind}">${human(row.kind)}</span>` +
      ` <span class="eid">${row.id}</span>`;
  if (key === 'status') return `<span class="chip st-${row.status}">${human(row.status)}</span>`;
  if (key === 'priority') return human(row.priority);
  if (key === 'tags') return tagsHtml(value);
  return stored(row, key);
}

function cell(row, key) {
  const mark = (MARKS[row.id] || {})[key];
  const note = mark ? mark.messages.join(' · ') : '';
  const ground = mark ? 'sev-cell-' + SEV_CLASS[mark.severity] : '';
  // role="img" with a name, not a bare character: the message was reachable only
  // by hovering the row, and a tooltip is not something a table gets hovered for.
  const glyph = mark
    ? ` <span class="sev-mark sev-mark-${SEV_CLASS[mark.severity]}" role="img"` +
      ` aria-label="${attr(note)}" title="${attr(note)}">⚠</span>`
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
  return `<td data-col="${key}"${editable ? ` data-entity="${row.id}" data-field="${key}"` : ''}` +
    `${!editable && key in WHY ? ` data-why="${attr(WHY[key])}"` : ''}` +
    ` class="${classes}"${tip ? ` title="${attr(tip)}"` : ''}>${body}</td>`;
}

function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${repo}/pull/${number}">${ref}</a>`;
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
  tbody.innerHTML = rows.length ? rows.map(rowHtml).join('') : emptyRow();
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
    document.getElementById('state').textContent = `${field} ${error.message}`;
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
      document.getElementById('state').textContent = answer.detail || 'refused';
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

if (EDITABLE) {
  tbody.addEventListener('dblclick', event => {
    const cell = event.target.closest('td.edit');
    // The tag reveal is a control inside an editable cell, so a double-click on
    // it would both open the list and open the editor over it.
    if (!cell || cell.querySelector('input') || event.target.closest('button.more')) return;
    const field = cell.dataset.field;
    const was = stored(DATA.rows[cell.dataset.entity], field);
    const suggest = SUGGESTS[field];
    const closed = CHOICES[EDITABLE[field]];
    // A closed set is chosen, never typed. Free text over three options is a way
    // to write `in progres` into the corpus. The option's value is the stored
    // identifier and its text is the word for it, so picking "In progress"
    // still writes `in_progress`.
    cell.innerHTML = closed
      ? `<select data-type="text">${closed.map(o =>
          `<option value="${o}" ${o === was ? 'selected' : ''}>${human(o)}</option>`
        ).join('')}</select>`
      : `<input value="${attr(was)}" data-type="${EDITABLE[field]}"` +
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
      if (e.key === 'Enter') input.blur();
      if (e.key === 'Escape') {
        // Escape means discard. Redrawing first would fire blur with the partial
        // value still in the box, and the edit somebody just abandoned gets saved.
        abandoned = true;
        draw();
      }
    };
  });
}
{% endif %}
tbody.addEventListener('click', event => {
  if (event.target.id === 'clear-filters') { clearFilters(); return; }
  const more = event.target.closest('button.more');
  if (more) more.closest('td').classList.add('open');
});
// A derived cell that ignores a double-click looks exactly like a cell that is
// broken. It answers instead, in the same place a refused save answers.
tbody.addEventListener('dblclick', event => {
  const computed = event.target.closest('td[data-why]');
  if (!computed) return;
  document.getElementById('state').textContent = computed.dataset.why;
  computed.classList.add('refused');
  setTimeout(() => computed.classList.remove('refused'), 1500);
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
.table-scroll { overflow: auto; max-height: calc(100vh - 13rem); min-height: 9rem;
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
/* Inside the body, not above it or beside it: an empty table with the message
   somewhere else is still a header row over a void. */
tr.nothing td { padding: 2.5rem .5rem; text-align: center; }
tr.nothing .headline { margin: 0 0 .25rem; color: var(--fg); font-size: 15px; }
tr.nothing .hint { margin: 0 0 .75rem; }
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
{% if editable %}
<p class="editbar">
  <button type="button" id="connect">Edit dependencies</button>
  <button type="button" id="save" hidden>Save</button>
  <button type="button" id="discard" hidden>Reset</button>
  <span id="state"></span>
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
    the node is actually filled with, so the legend cannot drift from the graph. -#}
<ul class="legend" aria-label="What a node colour means">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}"></span>{{ status|human }}</li>
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

// Cytoscape aligns a left-aligned label by its RIGHT edge against the box's left
// edge, so putting a group's name inside its own box means knowing how wide the
// name is. There is no API for that and character counts put an "i" and a "W" in
// different places, so it is measured on a canvas in the font the graph draws in.
const ruler = document.createElement('canvas').getContext('2d');
const GROUP_SIZE = 12;
const GROUP_MAX = 300;    // the width the label is told to ellipsise at
function groupWidth(node) {
  ruler.font = `600 ${GROUP_SIZE}px ${token('--font-sans')}`;
  return Math.min(GROUP_MAX, ruler.measureText(node.data('label') || '').width);
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
        'label': 'data(label)', 'font-size': 10, 'shape': 'round-rectangle',
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
        'border-color': token('--accent'),
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
                             'border-color': token('--accent'),
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

function say(message) {
  const state = document.getElementById('state');
  if (state) state.textContent = message;
}

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
      base.value = answer.commit;
      written += 1;
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
    the same token or the same pattern the plot uses. -#}
<ul class="legend" aria-label="What a bar colour means">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}"></span>{{ status|human }}</li>
  {% endfor %}
</ul>
<ul class="legend" aria-label="What a bar marking means">
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="neutral" width="20" height="11"/><rect class="mark mark-estimated"
        width="20" height="11"/></svg>appetite assumed</li>
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="neutral" width="20" height="11"/><rect class="mark mark-unowned"
        width="20" height="11"/></svg>nobody on it</li>
  <li><span class="swatch outline late"></span>overruns its cycle</li>
  <li><span class="swatch rule today"></span>today</li>
  <li><span class="swatch rule boundary"></span>a cycle closes</li>
  <li><span class="swatch band"></span>a cycle, build and cooldown</li>
</ul>
<div id="summary"><span id="shown">{{ t.bars|length }}</span> of {{ t.bars|length }}
  drawn{% if t.offscreen %} · {{ t.offscreen }} with no dates in this
  window{% endif %}</div>
<div class="tl"{% if not t.bars %} hidden{% endif %}>
<div class="labels">
  <div class="spacer" style="height: {{ t.header }}px"></div>
  {#- Indented by containment, so a project's work reads as a block. The clipped
      label is what fits in 250px; the whole title is on the anchor. -#}
  {% for bar in t.bars %}
  <div class="row" data-id="{{ bar.id }}" data-depth="{{ bar.depth }}"
       style="padding-left: {{ 8 + bar.indent }}px">
    <a href="{{ links.entity }}{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a></div>
  {% endfor %}
</div>
<div class="scroll">
<svg width="{{ t.width }}" height="{{ t.height }}"
     viewBox="0 0 {{ t.width }} {{ t.height }}" role="img"
     aria-label="Every scheduled entity as a bar, earliest first within its parent">
  <defs>
    <pattern id="hatch-estimated" width="6" height="6" patternTransform="rotate(45)"
             patternUnits="userSpaceOnUse">
      <line x1="0" y="0" x2="0" y2="6" stroke="var(--hatch)" stroke-opacity=".55" stroke-width="3"/>
    </pattern>
    <pattern id="hatch-unowned" width="8" height="8" patternTransform="rotate(-45)"
             patternUnits="userSpaceOnUse">
      <line x1="0" y="0" x2="0" y2="8" stroke="var(--hatch)" stroke-opacity=".7" stroke-width="4"/>
    </pattern>
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
  {% for bar in t.bars %}
  <a href="{{ links.entity }}{{ bar.id }}" aria-label="{{ bar.full }}"
     ><rect data-id="{{ bar.id }}" class="{{ bar.classes }} {{ bar.colour }}"
        x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="{{ bar_px }}"
        ><title>{{ t.rows[bar.id].tip }} — click to open</title></rect>{% for mark in
        bar.marks %}<rect class="mark mark-{{ mark }}" x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="{{ bar_px }}"/>{% endfor %}</a>
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
const BAR_TOP = {{ bar_top }};
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
    // The bar and whatever is hatched over it are one row and move together.
    for (const shape of rect.parentNode.querySelectorAll('rect'))
      shape.setAttribute('y', row * ROW_PX + HEADER + BAR_TOP);
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
/* The ground under a legend hatch. --muted rather than a line colour because it
   is the one token that tracks the status fills through the themes: a mid tone
   in light and a light one in dark, so --hatch reads on it exactly as it reads
   on a bar. */
rect.neutral { fill: var(--muted); }
/* The three markings, drawn the way the plot draws them: a hatch over a neutral
   ground, an outline, a rule. A legend that redraws a mark in its own way is a
   legend that can be wrong about the picture beside it. */
.legend .swatch.outline { background: var(--surface-2); }
.legend .swatch.late { border: 1.5px solid var(--danger); }
.legend .swatch.rule { width: 2px; height: 13px; border-radius: 0; }
.legend .swatch.today { background: var(--danger); }
.legend .swatch.boundary { background: none; border-left: 2px dashed var(--line-strong); }
.legend .swatch.band { background: var(--surface-2); border: 1px solid var(--line); }
.tl { display: flex; border: 1px solid var(--line); align-items: stretch; }
.tl[hidden] { display: none; }
.labels { flex: 0 0 250px; border-right: 1px solid var(--line); }
.labels .row {
  height: 22px; line-height: 22px; font-size: 11px; color: var(--muted);
  padding: 0 .5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scroll { overflow-x: auto; flex: 1 1 auto; min-width: 0; }
svg { display: block; }
.month-rule { stroke: var(--line); }
.month-label { font-size: 9px; fill: var(--muted); }
/* The band a cycle runs for, start of build to end of cooldown. It carries its
   own number, so the ground only has to say "there is a cycle here"; the dashed
   rule inside it is where one closes. */
.cycle-band { fill: var(--surface-2); }
.band-rule { stroke: var(--line); }
.cycle-rule { stroke: var(--line); stroke-dasharray: 3 3; }
.cycle-label { font-size: 10px; fill: var(--accent); font-weight: 600; }
.today { stroke: var(--danger); stroke-width: 1.5; }
.today-label { font-size: 10px; fill: var(--danger); font-weight: 600; }
rect.bar { rx: 3; }
rect.st-shaping { fill: var(--st-shaping); }
rect.st-ready { fill: var(--st-ready); }
rect.st-in_progress { fill: var(--st-in_progress); }
rect.st-done { fill: var(--st-done); }
rect.st-shelved { fill: var(--st-shelved); }
/* An assumed appetite and work nobody is on are hatched, not outlined: the
   outline says "overruns its cycle", and one channel carrying three facts says
   none of them. Drawn as a second rect over the bar so the status colour stays
   underneath, and transparent to the pointer so the bar is still what you hover. */
rect.mark { rx: 3; pointer-events: none; }
rect.mark-estimated { fill: url(#hatch-estimated); }
rect.mark-unowned { fill: url(#hatch-unowned); }
rect.late { stroke: var(--danger); stroke-width: 1.5; }
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
    const response = await fetch('/api/asset', {
      method: 'POST', headers: {'content-type': file.type}, body: file,
    });
    const answer = await response.json();
    const alt = (file.name || 'image').replace(/\.[^.]+$/, '').replace(/[\[\]]/g, '');
    area.value = area.value.replace(
      token, response.ok ? `![${alt}](${answer.path})` : ''
    );
    area.dispatchEvent(new Event('input', {bubbles: true}));
    status.textContent = response.ok
      ? (answer.fresh ? `${answer.path} uploaded` : `${answer.path} — already in the plan`)
      : (answer.detail || 'that upload was refused');
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

function attachSuggest(input) {
  const source = SUGGEST[input.dataset.suggest] || [];
  const multi = input.dataset.type === 'list';
  const list = document.createElement('ul');
  list.className = 'suggest';
  list.hidden = true;
  input.insertAdjacentElement('afterend', list);
  let active = -1;

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

  function close() { list.hidden = true; list.innerHTML = ''; active = -1; }

  function open() {
    const needle = typed();
    const matches = source
      .filter(item => (item.value + ' ' + item.label).toLowerCase().includes(needle))
      .filter(item => !multi || !tokens().slice(0, -1).includes(item.value))
      .slice(0, 8);
    list.innerHTML = matches
      .map((m, i) => `<li data-value="${m.value}" class="${i === 0 ? 'on' : ''}">` +
        `${m.value}${m.label ? ` <span class="dim">${m.label}</span>` : ''}</li>`).join('');
    active = matches.length ? 0 : -1;
    list.hidden = !matches.length;
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
      items[active]?.classList.remove('on');
      active = (active + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      items[active].classList.add('on');
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

_CONTROL = """
{% if f.type in ("status", "priority") %}
<select name="{{ f.name }}" data-type="text" class="field"
        {% if f.gate %}data-required-from="{{ f.gate }}"{% endif %}>
  {% for s in (statuses if f.type == "status" else priorities) %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{ s }}</option>
  {% endfor %}
</select>
{% elif f.type == "bool" %}
<input type="checkbox" name="{{ f.name }}" data-type="bool" class="field"
       {% if f.value %}checked{% endif %}>
{% elif f.type == "date" %}
<input type="date" name="{{ f.name }}" data-type="date" value="{{ f.text }}" class="field"
       {% if f.gate %}data-required-from="{{ f.gate }}"{% endif %}>
{% else %}
<input name="{{ f.name }}" data-type="{{ f.type }}" value="{{ f.text }}" class="field"
       autocomplete="off"
       {% if f.list %}data-suggest="{{ f.list }}"{% endif %}
       {% if f.gate %}data-required-from="{{ f.gate }}"{% endif %}>
{% endif %}
"""


def _control_html(field: dict) -> str:
    return _ENV.from_string(_CONTROL).render(
        f=field, statuses=STATUSES, priorities=PRIORITIES
    )


_FIELDS = """
{% for f in fields %}
<label>{{ f.name }}{{ f.control|safe }}</label>
{% endfor %}
<label class="wide">body
  <textarea name="body" rows="{{ rows }}">{{ body }}</textarea>
</label>
"""


def _fields_html(fields: list[dict], body: str, rows: int = 18) -> str:
    """The same controls whether an entity exists yet or not.

    Rendered through `_control_html` rather than a second copy of the markup: two
    copies drift the first time one gains an attribute, and the drift shows up as
    a field that autocompletes when you edit it and not when you create it.
    """
    return _ENV.from_string(_FIELDS).render(
        fields=[{**f, "control": _control_html(f)} for f in fields], body=body, rows=rows
    )


_NEW = """
<article class="entity editing">
  <p class="back"><a href="{{ links.table }}">← table</a></p>
  <p class="editbar">
    <button type="button" id="save">Create</button>
    <span id="state"></span>
  </p>
  <h1><input name="title" data-type="text" form="edit" value=""
             class="field title-field" placeholder="Title"></h1>
  <p class="meta">
    <label class="kindpick">kind
      <select id="kind">
        {% for k in kinds %}<option value="{{ k }}"
          {% if k == kind %}selected{% endif %}>{{ k }}</option>{% endfor %}
      </select>
    </label>
    · the id and the file are the server's to choose</p>
  <form id="edit" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <dl id="facts">
      {% for row in rows %}
      <dt data-kinds="{{ row.kinds }}">{{ row.label }}</dt>
      <dd data-kinds="{{ row.kinds }}">{{ row.control|safe }}</dd>
      {% endfor %}
    </dl>
    <ul id="problems" class="problems" hidden></ul>
    <p class="field bodybar">
      <button type="button" id="preview">Preview the body</button>
      <span class="hint">paste or drop an image to put it in the plan</span>
      <span class="hint" id="upload"></span>
    </p>
    <textarea name="body" class="field body-field" rows="14"
              placeholder="The shaping document."></textarea>
    <div class="doc" hidden></div>
  </form>
</article>
{{ combobox|safe }}
<script>
const FORM = document.getElementById('edit');
const STATE = document.getElementById('state');
const PROBLEMS = document.getElementById('problems');
const KIND = document.getElementById('kind');
const ORDER = STATUS_ORDER_JSON;

// Every kind's fields are on the page and the ones this kind does not have are
// hidden, rather than each kind being its own round trip. Switching kind after
// typing a title used to mean typing it again.
function showKind() {
  for (const element of FORM.querySelectorAll('[data-kinds]'))
    element.hidden = !element.dataset.kinds.split(' ').includes(KIND.value);
}
KIND.onchange = showKind;
showKind();

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
    try { value = read(control); } catch (error) { STATE.textContent = error.message; return; }
    const empty = value === null || (Array.isArray(value) && !value.length);
    const waived = control.name === 'reviewers' &&
      FORM.querySelector('[name=review_waived]')?.checked;
    const gate = control.dataset.requiredFrom;
    // Cumulative: a field demanded from `ready` is demanded at every status after
    // it, which is why this compares positions rather than equality.
    if (gate && empty && !waived && ORDER.indexOf(status) >= ORDER.indexOf(gate))
      missing.push(control.name);
    if (!empty) fields[control.name] = value;
  }
  const title = document.querySelector('.title-field');
  if (title.value.trim()) fields.title = title.value.trim(); else missing.push('title');
  if (missing.length) {
    PROBLEMS.hidden = false;
    PROBLEMS.innerHTML =
      `<li>still needed at status ${status}: ${missing.join(', ')}</li>`;
    return;
  }
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
  location.href = '/detail/' + answer.id;
};
</script>
"""

_DETAIL = """
{% if not single %}<div class="toc">
  {% for group in groups %}
  <h2 class="tocgroup">{{ group.status }}
    <span class="tally">{{ group.entities|length }}</span></h2>
  <ul>
    {% for e in group.entities %}
    <li><a href="{{ links.entity }}{{ e.id }}">{{ e.title }}</a>
        <span class="tocmeta">{{ e.kind }} · {{ e.owner or "unowned" }}</span></li>
    {% endfor %}
  </ul>
  {% endfor %}
</div>{% endif %}
{% for e in entities %}
<article id="{{ e.id }}" class="entity">
  <p class="back"><a href="{{ links.detail }}">← all</a></p>
  {% if editable %}
  <p class="editbar">
    <button type="button" id="toggle">Edit</button>
    <button type="button" id="save" hidden>Save</button>
    <span id="state"></span>
  </p>
  {% endif %}
  <h1><span class="read">{{ e.title }}</span></h1>
  <p class="meta"><code>{{ e.id }}</code> · {{ e.kind }} · <b>{{ e.status }}</b>
     {% if e.parent %}· in {{ e.parent_link|safe }}{% endif %}</p>
  {% if editable %}
  <form id="edit" data-id="{{ e.id }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <input name="title" data-type="text" value="{{ e.title }}" class="field title-field">
  {% endif %}
  <dl id="facts">
    {% for row in e.rows %}
    <dt class="{% if row.derived %}derived{% endif %}
               {% if row.editing_only %}editing-only{% endif %}">{{ row.label }}</dt>
    <dd class="{% if row.derived %}derived{% endif %}
               {% if row.editing_only %}editing-only{% endif %}">
      <span class="read">{{ row.display|safe }}</span>
      {% if editable and row.control %}{{ row.control|safe }}{% endif %}
    </dd>
    {% endfor %}
  </dl>
  {% if e.problems %}<ul class="problems">
    {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
  <div class="doc read">{{ e.body|safe }}</div>
  {% if editable %}
    <p class="field bodybar">
      <button type="button" id="preview">Preview the body</button>
      <span class="hint">paste or drop an image to put it in the plan</span>
      <span class="hint" id="upload"></span>
    </p>
    <textarea name="body" class="field body-field">{{ e.raw_body }}</textarea>
    <div id="body-preview" class="field doc" hidden></div>
    <div id="conflict" hidden></div>
  </form>
  {% endif %}
</article>
{% endfor %}
<div id="grip" title="drag to set the width"></div>
<script>
// The reader decides how wide prose should be. Remembered per browser rather than
// per entity: it is a property of the screen it is being read on, not of the plan.
const grip = document.getElementById('grip');
const root = document.documentElement;
const saved = localStorage.getItem('openproj:measure');
if (saved) root.style.setProperty('--measure', saved);

function place() {
  const article = document.querySelector('article.entity');
  if (article) grip.style.left = article.getBoundingClientRect().right + 'px';
}
place();
addEventListener('resize', place);

grip.onpointerdown = event => {
  grip.setPointerCapture(event.pointerId);
  grip.classList.add('dragging');
  const move = e => {
    const width = Math.max(320, e.clientX - 20);
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
{% if editable %}<script>
// Only what changed travels. Serialising the whole form would send back every
// field as this tab last saw it, overwriting whatever somebody else changed while
// it sat open — which is exactly what scoped compare-and-swap exists to prevent.
const FORM = document.getElementById('edit');
const ORIGINAL = {};
const CONTROLS = [...FORM.querySelectorAll('[data-type]')];
const BODY = FORM.querySelector('[name=body]');
attachUploads(BODY, document.getElementById('upload'));
const STATE = document.getElementById('state');
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

function show(editing) {
  // One class on the article. Each fact is a single row whose value swaps for its
  // control, so nothing is shown twice and the page does not jump when you start.
  document.querySelector('article.entity').classList.toggle('editing', editing);
  document.getElementById('save').hidden = !editing;
  document.getElementById('toggle').textContent = editing ? 'Cancel' : 'Edit';
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
    STATE.textContent = error.message;
    return;
  }
  const body = BODY.value === ORIGINAL_BODY ? null : BODY.value;
  if (!Object.keys(fields).length && body === null) {
    STATE.textContent = 'nothing changed';
    return;
  }

  STATE.textContent = 'saving…';
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
    STATE.textContent = 'not saved';
    return;
  }
  if (!response.ok) { STATE.textContent = answer.detail || 'refused'; return; }
  localStorage.removeItem(DRAFT);
  location.reload();
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
  STATE.textContent = 'unsaved draft restored';
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
article.entity {
  width: var(--measure, 52rem); max-width: 100%; margin-bottom: 3rem; position: relative;
}
#grip {
  position: fixed; top: 0; bottom: 0; width: 10px; cursor: col-resize; z-index: 30;
}
#grip::before {
  content: ""; position: absolute; inset: 0 4px; background: var(--line);
  transition: background .15s;
}
#grip:hover::before, #grip.dragging::before { background: var(--accent); }
article.entity h1 { font-size: 1.5rem; margin: .2rem 0; }
.meta { color: var(--muted); margin-top: 0; }
.back { margin: 0 0 .5rem; font-size: 12px; }
.editbar { display: flex; gap: .4rem; align-items: center; margin: .4rem 0 1rem; }
#state { color: var(--muted); font-size: 12px; }

dl { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: .45rem 1rem; margin: 1rem 0; }
dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
     padding-top: .35rem; }
dd { margin: 0; }
dt.derived, dd.derived { font-style: italic; }
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

# Which status first demands each field. Cumulative, per spec 5.1: permissive when
# an idea is captured, strict once work starts, strictest when it is claimed done.
# An HTML `required` attribute cannot express this, because what is required
# depends on the status chosen in the same form a moment ago. This is a copy of
# validate_all and is only ever a courtesy — the server's answer is the truth.
REQUIRED_FROM = {
    "owner": "ready",
    "reviewers": "ready",
    "effort_weeks": "ready",
    "appetite_weeks": "ready",
    "shaped_by": "ready",
    "assigned_on": "in_progress",
    "prs": "done",
}
# Fields only one kind has, so the create form can hide the rest.
KIND_ONLY = {"appetite_weeks": "pitch", "shaped_by": "pitch", "effort_weeks": "task"}
PREFIX = {"project": "proj", "pitch": "pitch", "task": "task"}

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
}


def _editable_for(entity: Entity) -> list[dict]:
    """The fields this kind actually has, with the type a form must coerce back to."""
    return [
        {
            "name": name,
            "type": kind,
            "value": getattr(entity, name),
            "gate": REQUIRED_FROM.get(name),
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
    for field in _editable_for(entity):
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
        elif field["type"] == "list":
            display = field["text"] or empty
        else:
            display = str(field["text"]) if field["text"] not in ("", None) else empty
        rows.append(
            {
                "label": LABELS.get(name, name),
                "display": display,
                "control": _control_html(field),
                "derived": False,
                # "Review waived: no" is a line that says nothing. The row still
                # exists while editing, because turning the waiver on is the whole
                # point of having it; it just does not clutter the read view.
                "editing_only": name == "review_waived" and not entity.review_waived,
            }
        )
    overrun = (
        f" · overruns cycle {entity.cycle} by {span.overruns_cycle_weeks:.1f} weeks"
        if span and span.overruns_cycle_weeks
        else ""
    )
    rows.append(
        {
            "label": "Scheduled",
            "display": (f"{span.start} → {span.end}{overrun}" if span else empty),
            "control": "",
            "derived": True,
            "editing_only": False,
        }
    )
    if why:
        rows.append(
            {
                "label": "Why then",
                "display": why.text,
                "control": "",
                "derived": True,
                "editing_only": False,
            }
        )
    rows.append(
        {
            "label": "Blocks",
            "display": _links(index.blocks[entity.id], index, links) or empty,
            "control": "",
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
        for field in _editable_for(blank):
            if field["name"] == "title":
                continue          # the title is the heading, not a row
            row = rows.setdefault(
                field["name"],
                {"label": LABELS.get(field["name"], field["name"]),
                 "control": _control_html(field), "kinds": []},
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
    )
    body = body.replace("STATUS_ORDER_JSON", json.dumps(list(STATUSES)))
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
    }


_CYCLE = """
<p class="editbar">
  <a href="{{ links.cycles }}">← all cycles</a>
  {% if editable %}
  <button type="button" id="save" disabled>Save</button>
  <span id="state"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
  {% endif %}
</p>
<h1>Cycle {{ c.number }}</h1>
<p class="meta">{{ c.starts_on }} → builds until <b>{{ c.builds_until }}</b>
   → cool-down ends {{ c.ends_on }}</p>

<form id="setup" onsubmit="return false">
  <dl id="facts">
    <dt>Starts on</dt>
    <dd><span class="read">{{ c.starts_on }}</span>
        <input type="date" name="starts_on" data-type="date" value="{{ c.starts_on }}"
               class="field"></dd>
    <dt>Build weeks</dt>
    <dd><span class="read">{{ c.build_weeks }}</span>
        <input name="build_weeks" data-type="number" value="{{ c.build_weeks }}"
               class="field"></dd>
    <dt>Cool-down weeks</dt>
    <dd><span class="read">{{ c.cooldown_weeks }}</span>
        <input name="cooldown_weeks" data-type="number" value="{{ c.cooldown_weeks }}"
               class="field"></dd>
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
    {% if editable %}<td><button type="button" class="drop" title="Take out of this
      cycle">&#128465;</button></td>{% else %}<td></td>{% endif %}
    <td>{{ row.login }}</td>
    <td><span class="read">{{ (row.rate * 100)|round|int }}%</span>
        <input class="field rate" data-login="{{ row.login }}" value="{{ row.rate }}"
               autocomplete="off"></td>
    <td class="derived capacity">{{ '%.1f'|format(row.capacity) }} wk</td>
    <td class="derived">{{ '%.1f'|format(row.held) }} wk</td>
    <td><span class="bar"><span style="width: {{ row.percent }}%"></span></span></td>
    <td class="derived">{{ row.until }}</td>
  </tr>
  {% endfor %}
</tbody></table>
{% if editable %}
<p class="editbar"><input id="joining" placeholder="login" data-suggest="people"
     autocomplete="off">
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
  {% for row in c.candidates %}
  <tr data-id="{{ row.id }}" class="{{ 'carried' if row.carried else '' }}">
    <td><input type="checkbox" class="bet" autocomplete="off"
               {{ 'checked' if row.in_cycle else '' }}
               {{ 'disabled' if row.carried else '' }}></td>
    <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
    <td>{{ row.kind }}</td>
    <td>{{ row.status }}</td>
    <td><input class="live" data-field="{{ row.size_field }}" data-type="number"
               autocomplete="off" value="{{ row.size }}"
               placeholder="{{ row.size_hint }}"></td>
    <td><input class="live wide" data-field="assignees" data-type="list"
               data-suggest="people" autocomplete="off" value="{{ row.assignees }}"></td>
    <td><input class="live wide" data-field="reviewers" data-type="list"
               data-suggest="people" autocomplete="off" value="{{ row.reviewers }}"></td>
    <td class="derived">{{ row.cycle }}</td>
  </tr>
  {% endfor %}
</tbody></table></div>
<div class="doc">{{ c.body|safe }}</div>
{% if editable %}
{{ combobox|safe }}
<script>
const BASE = document.getElementById('base');
const STATE = document.getElementById('state');
const NUMBER = {{ c.number }};

function say(message) { STATE.textContent = message; }

async function put(fields) {
  const response = await fetch(`/api/cycle/${NUMBER}`, {
    method: 'PUT', headers: {'content-type': 'application/json'},
    body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
  });
  const answer = await response.json();
  if (!response.ok) { say(answer.detail || 'refused'); return null; }
  BASE.value = answer.commit || BASE.value;
  return answer;
}

const SAVE = document.getElementById('save');
let ROSTER_DIRTY = false;

// The whole roster in one write. A name left out means somebody was taken off,
// which per-field merging would silently undo.
async function saveSetup(quiet) {
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
  if (!quiet) say('setup saved');
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
    say(`${PENDING.size} unsaved`);
  };
}

// Nothing is written until Save. A betting table is a conversation — a row gets
// staffed, argued about and restaffed inside a minute — and one commit per
// keystroke turns that into a git history nobody can read and a plan that is
// briefly wrong in public between two halves of one decision.
const PENDING = new Map();   // entity id -> {field: value}

function pend(id, field, value) {
  PENDING.set(id, {...(PENDING.get(id) || {}), [field]: value});
  mark();
}

function mark() {
  // Counted in edits rather than in commits: two fields on one row is two things
  // somebody changed, even though it is one write.
  let edits = ROSTER_DIRTY ? 1 : 0;
  for (const fields of PENDING.values()) edits += Object.keys(fields).length;
  SAVE.disabled = edits === 0;
  SAVE.textContent = edits ? `Save ${edits} change${edits === 1 ? '' : 's'}` : 'Save';
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
  if (ROSTER_DIRTY && !(await saveSetup(true))) { mark(); return false; }
  // One entity per commit, each against the commit the last one returned: a
  // batch that fails half way is still a readable history rather than one commit
  // nobody can unpick.
  let written = 0;
  for (const [id, fields] of [...PENDING]) {
    const response = await fetch(`/api/entity/${id}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
    });
    const answer = await response.json();
    if (!response.ok) {
      say(`${id}: ${answer.detail
            || (answer.problems || []).map(p => p.message).join('; ') || 'refused'}`
          + (written ? ` — ${written} already saved` : ''));
      mark();
      return false;
    }
    BASE.value = answer.commit || BASE.value;
    PENDING.delete(id);
    written += 1;
  }
  mark();
  say(quiet ? `autosaved ${written}` : `saved ${written}`);
  return true;
}

SAVE.onclick = async () => {
  if (await flush(false)) location.reload();
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
    say(`${PENDING.size} unsaved`);
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

function dropRow(button) {
  button.onclick = () => {
    const row = button.closest('tr');
    say(`${row.dataset.login} taken out — press Save to commit it`);
    row.remove();
    recount();
    dirty();
  };
}
document.querySelectorAll('#roster .drop').forEach(dropRow);

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
  row.innerHTML =
    `<td><button type="button" class="drop" title="Take out of this cycle">&#128465;</button></td>`
    + `<td>${login}</td>`
    + `<td><input class="field rate" data-login="${login}" value="1.0"></td>`
    + `<td class="derived capacity">—</td>`
    + `<td class="derived">${(HELD[login] || 0).toFixed(1)} wk</td>`
    + `<td><span class="bar"><span style="width: 0%"></span></span></td>`
    + `<td class="derived">—</td>`;
  document.getElementById('roster').append(row);
  dropRow(row.querySelector('.drop'));
  JOINING.value = '';
  recount();
  dirty();
  say(`${login} added — press Save to commit it`);
};
</script>
{% endif %}
"""

_CYCLE_STYLE = """
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
.bar { display: inline-block; width: 140px; height: 8px; background: var(--line);
       border-radius: 4px; overflow: hidden; vertical-align: middle; }
.bar > span { display: block; height: 100%; background: var(--accent); }
tr.over .bar > span { background: var(--danger); }
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
#save:not(:disabled) { border-color: var(--accent); color: var(--accent); }
"""

_CYCLES = """
<p class="hint">Every cycle the plan has a record for. A cycle sets the build and
  cool-down weeks and who is available for it.</p>
<div class="toc"><ul>
  {% for c in cycles %}
  <li><a href="{{ links.cycle }}{{ c.number }}">Cycle {{ c.number }}</a>
      <span class="tocmeta">{{ c.starts_on }} → {{ c.builds_until }}
        · {{ c.people }} people · {{ '%.1f'|format(c.held) }} of
        {{ '%.1f'|format(c.capacity) }} weeks bet</span></li>
  {% endfor %}
</ul></div>
{% if editable %}
<p class="editbar">
  <label class="facet">number
    <input id="number" type="number" value="{{ next.number }}" min="0" max="9999"></label>
  <label class="facet">starts
    <input id="starts" type="date" value="{{ next.starts_on }}"></label>
  <label class="facet">build weeks
    <input id="build" type="number" value="{{ next.build_weeks }}" step="0.5"></label>
  <label class="facet">cool-down
    <input id="cooldown" type="number" value="{{ next.cooldown_weeks }}" step="0.5"></label>
  <button type="button" id="start">Start it</button>
  <span class="hint">{{ next.roster|length }} people carried from cycle
    {{ next.number - 1 }}</span>
  <span id="state"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</p>
<script>
const ROSTER = ROSTER_JSON;
// Defaults carried from the last cycle: the length rarely changes, the next one
// starts when the last one ends, and mostly the same people are in it at mostly
// the same rates. All of it is corrected on the cycle's own page afterwards.
document.getElementById('start').onclick = async () => {
  const number = Number(document.getElementById('number').value);
  const response = await fetch(`/api/cycle/${number}`, {
    method: 'PUT', headers: {'content-type': 'application/json'},
    body: JSON.stringify({
      base_commit: document.getElementById('base').value,
      fields: {
        starts_on: document.getElementById('starts').value,
        build_weeks: Number(document.getElementById('build').value),
        cooldown_weeks: Number(document.getElementById('cooldown').value),
        availability: ROSTER,
      },
      body: null,
    }),
  });
  const answer = await response.json();
  if (!response.ok) {
    document.getElementById('state').textContent = answer.detail || 'refused';
    return;
  }
  location.href = '/cycle/' + number;
};
</script>
{% endif %}
"""

_PEOPLE = """
<p class="hint">Everyone named anywhere in the plan, and what they are on the hook for.</p>
<div id="controls">
  <input id="q" type="search" placeholder="Search person, entity, id">
  <div class="facets">
  <label class="facet">role
    <select data-attr="role"><option value="">all</option>
      {% for value in facets.role %}<option>{{ value }}</option>{% endfor %}
    </select>
  </label>
  <label class="facet">kind
    <select data-attr="kind"><option value="">all</option>
      {% for value in facets.kind %}<option>{{ value }}</option>{% endfor %}
    </select>
  </label>
  <label class="facet">status
    <select data-attr="status"><option value="">all</option>
      {% for value in facets.status %}<option>{{ value }}</option>{% endfor %}
    </select>
  </label>
  </div>
</div>
<div id="summary"><span id="shown">{{ people|length }}</span> of {{ people|length }} people</div>
{% for person in people %}
<section class="person" data-login="{{ person.login }}">
  <h2>{{ person.login }}
    <span class="tally">{{ person.counts }}</span></h2>
  <table class="roles">
    <thead><tr><th>role</th><th>entity</th><th>kind</th><th>status</th>
      <th>scheduled</th></tr></thead>
    <tbody>
      {% for row in person.rows %}
      <tr data-role="{{ row.role }}" data-kind="{{ row.kind }}" data-status="{{ row.status }}"
          data-text="{{ row.search }}">
        <td class="role">{{ row.role }}</td>
        <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
        <td>{{ row.kind }}</td>
        <td>{{ row.status }}</td>
        <td class="derived">{{ row.span }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="empty" hidden>Nothing here matches.</p>
</section>
{% endfor %}
<script>
// A person whose own name matches keeps all their rows: searching for somebody is
// asking what they are on the hook for, not asking to see only the rows that
// happen to repeat their name.
const SECTIONS = [...document.querySelectorAll('section.person')];
const FILTERS = [...document.querySelectorAll('#controls select')];
const q = document.getElementById('q');
const shown = document.getElementById('shown');

function apply() {
  const text = q.value.trim().toLowerCase();
  const want = FILTERS.filter(s => s.value).map(s => [s.dataset.attr, s.value]);
  let visible = 0;
  for (const section of SECTIONS) {
    const person = section.dataset.login.toLowerCase();
    let kept = 0;
    for (const row of section.querySelectorAll('tbody tr')) {
      const matches = want.every(([attr, value]) => row.dataset[attr] === value)
        && (!text || person.includes(text) || row.dataset.text.includes(text));
      row.hidden = !matches;
      kept += matches ? 1 : 0;
    }
    section.hidden = kept === 0;
    section.querySelector('.empty').hidden = kept > 0;
    visible += kept > 0 ? 1 : 0;
  }
  shown.textContent = visible;
}

q.oninput = apply;
FILTERS.forEach(select => { select.onchange = apply; });
</script>
"""

_PEOPLE_STYLE = """
.hint { max-width: 46rem; font-size: 13px; }
section.person { margin: 2rem 0; }
section.person h2 { font-size: 1.05rem; margin-bottom: .3rem; }
.tally { color: var(--muted); font-size: 12px; font-weight: 400; margin-left: .5rem; }
table.roles { border-collapse: collapse; width: 100%; max-width: 60rem; font-size: 13px; }
table.roles th, table.roles td {
  border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left;
}
table.roles th { color: var(--muted); font-weight: 600; font-size: 12px; }
td.role { color: var(--accent); font-size: 12px; text-transform: uppercase;
          letter-spacing: .04em; white-space: nowrap; }
"""

_ROLES = (("owner", "owner"), ("assignees", "assignee"), ("reviewers", "reviewer"),
          ("shaped_by", "shaper"))

# Most answerable first. Grouped by entity — which is what building the rows one
# entity at a time gave you — a person with twenty rows had their four ownerships
# scattered through it, and ownership is the thing being on the page is for.
_ROLE_ORDER = ("owner", "assignee", "shaper", "reviewer")


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
    build_weeks = plan.build_weeks if plan else 0.0
    listed = list(plan.availability) if plan else []

    # Exactly who was named. Being on the roster IS being in the cycle, so a name
    # is added deliberately rather than appearing because somebody was assigned
    # something — which would make the roster a report instead of a decision.
    people = []
    for login in sorted(listed, key=str.lower):
        rate = plan.availability.get(login, nominal) if plan else nominal
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
        "starts_on": plan.starts_on.isoformat() if plan else "—",
        "builds_until": plan.builds_until.isoformat() if plan else "—",
        "ends_on": plan.ends_on.isoformat() if plan else "—",
        "build_weeks": f"{build_weeks:g}",
        "cooldown_weeks": f"{plan.cooldown_weeks:g}" if plan else "—",
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
    body = body.replace("HELD_JSON", json.dumps(view["held"]))
    return _page(
        f"openproj — cycle {number}",
        body,
        _DETAIL_STYLE + _CYCLE_STYLE + _SUGGEST_STYLE,
        links,
    )


def render_cycles(
    index: Index, links: Links = STATIC, base_commit: str | None = None
) -> str:
    rows = []
    for number in sorted(index.plans, reverse=True):
        view = _cycle_view(index, number)
        rows.append(
            {
                "number": number,
                "starts_on": view["starts_on"],
                "builds_until": view["builds_until"],
                "people": len(view["people"]),
                "held": sum(p["held"] for p in view["people"]),
                "capacity": sum(p["capacity"] for p in view["people"]),
            }
        )
    last = index.plans[max(index.plans)] if index.plans else None
    body = _ENV.from_string(_CYCLES).render(
        cycles=rows,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        # The next cycle starts when the last one ends and is the same length,
        # because both are true far more often than not.
        next={
            "number": (max(index.plans) + 1) if index.plans else 1,
            "starts_on": (last.ends_on + timedelta(days=1)).isoformat()
            if last
            else index.today.isoformat(),
            "build_weeks": f"{last.build_weeks:g}" if last else "4",
            "cooldown_weeks": f"{last.cooldown_weeks:g}" if last else "2",
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
        "ROSTER_JSON", json.dumps(last.availability if last else {})
    )
    return _page("openproj — cycles", body, _DETAIL_STYLE + _CYCLE_STYLE, links)


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

    people = []
    # Case-folded, or every capitalised login sorts ahead of the lowercase ones and
    # "alphabetical" means ASCII to the page and nothing to the reader.
    for login, rows in sorted(held.items(), key=lambda pair: pair[0].lower()):
        tally = {role: sum(1 for r in rows if r["role"] == role) for _, role in _ROLES}
        people.append(
            {
                "login": login,
                "rows": rows,
                "counts": ", ".join(f"{n} as {role}" for role, n in tally.items() if n),
            }
        )
    # Only values that are actually on the page: a filter offering a status
    # nobody holds is a dead end that looks like a bug.
    facets = {
        key: sorted({row[key] for rows in held.values() for row in rows})
        for key in ("role", "kind", "status")
    }
    body = _ENV.from_string(_PEOPLE).render(people=people, links=links, facets=facets)
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
        single=only is not None,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        statuses=STATUSES,
        combobox=_combobox_html(index),
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
    data = _suggestions(index) if index else {"people": [], "entities": [], "tags": []}
    return _COMBOBOX.replace("SUGGEST_JSON", json.dumps(data))


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
    blockers = sum(1 for p in index.problems if p.severity == "blocker")
    body = _ENV.from_string(_TABLE).render(
        payload=payload,
        blockers=blockers,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        links=links,
        facets=_facets_html(index),
        filters=_FILTER_JS,
        combobox=_combobox_html(index),
    )
    body = body.replace("PAYLOAD_JSON", json.dumps(payload)).replace("ENTITY_HREF", links.entity)
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
        total=len(index.entities),
    )
    body = body.replace("ELEMENTS_JSON", json.dumps(_elements(index)))
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
        facets=_facets_html(index),
        filters=_FILTER_JS,
    )
    # The rows the shared `matches()` reads, for the bars that were drawn. Not the
    # whole plan: a bar that is not on this window cannot be filtered onto it.
    payload = {"rows": timeline["rows"], "human": HUMAN}
    body = body.replace("BARS_JSON", json.dumps(payload))
    return _page("openproj — timeline", body, _TIMELINE_STYLE, links)


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
