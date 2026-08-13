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
import re
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment
from markdown_it import MarkdownIt
from markupsafe import Markup

from .index import COMPUTED_PREDICATES, Index, _matches_predicate
from .model import Config, Entity, size_weeks

_STATIC = Path(__file__).resolve().parents[2] / "static"

_DAY_PX = 6
_ROW_PX = 22
_LEFT_PX = 250
_PLOT_PX = 1100
_HEADER_PX = 26
_LABEL_CHARS = 40


def _clip(text: str) -> str:
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "\u2026"
_STATUS_COLOUR = {
    "todo": "#8a93a5",
    "wip": "#1f6f8b",
    "done": "#3f7d58",
    "shelved": "#b0b4bd",
}


def _inline(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


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


def _payload(index: Index) -> dict:
    return {
        "rows": {i: _row(index, i) for i in index.entities},
        "facets": index.facets,
        "predicates": list(index.facets["predicate"]),
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
                "colour": _STATUS_COLOUR[entity.status],
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


_MD = MarkdownIt("commonmark").enable("table")
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
{{ style }}
</style></head><body>
<nav><a href="index.html">Table</a><a href="graph.html">Graph</a>
<a href="timeline.html">Timeline</a><a href="detail.html">Detail</a></nav>
{{ content }}
</body></html>
"""

_TABLE = """
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
  <th data-sort="priority">pri</th><th data-sort="cycle">cycle</th><th data-sort="size">size</th>
  <th data-sort="start">start</th><th data-sort="end">end</th>
  <th data-sort="blocked_by">blockers</th><th>prs</th><th>tags</th>
</tr></thead><tbody></tbody></table>
<script id="payload" type="application/json">PAYLOAD_JSON</script>
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
  if (key === 'title') return `<td><a href="detail.html#${row.id}">${text}</a></td>`;
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
  const rows = Object.values(DATA.rows).filter(matches)
    .sort((a, b) => String(a[sort] ?? '').localeCompare(String(b[sort] ?? '')));
  tbody.innerHTML = rows.map(row =>
    `<tr title="${(row.problems || []).join(' · ')}">` +
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

document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
for (const select of document.querySelectorAll('select[data-field]'))
  select.addEventListener('change', e => update(e.target.dataset.field, e.target.value));
for (const th of document.querySelectorAll('th[data-sort]'))
  th.addEventListener('click', () => update('sort', th.dataset.sort));
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
const COLOUR = {todo:'#8a93a5', wip:'#1f6f8b', done:'#3f7d58', shelved:'#b0b4bd'};
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
  location.href = 'detail.html#' + evt.target.id();
});
</script>
"""

_TIMELINE = """
<div class="tl">
<div class="labels">
  <div class="spacer" style="height: {{ t.header }}px"></div>
  {% for bar in t.bars %}
  <div class="row">
    <a href="detail.html#{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a></div>
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
  <a href="detail.html#{{ bar.id }}"
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


_DETAIL = """
<p class="hint">Pick anything from the table, the graph or the timeline. Every view links here.</p>
{% for e in entities %}
<article id="{{ e.id }}" class="entity">
  <h1>{{ e.title }}</h1>
  <p class="meta"><code>{{ e.id }}</code> · {{ e.kind }} · <b>{{ e.status }}</b>
     {% if e.parent %}· in <a href="#{{ e.parent }}">{{ e.parent }}</a>{% endif %}</p>
  <dl>
    <dt>Owner</dt><dd>{{ e.owner or "nobody" }}</dd>
    <dt>Reviewers</dt>
    <dd>{% if e.review_waived %}<i>waived</i>
        {% else %}{{ e.reviewers|join(", ") or "none yet" }}{% endif %}</dd>
    <dt>{{ e.size_label }}</dt><dd>{{ e.size }}</dd>
    <dt>Assigned on</dt><dd>{{ e.assigned_on or "—" }}</dd>
    <dt>Cycle</dt><dd>{{ e.cycle or "—" }}</dd>
    <dt class="derived">Scheduled</dt>
    <dd class="derived">{{ e.span }}
        {% if e.overrun %} · <b class="late">{{ e.overrun }}</b>{% endif %}</dd>
    {% if e.why %}<dt class="derived">Why then</dt><dd class="derived">{{ e.why }}</dd>{% endif %}
    <dt>Blocked by</dt><dd>{{ e.blocked_by|safe or "nothing" }}</dd>
    <dt class="derived">Blocks</dt><dd class="derived">{{ e.blocks|safe or "nothing" }}</dd>
    <dt>PRs</dt><dd>{{ e.prs|safe or "none" }}</dd>
    <dt>Tags</dt><dd>{{ e.tags|join(", ") or "—" }}</dd>
  </dl>
  {% if e.problems %}<ul class="problems">
    {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
  <div class="doc">{{ e.body|safe }}</div>
</article>
{% endfor %}
<script>
// One page, hash-routed: a stable shareable link per entity without a file each.
function show() {
  const wanted = location.hash.slice(1);
  let seen = false;
  for (const article of document.querySelectorAll('article.entity')) {
    const match = article.id === wanted;
    article.style.display = match || !wanted ? '' : 'none';
    seen = seen || match;
  }
  document.querySelector('.hint').style.display = wanted && seen ? 'none' : '';
}
addEventListener('hashchange', show);
show();
</script>
"""

_DETAIL_STYLE = """
.hint { color: var(--muted); }
article.entity { max-width: 46rem; margin-bottom: 3rem; }
article.entity h1 { font-size: 1.4rem; margin-bottom: .2rem; }
.meta { color: var(--muted); margin-top: 0; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1rem; margin: 1rem 0; }
dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
dd { margin: 0; }
dt.derived, dd.derived { font-style: italic; }
.late { color: #9a3327; }
.problems { color: #8f5c07; padding-left: 1.1rem; }
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2, rgba(127,127,127,.12)); padding: 0 .25em; }
"""


def _links(ids: list[str], index: Index) -> str:
    return ", ".join(
        f'<a href="#{i}">{index.entities[i].title if i in index.entities else i}</a>' for i in ids
    )


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


def render_detail(index: Index) -> str:
    body = _ENV.from_string(_DETAIL).render(entities=_detail_rows(index))
    return _page("openproj — detail", body, _DETAIL_STYLE)


def _page(title: str, content: str, style: str = "") -> str:
    """Autoescaping protects entity titles inside the inner templates; the already
    rendered body and stylesheet are marked safe here so the shell does not escape
    them a second time."""
    return _ENV.from_string(_SHELL).render(
        title=title, content=Markup(content), style=Markup(style)
    )


def render_table(index: Index) -> str:
    payload = _payload(index)
    blockers = sum(1 for p in index.problems if p.severity == "blocker")
    body = _ENV.from_string(_TABLE).render(payload=payload, blockers=blockers)
    body = body.replace("PAYLOAD_JSON", json.dumps(payload))
    return _page("openproj — table", body, _TABLE_STYLE)


def render_graph(index: Index) -> str:
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
    return _page("openproj — graph", body, "#cy { height: 78vh; border: 1px solid var(--line); }")


def render_timeline(index: Index) -> str:
    body = _ENV.from_string(_TIMELINE).render(t=_timeline(index))
    return _page("openproj — timeline", body, _TIMELINE_STYLE)


def render_static(index: Index, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, html in (
        ("index.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
