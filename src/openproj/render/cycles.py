"""The cycle page, the cycles listing, and the people page."""

from __future__ import annotations

from datetime import date

from markupsafe import Markup

from ..index import Index
from ..model import Config, Cycle, days_after, is_bettable, size_weeks, without_comments
from ..schedule import build_end
from .controls import _FILTER_JS, _combobox_html, _cycle_numbers, _facets_html
from .env import _compiled
from .icons import _ICON_ART, ICONS, icon_svg
from .markdown import _markdown
from .shell import ROUTES, STATIC, Links, _page
from .styles import _DETAIL_STYLE, _SCROLL_STYLE, _SUGGEST_STYLE
from .tokens import PRIORITIES, STATUSES

# Betting table to review meeting for a plan with nothing to copy from. Four
# weeks is the team's cadence; every cycle written after the first one carries
# its predecessor's length instead.
_DEFAULT_CYCLE_DAYS = 28


_CYCLE = """
{#- The same header the detail page and the create form wear: a way back, then
    the name, then the meta line. `.back` and not `.editbar` — this is one link
    out, not a row of controls, and it was the only one of the three sized
    differently.

    The eyebrow the other two carry is missing here on purpose. It says what the
    thing is, and this heading is "Cycle 37": the kind is already its first word,
    so a CYCLE chip above it would be the restatement the id column's kind chip
    was. -#}
<p class="back"><a href="{{ links.cycles }}">← all cycles</a></p>
<h1>Cycle {{ c.number }}</h1>
{#- The one link off this page that is not a record: the deck for the review
    meeting, which is the other thing `reviews_on` is a date for. Drawn only where
    `links.deck` is set, which is the server — a static export has no per-cycle
    page and nothing to number a deck with. It is not in the nav: the nav names
    the views of the whole plan, and this is one cycle's handout. -#}
{% if links.deck %}<p class="back"><a href="{{ links.deck }}{{ c.number }}"
  >Review deck →</a></p>{% endif %}
{% if c.recorded %}
<p class="meta">{{ on(c.starts_on) }} → builds until <b>{{ on(c.builds_until) }}</b>
   → cool-down ends {{ on(c.ends_on) }}</p>
{% else %}
<p class="meta">No record yet{% if c.dated %} — config/cycles.yaml puts this cycle at
   {{ on(c.starts_on) }} → {{ on(c.ends_on) }}{% endif %}. Nothing holds these weeks: what is
   below is the record Save would write.</p>
{% endif %}

{% if editable %}
{#- One Save for the whole page, at the top of it, where the detail page and the
    create form now keep theirs. It was last in the markup — under the setup form,
    the roster, the betting table and the notes box — which is a long way from the
    row being argued about at a betting table, and since the shell's
    `#commitbar { top: 0 }` reached this page through `_DETAIL_STYLE` it was not
    even stuck to the foot any more: measured in Chrome at 1400x900, the bar sat
    1113px down a 1206px page and was on screen from nowhere at the top of it.

    The old argument here was F15 — "every commit action on this page sat above
    the form it commits". What that fix actually bought was reachability, and the
    sticky it shipped alongside is what keeps it: this page is one record and one
    Save, and the bar is on screen at both ends of it either way. -#}
<div class="commitbar" id="commitbar">
  <span id="unsaved">Nothing to save</span>
  <button type="button" id="save" disabled>Save</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</div>
{% endif %}

{#- Three boxes that decide when the cycle runs and how long for, and not one of
    them had a name: the word beside each is a `<dt>`, which is a caption to a
    reader and nothing to the accessibility tree. -#}
{#- The read-mode value is hidden wherever a box is drawn beside it. This page
    renders both at once — it has no editing/reading toggle, so `.read` and the
    input are on screen together — and after the `.iso` echo went that left
    `25.08.2026` printed immediately left of a box already showing the same day.
    One fact, twice, differently formatted, is exactly what jcanton asked to have
    removed; the span stays in the markup for a reader the server would refuse a
    write from, where there is no box and it is the only value on the row. -#}
<form id="setup" onsubmit="return false">
  <dl id="facts">
    <dt><label for="starts_on">Starts on</label></dt>
    <dd><span class="read">{{ on(c.starts_on) }}</span>
        <input type="date" id="starts_on" name="starts_on" data-type="date"
               value="{{ c.starts_on }}" class="field"></dd>
    <dt><label for="reviews_on">Review meeting</label></dt>
    <dd><span class="read">{{ on(c.reviews_on) }}</span>
        <input type="date" id="reviews_on" name="reviews_on" data-type="date"
               value="{{ c.reviews_on }}" class="field"></dd>
    {#- Both of the above are meetings somebody put in a calendar. Everything
        below is worked out from them and from the holidays, so it is written in
        the derived style and has no box. -#}
    <dt class="derived">Builds until</dt>
    <dd class="derived">{{ on(c.builds_until) }} · {{ c.build_weeks }} working weeks
      {% if c.assumed_review %}<span class="warnish">— assumed: this cycle names
        no review meeting</span>{% endif %}</dd>
    <dt class="derived">Cool-down ends</dt>
    <dd class="derived">{{ on(c.ends_on) }}
      {% if c.assumed_end %}<span class="warnish">— assumed: the next cycle's
        betting table is what ends it, and there is no record after this
        one</span>{% endif %}</dd>
  </dl>
</form>

<h2>Who is in this cycle</h2>
<p class="hint">Availability is a fraction of the {{ c.build_weeks }} working weeks
  this cycle builds for. Only the people named here are in the cycle.
  <span id="stale" class="warnish" hidden>The dates changed — capacity is
    recounted when you save.</span></p>
<div class="sideways">
<table class="load unfitted"><thead><tr>
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
    {#- The bet, and what is missing from it. A record with nobody's estimate on
        it charges nobody, so this number is smaller than the work on this
        person's plate — and a smaller number with no explanation beside it is
        read as less work rather than as less knowledge. -#}
    <td class="derived">{{ '%.1f'|format(row.held) }} wk{% if row.unsized %}
      <span class="unsized">· {{ row.unsized }} not sized</span>{% endif %}</td>
    <td><span class="bar"><span style="width: {{ row.percent }}%"></span></span></td>
    <td class="derived">{{ on(row.until) }}</td>
  </tr>
  {% endfor %}
</tbody></table>
</div>
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
{% if c.carried %}
{#- Counted in the bars above, and named here. Work bet in an earlier cycle keeps
    that cycle's number so its overrun keeps accusing, which also means the load
    column cannot show where it came from. -#}
<p class="hint" id="carried">Counted above, and carried in from an earlier cycle:
  {% for row in c.carried %}<a href="{{ links.record }}{{ row.id }}">{{ row.title
  }}</a> (bet in {{ row.cycle }}){% if not loop.last %}, {% endif %}{% endfor %}.</p>
{% endif %}

{#- What the cycle produced, directly under what was planned for it and above the
    line where the next betting table begins. §5 of `design/time-model.md` draws
    them in that order and against a rule, and the reason is that they are two
    readings of the same weeks that must be read together: the roster says every
    person is at 0.0 of their capacity, and this says what they spent it on. A
    section further down the page — after the goal, or under the notes — is a
    correction to a number nobody scrolls back up to re-read. -#}
<section id="delivered">
<h2>Delivered</h2>
<p class="hint">What ended inside this cycle's window, by the date on the record.
  It is not in the weeks above: those are what people's <em>next</em> weeks hold,
  and finished work is nobody's next week.
  {#- Said only where there is such a row. A line explaining a state the reader
      cannot see is paid for by everybody who has none of it. `rejectattr` with no
      test reads the attribute as a boolean, which is the same question the cell
      below asks.

      This comment strips on its left and not on its right, which every other
      comment on this page does at both ends. What the right-hand strip eats here
      is the newline separating two sentences of prose, and it printed
      "nobody's next week.A record written before" on the corpus's cycle 28. #}
  {% if c.delivered|rejectattr('ended')|list %}A record written before the end
  date existed has none to show; it is listed under the cycle its bet was made
  in, and there is nothing this can say about when it landed.{% endif %}</p>
{% if c.delivered %}
<div class="sideways">
<table class="delivered unfitted"><thead><tr>
  <th>title</th><th>bet</th><th>ended</th></tr></thead>
<tbody>
  {% for row in c.delivered %}
  <tr data-id="{{ row.id }}">
    <td><a href="{{ links.record }}{{ row.id }}">{{ row.title }}</a></td>
    {#- An empty appetite is named rather than filled in with a number, exactly as
        the betting table's placeholder is: the size gate reaches `ready` and
        `in_progress` and nothing older, so finished work with no bet on it is an
        ordinary thing to find and not a fault. -#}
    <td class="num">{% if row.bet %}{{ row.bet }} wk{% else %}<span class="quiet"
      >not sized</span>{% endif %}</td>
    {#- The detail page's own overrun sentence, shortened to what a column can
        hold and wearing the same class and the same mark, so the one sentence
        that says a bet did not fit its box reads alike wherever it is drawn. The
        cycle it names is the span's and never this page's number: a task under a
        pitch bet in 36 can be delivered in 37, and the box it missed is still
        36's.

        The separator is written inside the `if` and the tag before it strips
        rather than the other way round, because the space in front of the dot is
        load-bearing: laid out over two lines with the comment between them it was
        eaten, and the cell read `07.10.2026· ▲`. -#}
    <td class="num">{% if row.ended %}{{ on(row.ended) }}
      {%- if row.over %} · <span class="overrun"><span class="sev-mark sev-mark-warn"
        aria-hidden="true">▲</span> {{ row.over }} wk past cycle {{ row.over_cycle
        }}</span>{% endif %}{% else %}<span class="quiet">no end date</span>{% endif %}</td>
  </tr>
  {% endfor %}
</tbody></table>
</div>
{% else %}
{#- Empty is an invitation to act, and this one has an action: the end date is
    collected at the transition, so what puts work here is marking it done. -#}
<p class="hint">Nothing has landed in this window yet. Marking work done records
  the day it ended, and that date is what puts it here.</p>
{% endif %}
</section>

{#- The goal above the table, the notes below it, and they are two fields now.
    One box served as both for as long as the goal was the body, which put the
    cycle's whole point wherever the growing half of the document happened to
    leave it — and there is no arrangement of one box that is both above the
    table where the room is looking and below it where the room is writing. -#}
<h2>Goal</h2>
{% if editable %}
<p class="editbar goalbar">
  <textarea id="goal" class="goal" rows="2"
    aria-label="What this cycle is for"
    placeholder="What this cycle is for. Settled at the betting table.">{{ c.goal }}</textarea>
</p>
{% elif c.goal %}
<p class="goal read">{{ c.goal }}</p>
{% endif %}

<h2>The bet</h2>
{#- The search box on the same line as the sentence that describes the table —
    jcanton, 2026-08-25: "inline the search box left of the description". It
    belongs to this table and not to the page, so it sits with the table's own
    caption rather than in a control bar above the heading.

    A box and not the facet bar the three plan views share. The facets it would
    offer are status and kind, and this table is ALREADY only ready and
    in-progress bettable records — a filter whose whole vocabulary has been
    applied is a control with one setting. What a betting table actually needs
    is "where is the thing somebody just said out loud", which is a search, and
    "put the big ones together", which is a sort. -#}
<p class="hint betsearch">
  <label for="betfind" class="sr-only">Search the betting table</label>
  <input type="search" id="betfind" placeholder="Search" autocomplete="off">
  <span>Everything ready or in progress. Ticking one stamps it with cycle
  {{ c.number }}; an item already in progress from an earlier cycle keeps the cycle it
  was bet in, so its overrun keeps counting.</span>
</p>
{#- Empty is not broken, and a search that matches nothing is the commonest way
    to arrive at an empty table. Drawn inside the table's own body by the script,
    with the control that gets you out of it — finding F1, which keeps coming
    back through new mechanisms. -#}
<p class="hint" id="betnone" hidden>Nothing here matches
  <strong id="betterm"></strong>. <button type="button" id="betclear">Clear the
  search</button></p>
{#- No `table-scroll` wrapper. It wore one from the day it was written, against a
    stylesheet that has never carried the rule, so the class did nothing — and
    the rule is the table page's own, sized against a stack of controls this page
    does not have. Eight columns fit a screen; the page scrolls. -#}
{#- Every column head but the first is a sort control. The tick column is not:
    it holds a checkbox per row and sorting by "have I bet on this yet" would
    reorder the table under the hand that is ticking it.

    `aria-sort` and a real `<button>` inside the `<th>`, because a clickable
    table head that is only a `<th>` with a listener is a control a keyboard
    cannot reach and a screen reader does not announce — the quality floor this
    repository holds every page to. -#}
<div class="sideways">
<table id="bets" class="unfitted" autocomplete="off"><thead><tr>
  <th>in {{ c.number }}</th>
  {% for column in ("title", "kind", "status", "priority", "appetite", "assignees", "reviewers") %}
  <th data-sort="{{ loop.index }}" aria-sort="none">
    <button type="button" class="sorter">{{ column }}</button></th>
  {% endfor %}
  <th data-sort="8" aria-sort="none"><button type="button" class="sorter">bet in</button></th>
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
    <td><a href="{{ links.record }}{{ row.id }}">{{ row.title }}</a></td>
    <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
    {#- Status and priority are CHOSEN, never typed: three words over six rungs is
        a way to write `in progres` into the corpus, and the record page and the
        table both already answer this question with a closed list. The mark
        travels with the word for the same reason it does in the table's editor —
        a picker that drops the glyph is a picker whose open state says something
        different from the cell it replaced.

        Both are offered on a carried row. What a carried row may not have is a
        second cycle stamped onto it, which is the checkbox; its priority is a
        fact about the work and stays as editable as anybody's. -#}
    <td><select class="pick {{ status_class(row.status) }}" data-field="status"
        aria-label="{{ row.title }} status">
      {% for value in statuses %}<option value="{{ value }}"
        {{- ' selected' if value == row.status else '' }}>{{ mark('status', value) }}{{
        value|human }}</option>{% endfor %}</select></td>
    <td><select class="pick" data-field="priority" aria-label="{{ row.title }} priority">
      {% for value in priorities %}<option value="{{ value }}"
        {{- ' selected' if value == row.priority else '' }}>{{ mark('priority', value) }}{{
        value|human }}</option>{% endfor %}</select></td>
    <td><input class="live" data-field="{{ row.size_field }}" data-type="number"
               aria-label="{{ row.title }} appetite in weeks"
               autocomplete="off" value="{{ row.size }}"
               placeholder="not sized"></td>
    <td><input class="live wide" data-field="assignees" data-type="list"
               aria-label="{{ row.title }} assignees"
               data-suggest="people" autocomplete="off" value="{{ row.assignees }}"></td>
    <td><input class="live wide" data-field="reviewers" data-type="list"
               aria-label="{{ row.title }} reviewers"
               data-suggest="people" autocomplete="off" value="{{ row.reviewers }}"></td>
    <td class="derived">{{ row.cycle }}</td>
  </tr>
  {% endfor %}
</tbody></table>
</div>

<h2>Notes</h2>
{#- Below the table on purpose: this is what the room said while it was ticking
    rows — why a pitch was left out, what would make it a bet next time — and it
    was going into a HackMD note nobody linked. Still the record's markdown body,
    so it renders like every other shaping document here. -#}
{#- Rendered OR editable, never both. The detail page draws prose above the box
    that edits it because the two are far apart there and the rendered copy is
    the thing you came to read. Here they are adjacent, so the page printed the
    notes twice — once as markdown and once as the same text in a box directly
    beneath it — which reads as a bug rather than as a preview.

    The hint that used to sit between them is the box's placeholder now, for the
    same reason: a line under a heading explaining what Notes are for is paid for
    by every reader on every visit; a placeholder is paid for only by the person
    looking at an empty box. -#}
{% if editable %}
<textarea id="notes" class="notes" rows="8" aria-label="Cycle notes"
  placeholder="What came up at the betting table — why a pitch was left out,
what would make it a bet next time. Markdown.">{{ c.raw_body }}</textarea>
{% else %}
<div class="doc read">{{ c.body }}</div>
{% endif %}

{% if editable %}
{{ combobox }}
<script>
const BASE = document.getElementById('base');
const BAR = document.getElementById('commitbar');
const UNSAVED = document.getElementById('unsaved');
const NUMBER = {{ c.number }};
// Working weeks between the two meetings, holidays taken out — the server's
// answer, shipped rather than recomputed. See the input listener below.
const BUILD_WEEKS = {{ c.build_weeks }};
// What is on this page, so the shell's banner can tell a write that lands here
// from one that lands somewhere else. The cycle record and every record that can
// be bet into it: those are the ids the server announces.
window.SHOWING = ['cycle-' + NUMBER].concat(
  [...document.querySelectorAll('#bets tbody tr')].map(tr => tr.dataset.id));

// Through the shell's live region, which is what puts it in `#state` as well.
// A receipt that is only drawn is a save nobody is told landed.
function say(message) { announce(message); }

async function put(fields, body = null) {
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/cycle/${NUMBER}`, {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields, body}),
    });
    // `answerOf` and not `response.json()`: a 500 answers in plain text, and the
    // rejection took `flush()` with it — Save disabled, the bar still claiming
    // unsaved changes, and nothing said. `refusal` because a cycle written
    // against a moved HEAD answers with a report and no `detail` at all.
    const answer = await answerOf(response);
    if (!response.ok) { say(refusal(answer, response.status)); return null; }
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
const NOTES = document.getElementById('notes');
const GOAL = document.getElementById('goal');
let ROSTER_DIRTY = false;
let NOTES_DIRTY = false;
// The goal is a frontmatter field, so it travels with the roster and the dates
// rather than with the body — but it is dirty-tracked like the notes, because an
// untouched box must not be sent: a cycle whose goal nobody edited would
// otherwise be rewritten on every roster save, and `patch_text` only leaves a
// field alone if it is absent from the payload.
let GOAL_DIRTY = false;
const NOTES_WERE = NOTES ? NOTES.value : '';
const GOAL_WAS = GOAL ? GOAL.value : '';

// The receipt has to outlive the reload that proves it. Saving reloads, because
// half the numbers on this page — capacity, load, the scheduled-until column —
// are derived from what was just written; a confirmation that only lived in the
// DOM would be thrown away by the very thing it is confirming.
const RECEIPT = 'openproj:cycle-saved';
let receipt = '';

// Through the shell's door, which is where the guard for a store that throws
// lives now. It was written a second time here, as a `try` around the read —
// the same rule in two places, and the copy that had to be remembered.
const landed = forThisTab.get(RECEIPT);
if (landed) { say(landed); forThisTab.forget(RECEIPT); }

// The whole roster in one write. A name left out means somebody was taken off,
// which per-field merging would silently undo.
async function saveSetup() {
  const setup = document.getElementById('setup');
  const availability = {};
  for (const input of document.querySelectorAll('input.rate')) {
    const typed = input.value.trim();
    const rate = Number(typed);
    // Refused, not skipped. A missing name means somebody was taken out of the
    // cycle with their capacity, so `if (rate > 0)` turned an empty box, a zero
    // or a `50%` into a removal nobody asked for and nothing reported. Taking
    // somebody out is the button beside their name, which asks first. Said the
    // way the bets table one screen away says it: the field, and the value.
    if (!typed || Number.isNaN(rate) || rate <= 0) {
      say(`${input.dataset.login}'s availability must be a number greater than `
          + `zero, not "${input.value}"`);
      input.focus();
      return false;
    }
    availability[input.dataset.login] = rate;
  }
  // The three boxes as they were typed. `Number('six')` is NaN and
  // `JSON.stringify` sends NaN as null, so coercing here threw the typo away and
  // left the server refusing "blank" about a box holding a word. The server is
  // the one place that decides what a cycle field may hold, and it can only name
  // the value if it is given the value.
  const fields = {
    starts_on: setup.querySelector('[name=starts_on]').value,
    reviews_on: setup.querySelector('[name=reviews_on]').value.trim(),
    availability,
  };
  if (GOAL_DIRTY) fields.goal = GOAL.value.trim();
  // `null` and not the unchanged text: the write path merges a body three ways,
  // and sending one nobody edited makes every roster save a body edit too.
  if (!(await put(fields, NOTES_DIRTY ? NOTES.value : null))) return false;
  ROSTER_DIRTY = false;
  NOTES_DIRTY = false;
  GOAL_DIRTY = false;
  return true;
}

if (NOTES) NOTES.oninput = () => {
  NOTES_DIRTY = NOTES.value !== NOTES_WERE;
  mark();
};

if (GOAL) GOAL.oninput = () => {
  GOAL_DIRTY = GOAL.value !== GOAL_WAS;
  mark();
};

// Ticking is a write to the RECORD, not to the cycle: `cycle` lives on the thing
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
const PENDING = new Map();   // record id -> {field: value}

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
  let edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);
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
  if (!PENDING.size && !ROSTER_DIRTY && !NOTES_DIRTY && !GOAL_DIRTY) return;
  event.preventDefault();
  event.returnValue = '';
});

async function flush(quiet) {
  if (!PENDING.size && !ROSTER_DIRTY && !NOTES_DIRTY && !GOAL_DIRTY) return true;
  SAVE.disabled = true;
  // Counted in edits, the unit `mark()` counts, and not in commits. Two fields on
  // one row is one write, so counting writes said "2 unsaved changes" and then
  // "Saved 1 change" about the same two edits — and a save you have to reconcile
  // against its own receipt is a save you do not believe.
  let saved = 0;
  if (ROSTER_DIRTY || NOTES_DIRTY || GOAL_DIRTY) {
    // Counted before the save clears the flags. The roster and the notes go in
    // one PUT and are two edits to `mark()`, so a receipt saying "1" after
    // changing both is the reconciliation problem this counter exists to avoid.
    const edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);
    if (!(await saveSetup())) { mark(); return false; }
    saved += edits;
  }
  // One record per commit, each against the commit the last one returned: a
  // batch that fails half way is still a readable history rather than one commit
  // nobody can unpick.
  for (const [id, fields] of [...PENDING]) {
    dispatchEvent(new Event('openproj:writing'));
    let committed = null;
    try {
      const response = await fetch(`/api/record/${encodeURIComponent(id)}`, {
        method: 'PATCH', headers: {'content-type': 'application/json'},
        body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
      });
      const answer = await answerOf(response);
      if (!response.ok) {
        say(`${id}: ${refusal(answer, response.status)}`
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
    forThisTab.set(RECEIPT, receipt);   // and a browser that refuses still saved
    location.reload();
  }
};

// Every two minutes, so a dropped connection or a closed laptop costs the last
// two minutes rather than the whole meeting. Quiet when there is nothing to say.
setInterval(() => {
  if (PENDING.size || ROSTER_DIRTY || NOTES_DIRTY) flush(true);
}, 120000);

// Every editable cell is an input already: a betting table is filled in, not
// inspected, and a double-click to reach a field somebody is about to type in is
// a step that only exists because the table also had to be readable.
// No attachSuggest here: these inputs are in the served markup, so the combobox
// script's own sweep — which runs above this block — has already attached the
// widget. Attaching again put a second widget on the same box: two lists opened
// together, and one Enter picked a name from each — choosing `bo` wrote
// `bo, ann, `.
for (const input of document.querySelectorAll('#bets input.live')) {
  let was = input.value;
  // Saving on blur alone is not safe when the field is already an input: the
  // browser restores form values across a reload, autofills, and the picker
  // rewrites the field to add a separator — none of which is a person deciding
  // something. A cell is only staged if somebody typed in it or picked from it,
  // which is what an `input` event means.
  let edited = false;
  input.addEventListener('input', () => { edited = true; });
  input.onkeydown = event => {
    // The suggestion widget answers first — the combobox sweep attached its
    // listener to this input before this script ran — and a key it consumed is
    // not this cell's to act on too. This is the third copy of the gate panel's
    // collision: without the mark, one Escape closed the list AND reverted the
    // typing it was completing, and one Enter picked a name AND blurred,
    // staging the list half-finished. No stopPropagation, unlike the cell
    // editor's guard: nothing above a betting cell answers either key.
    if (event.defaultPrevented) return;
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

// The two closed-set cells, staged the same way and with far less to guard.
// There is no typing to revert, no suggestion widget to lose a key to and no
// coercion to get wrong: a `<select>`'s value is always one of the rungs the page
// drew, and `change` fires only when somebody picked. What it shares with the
// boxes above is the thing that matters — nothing is written here, it is staged,
// and the one Save button on this page commits it with everything else.
for (const pick of document.querySelectorAll('#bets select.pick')) {
  let was = pick.value;
  pick.onchange = () => {
    if (pick.value === was) return;
    was = pick.value;
    // The rung's own colour travels with the picker, so the status column still
    // reads DOWN at a glance — which is the whole reason it was a chip and not a
    // word. Rewritten on change rather than left on the value it was drawn with:
    // a picker showing `Done` in the ready tint is worse than an uncoloured one,
    // because it is confidently wrong. The class list is rebuilt from `st-`
    // rather than toggled, so nothing has to know which rung it was.
    if (pick.dataset.field === 'status') {
      pick.className = [...pick.classList].filter(one => !one.startsWith('st-')).join(' ')
        + ' st-' + pick.value;
    }
    pend(pick.closest('tr').dataset.id, pick.dataset.field, pick.value);
  };
}

// Capacity is what a rate BUYS, so it has to move while the rate is being typed.
// Left to the next page load, the number somebody is setting is invisible at the
// moment they are setting it — which is most of the moment that matters.
function recount() {
  const build = BUILD_WEEKS;
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
  if (event.target.matches('input.rate')) recount();
  if (event.target.closest('#setup') || event.target.matches('input.rate')) dirty();
  // A date changes how many working weeks the cycle builds for, and that answer
  // needs the holidays — which this page does not have and should not grow a
  // second copy of. The column says it is out of date rather than showing a
  // number computed by a rule that is only nearly the server's.
  if (event.target.matches('#setup input[type=date]')) {
    const note = document.getElementById('stale');
    if (note) note.hidden = false;
  }
});

function dirty() {
  ROSTER_DIRTY = true;
  mark();
}

// The roster is edited in the page and written by Save, so adding somebody and
// setting their availability is one decision and one commit rather than two.
const HELD = {{ c.held|tojson }};
// Already carrying the widget: the combobox sweep reached this box too, and the
// second attachSuggest here doubled it the same way the betting cells' did.
const JOINING = document.getElementById('joining');

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
  const who = esc(login);
  return `<td class="dropcell"><button type="button" class="drop"`
    + ` title="Take ${who} out of this cycle"`
    + ` aria-label="Take ${who} out of this cycle">&#128465;</button>`
    + `<span class="confirm" hidden>out?<button type="button" class="yes">yes</button>`
    + `<button type="button" class="no">no</button></span></td>`;
}

document.getElementById('add').onclick = () => {
  const login = JOINING.value.trim().replace(/,$/, '');
  if (!login) return;
  // CSS.escape, the way `refusals()` already does it on the detail page. A login
  // is typed, and a quote or a bracket in one made this a selector that is not a
  // selector: the browser threw inside the handler and the Add button stopped
  // working — for every later click too, with nothing on screen saying why.
  if (document.querySelector(`#roster tr[data-login="${CSS.escape(login)}"]`)) {
    say(`${login} is already in this cycle`);
    return;
  }
  const row = document.createElement('tr');
  row.dataset.login = login;
  // Somebody added to the cycle may already be bet into it — that is exactly why
  // the page named them below the table. Their load comes with them.
  row.dataset.held = (HELD[login] || 0);
  // A login is typed here rather than read out of the plan, which makes this the
  // one injection on these pages that starts as a person doing it to themselves
  // — and ends as everybody's, because Save writes the name into the cycle file
  // and the roster is drawn from that file for every reader afterwards.
  const who = esc(login);
  row.innerHTML = dropCell(login)
    + `<td>${who}</td>`
    + `<td><input class="field rate" data-login="${who}" value="1.0"`
    + ` aria-label="${who} availability" autocomplete="off"></td>`
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

// --- Finding a row, and putting the big ones together ------------------------
//
// A betting table is a conversation: somebody says a name and everybody looks
// for it. With thirty candidates that is a scroll and a squint, and the table
// already has every word in it.
//
// **Rows are hidden and never removed.** Each row carries a checkbox that is
// part of the form, and a row taken out of the DOM is a bet that cannot be made
// and, worse, a tick that would not be saved. `hidden` leaves the form intact
// and the search is a lens rather than an edit.
const BETS = document.getElementById('bets');
const BETFIND = document.getElementById('betfind');
const BETNONE = document.getElementById('betnone');

function betRows() { return [...BETS.tBodies[0].rows]; }

function betSearch() {
  const term = BETFIND.value.trim().toLowerCase();
  let shown = 0;
  for (const row of betRows()) {
    // The whole row's text, which is what somebody means by "search": a title,
    // an owner, a kind and an id are all things said out loud at a betting
    // table. `textContent` misses what is inside the editable cells, whose
    // value lives on the input rather than in the tree, so those are asked
    // separately.
    const typed = [...row.querySelectorAll('input')]
      .filter(box => box.type !== 'checkbox').map(box => box.value).join(' ');
    const hit = !term || (row.textContent + ' ' + typed).toLowerCase().includes(term);
    row.hidden = !hit;
    if (hit) shown++;
  }
  // Empty must not look like broken. A search matching nothing is the commonest
  // way to arrive at an empty table, and it is a different sentence from "this
  // cycle has nothing to bet on" — with the control that gets you out of it.
  BETNONE.hidden = shown > 0 || !term;
  if (!BETNONE.hidden) document.getElementById('betterm').textContent = BETFIND.value.trim();
  say(term ? `${shown} of ${betRows().length} shown` : '');
}

BETFIND.addEventListener('input', betSearch);
document.getElementById('betclear').onclick = () => {
  BETFIND.value = '';
  betSearch();
  BETFIND.focus();
};

// Sorting, by the text a reader can see. `appetite` is the one column where
// that is a number and sorting it as a string would put 10 before 2 — so a cell
// that parses as one is compared as one, and everything else falls back to a
// locale compare. One rule, decided per PAIR rather than per column, so a column
// holding "3" and "assumed" still orders sensibly instead of throwing.
function betCell(row, at) {
  const cell = row.cells[at];
  if (!cell) return '';
  // A LADDER sorts by rung, not by spelling. `selectedIndex` is the rung,
  // because the page draws both lists in the order `STATUSES` and `PRIORITIES`
  // declare them — so status goes thinking, shaping, ready, in progress, done,
  // shelved, and priority goes very high to very low, which is the order every
  // other view in the app puts them in.
  //
  // It also fixes the status column, which is older than this: sorting it by
  // what the chip said gave `Done, In progress, Ready, Shaping` — alphabetical
  // order over a ladder, which is an order nobody at a betting table wants.
  //
  // Padded, so `parseFloat` in `betSort` takes this branch and compares numbers.
  // Returning the raw index would work by luck until a ladder grew a tenth rung.
  const pick = cell.querySelector('select');
  if (pick) return String(pick.selectedIndex).padStart(3, '0');
  const box = cell.querySelector('input:not([type=checkbox])');
  return (box ? box.value : cell.textContent).trim();
}

function betSort(at, descending) {
  const rows = betRows();
  rows.sort((a, b) => {
    const one = betCell(a, at), two = betCell(b, at);
    const x = parseFloat(one), y = parseFloat(two);
    const by = Number.isFinite(x) && Number.isFinite(y)
      ? x - y : one.localeCompare(two, undefined, {numeric: true});
    return descending ? -by : by;
  });
  // Re-appending a row MOVES it, so the checkboxes and their state travel with
  // it. This is the whole reason the sort is done on the live rows rather than
  // by re-rendering the table from data: the data is in the form.
  for (const row of rows) BETS.tBodies[0].append(row);
}

// --- The table follows the plan while the table is going on ------------------
//
// jcanton, 2026-08-25: "can the cycle page autoreload the betting table at
// regular intervals in case people have added / modified records while the
// betting table is going on? (which happens regularly)". It does happen: the
// meeting is where somebody shapes the pitch that has just been argued for, and
// until now the room was looking at a list rendered before they started.
//
// The shell already answers a plan change with a "reload" banner, which is right
// on a reading page and wrong here for the same reason it was wrong on the deck:
// this page is a FORM, and a reload throws away every tick nobody has saved yet.
//
// **So it swaps the rows, and only when swapping them cannot cost anything.**
// Three refusals, and each is a way somebody loses work:
//
//   - not while anything on this page is unsaved, because a swap would drop
//     ticks that are the whole point of the meeting;
//   - not while the focus is inside the table, because the row under somebody's
//     cursor moving mid-sentence is worse than a stale row;
//   - not while a save is in flight, because the answer is about to move again.
//
// What it costs is that a busy table stops updating until somebody saves, which
// is the right way round: the unsaved ticks are the thing that cannot be got
// back, and the sentence below says so rather than leaving it silent.
let betHead = null;
let betSwapping = false;
const BET_POLL_MS = 30000;

// The same four things `beforeunload` above refuses to leave over, asked as one
// question. Written as a call to that state rather than as a fifth copy of the
// list: a swap and a tab close are the two ways unsaved work here is lost, and
// they must not be able to disagree about what "unsaved" means.
function betBusy() {
  if (PENDING.size || ROSTER_DIRTY || NOTES_DIRTY || GOAL_DIRTY) return 'unsaved changes';
  if (BETS.contains(document.activeElement)) return 'the table has focus';
  return '';
}

async function betRefresh() {
  if (betSwapping) return;
  betSwapping = true;
  try {
    const answer = await fetch(location.pathname + location.search,
                              {headers: {'accept': 'text/html'}});
    if (!answer.ok) return;
    const fresh = new DOMParser().parseFromString(await answer.text(), 'text/html');
    const rows = fresh.querySelector('#bets tbody');
    if (!rows) return;
    // Which rows were ticked, by id, so the swap cannot lose a decision that
    // has been made and saved — and so a row that arrives already bet in comes
    // back ticked rather than blank.
    BETS.tBodies[0].replaceWith(rows);
    betSearch();
    say('The betting table was refreshed — somebody changed the plan');
  } finally {
    betSwapping = false;
  }
}

async function betPoll() {
  try {
    const health = await (await fetch('/api/health')).json();
    if (betHead !== null && health.head !== betHead) {
      const why = betBusy();
      if (why) {
        // Said, not swallowed. A table that has quietly stopped following the
        // plan looks exactly like a plan that has not changed.
        say(`The plan changed — this table will refresh once ${why} is cleared`);
      } else {
        await betRefresh();
      }
    }
    betHead = health.head;
  } catch { /* a moment offline is not news at a betting table */ }
}

// A poll and not the event stream, for the reason the deck's own refresh writes
// down: Cloud Run recycles the stream every 300s with no replay, so an event
// proves a change and its absence proves nothing. Thirty seconds, because this
// is a meeting and a minute is a long time to argue about a stale row.
setInterval(betPoll, BET_POLL_MS);
betPoll();

for (const head of BETS.querySelectorAll('th[data-sort]')) {
  head.querySelector('.sorter').onclick = () => {
    const at = Number(head.dataset.sort);
    const was = head.getAttribute('aria-sort');
    const descending = was === 'ascending';
    for (const other of BETS.querySelectorAll('th[data-sort]'))
      other.setAttribute('aria-sort', 'none');
    head.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    betSort(at, descending);
    say(`Sorted by ${head.textContent.trim()}, ${descending ? 'descending' : 'ascending'}`);
  };
}
</script>
{% endif %}
"""

