"""The filter bar, the combobox and the field controls every editable page draws."""

from __future__ import annotations

import json

from markupsafe import Markup

from ..index import Index
from ..model import MAX_BODY_BYTES, Record
from .env import _fragment
from .hill import _hill_html
from .tokens import HISTORY_MARKS, PEOPLE_FIELDS, PRIORITIES, _human

# The control bar, for every view that filters something. The field list is a
# parameter because the people page filters by role, kind and status while the
# plan's three views filter by nine fields and a flag — and that page used to
# draw the whole bar again by hand, which is how a search box comes to be labelled
# on one page and not on the next.
_FACETS = """
<div id="controls">
  <div class="searching">
  {#- A placeholder is not a name: it is gone the moment anything is typed, and
      it never reaches the accessibility tree as one. Every dropdown beside this
      box is wrapped in its `<label>`; the search box was the one control in the
      bar that had nothing to say what it searches. -#}
  <input id="q" type="search" aria-label="{{ search }}" placeholder="{{ search }}">
  {#- What is wrong with what is in the box. Here rather than in each view,
      because the box is in the bar and the bar is shared: the table can say it
      again over its own empty rows, and does, but the graph and the timeline
      draw pictures and have nowhere to put a sentence at all.
      `role="status"` and polite: a query is typed a character at a time, and a
      reader who is told about every half-finished bracket as an alert is a
      reader who turns the page off. -#}
  <span id="query-error" role="status" aria-live="polite" hidden></span>
  {#- The way out, beside the box that gets you in. Drawn only when something is
      actually set: a Clear that is always there is a control that does nothing
      most of the time, and the reader has to read it to find that out. It is not
      `#clear-filters` — the table draws one of those inside its own empty state,
      where a reader who has filtered everything away is looking, and two elements
      cannot share an id. -#}
  <button type="button" id="unfilter" hidden>Clear filters</button>
  {#- The far end of the search box's line, for what a page has to say about the
      view it draws. A slot rather than a sentence, because the three views say
      different things there — how to pan the graph, which window the timeline is
      showing — and not one of them is worth a row of its own on a page whose
      whole point is the drawing underneath. -#}
  {% if aside %}<div class="aside">{{ aside }}</div>{% endif %}
  </div>
  <div class="facets">
  {#- A field is a button and a list of checkboxes, and not a `<select>`, because
      the filter underneath has always been able to answer more than a select can
      ask: `apply_filters` ORs within a field and ANDs across them, and the URL
      has always carried a field twice. The menu was the only thing insisting on
      one value, and a control that can express less than the thing it controls
      is a control that hides half the tool.

      Checkboxes and not a `<select multiple>`: the native one costs four rows of
      height per field on a bar of ten of them, and de-selecting is ctrl-click,
      which is folklore. Real `<input type="checkbox">` inside real `<label>`s
      rather than a listbox with `aria-selected`, because a checkbox already
      means "several of these, independently" to every reader and every screen
      reader, and the roles this would otherwise need are the part people get
      wrong. -#}
  {% for field in fields %}
  <div class="facet" data-field="{{ field }}">
    <button type="button" class="facetopen" id="facet-{{ field }}" aria-expanded="false">
      <span class="facetname">{{ label(field) }}</span>
      {#- What is chosen, in the control rather than only in the popup: a filter
          you cannot see is a filter you forget you set, and this bar spends most
          of its life closed. -#}
      <span class="facetsaid">all</span>
    </button>
    <div class="facetmenu" role="group" aria-labelledby="facet-{{ field }}" hidden>
      {% for value in facets.get(field, []) %}
      {#- The value is what the filter matches and what the URL carries; the word
          beside it is what a person reads. They are the same string for a status
          and a login and are not for a project, whose values are ids — `Project:
          proj-370001` is a menu that asks you to know the plan by heart. -#}
      <label><input type="checkbox" value="{{ value }}">{{
        titles.get(value) or value|human }}</label>{% endfor %}
    </div>
  </div>
  {% endfor %}
  </div>
</div>
"""

# The plan's own filters, in the order the bar draws them. `predicate` is last and
# is a field like any other here: its values are `index.facets["predicate"]`, so
# the select it needs is the select every other field gets.
_PLAN_FACETS = (
    "kind", "priority", "status", "owner", "assignees", "reviewers",
    "cycle", "product", "project", "tags", "predicate",
)

# The filter model itself, shared by every view that offers the bar above. The
# README has always said three views filter the same plan the same way; while
# `matches` lived inside the table's script, that was true of one of them, and a
# second copy of it is how a facet comes to mean something different per page.
_FILTER_JS = Markup(r"""
<script>
const params = new URLSearchParams(location.search);

// Every field the control bar offers. A field in one list and not the other is a
// dropdown that changes the URL and filters nothing.
const FILTERS = ['kind','status','owner','assignees','reviewers','priority',
                 'cycle','product','project','tags'];

// The menu option that means "this field is empty". Spelled here as a literal
// and in `index.NO_VALUE` in Python, because this block is a constant rather
// than a template — `test_empty_is_spelled_the_same_on_both_sides_of_the_wire`
// is what stops the two drifting, and a drift would filter differently in the
// browser than on the server with neither one erroring.
const NO_VALUE = '(none)';

function wanted(field) { return params.getAll(field).filter(Boolean); }

// --- the query language ----------------------------------------------------
//
// The second implementation of `query.py`, and it has to be a second one: the
// static export has no server to ask and this table filters without one. The
// two are pinned together by results rather than by source — a corpus of
// queries run through both in `tests/test_search.py` — because that is the only
// claim worth making about two parsers.
//
// Every rule here is argued in `query.py`. The short version: adjacency is AND,
// `not` binds tightest then `and` then `or`, an unknown field matches nothing
// rather than everything, and a query that cannot be read matches nothing and
// says why.

// The fields a query may name, and the alias each is asked by. Written out
// rather than derived from the row, because a row also carries `progress`,
// `derived` and eleven other things nobody would type — and because the same
// list exists in `index.py`, where `test_the_two_field_lists_are_the_same` holds
// the two together.
const QUERY_FIELDS = ['kind','status','owner','priority','cycle','assignees',
                      'reviewers','tags','product','project','id','title','prs','predicate'];
const ALIASES = {tag: 'tags', assignee: 'assignees', reviewer: 'reviewers',
                 pr: 'prs', person: 'owner'};
// Free text, matched by substring; everything else is a vocabulary and is
// matched whole, so `cycle:3` does not answer for cycle 30.
const FREE_TEXT = ['title', 'prs'];

// One record's values per field, lowered — the same map `query_fields` builds in
// `index.py`, so both parsers are asked about identical data and a disagreement
// between them is the language rather than the plan.
function queryFields(row) {
  const fields = {};
  for (const name of QUERY_FIELDS) {
    // `predicates` on the row, `predicate` in the language: the menu is named
    // for the question and the row for its answers.
    const held = name === 'predicate' ? row.predicates : row[name];
    fields[name] = [].concat(held ?? []).map(String).map(v => v.toLowerCase())
      .filter(v => v !== '');
  }
  return fields;
}

// `[text, wasQuoted]` per token, with the brackets as their own. Quoting is
// tracked and not forgotten: `"and"` is a word rather than the operator, and the
// colon inside `title:"a: b"` belongs to the value. The NUL marks the one colon
// that splits the term, found here rather than searched for again later.
function queryTerms(text) {
  const tokens = [];
  let i = 0;
  while (i < text.length) {
    if (/\s/.test(text[i])) { i++; continue; }
    if (text[i] === '(' || text[i] === ')') { tokens.push([text[i], false]); i++; continue; }
    let buffer = '', quoted = false, colon = -1;
    while (i < text.length && !/\s/.test(text[i]) && text[i] !== '(' && text[i] !== ')') {
      if (text[i] === '"') {
        const closes = text.indexOf('"', i + 1);
        if (closes < 0) throw new QueryError('a quote is opened and never closed');
        buffer += text.slice(i + 1, closes);
        quoted = true;
        i = closes + 1;
        continue;
      }
      if (text[i] === ':' && colon < 0) colon = buffer.length;
      buffer += text[i];
      i++;
    }
    tokens.push([colon < 0 ? buffer
      : buffer.slice(0, colon) + '\u0000' + buffer.slice(colon + 1), quoted]);
  }
  return tokens;
}

class QueryError extends Error {}

function queryTerm(raw, quoted) {
  const colon = raw.indexOf('\u0000');
  if (colon >= 0) {
    const name = raw.slice(0, colon).toLowerCase(), value = raw.slice(colon + 1);
    if (!name || !value)
      throw new QueryError('a field and a value both have to be there, as `field:value`');
    return {field: ALIASES[name] || name, value: value.toLowerCase()};
  }
  if (!raw) throw new QueryError('there is nothing between the quotes');
  return {word: raw.toLowerCase()};
}

function queryTree(text) {
  const tokens = queryTerms(text);
  let at = 0;
  const peek = () => at < tokens.length ? tokens[at] : null;
  const keyword = word => {
    const token = peek();
    return !!token && !token[1] && token[0].toLowerCase() === word;
  };
  const done = () => { const token = peek(); return !token || (token[0] === ')' && !token[1]); };

  function either() {
    let node = both();
    while (keyword('or')) {
      at++;
      if (done()) throw new QueryError('`or` needs something on both sides of it');
      node = {either: [node, both()]};
    }
    return node;
  }
  function both() {
    let node = unary();
    for (;;) {
      if (keyword('and')) {
        at++;
        if (done()) throw new QueryError('`and` needs something on both sides of it');
      } else if (done() || keyword('or')) {
        return node;
      }
      node = {both: [node, unary()]};
    }
  }
  function unary() {
    if (keyword('not')) {
      at++;
      if (done()) throw new QueryError('`not` needs something to take away');
      return {not: unary()};
    }
    const token = peek();
    if (!token) throw new QueryError('the query stops in the middle');
    if (token[0] === '(' && !token[1]) {
      at++;
      // Asked here and not left to the parse inside: `kind:task and (` is a
      // bracket somebody just opened, and being told the query stops in the
      // middle is true and useless.
      if (!peek()) throw new QueryError('a bracket is opened and never closed');
      if (peek()[0] === ')') throw new QueryError('there is nothing inside the brackets');
      const node = either();
      const closing = peek();
      if (!closing || closing[0] !== ')')
        throw new QueryError('a bracket is opened and never closed');
      at++;
      return node;
    }
    if (token[0] === ')' && !token[1])
      throw new QueryError('a bracket is closed that was never opened');
    const word = token[1] ? '' : token[0].toLowerCase();
    if (word === 'and' || word === 'or')
      throw new QueryError('`' + word + '` needs something on both sides of it');
    at++;
    return queryTerm(token[0], token[1]);
  }

  if (!tokens.length) return null;
  const node = either();
  if (peek() !== null) throw new QueryError('a bracket is closed that was never opened');
  return node;
}

function answers(node, fields, text) {
  if (node === null) return true;
  if ('word' in node) return text.includes(node.word);
  if ('not' in node) return !answers(node.not, fields, text);
  if ('both' in node)
    return answers(node.both[0], fields, text) && answers(node.both[1], fields, text);
  if ('either' in node)
    return answers(node.either[0], fields, text) || answers(node.either[1], fields, text);
  // A field this plan has not got: nothing, and not everything. Filter state is
  // hand-editable, and a typo that widens a result set is worse than one that
  // visibly empties it.
  if (!(node.field in fields)) return false;
  const held = fields[node.field];
  if (node.value === NO_VALUE) return !held.length;
  if (FREE_TEXT.includes(node.field)) return held.some(value => value.includes(node.value));
  return held.includes(node.value);
}

// Parsed once per query and not once per row: the table redraws on every
// keystroke over as many rows as the plan has, and parsing `kind:task` two
// hundred times to answer one question is two hundred parses.
let ASKED = {text: null, tree: null, error: ''};
function asked() {
  const text = params.get('q') || '';
  if (text === ASKED.text) return ASKED;
  try {
    ASKED = {text, tree: queryTree(text), error: ''};
  } catch (error) {
    if (!(error instanceof QueryError)) throw error;
    ASKED = {text, tree: null, error: error.message};
  }
  return ASKED;
}

// What is wrong with what is in the box, or '' if nothing is. The views draw
// this beside the rows: a query somebody is halfway through typing must not look
// like a plan with nothing in it.
function queryError() { return asked().error; }

// AND between fields, OR inside one: two owners means either of them, an owner
// and a status means both. Anything shaped like a table row can be asked — the
// graph hands it a node's data, which is that same row.
function matches(row) {
  // The query language, over `row.search` for a bare word — what is searchable is
  // decided once, by `SEARCH_FIELDS` in `index.py`, and shipped on the row. This
  // line used to read `row.title + ' ' + row.tags`, which is neither what
  // `apply_filters` searched nor what the placeholder promised: a table that
  // quietly searches less than the link you were sent is a table that lies twice.
  const query = asked();
  if (query.error) return false;
  if (!answers(query.tree, queryFields(row), row.search || '')) return false;
  for (const field of FILTERS) {
    const values = wanted(field);
    if (!values.length) continue;
    // `held` is empty for a field nobody has filled in, which no value in the
    // menu can ever match — so emptiness gets its own option, and it asks about
    // the list rather than looking inside it. Server-side `apply_filters` in
    // index.py answers the same question the same way; the sentinel is spelled
    // once, in `NO_VALUE` there, and reaches here through the template.
    const held = [].concat(row[field] ?? []).map(String).filter(v => v !== '');
    const empty = values.includes(NO_VALUE) && !held.length;
    if (!empty && !values.some(v => held.includes(v))) return false;
  }
  const preds = wanted('predicate');
  if (preds.length && !preds.some(p => row.predicates.includes(p))) return false;
  return true;
}

// The controls take their state from the query string rather than from
// themselves, so a filtered view somebody pasted to you opens with its dropdowns
// already set.
function syncFilters() {
  // Every control takes its state from the query string rather than from itself,
  // so a filtered view somebody pasted to you opens with its boxes already
  // ticked — and so a Clear is one `params.delete` rather than a sweep of the
  // DOM that has to find every control it drew.
  for (const facet of document.querySelectorAll('.facet[data-field]')) {
    const chosen = params.getAll(facet.dataset.field).filter(Boolean);
    for (const box of facet.querySelectorAll('input[type=checkbox]'))
      box.checked = chosen.includes(box.value);
    facet.querySelector('.facetsaid').textContent = facetSummary(facet, chosen);
    // The class the accent hangs off. On the wrapper and not the button, so a
    // field that is set reads as set whether its menu is open or closed.
    facet.classList.toggle('chosen', chosen.length > 0);
    // The button says what is set, and the button is also what a reader who
    // cannot see it hears — so the count goes in the accessible name too, and
    // not only in the ink.
    facet.querySelector('.facetopen').setAttribute(
      'aria-label', `${facetLabel(facet)}: ${facetSummary(facet, chosen)}`);
  }
  document.getElementById('q').value = params.get('q') || '';
  sayQueryError();
  showTheWayOut();
}

// Whether anything is set at all, asked of the query string rather than of the
// controls: the query string is the state, and the people page's `role` is a
// field the record list below has never heard of.
function showTheWayOut() {
  const out = document.getElementById('unfilter');
  if (!out) return;
  const fields = [...document.querySelectorAll('.facet[data-field]')]
    .map(facet => facet.dataset.field);
  const set = [...fields, 'q', 'predicate']
    .some(field => params.getAll(field).filter(Boolean).length);
  out.hidden = !set;
}

function facetLabel(facet) {
  return facet.querySelector('.facetname').textContent.trim();
}

// `all`, the value itself, or how many.
//
// `facetSummary` and not `summarise`: the table already has a `summarise` that
// writes "17 of 17 shown", and these two scripts are two `<script>` blocks in one
// global scope. The first version of this function was named that, and the table's
// won — so every field's button said `undefined` while nothing threw. Everything
// this block declares is named for the bar for that reason; see
// `test_no_two_scripts_on_a_page_declare_the_same_name`. One value is named because naming it is
// the whole point of a closed control saying anything; three are counted because
// three tag names do not fit in a button on a bar of ten of them.
//
// The word comes off the checkbox the server drew rather than from a map: this
// script is shared by every page with a filter bar — records, the table, the
// graph, the timeline, the people page — and `HUMAN` is the table's payload, so a `human`
// of its own here would be the same vocabulary written twice — and `in_progress`
// would read as itself on the one page that had not been given the map.
function facetSummary(facet, chosen) {
  if (!chosen.length) return 'all';
  if (chosen.length > 1) return `${chosen.length} chosen`;
  const box = facet.querySelector(`input[type=checkbox][value="${CSS.escape(chosen[0])}"]`);
  return box ? box.parentNode.textContent.trim() : chosen[0];
}

// The half of "a malformed query says so and matches nothing" that says so. The
// other half is `matches`, which keeps every row out — and on its own that is a
// plan that looks empty, which is the failure this repository keeps finding in
// new places.
function sayQueryError() {
  const where = document.getElementById('query-error');
  if (!where) return;
  const said = queryError();
  where.textContent = said;
  where.hidden = !said;
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

// One value of one field, on or off, leaving the field's other values alone.
// `delete` then `append` per value rather than a `set`, because `set` is the one
// value a select could hold and this control's whole point is that a field can
// be asked about twice.
function chooseValue(field, value, wanted) {
  const chosen = params.getAll(field).filter(Boolean).filter(v => v !== value);
  if (wanted) chosen.push(value);
  params.delete(field);
  for (const one of chosen) params.append(field, one);
  settled();
}

function clearFilters() {
  // Every control the page actually draws, and not only the record fields above:
  // the people page filters by role, which is not a field of a record, and a
  // Clear that left it set is a Clear that did not clear.
  const onPage = [...document.querySelectorAll('.facet[data-field]')]
    .map(facet => facet.dataset.field);
  // Not the sort order: clearing the filters and losing the column somebody
  // sorted by is a second surprise on top of the one they were undoing.
  for (const field of [...FILTERS, ...onPage, 'predicate', 'q']) params.delete(field);
  settled();
}

document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
const UNFILTER = document.getElementById('unfilter');
if (UNFILTER) UNFILTER.onclick = clearFilters;

// --- opening and closing a field -------------------------------------------
//
// One listener on the bar rather than one per control: the bar is drawn once by
// the server and never rebuilt, but a listener per checkbox on a plan with two
// hundred tags is two hundred listeners for a thing that can be asked once.

const FACET_BAR = document.getElementById('controls');

function openFacet(facet, open) {
  facet.querySelector('.facetmenu').hidden = !open;
  facet.querySelector('.facetopen').setAttribute('aria-expanded', String(open));
}

function closeFacets(except) {
  for (const facet of document.querySelectorAll('.facet[data-field]'))
    if (facet !== except) openFacet(facet, false);
}

if (FACET_BAR) {
  FACET_BAR.addEventListener('click', event => {
    const opener = event.target.closest('.facetopen');
    if (opener) {
      const facet = opener.closest('.facet');
      const open = opener.getAttribute('aria-expanded') !== 'true';
      closeFacets(facet);
      openFacet(facet, open);
      return;
    }
    // A click anywhere else inside the bar that is not in a menu closes the
    // menus: the labels and the search box are in here too.
    if (!event.target.closest('.facetmenu')) closeFacets(null);
  });

  FACET_BAR.addEventListener('change', event => {
    const box = event.target.closest('.facetmenu input[type=checkbox]');
    if (box) chooseValue(box.closest('.facet').dataset.field, box.value, box.checked);
  });

  // Escape closes the menu and hands the keyboard back to the button that opened
  // it. Without the second half, Escape drops focus on `<body>` and the next Tab
  // starts from the top of the page — which is the same defect the draft row's
  // Escape had, in a different control.
  FACET_BAR.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const facet = event.target.closest('.facet');
    if (!facet || facet.querySelector('.facetmenu').hidden) return;
    event.stopPropagation();
    openFacet(facet, false);
    facet.querySelector('.facetopen').focus();
  });
}

// Outside the bar entirely. `pointerdown` and not `click`, so a menu that is over
// the thing somebody is reaching for is gone before the press lands on it.
addEventListener('pointerdown', event => {
  if (!event.target.closest('.facet')) closeFacets(null);
});

syncFilters();
</script>
""")


