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

from .index import COMPUTED_PREDICATES, Index, _matches_predicate
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
_STATUS_COLOUR = {
    "shaping": "#b9a6c9",
    "ready": "#8a93a5",
    "in_progress": "#1f6f8b",
    "done": "#3f7d58",
    "shelved": "#b0b4bd",
}


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
        "labels": STATUS_LABEL,
    }


def _elements(index: Index) -> list[dict]:
    elements: list[dict] = []
    for entity_id, entity in index.entities.items():
        data = {
            "id": entity_id,
            "label": f"{entity.title}\n{entity_id}",
            "status": entity.status,
            "priority": entity.priority,
            "kind": entity.kind,
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


def _timeline(index: Index) -> dict:
    """Geometry for the hand-rolled SVG Gantt.

    No Gantt library: hatching, cycle rules and per-bar explanations are all custom,
    and the scheduler emits exact spans, so the renderer is the small part.
    """
    drawn = {i: s for i, s in index.spans.items() if not s.unscheduled}
    if not drawn:
        return {"bars": [], "rules": [], "width": _LEFT_PX, "height": _ROW_PX, "origin": None}

    starts = [s.start for s in drawn.values()] + [w[0] for w in index.cycles.values()]
    ends = [s.end for s in drawn.values()] + [w[1] for w in index.cycles.values()]
    origin, last = min(*starts, index.today), max(*ends, index.today)

    # A corpus can span ten months. At a fixed day width that is 1800px of
    # coordinate space, and an SVG with no viewBox CLIPS rather than scales, so
    # everything past the fold silently vanished. Scale the day instead, floored
    # so a short plan does not turn into a hairline.
    days = max((last - origin).days, 1)
    day_px = max(1.6, min(_DAY_PX, _PLOT_PX / days))

    def x(day: date) -> float:
        # Plot coordinates only. The label column is HTML beside the SVG, not
        # inside it, so that it can stay put while the plot scrolls.
        return round((day - origin).days * day_px, 1)

    order = sorted(drawn, key=lambda i: (drawn[i].start, i))
    bars = []
    for row, entity_id in enumerate(order):
        span = drawn[entity_id]
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
                "x": x(span.start),
                "y": row * _ROW_PX + _HEADER_PX,
                "width": max(_DAY_PX, x(span.end + timedelta(days=1)) - x(span.start)),
                "colour": _STATUS_COLOUR.get(entity.status, "#8a93a5"),
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
        "today_x": x(index.today),
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
    entity: str = "detail.html#"  # prefix, then the entity id
    new: str = ""  # only the server can create; a rendered file has nowhere to post


STATIC = Links()
ROUTES = Links(
    table="/", detail="/detail", graph="/graph", timeline="/timeline",
    entity="/detail/", new="/new",
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
<style>
:root { color-scheme: light dark; --line: #d7dfe1; --muted: #6a7a80; --accent: #0f5c6b; }
@media (prefers-color-scheme: dark) {
  :root { --line: #253339; --muted: #7e9098; --accent: #5cb9ca; }
}
body { font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 1rem 1.25rem 3rem; }
nav { display: flex; gap: 1rem; margin-bottom: 1rem; font-size: 13px; }
nav a { color: var(--accent); }
.derived { color: var(--muted); font-variant-numeric: tabular-nums; font-style: italic; }
#moved { position: fixed; right: 1rem; bottom: 1rem; background: var(--accent); color: #fff;
         padding: .5rem .8rem; font-size: 13px; border-radius: 3px; }
#moved a { color: #fff; }
#moved .sha { font-family: ui-monospace, monospace; opacity: .7; }
{{ style }}
</style></head><body>
<nav><a href="{{ links.table }}">Table</a><a href="{{ links.graph }}">Graph</a>
<a href="{{ links.timeline }}">Timeline</a><a href="{{ links.detail }}">Detail</a></nav>
{{ content }}
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
  {% for field in ['kind','status','owner','reviewers','priority','cycle','project','tags'] %}
  <select data-field="{{ field }}"><option value="">{{ field }}</option>
    {% for value in payload.facets.get(field, []) %}<option>{{ value }}</option>{% endfor %}
  </select>
  {% endfor %}
  <select data-field="predicate"><option value="">predicate</option>
    {% for p in payload.predicates %}<option>{{ p }}</option>{% endfor %}
  </select>
</div>
<table id="rows"><thead><tr>
  <th data-sort="id">id</th><th data-sort="title">title</th><th data-sort="status">status</th>
  <th data-sort="owner">owner</th><th data-sort="reviewers">reviewers</th>
  <th data-sort="priority">priority</th><th data-sort="cycle">cycle</th>
  <th data-sort="size">weeks</th>
  <th data-sort="start">start</th><th data-sort="end">end</th>
  <th data-sort="blocked_by">blockers</th><th>prs</th><th>tags</th>
</tr></thead><tbody></tbody></table>
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
  for (const field of ['kind','status','owner','reviewers','priority','cycle','tags']) {
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
  if (key === 'title') return `<td data-entity="${row.id}" data-field="title"` +
    `><a href="ENTITY_HREF${row.id}">${text}</a></td>`;
  if (EDITABLE && key in EDITABLE)
    return `<td data-entity="${row.id}" data-field="${key}" class="edit">${text}</td>`;
  if (key === 'prs') return `<td>${(value || []).map(prLink).join(', ')}</td>`;
  return `<td class="${derived ? 'derived' : ''}">${text}</td>`;
}

function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${repo}/pull/${number}">${ref}</a>`;
}

function draw() {
  const keys = ['id','title','status','owner','reviewers','priority','cycle','size',
                'start','end','blocked_by','prs','tags'];
  const sort = params.get('sort') || 'id';
  const descending = params.get('desc') === '1';
  const rows = Object.values(DATA.rows).filter(matches)
    .sort((a, b) => String(a[sort] ?? '').localeCompare(String(b[sort] ?? '')));
  if (descending) rows.reverse();
  tbody.innerHTML = rows.map(row =>
    `<tr data-id="${row.id}" title="${(row.problems || []).join(' · ')}">` +
    keys.map(k => cell(row, k)).join('') + '</tr>').join('');
  document.getElementById('shown').textContent = rows.length;
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
const LABELS = DATA.labels;

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
          `<option value="${o}" ${o === was ? 'selected' : ''}>${LABELS[o] || o}</option>`
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
for (const th of document.querySelectorAll('th[data-sort]'))
  th.addEventListener('click', () => {
    // Clicking the column you are already sorted by reverses it, which is what
    // every table anybody has used does.
    const already = (params.get('sort') || 'id') === th.dataset.sort;
    params.set('sort', th.dataset.sort);
    update('desc', already && params.get('desc') !== '1' ? '1' : '');
  });
draw();
</script>
"""

_TABLE_STYLE = """
#controls { display: flex; flex-wrap: wrap; gap: .4rem; margin: .75rem 0; }
#summary { color: var(--muted); }
#blocker-count { color: #9a3327; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left; }
th[data-sort] { cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; }
"""

_GRAPH = """
<div id="cy"></div>
<script id="elements" type="application/json">ELEMENTS_JSON</script>
<script>@@cytoscape.min.js@@</script>
<script>@@dagre.min.js@@</script>
<script>@@cytoscape-dagre.js@@</script>
<script>
cytoscape.use(cytoscapeDagre);
const COLOUR = {shaping:'#b9a6c9', ready:'#8a93a5', in_progress:'#1f6f8b',
                done:'#3f7d58', shelved:'#b0b4bd'};
cytoscape({
  container: document.getElementById('cy'),
  elements: JSON.parse(document.getElementById('elements').textContent),
  layout: {"name": "dagre", "rankDir": "LR", "nodeSep": 18, "rankSep": 70},
  style: [
    { selector: 'node', style: {
        'label': 'data(label)', 'font-size': 9, 'shape': 'round-rectangle',
        // text-wrap alone does nothing: without a max width the label just
        // overflows the box it is supposed to sit inside.
        'text-wrap': 'wrap', 'text-max-width': 136,
        'background-color': e => COLOUR[e.data('status')],
        'border-width': e => 4 - e.data('priority'), 'border-color': '#0f5c6b',
        'color': '#fff', 'text-valign': 'center', 'width': 150, 'height': 44 } },
    { selector: ':parent', style: {
        'background-opacity': .08, 'text-valign': 'top', 'color': '#6a7a80' } },
    { selector: 'edge', style: {
        'width': 1.5, 'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
        'line-color': '#8a93a5', 'target-arrow-color': '#8a93a5' } },
  ],
}).on('tap', 'node', evt => {
  location.href = 'ENTITY_HREF' + evt.target.id();
});
</script>
"""

_TIMELINE = """
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
      <line x1="0" y="0" x2="0" y2="6" stroke="#fff" stroke-opacity=".55" stroke-width="3"/>
    </pattern>
    <pattern id="hatch-unowned" width="8" height="8" patternTransform="rotate(-45)"
             patternUnits="userSpaceOnUse">
      <line x1="0" y="0" x2="0" y2="8" stroke="#fff" stroke-opacity=".7" stroke-width="4"/>
    </pattern>
  </defs>
  {% for rule in t.rules %}
  <line class="cycle-rule" x1="{{ rule.x }}" y1="0" x2="{{ rule.x }}" y2="{{ t.height }}"/>
  <text class="cycle-label" x="{{ rule.x + 3 }}" y="10">{{ rule.label }}</text>
  {% endfor %}
  <line class="today" x1="{{ t.today_x }}" y1="0" x2="{{ t.today_x }}" y2="{{ t.height }}"/>
  {% for bar in t.bars %}
  <a href="{{ links.entity }}{{ bar.id }}"
     ><rect data-id="{{ bar.id }}" class="{{ bar.classes }}" x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="14" fill="{{ bar.colour }}"
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
scroller.scrollLeft = Math.max(0, {{ t.today_x }} - 320);
</script>
"""

_TIMELINE_STYLE = """
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
.today { stroke: #9a3327; stroke-width: 1.5; }
rect.bar { rx: 3; }
rect.estimated { stroke: #8f5c07; stroke-width: 1; }
rect.late { stroke: #9a3327; stroke-width: 1.5; }
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
    if (multi) {
      const held = tokens();
      held[held.length - 1] = value;
      input.value = held.filter(Boolean).join(', ') + ', ';
    } else {
      input.value = value;
    }
    close();
    input.focus();
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
           background: var(--surface, #fff); border: 1px solid var(--line-strong, #b7c5c9);
           border-radius: 3px; min-width: 14rem; max-height: 16rem; overflow-y: auto;
           box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.suggest li { padding: .25rem .5rem; cursor: pointer; }
.suggest li.on { background: var(--accent, #0f5c6b); color: #fff; }
.suggest .dim { opacity: .6; }
.suggest li.on .dim { opacity: .85; }
dd, td.edit { position: relative; }
"""

_CONTROL = """
{% if f.type in ("status", "priority") %}
<select name="{{ f.name }}" data-type="text" class="field"
        {% if f.gate %}data-required-from="{{ f.gate }}"{% endif %}>
  {% for s in (statuses if f.type == "status" else priorities) %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{ labels.get(s, s) }}</option>
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
        f=field, statuses=STATUSES, priorities=PRIORITIES, labels=STATUS_LABEL
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
<article class="entity">
  <p class="back"><a href="{{ links.table }}">← table</a></p>
  <p class="editbar">
    <button type="button" id="save">Create</button>
    <button type="button" id="preview">Preview</button>
    <span id="state"></span>
  </p>
  <h1>New {{ kind }}</h1>
  <p class="meta">The id and the file are the server's to choose.
    {% for k in kinds %}{% if k != kind %}
    <a href="{{ links.new }}?kind={{ k }}">make a {{ k }} instead</a>{% endif %}{% endfor %}</p>
  <form id="edit" data-kind="{{ kind }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <div id="fields">{{ fields_html|safe }}</div>
    <div id="problems" hidden></div>
  </form>
  <div class="doc" hidden></div>
</article>
{{ combobox|safe }}
<script>
const FORM = document.getElementById('edit');
const STATE = document.getElementById('state');
const PROBLEMS = document.getElementById('problems');
const ORDER = ['todo', 'wip', 'done'];

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

document.getElementById('preview').onclick = async () => {
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: FORM.querySelector('[name=body]').value}),
  });
  const doc = document.querySelector('.doc');
  doc.hidden = false;
  doc.innerHTML = (await response.json()).html;
};



document.getElementById('save').onclick = async () => {
  const fields = {kind: FORM.dataset.kind};
  const status = FORM.querySelector('[name=status]')?.value || 'todo';
  const missing = [];
  for (const control of FORM.querySelectorAll('[data-type]')) {
    let value;
    try { value = read(control); } catch (error) { STATE.textContent = error.message; return; }
    const empty = value === null || (Array.isArray(value) && !value.length);
    const waived = control.name === 'reviewers' &&
      FORM.querySelector('[name=review_waived]')?.checked;
    const gate = control.dataset.requiredFrom;
    // Cumulative: a field demanded from `todo` is demanded at every status after
    // it, which is why this compares positions rather than equality.
    if (gate && empty && !waived && ORDER.indexOf(status) >= ORDER.indexOf(gate))
      missing.push(control.name);
    if (!empty) fields[control.name] = value;
  }
  if (missing.length) {
    PROBLEMS.hidden = false;
    PROBLEMS.textContent = `still needed at status ${status}: ${missing.join(', ')}`;
    return;
  }
  const response = await fetch('/api/entity', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({
      base_commit: FORM.querySelector('[name=base_commit]').value, fields,
      body: FORM.querySelector('[name=body]').value || '',
    }),
  });
  const answer = await response.json();
  if (!response.ok) {
    // The client check is a courtesy; this is the truth, and swallowing it leaves
    // somebody staring at a form that looks fine.
    PROBLEMS.hidden = false;
    PROBLEMS.textContent = (answer.problems || [])
      .map(p => `${p.field}: ${p.message}`).join('; ') || answer.detail || 'refused';
    return;
  }
  location.href = '/detail/' + answer.id;
};
</script>
"""

_DETAIL = """
{% if not single %}<ul class="toc">
  {% for e in entities %}
  <li><a href="{{ links.entity }}{{ e.id }}">{{ e.title }}</a>
      <span class="tocmeta">{{ e.kind }} · {{ e.status }} · {{ e.owner or "unowned" }}</span></li>
  {% endfor %}
</ul>{% endif %}
{% for e in entities %}
<article id="{{ e.id }}" class="entity">
  <p class="back"><a href="{{ links.detail }}">← all</a></p>
  {% if editable %}
  <p class="editbar">
    <button type="button" id="toggle">Edit</button>
    <button type="button" id="preview" hidden>Preview</button>
    <button type="button" id="save" hidden>Save</button>
    <span id="state"></span>
  </p>
  {% endif %}
  <h1><span class="read">{{ e.title }}</span></h1>
  <p class="meta"><code>{{ e.id }}</code> · {{ e.kind }} · <b>{{ e.status }}</b>
     {% if e.parent %}· in
     <a href="{{ links.entity }}{{ e.parent }}">{{ e.parent }}</a>{% endif %}</p>
  {% if editable %}
  <form id="edit" data-id="{{ e.id }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <input name="title" data-type="text" value="{{ e.title }}" class="field title-field">
  {% endif %}
  <dl id="facts">
    {% for row in e.rows %}
    <dt class="{% if row.derived %}derived{% endif %}">{{ row.label }}</dt>
    <dd class="{% if row.derived %}derived{% endif %}">
      <span class="read">{{ row.display|safe }}</span>
      {% if editable and row.control %}{{ row.control|safe }}{% endif %}
    </dd>
    {% endfor %}
  </dl>
  {% if e.problems %}<ul class="problems">
    {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
  <div class="doc read">{{ e.body|safe }}</div>
  {% if editable %}
    <textarea name="body" class="field body-field">{{ e.raw_body }}</textarea>
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
  for (const id of ['preview', 'save']) document.getElementById(id).hidden = !editing;
  document.getElementById('toggle').textContent = editing ? 'Cancel' : 'Edit';
}

document.getElementById('toggle').onclick = () => {
  const editing = !document.querySelector('article.entity').classList.contains('editing');
  show(editing);
  if (!editing) localStorage.removeItem(DRAFT);
};

document.getElementById('preview').onclick = async () => {
  // A round trip, not a second markdown implementation: two renderers disagree
  // eventually, and the one people trust would not be the one that gets committed.
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: BODY.value}),
  });
  document.querySelector('.doc').innerHTML = (await response.json()).html;
  show(false);
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
.hint { color: var(--muted); font-size: 12px; }
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
.problems { color: #8f5c07; padding-left: 1.1rem; }

/* The two modes of the same rows. Controls are hidden until the article is
   editing, and the values they replace are hidden once it is. */
.field { display: none; }
.entity.editing .field { display: block; }
.entity.editing .read { display: none; }
.entity.editing dd .field[type=checkbox] { display: inline-block; }
label { display: block; }
input.field, select.field, textarea.field {
  width: 100%; box-sizing: border-box; font: inherit; padding: .25rem .4rem;
  border: 1px solid var(--line-strong, #b7c5c9); border-radius: 3px;
  background: var(--surface, #fff); color: inherit;
}
input.title-field { font-size: 1.4rem; font-weight: 600; margin-bottom: .6rem; }
textarea.body-field {
  min-height: 60vh; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px; line-height: 1.55; resize: vertical;
}
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2, rgba(127,127,127,.12)); padding: 0 .25em; }
#conflict { border-left: 3px solid #9a3327; padding: .5rem .8rem; margin-top: 1rem;
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
# What each status is called on screen. The stored value stays a plain identifier
# so it can be filtered and sorted; the label is for the person reading it.
STATUS_LABEL = {"in_progress": "in progress"}

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
    "parent": "entities", "depends_on": "entities", "tags": "tags",
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
    for field in _editable_for(entity):
        name = field["name"]
        if name == "title":
            continue
        if name == "depends_on":
            display = _links(index.blocked_by[entity.id], index, links) or "nothing"
        elif name == "prs":
            display = ", ".join(_pr_link(ref) for ref in entity.prs) or "none"
        elif name == "review_waived":
            display = "waived" if entity.review_waived else "no"
        elif field["type"] == "list":
            display = field["text"] or "—"
        else:
            display = str(field["text"]) if field["text"] not in ("", None) else "—"
        rows.append(
            {
                "label": LABELS.get(name, name),
                "display": display,
                "control": _control_html(field),
                "derived": False,
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
            "display": (f"{span.start} → {span.end}{overrun}" if span else "not scheduled"),
            "control": "",
            "derived": True,
        }
    )
    if why:
        rows.append({"label": "Why then", "display": why.text, "control": "", "derived": True})
    rows.append(
        {
            "label": "Blocks",
            "display": _links(index.blocks[entity.id], index, links) or "nothing",
            "control": "",
            "derived": True,
        }
    )
    return rows


def _detail_rows(index: Index) -> list[dict]:
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
                "span": f"{span.start} → {span.end}" if span else "not scheduled",
                "overrun": (
                    f"overruns cycle {entity.cycle} by {span.overruns_cycle_weeks:.1f} weeks"
                    if span and span.overruns_cycle_weeks
                    else ""
                ),
                "why": why.text if why else "",
                "blocked_by": _links(index.blocked_by[entity_id], index),
                "blocks": _links(index.blocks[entity_id], index),
                "prs": ", ".join(_pr_link(ref) for ref in entity.prs),
                "tags": entity.tags,
                "problems": [p.message for p in index.problems if p.entity_id == entity_id],
                "body": _body_html(entity),
            }
        )
    return rows