_CYCLE_STYLE = """
/* The printed date, hidden wherever the box that edits it is on screen. This
   page draws read value and control together — it has no editing mode to
   switch between — so with the `.iso` echo gone the row still read
   `25.08.2026 [25.08.2026]`. `:has()` asks the question the layout actually
   poses ("is there a control in this cell?") rather than encoding today's
   answer, so a row that gains or loses its box stays right. */
#setup dd:has(input[type="date"]) > .read { display: none; }

/* The betting table's search, on the line with the sentence that describes the
   table rather than in a bar above the heading: it belongs to this table. The
   box first, because it is the control and the sentence is the caption. */
.betsearch { display: flex; align-items: baseline; gap: .6rem; }
.betsearch input { flex: none; width: 12rem; }
.betsearch > span { flex: 1 1 auto; min-width: 0; }
/* A column head that sorts. It is a real button so a keyboard can reach it, and
   it wears the head's own type so the row still reads as a header row. */
#bets th .sorter {
  font: inherit; color: inherit; background: none; border: 0; padding: 0;
  cursor: pointer; text-transform: inherit; letter-spacing: inherit;
}
#bets th .sorter:hover { color: var(--accent); }
/* The arrows as CHARACTERS and not as CSS escapes. `_CYCLE_STYLE` is a Python
   string that is not raw, so `\2191` never reaches the browser as one: Python
   reads `\21` as an octal escape first and the declaration arrives as
   `content: " \11 93"`, which Chrome renders as the literal text "93" beside
   every column head. `shell.py` carries a comment about this exact trap, written
   the last time somebody put a backslash in one of these blocks. */
#bets th[aria-sort="ascending"] .sorter::after { content: " ↑"; }
#bets th[aria-sort="descending"] .sorter::after { content: " ↓"; }

/* .commitbar, #unsaved and #save are the shell's: the cycle page was the first
   to need a bar that says whether the page is saved, and then the detail page
   and the create page needed the same one. */
/* A destructive control asks before it acts, and the question replaces the
   glyph rather than appearing beside it, so the row does not jump. */
.confirm { font-size: 12px; color: var(--warn); }
td .confirm { white-space: nowrap; }
.confirm button { font-size: 12px; margin-left: .25rem; padding: 0 .35rem; }
.confirm button.yes { border-color: var(--danger); color: var(--danger); }
/* The notes box, at the width of the prose it holds rather than the width of the
   betting table beside it. */
textarea.notes { display: block; width: 100%; max-width: 52rem; box-sizing: border-box;
                 font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                 font-size: 13px; line-height: 1.55; padding: .4rem;
                 border: 1px solid var(--line-strong); border-radius: 3px;
                 background: var(--surface); color: inherit; resize: vertical; }
/* The goal box wears the notes' shape and not its typeface: notes are markdown
   and read better in mono, a goal is a sentence somebody says out loud. Wider
   measure than prose wants, because it sits above a table and a goal that wraps
   three times stops being the one line the room agreed on. */
/* No rule above the cycle's prose. `.doc`'s border-top comes from _DETAIL_STYLE,
   where it separates a shaping document from the facts pane above it; here the
   block sits directly under its own `<h2>`, so the same rule drew a stray line
   between a heading and the text it heads. Unscoped and relying on order: this
   sheet is concatenated after _DETAIL_STYLE and is loaded by the two cycle pages
   only, so there is no third page for it to reach. */
.doc { border-top: 0; padding-top: 0; }
textarea.goal { display: block; width: 100%; max-width: 52rem; box-sizing: border-box;
                font: inherit; font-size: 15px; line-height: 1.5; padding: .4rem;
                border: 1px solid var(--line-strong); border-radius: 3px;
                background: var(--surface); color: inherit; resize: vertical; }
p.goal.read { font-size: 15px; max-width: 52rem; margin: 0 0 1rem; }
.goalbar { margin: 0 0 1rem; }
#setup .field, table.load .field { display: inline-block; }
#setup .field { width: 12rem; }
#setup .read, table.load .read { display: none; }
/* The roster and the delivered list wear one dress, said once. They are the two
   plain tables on this page — the betting table below is a grid of controls and
   has its own block — and writing the second one out again is how two tables
   that are meant to read alike stop doing so a rule at a time. `.delivered` is a
   class nothing else on any page carries, so adding it here beats nothing that
   was not already beaten: it inherits these three rules and no others, which is
   why `table.load .field` and `table.load .read` below stay as they are — a
   delivered row has no control in it to hide a printed value behind. */
table.load, table.delivered { border-collapse: collapse; font-size: 13px;
                              margin: .5rem 0 1rem; }
table.load th, table.load td, table.delivered th, table.delivered td {
  border-bottom: 1px solid var(--line); padding: .3rem .6rem; text-align: left;
}
table.load th, table.delivered th { color: var(--muted); font-weight: 400;
                                    font-size: 11px; text-transform: uppercase;
                                    letter-spacing: .04em; }
/* A bet and a date are figures read down a column, and a column of figures that
   are not the same width per digit reads as a ragged edge rather than as a
   comparison. Not `.derived`, which carries these numerals already and would
   have been the cheap way to get them: that class means "computed, and typing
   over it would change nothing", and both of these are fields somebody stored.
   The overrun beside the date is the one derived thing in the table and it
   keeps `.overrun`, the detail page's own class. */
table.delivered td.num { font-variant-numeric: tabular-nums; }
/* The rule §5 sketches between what was planned and what arrived. Above the
   section and not below it, because what it separates is the two readings of one
   cycle's weeks: everything from here down happened, and everything above it is
   still a forecast. `#create`'s rule on the cycles index is the same device for
   the same reason, and the heading loses its own top margin so the distance from
   the rule is this rule's to set. */
#delivered { border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1rem; }
#delivered h2 { margin-top: 0; }
tr.over td { color: var(--danger); }
/* What the bet beside it does not count. Muted rather than warning-coloured: an
   unshaped bet with no appetite is the ordinary state of a cycle's early weeks
   and not a fault, and `tr.over td` above already owns the red in this table. */
.unsized { color: var(--muted); }
input.rate { width: 4rem; }
#bets input.live { font: inherit; font-size: 13px; width: 5rem;
                   background: var(--surface); color: inherit;
                   border: 1px solid transparent; border-radius: 3px; padding: .1rem .3rem;
                   /* A box with no border that cuts its value mid-word — "…jcanto"
                      — reads as broken text rather than as a field. An input
                      clips its overflow and says nothing about it; this is the
                      one thing that does. */
                   text-overflow: ellipsis; }
/* As wide as the column it is in, not 11rem regardless. The column is sized by
   the header and the widest name in it and there was room to spare beside every
   one of these boxes, so a fixed width was cutting values the table had already
   made room for. `min-width` keeps the column from collapsing to the width of
   the word above it, and `border-box` keeps the padding inside the cell. */
#bets input.live.wide { width: 100%; min-width: 11rem; box-sizing: border-box; }
#bets input.live:hover { border-color: var(--line); }
/* The two closed-set cells. Dressed as the boxes beside them rather than as the
   browser's own control: a betting table is one grid of things you are filling
   in, and a native select among five bordered inputs reads as a different kind
   of thing that must therefore do a different kind of job.
   `max-width: 100%` because a status word plus its glyph is wider than the
   column header, and the two frozen columns are not this table's problem —
   without it the picker sets the column width and `title` pays for it. */
#bets select.pick {
  font: inherit; font-size: 13px; max-width: 100%;
  color: inherit; background: var(--bg);
  border: 1px solid var(--surface-2); border-radius: 2px; padding: .1rem .15rem;
}
/* The rung's colour comes from the shell, where `select.pick.st-X` is generated
   beside `.chip.st-X` from the one loop over `STATUSES` — see the note there.
   Nothing about the ladder is written in this file. */
#bets select.pick:hover { border-color: var(--line); }
#bets select.pick:focus { border-color: var(--accent); }
/* The border is the hover affordance, not the focus one. Suppressing the outline
   here left the only keyboard-reachable cell on the page with nothing to say it
   had focus; the shell's :focus-visible ring draws it now. */
#bets input.live:focus { border-color: var(--accent); }
/* No `#bets td { position: relative }`. It was here to anchor the suggestion
   popup the assignees and reviewers boxes open, and the popup is parked on the
   body now. Left in, it is a rule with nothing to do and a trap for whoever
   writes the next one: the identical rule on the table's cells is what stole
   `position: sticky` from the frozen title column. */
button.drop { border: none; background: none; cursor: pointer; padding: 0 .2rem;
              color: var(--muted); font-size: 13px; line-height: 1; }
button.drop:hover { color: var(--danger); }
#joining { font: inherit; font-size: 13px; width: 10rem; }
/* **The two wide tables scroll themselves, not the document.** The roster is
   seven columns and the betting table is eight, and both were written down as
   "eight columns fit a screen; the page scrolls" — which was measured against a
   screen. At a 390px viewport the roster ran to 617px and the betting table to
   865, and what scrolled was the whole page: every heading, the prose, the Save
   bar and the notes box slid sideways together, so reading one number in the
   `load` column moved the entire cycle out from under the reader.

   A wrapper and not `display: block` on the table itself, which is the trick
   this replaces the need for: a block-level table stops being a table box, and
   these two are `border-collapse` with a sticky `thead` and measured column
   widths. The box goes around it instead, and the table inside is untouched.

   No `max-height` and therefore not `.table-scroll`, which carries one. That
   class is for the ONE box a view fills to the window; these two sit in the
   middle of a document that scrolls past them, and capping their height would
   put a second vertical scroller inside a page that already has one.

   Every width, not only below 40rem. The tables are as wide as the plan makes
   them — a long login or a long title widens the roster on any screen — so a
   rule that only applies to phones is a rule that lets the desktop page scroll
   sideways the day somebody joins with a long name. */
.sideways { overflow-x: auto; overscroll-behavior-x: contain; }
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
/* The one control on this page that creates something, so it is the one drawn in
   the accent. The shape is the default's; the colour is what is its own. */
#start { padding: .25rem .8rem; border-color: var(--accent); color: var(--accent); }
#confirm { margin: .6rem 0 0; font-size: 13px; }
"""

