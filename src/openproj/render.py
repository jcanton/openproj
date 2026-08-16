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

import json
import os
import re
from datetime import date, timedelta
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
_HEADER_PX = 26
_LABEL_CHARS = 40


def _clip(text: str) -> str:
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "\u2026"
# A status is a class, not a colour baked into the markup: the same rect has to
# be one colour on a white ground and another on a dark one, and a `fill`
# attribute written at render time cannot change when somebody flips the toggle.
def _status_class(status: str) -> str:
    return f"st-{status}" if status in STATUSES else "st-ready"


def _inline(name: str) -> str:
    return (_static_dir() / name).read_text(encoding="utf-8")


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
        "problems": [p.message for p in index.problems if p.entity_id == entity_id],
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
        # One list of what a person may change, shared with the detail page. Two
        # lists drift the first time a field is added, and silently.
        "editable": {k: v for k, v in EDITABLE.items() if k not in _TABLE_DERIVED},
        "suggests": SUGGESTS,
        "choices": {"status": list(STATUSES), "priority": list(PRIORITIES)},
    }


def _elements(index: Index) -> list[dict]:
    elements: list[dict] = []
    for entity_id, entity in index.entities.items():
        data = {
            "id": entity_id,
            # The title alone. The id is on every other page and in the URL the
            # node opens; on a box 150px wide it cost a line of the only text
            # anybody reads the graph for.
            "label": entity.title,
            "status": entity.status,
            "priority": entity.priority,
            "kind": entity.kind,
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
    drawn = {i: s for i, s in index.spans.items() if not s.unscheduled}
    if not drawn:
        return {
            "bars": [], "rules": [], "months": [], "today_x": None, "header": _HEADER_PX,
            "width": _LEFT_PX, "height": _ROW_PX, "origin": None, "last": None, "zoom": "",
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

    order = sorted(drawn, key=lambda i: (drawn[i].start, i))
    bars = []
    for row, entity_id in enumerate(order):
        span = drawn[entity_id]
        visible_start, visible_end = max(span.start, origin), min(span.end, last)
        entity = index.entities[entity_id]
        classes = ["bar"]
        if span.estimated:
            classes.append("estimated")
        if span.unowned:
            classes.append("unowned")
        if span.overruns_cycle_weeks:
            classes.append("late")
        explanation = index.explanations.get(entity_id)
        bars.append(
            {
                "id": entity_id,
                "label": _clip(entity.title),
                "full": f"{entity.title} ({entity_id})",
                "classes": " ".join(classes),
                "x": x(visible_start),
                "y": row * _ROW_PX + _HEADER_PX,
                "width": max(
                    day_px, x(visible_end + timedelta(days=1)) - x(visible_start)
                ),
                "colour": _status_class(entity.status),
                "owner": entity.owner or "unowned",
                "tip": explanation.text if explanation else "Starts as soon as it can.",
            }
        )
    rules = [
        {"x": x(window[1]), "label": f"cycle {number}"}
        for number, window in sorted(index.cycles.items())
        if origin <= window[1] <= last
    ]
    return {
        "bars": bars,
        "rules": rules,
        "months": _month_ticks(origin, last, x),
        # A window that excludes today has no today line. Drawing it at a clamped
        # coordinate would put "now" on an edge it is not on.
        "today_x": x(index.today) if origin <= index.today <= last else None,
        "origin": origin.isoformat(),
        "last": last.isoformat(),
        "zoom": zoom or "",
        "header": _HEADER_PX,
        "width": x(last) + 24,
        "height": len(bars) * _ROW_PX + _HEADER_PX + 20,
    }


def _month_ticks(origin: date, last: date, x) -> list[dict]:
    """A bar chart with no dates on it is a picture, not a plan."""
    ticks, cursor = [], date(origin.year, origin.month, 1)
    while cursor <= last:
        if cursor >= origin:
            ticks.append({"x": x(cursor), "label": cursor.strftime("%b %Y")})
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


STATIC = Links()
ROUTES = Links(
    table="/", detail="/detail", graph="/graph", timeline="/timeline",
    entity="/detail/", new="/new", people="/people",
    cycles="/cycles", cycle="/cycle/",
)

_MD = MarkdownIt("commonmark", {"html": False}).enable("table")
_PR = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


def _pr_link(ref: str) -> str:
    """A dead PR reference teaches people the field is decorative."""
    repo, _, number = ref.partition("#")
    return f'<a href="https://github.com/{repo}/pull/{number}">{ref}</a>'


_REMOTE_IMG = re.compile(r'<img\s+src="(https?://[^"]+)"(?:[^>]*?alt="([^"]*)")?[^>]*>')


def _body_html(entity: Entity) -> str:
    """The shaping document, rendered, with PR references made clickable.

    A remote image in a shaping doc would make the page fetch from the network,
    which is exactly what inlining every library was for. Remote images become
    links instead: the reference survives, the dependency does not.
    """
    html = _MD.render(entity.body)
    html = _REMOTE_IMG.sub(
        lambda m: f'<a href="{m.group(1)}">{m.group(2) or "image"} (external image)</a>', html
    )
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
/* Three states, not two: an explicit choice stamps data-theme, and the default
   is no stamp at all, where only the media query separates one from the other.
   Every colour is a token so that nothing has its only definition inside a
   block that half the readers never match. */
:root {
  /* Named, not `light dark`: that means "follow the system", so a page stamped
     dark against a light system kept rendering its buttons, scrollbars and date
     pickers light — the parts of the page the stylesheet does not draw. */
  color-scheme: light;
  --bg: #ffffff; --fg: #1a2226; --surface: #ffffff;
  --line: #d7dfe1; --line-strong: #b7c5c9; --muted: #6a7a80;
  --accent: #0f5c6b; --on-accent: #ffffff;
  --danger: #9a3327; --warn: #8f5c07;
  --st-shaping: #b9a6c9; --st-ready: #8a93a5; --st-in_progress: #1f6f8b;
  --st-done: #3f7d58; --st-shelved: #b0b4bd;
  --on-status: #ffffff; --hatch: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #11181b; --fg: #dbe4e7; --surface: #182126;
    --line: #263539; --line-strong: #3a4d53; --muted: #8da0a8;
    --accent: #5cb9ca; --on-accent: #0b1214;
    --danger: #e0796a; --warn: #d6a33f;
    --st-shaping: #9b86ad; --st-ready: #717b8c; --st-in_progress: #2b7f9c;
    --st-done: #418062; --st-shelved: #7d828b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #11181b; --fg: #dbe4e7; --surface: #182126;
  --line: #263539; --line-strong: #3a4d53; --muted: #8da0a8;
  --accent: #5cb9ca; --on-accent: #0b1214;
  --danger: #e0796a; --warn: #d6a33f;
  --st-shaping: #9b86ad; --st-ready: #717b8c; --st-in_progress: #2b7f9c;
  --st-done: #418062; --st-shelved: #7d828b;
}
body { font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 1rem 1.25rem 3rem;
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
.empty { color: var(--line-strong); }
#moved { position: fixed; right: 1rem; bottom: 1rem; background: var(--accent);
         color: var(--on-accent);
         padding: .5rem .8rem; font-size: 13px; border-radius: 3px; }
#moved a { color: var(--on-accent); }
#moved .sha { font-family: ui-monospace, monospace; opacity: .7; }
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
const source = new EventSource('/api/events');
source.onmessage = event => {
  const {commit, changed} = JSON.parse(event.data);
  const here = location.pathname.split('/').pop();
  const mine = changed.includes(here);
  moved.hidden = false;
  moved.innerHTML = (mine ? 'This was just changed by somebody else. ' : 'The plan changed. ')
    + `<a href="">reload</a> <span class="sha">${commit.slice(0, 7)}</span>`;
};
</script>
{% endif %}
</body></html>
"""

_TABLE = """
<p class="editbar"><a class="button" href="{{ links.new }}">New entity</a>
   <span class="hint">double-click a cell to edit it</span>
   <span id="state"></span></p>
<div id="summary">
  <strong id="blocker-count">{{ blockers }}</strong> blocking problems ·
  <span id="shown">{{ payload.rows|length }}</span> of {{ payload.rows|length }} shown
</div>
<div id="controls">
  <input id="q" type="search" placeholder="Search title, tags, body">
  <div class="facets">
  {% for field in ['kind','priority','status','owner','assignees','reviewers',
                   'cycle','project','tags'] %}
  <label class="facet">{{ field }}
    <select data-field="{{ field }}"><option value="">all</option>
      {% for value in payload.facets.get(field, []) %}<option>{{ value }}</option>{% endfor %}
    </select>
  </label>
  {% endfor %}
  <label class="facet">state
    <select data-field="predicate"><option value="">all</option>
      {% for p in payload.predicates %}<option>{{ p }}</option>{% endfor %}
    </select>
  </label>
  </div>
</div>
<div class="table-scroll"><table id="rows"><thead><tr>
  <th data-sort="id">id</th><th data-sort="title">title</th>
  <th data-sort="priority">priority</th><th data-sort="status">status</th>
  <th data-sort="owner">owner</th><th data-sort="assignees">assignees</th>
  <th data-sort="reviewers">reviewers</th><th data-sort="cycle">cycle</th>
  <th data-sort="size">weeks</th>
  <th data-sort="start">start</th><th data-sort="end">end</th>
  <th data-sort="blocked_by">blockers</th><th>prs</th><th>tags</th>
</tr></thead><tbody></tbody></table></div>
{% if editable %}
<input type="hidden" name="base_commit" id="base" value="{{ base_commit }}">
<div id="row-conflict" hidden></div>
{% endif %}
<script id="payload" type="application/json">PAYLOAD_JSON</script>
{% if editable %}{{ combobox|safe }}{% endif %}
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const params = new URLSearchParams(location.search);
const tbody = document.querySelector('#rows tbody');

function wanted(field) { return params.getAll(field).filter(Boolean); }

function matches(row) {
  const q = (params.get('q') || '').trim().toLowerCase();
  if (q && !(row.title + ' ' + row.tags.join(' ')).toLowerCase().includes(q)) return false;
  // Every field the control bar offers. A field in one list and not the other is
  // a dropdown that changes the URL and filters nothing.
  for (const field of ['kind','status','owner','assignees','reviewers','priority',
                       'cycle','project','tags']) {
    const values = wanted(field);
    if (!values.length) continue;
    const held = [].concat(row[field] ?? []).map(String);
    if (!values.some(v => held.includes(v))) return false;
  }
  const preds = wanted('predicate');
  if (preds.length && !preds.some(p => row.predicates.includes(p))) return false;
  return true;
}

function cell(row, key) {
  const value = row[key];
  const derived = (key === 'start' || key === 'end') && row.derived;
  const text = Array.isArray(value) ? value.join(', ') : (value ?? '');
  // The title is the way into the shaping doc; the id is the way to cite it.
  // A cell can be a link and still be editable. Making everything editable first
  // is what silently turned the PR column into plain text.
  const shown = key === 'title'
    ? `<a href="ENTITY_HREF${row.id}">${text}</a>`
    : key === 'prs' ? (value || []).map(prLink).join(', ') : text;
  if (EDITABLE && key in EDITABLE)
    return `<td data-entity="${row.id}" data-field="${key}" class="edit">${shown}</td>`;
  if (key === 'title' || key === 'prs') return `<td>${shown}</td>`;
  return `<td class="${derived ? 'derived' : ''}">${text}</td>`;
}

function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${repo}/pull/${number}">${ref}</a>`;
}

function draw() {
  // Index-parallel with the header row above. Nothing enforces that at runtime,
  // so the two are edited together or every cell shifts one column left.
  const keys = ['id','title','priority','status','owner','assignees','reviewers','cycle',
                'size','start','end','blocked_by','prs','tags'];
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
  tbody.innerHTML = rows.map(row =>
    `<tr data-id="${row.id}" title="${(row.problems || []).join(' · ')}">` +
    keys.map(k => cell(row, k)).join('') + '</tr>').join('');
  document.getElementById('shown').textContent = rows.length;
  // Sorting redraws without reloading, so the marker has to move with it. Set
  // once at load, it stayed on whatever the URL said when the page opened.
  for (const th of headers)
    th.classList.toggle('sorted', th.dataset.sort === sort);
  for (const select of document.querySelectorAll('select[data-field]'))
    select.value = params.get(select.dataset.field) || '';
  document.getElementById('q').value = params.get('q') || '';
}

function update(field, value) {
  if (value) params.set(field, value); else params.delete(field);
  history.replaceState(null, '', '?' + params.toString());
  draw();
}

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

async function saveCell(cell, value) {
  const field = cell.dataset.field;
  let coerced;
  try {
    coerced = coerce(EDITABLE[field], value);
  } catch (error) {
    document.getElementById('state').textContent = `${field} ${error.message}`;
    return;
  }
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
  BASE.value = answer.commit;
  DATA.rows[cell.dataset.entity][field] = coerced;
  draw();
}

if (EDITABLE) {
  tbody.addEventListener('dblclick', event => {
    const cell = event.target.closest('td.edit');
    if (!cell || cell.querySelector('input')) return;
    const was = cell.textContent;
    const field = cell.dataset.field;
    const suggest = SUGGESTS[field];
    const closed = CHOICES[EDITABLE[field]];
    // A closed set is chosen, never typed. Free text over three options is a way
    // to write `in progres` into the corpus.
    cell.innerHTML = closed
      ? `<select data-type="text">${closed.map(o =>
          `<option value="${o}" ${o === was ? 'selected' : ''}>${o}</option>`
        ).join('')}</select>`
      : `<input value="${was.replace(/"/g, '&quot;')}" data-type="${EDITABLE[field]}"` +
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
document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
for (const select of document.querySelectorAll('select[data-field]'))
  select.addEventListener('change', e => update(e.target.dataset.field, e.target.value));
// Column widths, dragged and remembered. The defaults are whatever the browser
// works out from the content, and are only frozen once somebody drags: measuring
// them all at that moment is what keeps the other columns where they were.
// Bumped when the columns changed: widths stored against the old positional
// keys would land on the wrong columns rather than simply being ignored.
const WIDTH_KEY = 'openproj:widths:2';
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
    const key = keyOf(th, i);
    if (WIDTHS[key]) { th.style.width = WIDTHS[key] + 'px'; total += WIDTHS[key]; }
  });
  // The table stops being 100% wide once the columns are explicit. Left at 100%,
  // a fixed layout divides the space it is given, so widening one column silently
  // squeezes every other — which is precisely what freezing them was meant to
  // prevent. It scrolls sideways in its own container instead.
  table.style.width = total + 'px';
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
  th.addEventListener('click', () => {
    if (dragging) return;
    // Clicking the column you are already sorted by reverses it, which is what
    // every table anybody has used does.
    const already = (params.get('sort') || 'id') === th.dataset.sort;
    params.set('sort', th.dataset.sort);
    update('desc', already && params.get('desc') !== '1' ? '1' : '');
  });
}
draw();
// After the first draw, because there is nothing to measure before the rows
// exist. Stored widths win: they were set by hand, on purpose.
if (Object.keys(WIDTHS).length) applyWidths(); else fitWidths();
</script>
"""

_TABLE_STYLE = """
#summary { color: var(--muted); }
#blocker-count { color: var(--danger); }
.table-scroll { overflow-x: auto; }
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
th .grip {
  position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize;
}
th .grip::before {
  content: ""; position: absolute; top: 20%; bottom: 20%; right: 3px; width: 1px;
  background: var(--line-strong);
}
th .grip:hover::before, th .grip.dragging::before { background: var(--accent); width: 2px; }
.measuring th, .measuring td { white-space: nowrap; }
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
<p class="hint">Double-click a node to open it. Drag to pan, scroll to zoom, drag a node
  to move it.</p>
{% if editable %}
<p class="hint" id="howto" hidden>Click what must finish first and then what waits for
  it. Draw as many as you like; nothing is written until you press Save.
  <strong>Reset</strong> clears what you have drawn and stays in edit mode.</p>
{% endif %}
<div id="cy"></div>
<script id="elements" type="application/json">ELEMENTS_JSON</script>
<script>@@cytoscape.min.js@@</script>
<script>@@dagre.min.js@@</script>
<script>@@cytoscape-dagre.js@@</script>
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

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements: JSON.parse(document.getElementById('elements').textContent),
  layout: {"name": "dagre", "rankDir": "LR", "nodeSep": 18, "rankSep": 70},
  style: [
    { selector: 'node', style: {
        'label': 'data(label)', 'font-size': 9, 'shape': 'round-rectangle',
        // text-wrap alone does nothing: without a max width the label just
        // overflows the box it is supposed to sit inside.
        'text-wrap': 'wrap', 'text-max-width': 136,
        'background-color': e => COLOUR()[e.data('status')],
        // A rank, not arithmetic on the value: priority became a word, and
        // `4 - 'high'` is NaN, which cytoscape draws as no border at all.
        'border-width': e => ({high: 4, medium: 2, low: 1})[e.data('priority')] ?? 2,
        'border-color': token('--accent'),
        'color': token('--on-status'), 'text-valign': 'center',
        'width': 150, 'height': 44 } },
    { selector: '.picked', style: {
        'border-color': token('--danger'), 'border-width': 5 } },
    { selector: ':parent', style: {
        'background-opacity': .08, 'text-valign': 'top', 'color': token('--muted') } },
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
// theme changes the tokens, not the resolved values, so they are re-read.
addEventListener('themechange', () => {
  cy.style()
    .selector('node').style({'background-color': e => COLOUR()[e.data('status')],
                             'border-color': token('--accent'),
                             'color': token('--on-status')})
    .selector('.picked').style({'border-color': token('--danger')})
    .selector(':parent').style({'color': token('--muted')})
    .selector('edge').style({'line-color': token('--st-ready'),
                             'target-arrow-color': token('--st-ready')})
    .selector('edge.pending').style({'line-color': token('--danger'),
                                     'target-arrow-color': token('--danger')})
    .update();
  route();
});

cy.on('layoutstop', route);
cy.on('position', 'node', route);
route();

const CONNECT = document.getElementById('connect');
const SAVE = document.getElementById('save');
const DISCARD = document.getElementById('discard');
let connecting = false;
let source = null;

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
    source = null;
    cy.nodes().removeClass('picked');
    CONNECT.textContent = connecting ? 'Discard and exit' : 'Edit dependencies';
    // Instructions for a mode you are not in are noise on every other visit.
    document.getElementById('howto').hidden = !connecting;
    tally(connecting ? 'click what must finish first, then what waits for it'
                     : dropped ? `discarded ${dropped}` : '');
  };

  DISCARD.onclick = () => {
    cy.remove(pending());
    source = null;
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
  if (!source) {
    source = node;
    node.addClass('picked');
    tally(`${node.id()} must finish first — now click what waits for it`);
    return;
  }
  const from = source;
  source = null;
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

_TIMELINE = """
<form class="tl-controls" method="get" action="{{ links.timeline }}">
  <label class="facet">from <input type="date" name="from" value="{{ window[0] }}"></label>
  <label class="facet">to <input type="date" name="to" value="{{ window[1] }}"></label>
  <label class="facet">zoom
    <select name="zoom">
      <option value="">fit to window</option>
      {% for px, label in zooms %}
      <option value="{{ px }}"{{ ' selected' if chosen == px else '' }}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
  <button type="submit">Apply</button>
  <a class="reset" href="{{ links.timeline }}">Reset</a>
</form>
<p class="hint">Showing {{ t.origin or 'nothing' }}{% if t.last %} to {{ t.last }}{% endif %}.
  Drag sideways or scroll to move through the plan. Bars reaching past the window are
  clipped to it, never dropped.</p>
<div class="tl">
<div class="labels">
  <div class="spacer" style="height: {{ t.header }}px"></div>
  {% for bar in t.bars %}
  <div class="row">
    <a href="{{ links.entity }}{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a></div>
  {% endfor %}
</div>
<div class="scroll">
<svg width="{{ t.width }}" height="{{ t.height }}"
     viewBox="0 0 {{ t.width }} {{ t.height }}" role="img">
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
  {% for rule in t.rules %}
  <line class="cycle-rule" x1="{{ rule.x }}" y1="0" x2="{{ rule.x }}" y2="{{ t.height }}"/>
  <text class="cycle-label" x="{{ rule.x + 3 }}" y="10">{{ rule.label }}</text>
  {% endfor %}
  {% if t.today_x is not none %}
  <line class="today" x1="{{ t.today_x }}" y1="0" x2="{{ t.today_x }}" y2="{{ t.height }}"/>
  {% endif %}
  {% for bar in t.bars %}
  <a href="{{ links.entity }}{{ bar.id }}"
     ><rect data-id="{{ bar.id }}" class="{{ bar.classes }} {{ bar.colour }}"
        x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="14"
        ><title>{{ bar.tip }} — click to open</title></rect></a>
  {% endfor %}
  {% for month in t.months %}
  <line class="month-rule" x1="{{ month.x }}" y1="{{ t.header }}" x2="{{ month.x }}"
        y2="{{ t.height }}"/>
  <text class="month-label" x="{{ month.x + 3 }}" y="{{ t.header - 8 }}">{{ month.label }}</text>
  {% endfor %}
</svg>
</div>
</div>
<script>
// Open on today rather than on the oldest finished work. The plan is scrollable
// so history stays reachable, but "now" is what the page is for.
const scroller = document.querySelector('.scroll');
{% if t.today_x is not none %}
scroller.scrollLeft = Math.max(0, {{ t.today_x }} - 320);
{% endif %}

// The window is re-rendered by the server, so zoom keeps its labels upright and
// its corners round. Changing a control just submits; the button stays for
// anybody without JavaScript, and the URL stays shareable either way.
const form = document.querySelector('.tl-controls');
form.querySelectorAll('input, select').forEach(control => {
  control.onchange = () => form.submit();
});

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
</script>
"""

_TIMELINE_STYLE = """
.tl-controls { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: baseline;
               margin: .75rem 0 .25rem; }
.tl-controls input, .tl-controls select, .tl-controls button {
  display: block; font: inherit; font-size: 13px; text-transform: none; letter-spacing: 0;
}
.tl-controls .reset { color: var(--accent); font-size: 13px; }
.tl { display: flex; border: 1px solid var(--line); align-items: stretch; }
.labels { flex: 0 0 250px; border-right: 1px solid var(--line); }
.labels .row {
  height: 22px; line-height: 22px; font-size: 11px; color: var(--muted);
  padding: 0 .5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scroll { overflow-x: auto; flex: 1 1 auto; min-width: 0; }
svg { display: block; }
.month-rule { stroke: var(--line); }
.month-label { font-size: 9px; fill: var(--muted); }
.cycle-rule { stroke: var(--line); stroke-dasharray: 3 3; }
.cycle-label { font-size: 9px; fill: var(--accent); font-weight: 600; }
.today { stroke: var(--danger); stroke-width: 1.5; }
rect.bar { rx: 3; }
rect.st-shaping { fill: var(--st-shaping); }
rect.st-ready { fill: var(--st-ready); }
rect.st-in_progress { fill: var(--st-in_progress); }
rect.st-done { fill: var(--st-done); }
rect.st-shelved { fill: var(--st-shelved); }
rect.estimated { stroke: var(--warn); stroke-width: 1; }
rect.late { stroke: var(--danger); stroke-width: 1.5; }
"""


_COMBOBOX = """
<script id="suggest" type="application/json">SUGGEST_JSON</script>
<script>
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
      <span class="hint">the fields above are shown as you set them</span>
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
      <span class="hint">the fields above are shown as you set them</span>
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
  min-height: 60vh; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px; line-height: 1.55; resize: vertical;
}
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2, rgba(127,127,127,.12)); padding: 0 .25em; }
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

LABELS = {
    "title": "Title", "status": "Status", "owner": "Owner", "assignees": "Assignees",
    "reviewers": "Reviewers", "review_waived": "Review waived", "assigned_on": "Assigned on",
    "priority": "Priority", "cycle": "Cycle", "parent": "Parent", "depends_on": "Blocked by",
    "tags": "Tags", "prs": "PRs", "appetite_weeks": "Appetite (weeks)",
    "shaped_by": "Shaped by", "effort_weeks": "Effort (weeks)",
}
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
                "size_label": "Appetite" if entity.kind == "pitch" else "Effort",
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
                "body": _body_html(entity),
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
  <button type="button" id="save">Save the setup</button>
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
  <tr data-login="{{ row.login }}" class="{{ 'over' if row.over else '' }}">
    {% if editable %}<td><button type="button" class="drop" title="Take out of this
      cycle">&#128465;</button></td>{% else %}<td></td>{% endif %}
    <td>{{ row.login }}</td>
    <td><span class="read">{{ (row.rate * 100)|round|int }}%</span>
        <input class="field rate" data-login="{{ row.login }}" value="{{ row.rate }}"></td>
    <td class="derived">{{ '%.1f'|format(row.capacity) }} wk</td>
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
{% if c.over %}
<p class="problems" id="over">Over capacity: {{ c.over|join(', ') }}. The room can
  still bet it — this is a number, not a refusal.</p>
{% endif %}

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

// The whole roster in one write. A name left out means somebody was taken off,
// which per-field merging would silently undo.
document.getElementById('save').onclick = async () => {
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
  say('saving…');
  if (await put(fields)) location.reload();
};

// Ticking is a write to the ENTITY, not to the cycle: `cycle` lives on the thing
// being bet, and one row is one commit so a half-finished betting table is still
// a readable history rather than one commit nobody can unpick.
for (const box of document.querySelectorAll('input.bet')) {
  box.onchange = async () => {
    const row = box.closest('tr');
    const id = row.dataset.id;
    box.disabled = true;
    const response = await fetch(`/api/entity/${id}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: BASE.value,
        fields: {cycle: box.checked ? NUMBER : null},
        body: null,
      }),
    });
    const answer = await response.json();
    box.disabled = false;
    if (!response.ok) {
      box.checked = !box.checked;
      say(`${id}: ${answer.detail || 'refused'}`);
      return;
    }
    BASE.value = answer.commit || BASE.value;
    say(`${id} ${box.checked ? 'bet into' : 'taken out of'} cycle ${NUMBER}`);
    row.querySelector('td:last-child').textContent = box.checked ? NUMBER : '—';
  };
}

// Every editable cell is an input already: a betting table is filled in, not
// inspected, and a double-click to reach a field somebody is about to type in is
// a step that only exists because the table also had to be readable.
for (const input of document.querySelectorAll('#bets input.live')) {
  if (input.dataset.suggest) attachSuggest(input);
  let was = input.value;
  let abandoned = false;
  // Saving on blur alone is not safe when the field is already an input: the
  // browser restores form values across a reload, autofills, and the picker
  // rewrites the field to add a separator — none of which is a person deciding
  // something, and all of which used to reach git. A cell saves only if somebody
  // typed in it or picked from it, which is what an `input` event means.
  let edited = false;
  input.addEventListener('input', () => { edited = true; });
  input.onkeydown = event => {
    if (event.key === 'Escape') { abandoned = true; input.value = was; input.blur(); }
    if (event.key === 'Enter') input.blur();
  };
  input.onblur = async () => {
    const value = input.value.trim();
    if (abandoned || !edited || value === was.trim()) { abandoned = false; return; }
    const id = input.closest('tr').dataset.id;
    const field = input.dataset.field;
    let sent;
    if (input.dataset.type === 'list') {
      sent = value ? [...new Set(value.split(',').map(s => s.trim()).filter(Boolean))] : [];
    } else if (value === '') {
      sent = null;
    } else if (Number.isNaN(Number(value))) {
      say(`${field} must be a number, not "${value}"`);
      input.value = was;
      return;
    } else {
      sent = Number(value);
    }
    const response = await fetch(`/api/entity/${id}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: {[field]: sent}, body: null}),
    });
    const answer = await response.json();
    if (!response.ok) {
      input.value = was;
      say(`${id}: ${answer.detail || (answer.problems || []).map(p => p.message).join('; ')
                    || 'refused'}`);
      return;
    }
    BASE.value = answer.commit || BASE.value;
    was = Array.isArray(sent) ? sent.join(', ') : input.value;
    edited = false;
    say(`${id}: ${field} saved — reload to see the load move`);
  };
}

// The roster is edited in the page and written by Save, so adding somebody and
// setting their availability is one decision and one commit rather than two.
const JOINING = document.getElementById('joining');
if (JOINING) attachSuggest(JOINING);

function dropRow(button) {
  button.onclick = () => {
    const row = button.closest('tr');
    say(`${row.dataset.login} taken out — press Save to commit it`);
    row.remove();
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
  row.innerHTML =
    `<td><button type="button" class="drop" title="Take out of this cycle">&#128465;</button></td>`
    + `<td>${login}</td>`
    + `<td><input class="field rate" data-login="${login}" value="1.0"></td>`
    + `<td class="derived">—</td><td class="derived">—</td><td></td><td class="derived">—</td>`;
  document.getElementById('roster').append(row);
  dropRow(row.querySelector('.drop'));
  JOINING.value = '';
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
#bets input.live:focus { border-color: var(--accent); outline: none; }
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
  <span id="state"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</p>
<script>
// Defaults carried from the last cycle: the length rarely changes, and the next
// one starts when the last one ends. Both are still typed over before saving.
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
        "strangers": strangers,
        "over": [p["login"] for p in people if p["over"]],
        "candidates": candidates,
        "body": _MD.render(plan.body) if plan else "",
    }


def render_cycle(
    index: Index, number: int, links: Links = ROUTES, base_commit: str | None = None
) -> str:
    body = _ENV.from_string(_CYCLE).render(
        c=_cycle_view(index, number),
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        combobox=_combobox_html(index),
    )
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
        },
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
        links=links,
        # Only the server has an event stream to listen to. A static page opening a
        # connection to nothing would retry forever in the console.
        live=links.table.startswith("/"),
    )


def preview_html(body: str) -> str:
    """Markdown rendered for the preview pane, with HTML disabled.

    markdown-it-py leaves raw HTML alone by default. The body is written by
    signed-in members and rendered back to every reader, so a script tag in a
    shaping doc would run in everybody's browser.
    """
    return MarkdownIt("commonmark", {"html": False}).render(body)


def render_table(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
    payload = _payload(index)
    blockers = sum(1 for p in index.problems if p.severity == "blocker")
    body = _ENV.from_string(_TABLE).render(
        payload=payload,
        blockers=blockers,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        links=links,
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
        editable=base_commit is not None, base_commit=base_commit or ""
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
    return _page(
        "openproj — graph", body, "#cy { height: 78vh; border: 1px solid var(--line); }", links
    )


_ZOOMS = (("2", "months"), ("6", "weeks"), ("14", "days"), ("30", "close"))


def render_timeline(
    index: Index,
    links: Links = STATIC,
    window: tuple[date | None, date | None] = (None, None),
    zoom: float | None = None,
) -> str:
    body = _ENV.from_string(_TIMELINE).render(
        t=_timeline(index, window, zoom),
        links=links,
        zooms=_ZOOMS,
        chosen=f"{zoom:g}" if zoom else "",
        # Echo what was asked for, not what was computed: a `from` box that fills
        # itself with the corpus start makes an empty window look like a set one.
        window=[d.isoformat() if d else "" for d in window],
    )
    return _page("openproj — timeline", body, _TIMELINE_STYLE, links)


def render_static(index: Index, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, html in (
        ("index.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("people.html", render_people(index)),
        ("cycles.html", render_cycles(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