def render_new(
    kind: str, base_commit: str, links: Links = ROUTES, index: Index | None = None
) -> str:
    """The create page, laid out exactly like a detail page in edit mode.

    A second, differently-shaped form for creating was the thing that made the
    tool feel like two tools. The fields a kind has are decided here rather than
    hidden by script, so the page shows what this kind actually is.
    """
    blank = {"project": Project, "pitch": Pitch, "task": Task}[kind](
        id=f"{PREFIX[kind]}-000000",
        kind=kind,
        title="",
        # Today, because a date field that starts empty is a date field somebody
        # leaves empty. An existing value is never overwritten — this is a blank.
        assigned_on=date.today(),
    )
    body = _ENV.from_string(_NEW).render(
        kind=kind,
        kinds=("project", "pitch", "task"),
        base_commit=base_commit,
        links=links,
        fields_html=_fields_html(_editable_for(blank), "", rows=14),
        combobox=_combobox_html(index),
    )
    return _page(f"openproj — new {kind}", body, _DETAIL_STYLE + _SUGGEST_STYLE, links)


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
    return {
        "people": [{"value": p, "label": ""} for p in sorted(people)],
        "entities": [
            {"value": i, "label": e.title} for i, e in sorted(index.entities.items())
        ],
        "tags": [{"value": t, "label": ""} for t in sorted(tags)],
    }


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
    rows = _detail_rows(index)
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


def render_graph(index: Index, links: Links = STATIC) -> str:
    """Inline the libraries in one pass, keyed by filename.

    Sequential `str.replace` calls were wrong here and silently so: `DAGRE_JS` is a
    substring of `CYTOSCAPE_DAGRE_JS`, so replacing the shorter marker first ate
    the tail of the longer one. dagre was inlined twice, cytoscape-dagre never,
    and the page rendered blank with a stray identifier. One regex pass over
    delimited markers cannot collide however the names are chosen.
    """
    body = _GRAPH.replace("ELEMENTS_JSON", json.dumps(_elements(index)))
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


def render_timeline(index: Index, links: Links = STATIC) -> str:
    body = _ENV.from_string(_TIMELINE).render(t=_timeline(index), links=links)
    return _page("openproj — timeline", body, _TIMELINE_STYLE, links)


def render_static(index: Index, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, html in (
        ("index.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