_CYCLES = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Cycles</h1>
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
    <p class="window">{% if c.recorded %}{{ on(c.starts_on) }} → builds until
      {{ on(c.builds_until) }}{% elif c.starts_on %}{{ on(c.starts_on) }} → {{ on(c.ends_on) }}
      {% else %}no dates{% endif %}
      · {{ c.people }} {{ 'person' if c.people == 1 else 'people' }}</p>
    {#- The count of what the weeks leave out, on both readings of the card.
        Neither number moves when somebody shapes one of those records and gives
        it an appetite — the weeks go up and the count goes down — which is the
        pair a room needs in front of it, rather than a total that grows for
        reasons the page never mentioned. -#}
    {% if c.recorded %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> of
      <b class="num">{{ '%.1f'|format(c.capacity) }}</b> weeks bet{% if c.unsized %}
      <span class="unsized">· {{ c.unsized }} not sized</span>{% endif %}</p>
    <span class="bar"><span style="width: {{ c.percent }}%"></span></span>
    {% else %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> weeks bet against
      no roster{% if c.unsized %}
      <span class="unsized">· {{ c.unsized }} not sized</span>{% endif %}</p>
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
  <p class="editbar">
    <label class="facet">number
      <input id="number" type="number" value="{{ next.number }}" min="0" max="9999"></label>
    <label class="facet">betting table
      <input id="starts" type="date" value="{{ next.starts_on }}"></label>
    <label class="facet">review meeting
      <input id="reviews" type="date" value="{{ next.reviews_on }}"></label>
    {#- On the same line as the three boxes it acts on. It had a row to itself,
        which reads as a second step and is not one: with the goal box gone this
        form is three fields and the button that commits them, and `.editbar`
        already wraps when the window is too narrow to hold them. -#}
    <button type="button" id="start">Start it</button>
    <span id="state" role="status"></span>
    <input type="hidden" id="base" value="{{ base_commit }}">
  </p>
  {#- No goal box here. It was asked on this form for one round and belongs on
      the cycle's own page instead: this form's whole job is to bring a record
      into existence, and the goal is then edited where it is read, above the
      betting table it is about. Two places to write one field is one place too
      many. -#}
  <p class="confirm" id="confirm" hidden>Start cycle <b id="confirm-number"></b> on
    <b id="confirm-starts"></b>, <b id="confirm-length"></b>, with
    <b id="confirm-people"></b>? This commits a cycle record.
    <button type="button" id="yes">Yes, start it</button>
    <button type="button" id="no">Cancel</button></p>
</section>
<script>
const ROSTER = {{ roster|tojson }};
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
  // Measured from the two dates in front of you, and not from `#build` and
  // `#cooldown` — two inputs this form stopped having when it started asking for
  // the review date instead. `field()` answered null for both, reading `.value`
  // off null threw, and the throw happened before `CONFIRM.hidden = false`: so
  // "Start it" did nothing at all, silently, and no cycle could be started from
  // the page at all. The confirmation is the only thing between a click and a
  // commit, which is why it is computed from what is on screen.
  const weeks = Math.round(
    (Date.parse(field('reviews').value) - Date.parse(field('starts').value))
    / (7 * 24 * 60 * 60 * 1000));
  field('confirm-length').textContent = Number.isFinite(weeks) && weeks > 0
    ? `${weeks} week${weeks === 1 ? '' : 's'} to the review meeting`
    : 'dates not set';
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
        // As typed, the way the cycle page sends them: a coerced NaN arrives as
        // null and the refusal can only say "blank" about a box with a word in it.
        fields: {
          starts_on: field('starts').value,
          reviews_on: field('reviews').value,
          availability: ROSTER,
        },
        // null, not "": the write path treats a null body as "leave it alone"
        // and an empty string as "set it to empty", and those differ the day
        // somebody starts a cycle whose record already exists.
        body: null,
      }),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      announce(refusal(answer, response.status));
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
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">People</h1>
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
{{ facets }}
<div id="summary"><span id="shown" class="num">{{ people|length }}</span>
  of {{ people|length }} people</div>
{#- One table for the whole page. Fifteen tables meant fifteen headers, and a
    column of statuses that started at a different x for every person cannot be
    read down. The person is a group row inside it instead of a heading above a
    table of their own. -#}
{#- The same wrapper the Records list and the Table page carry, and for the same
    three reasons at once: the table scrolls inside it, everything above it — the
    nav, the search, the filters, the summary — stays where it is, and the footer
    stays at the foot of the window. This page had none, so it scrolled the whole
    document and took all four with it. jcanton, 2026-08-25, on seeing Records
    beside it: "people doesn't even have the nav and search pinned!"

    `data-fills` is what tells the shell this is the box to give the window's
    remaining height to; `--room` does the measuring. -#}
<div class="table-scroll" data-fills>
<table id="roles" class="unfitted">
  <thead><tr><th scope="col">role</th><th scope="col">record</th><th scope="col">kind</th>
    <th scope="col">status</th><th scope="col">scheduled</th></tr></thead>
  {% for person in people %}
  <tbody class="person" data-login="{{ person.login }}">
    <tr class="group{{ ' over' if person.over else '' }}">
      <th colspan="5" scope="colgroup"><div class="groupline">
        {#- The person's own mark. A button for exactly one person on the page —
            whoever is signed in — and a plain span for everybody else, because
            the only icon anybody may set here is their own.

            The button and its list are wrapped together because the list is
            positioned against the wrapper: the group line wraps, so the button
            has no fixed place in it, and a popup anchored to anything else opens
            somewhere the button is not. -#}
        {%- if person.mine %}
        <span class="pickwrap">
        <button type="button" id="pick" class="avatar pick{{ ' unset' if not person.art else '' }}"
                aria-haspopup="listbox" aria-expanded="false" aria-controls="picker"
                aria-label="Your icon" title="Your icon">{{ person.art }}</button>
        {#- A listbox and not a `<select>`: a native option cannot hold an SVG,
            and picking your own mark by reading the word "fox" is not the
            feature. Every row carries the drawing AND the name, because the name
            is what is stored and what a refusal will say back.

            "No icon" first, and not last where the old strip's clear button was:
            it is the way out, and a way out you have to scroll twenty-four rows
            to reach is the hardest row on the list to find.

            `aria-selected` marks the one that is stored, which is a different
            fact from the one the arrow keys are on — that one is named by
            `aria-activedescendant` and drawn by `.on`. The suggestion combobox
            conflates the two, and is right to: it has no stored value to mark. -#}
        <ul id="picker" class="picker" role="listbox" aria-label="Your icon" tabindex="-1" hidden>
          <li id="pick-none" class="option" role="option" data-icon=""
              aria-selected="{{ 'true' if not person.icon else 'false' }}"><span
              class="art"></span>No icon</li>
          {% for one in icons %}
          <li id="pick-{{ one.name }}" class="option" role="option" data-icon="{{ one.name }}"
              aria-selected="{{ 'true' if one.name == person.icon else 'false' }}"><span
              class="art">{{ one.art }}</span>{{ one.name }}</li>
          {%- endfor %}
        </ul>
        </span>
        {%- elif person.art %}
        <span class="avatar">{{ person.art }}</span>
        {%- endif %}
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
        {%- elif load.cycle is not none and not person.unsized %}
        <span class="load none">nothing bet in cycle {{ load.cycle }}</span>
        {%- endif %}
        {#- What the weeks beside it do not count. Its own item rather than a
            clause inside the load span, because it has to sit beside all four of
            those branches — including the last, which is why that one now asks:
            "nothing bet" is false about somebody holding three records nobody
            has put an appetite on, and it was the sentence they got the moment
            the default stopped inventing weeks for them. -#}
        {%- if person.unsized %}
        <span class="unsized">{{ person.unsized }} not sized</span>
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
        {%- if person.mine %}
        {#- Where a refusal is read. `announce` writes into `#state` when a page
            has one and into the shell's screen-reader region when it does not,
            and this page had none — so the first version of this feature failed
            silently for everybody who could see: the button did nothing, and the
            only account of why went to a region carrying `.sr-only`, which is
            `position: absolute; clip-path: inset(50%)`.

            A line of its own at the end of the group line, and drawn only where
            the button is. Not at the top of the page: the filter hides a whole
            person's `tbody` at once, so a status line up there would be on screen
            when the control it is about is not, and gone in exactly the case this
            exists for. Anybody who can press the button can see this, because it
            is two centimetres under their hand rather than at the far end of a
            row that is a metre wide on this table. It stays in the flow of the
            group line now that the list floats: a refusal is read after the list
            has closed over it, and a message inside a popup is a message that
            leaves with the popup. -#}
        <span id="state" role="status"></span>
        {%- endif %}
      </div></th>
    </tr>
    {% for row in person.rows %}
    <tr data-role="{{ row.role }}" data-kind="{{ row.kind }}" data-status="{{ row.status }}"
        data-text="{{ row.search }}">
      <td class="role">{{ row.role }}</td>
      <td><a href="{{ links.record }}{{ row.id }}">{{ row.title }}</a></td>
      <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
      <td><span class="chip {{ status_class(row.status) }}">{{ row.status|human }}</span></td>
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
</div>
{{ filters }}
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
  // `getAll` and OR within a field, which is what the bar can now ask and what
  // `matches` and `apply_filters` have always answered. With `get` this page
  // honoured the first value and ignored the rest in silence — a control that
  // sets two and a page that reads one is the same divergence as the search
  // blob, on the same afternoon it was fixed.
  const want = ['role', 'kind', 'status']
    .map(field => [field, params.getAll(field).filter(Boolean)])
    .filter(([, values]) => values.length);
  let visible = 0;
  for (const group of GROUPS) {
    const person = group.dataset.login.toLowerCase();
    let kept = 0;
    for (const row of group.querySelectorAll('tr[data-role]')) {
      const keep = want.every(([field, values]) => values.includes(row.dataset[field]))
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
{#- Only where there is a server to write to. A static export carries no picker,
    so shipping the script that drives one would put a `fetch` for a route that
    does not exist into a file opened over `file://` — dead code in the one copy
    of this plan that has to be readable with nothing else on the machine. -#}
{% if editable %}
<script>
// Picking your own icon. Both are absent for somebody who may write and is named
// nowhere in the plan: this page lists whoever holds work, so there is no row to
// hang a picker off for a person who holds none. Guarded rather than assumed,
// because that reader gets this script like everybody else who may write.
const PICK = document.getElementById('pick');
const PICKER = document.getElementById('picker');

// One region for both sentences a write produces, told apart by colour rather
// than by having two places to look. `announce` picks `#state` on a page that
// has one — this page's is beside the button, and it is drawn only when the
// button is, so the message is where the hand already is.
// `report` and not `say`: two classic scripts on one page share one global
// scope, and `say` is already taken twice in this file.
function report(message, bad) {
  const state = document.getElementById('state');
  if (state) state.classList.toggle('bad', !!bad);
  announce(message);
}

async function chooseIcon(name) {
  // The whole request: one key, and the login is the server's own. There is
  // nothing here to name somebody else with, and nothing to name a file with
  // either — the path is `people/<your login>.md` and it is built on the server
  // from the session. See the endpoint.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/icon', {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({icon: name || null}),
    });
    // `answerOf` and not `.json()`: a refusal that arrives as plain text would
    // otherwise reject here and leave the picker open with nothing said.
    const answer = await answerOf(response);
    if (!response.ok) { report(refusal(answer, response.status), true); return false; }
    committed = answer.commit;
    return true;
  } finally {
    // Announced even when the write was refused, or the shell holds every later
    // event back and its banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// The rows, read once from the markup the server rendered. Not rebuilt here: the
// drawings are already in the page, and a script that assembled twenty-four
// `<svg>` strings would be a second copy of `_ICON_ART` in a template literal —
// an invariant written twice, which this codebase guards once or not at all.
const OPTIONS = PICKER ? [...PICKER.querySelectorAll('[role="option"]')] : [];
// Where the keyboard is, which is NOT which row is stored. `aria-selected` says
// what you have; this says what you are looking at, and the listbox says so with
// `aria-activedescendant` — the same arrangement the suggestion popup in this
// file uses to keep focus on the control while the highlight moves in the list.
// Named like this and not `at`, `highlight`, `choose`: two classic scripts on
// one page share one global scope, which is why `report` is not called `say`.
let AT_ROW = 0;

function highlightRow(next) {
  AT_ROW = (next + OPTIONS.length) % OPTIONS.length;
  OPTIONS.forEach((option, i) => option.classList.toggle('on', i === AT_ROW));
  PICKER.setAttribute('aria-activedescendant', OPTIONS[AT_ROW].id);
  // `block: 'nearest'`, or every move scrolls the list to centre the row and the
  // list appears to jump under a reader who pressed Down once.
  OPTIONS[AT_ROW].scrollIntoView({block: 'nearest'});
}

// `back` is whether closing should hand focus to the button. Escape and a choice
// both should — the button is where that person's hand is. Focus LEAVING the
// list must not, because it left for somewhere the reader chose, and dragging it
// back is the popup arguing with them.
function openPicker(open, back = true) {
  PICKER.hidden = !open;
  PICK.setAttribute('aria-expanded', String(open));
  if (open) {
    // Opened on the row that is already stored, so the first arrow press moves
    // from your own mark rather than from the top of a list of twenty-five.
    highlightRow(Math.max(0, OPTIONS.findIndex(o => o.getAttribute('aria-selected') === 'true')));
    PICKER.focus();
  } else if (back) {
    PICK.focus();
  }
}

async function chooseRow(option) {
  const name = option.dataset.icon;
  // The picker stays open on a refusal, with the reason beside it in `#state`:
  // closing it would leave a page that looks exactly like one where nothing
  // was pressed, which is the state this feature shipped in once already.
  if (!await chooseIcon(name)) return;
  // The drawing is moved, not rebuilt: the chosen row already holds the exact
  // markup the server would send back, so the new mark is a clone of a node this
  // page rendered rather than a string assembled from an answer. Nothing crosses
  // an escaping boundary, and the page does not have to reload to show what it
  // just saved.
  const art = option.querySelector('svg');
  PICK.replaceChildren(...(art ? [art.cloneNode(true)] : []));
  PICK.classList.toggle('unset', !art);
  // The list is open again one press later, and it has to open on what is now
  // stored rather than on what was stored when the page was rendered.
  OPTIONS.forEach(one => one.setAttribute('aria-selected', String(one === option)));
  openPicker(false);
  report(name ? `Your icon is now ${name}.` : 'Your icon is cleared.', false);
}

if (PICK && PICKER) {
  PICK.onclick = () => openPicker(PICKER.hidden);
  PICKER.addEventListener('keydown', event => {
    // The listbox keys, in the order somebody reaches for them. Escape closes,
    // because a popup that only closes by pressing the thing that opened it is a
    // trap for anybody who got here with the keyboard; Home and End because this
    // list is long enough to scroll and "No icon" is at the top of it.
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      highlightRow(AT_ROW + (event.key === 'ArrowDown' ? 1 : -1));
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      highlightRow(event.key === 'Home' ? 0 : OPTIONS.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      // Space as well as Enter, and both prevented: Space on a focused element
      // scrolls the page, so a listbox that ignored it would answer the second
      // most obvious key by scrolling the list out from under the reader.
      event.preventDefault();
      chooseRow(OPTIONS[AT_ROW]);
    } else if (event.key === 'Escape') {
      openPicker(false);
    }
  });
  PICKER.addEventListener('click', event => {
    const option = event.target.closest('[role="option"]');
    if (option) chooseRow(option);
  });
  // Clicking anywhere else closes it. `relatedTarget` is the button when the
  // button is what was clicked, and closing here as well would let the click
  // that follows reopen a list the reader was shutting.
  PICKER.addEventListener('focusout', event => {
    if (!PICKER.contains(event.relatedTarget) && event.relatedTarget !== PICK) {
      openPicker(false, false);
    }
  });
}
</script>
{% endif %}
"""

# `_SCROLL_STYLE` first, which is what makes the wrapper above actually a
# scroller: `.table-scroll { overflow: auto; max-height: var(--room) }` and the
# frozen header row live there, and this page did not inline them. The Records
# list and the Table page both open with the same line — the class was on the
# markup here and dressed by nothing, which is a wrapper that scrolls the
# document instead of itself.
_PEOPLE_STYLE = (
    _SCROLL_STYLE
    + """
.hint { max-width: 46rem; font-size: 13px; }
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
tr.group > th { font-weight: 400; background: var(--surface-2); }
/* Air above each person, so a name does not begin on the line the previous
   person's last row ended on. Space and not a rule: every row here already ends
   in a hairline and the group row already has a ground of its own, and a third
   boundary drawn between two things that are each already bounded is noise. It
   is a thick border in the page's own colour because the table is collapsed —
   a collapsed border resolves to the widest of the two it joins, so this eats
   the row-hairline above it and leaves a clean gap rather than a gap with a line
   in it. The sibling combinator and not `:first-of-type`: the gap belongs
   *between* people, so the first group must not open with one. */
tbody.person + tbody.person > tr.group > th { border-top: .7rem solid var(--bg); }
.groupline { display: flex; flex-wrap: wrap; align-items: baseline; gap: .15rem .75rem; }
.who { font-size: 15px; font-weight: 650; }
.load { color: var(--muted); font-size: 12px; }
.load b { color: var(--fg); font-size: 13px; font-weight: 600; }
/* The number that says the person is over, in the colour that says so. The bar
   beside it turns with the row through the shell's `.over` rule. */
tr.group.over .load b.held { color: var(--danger); }
/* Muted, and deliberately not the warning colour beside it: an unshaped bet
   carries no appetite by design, and `.load.stranger` below is about somebody
   being bet work in a cycle they are not in, which is a fault. */
.unsized { color: var(--muted); font-size: 12px; }
.load.stranger { color: var(--warn); }
.load.stranger b { color: var(--warn); }
.elsewhere { color: var(--muted); font-size: 12px; }
.tally { color: var(--muted); font-size: 12px; margin-left: auto; }
/* Muted and not accent: the accent is what a link is on every other page, and a
   column of teal words beside a column of teal links reads as twelve dead links. */
td.role { color: var(--muted); font-size: 12px; text-transform: uppercase;
          letter-spacing: .04em; white-space: nowrap; }
/* The person's mark, at the size of the name beside it and in the same ink. Not
   allowed to shrink: the group line wraps, and an icon that collapsed to nothing
   on a narrow window would take the one thing on this page a person chose for
   themselves off the page at exactly the width where the name is all that is
   left. */
.avatar { flex: none; display: inline-flex; align-items: center; justify-content: center;
          width: 1.6rem; height: 1.6rem; color: var(--fg); }
.avatar svg { width: 100%; height: 100%; }
button.avatar {
  font: inherit; background: var(--surface); color: var(--fg); cursor: pointer;
  border: 1px solid transparent; border-radius: 5px; padding: .1rem;
}
button.avatar:hover { border-color: var(--accent); }
/* Nothing chosen yet still has to be a target. An empty button is a control
   nobody can find, and this one is the only way to the picker — so the unset
   state is a dashed ring, which reads as a place something goes. */
button.pick.unset::before { content: ""; width: 1.1rem; height: 1.1rem; border-radius: 50%;
                            border: 1.5px dashed var(--muted); }
/* What the list hangs off. `position: relative` and no z-index on purpose: a
   positioned element with `z-index: auto` does NOT open a stacking context, so
   the list's z-index below is weighed in the page's own context against the
   sticky header's — and 3 beats 2. Given a z-index here the wrapper would become
   the context, the list would be trapped inside it at the wrapper's own level,
   and a list left open while the page scrolls would be painted over by the
   header. `flex: none` for the same reason `.avatar` has it: this is the button's
   place in a line that wraps. */
.pickwrap { position: relative; flex: none; display: inline-flex; }
/* A popup, and no longer a row inside the group line. Twenty-five rows of drawing
   and name cannot be a line in a wrapping flex row: in flow they push every
   person below down by the height of the list, which is an accordion rather than
   a picker, and the reason the old arrangement could get away with a strip of
   bare buttons was that twelve of them fitted on one line.
   So it floats, and everything that arrangement bought — no positioning, no
   z-index, no argument with the sticky header two rows up — is paid for by the
   wrapper above and by the z-index here, both of them argued rather than tried.
   `max-height` and not a row count, so a set that grows again still scrolls
   inside itself rather than off the window. 15rem and not more because this
   opens downward and only downward: a list that flipped above the button on the
   rows near the bottom of the page and below it everywhere else is a list nobody
   can aim at, so the overhang is bounded instead, and the page scrolls to it.
   `.picker[hidden]` is (0,2,0) against `.picker`'s (0,1,0), so the attribute wins
   on specificity and not on source order — which matters because the shell's
   stylesheet is inlined before this one and a rule that relied on order would be
   the loser there. */
.picker { position: absolute; z-index: 3; top: calc(100% + .3rem); left: 0;
          margin: 0; padding: .2rem; list-style: none; min-width: 11rem;
          max-height: 15rem; overflow-y: auto; overscroll-behavior: contain;
          background: var(--surface); color: var(--fg);
          border: 1px solid var(--line-strong); border-radius: 3px;
          box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.picker[hidden] { display: none; }
.picker .option { display: flex; align-items: center; gap: .45rem; cursor: pointer;
                  padding: .2rem .35rem; border-radius: 2px; white-space: nowrap; }
/* The drawing keeps its own box, so the names all start at the same x whatever
   width the drawing happens to use. A column of names that stepped in and out
   with the art is a column nobody can scan, which is the whole reason the names
   are here. */
.picker .art { flex: none; display: inline-flex; width: 1.25rem; height: 1.25rem; }
.picker .art svg { width: 100%; height: 100%; }
/* Where the keyboard is, in the colour the suggestion popup already uses for the
   same fact — one language for "this is the row you are on", on the two lists
   this application has. The drawing follows because it is `currentColor`. */
.picker .option.on { background: var(--accent); color: var(--on-accent); }
.picker .option:hover { background: var(--surface-2); }
.picker .option.on:hover { background: var(--accent); }
/* And which row is already yours, which is a different fact from the one above
   and so is drawn in a different channel: weight, not ground. Both at once is the
   ordinary case — you open the list on your own mark — and two grounds would
   have made that one row look like two states of the same thing. */
.picker .option[aria-selected="true"] { font-weight: 650; }
/* What the picker said. A line of its own under the group line, the same way the
   picker used to take one under the name — and not a cell at the end of the row, where
   `.tally`'s `margin-left: auto` had put it a full table's width away from the
   button it is about. Empty it is a zero-height line and costs the row a 2px
   gap; `display: none` on `:empty` would cost more than that, because a live
   region has to be in the accessibility tree BEFORE its text changes or the
   change is announced to nobody.

   Two colours in one region, because it carries two kinds of sentence: a
   receipt, which the mark changing beside it has already confirmed, and a
   refusal, which is the whole reason this element exists and has to be findable
   next to a button that otherwise looks like it did nothing. */
.groupline #state { flex: 0 0 100%; color: var(--muted); font-size: 12px; }
.groupline #state.bad { color: var(--warn); }
"""
)

_ROLES = (("owner", "owner"), ("assignees", "assignee"), ("reviewers", "reviewer"))

# Most answerable first. Grouped by record — which is what building the rows one
# record at a time gave you — a person with twenty rows had their four ownerships
# scattered through it, and ownership is the thing being on the page is for.
# There is no shaper row any more: `shaped_by` retired into `owner`, so who
# shaped a pitch is its Owner line.
_ROLE_ORDER = ("owner", "assignee", "reviewer")

# Which table filter answers "show me this person's <role>", and the words for
# what that link opens. Every role this page draws is a table facet now, but the
# lookups below stay `.get`-shaped: a role without a filter is a count rather
# than a dead link, which is what kept the shaper row honest while it existed.
_ROLE_FILTER = {
    "owner": ("owner", "owns"),
    "assignee": ("assignees", "is assigned"),
    "reviewer": ("reviewers", "reviews"),
}


def _proposed(index: Index, number: int, window: tuple[date, date] | None) -> Cycle:
    """The record Save would write for a cycle nobody has written one for.

    Every date on it comes from where the rest of the tool already gets that
    cycle's dates: the `config/cycles.yaml` window, and `schedule.build_end`,
    which is what the overrun flag and the timeline's solid rule both read. This
    page must not have arithmetic of its own — it had, briefly, and it took the
    end of the WINDOW for the review meeting. Cool-down is inside a window, so
    cycle 36 offered 7.8 weeks of capacity against a build the scheduler ends
    seven weeks in: three answers about one cycle, and the largest of them was
    the number a betting table would have bet against.

    A cycle nobody has dated at all falls back to the team's cadence, and both
    dates are marked assumed so the page says so.
    """
    config = Config(holidays=index.holidays, cooldown_weeks=index.cooldown_weeks)
    if window is None:
        starts_on = index.today
        builds_until = days_after(starts_on, _DEFAULT_CYCLE_DAYS - 1)
        ends_on = days_after(builds_until, round(index.cooldown_weeks * 7))
    else:
        starts_on = window[0]
        builds_until = build_end(number, window, config)
        ends_on = window[1]
    return Cycle(
        cycle=number,
        starts_on=starts_on,
        # The meeting is the day after the last day of build, and nobody holds one
        # on a Saturday.
        reviews_on=config.next_working_day(builds_until),
        builds_until=builds_until,
        # A window whose cool-down is longer than the window itself would end
        # before its own build. One bad row in a config file, not a broken page.
        ends_on=max(ends_on, builds_until),
        build_weeks=config.working_weeks(starts_on, builds_until),
        # Nobody wrote either of them: the review is inferred from the global
        # cool-down, and the end is only as good as the window it came from.
        assumed_review=True,
        assumed_end=window is None,
    )


def _cycle_view(index: Index, number: int, links: Links = ROUTES) -> dict:
    """Everything the cycle page shows, computed once so the markup only lays out.

    A person's scheduled end date sits beside their capacity bar deliberately: a
    green bar next to a timeline that runs a month past the cycle is the failure
    that stops a room trusting the tool, and the two numbers come from different
    subsystems. Put together, they cannot quietly disagree.
    """
    plan = index.plans.get(number)
    held = index.load(number)
    # What is NOT in `held`, per person. Shaping and thinking work is legitimately
    # unsized — the validator asks nobody to guess an appetite for a bet nobody
    # has shaped — and `counts_in` says it is still what somebody's next weeks are
    # spent on, so it used to be charged the default half a week each. Now it is
    # charged nothing, and a person's bet is that much smaller than it was; the
    # count beside it is what stops that being a number that quietly shrank.
    #
    # It is not only shaping work. The size gate is `ready` only, so a task can be
    # running with no appetite on it, and on the page for the cycle it is running
    # in that record is the whole of the difference between the bar and the
    # weeks somebody is actually spending. `counts_in` carries it here by its
    # start date; `carried` below names it, so the count has something behind it.
    unsized = index.unsized_in(number)
    nominal = index.nominal_availability
    window = index.cycles.get(number)
    # A cycle with no record has a page too, because the index links to every
    # cycle the plan names and not only to the ones somebody wrote down. That
    # page is a form: everything on it is the record Save would write — the
    # model's own default length, the config window's start if there is one, and
    # the team list as a roster to correct. An empty table with an add box next
    # to it is a form nobody can tell is working.
    # A cycle with no record is shown as the record Save would write, resolved
    # the same way a real one is: `with_plans` is what turns two meetings into
    # dates and a length, and doing that arithmetic a second time here is how the
    # form and the page start disagreeing about the same cycle.
    proposed = plan or _proposed(index, number, window)
    listed = list(plan.availability) if plan else list(index.known_people)
    ends_on = proposed.ends_on.isoformat() if proposed.ends_on else ""

    # Exactly who was named. Being on the roster IS being in the cycle, so a name
    # is added deliberately rather than appearing because somebody was assigned
    # something — which would make the roster a report instead of a decision.
    people = []
    for login in sorted(listed, key=str.lower):
        rate = proposed.availability.get(login, nominal)
        # Asked of the cycle rather than multiplied out here. It was
        # `rate * build_weeks`, which is `Cycle.capacity` written a second time —
        # and the cycles index already asks the cycle, so the two pages computed
        # one number two ways.
        capacity = proposed.capacity(login, nominal)
        # `counts_in` and not `cycle == number`, the same question the load column
        # asks. Filtering on the stamp alone hid every carried bet from the date
        # beside the bar — so the bar and the date agreed with each other and both
        # left out the work actually filling the person's weeks.
        mine = [
            index.spans[i].end
            for i, e in index.plan.items()
            if index.counts_in(e, number)
            and login in (e.assignees + ([e.owner] if e.owner else []))
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
                "unsized": len(unsized.get(login, [])),
                "until": max(mine).isoformat() if mine else "—",
            }
        )

    # Bet into this cycle and not on its roster. Dropping them silently would
    # hide load from the one page that exists to add load up — which is why the
    # unsized names are in here too: somebody whose whole cycle is unsized work
    # holds no weeks at all, and reading this off `held` alone would take them
    # off the page for the same reason the number went down.
    strangers = sorted((set(held) | set(unsized)) - set(listed), key=str.lower)

    # Work bet earlier and still running. It keeps its own cycle number (D-C1), so
    # it is not "in" this cycle by the stamp — but it is being done with this
    # cycle's weeks, and it is counted above. Named here so the number can be
    # argued with rather than wondered about.
    carried = [
        {"id": i, "title": index.plan[i].title, "cycle": index.plan[i].cycle}
        for i in index.carried_into(number)
        # The same two exclusions `load` makes, so this list explains that number
        # and not a different one: a parent is a rollup and charges nothing, and
        # work with nobody on it charges nobody.
        if not index.children.get(i) and (index.plan[i].owner or index.plan[i].assignees)
    ]

    # What this cycle produced, which nothing above it can say. Every figure in
    # the roster is `counts_in`, and `counts_in` refuses a done record on its
    # first line — so the page for a cycle that has been reviewed showed every
    # person at 0.0 of their capacity and had no way to mention the work they had
    # just spent it on. `delivered_in` is the second question, asked of the end
    # dates §4 made a stored field; the bars above keep meaning what they meant.
    delivered = []
    for record_id in index.delivered_in(number):
        record = index.plan[record_id]
        span = index.spans.get(record_id)
        size = size_weeks(record)
        # The one number on the row that is a measurement and not a forecast, and
        # it is shown only where the span it came from was measured from THIS
        # date. `schedule` reads a done record's end back as no end at all when
        # it falls before the start — a hand-written file can contradict itself,
        # and `ends_before_it_starts` is a blocker at the door rather than
        # something this module may assume away — and it then hands `_overrun`
        # the START date instead. Printed beside `end_date` that would be an
        # overrun measured against one day beside a claim about another, which is
        # the exact defect §4b's `overruns_cycle` was pinned to the span to end.
        # The equality is the whole gate: the number and the date agree, or the
        # row says only what it can.
        measured = span is not None and record.end_date is not None and span.end == record.end_date
        delivered.append(
            {
                "id": record_id,
                "title": record.title,
                # A bet is what somebody stated, and plenty of finished work
                # states none — the size gate reaches `ready` and `in_progress`
                # and nothing older than it. Empty here and named in the
                # template, for the reason an empty appetite box on the betting
                # table says "not sized" rather than showing a default: a number
                # in this column is a number the room said out loud.
                #
                # `%.1f` and not the `%g` the betting table uses on the same
                # number. That one fills an INPUT, where `3.0` in a box whose file
                # says `3` is a page proposing an edit nobody made; this is a
                # figure in a column of figures, beside the roster's own `bet`
                # column, which is `%.1f` — and 3 above 4.5 is a ragged column
                # where 3.0 above 4.5 is a comparison.
                "bet": "" if size is None else f"{size:.1f}",
                "ended": record.end_date.isoformat() if record.end_date else "",
                # `%.1f` and the cycle beside it, the same two values the detail
                # page's overrun sentence prints, so a bet that overran says the
                # same thing in both places.
                "over": f"{span.overruns_cycle_weeks:.1f}"
                if measured and span.overruns_cycle_weeks
                else "",
                "over_cycle": span.overruns_cycle if measured else None,
            }
        )

    candidates = []
    # Ready first, then in progress, and by id inside each: the question at a
    # betting table is what to pick up, and what is already running is context.
    order = ("ready", "in_progress")
    for record_id, record in sorted(
        index.plan.items(),
        key=lambda kv: (order.index(kv[1].status) if kv[1].status in order else len(order), kv[0]),
    ):
        # A bet is made on a pitch, or on a chore nobody pitched. A task under a
        # pitch is part of that bet and comes with it; a project is a container
        # for bets and is not one. Listing all three put a milestone and eleven
        # of its own tasks on the table beside the five pitches they belong to,
        # and ticking any of them stamped a second cycle onto one decision.
        if record.status not in order or not is_bettable(record):
            continue
        size = size_weeks(record)
        candidates.append(
            {
                "id": record_id,
                "title": record.title,
                "kind": record.kind,
                "status": record.status,
                # The field jcanton asked for at the table: "it's missing
                # priority, that's very important". A bet is a decision about
                # what matters most against a fixed appetite, and the one number
                # that says what matters was on every other view but this one.
                "priority": record.priority,
                "size": "" if size is None else f"{size:g}",
                "size_field": "person_weeks",
                # `size_hint` was here and filled the empty box with the default
                # this row would have been charged at — "0.5 assumed", a number
                # somebody could read off a betting table as though the room had
                # said it. An empty box now means nobody has bet a size, which is
                # the one thing a betting table is for settling, so the
                # placeholder says that in the template and needs no value from
                # here.
                "assignees": ", ".join(record.assignees),
                "reviewers": ", ".join(record.reviewers),
                "cycle": record.cycle if record.cycle is not None else "—",
                "in_cycle": record.cycle == number,
                # Bet in an earlier cycle and still running: shown, counted, and
                # not re-stampable. Overwriting its cycle would move the deadline
                # its overrun is measured against and forgive the slip.
                "carried": record.status == "in_progress"
                and record.cycle is not None
                and record.cycle < number,
            }
        )

    return {
        "number": number,
        "recorded": plan is not None,
        "dated": window is not None,
        "starts_on": proposed.starts_on.isoformat(),
        "reviews_on": proposed.reviews_on.isoformat() if proposed.reviews_on else "",
        "builds_until": proposed.builds_until.isoformat() if proposed.builds_until else "",
        "ends_on": ends_on,
        "build_weeks": f"{proposed.build_weeks:g}",
        "assumed_review": proposed.assumed_review,
        "assumed_end": proposed.assumed_end,
        "nominal": nominal,
        "people": people,
        "held": held,
        "strangers": strangers,
        "carried": carried,
        "delivered": delivered,
        "over": [p["login"] for p in people if p["over"]],
        "candidates": candidates,
        # `_markdown` and not a bare `_MD.render`: a cycle's goal is a shaping
        # document like any other, and rendered its own way it was the one body
        # on the site whose uploaded figures pointed at the wrong prefix and
        # whose remote images still went to the network.
        "body": _markdown(without_comments(plan.body), links) if plan else Markup(""),
        # The source, for the box somebody types in. Rendered above it, edited
        # below it — the same two views of one field the detail page has.
        "raw_body": plan.body if plan else "",
        # The goal is a field and not prose, so it is drawn as text rather than
        # put through the markdown renderer: a sentence the room agreed on does
        # not want a heading level, and running it through `_markdown` would wrap
        # it in a paragraph that the layout above the table has to undo.
        "goal": plan.goal if plan else "",
    }


def render_cycle(
    index: Index, number: int, links: Links = ROUTES, base_commit: str | None = None
) -> str:
    view = _cycle_view(index, number, links)
    body = _compiled(_CYCLE).render(
        c=view,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        # The two ladders, in rung order, so the pickers and the sort agree with
        # the rest of the app rather than with a copy written here.
        statuses=STATUSES,
        priorities=PRIORITIES,
        combobox=_combobox_html(index, live=base_commit is not None),
    )
    return _page(
        f"openproj — cycle {number}",
        body,
        _DETAIL_STYLE + _CYCLE_STYLE + _SUGGEST_STYLE,
        links,
        # `/cycle/37` is not `/cycles`, and one cycle is what the Cycles listing is
        # a listing of — so the item that got you here is the item that stays lit.
        # The heading below is "Cycle 37", which is the thing you are looking at
        # and not the word in the nav, so it stays on the screen.
        "cycles",
        index.unreadable,
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

    `unsized` is that same direction guarded a second time. Work nobody has put
    an appetite on charges nothing, so the sum is only over what the plan
    actually knows the weight of, and the count says how many records the sum
    could not include. Distinct records, not the per-person entries behind them:
    one bet with two assignees is one thing nobody has sized, and it is on each
    of their rows on the cycle page for the same reason.
    """
    plan = index.plans.get(number)
    window = index.cycles.get(number)
    bet = sum(index.load(number).values())
    unsized = {one for ids in index.unsized_in(number).values() for one in ids}
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
        "ends_on": plan.ends_on.isoformat() if plan else (window[1].isoformat() if window else ""),
        "people": len(plan.availability) if plan else 0,
        "bet": bet,
        "unsized": len(unsized),
        "capacity": capacity,
        "percent": min(100, round(100 * bet / capacity)) if capacity else 0,
        "over": bool(capacity) and bet > capacity,
    }


def render_cycles(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
    # Every cycle the plan names, not only the ones with a file. A cycle dated in
    # config, or one that records point at with nothing behind it, is exactly
    # the cycle somebody needs to find: it holds work and holds no record.
    numbers = _cycle_numbers(index)
    rows = [_cycle_totals(index, number) for number in sorted(numbers, reverse=True)]
    last = index.plans[max(index.plans)] if index.plans else None
    # The number to propose comes from the cycles the plan has *decided* — the
    # ones with a record and the ones config/cycles.yaml dates — and not from
    # every number a record happens to mention. A plan whose cycles live only in
    # config would otherwise be offered cycle 1 while it is running cycle 37; but
    # unioning `record.cycle` in overshoots the other way, and worse. One bet into
    # a cycle nobody has written down — which the listing above actively invites —
    # made the form propose the number after *that*, with no dates behind it, so
    # the real last cycle's end date was thrown away and the proposal started
    # today. Record-referenced numbers belong to the listing; they are not a
    # decision about when the next cycle begins.
    decided = set(index.plans) | set(index.cycles)
    top = max(decided) if decided else 0
    ends = index.cycles.get(top)
    body = _compiled(_CYCLES).render(
        cycles=rows,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        # Whether there is a page per cycle to link a card to. Only the server
        # serves one; `render_static` writes six files and no cycle is among
        # them, so on a rendered plan the card names its cycle and stops there.
        per_cycle_page=links.cycle.startswith("/"),
        # The next cycle's betting table is the day the last one's cool-down
        # ends, and its review meeting is as far from it as the last one's was:
        # both are true far more often than not, and both are corrected on the
        # new cycle's own page.
        next={
            "number": top + 1,
            # `days_after`, because the cycle this reads from may be the one
            # somebody dated at the end of the calendar: a day past that would be
            # `/cycles` gone too.
            "starts_on": days_after(ends[1], 1).isoformat() if ends else index.today.isoformat(),
            "reviews_on": days_after(
                days_after(ends[1], 1) if ends else index.today,
                _DEFAULT_CYCLE_DAYS
                if last is None or last.reviews_on is None
                else (last.reviews_on - last.starts_on).days,
            ).isoformat(),
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
        roster=last.availability if last else {},
    )
    return _page(
        "openproj — cycles",
        body,
        _DETAIL_STYLE + _CYCLE_STYLE,
        links,
        "cycles",
        index.unreadable,
    )


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
    # Records this cycle charges nobody for, because nobody has sized them. One
    # cycle is asked, the one running now, exactly as the weeks above are: a count
    # drawn from every cycle at once beside a figure drawn from one would be two
    # answers to one question. Weeks bet elsewhere are summed below and get no
    # such count — that line is a hint that somebody is busier than this page
    # says, and a second qualification on a number that is already a
    # qualification is a line nobody finishes reading.
    missing = index.unsized_in(number) if number is not None else {}
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
            "unsized": len(missing.get(login, [])),
            "capacity": capacity,
            "over": bool(capacity) and held > capacity,
            "percent": min(100, round(100 * held / capacity)) if capacity else 0,
            "elsewhere": elsewhere.get(login, 0.0),
        }
    return {"cycle": number, "recorded": plan is not None, "people": people}


def render_people(index: Index, links: Links = STATIC, editable: bool = False, me: str = "") -> str:
    """Everyone in the plan, and what they are on the hook for.

    Built from the fields rather than from a roster: a page that reads a separate
    list of members shows people who have nothing to do and misses whoever was
    added this morning. That is also why `me` may be somebody with no row here,
    and why there is then no picker: the only place to put one would be a row for
    a person listed for holding nothing, which is the row this page does not draw.

    `editable` is the server and `me` is who it says may pick an icon. Both are
    needed for a picker and neither is inferred from the other — a static export
    is editable by nobody no matter whose name is in it, and a served page read
    by a stranger is the same. `me` is empty for anybody the write path would
    refuse, decided by the same function the write path asks: a control that can
    only answer 403 is a dead end you find by pressing it.
    """
    held: dict[str, list[dict]] = {}
    for record_id, record in sorted(index.plan.items()):
        span = index.spans.get(record_id)
        for field, role in _ROLES:
            value = getattr(record, field, None)
            for login in value if isinstance(value, list) else [value] if value else []:
                held.setdefault(login, []).append(
                    {
                        "role": role,
                        "id": record_id,
                        "title": record.title,
                        "kind": record.kind,
                        "status": record.status,
                        "span": f"{span.start} → {span.end}" if span else "—",
                        "search": f"{record_id} {record.title}".lower(),
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
        # What this person has stored, and only if this version can draw it: a
        # `dragon` nobody has the art for must not mark a row in the picker, and
        # must not stop "No icon" from being the row the list opens on. Same
        # bargain as `icon_svg` one line down, said in the one place that has to
        # agree with it.
        chosen = index.icons.get(login, "")
        people.append(
            {
                "login": login,
                # The drawing, resolved here rather than in the template: an icon
                # name this version no longer draws comes back as nothing at all,
                # so the template asks whether there is a mark and never whether
                # there is a name.
                "art": icon_svg(chosen),
                "icon": chosen if chosen in _ICON_ART else "",
                "mine": editable and login == me,
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
    body = _compiled(_PEOPLE).render(
        people=people,
        links=links,
        # Every icon, drawn once, for the picker. In `ICONS` order, which is the
        # sky, then the world, then the creatures: a list ordered by nothing is a
        # list a reader has to search rather than scan.
        icons=[{"name": name, "art": icon_svg(name)} for name in ICONS],
        editable=editable,
        # The same bar the plan's three views draw, over this page's own three
        # fields. Which hat somebody is wearing is not a field of a record, so
        # `role` is only ever offered here.
        facets=_facets_html(facets, ("role", "kind", "status"), "Search person, record, id"),
        load=load,
        filters=_FILTER_JS,
    )
    return _page("openproj — people", body, _PEOPLE_STYLE, links, "people", index.unreadable)