# Raw, because the JS in here contains regex escapes. `\\.` is not a Python escape,
# so it survived as a literal backslash and the widget worked — while emitting a
# SyntaxWarning on every fresh compile, and Python 3.14 turns that into an error.
_COMBOBOX = r"""
<script id="suggest" type="application/json">{{ suggest|tojson }}</script>
<script>
// --- the textarea, as a surface --------------------------------------------
//
// Everything between this banner and the one that closes it is the only code on
// any page `_COMBOBOX` ships on that knows the document is being written in a
// `<textarea>`. Nothing outside it reads `.value`, `selectionStart`,
// `selectionEnd` or calls `setSelectionRange`, and
// `test_the_body_is_read_through_one_place_and_nothing_else` holds it there.
//
// **Seven operations, and the shape of them is measured rather than guessed.**
// `docs/EDITOR.md`'s "What the skeptics broke" is the evidence, in full, against
// a real editor and this repository's own `Room`; three findings decide what is
// here and what deliberately is not:
//
// * A textarea's programmatic `.value =` fires ZERO input events, and that —
//   nothing else — is why this application has never needed a re-entrancy guard.
//   Every other surface fires its change event for its own edits and the page's
//   alike, indistinguishably. So `applying` is here NOW, with a test.
// * **There is no "set the text", and that absence is the design.** Every
//   measured one is remove-all-then-insert-all: two change events with an EMPTY
//   DOCUMENT between them, which no prefix/suffix walk can recover a splice
//   from. One remote four-character keystroke reflected that way made a PASSIVE
//   tab push a whole 97,890-character body up the socket and take the authorship
//   credit for it — 6,700x, `MAX_OUTBOX_BYTES` full in three frames. The one
//   write is `splice`, and a whole-document replacement has to say so in words.
// * **Every index here is a UTF-16 CODE UNIT** — what `selectionStart` counts,
//   what a `Y.Text` is counted in inside a browser, and what `Room.sits` relays.
//   `units()` in `_COEDIT` is the one conversion at the one boundary and
//   `coedit.byte_offset` is its server twin.
//
// The seven: `text`, `caret`, `setCaret`, `splice`, `onInput`, `onCaret`,
// `seats`. Three more are on the object and are NOT of that set, each for a
// reason given where it is defined: `apply`, `lineCoords` and `el`.
//
// The seventh used to be `coordsAt` — where the carets at these indexes are
// drawn — and it existed for exactly one caller, the seat bands, back when the
// page measured them itself and each surface only answered where a row was.
// Ace's answer to "where is this index drawn" is a screen row inside a layer it
// owns, which is not a number the page can put a `<div>` at; so the surfaces
// stopped answering where and started answering DRAW THEM, and the caller went
// with the answer. Nothing else ever asked, which is why it is gone rather than
// kept for a second consumer that has not turned up in the life of this file the
// question has existed.

// Every programmatic edit to a textarea goes through here.
//
// `textarea.value = ...` wipes the browser's native undo stack: paste a diagram
// into a four-hundred-line pitch, press ctrl-Z, and the last ten minutes are
// gone with no way back. `execCommand('insertText')` is deprecated and is also
// the only API in any shipping browser that edits a textarea as though a person
// had typed — one undo step, selection handled, `input` fired for free. The
// fallback keeps the feature working if it is ever removed; it loses undo, which
// is the least bad of the things that can be lost.
//
// Called from one place now — `splice` below — rather than from fifteen, which
// is what lets the guard test say "one place" and mean it.
function replaceRange(area, text) {
  area.focus();
  if (document.execCommand && document.execCommand('insertText', false, text)) return;
  const {selectionStart: from, selectionEnd: to} = area;
  area.value = area.value.slice(0, from) + text + area.value.slice(to);
  area.selectionStart = area.selectionEnd = from + text.length;
  area.dispatchEvent(new Event('input', {bubbles: true}));
}

function textareaSurface(area) {
  // The re-entrancy flag: belt and braces on a textarea, and the whole of the
  // difference on anything else between reflecting somebody's keystroke and
  // pushing the document back up the socket under your own name. A flag
  // introduced with the boundary has a written reason; one introduced with the
  // second surface is one added under pressure.
  let applying = false;
  const heard = {input: [], caret: []};
  const fire = kind => { for (const listener of heard[kind]) listener(); };

  // Two element listeners for the whole page, and the order between them is
  // fixed rather than left to whoever attached first: on an `input` event every
  // `onInput` subscriber runs, then every `onCaret` one.
  area.addEventListener('input', () => { if (!applying) fire('input'); });
  // What moves a caret, and none of it is an `input` — except typing, which is
  // why `input` is in the list too. Every subscriber here is idempotent on the
  // position: `sit()` compares against what it last sent, `refresh()` recomputes.
  //
  // NOT gated on `applying`: a position that really did move is one the caret
  // readout and the seat layer both want, and it moving because somebody else
  // typed is the case the seat layer exists for.
  for (const kind of ['input', 'keyup', 'click', 'select', 'focus']) {
    area.addEventListener(kind, () => fire('caret'));
  }

  return {
    // The box, for the questions that are about a box rather than a document:
    // scroll offsets, class names, `closest`, and the events the seven do not
    // cover — keydown, paste, drop, scroll. Never for its text.
    el: area,

    // 1. The whole document, in UTF-16 code units.
    text: () => area.value,

    // 2. Where the caret is, as a range, because it is one: an empty selection
    // is `from === to`. Both in UTF-16 code units.
    caret: () => ({from: area.selectionStart, to: area.selectionEnd}),

    // 3. And where to put it. One argument means an empty selection there.
    setCaret(from, to) { area.setSelectionRange(from, to === undefined ? from : to); },

    // 4. The only write. `[from, to)` in UTF-16 code units, replaced by `put`.
    //
    // Two ways, and `applying` is which. A person's edit — a toolbar button, an
    // indent, an upload's placeholder — goes through `execCommand`: one undo
    // step, `input` fired, and the room hears it as typing, which is what it is.
    // The page's own write goes through the `.value` setter with the caret
    // carried across, which fires nothing and steals no focus.
    //
    // That setter wiping the native undo stack is a live defect and it is this
    // stage's job NOT to fix it: `reflect()` has done exactly this on every
    // remote keystroke since rooms shipped, S4 answers it with `Y.UndoManager`,
    // and a commit that changes the co-editing path and a behaviour at once is
    // one whose regression cannot be attributed to it.
    splice(from, to, put) {
      if (!applying) {
        area.setSelectionRange(from, to);
        replaceRange(area, put);
        return;
      }
      const was = area.value;
      const start = area.selectionStart, end = area.selectionEnd;
      const shift = put.length - (to - from);
      // Anything before the splice stays put; anything after it moves by the
      // difference, and nothing may end up before where the splice began.
      const moved = at => at <= from ? at : Math.max(from, at + shift);
      area.value = was.slice(0, from) + put + was.slice(to);
      // Only when this box has the caret: `setSelectionRange` on an unfocused
      // textarea also scrolls it, and a page scrolling itself because somebody
      // else typed is the thing nobody asked for.
      if (document.activeElement === area) area.setSelectionRange(moved(start), moved(end));
    },

    // 5 and 6. The two subscriptions. `onInput` is "the text changed and a
    // person did it"; `onCaret` is "the caret is somewhere else".
    onInput(listener) { heard.input.push(listener); },
    onCaret(listener) { heard.caret.push(listener); },

    // 7. Where everybody ELSE in the room is: a translucent band on the row each
    // of their carets is in, with the login on the right.
    //
    // **A member, and it used to be a `provides.seats` boolean.** The flag was
    // false on Ace, and a boolean whose false arm has no other implementation to
    // pick is not a capability — it is an absence, and it showed: the false arm
    // grew an `announce` in the middle of `drawSeats`'s drawing loop, where
    // `attachGutter`'s clean early return needs none. Now that both surfaces can
    // draw, a flag beside this member would be a second spelling of what the
    // member already says, and two spellings drift. `history` is the precedent —
    // there the boolean picks between two real implementations of one contract —
    // and a surface that genuinely cannot draw seats is handled the way
    // `onSplice` is, by not being here.
    //
    // The mirror stays on this side of the boundary with `rowTops` and the rest
    // of the measuring, and `#seats` is a layer only this surface writes to. The
    // hue arrives already computed, so one rule colours both surfaces and the
    // same person is the same colour in every window in the room.
    seats: {
      draw(others) {
        const layer = document.getElementById('seats');
        if (!layer) return;
        // A box nothing is drawing has no rows to sit on. The roster arrives
        // while the page is still in read mode, where this box is `display: none`
        // and every measurement is zero — and a mirror given a width of zero
        // wraps the whole document one character per row before answering with a
        // number that means nothing. `openproj:editing` brings everyone back.
        if (!area.getClientRects().length) { layer.replaceChildren(); return; }
        const style = getComputedStyle(area);
        const height = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
        const tops = rowTops(area, area.value, others.map(seat => seat.at));
        // The layer fills `.bodywrap`, whose top is the box's border box, while
        // `rowTops` answers from its padding box. One border-width, on every band.
        const origin = textTop(area, layer);
        layer.replaceChildren(...others.map((seat, which) => {
          const band = document.createElement('div');
          band.className = 'seat';
          band.style.top = (origin + tops[which] - area.scrollTop) + 'px';
          band.style.height = height + 'px';
          band.style.background = `hsl(${seat.hue} 70% 60% / .22)`;
          const who = document.createElement('span');
          who.className = 'seatname';
          who.style.background = `hsl(${seat.hue} 70% 60% / .85)`;
          // `textContent`, because this is a login off a socket.
          who.textContent = seat.login;
          band.appendChild(who);
          return band;
        }));
      },
      clear() {
        const layer = document.getElementById('seats');
        if (layer) layer.replaceChildren();
      },
    },

    // 8. Undo and redo, which on a `<textarea>` belong to the browser.
    // `execCommand` for the same reason `replaceRange` uses it: it is the one
    // API in any shipping browser that reaches the stack Ctrl+Z reaches.
    //
    // **Truthful only while nothing has assigned `.value`.** Measured in Chrome:
    // type, then `area.value = 'x'`, and `queryCommandEnabled('undo')` goes on
    // answering TRUE while `execCommand('undo')` returns true and moves nothing.
    // A wiped native stack does not come up empty, it LIES — which is why
    // `provides.history` is false and why a room takes this question off the box.
    history: {
      // Asked rather than trusted: `queryCommandEnabled` is not a standard and a
      // throw inside a listener that runs on every keyup is a toolbar that stops
      // redrawing itself.
      can(what) {
        try { return document.queryCommandEnabled(what); } catch (error) { return true; }
      },
      // Focused first, for the reason `replaceRange` focuses the box: a toolbar
      // press is a continuation of typing. And a refusal says so out loud.
      step(what) {
        area.focus();
        if (document.execCommand && document.execCommand(what)) return;
        announce(`This browser would not ${what} from a button. `
                 + `${what === 'undo' ? 'Ctrl+Z' : 'Ctrl+Shift+Z'} still works — `
                 + 'that one is the browser’s own.');
      },
      // Whether the page has to take the keystroke. It does not: the browser's
      // binding reaches this stack and restores the SELECTION the edit was made
      // with, which `execCommand` alone does not.
      keyed: false,
    },

    // What this surface does for itself, so the page does not do it twice or
    // ask for something that is not there. A capability and not a type name:
    // `if (surface.kind === 'ace')` puts the second surface's name in six
    // functions that have no other business knowing it, and the third surface
    // then has to be added to all six. Two entries, because two things differ.
    //
    // `gutter` — a textarea has no line numbers, so `attachGutter` draws them
    // through a mirror. Ace draws its own, and two gutters is one too many.
    // `seats` was the third entry here and is now a member above, because both
    // surfaces answer it: Ace draws the band in its own marker layer, from its
    // own screen rows, on the frame it draws the selection on. The note that
    // stood here said an untested band is a band one line off, which was right;
    // what changed is that it is measured now, at eighty widths, scrolled and
    // folded, in `tests/test_seats.py`.
    // `history` — whether this surface's undo stack SURVIVES somebody else
    // typing. False, and that is a fact about textareas: a remote change reaches
    // the box as an assignment to `.value` (`splice` under `apply`, the one
    // place allowed to), which wipes the native stack. `historyOf` reads this to
    // decide whether the room's `Y.UndoManager` answers the buttons instead.
    provides: {gutter: false, history: false},
    // Which of the two this IS, in the vocabulary the address and the preference
    // already use — and it exists for exactly one consumer, the switch beside the
    // three view segments, which has to say out loud which editor a person is
    // writing in. **Never branch on it.** A behavioural difference between the
    // surfaces goes in `provides` above, for the reason written there; this is a
    // label, and the one question a capability cannot answer is what to call the
    // thing. It is the mounted surface and not `EDITOR.editor`, which is only
    // what was asked for: on a copy of this page saved to a file the two come
    // apart, because there is no server to fetch the other bytes from.
    //
    // Not `editor`, which was the first spelling and lasted one test run: the Ace
    // surface already publishes `editor`, and it is the Ace instance. A second
    // key of that name later in the same object literal is not an error anywhere
    // — it silently wins, and every use of the real one became a string.
    editorName: 'plain',

    // The scroll offset, and the three ways the page asks about it. These used
    // to be `el.scrollTop` and `el.addEventListener('scroll')` at four call
    // sites, which the adapter's own report named as the hole left open: `el`
    // let anything reach the box, and a surface that is not a box has no
    // `scrollTop` and fires no `scroll`. Ace's scroller is an inner element and
    // its offset arrives as `changeScrollTop` on the session, so the two sides
    // agree on the number and on nothing else.
    scrolled: () => area.scrollTop,
    scrollTo(top) { area.scrollTop = top; },
    onScroll(listener) { area.addEventListener('scroll', listener); },

    // The page writing rather than a person. The previous value is restored
    // rather than `false` assumed, so nesting is safe; the `finally` is what
    // stops one throw inside a reflect leaving this page deaf to every keystroke
    // after it.
    apply(run) {
      const before = applying;
      applying = true;
      try { return run(); } finally { applying = before; }
    },
    applying: () => applying,

    // NOT one of the seven, and here rather than as a bare `lineTops(el)` at two
    // call sites so the mirror stays on this side of the boundary. Where every
    // logical LINE starts — the gutter's question on every keystroke, the scroll
    // sync's on every resize. Separate from `rowTops`, which `seats` above uses,
    // because it is ONE layout of the document where that is one forced reflow
    // per index: asking it per line start would turn the gutter's measured 6.5ms
    // at 1,000 lines into a thousand reflows.
    lineCoords() { return lineTops(area, area.value); },
  };
}

// --- end of the textarea surface -------------------------------------------


// Which of the two the page got. The decision is the SERVER's, because the
// server is what decides whether 594 KB is in the page at all. `remembered` is
// `localStorage` and the server cannot read it, which is why the address carries
// the choice and the preference only carries it back on the next visit.
//
// **The default is Ace, and the parameter is the way out of it** — jcanton,
// 2026-08-20, on Ace becoming what a writer gets: "I think it's worth it". Only
// the default arm moved; the machinery is the same machinery. The reload the
// sticky preference costs moved with it, onto the people who want the plain
// box — and that is the better side to pay it on, because the alternative was an
// Ace writer paying a redirect on every record and paying it by downloading
// 594 KB twice.
//
// `editable` is gated on `base_commit` alone, so a signed-out reader already
// receives the textarea and `attachEditing` — an Ace block at that gate would
// have shipped 594 KB to every public reader, 4.19x their page. `_ace_wanted`'s
// `may_write` is what keeps that at zero, and it did not move.
//
// The branch where the second editor was ASKED for and the bytes are not here
// says so. A static export has no server to ask, so `detail.html?editor=ace`
// opened from a memory stick is exactly that case, and a page that silently
// gives you the other editor is a page you report as broken.
function bodySurface(area) {
  // Built either way, because it is the one place that reads the box — the Ace
  // surface is SEEDED from it rather than reading the textarea itself, so "the
  // document is read in exactly one place" stays literally true with two
  // surfaces in the tree. An unsubscribed surface is two listeners on an element
  // nothing else touches.
  const box = textareaSurface(area);
  if (EDITOR.editor !== 'ace') {
    // Wanted the plain box and the library came anyway, which means the address
    // has not told the server yet. One reload gets the page this person asked
    // for, and it is the only place in this function that navigates for the sake
    // of BYTES rather than for the sake of a feature — the surface below would
    // work perfectly well over 594 KB nobody is going to use, and shipping it
    // silently is how a preference becomes decorative.
    if (typeof ace !== 'undefined') stickyEditor();
    return box;
  }
  if (typeof ace !== 'undefined') return aceSurface(area, box.text());
  // Ace, and it is not here. Two situations, and only one of them is news.
  //
  // **The default is not news**, and this line is what the flip made necessary.
  // Every signed-out reader now resolves to `ace` without having said anything,
  // and `may_write` correctly sends them no library — so without this guard the
  // sentence below would be read out on every record to every reader, about a
  // thing they never asked for. `chosen` is the difference between a decision
  // that cannot be honoured and a default that was never going to be.
  if (!EDITOR.chosen) return box;
  // Either this browser remembers the choice and the address does not carry it —
  // go and ask the server for it, which is what makes the preference stick at
  // all — or there is no server to ask, and then say so.
  if (stickyEditor()) return box;
  // Said in what is true rather than in a guess at why: there are two ways to be
  // here — a page saved to a file, which has no server to ask, and a reader the
  // server would refuse a save from, who gets the box and the toolbar and would
  // get no use out of a keymap. The sentence covers both.
  announce('This page does not carry the second editor. It is inlined only where the '
           + 'server would take a save from you, and this copy of the page has none of '
           + 'it. Still editing in the ordinary box.');
  // And then stop asking. The address DID carry the request, the server answered
  // it by sending no library, and a remembered choice that cannot be honoured
  // costs a redirect on every page for nothing. Only in that case: a page opened
  // from a file was never asked, and forgetting there would clear somebody's
  // choice because they read an export.
  if (new URLSearchParams(location.search).has('editor')) {
    rememberEditor({editor: 'plain', chosen: true});
  }
  return box;
}


// The toolbar in the screenshot, in the order and the groups it is drawn in:
// `docs/hackmd-observed.md`, read off the pixels of a real note.
//
// **This overrules a measurement, and the measurement was not wrong.** `d6997e3`
// counted the seed and the migrated HackMD corpora — 485 lines carry an inline
// code span, 161 a bullet, 124 a heading, 83 bold, against 8 markdown links —
// and cut the link button on that count, correctly, because you do not add a
// button before somebody asks for it. Somebody has now asked for it by name:
// "the buttons along the top of the editor", as ask 2 of seven, pointing at that
// screenshot. So link, image and a numbered list are here, and the count is not
// refuted — it is overruled, and the difference is written down so that whoever
// reads this in a year does not mistake one for the other.
//
// Three deliberate departures from the shot, each with a reason:
//
// * **Two code buttons, not one.** The team types on a mix of US and
//   Swiss-German layouts, and on CH a backtick is a dead key — so a fence is
//   three of them in a row, and the two fenced blocks in the whole corpus
//   measure how awkward that is rather than how little code people would paste.
// * **No comment button.** It is a HackMD collaboration feature, not markdown,
//   and there is nothing behind it here. The review channel this team uses is
//   the PR, which every pitch already names in `prs:`.
// * **No comment button** (above), and — until this stage — no undo and redo
//   either. They are the first two buttons in the shot and they were held back
//   with the defect that makes them necessary: a remote keystroke reaches the
//   box as an assignment to `.value`, which wipes the browser's native undo
//   stack, and a history button that does nothing after somebody else types is
//   worse than no button. `Y.UndoManager` in `_COEDIT` is what answers that, so
//   they are here now, leftmost, as the shot has them.
//
// The check list and the strikethrough are still guesses on the shape of the
// documents rather than on a count — a checklist is what a pitch's Progress
// section is made of, a strikethrough is how a dropped line is marked — because
// the migrated corpus is not in this repository and the seed one is synthetic
// and answers zero for both. That grep is still owed.
//
// `group: true` opens a new group; `attachEditing` draws a rule before it.
const FORMATS = [
  // The history group: the two entries here that write no markdown at all.
  // `history` rather than a shape, so `applyMark` never sees one — both the
  // pointer binding and the keyboard branch ask for it first. Drawn rather than
  // typed, because no arrow is in the vendored subset (see `HISTORY_MARKS`), so
  // `label` is the ACCESSIBLE name and not a visible one. ⌘Z and ⌘⇧Z are taken
  // off the browser only where the browser's own has been destroyed —
  // `historyOf`.
  {key: 'z', label: 'Undo', title: 'Undo  ⌘Z', history: 'undo'},
  {key: 'z', shift: true, label: 'Redo', title: 'Redo  ⌘⇧Z', history: 'redo'},

  {key: 'b', group: true, label: 'B', title: 'Bold  ⌘B', wrap: '**'},
  {key: 'i', label: 'I', title: 'Italic  ⌘I', wrap: '*', style: 'font-style: italic'},
  // ⌘⇧X and not ⌘⇧S: the shortcut is matched on `event.key`, and every shifted
  // binding here is a letter, because shift-8 on a US layout is `*` rather than
  // `8` and a shortcut on a digit is one that could never once fire.
  {key: 'x', shift: true, label: 'S', title: 'Strikethrough  ⌘⇧X', wrap: '~~',
   style: 'text-decoration: line-through'},
  {key: '2', label: 'H', title: 'Heading  ⌘2', prefix: '## '},

  {key: 'e', group: true, label: '<>', title: 'Code  ⌘E', wrap: '`'},
  {key: 'e', shift: true, label: '{ }', title: 'Code block  ⌘⇧E', fence: true},
  {key: '.', label: '❝', title: 'Quote  ⌘.', prefix: '> '},
  {key: '8', label: '•', title: 'Bullet list  ⌘8', prefix: '- '},
  // ⌘7 beside ⌘8, on the precedent ⌘8 already set: both are browser tab
  // shortcuts and both are taken back by `preventDefault`, and a numbered list
  // one key from the bulleted one is the pairing anybody would guess.
  {key: '7', label: '1.', title: 'Numbered list  ⌘7', prefix: '1. ', ordered: true},
  {key: 'l', shift: true, label: '[x]', title: 'Check list  ⌘⇧L', prefix: '- [ ] ', box: true},

  {key: 'k', group: true, label: '[]()', title: 'Link  ⌘K', link: true},
  // The one button that does not write markdown. An `![alt](https://…)` typed
  // into this tool draws no picture: `_image` refuses anything that is not an
  // asset this repository stored, on the allowlist rule, and renders it as a
  // link instead. So the image button does what paste and drop already do —
  // uploads the bytes and writes the path they landed at.
  {label: '![]', title: 'Image', upload: true},
  // No shortcut on the last three: every letter this page could spare is spoken
  // for, and none of them is something anybody inserts twice a minute.
  // `chooses` is an offset and a length into the inserted text, so the word you
  // are about to replace is already selected.
  {label: '▤', title: 'Table',
   insert: '| Heading | Heading |\n| --- | --- |\n| Cell | Cell |', chooses: [2, 7]},
  {label: '—', title: 'Horizontal rule', insert: '---'},
];

// The two drawings the history buttons wear, rendered on the server: a template
// variable and not a `.replace` into finished markup, the same crossing the
// table's draft row makes with `MARK`. `innerHTML` at the one use site because
// it IS markup and nothing of anybody's reaches it — the value is the constant
// `HISTORY_MARKS` in `render.py`.
const HISTORY_ART = {{ history_art|tojson }};

// The room's undo history, once there is a room wired to this box. Declared here
// and assigned in `_COEDIT`, which is a separate `<script>` inlined AFTER this
// one and after `attachEditing` has run — so the toolbar cannot capture it at
// setup, and `typeof COEDIT` is not an option either: a `const` that has not
// been reached yet is in its temporal dead zone and `typeof` on one THROWS.
let COEDIT_HISTORY = null;

// Which undo history a press reaches. Three states, each served by the only
// thing that can serve it:
//
// 1. **No room.** The browser's own, through the surface: nothing has assigned
//    `.value`, so it is complete, and the keyboard reaches it unaided.
// 2. **A room, on the textarea.** `Y.UndoManager` over the `'typed'` origin
//    alone — the state this whole stage exists for, because there every
//    keystroke of somebody else's arrives as an assignment to `.value`.
// 3. **Ace, room or not.** Ace's own manager, taught to ignore deltas this tab
//    did not make, and the one Ace's command table binds Ctrl+Z to. The surface
//    is asked FIRST for that reason: button and key must reach one stack.
//
// Asked at the press, because a room binds seconds after the toolbar is built
// and can be lost again at any moment.
function historyOf(surface) {
  if (surface.provides.history) return surface.history;
  return COEDIT_HISTORY || surface.history;
}

// A numbered list, on any of the ways somebody has already written one —
// including an indented one. Written `^\d+\.` at first, which made this the one
// prefix in the toolbar that was blind to indentation while `LIST_ITEM` four
// lines below is not: ⌘7 over `  1. one` wrote `1.   1. one` instead of taking
// the numbers off, and a nested list is what this repository's own documents are
// made of.
const ORDERED = /^(\s*)\d+\.\s+/;

function lineRange(surface) {
  const text = surface.text();
  const {from: start, to: end} = surface.caret();
  const from = text.lastIndexOf('\n', start - 1) + 1;
  const to = text.indexOf('\n', end);
  return [from, to === -1 ? text.length : to];
}

// How much blank line is missing on each side of a block about to be written in.
//
// A block only is one if it stands apart: `---` written directly under a line of
// text is a setext heading rather than a rule, and a table cannot interrupt a
// paragraph at all — so both of the toolbar's templates and a pasted grid would
// otherwise go in and render as punctuation. One function because that is one
// rule about markdown, and the two callers would have been the same four
// conditionals twice.
function blockPadding(before, after) {
  return [
    !before ? '' : before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n',
    !after ? '' : after.startsWith('\n\n') ? '' : after.startsWith('\n') ? '\n' : '\n\n',
  ];
}

function applyMark(surface, mark) {
  const text = surface.text();
  if (mark.fence) {
    // Whole lines, and on their own lines: a fence only opens a block if nothing
    // shares its line, so wrapping a selection in place would produce three
    // paragraphs of literal backticks.
    const [from, to] = lineRange(surface);
    const chosen = text.slice(from, to);
    const fenced = /^```/.test(chosen) && /```$/.test(chosen);
    if (fenced) {
      const inner = chosen.replace(/^```[^\n]*\n?/, '').replace(/\n?```$/, '');
      surface.splice(from, to, inner);
      surface.setCaret(from, from + inner.length);
      return;
    }
    surface.splice(from, to, '```\n' + chosen + '\n```');
    // The caret lands on the language, which is the one word you type before the
    // code and cannot paste from anywhere.
    surface.setCaret(from + 3);
    return;
  }
  if (mark.prefix) {
    // Whole lines, and a toggle: pressing bullet twice is how somebody undoes a
    // bullet, and it costs one `startsWith`.
    const [from, to] = lineRange(surface);
    const lines = text.slice(from, to).split('\n');
    // Three ways a line prefix can already be on, because two of these marks are
    // not a fixed string. A check list is a bullet with a box on it, so on lines
    // that are already bullets the box goes onto the bullet that is there —
    // stacking the whole prefix wrote `- [ ] - a`, which renders as one checked
    // item whose text is a dash, and the toggle could never find its way back
    // because the line no longer started with what it was given.
    const boxed = mark.box && lines.every(line => LIST_ITEM.test(line));
    const on = mark.ordered
      ? lines.every(line => ORDERED.test(line))
      : boxed
        ? lines.every(line => LIST_ITEM.exec(line)[4])
        : lines.every(line => line.startsWith(mark.prefix));
    const next = lines
      .map((line, at) => {
        // Numbered, and not `1.` on every line. Commonmark renumbers, so both
        // render the same — but the file is the record here and people read and
        // edit it in git, where a list of five `1.`s reads as a mistake.
        //
        // The line's own indent is kept on both sides of the toggle: numbering a
        // nested list must not un-nest it, and un-numbering it must not either.
        if (mark.ordered) {
          const lead = /^\s*/.exec(line)[0];
          return on
            ? line.replace(ORDERED, '$1')
            : `${lead}${at + 1}. ${line.slice(lead.length)}`;
        }
        if (!boxed) return on ? line.slice(mark.prefix.length) : mark.prefix + line;
        const [, indent, bullet, gap, , rest] = LIST_ITEM.exec(line);
        return `${indent}${bullet}${gap}${on ? '' : '[ ] '}${rest}`;
      })
      .join('\n');
    surface.splice(from, to, next);
    surface.setCaret(from, from + next.length);
    return;
  }
  if (mark.link) {
    // `[text](url)`: two halves that differ, so it is neither a wrap nor an
    // insert. What ends up selected is what you are about to replace — the URL
    // when there are already words to link, and the words when there are not.
    const {from, to} = surface.caret();
    const chosen = text.slice(from, to);
    // A bracket inside the label ends the label. `[a]b]` selected and linked
    // wrote `[a]b](url)`, which the committed renderer draws as literal text
    // with no link in it and no sign that anything failed. Escaped rather than
    // dropped, for the same reason `pastedAs` escapes a cell's own pipe — and
    // the caret arithmetic below counts the escaped label, not the raw one.
    //
    // The backslash is escaped with them, because an escaper that escapes the
    // metacharacter and not the escape character reproduces the bug it closes
    // one character over: `a\]b` became `[a\\]b](url)`, in which the `\\` is a
    // literal backslash and the `]` is the one that ends the label again.
    const label = (chosen || 'text').replace(/([\\[\]])/g, '\\$1');
    surface.splice(from, to, `[${label}](url)`);
    const at = from + 1;
    if (chosen) surface.setCaret(at + label.length + 2, at + label.length + 5);
    else surface.setCaret(at, at + label.length);
    return;
  }
  if (mark.insert) {
    // A fourth shape, because a table and a rule are neither a wrap nor a prefix
    // nor a fence: they are blocks that replace nothing, and they land after the
    // line the caret is on rather than inside it.
    const [, to] = lineRange(surface);
    const [lead, tail] = blockPadding(text.slice(0, to), text.slice(to));
    surface.splice(to, to, lead + mark.insert + tail);
    const at = to + lead.length;
    const [start, width] = mark.chooses || [mark.insert.length, 0];
    surface.setCaret(at + start, at + start + width);
    return;
  }
  // The tail is the WRAP shape, and it is reached only by a mark that is one.
  //
  // It used to be the fall-through — "anything I do not recognise is a wrap" —
  // and `FORMATS` now holds a fifth shape that is not: the image button writes no
  // markdown at all, it opens a file picker, and reaching here with it read
  // `undefined.length` and threw inside a click handler, which is a button that
  // does nothing and a console nobody has open. A guard naming that one entry was
  // written first and is the wrong shape of fix: it closes the case that exists
  // and leaves the trap set for the sixth. So the last branch asks whether it is
  // the one it can do, and a mark it cannot do is refused out loud — which is the
  // rule this application has broken three times by returning in silence.
  if (typeof mark.wrap !== 'string') {
    announce(`${mark.title} writes nothing into the document`);
    return;
  }
  const {from, to} = surface.caret();
  const chosen = text.slice(from, to);
  const width = mark.wrap.length;
  const wrapped =
    text.slice(from - width, from) === mark.wrap &&
    text.slice(to, to + width) === mark.wrap;
  if (wrapped) {
    // Already marked: unwrap, taking the marks with it rather than leaving a
    // stray pair behind for somebody to delete by hand.
    surface.splice(from - width, to + width, chosen);
    surface.setCaret(from - width, to + width - 2 * width);
    return;
  }
  surface.splice(from, to, mark.wrap + chosen + mark.wrap);
  // An empty selection leaves the caret between the marks, ready to type. A
  // selection stays selected, so a second press undoes it.
  if (chosen) surface.setCaret(from + width, to + width);
  else surface.setCaret(from + width);
}

const LIST_ITEM = /^(\s*)([-*+]|\d+\.)(\s+)(\[[ xX]\]\s+)?(.*)$/;

// --- what this browser remembers about the editor ---------------------------
//
// One key, one JSON object, and the version in the key: `{mode, indent,
// autosave}`, on the precedent of `openproj:widths:4`. One object rather than
// three keys because a preference that grows a fourth field grows a fourth key
// otherwise, and nothing then forgets the third when the shape changes.
//
// **There is no earlier spelling to forget**, and that is worth stating rather
// than leaving as an absence: this key is new in this commit, so the `forget`
// that every other bumped key here carries would be forgetting something that
// was never written. The version is in the name so the NEXT shape is
// `openproj:editor:2` and forgets this one out loud, the way the draft key's
// bump already does.
//
// Through `remembered` and never a bare `localStorage`, which throws on the
// property itself in a private window, behind a blocked cookie or under an
// enterprise policy — `remembered.map` answers `{}` there and the defaults below
// are the answer. That is the right way round for a preference about controls
// that have to exist before it can be read.
//
// And every value is checked against what the control actually offers rather
// than trusted. `{"indent": "four"}` is one hand-edit away, and it would reach
// `' '.repeat("four")` in the one script every `_COMBOBOX` page shares.
const EDITOR_KEY = 'openproj:editor:1';
// What the indent picker offers. Two first, because that is what the plan is
// already written at: 48 of the 56 nested bullets in it are indented by two.
const INDENT_WIDTHS = [2, 4, 8];
// How often a draft may be written, in seconds — and the coarsest offer is not a
// taste. The room commits a document everybody has stopped typing in after
// `QUIET_SECONDS` (20, in `coedit.py`), and that window is what backstops a
// draft this browser is holding. An interval coarser than it would let somebody
// set their own floor below the thing that catches them.
const DRAFT_SECONDS = [1, 2, 5, 10, 20];
// How lopsided the split view may be remembered as being: the writing box over
// the preview, which is what `--split` is in `fr`. Every other value here is one
// of a list and `one()` checks it; this is a ratio, so it gets its own guard and
// the guard has to be its own kind of strict. `{"split": "wide"}` is one
// hand-edit away and it would reach `minmax(0, wide)`, which is not a track size
// — the whole `grid-template-columns` declaration is then invalid at computed
// value time and the three tracks lay out as three auto columns, which is the
// split view with its panes in the wrong places rather than a value quietly
// ignored. And a bound as well as a number, because a ratio dragged out on a
// wide monitor and restored on a laptop is a pane at a few pixels: `applySplit`
// clamps to what fits on the screen it is actually on, and this is the outer
// fence around what may be stored at all.
//
// **The same fence bounds the writing**, in `splitBound` beside the clamp, and it
// did not at first: a drag on a 3440px screen stored 11.57 and this line then
// threw it away on the very next load. A number a control can produce and its own
// guard refuses is a preference that vanishes for exactly the people with the
// biggest monitors.
const SPLIT_RANGE = 8;
// The two surfaces, spelled the way the query string spells them, because these
// are the same two strings the server reads — one vocabulary and not two.
// `ace` first now, because it is the one a page carries when nobody said
// anything — jcanton, 2026-08-20, on that becoming the default: "I think it's
// worth it".
const EDITORS = ['ace', 'plain'];
// `textarea` was this branch's own name for the plain box, in the address and in
// the preference alike, and it is accepted on the way in for exactly one reason:
// a stored `textarea` is somebody who OPTED OUT, and the fallback below is now
// `ace`. Reading an old opt-out as "nothing was said" would hand 594 KB to the
// one person who had asked not to have it. It is never written back — a value
// read here is rewritten as `plain` by the first `rememberEditor` — so this list
// shrinks by itself rather than being a second spelling to keep alive.
const EDITORS_WERE = {textarea: 'plain'};
// And the keymaps the second one offers. A textarea has one and it is the
// browser's, which is why this list is read only where Ace is.
const KEYMAPS = ['default', 'vim'];
const EDITOR = (() => {
  const held = remembered.map(EDITOR_KEY);
  const one = (value, offered, fallback) => offered.includes(value) ? value : fallback;
  // **The URL wins over the preference, and it has to.** This is the one setting
  // on the page that decides which BYTES the server rendered, and the server
  // cannot read `localStorage`. So the address is what put this surface in the
  // page and is therefore what says whether it is here; the remembered value is
  // only how a person who chose gets that choice again tomorrow without typing
  // it. A remembered value the page was not rendered for is a preference for
  // something that is not here — which `bodySurface` deals with out loud rather
  // than quietly ignoring.
  const named = value => one(EDITORS_WERE[value] ?? value, EDITORS, null);
  const chose = named(new URLSearchParams(location.search).get('editor'));
  const kept = named(held.editor);
  return {
    // `edit` and not null. null means "editing, but not in one of the three
    // views", which is the state a page opened for the first time was left in:
    // the surface came up in a shape none of the three segments was pressed for,
    // and clicking one of them made it jump. jcanton, 2026-08-21: "entering edit
    // mode the first time opened the editor without having selected one of the
    // three... can you select edit as default mode?"
    //
    // It is still a remembered preference — the segments write it — so this is
    // only what somebody who has never pressed one of them gets.
    //
    // Only the two session modes. `view` stopped being a session shape when
    // the landing state took its name: the same stored word meant "open
    // sessions in preview-only" yesterday and "the sessionless read page"
    // today, and a preference that changes meaning under a stored value is a
    // trap. A legacy `view` reads as `edit` — the nearest session — and is
    // rewritten the first time anything remembers.
    mode: one(held.mode === 'view' ? 'edit' : held.mode, ['edit', 'both'], 'edit'),
    indent: one(held.indent, INDENT_WIDTHS, 2),
    autosave: one(held.autosave, DRAFT_SECONDS, 2),
    // Added to this key rather than bumping it to `openproj:editor:2`. A bump
    // says "the SHAPE changed and the old value cannot be read"; every field
    // here is read one at a time against its own fallback, so a stored map from
    // before this commit simply has no `split` and gets the default. Bumping
    // would throw away four settings people have chosen to introduce a fifth
    // that costs nothing to be absent.
    //
    // `Number.isFinite` and not a `>` chain: it rejects `null`, `"2"` and `NaN`
    // by itself, and a string is exactly what a hand-edited entry is.
    split: Number.isFinite(held.split) && held.split >= 1 / SPLIT_RANGE
           && held.split <= SPLIT_RANGE ? held.split : 1,
    editor: chose ?? kept ?? 'ace',
    // Whether anybody actually said so, as against this being the default — and
    // it is a separate fact because the default must not announce its own
    // absence. `bodySurface` says "this page does not carry the second editor"
    // when a choice cannot be honoured, and with `ace` as the fallback every
    // signed-out reader on every detail page would now be told that about a
    // library they never asked for.
    chosen: (chose ?? kept) !== null,
    keymap: one(held.keymap, KEYMAPS, 'default'),
  };
})();

// What is written down, named rather than "whatever is on the object": the
// object also carries things that are true of this load and not of this browser,
// and a preference store that quietly grows a field is one nothing forgets.
const EDITOR_KEPT = ['mode', 'indent', 'autosave', 'keymap', 'split'];

function rememberEditor(change) {
  Object.assign(EDITOR, change);
  const kept = Object.fromEntries(EDITOR_KEPT.map(k => [k, EDITOR[k]]));
  // The surface is written down only when somebody CHOSE it, which is why it is
  // not in the list above. `ace` is the default now, so a page that merely
  // resolved that default and then stored it would make every later load look
  // like a decision — and `chosen` is what decides whether a page that cannot
  // honour a decision says so out loud. Without this, choosing the split view
  // once (`rememberEditor({mode})`) would have signed a reader up to be told, on
  // every record afterwards, that a library they never asked for is missing.
  if (EDITOR.chosen) kept.editor = EDITOR.editor;
  remembered.set(EDITOR_KEY, JSON.stringify(kept));
}

// Typing the parameter is choosing, and choosing is what makes it stick — in
// both directions now, because `?editor=plain` is a choice as much as
// `?editor=ace` is and the way back out of either has to be the other one. A
// setting whose only way out is editing `localStorage` by hand is a trap, and
// with the default on the expensive side it would be the expensive trap.
if (new URLSearchParams(location.search).has('editor')) rememberEditor({});

// And the other half of sticky: the preference put back into the URL, because
// the URL is the only part of this the server can see. Called from
// `bodySurface` and nowhere else, so the table and the cycle page — which share
// this block and have no body editor — never navigate.
//
// Only over http(s). A static export IS the case where the parameter can never
// work: there is no server to render the other bytes, so reloading a file to add
// a parameter to it costs a reload and buys nothing. Returns whether the page is
// going away, so the caller can tell "fetching it" from "it is not obtainable".
function stickyEditor() {
  if (!location.protocol.startsWith('http')) return false;
  const url = new URL(location.href);
  if (url.searchParams.has('editor')) return false;
  url.searchParams.set('editor', EDITOR.editor);
  // `replace` and not `assign`: a preference carried forward is not a place in
  // the history somebody wants the back button to take them to. It matters more
  // now than it did — with the default on the other side, this fires for the
  // people who chose the plain box, on every record they open, and `assign`
  // would put a bounce in the back button for each one of them.
  location.replace(url);
  return true;
}
// Spaces, because a tab character is two columns here, four in git's diff view
// and eight in a terminal, and the place these documents are read that this tool
// does not draw is GitHub.
//
// It is a TYPING setting and never a "convert this document" command. A global
// re-indent reaches the room as one delete-everything-insert-everything, which
// `tests/test_coedit.py` already measures as larger than a body is allowed to
// be — so the whole document is never re-indented here, and the picker that
// makes the width settable changes what the next Tab types and not one character
// of what is already written.
//
// `let`, because the picker moves it. `OUTDENT` is derived from the same number
// in the same call rather than written down a second time: one tab, or up to as
// many spaces as an indent puts in, and two constants that are the same number
// are the same defect.
let INDENT;
let OUTDENT;

function setIndentWidth(width) {
  INDENT = ' '.repeat(width);
  OUTDENT = new RegExp('^(?:\\t| {1,' + width + '})');
}
setIndentWidth(EDITOR.indent);

// Tab indents what the selection touches, and Shift-Tab takes it back.
//
// Every write goes through `replaceRange`, so the whole gesture is one undo step
// and the native history survives it — including the outdent, which deletes
// through `execCommand('insertText', false, '')` exactly as the empty-list-item
// branch below already does.
function indentLines(surface, out) {
  const text = surface.text();
  const {from: start, to: end} = surface.caret();
  const [from, to] = lineRange(surface);
  const chosen = text.slice(from, to);
  const item = LIST_ITEM.exec(chosen);
  const head = text.slice(from, start);
  // Whole lines when there is a selection, when the caret is in the indent, and
  // when it is anywhere inside a bullet's marker — which is the gesture that
  // nests a list item under the one above it, and the reason `LIST_ITEM` is
  // consulted here rather than a plain `^\s*`. A caret in the middle of a
  // sentence means the other thing: type spaces to the next stop, the way a tab
  // key does on a line of prose.
  const lead = item ? item[1].length + item[2].length + item[3].length : 0;
  const whole = out || start !== end || /^\s*$/.test(head) || (item && head.length <= lead);
  if (!whole) {
    surface.splice(start, end, ' '.repeat(INDENT.length - ((start - from) % INDENT.length)));
    return;
  }
  const lines = chosen.split('\n');
  const moves = [];
  const next = lines
    .map(line => {
      if (!out) { moves.push(INDENT.length); return INDENT + line; }
      const cut = OUTDENT.exec(line);
      moves.push(cut ? -cut[0].length : 0);
      return cut ? line.slice(cut[0].length) : line;
    })
    .join('\n');
  // Nothing to take away. Without this, Shift-Tab on a line with no indent still
  // wrote the line back over itself and cost somebody an undo press to find out
  // that nothing had happened.
  if (next === chosen) return;
  surface.splice(from, to, next);
  // The caret ends where the text it was on ended up, not at the end of what was
  // rewritten: an indent moves the line under you and leaves you on the word you
  // were typing. Clamped to the start of its own line, for a caret that was
  // sitting inside indentation an outdent has just removed.
  const carried = at => {
    let opens = from;
    let before = 0;
    for (let i = 0; i < lines.length; i++) {
      const ends = opens + lines[i].length;
      if (at <= ends) return Math.max(opens + before, at + before + moves[i]);
      opens = ends + 1;
      before += moves[i];
    }
    return at + before;
  };
  surface.setCaret(carried(start), carried(end));
}

// The mirror. One of them, and every pixel question about a textarea is asked of
// it: where each logical line starts, and where a caret at a given index is
// drawn. There were two — this one and `_COEDIT`'s `ghost`, built the same way
// for the seat bands and carrying the width bug below — and two mirrors is two
// places for the same answer to be wrong in.
//
// A textarea has no DOM inside it, so there is no range to measure and no other
// way to ask any of this: the answer comes from a mirror that is given the box's
// own metrics and one block per logical line, and `offsetTop` then reads a
// position straight off. Measured rather than assumed — `scrollTop / lineHeight`
// is only right for a document in which nothing wraps, and in a pane half a
// window wide most lines wrap.
//
// **The width is the fractional content box, and that is the whole of the
// accuracy.** The seat mirror this replaces set `ghost.style.width =
// BODY.clientWidth + 'px'` on a `border-box` element it had also handed the
// textarea's padding and border to — so it took the padding box for a border box
// and came out a whole border narrower than the real content box, on top of
// `clientWidth` being an integer where the content box is fractional. At a width
// sitting on a wrap boundary that flips one break, and every line below it lands
// a whole line height out, up to three: 1.7% to 10.4% of widths across six
// corpora and 481 widths each, against 0 of 481 with this. `VENDOR.md` holds
// this feature to "a caret one line off is worse than no caret".
//
// `ask` is handed the mirror rather than the mirror handed back, so the thing
// cannot outlive the question: an off-screen copy of the document left in the
// page is one that goes stale and one a later `querySelector` finds.
//
// **Every top this answers is in the box's own SCROLL space** — zero is the top
// of the padding box, which is what `scrollTop` counts from, so a consumer that
// has already subtracted `scrollTop` is done. Anything drawn OVER the box is
// positioned from its BORDER box instead and has one more term to add; that is
// `textTop` below, and it is a whole border-width, which is why every line
// number was a pixel above the line it numbered before it existed.
//
// `ask` is handed a `topOf` rather than being left to read `offsetTop`, and that
// is the second half of the accuracy. `offsetTop` is an integer while a row here
// is 20.15625px tall, so it rounds — and the rounding accumulates down the
// document, up to half a row by the foot of a long one. A rect is fractional.
function measuredLines(area, text, ask) {
  const style = getComputedStyle(area);
  const mirror = document.createElement('div');
  mirror.setAttribute('aria-hidden', 'true');
  for (const name of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
                      'letterSpacing', 'padding', 'border', 'whiteSpace',
                      'wordBreak', 'overflowWrap', 'tabSize']) {
    mirror.style[name] = style[name];
  }
  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.top = mirror.style.left = '-9999px';
  mirror.style.boxSizing = 'border-box';
  // The scrollbar is the browser's own furniture and is an integer; everything
  // else in this sum is fractional and is kept so.
  const bars = area.offsetWidth - area.clientWidth
    - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
  mirror.style.width = (area.getBoundingClientRect().width - bars) + 'px';
  // One block per logical line, so a line that wraps is one box however many
  // rows it draws on — which is what "line 17" means in the gutter of the editor
  // this is modelled on, and what `data-startline` counts on the other side.
  // A zero-width space on an empty line, or the box has no height at all.
  //
  // The text is handed in rather than read off the box, and that is the boundary
  // above showing through: the mirror is about GEOMETRY — a font, a width, a
  // wrap — and the document it lays out belongs to the surface. Reading
  // the box's own value here would be a second place that knows this is a
  // textarea.
  const lines = text.split('\n');
  mirror.append(...lines.map(line => {
    const row = document.createElement('div');
    row.textContent = line || '\u200b';
    return row;
  }));
  document.body.append(mirror);
  // The mirror's own border box, plus its border, is the origin the box's
  // `scrollTop` counts from — so a row's distance from it is the number a
  // consumer can subtract `scrollTop` from directly.
  const zero = mirror.getBoundingClientRect().top + parseFloat(style.borderTopWidth);
  const topOf = element => element.getBoundingClientRect().top - zero;
  try {
    return ask([...mirror.children], lines, topOf);
  } finally {
    mirror.remove();
  }
}

// Where every logical line of a textarea starts, in the box's own scroll space.
function lineTops(area, text) {
  return measuredLines(area, text, (rows, lines, topOf) => rows.map(topOf));
}

// And where the top of the box's first row of text is drawn, in the coordinates
// of a layer that fills `host` — the gutter's column and the seat layer are both
// absolutely positioned inside `.bodywrap`, whose top is the box's BORDER box,
// while `lineTops` and `rowTops` answer from its padding box.
//
// One border-width apart, which sounds like nothing and is not: measured in
// Chrome against an independent overlay, every line number came out exactly
// 1.000px above the line it numbered, on every line, in a column of numbers
// whose whole job is to line up with something.
function textTop(area, host) {
  return area.getBoundingClientRect().top - host.getBoundingClientRect().top
    + (parseFloat(getComputedStyle(area).borderTopWidth) || 0);
}

// And where the carets at these indexes are drawn — the top of the visual ROW
// each one sits on, which is not the top of its logical line the moment that line
// wraps. A band on the first row of a paragraph somebody is typing the fourth row
// of is a band pointing at the wrong sentence.
//
// Every index in one pass over one mirror, because the loop this replaces built a
// mirror, filled it with a prefix of the whole document and laid it out once PER
// PERSON in the room — the only item in this plan that makes something already
// shipped cheaper.
function rowTops(area, text, indexes) {
  return measuredLines(area, text, (rows, lines, topOf) => {
    const mark = document.createElement('span');
    // A zero-width space, so the marker has a box on an empty line and so the
    // line it is on does not come out one character wider than the real one.
    mark.textContent = '\u200b';
    return indexes.map(index => {
      let line = 0;
      let opens = 0;
      // The line the index is IN, so an index at the very end of a line stays on
      // that line rather than jumping to the top of the next one.
      while (line < lines.length - 1 && index > opens + lines[line].length) {
        opens += lines[line].length + 1;
        line++;
      }
      const row = rows[line];
      row.textContent = lines[line].slice(0, Math.max(0, index - opens));
      row.append(mark);
      const top = topOf(mark);
      // Put the line back, or the second index measured is measured against a
      // document the first one truncated.
      row.textContent = lines[line] || '\u200b';
      return top;
    });
  });
}

// Ask 4: the numbers down the side of the box.
//
// LOGICAL lines, one number each, aligned to the first visual row of the line it
// numbers — which is what the note this is modelled on does, and what makes the
// number mean the same thing as the line number in a diff, a stack trace or a
// review comment. A count of visual rows would be a number that changes when you
// drag the width handle.
//
// The ceiling exists because the rebuild is a layout of the whole document and
// it happens on every keystroke. Measured in Chrome, mirror and numbers
// together: 0.8ms at 100 lines, 2.6 at 400, 6.5 at 1,000, 8 at 1,200, 15.6 at
// 2,000 and 25.3 at 4,000. A 60Hz frame is 16.7ms, so 2,000 already spends one
// on a fast machine and the ceiling is set at half of one instead — the longest
// document in this repository's own corpus is 124 lines, so a thousand is eight
// times anything anybody has written here and still leaves room for a machine
// three times slower than this one.
//
// Above it the gutter goes off and SAYS SO, in the bar above the box, with the
// count it went off for. This application has shipped three branches that
// decided not to act and said nothing about it, and a gutter that silently
// vanishes on a long document is the one somebody reports as "the line numbers
// are broken".
const GUTTER_MAX = 1000;

function attachGutter(surface, note) {
  // A surface that draws its own numbers is left to draw them. Not silence: the
  // numbers are there, drawn by the thing that owns the rows, and a second
  // column of them measured through a mirror of a box that is not on screen
  // would be the wrong numbers beside the right ones.
  if (surface.provides.gutter) return null;
  // The box, for the questions that are about a box: does it have a layout, how
  // far is it scrolled, which wrapper is it in. The DOCUMENT comes off the
  // surface, and so do the two measurements, which is why the mirror is not
  // reached for by name here any more.
  const area = surface.el;
  const wrap = area.closest('.bodywrap');
  if (!wrap) return;
  const gutter = document.createElement('div');
  gutter.className = 'gutter';
  // Furniture, and out of the accessibility tree: a screen reader reading four
  // hundred numbers before the document is worse than no gutter at all.
  gutter.setAttribute('aria-hidden', 'true');
  const rows = document.createElement('div');
  rows.className = 'gutterrows';
  gutter.append(rows);
  // After the box and not before it, which decides which one is painted on top:
  // both are positioned, so document order is the tie-break, and a gutter drawn
  // under the textarea is a gutter behind an opaque background.
  wrap.append(gutter);

  // The numbers move with the box, and that is a transform on one element rather
  // than a rebuild: scrolling changes where the lines are drawn and not where
  // they are. `textTop` is the border the column is anchored outside of and the
  // measurements are taken inside of; without it every number is one pixel high.
  const slide = () => {
    rows.style.transform =
      'translateY(' + (textTop(area, wrap) - area.scrollTop) + 'px)';
  };

  // Named for what it draws, and not `draw`. This block ships wherever
  // `_COMBOBOX` does — the table and the cycle page have no body editor at
  // all — and the table declares a top-level `draw` of its own — so a generic
  // name here is a name that reads as the
  // table's to anything looking at the page as text. It is nested and therefore
  // lexically safe, and the suite went red anyway: the test that greps out the
  // table's sort routine by name matched this one first, because it comes
  // earlier in the document. The same collision, arriving through the one door
  // that was open.
  let off = false;
  // The column that is currently applied, or `null` for none. Kept because
  // changing it changes where every line WRAPS — see the dispatch at the foot of
  // this function — and a change has to be told from a redraw at the same width.
  let column = null;
  function drawGutter() {
    // The same question `place` asks, and for the same reason: a box nothing is
    // drawing measures zero, and a mirror given a width of zero wraps the
    // document one character per row. Read mode is exactly that, and
    // `openproj:editing` is what brings the gutter back.
    if (!area.getClientRects().length) return;
    const count = surface.text().split('\n').length;
    if (count > GUTTER_MAX) {
      wrap.classList.remove('numbered');
      rows.replaceChildren();
      const said = 'Line numbers are off above ' + GUTTER_MAX.toLocaleString()
        + ' lines — this document has ' + count.toLocaleString() + '.';
      if (note) note.textContent = said;
      // Both channels, and each is doing a different job. The label beside the
      // box is the one that persists, and it is the one being relied on — but it
      // lives in `.bodybar`, which is `display: none` until the article is
      // editing, and a live region that is not displayed when its text is set is
      // one a screen reader may never read out. `announce` is the page's single
      // place for "something was refused and here is why" and it is always on the
      // page. Said once per crossing, not once per keystroke: a live region that
      // repeats itself on every input is one people turn off.
      if (!off) announce(said);
      off = true;
      moved(null);
      return;
    }
    if (note) note.textContent = '';
    off = false;
    // The column's width first, then the measurement: the width is the box's
    // left padding, the padding decides the content box, and the content box
    // decides where every line wraps. Measured before it is applied, the mirror
    // answers about a box one gutter wider than the one on the screen.
    const want = 'calc(' + String(count).length + 'ch + 1.1rem)';
    wrap.style.setProperty('--gutter', want);
    wrap.classList.add('numbered');
    rows.replaceChildren(...surface.lineCoords().map((top, at) => {
      const number = document.createElement('span');
      number.className = 'lineno';
      number.style.top = top + 'px';
      number.textContent = String(at + 1);
      return number;
    }));
    slide();
    moved(want);
  }

  // This column is the box's own `padding-left`, so switching it on — or growing
  // it from two digits to three, or taking it away again at the ceiling — narrows
  // or widens the content box and rewraps every line in the document. Anything
  // else drawn over the box is then on the wrong line, which is the exact defect
  // this stage exists to remove, arriving through the stage's own new feature:
  // measured in Chrome, turning the gutter on left the band for a caret below a
  // wrapping paragraph one whole 20.15px row above where it belonged.
  //
  // So the gutter says so, through the event every layer over this box already
  // listens to. Only on a real change, which is what stops it being a loop: this
  // function is one of the listeners, and the redraw a dispatch causes writes the
  // same column and dispatches nothing.
  function moved(now) {
    if (now === column) return;
    column = now;
    dispatchEvent(new Event('openproj:editing'));
  }

  // Coalesced, because one resize is a burst of events and each of these is a
  // layout of the whole document. A frame AND a timer, whichever arrives first:
  // `requestAnimationFrame` is the right clock for something about to be
  // painted, and it is also a clock that does not tick in a tab nobody is
  // looking at — the finding `announce` records — nor under the headless virtual
  // clock every pixel question in this repository is asked through, which would
  // make the gutter the one drawing here that no test can see.
  let frame = 0;
  let backstop = 0;
  function now() {
    cancelAnimationFrame(frame);
    clearTimeout(backstop);
    backstop = 0;
    drawGutter();
  }
  function later() {
    if (backstop) return;
    frame = requestAnimationFrame(now);
    backstop = setTimeout(now, 32);
  }

  area.addEventListener('scroll', slide);
  surface.onInput(later);
  addEventListener('resize', later);
  // Every view change, and the one that turns editing on: the box arrives, or
  // changes width by half a window, and the numbers are a function of its width.
  addEventListener('openproj:editing', later);
  // And the box changing shape without any of those, which is three things at
  // once: the width grip writes `--measure` and calls `place()` and dispatches
  // nothing; this column IS the box's left padding, so turning it on narrows the
  // content box and rewraps every line under it; and the box carries a
  // `resize: vertical` handle of its own. All three are the CONTENT box
  // changing, which is what a `ResizeObserver` observes by default, so one
  // observer answers all three rather than three events being remembered
  // separately. Measured before this: dragging the grip to 30rem left six of
  // nine numbers between 20.8 and 122.1px off their lines until the window was
  // resized. The redraw this observer causes can itself change the column's
  // width, which fires the observer once more and then settles, because the
  // second pass writes the same `--gutter` and changes no size.
  if (typeof ResizeObserver === 'function') new ResizeObserver(later).observe(area);
  // A mirror in a fallback face measures the fallback's line height, and every
  // number then lands on the wrong row on the one machine whose webfont has not
  // arrived yet.
  if (document.fonts) document.fonts.ready.then(later);
  drawGutter();
}

// Ask 5's control, and the two facts either side of it.
//
// The shape is read off the note in `docs/hackmd-observed.md` rather than
// invented: a strip along the FOOT of the box, holding `Line 1, Columns 1 — 100
// Lines`, `Spaces: 4` and `Length: 1369`. The thing worth copying is what
// `Spaces: 4` IS — two words that state the current value and are themselves the
// click target. No dialog, no settings screen, no "preferences" anywhere: the
// value is legible without opening anything and one press changes it.
//
// What is deliberately not built from that strip, so it is not rediscovered as
// an omission: `Breaks` is a SERVER setting here — `_MD` is `MarkdownIt(
// "commonmark", ...)` and CommonMark makes a single newline a space — and
// flipping it would reflow every document already in the plan repository without
// changing a character of any of them. It is a stated unknown in the plan
// pending a grep of the migrated corpus, not a switch. Spellcheck and an editor
// theme are the other two, and both are refused rather than postponed: the
// browser's own spellcheck already works in this box, and a pane that themes
// itself independently of the page is a colour with its only definition inside a
// block half the readers never match.
//
// The bar is built rather than written into the template, for the same reason
// the toolbar is: one block builds the strip wherever the markup mounts it, so
// the row of spans has one author and no hand-written copy to fall behind. A page that wants
// something of its own in the middle of the strip — the draft interval, on the
// one page that has a draft — puts it in the markup and this wraps it, which is
// why the two ends are `prepend` and `append` rather than `replaceChildren`.
const MAX_BODY = {{ max_body_bytes|tojson }};

// A status-bar picker. `label: value`, cycling on click, announced when it
// moves — because the only thing on screen that changed is two characters in an
// 11px strip, which is not a change a person who pressed a button can see.
function statusPick(button, label, offered, chosen, chose) {
  const draw = () => {
    button.textContent = `${label}: ${chosen}`;
    // What pressing it will do, in the words of what it will become. A picker
    // that says only what it IS leaves a person to press it to find out.
    const next = offered[(offered.indexOf(chosen) + 1) % offered.length];
    button.title = `${label}: ${chosen} — press for ${next}`;
  };
  button.type = 'button';
  button.classList.add('stat', 'pick');
  button.onclick = () => {
    chosen = offered[(offered.indexOf(chosen) + 1) % offered.length];
    draw();
    chose(chosen);
  };
  draw();
  return button;
}

function attachStatus(surface, bar) {
  if (!bar) return null;
  const where = document.createElement('span');
  where.className = 'stat';
  const spaces = statusPick(
    document.createElement('button'), 'Spaces', INDENT_WIDTHS, EDITOR.indent,
    width => {
      setIndentWidth(width);
      rememberEditor({indent: width});
      // In the words of what it is and what it is not. A person who has just
      // pressed something called "Spaces" on a document full of tabs is entitled
      // to think the document changed, and it did not: re-indenting a whole
      // document reaches a live room as one delete-everything-insert-everything,
      // which is measurably larger than a body is allowed to be.
      announce(`Tab now types ${width} spaces. Nothing already written was changed.`);
    });
  const size = document.createElement('span');
  size.className = 'stat';
  bar.prepend(where, spaces);
  bar.append(size);

  // Ask 6, where the note this is modelled on puts it: a keymap glyph in the
  // strip along the foot of the box, beside the indent width and the length.
  //
  // Only on a surface that HAS keymaps, and that is an absence rather than a
  // silence: a `<textarea>`'s keymap is the browser's, there is no second one to
  // offer, and a picker offering a choice it cannot make is worse than no
  // picker. What that used to cost was that the second editor was reachable only
  // by typing a parameter nothing on the page mentioned; it is the switch beside
  // the three view segments now, so the way to a keymap is on the page as well.
  if (surface.setKeymap) {
    bar.append(statusPick(
      document.createElement('button'), 'Keymap', surface.keymaps, EDITOR.keymap,
      // Nothing announced. The sentence that was here explained what vim mode
      // takes — Escape, Tab, every printable key in NORMAL mode — to somebody who
      // had just switched to vim mode on purpose. jcanton, 2026-08-21: "we don't
      // need [it], can be completely removed". The control itself says which
      // keymap is on.
      name => {
        surface.setKeymap(name);
        rememberEditor({keymap: name});
      }));
  }

  const bytes = new TextEncoder();
  // Said once per crossing rather than once per keystroke, the way the gutter's
  // ceiling is: a live region that repeats itself on every character is one
  // people turn off.
  let wasOver = false;

  function refresh() {
    const text = surface.text();
    const {from: at, to: ends} = surface.caret();
    // Counted rather than split: `text.slice(0, at).split('\n')` allocates every
    // line above the caret, and this runs on every keystroke of a document that
    // may be four hundred lines long.
    let line = 1;
    for (let i = text.indexOf('\n'); i !== -1 && i < at; i = text.indexOf('\n', i + 1)) line++;
    const opens = text.lastIndexOf('\n', at - 1) + 1;
    // Code points and not code units, and only over the current line so the cost
    // is the line rather than the document: a caret after an emoji is in column
    // 2, and reporting 3 is the same class of wrongness as a splice that cuts a
    // surrogate pair in half.
    const column = [...text.slice(opens, at)].length + 1;
    const lines = text.split('\n').length;
    const chosen = ends - at;
    // Singular at one, which is a departure from the shot and a deliberate one.
    // HackMD's own strip reads `Line 1, Columns 1 — 100 Lines` — plural on the
    // column whatever the number — and this bar already spells `Column` singular
    // because copying a typo is not what "build the toolbar in the screenshot"
    // asked for. Having done that once, `1 Lines` is the same mistake left in:
    // an empty document is the FIRST thing anybody sees on /new, and it opened
    // reading `Line 1, Column 1 — 1 Lines`.
    where.textContent = `Line ${line}, Column ${column}`
      + (chosen ? ` — ${chosen.toLocaleString()} selected` : '')
      + ` — ${lines.toLocaleString()} Line${lines === 1 ? '' : 's'}`;

    // The count is UTF-16 code units, which is what the editor this is modelled
    // on counts too, and it is NOT what the ceiling is in. The ceiling is UTF-8
    // bytes, so the two are said separately rather than one being passed off as
    // the other — and the byte figure appears only when the document is close
    // enough to the ceiling for it to be news.
    //
    // Encoded only when it could possibly be over: UTF-8 is at most three bytes
    // per UTF-16 code unit, so a shorter document cannot be, and this is a scan
    // of the whole body on every keystroke.
    const near = text.length * 3 >= MAX_BODY * 0.9 ? bytes.encode(text).length : 0;
    const over = near > MAX_BODY;
    size.textContent = `Length: ${text.length.toLocaleString()}`
      + (near >= MAX_BODY * 0.9
         ? ` — ${near.toLocaleString()} of ${MAX_BODY.toLocaleString()} bytes`
         : '')
      + (over ? ', too long to save' : '');
    size.classList.toggle('over', over);
    // Before Save is pressed and not after it. The server answers a body over
    // this with a refusal, which is correct and is also the worst moment to find
    // out: the writing is done, the tab is about to be closed, and the only copy
    // is in a box.
    if (over && !wasOver) {
      announce(`This document is ${near.toLocaleString()} bytes and cannot be saved above `
               + `${MAX_BODY.toLocaleString()}.`);
    }
    wasOver = over;
  }

  // The same events the seat layer's `sit` uses, for the same reason: a caret
  // moves on a keystroke, on a click and on a selection, and none of those is an
  // `input`. `openproj:editing` is the box arriving, changing width, or being
  // written into by somebody else in the room — all three change what this says
  // and none of them fires anything else here.
  // Exactly the five events this used to name one at a time: the surface's
  // `onCaret` IS that list, and it is one list now rather than two copies of it
  // in two functions that both wanted "the caret may have moved".
  surface.onCaret(refresh);
  addEventListener('openproj:editing', refresh);
  refresh();
  return {refresh};
}

function attachEditing(surface, bar) {
  const area = surface.el;
  // The two history buttons, so their disabled state can be kept honest. Empty
  // on a bar that was never drawn, which is what makes `syncHistory` a no-op on
  // the table and the cycle page, which inline this block and have no editor. Named rather than
  // called `history`, which is a global this page has no business shadowing.
  const historyButtons = [];
  if (bar) {
    for (const mark of FORMATS) {
      if (mark.group) {
        // A rule and not a gap. Three groups of adjacent buttons say "these do
        // the same kind of thing" only if the boundary is visible; spacing
        // alone reads as a toolbar that wrapped.
        const rule = document.createElement('span');
        rule.className = 'sep';
        rule.setAttribute('aria-hidden', 'true');
        bar.append(rule);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'mark';
      button.textContent = mark.label;
      button.title = mark.title;
      if (mark.style) button.setAttribute('style', mark.style);
      // mousedown, not click: click runs after the textarea has lost focus and
      // with it the selection the mark is supposed to apply to.
      //
      // The image button is the exception and has to be a click: a file picker
      // opens only on a real user gesture, and `preventDefault` on mousedown
      // takes the activation away from the `.click()` that opens it. It has no
      // selection to protect, so nothing is lost by waiting.
      //
      // Three shapes, then: history, which moves a stack; the upload, which
      // opens a dialog; and a mark, which writes markdown.
      if (mark.history) {
        // A drawing and no letters, so the name is said twice: `aria-label` for
        // a reader who cannot see it, `title` for one who can and cannot tell
        // what it is. The draft row's check and cross do the same.
        button.classList.add('hist');
        button.innerHTML = HISTORY_ART[mark.history];
        button.setAttribute('aria-label', mark.label);
        historyButtons.push([button, mark.history]);
        // mousedown so the box keeps the focus and the caret, and a keyboard
        // click beside it: Enter and Space produce no mousedown at all, and
        // thirteen of fourteen buttons on this bar were once mouse-only.
        button.onmousedown = event => { event.preventDefault(); step(mark.history); };
        button.onclick = event => { if (event.detail === 0) step(mark.history); };
      } else if (mark.upload) {
        button.onclick = () => area.dispatchEvent(new Event('openproj:pick-image'));
      } else {
        button.onmousedown = event => { event.preventDefault(); applyMark(surface, mark); };
        // And the keyboard, which `onmousedown` alone left out: Enter and Space
        // on a focused button produce a click and no mousedown at all, so every
        // mark in this bar was a focus stop that did nothing. `detail === 0` is
        // how a click synthesised from a key is told from one a pointer made, so
        // a mouse press still applies the mark exactly once.
        button.onclick = event => { if (event.detail === 0) applyMark(surface, mark); };
      }
      bar.append(button);
    }
  }

  // One press of undo or redo, sent to whichever history owns the document now.
  function step(what) {
    historyOf(surface).step(what);
    // The step may fire nothing this page hears: `execCommand('undo')` does fire
    // an `input`, but `Y.UndoManager.undo()` reaches the box through `reflect()`
    // inside `apply`, which deliberately fires none.
    syncHistory();
  }

  // **Disabled-ness has to be honest.** A control that looks pressable and does
  // nothing is worse than no control, and this bar has the conditions to produce
  // one: the native stack answers `queryCommandEnabled` truthfully only until
  // something assigns `.value`, and which history owns the document changes
  // under the toolbar when a room binds or drops. `disabled` and not a class —
  // it is the one state a screen reader, a pointer and the stylesheet all agree
  // about already.
  function syncHistory() {
    if (!historyButtons.length) return;
    const owner = historyOf(surface);
    for (const [button, what] of historyButtons) button.disabled = !owner.can(what);
  }
  // Every moment the answer can change and no more. `onCaret` is the five events
  // a person's hands produce, and each is a moment when the box is the browser's
  // editing host — the only moment `queryCommandEnabled` is answering about THIS
  // box rather than about whatever was focused last. `openproj:editing` is the
  // box arriving or somebody else writing into it; `openproj:history` is the
  // room binding, dropping, or its stack moving.
  surface.onCaret(syncHistory);
  addEventListener('openproj:editing', syncHistory);
  addEventListener('openproj:history', syncHistory);
  syncHistory();

  // Armed by Escape, spent by the next Tab, and cleared by typing — which is
  // what `input` is for rather than a second keydown branch: the Shift in
  // Shift-Tab is itself a keydown, so disarming on any key would have taken the
  // hatch away from the gesture for leaving backwards.
  let leaving = false;
  surface.onInput(() => { leaving = false; });

  area.addEventListener('keydown', event => {
    // **A `defaultPrevented` guard was written here and then measured away.**
    // The plan promised one, in those words, as how a keymap would claim a key
    // ahead of the three claimants below. It is not needed and it would encode
    // nothing: Ace's `stopEvent` does `stopPropagation` as well as
    // `preventDefault`, so a key its command table handled never reaches this
    // listener at all. Measured in Chrome on the second surface, with a listener
    // beside this one: Tab arrives at Ace's input and does NOT reach here — one
    // indent, Ace's, at its own tab width — while Escape and Cmd+S both do,
    // unprevented, so leaving the full-page view and saving still work. A guard
    // whose condition is never true is a guard nobody can test, and the last
    // thing this handler needs is a line that looks like arbitration and is not.
    if (event.key === 'Escape') {
      // Escape has three claimants, and this is where they are arbitrated. In
      // order of who gets it and why:
      //
      // 1. **The page, while there is something to come back out of.** On the
      //    pages with a full-page view, Escape leaves it — and on a record page
      //    the place it leaves TO is the sessionless read page, so the session
      //    ends with it. It goes first because it is what a person pressing
      //    Escape in a screen-filling editor means, because the change is
      //    visible the instant it happens, and because one click puts it back.
      //    Announced by nothing, because the whole screen answering is the
      //    answer.
      // 2. **The Tab hatch.** Tab indents here, which takes away the only way
      //    out of the box for somebody with no pointer. Escape gives it back for
      //    one press, and says so: an escape hatch nobody is told about is not
      //    one, and swallowing Tab in silence is the version of this feature
      //    that traps people.
      // 3. **Discarding writing: never.** The session Escape ends keeps the
      //    text in the surface and the draft in its store; putting fields back
      //    is Cancel, a button with a name, because a key that discards writing
      //    is a key somebody presses by mistake once.
      //
      // The seam is an event on the element, the way the image button's is: this
      // block is shared by every `_COMBOBOX` page and only the record page
      // and the create form have a view to leave.
      // Where nothing listens, nothing is cancelled and the hatch opens straight
      // away. Vim, if it is ever bought, claims Escape ahead of all three while
      // it is in insert mode, and the same `cancelable` answer is how it says so.
      if (!area.dispatchEvent(new Event('openproj:escaped', {cancelable: true}))) return;
      leaving = true;
      announce('Press Tab to leave the document, or carry on typing to stay in it');
      return;
    }
    if (event.key === 'Tab' && !event.metaKey && !event.ctrlKey && !event.altKey) {
      // Spent, and the browser moves focus the way it does everywhere else.
      if (leaving) { leaving = false; return; }
      event.preventDefault();
      indentLines(surface, event.shiftKey);
      return;
    }
    if (event.metaKey || event.ctrlKey) {
      const mark = FORMATS.find(
        m => m.key === event.key.toLowerCase() && !!m.shift === event.shiftKey
      );
      if (mark && !event.altKey) {
        // ⌘Z and ⌘⇧Z are the browser's before they are this page's, and the
        // page takes them only where the browser's own has been destroyed —
        // `keyed` says which. False on a textarea with no room, and that is not
        // laziness: the native binding restores the SELECTION the edit was made
        // with and `execCommand('undo')` does not. False on Ace, whose command
        // table took the key before this listener saw it. True in a live room.
        if (mark.history) {
          const owner = historyOf(surface);
          if (!owner.keyed) return;
          event.preventDefault();
          step(mark.history);
          return;
        }
        event.preventDefault();
        applyMark(surface, mark);
      }
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey) return;
    // Enter continues a list, which is the one thing everybody misses from
    // HackMD within a minute. An empty item ends the list instead of making
    // another empty one, which is how every editor that does this behaves.
    const [from] = lineRange(surface);
    const caret = surface.caret();
    const line = surface.text().slice(from, caret.from);
    const parts = LIST_ITEM.exec(line);
    if (!parts) return;
    event.preventDefault();
    const [, indent, bullet, gap, box, text] = parts;
    if (!text.trim()) {
      surface.splice(from, caret.to, '');
      return;
    }
    const next = /^\d+\./.test(bullet)
      ? `${parseInt(bullet, 10) + 1}.`
      : bullet;
    surface.splice(caret.from, caret.to, `\n${indent}${next}${gap}${box ? '[ ] ' : ''}`);
  });
}

// Two things a paste is nearly always the beginning of retyping by hand: a URL
// dropped over the words it should link, and a block of cells copied out of a
// spreadsheet. Both come back as markdown here, and both go in through
// `replaceRange`, so one ctrl-Z gives back exactly what was on the clipboard —
// which is the whole of the argument for doing this at all rather than leaving
// it to a person.
//
// An allowlist, and a narrow one, for the same reason `_image` is one: `http`
// and `https`, no whitespace, and only over a selection. A URL pasted with
// nothing selected is somebody pasting a URL, and `[](url)` there would be the
// editor guessing at what they meant.
const URL_ONLY = /^https?:\/\/\S+$/;

function pastedAs(surface, text) {
  if (!text) return null;
  const {from: start, to: end} = surface.caret();
  const chosen = surface.text().slice(start, end);
  const one = text.trim();
  if (chosen && URL_ONLY.test(one)) return `[${chosen}](${one})`;
  const rows = text.replace(/\n$/, '').split('\n').map(row => row.split('\t'));
  // Two rows and two columns, every row the same width. Anything less is a line
  // that happens to contain a tab, and a line is what it has to paste as: a
  // paste that quietly becomes something else is worse than no help at all.
  if (rows.length < 2 || rows[0].length < 2) return null;
  if (!rows.every(row => row.length === rows[0].length)) return null;
  // A cell's own pipe would end the cell. Escaped rather than dropped, because
  // the numbers people paste here are measurements and one of them is a range.
  const line = cells =>
    '| ' + cells.map(cell => cell.trim().replace(/\|/g, '\\|')).join(' | ') + ' |';
  const table = [line(rows[0]), line(rows[0].map(() => '---')), ...rows.slice(1).map(line)]
    .join('\n');
  const [lead, tail] = blockPadding(surface.text().slice(0, start), surface.text().slice(end));
  return lead + table + tail;
}

// Paste or drop an image and it goes into the plan repository, content-addressed,
// and the markdown that names it is inserted where the cursor is. The path is
// written repository-relative so the same text reads correctly in git, on GitHub
// and here — only the prefix in front of it differs.
function attachUploads(surface, status) {
  const area = surface.el;
  // At the caret, which the splice has to be told rather than left to infer —
  // that explicitness is the whole point of the boundary. See `textareaSurface`.
  const insert = markdown => {
    const {from, to} = surface.caret();
    surface.splice(from, to, markdown);
  };

  async function send(file) {
    if (!file) return;
    // The branch that decides not to act, saying so. `accept="image/*"` filters
    // the dialog and does not bind it — macOS Chrome's format popup still offers
    // All Files — so somebody who presses Image, picks a PDF and comes back used
    // to get no status text, no announcement and no change. "Nothing happened"
    // is a plausible outcome of a paste; it is not a plausible outcome of
    // pressing a button called Image.
    if (!file.type.startsWith('image/')) {
      status.textContent = `${file.name || 'that file'} is not an image`;
      announce(status.textContent);
      return;
    }
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
      const answer = await answerOf(response);
      // Only a fresh upload made a commit. Claiming the sha of one that was
      // already in the plan would swallow a banner about somebody else's write.
      if (response.ok && answer.fresh) committed = answer.commit;
      const alt = (file.name || 'image').replace(/\.[^.]+$/, '').replace(/[\[\]]/g, '');
      const at = surface.text().indexOf(token);
      // The placeholder is not there any more. It was undone, or typed over, or
      // the whole document was replaced by a restored draft while the upload was
      // in the air — all of which take longer than they sound over a phone
      // connection. This used to be `if (at >= 0) { … }` with nothing else: the
      // blob was committed, nothing was inserted, and the bar said "uploaded"
      // over a document with no image in it. The commit is the server's and
      // cannot be taken back from here, so the honest answer is to say the file
      // is in the plan and hand over the line that reaches it.
      if (at < 0) {
        status.textContent = response.ok
          ? `${answer.path} is in the plan, but the line that pointed at it is gone — `
            + `type ![${alt}](${answer.path}) where you want it`
          : (answer.detail || 'that upload was refused');
        announce(status.textContent);
        return;
      }
      surface.splice(at, at + token.length, response.ok ? `![${alt}](${answer.path})` : '');
      status.textContent = response.ok
        ? (answer.fresh ? `${answer.path} uploaded` : `${answer.path} — already in the plan`)
        : (answer.detail || 'that upload was refused');
    } catch (error) {
      // The connection went while the request was in the air: wifi dropped, the
      // laptop slept, the tab was offline before the press. This was `try` and
      // `finally` with no `catch`, so the rejection escaped as an unhandled one
      // and what a person was left looking at was the placeholder sitting in
      // their document for ever with `uploading diagram.png…` under it — a
      // sentence that says the thing is still happening, about a thing that
      // stopped.
      //
      // The token goes back out through the surface and not by assignment, so
      // one Ctrl+Z is still one step; and the sentence names the file, because
      // a paste of three images that half fails is otherwise unreadable.
      const at = surface.text().indexOf(token);
      if (at >= 0) surface.splice(at, at + token.length, '');
      status.textContent =
        `${file.name || 'that image'} was not uploaded — ${error.message}`;
      announce(status.textContent);
    } finally {
      dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
    }
  }

  // The toolbar's image button, wired without either function reaching into the
  // other. `attachEditing` builds the bar and `attachUploads` owns the upload,
  // and every page attaches them in two lines that know nothing of each other;
  // an event on the element they both already hold is the seam. A page with a
  // toolbar and no uploader would draw a button that does nothing, and there is
  // no such page — all four call both.
  area.addEventListener('openproj:pick-image', () => {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/*';
    picker.multiple = true;
    picker.onchange = () => [...picker.files].forEach(send);
    picker.click();
  });

  area.addEventListener('paste', event => {
    const files = [...(event.clipboardData?.files || [])];
    if (files.length) {
      event.preventDefault();
      files.forEach(send);
      return;
    }
    const made = pastedAs(surface, event.clipboardData?.getData('text/plain') || '');
    // `null` and not `''`: everything this does not recognise is left to the
    // browser, which pastes it as the text it is.
    if (made === null) return;
    event.preventDefault();
    const {from, to} = surface.caret();
    surface.splice(from, to, made);
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

// Every list currently parked on the body, with the input it belongs to.
//
// A list used to be the input's own next sibling, which meant `overflow` on any
// ancestor cut it off: the table's rows scroll inside `.table-scroll` and nine
// of its fourteen columns carry one of these, so a list opened on a low row was
// clipped against the bottom of the box — the normal case, not an edge. The
// frozen columns made it worse: `position: sticky` with a z-index is a stacking
// context, so a list opened in the title column was also painted under the
// sticky header. The body has neither problem, and nothing has to be given
// `position: relative` to anchor it any more.
//
// The price is that a list is no longer removed with the input it belongs to,
// and the table replaces its whole tbody after every save. An input taken off
// the page while it still holds focus never fires blur, so closing on blur is
// not enough to clean up after it — every list parked here is swept the next
// time one is. The scroll listener goes with it: it is what keeps the list under
// a box that moves, and forty cell edits would otherwise leave forty of them
// measuring inputs that are no longer on the page.
const PARKED = [];

function park(input, list, follow) {
  for (let i = PARKED.length - 1; i >= 0; i--) {
    const stale = PARKED[i];
    if (stale.input.isConnected) continue;
    stale.list.remove();
    removeEventListener('scroll', stale.follow, true);
    removeEventListener('resize', stale.follow);
    PARKED.splice(i, 1);
  }
  PARKED.push({input, list, follow});
  document.body.append(list);
  // Anything that moves the input moves the list: the page scrolling, the table
  // scrolling inside its own box, the window resizing. Capture, because a scroll
  // event on an element does not bubble up to the window.
  addEventListener('scroll', follow, true);
  addEventListener('resize', follow);
}

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

  // Where the input is, in the page's coordinates rather than the viewport's:
  // the list hangs off the body now, so it is positioned against the document.
  // Declared inside `attachSuggest` and not beside it, because the detail page
  // already has a global `place` — the one that puts the width grip against the
  // article — and two classic scripts on a page share one scope.
  function place() {
    const box = input.getBoundingClientRect();
    const under = innerHeight - box.bottom;
    // Above the box when there is no room under it. Parking the list on the body
    // stops it being clipped, but a list hanging off the bottom of the window
    // still has to be scrolled to, and the row somebody is editing is the row
    // they are looking at.
    const over = under < list.offsetHeight && box.top > under;
    list.style.left = (box.left + scrollX) + 'px';
    list.style.top = (over ? box.top + scrollY - list.offsetHeight
                           : box.bottom + scrollY) + 'px';
  }

  park(input, list, () => { if (!list.hidden) place(); });
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
    // Everything but the counter is stored text. For the `records` source the
    // value is an id and the label IS a record title, so before this, opening
    // the Parent list on the detail page inserted whatever the last person to
    // rename a record had typed — as markup, into a page that then offers a
    // Save button. `esc` is the shell's, so this widget uses the same one the
    // table and the timeline do rather than being the one script with none.
    list.innerHTML = matches
      .map((m, i) => `<li id="${id}-${i}" role="option" data-value="${esc(m.value)}">` +
        `${esc(m.value)}${m.label ? ` <span class="dim">${esc(m.label)}</span>` : ''}</li>`)
      .join('');
    active = matches.length ? 0 : -1;
    list.hidden = !matches.length;
    // After it is shown and filled, because `place` measures how tall it is to
    // decide whether it fits under the box.
    if (!list.hidden) place();
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


# Every branch carries an `id`, and every `<dt>` that renders one of these carries
# a `<label for>` pointing at it. A `<dt>`/`<dd>` pair is a name and a value to a
# reader and nothing at all to the accessibility tree, so before this not one
# control on the detail page or the create page had a name.
_CONTROL = """
{% if f.type == "priority" %}
<select name="{{ f.name }}" id="{{ f.id }}" data-type="text" class="field"
        {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
        {% if f.disabled %}disabled{% endif %}
        {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
  {#- The mark in front of the word, the same one the graph draws on a node and
      the table draws in a cell — jcanton, 2026-08-20: "can we have the status and
      priority icons and colours also in the dropdowns for editing a record".
      Status used to share this branch and left when it became the hill; priority
      keeps the native `<select>`, and the mark-as-text is the honest cost of
      keeping one. -#}
  {% for s in priorities %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{
    mark(f.type, s) }}{{ s|human }}</option>
  {% endfor %}
</select>
{% elif f.type == "bool" %}
<input type="checkbox" name="{{ f.name }}" id="{{ f.id }}" data-type="bool" class="field"
       {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
       {% if f.disabled %}disabled{% endif %}
       {% if f.value %}checked{% endif %}>
{% elif f.type == "date" %}
<input type="date" name="{{ f.name }}" id="{{ f.id }}" data-type="date" value="{{ f.text }}"
       class="field"
       {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
       {% if f.disabled %}disabled{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% else %}
<input name="{{ f.name }}" id="{{ f.id }}" data-type="{{ f.type }}" value="{{ f.text }}"
       class="field" autocomplete="off"
       {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
       {% if f.placeholder %}placeholder="{{ f.placeholder }}"{% endif %}
       {% if f.disabled %}disabled{% endif %}
       {% if f.list %}data-suggest="{{ f.list }}"{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% endif %}
"""

# One script for both forms that carry a status. Written once because the create
# page and the detail page ask the same question of the same controls, and two
# copies of a validation courtesy is one copy that quietly stops matching.
_REQUIRED_JS = Markup("""
// The status a form with no status control is read as. Handed over from the
// model rather than typed here: `Record.status`'s default is the one place a new
// record's opening word is written, and this was a second copy of it — with
// `createRecord` on the create page a third — that would have gone on saying
// `shaping` after the ladder grew a rung below it, in silence, because the two
// scripts that read it only ever ask which labels to mark.
//
// A form has no status control when its kind does not read one (a product), and
// the gates at the opening status are empty either way, so nothing visible turns
// on the value. What turns on it is that a wrong word here is a word no
// `data-required-at` list contains, which marks nothing and says nothing.
const OPENS = """ + json.dumps(Record.model_fields["status"].default) + """;

// The word printed beside a control, which is the word somebody is looking at.
// The `<dt>` holds the label and then the mark, so its first node is the name.
function labelOf(control) {
  const dt = control.closest('dd')?.previousElementSibling;
  return dt ? dt.childNodes[0].textContent.trim() : control.name;
}

// What the server refused a write with, in the words on this page. A Problem
// carries its field as an identifier because that is what marks the control;
// printing that identifier is how `person_weeks` ended up in a sentence under
// a label reading "Appetite (weeks)". The field is named by the same `labelOf`
// the form's own check uses, so the two refusals cannot drift apart.
function refusals(answer, status) {
  const problems = answer.problems || [];
  // The shell's `refusal`, which is the one place that knows a 409 answers with
  // a report rather than with a `detail` — creating a record against a moved
  // HEAD is a conflict like any other, and this line printed "refused" for it.
  if (!problems.length) return [refusal(answer, status)];
  return problems.map(problem => {
    // `CSS.escape` because the field arrives over the wire: an unescaped one
    // would be a malformed selector, and a DOMException here would swallow the
    // whole refusal rather than one line of it.
    const control = problem.field
      && document.querySelector(`[data-type][name="${CSS.escape(problem.field)}"]`);
    return control ? `${labelOf(control)}: ${problem.message}` : problem.message;
  });
}

// What the chosen status will make the server refuse this form without. Marked
// on the label rather than announced after a rejected save: which fields a
// status demands is the thing you need before you fill the form in, and the
// rules change under you the moment the status select does.
function markRequired(form) {
  const status = form.querySelector('[name=status]')?.value || OPENS;
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
""")


def _control_html(
    field: dict,
    *,
    ladder: str = "record",
    live: bool = True,
    shown: str | None = None,
    describedby: str = "",
) -> Markup:
    # Status is the one field whose control is not a box. It is the hill, and the
    # `<select>` that was here is gone rather than kept beside it: `render.py`'s
    # header already carries the note about what the same word in the same colour
    # twice costs, and a dropdown under a hill that sets the same field is that
    # note again with an extra control.
    #
    # The hidden input, and not the radios, is what the form serialises. `CONTROLS`
    # is `querySelectorAll('[data-type]')` keyed by `name`, so five radios sharing
    # one name would leave `ORIGINAL` holding a single entry and `changed()`
    # answering for whichever radio it read last. `markRequired` and the create
    # form's refusal both ask `[name=status]` for a value and neither has to know
    # that the thing behind it became a picture.
    #
    # `shown` is the word the picture draws; the input keeps the stored one. They
    # differ only on a locked control, where the state is derived from a link —
    # the read view already shows the derived word, and "pressing Edit moves
    # nothing" is a promise this row makes two comments up.
    if field["type"] == "status":
        return Markup(
            # No `.field`: that class is what `.record.editing .field { display:
            # block }` switches on, and a hidden input is the one control that must
            # not gain a box when the form opens. `CONTROLS` reads `[data-type]`,
            # which is the attribute that matters here.
            '<input type="hidden" name="{}" id="{}" data-type="text"'
            ' value="{}" data-word="{}"{}>{}'
        ).format(
            field["name"],
            field["id"],
            field["value"],
            _human(field["value"]),
            # `disabled` on the input as well as no stops on the hill. The form's
            # own serialiser never sends an unchanged field, so this submits
            # nothing differently — it is the DOM saying what the page means, so
            # a test can ask the input rather than inferring the lock from an
            # absence of radios.
            Markup(" disabled") if not live else Markup(""),
            # Grouped by the control's own id. The static export puts every record
            # in one file, and one group name would have made four hundred records
            # share a single radio group — pressing a stop on one moves the ball on
            # all of them.
            _hill_html(
                shown if shown is not None else field["value"],
                ladder,
                live=live,
                control=True,
                group=f"hill-{field['id']}",
                describedby=describedby,
            ),
        )
    # Every branch takes it, not only the two fields that carry one today:
    # `aria-describedby` is a property of a control, and a template where
    # three of four branches silently drop it is the copy that goes stale the
    # day a fourth hint is written.
    return _fragment(_CONTROL, f=field, priorities=PRIORITIES, describedby=describedby)


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
    # Records, not the plan: `reported_by` and `written_by` names and an inbox
    # record's tags belong in the datalists like anybody else's.
    for record in index.records.values():
        for name in PEOPLE_FIELDS:
            value = getattr(record, name, None)
            people.update(value if isinstance(value, list) else [value] if value else [])
        tags.update(record.tags)
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
    refs = {ref for record in index.records.values() for ref in record.prs}
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
        # Named `records`, filled from the PLAN, deliberately: these complete
        # `parent` and `depends_on`, and offering an issue or a note there
        # would offer an edge the model refuses.
        "records": [
            {"value": i, "label": e.title} for i, e in sorted(index.plan.items())
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


def _cycle_numbers(index: Index) -> set[int]:
    """Every cycle the plan names.

    Three sets that are not the same set: the cycles with a record, the cycles
    config/cycles.yaml dates, and the cycles records point at. A page that asks
    only one of them loses exactly the cycle somebody is looking for — the one
    holding work with nothing written down behind it.
    """
    return (
        set(index.plans)
        | set(index.cycles)
        | {e.cycle for e in index.plan.values() if e.cycle is not None}
    )


_NO_ASIDE = Markup("")


def _facets_html(
    facets: dict,
    fields: tuple[str, ...] = _PLAN_FACETS,
    search: str = "Search titles, tags, PRs, people",
    aside: Markup = _NO_ASIDE,
    titles: dict[str, str] | None = None,
) -> Markup:
    """The control bar, for any view that filters anything.

    One bar and one `matches()` in `_FILTER_JS`, rather than a copy per page: the
    table's dropdowns and the graph's have to mean the same thing, or a link
    somebody pasted filters differently depending on which view it opens in. The
    people page had written its own, over its own three fields, and had already
    drifted — same markup, a different search box.

    `titles` is what a value is called where the value itself is not a word: the
    Project menu's values are record ids, because that is what the filter matches
    and what the URL has to carry, and a menu of `proj-370001` asks a reader to
    know the plan by heart. Given per page rather than looked up here, because
    this function is handed facets and not an index — the people page's three
    fields have no titles at all.

    `aside` rides at the far end of the search box's line. It is here rather than
    on each page because the sentence a view writes about itself was a full row on
    every one of them, and a row above the drawing is the most expensive place on
    these pages to put twelve words.
    """
    return _fragment(
        _FACETS, facets=facets, fields=fields, search=search, aside=aside,
        titles=titles or {},
    )


def _combobox_html(index: Index | None) -> Markup:
    """The suggestion data and the widget that filters it, for any page with inputs."""
    data = (
        _suggestions(index)
        if index
        else {"people": [], "records": [], "tags": [], "prs": [], "cycles": []}
    )
    return _fragment(
        _COMBOBOX, suggest=data, max_body_bytes=MAX_BODY_BYTES, history_art=HISTORY_MARKS
    )
