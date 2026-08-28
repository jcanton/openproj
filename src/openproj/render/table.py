"""The plan table."""

from __future__ import annotations

from markupsafe import Markup

from ..index import Index
from ..model import KINDS as KIND_LADDER
from ..model import PARENT_KINDS, required_at, unread_fields
from .controls import (
    _FILTER_JS,
    _NO_ASIDE,
    _combobox_html,
    _facets_html,
    _summary_html,
)
from .env import _compiled
from .rows import _row
from .shell import STATIC, Links, _page, _titles
from .styles import _SCROLL_STYLE, _SUGGEST_STYLE, _TREE_STYLE
from .tokens import (
    _KIND_MODELS,
    DRAFT_MARKS,
    EDITABLE,
    HUMAN,
    LABELS,
    PRIORITIES,
    PRIORITY_GLYPH,
    PRIORITY_LEVEL,
    STATUS_GLYPH,
    STATUSES,
    SUGGESTS,
    TEMPLATES,
)

# Columns the table shows that are computed rather than owned, each with what the
# cell answers when somebody tries to edit it. `size` is the least obvious: it
# shows the appetite of the record itself, and on a pitch it is the bet rather
# than what the tasks under it come to — two numbers one cell cannot hold, and an
# editor opened on the wrong one writes the wrong one.
#
# The names and the sentences are one map because they were two: the script
# carried its own literal list of four, so a fifth derived column would have kept
# its editor open and refused with `undefined`. A cell that will not be edited and
# will not say why is indistinguishable from a cell that is broken.
#
# **`end` was in here and is not, and the sentence it carried was the reason.**
# It read "Derived from the start and the appetite", which stopped being true of
# every `done` record when §4b of `design/time-model.md` gave the done branch a
# typed `end_date` to end at. On such a row the cell shows what the file states,
# the validator's `a done record needs the date it ended` now marks that same
# cell — and the tooltip underneath it claimed the value was computed and offered
# no way to supply it. The mark reached the right cell and the cell refused the
# one edit that would clear it. The End column is the editor for `end_date` now,
# exactly as Start is for `start_date`, and `_TABLE_SHOWS` is where it says which
# of the two dates a given cell is drawing.
_TABLE_WHY = {
    "blocked_by": "Counted from depends_on, minus the ones already done or shelved.",
    "progress": "Counted from the task list in the body. Tick the boxes there.",
}
_TABLE_DERIVED = tuple(_TABLE_WHY)

# Every column of this table whose header is not the name of the field beneath
# it, written down once and read in both directions below. A column and a field
# that happen to share a word need no entry: `owner` is `owner` everywhere, and
# listing the identities would be a list to keep in step with `_TABLE_COLUMNS`.
#
# It is one map because it was two, and the two disagreed in exactly the way
# this repository keeps being bitten by. `_COLUMN_FIELD` knew `start` was
# `start_date`; the script's `MARK_COLUMN` knew `person_weeks` was `size` and
# `depends_on` was `blocked_by`, and neither of them knew about the dates. So
# every problem the validator reports about a start or an end — a start date
# that has passed, an end missing at `done`, an end before its start, a date
# outside every cycle this plan has dated — hung its mark on the ID cell, while
# the tooltip on that mark says the fix "is to edit the cell the sentence is
# on". The reader was sent to the one cell that cannot be wrong.
_COLUMN_SHOWS = {
    "size": "person_weeks",
    "start": "start_date",
    "end": "end_date",
    "blocked_by": "depends_on",
}

# The three columns that SHOW one value and EDIT the written one underneath it.
# jcanton, 2026-08-27: "the appetite is not an editable field in the /table (dunno
# why) make it editable in /table please. start date as well".
#
# The reason they were not is in `_TABLE_WHY`, where all three used to sit: `size`
# on a pitch with tasks is the bet and not what those tasks come to, and `start`
# is `start_date` after the scheduler has moved it for the dependencies and for
# what the people on it are already doing. Those two cells are forecasts, and
# typing over a forecast is how a plan stops being believed.
#
# **`end` is the third, and it is the one whose cell is not always a forecast.**
# A `done` record's span ends at the `end_date` its file states (§4b of
# `design/time-model.md`), so the End cell on that row shows a value somebody
# typed — and the record page has had an editable End date row for it all along.
# The table now agrees, which is what the two surfaces have to do: a person who
# learns the model from one page must not be taught something else by the other.
#
# What makes all three editable is that the editor opens on the WRITTEN field and
# never on the value in the cell, which is the same rule the draft row has
# followed since it was written (`_editable_for`). Type into it and the cell goes
# back to being the scheduler's on the next draw — where the scheduler has an
# answer at all.
#
# A kind that reads none of these fields is still refused, and by the mechanism
# that already existed rather than a new one: `reads()` asks `unread_fields`,
# which puts `person_weeks` on any rung that is not `sized` and both dates on any
# rung that does not schedule. A product's size cell has never been editable and
# still is not.
#
# Derived from the map above rather than listed beside it, and `_TABLE_DERIVED`
# is the whole of the difference: a column with a sentence in `_TABLE_WHY` has no
# editor at all — `whyOf` closes the cell before `EDITABLE` is ever consulted —
# so `blocked_by` drops out here for the reason it was written into `_TABLE_WHY`
# in the first place. Listing this trio by hand instead is what would let a sixth
# column be added above and silently open an editor on a forecast, which is the
# thing this comment spends four paragraphs refusing.
_COLUMN_FIELD = {
    column: field for column, field in _COLUMN_SHOWS.items() if column not in _TABLE_DERIVED
}

# The same map read the other way: a `Problem` names a FIELD and a mark hangs on
# a COLUMN, so the browser needs the inverse of what the editors need. Inverted
# here rather than typed out in the script, because two hand-written halves of
# one mapping is precisely how the dates came to have a route in and none back.
_MARK_COLUMN = {field: column for column, field in _COLUMN_SHOWS.items()}

# How a rollup's size cell reads against the box the bet bought, as one mark per
# state of `_rollup` (`rows.py`). Colour is the first channel and this is the
# second, because colour is the one channel a dichromat loses and the difference
# between "this fits" and "this does not" is the whole reason the cell is drawn.
#
# Shipped as a map keyed by the state rather than as a character on every row,
# which is what `GLYPHS` and `RUNGS` already do with the status and priority
# marks: a constant repeated once per record is a constant that arrives in the
# payload four hundred times and can still only ever say one thing.
#
# `unbet` has no mark, and that is the state saying so. There is no box to be
# under, level with or over, so a mark here would be a verdict on a bet nobody
# has made — the same silence `_rollup_problems` keeps about that record.
_ROLLUP_GLYPH = {"under": "▾", "level": "=", "over": "▴", "unsized": "?", "unbet": ""}

# The columns whose cell draws a date, which is the pair that can be showing
# either the file's own value or the scheduler's. Written once and read three
# ways below — how the cell is formatted, whether it is drawn as computed, and
# which half of its tooltip it gets — because "start and end are the dates" was
# three literals in this script and a fourth idea in the payload.
_TABLE_DATES = ("start", "end")

# What the tooltip adds on those three, because "double-click to edit appetite"
# on a cell reading `2 wk` does not explain what the number in it is.
#
# **A date column gets two sentences and not one, because it shows two different
# things.** `start` was a single sentence beginning "Shows the scheduled start",
# and a row with no span draws the date its own file states — so the sentence
# named a forecast that does not exist over a value somebody typed. `end` is the
# same fault with the halves swapped: it said "Derived from the start and the
# appetite" from `_TABLE_WHY`, which a `done` record's End cell has not been
# since it began ending at the `end_date` its file records. Which of the two a
# given cell holds is `row.stated` (`rows.py`), and `showsIn` below picks the
# sentence with it.
_TABLE_SHOWS = {
    "size": "Shows the appetite this record was bet at. Blank means nobody has sized it.",
    "start": {
        "stated": "Shows start_date, which this record states. "
        "Editing sets start_date, the earliest it may begin.",
        "derived": "Shows the scheduled start. Editing sets start_date, the earliest it may begin.",
    },
    "end": {
        "stated": "Shows end_date, the day this record records that it ended. "
        "Editing sets end_date.",
        "derived": "Shows the scheduled end, derived from the start and the appetite. "
        "Editing sets end_date, the day the work actually stopped.",
    },
}

# What this view can be done to, said once, beside the search box. Three gestures
# in one line because a page that teaches them one at a time teaches the third to
# nobody: a drag has no name written on it anywhere, and the grip beside an id is
# 8px of dotted rule. The `+` row at the foot of the table says what it is by
# being a control, so it is the one that needs no sentence.
_TABLE_HINT = Markup(
    '<p class="hint">double-click a cell, or press Enter on it, to edit it · '
    "drag a row by the grip beside its id onto another to file it there</p>"
)

# Every column the table draws, in the order it draws them, and whether it sorts.
# One list rather than three: the header row, the `keys` the cells are built from
# and the width the empty row spans were a Jinja loop and two JavaScript literals
# that had to be edited together, with a comment saying so. Nothing enforced it,
# and index-parallel lists that drift shift every cell one column left. The word
# in each header comes from LABELS, so the column and the facet naming the same
# field cannot be given two different words.
_TABLE_COLUMNS = (
    ("id", True),
    ("title", True),
    ("priority", True),
    ("status", True),
    ("owner", True),
    ("assignees", True),
    ("reviewers", True),
    ("cycle", True),
    ("size", True),
    ("start", True),
    ("end", True),
    ("blocked_by", True),
    ("progress", True),
    ("prs", False),
    ("tags", False),
)


def _columns_for(index: Index) -> tuple[tuple[str, bool], ...]:
    """The columns this plan has anything to put in.

    Only `progress` is conditional, and it earns the exception: it is counted out
    of the body rather than stored, so a plan where nobody keeps a checklist would
    carry a permanently empty column across fifteen others — which reads as a
    broken column, not as an unused one. It appears the moment one body has a
    list, and the column that was never there is not a feature anybody has to
    turn off.
    """
    if index.progress:
        return _TABLE_COLUMNS
    return tuple(column for column in _TABLE_COLUMNS if column[0] != "progress")


def _payload(index: Index) -> dict:
    return {
        "rows": {i: _row(index, i) for i in index.plan},
        # No `facets` and no `predicates`: the control bar is server-rendered from
        # `index.facets` and the script reads its own `<select>`s, so both keys
        # were the whole facet index inlined into every table page and read by
        # nothing. Two tests had grown to protect the weight.
        # Flat, exactly as the validator produced them, and grouped by the page.
        # Grouped here as well, the table would have carried two copies of one
        # aggregation — the one rendered into the rows and the one it has to
        # rebuild after every save from /api/index.json, which returns this same
        # flat list. Only the first would ever have been tested.
        #
        # The PLAN's problems only, now that `validate_all` covers every record:
        # a problem on an issue has no row here to hang on, and an inbox id in a
        # plan page's payload is the leak the exclusion sweep exists to catch.
        "problems": [p.model_dump() for p in index.problems if p.record_id in index.plan],
        # One list of what a person may change, shared with the detail page. Two
        # lists drift the first time a field is added, and silently.
        "editable": {k: v for k, v in EDITABLE.items() if k not in _TABLE_DERIVED},
        "suggests": SUGGESTS,
        "choices": {"status": list(STATUSES), "priority": list(PRIORITIES)},
        # The two marks a row wears, shipped rather than restated in the script.
        # The table draws its rows in the browser and the graph, the timeline and
        # the legend are drawn here, and a second copy of either map is a rung
        # that agrees until somebody adds one.
        "glyphs": STATUS_GLYPH,
        "marks": PRIORITY_GLYPH,
        "levels": PRIORITY_LEVEL,
        # Which statuses demand which fields, derived from the gate itself by
        # `required_at` (`model.py`). The detail page has had this since it grew
        # the marks beside its labels; the table had nothing, so moving a row to
        # `in_progress` was a refusal naming a field the table does not show, and
        # the way out was to open the record and come back.
        #
        # Per kind, because a row is one kind: merged, the map says a project is
        # missing `person_weeks` at `ready` and a project has no such field. The
        # form keeps the merge, because its kind can still be switched.
        "required": {kind: required_at(kind) for kind in _KIND_MODELS},
        # What a row that does not exist yet can be typed into, per kind.
        "new_row": _new_row_fields(),
        # And which fields a row that already exists must not be typed into,
        # per kind, from the same `unread_fields` the map above is built from
        # and the validator reports from. The draft row asked this question and
        # a stored row did not: a product's status cell was empty (`_row`
        # withholds the value) and still opened an editor that committed
        # `status` onto a record with no such field.
        "unread": {kind: unread_fields(kind) for kind in _KIND_MODELS},
        # And what it holds before anybody types anything, read off the model
        # rather than written down here. The row being filled in shows the status
        # and the priority it will be created with: a blank cell that turns into
        # `thinking` on save is the row lying about what it is about to write.
        # Derived, so it moved on its own when the ladder gained a foot — which
        # is what the three hand-written copies of this default did not.
        "defaults": {
            name: _KIND_MODELS["task"].model_fields[name].default for name in ("status", "priority")
        },
        # Which kind may hold which, from the model's own map. It decides what a
        # drop does *before* the drop: a row that cannot take this one is drawn
        # as refusing it while the mouse is still down, which is the difference
        # between a rule and a 422.
        "parent_kinds": {kind: list(kinds) for kind, kinds in PARENT_KINDS.items()},
        # The same templates `/new` offers — one per planned kind, plus blank.
        # A record created from the table is the same document as one created
        # from the form — a plan where a pitch has a shaping template only if
        # you happened to make it on the other page is a plan with two kinds of
        # pitch in it.
        "templates": TEMPLATES,
        # The word a reader gets, shipped rather than baked into the cells: the
        # rows are drawn by script, and a status the script renders has to reach
        # the same map the server-rendered pages read.
        "human": HUMAN,
        "labels": LABELS,
    }


_TABLE = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Table</h1>
{#- **No New record button here, and no instruction beside it.** Both were in
    this row until 2026-08-25; jcanton: "the new record button on top of the table
    should be removed: we already have the + new row at the bottom; move the
    description ... next to the search box so the page is consistent with the
    timeline and graph pages".

    The button was the older of two ways to bring a record into existence and the
    weaker one: it leaves the table for a form, where the `+` row at the foot
    creates one in place, with the plan still on screen. Two controls for one job,
    one of them a page away, is the shape a table grows when a feature arrives
    beside the thing it replaces rather than in it. `/new` is still a route and
    the records list still links to it (`records.py`, per kind) — this page is
    simply not where that door belongs, because it has one of its own inside the
    rows. The `+` row is drawn under the empty states too, so a plan with nothing
    in it still shows the way to put something in it. -#}

{#- The instruction went to `#controls .aside`, which is where the graph and the
    timeline already say what their view can do. It was here because it belonged
    beside the button it shared a subject with; with the button gone it belonged
    beside the box every one of these pages puts its own sentence next to.

    **And the row that held them is gone with them.** It kept the blocker count
    and the save receipt for one day, which left a `<p>` of furniture above the
    controls holding one sentence at the right-hand end and nothing at the left —
    jcanton, 2026-08-25: "there's now empty vertical space in the table view, for
    the 'blocking problem and N of M shown'; move this to the search box line".
    Both went into `#controls .searching` through `_summary_html`, which is the
    same box and the same wording the graph and the timeline now use. -#}
{{ facets }}
{#- role="grid" only where the cells are editable. It is a claim about who owns
    the arrow keys — a screen reader hands them to the page inside a grid and
    keeps them for its own cursor inside a table — and on a rendered file there
    is no editor for them to reach. -#}
<div class="table-scroll" data-fills><table id="rows"{% if editable %} role="grid"{%
  endif %}><thead><tr>
  {#- A real button inside every sortable header, not a click handler on the cell:
      there is no way to tab to a table cell, so sorting was mouse-only. The
      columns that cannot be sorted have no button, which is the difference said
      out loud. data-col names the field the column stands for, so the narrow
      breakpoint and the sticky rules pick columns by name rather than by
      counting them — and so does the remembered width, which is why the header
      word is free to be the reader's word rather than the field's. -#}
  {% for column, sortable in columns %}
  {%- if sortable %}<th data-col="{{ column }}" data-sort="{{ column }}" aria-sort="none"
    ><button type="button">{{ label(column) }}<span class="dir"
      aria-hidden="true"></span></button></th>
  {%- else %}<th data-col="{{ column }}">{{ label(column) }}</th>{% endif %}
  {%- endfor %}
</tr></thead><tbody></tbody></table></div>
{% if editable %}
<input type="hidden" name="base_commit" id="base" value="{{ base_commit }}">
{#- A conflict is the one answer that means the save did not land. It was a
    box that appeared, and nothing more. -#}
<div id="row-conflict" role="status" aria-live="polite" hidden></div>
{#- What the status about to be saved demands and the row has not got. A panel
    and not a column: `start_date` beside `start` and `end` is a third date on a
    row that already carries two derived ones, and the question is only ever
    asked at the moment the status moves. -#}
<div id="askfor" hidden></div>
{% endif %}
<script id="payload" type="application/json">{{ payload|tojson }}</script>
{% if editable %}{{ combobox }}{% endif %}
{{ filters }}
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

// `esc` comes from the shell, which declares it before this script runs. It was
// declared here as well as in the timeline, and the third script that needed
// it — the combobox, on every page `_COMBOBOX` ships on — had neither copy in
// scope.

// The same list the header row above was drawn from, emitted rather than
// retyped: these were two literals that had to stay index-parallel, with a
// comment asking whoever edited one to remember the other, and nothing enforcing
// it at runtime. One column out of step shifts every cell one column left.
const keys = {{ columns|map(attribute=0)|list|tojson }};

// Which column carries a complaint about a field whose column is not called by
// its name — `_COLUMN_SHOWS` inverted, shipped rather than written out here.
// This was a literal of two entries and `_COLUMN_FIELD` was a literal of two
// others, so the table drew a Start column and an End column that no problem
// about a start or an end could ever reach.
//
// A field with no column at all — `parent`, which the tree draws instead, and
// the inbox fields no planned row carries — still falls to the id cell, because
// a row that says something is wrong and will not say what is worse than no
// marker at all.
const MARK_COLUMN = {{ mark_column|tojson }};
const SEV_CLASS = {blocker: 'blocker', warning: 'warn'};

let MARKS = {};     // record id -> column -> {severity, messages}
let TROUBLE = {};   // record id -> the worst severity found on it
let BLOCKERS = 0;   // blocking problems
let BLOCKED = 0;    // records carrying at least one of them — what the link opens

// The problems arrive flat, exactly as the validator produced them, and are
// grouped here rather than on the server: /api/index.json hands back the same
// flat list after a save, so one grouping serves both and the after-a-save path
// cannot drift from the at-load one.
function regroup(problems) {
  MARKS = {};
  TROUBLE = {};
  BLOCKERS = problems.filter(problem => problem.severity === 'blocker').length;
  for (const problem of problems) {
    const id = problem.record_id;
    if (problem.severity === 'blocker' || !TROUBLE[id]) TROUBLE[id] = problem.severity;
    const column = MARK_COLUMN[problem.field]
      || (keys.includes(problem.field) ? problem.field : 'id');
    const columns = MARKS[id] || (MARKS[id] = {});
    const mark = columns[column]
      || (columns[column] = {severity: problem.severity, messages: []});
    if (problem.severity === 'blocker') mark.severity = 'blocker';
    // `drawn`, the day-first form: this hangs on a cell in a table whose own
    // Start and End columns are drawn that way. Every Problem carries both.
    mark.messages.push(problem.drawn);
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
  // How many rows there are to be shown *of*. It moves when a row is created
  // here, which is the only thing that changes it without a reload.
  document.getElementById('total').textContent = Object.keys(DATA.rows).length;
  // The count is of problems and the link filters records. One record can hold
  // three of them, so the population the link opens is named as well — a count
  // that opens a table of a different size is a count nobody trusts again.
  document.getElementById('blocker-word').textContent = BLOCKERS
    ? `blocking problem${BLOCKERS === 1 ? '' : 's'} on ${BLOCKED} ` +
      `${BLOCKED === 1 ? 'record' : 'records'}`
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
// Shipped from `_TABLE_WHY`, which is also the list of columns the payload
// withholds an editor for — written out again here, a fifth derived column would
// have arrived with no class and no sentence.
const WHY = {{ why|tojson }};

// The mark each rollup state wears, from `_ROLLUP_GLYPH`.
const ROLLUP_GLYPH = {{ rollup_glyph|tojson }};

// What this row's work adds up to, where this is the column that draws it.
// Three things ask — what the cell prints, what ground it takes, and why it
// cannot be edited — and the column name is written here rather than at each of
// them, because "the appetite column is the one that can be a rollup" is one
// fact and a row carrying `rollup` with a cell that ignored it would be a cell
// showing a bet under a ground describing its tasks.
const rollupOn = (row, key) => key === 'size' ? row.rollup : null;

// Why THIS cell refuses a double-click, which is the column's sentence for all
// but one. A size cell over a record with tasks under it draws what those tasks
// occupy and not the bet, so the reason it cannot be edited is a fact about the
// row rather than about the column — and the row already carries the sentence,
// written where the comparison it describes was made.
//
// One function and not a second flag, because four things have to agree about
// it: whether the cell is a control, whether it is drawn as derived, what a
// double-click answers, and whether the keyboard stops there. They were four
// reads of `key in WHY`, and a fifth answer that only some of them knew about is
// how a cell ends up looking editable and refusing to open.
function whyOf(row, key) {
  const rollup = rollupOn(row, key);
  return rollup ? rollup.why : (WHY[key] || '');
}

// The two columns whose cell shows one thing and edits another — `size` shows the
// scheduler's number and writes `person_weeks`, `start` shows the scheduled day
// and writes `start_date`. Everything below asks `fieldOf(key)` rather than
// using the column name as a field name, which is what they were the same thing
// for every other column.
const COLUMN_FIELD = {{ fields|tojson }};
const SHOWS = {{ shows|tojson }};
const fieldOf = key => COLUMN_FIELD[key] || key;

// The columns that draw a date, from `_TABLE_DATES`.
const DATES = {{ dates|tojson }};

// Whether the value in this cell was worked out rather than typed. It decides
// one thing — the muted italic `.derived` — and it used to be `!editable && why`
// written at that one site, which is the same answer for every column BUT the
// two dates: those show the scheduler's answer on one row and the file's own on
// the next, and the row says which (`row.stated`, `rows.py`).
//
// A column that is derived by construction stays derived however its cell reads,
// which is why `whyOf` is asked first: the appetite cell on a pitch draws what
// its tasks occupy, and that is computed whatever the file says.
function computedIn(row, key) {
  if (whyOf(row, key)) return true;
  return DATES.includes(key) && !!row[key] && !(row.stated || []).includes(key);
}

// What this cell is showing, on the columns where that is not what editing
// writes. A string is the whole answer; a pair is one sentence for the date the
// file states and one for the date the scheduler worked out, because a cell that
// draws either must not describe both as a forecast.
function showsIn(row, key) {
  const said = SHOWS[key];
  if (!said) return '';
  return typeof said === 'string' ? said : said[computedIn(row, key) ? 'derived' : 'stated'];
}

// Which kind may hold which — `model.PARENT_KINDS`, shipped rather than retyped.
// It decides three things on this page: which rows grow a handle, which rows
// light up as a drop would land, and which refuse before anything is sent.
const PARENT_KINDS = DATA.parent_kinds || {};
// Whether this row has anywhere to go. The top of the ladder belongs to nothing,
// so it can neither be filed under something nor taken out of it, and every
// control that would say otherwise is left undrawn rather than drawn and then
// refused. Which kind that is comes off `PARENT_KINDS` and is not written here:
// it was `project` until a `product` was added above it, and a rule that names
// the top rung is a rule that is wrong the day the ladder grows.
//
// And never while the stored `parent` names a record this table cannot show —
// `off_plan_parent`, the move gesture's `off_plan_deps`. The payload nulls the
// value (an inbox id may not reach this page's bytes), so a drop or the
// unparent bar would overwrite a line the table never drew, and the server
// could not tell that from the record page legitimately refiling it. Refused
// here, before anything is attempted, exactly as the graph refuses its edge
// gestures at tap time.
const movable = row =>
  !row.off_plan_parent && (PARENT_KINDS[row.kind] || []).length > 0;
// What a kind may be filed under, in the validator's own words. `a pitch or a
// project`, `nothing` — the sentence `_containment_problems` builds when it has
// already happened, said here before it can.
const holders = kind =>
  (PARENT_KINDS[kind] || []).map(one => 'a ' + one).join(' or ') || 'nothing';
const moveTip = row => row.off_plan_parent
  ? `${row.id} is filed under something this table cannot show — `
    + 'where it belongs is edited on its own page'
  : movable(row)
  ? `Drag by the grip, or press Enter, to file this under ${holders(row.kind)}`
  : `A ${row.kind} belongs to nothing, so there is nothing to file it under`;
// The handle itself. Two dotted rules drawn by the stylesheet and not a glyph:
// `⠿` is the conventional one and is not in the vendored face's latin subset, so
// on a machine with no webfont it is a tofu box — which is the same argument
// STATUS_GLYPH settles the other way, because those five had to be text.
// `aria-hidden`, because the keyboard does not reach for this: the cell it sits
// in is the tab stop and Enter on that cell is the same move (see `startMoving`).
const GRIP = '<span class="rowgrip" draggable="true" aria-hidden="true"></span>';

// Five tags wrapped to five lines and every row on screen grew to match, so one
// line and a count. The count is exact: "+2" means two you cannot see, not two
// the browser might have fitted in anyway.
//
// Written for tags, then needed again the moment tags were fixed: a task with
// three merged PRs is 128px tall against a 50px row, so the column that sets the
// height of the plan had simply moved one to the left. Any list in a cell has
// this shape, so the clamp takes rendered pieces and the noun to count them by.
//
// `pieces` are already markup — a caller hands it `list.map(esc)` or
// `list.map(prLink)` — which makes this the one function here that must NOT
// escape what it is given. Everything it adds of its own is a literal or a
// count, so nothing else on this line can carry stored text.
//
// The one visible piece is wrapped even when there is no badge beside it, because
// the wrapper is what can be given an ellipsis: the badge is the promise the
// clamp makes — "there are two more, here is where they are" — and it was the
// part being cut, by a third of itself under about 128px and by 368px on a
// sixty-character login. `.first` is the flex item that shrinks; the badge never
// does. See `td.clamp` in the stylesheet.
//
// Both words for the thing being counted, because the badge names a number of
// them and `+1` is as ordinary as `+4`. It used to be the singular and an `s`,
// which is how the control offering to show two more people offered "2 more
// persons".
//
// The badge is a *toggle*: `classList.add('open')` was the whole of the reveal
// and nothing anywhere took the class off again, so an expanded cell could only
// be collapsed by reloading the page. One cell is cheap enough to live with;
// with the column control beside it, one click opens seventeen and a one-way
// control that doubles the height of the table is a trap. So it carries both of
// its names — a control says exactly what it will do, and what this one will do
// changes with the cell it is in — and the sign in front of the count is drawn
// by the stylesheet from the same class that opens the cell, which is how the
// glyph and the state cannot come apart.
function clamped(pieces, one, many) {
  if (!pieces.length) return '';
  const [first, ...rest] = pieces;
  const shown = `<span class="first">${first}</span>`;
  if (!rest.length) return shown;
  const word = rest.length === 1 ? one : many;
  const expand = `Show ${rest.length} more ${word}`;
  return `${shown}<span class="rest">, ${rest.join(', ')}</span>` +
    `<button type="button" class="more" aria-label="${expand}" data-expand="${expand}"` +
    ` data-collapse="Show ${rest.length} fewer ${word}">${rest.length}</button>`;
}

// The two marks a row wears, off the payload rather than restated here.
// `GLYPHS` is what the graph and the timeline already draw; `RUNGS` below is the
// priority character, which the graph now draws too — a card's title carries the
// same two marks a row does, in the same order.
const GLYPHS = DATA.glyphs || {};
// The mark that goes in front of a word inside an `<option>`, which is text and
// nothing else — the same string `mark()` writes on the server, for both ladders.
const RUNGS = DATA.marks || {};
function markFor(field, value) {
  if (field === 'status') return GLYPHS[value] ? GLYPHS[value] + ' ' : '';
  if (field === 'priority') return RUNGS[value] ? RUNGS[value] + ' ' : '';
  return '';
}

function shown(row, key) {
  const value = row[key];
  // The title is the way into the shaping doc; the id is the way to cite it.
  // A cell can be a link and still be editable. Making everything editable first
  // is what silently turned the PR column into plain text.
  if (key === 'title') return `<a href="{{ links.record }}${esc(row.id)}">${esc(row.title)}</a>`;
  if (key === 'prs') return clamped((value || []).map(prLink), 'pull request', 'pull requests');
  // No kind chip here. `pitch-0c0001` already says pitch, in a prefix the model
  // guarantees agrees with the kind, so the chip was restating the first word of
  // the cell it sat in — seventeen times, in a column that is otherwise the
  // narrowest thing on the row. The id string is not boxed in its place either:
  // it is monospace, which is already what marks it as a token to be cited, and a
  // border round every id is the same noise wearing a different hat. Kind stays
  // filterable in the KIND facet, which is where "show me only tasks" is asked,
  // and stays a chip on the detail, people and cycle pages, where no id is
  // present to carry it.
  //
  // The grip in front of it is where a row is picked up from. Not the row
  // itself: a `draggable` row cannot have its text selected, and an id is the
  // one thing on this page people copy out of it — and the cell editor puts an
  // `<input>` inside a cell, which a draggable ancestor interferes with. So the
  // handle is a thing of its own, in the column that is the row's own name, and
  // it is in the frozen pair, so it is on screen however far the table is
  // scrolled sideways. A row that can go nowhere gets none: a project is the top
  // of the tree, and the missing handle is that said without a sentence.
  if (key === 'id')
    return (EDITABLE && movable(row) ? GRIP : '')
      + `<span class="eid">${esc(row.id)}</span>` + landingMark(row.id);
  // The same mark the graph and the timeline draw, in the chip the table already
  // had. The fill was the only channel here, and five fills on a luminance ladder
  // are separable but not nameable — the graph has said `»` for in-progress since
  // the day it was drawn and the table said nothing, so the two views keyed one
  // fact differently.
  //
  // Guarded on the value, exactly as `priority` below is, and it was the one of
  // the pair that was not: a rung that reads no status arrives with `null` here
  // (`unread_fields`, applied in `_row`), and an unguarded chip drew the ladder's
  // ground colour behind an empty word — a product wearing a status it does not
  // have and cannot be given. jcanton, 2026-08-25: "a product has no status, but
  // in the table the status cell has a chip with background and color, that
  // should not be there".
  if (key === 'status')
    return row.status
      ? `<span class="chip ${stClass(row.status)}">` +
        `<span class="chipmark" aria-hidden="true">${esc(GLYPHS[row.status] || '')}</span>` +
        // The word in its own element so a narrow column can drop it and keep
        // the mark. A bare text node cannot be hidden without hiding the mark
        // with it.
        `<span class="chipword">${esc(human(row.status))}</span></span>`
      : '';
  // Bars and the word. The bars are what the eye picks out of a column of
  // fifteen rows; the word is what settles which rung it is. Priority was text
  // alone here while the graph drew it as line thickness — one fact, two views,
  // no shared notation, and nothing on either page saying so.
  if (key === 'priority')
    return row.priority
      ? `<span class="chip pri pri-${esc(row.priority)}">` +
        `<span class="chipmark" aria-hidden="true">${esc(RUNGS[row.priority] || '')}</span>` +
        `<span class="chipword">${esc(human(row.priority))}</span></span>`
      : '';
  // Counted out of the body's own checklist. Empty where there is no checklist,
  // rather than "0/0" — a body nobody has written a list in has no progress to
  // report, which is not the same as no progress.
  //
  // The bar alone. `6/16 items` beside it was the widest thing in the column and
  // is the one number nobody reads at a glance — the bar is what a column of
  // fifteen rows is scanned for. The count is on the card, in full, beside what
  // it was counted from, and in this cell's own tooltip for a reader who wants it
  // without leaving the row.
  if (key === 'progress')
    return row.progress === null ? '' :
      `<span class="meter" title="${esc(row.progress_text)}"><span style="width: ` +
      `${Math.round(row.progress * 100)}%"></span></span>`;
  if (key === 'tags') return clamped((value || []).map(esc), 'tag', 'tags');
  // Nobody named here, and somebody named underneath: a pitch whose tasks each
  // have a reviewer is reviewed, and the validator has stopped asking it for one
  // of its own. Drawn rather than left blank, because a column that is empty on
  // the row and answered a level down is a column that reads as a gap.
  if (key === 'reviewers' && !(value || []).length && (row.reviewers_from || []).length)
    return clamped(row.reviewers_from.map(esc), 'person', 'people');
  // Every list in the table clamps, for the same reason and by the same badge.
  // These two were the last that did not, and they were most of the wrapping
  // left: `OngChia, nfarabullini, jcanton` took three lines in a 159px column and
  // the whole row grew to match, which is the defect the tags clamp was written
  // for. The owner is the name that matters and it has its own column; the rest
  // are one click away, where they always were.
  if (key === 'assignees' || key === 'reviewers')
    return clamped((value || []).map(esc), 'person', 'people');
  // A date, short. `2026-07-14` is ten characters and two of them are the century;
  // on a laptop the two date columns were 22 characters of a fourteen-column
  // table and every one of them wrapped onto a second line. `26.07.14` says the
  // same thing in eight, and the column tightens to `07.14` when even that will
  // not fit — the year is the one part a reader can almost always supply.
  //
  // The stored value is untouched: this is the cell's text, the row still carries
  // the ISO string, and the sort still reads that.
  if (DATES.includes(key)) return value ? shortDate(value) : '';
  // A record with work under it shows what that work occupies — `5.6 in tasks`,
  // the record page's own sentence for the same number — and not the bet it was
  // made at. The bet is not printed beside it: jcanton, 2026-08-27, "the colour
  // already says whether it is under, level or over, so repeating the bet is a
  // number for nothing". Nor are the records that make up the sum named, for the
  // reason the table needs no help saying it: they are the rows directly
  // underneath, because this is a tree.
  //
  // The mark leads, so a column of these reads as one column of verdicts rather
  // than as numbers with something after them — and it is first inside the cell
  // for the same reason the status chip's mark is.
  //
  // Named, not `aria-hidden` like the chip's mark: there the word beside it says
  // the same thing, and here the words are `5.6 in tasks`, which is the one half
  // of this cell that does NOT say whether the bet fits. A reader who cannot see
  // the tint would otherwise be given the number and no reading of it. The
  // sentence is the row's own, so the mark, the ground and the tooltip are three
  // channels of one value rather than three that could come apart.
  const rollup = rollupOn(row, key);
  if (rollup)
    return `<span class="rollmark" role="img" aria-label="${esc(rollup.why)}"` +
      `>${esc(ROLLUP_GLYPH[rollup.state] || '')}</span>${esc(rollup.text)}`;
  // Unreachable for `reviewers`, which is handled above — kept as one line so
  // the two list columns stay one branch.
  return esc(stored(row, key));
}

// `2026-07-14` as `26.07.14`, or as `07.14` once the column is told to tighten.
// Dots and not dashes: a dash is what the ISO string uses and this is not it, and
// at 13px the dot is the narrower separator.
function shortDate(iso) {
  const [year, month, day] = String(iso).split('-');
  if (!day) return esc(iso);
  // Day first. jcanton, 2026-08-21: "I'd like to reverse the order of the dates
  // in the entire app... to dd.mm and dd.mm.YY dd.mm.YYYY" — which is how these
  // are read aloud here, and the order every date on the page now uses.
  //
  // The year is its own element and trails, so the column drops it when it
  // tightens: `14.07` is still a date read the same way round, where `07.14`
  // with the year gone reads as a different day.
  return `${esc(day)}.${esc(month)}<span class="dateshort">.${esc(year.slice(2))}</span>`;
}

// What a clamped cell is not showing, in words, for the cell's own tooltip.
//
// Four columns draw one value and a `+N`, and the only way to read the rest was
// to click the badge — while hovering the cell answered a question nobody had
// asked, "Double-click to edit assignees". So the answer to the question they did
// ask goes first. The badge is untouched: this adds a way to *read* the hidden
// values, it does not replace the way to reveal them.
//
// Capped, because a native tooltip has no scrollbar and cannot be scrolled: sixty
// tags in one is a wall of text with the instruction lost at the bottom of it. The
// cap is on characters rather than on a count, because the values differ by an
// order of magnitude in width — `ci` and `C2SM/icon4py#1223` are both one item —
// and what has to fit is a line, not a number of things. At least one always
// prints, however long it is, or a single very long value would come back as
// nothing but a count of itself.
const TIP_CHARS = 160;
function hiddenBy(row, key) {
  if (!CLAMPED.has(key)) return '';
  // The stored values, not the rendered ones: a PR cell draws `#1223` because the
  // repository never varies, but a tooltip has room to say which one it is.
  const rest = [].concat(row[key] ?? []).map(String).slice(1);
  if (!rest.length) return '';
  const fits = [];
  let length = 0;
  for (const value of rest) {
    if (fits.length && length + value.length + 2 > TIP_CHARS) break;
    fits.push(value);
    length += value.length + 2;
  }
  const over = rest.length - fits.length;
  // `+2 more`, in the badge's own words, so the line reads as the answer to the
  // badge the reader is looking at rather than as a list from nowhere.
  return `+${rest.length} more: ${fits.join(', ')}${over ? ` … and ${over} not shown` : ''}`;
}

// The four shapes a level of the tree can be drawn as. An allowlist and not a
// pass-through, because `treeHtml` is called a second time with a value read
// back off the DOM — see `openEditor` — and this page's rule is that a value
// crossing back into markup is checked against what it is allowed to be rather
// than against what it must not.
const TREE_RUNGS = new Set(['line', 'blank', 'tee', 'end']);

// One space-separated rung name per level, as the drawing. One function, because
// the cell editor has to put the drawing back: `openEditor` replaces the whole
// of a cell's contents with an input, and a connector that disappears for as
// long as somebody is typing a title reads as the tree having lost the row.
function treeHtml(rungs) {
  const each = String(rungs || '').split(' ').filter(one => TREE_RUNGS.has(one));
  if (!each.length) return '';
  return '<span class="tree" aria-hidden="true">' +
    each.map(one => `<span class="rung ${one}"></span>`).join('') + '</span>';
}

// **The cells a bulk edit will write, as record ids and one column.**
//
// **Declared here, above `cell()`, and the position is load-bearing.** `const`
// is not hoisted, `cell()` reads `PICKED` on every draw, and `draw()` runs while
// this script is still being evaluated. Written further down — beside the
// functions that use them, which is where they were first put — the very first
// draw threw a ReferenceError out of the temporal dead zone: the table drew
// nothing at all, on every load, with one console line as the only symptom, and
// six unrelated browser tests failed saying "the page reported nothing".
//
// Ids and not elements, for the reason `AT` is a row id and a column: `draw()`
// replaces every cell after every save, so an element held here is detached by
// the time anything reads it. `cell()` puts the class back from this set on the
// way past.
//
// ONE column, and that is the safety model rather than a convenience. A
// selection that could span columns is a selection that can write a status into
// an appetite, and the gesture that would do it — dragging across a row — is the
// one people make by accident. Picking a cell in a different column REPLACES the
// selection, so the wrong thing is not reachable at all.
const PICKED = new Set();
let PICKED_FIELD = null;
// Where a shift range measures from: the last cell picked without shift, which
// is what every list in every file manager means by an anchor.
let PICKED_FROM = null;

function cell(row, key, place) {
  const mark = (MARKS[row.id] || {})[key];
  const note = mark ? mark.messages.join(' · ') : '';
  const ground = mark ? 'sev-cell-' + SEV_CLASS[mark.severity] : '';
  // role="img" with a name, not a bare character: the message was reachable only
  // by hovering the row, and a tooltip is not something a table gets hovered for.
  const glyph = mark
    ? ` <span class="sev-mark sev-mark-${SEV_CLASS[mark.severity]}" role="img"` +
      ` aria-label="${esc(note)}" title="${esc(note)}">⚠</span>`
    : '';
  // A clamped cell is one line laid out in a row: the value, which gives up
  // width, and then the badge and the severity glyph, which do not. The wrapper
  // is what makes that a row — a `td` cannot be the flex container itself
  // without ceasing to be a table cell — and it holds the glyph too, or the mark
  // that says which cell is wrong drops to a second line and takes the row's
  // height with it.
  // The tree, in the column that holds the row's own words. Not the id column
  // beside it: an id is a token to be cited, monospace and the same width on
  // every row, and indenting it would make the one column that is a straight
  // list of names into a ragged one. The title is a sentence and already ragged.
  //
  // `aria-hidden`, and it is a wrapper around empty spans rather than characters:
  // there is nothing here to read out. A screen reader gets the tree from the
  // rows themselves — the parent is a field of the record and the title opens it
  // — and what it would get from the drawing is "box drawings light up and
  // right" in front of every child's title.
  //
  // Drawn first inside the cell and taken out of flow by the stylesheet, so the
  // link keeps the whole of the cell's content box: the indent is padding on the
  // cell, which is what puts it in the fit's measurement of the column.
  const rungs = key === 'title' && place ? place.rungs.join(' ') : '';
  // Nothing to clamp is nothing to wrap. The four clamped columns wrapped
  // unconditionally, so every row with no assignees, no reviewers, no PRs and no
  // tags carried four empty `<span class="clamped">`s — inert, and a lie to
  // anything that asks what a cell holds: a product row that reads as empty was
  // drawing four of them, which is how `test_a_products_row_is_empty_...` found
  // this while looking for a chip.
  const inner = shown(row, key) + glyph;
  const body = treeHtml(rungs)
    + (CLAMPED.has(key) && inner ? `<span class="clamped">${inner}</span>` : inner);
  // The field this column writes, which is the column itself for all but two.
  // `reads` is asked about the FIELD and not the column, so a product's size cell
  // is refused because a product reads no `person_weeks` — the rule that was
  // already there, reached by the right name.
  const field = fieldOf(key);
  // A cell that has a reason it cannot be edited is not editable, and that is
  // the whole of the rule rather than a second list beside `EDITABLE`. It is
  // what makes a rollup's size cell read-only without teaching this page a
  // second way for a cell to be closed: `whyOf` is the one answer, and the four
  // reads below take it from there.
  const why = whyOf(row, key);
  const rollup = rollupOn(row, key);
  const editable = EDITABLE && field in EDITABLE && reads(row, field) && !why;
  // One class list rather than three returns. The tags clamp used to be written
  // only into the editable branch, so on a rendered file the column kept the
  // reveal button and showed every tag beside it anyway.
  const classes = [
    editable ? 'edit' : '',
    // The value in this cell was worked out rather than typed. `computedIn` and
    // not `!editable && why`, which was the same answer by a narrower route:
    // being a control and being a forecast are two questions, and the two date
    // columns are both — a scheduled start is muted and italic like every other
    // computed value, and the same cell showing the date this record's own file
    // states is left in the page's ink, because it is not a forecast.
    computedIn(row, key) ? 'derived' : '',
    // How this record's contents read against the box its bet bought. The class
    // is written for every state and the stylesheet paints only what it should:
    // `under` and `unsized` have a ground of their own, `level` shares the
    // declaration `.inherited` already carries, `unbet` is drawn plain because
    // there is no box to read against — and `over` takes the severity fill,
    // because the warning `_rollup_problems` yields about exactly that
    // comparison already reaches this cell through `MARK_COLUMN`. A second warn
    // ground written for it would be a second copy of one colour, and the only
    // thing two copies of a colour can do is disagree.
    rollup ? 'roll-' + rollup.state : '',
    CLAMPED.has(key) ? 'clamp' : '',
    // Inherited, not typed. The ground says the value came from the work under
    // this record rather than from its own file, which is the difference between
    // "these are the reviewers" and "these are the reviewers, and changing them
    // means changing the tasks".
    key === 'reviewers' && !(row.reviewers || []).length
      && (row.reviewers_from || []).length ? 'inherited' : '',
    // Something is still in the way. Only where there is: a column tinted on
    // every row says nothing, and the value of this is that the few tinted cells
    // are the ones worth looking at. Written beside the number rather than as a
    // CSS rule on the text, so the tint cannot outlive the count — the row is
    // rebuilt from the index after every write, and a blocker that has just been
    // marked done takes its ground with it.
    key === 'blocked_by' && row.blocked_by > 0 ? 'waiting' : '',
    // In the selection a bulk edit will write. Read from `PICKED` at draw time
    // rather than kept on the element, because `draw()` replaces every cell in
    // the table after every save — a class put on a node is gone the next time
    // anything happens, which is exactly when a selection has to survive.
    PICKED.has(row.id) && field === PICKED_FIELD ? 'picked' : '',
    ground,
  ].filter(Boolean).join(' ');
  // The field's name and not the column's, so the size column's tooltip and the
  // box it opens both say "appetite" — a control that is called one thing on the
  // way in and another once it is open is two controls to a reader.
  const named = (FIELD_LABELS[field] || field).toLowerCase();
  // Three lines at most, in the order of what a reader wants: what is wrong here,
  // what is hidden here, what can be done here. A native `title` takes newlines,
  // so they are three lines and not a run-on sentence.
  //
  // The problem no longer *replaces* the rest, it goes first. It used to be the
  // whole tooltip, which meant that a cell with a blocker on it and a `+2` beside
  // it answered neither "who are the other two" nor "how do I fix this" — and the
  // fix for most of these problems is to edit the cell the sentence is on.
  //
  // A cell hiding nothing gets no second line: every tooltip in the table growing
  // a redundant sentence is how a tooltip stops being read at all.
  //
  // The id column's line is what the handle beside it cannot say: a drag is a
  // gesture with no name on it, and the same cell is where Enter picks the row
  // up. A row that can go nowhere says that instead, which is also why it has no
  // handle to explain.
  const tip = [note, hiddenBy(row, key),
               key === 'reviewers' && !(row.reviewers || []).length
                 && (row.reviewers_from || []).length
                 ? 'From the work filed under this record. Editing names reviewers of its own.'
                 : '',
               // What the cell is showing, on the two columns where that is not
               // what editing writes. Before the sentence about editing, because
               // it is the answer to "why is this number here" and the other is
               // the answer to "how do I change it".
               editable ? showsIn(row, key) : '',
               editable ? 'Double-click to edit ' + named
                        : key === 'id' && EDITABLE ? moveTip(row) : why]
    .filter(Boolean).join('\\n');
  // Reachable without a mouse. This table is the app's primary editing surface
  // and it was double-click-only, so half the room could not change a single
  // field on it. `-1` rather than `0`: `rove()` promotes exactly one cell, so
  // the grid is one tab stop with the arrows moving inside it — fourteen columns
  // times forty rows is 560 stops if every cell takes one, which is not a
  // keyboard path, it is a maze.
  //
  // The id cell joins them, and it is not editable: it is the one place a move
  // can be started without a mouse, and a gesture that only a mouse can make is
  // a gesture half the room does not have.
  const reachable = EDITABLE && (editable || !!why || key === 'id');
  // `row.id` is escaped like anything else here. An id that fails its pattern is
  // a *reported* blocker and not a refusal, so the record still loads and still
  // draws a row: one shaped `task-000001"><img src=x onerror=…>` put ten
  // elements into the table body while the text beside them read correctly.
  return `<td data-col="${key}"` +
    `${editable ? ` data-record="${esc(row.id)}" data-field="${esc(field)}"` : ''}` +
    `${!editable && why ? ` data-why="${esc(why)}"` : ''}` +
    `${rungs ? ` data-rungs="${esc(rungs)}"` : ''}` +
    `${reachable ? ' tabindex="-1"' : ''}` +
    ` class="${classes}"${tip ? ` title="${esc(tip)}"` : ''}>${body}</td>`;
}

// `#1223`, not `C2SM/icon4py#1223`. Every reference in a plan is to the repository
// the plan is about, so the owner and the name were seventeen rows of the same
// eleven characters — the widest column on the page spent on the part that never
// varies. It cost the sentence beside it: `title` was squeezed to its floor while
// `prs` kept 172px, and at the window this was reported on the table still would
// not fit. The whole reference is in the link's title, and the detail page prints
// it in full, so nothing is lost — a plan that does span two repositories reads a
// little thinner here and exactly the same everywhere else.
function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${esc(repo)}/pull/${esc(number)}"` +
    ` title="${esc(ref)}">#${esc(number)}</a>`;
}

// What the id cell says about whether this row's last save has reached GitHub.
// In the id column because that pair is frozen: the mark is on screen however
// far the table is scrolled sideways, beside the row's own name.
//
// Both states are the same drawn ring, not characters — `.rowgrip`'s argument:
// a glyph outside the vendored latin subset is a tofu box on a machine without
// a font that has it, and a drawing follows the theme instead. Hollow and
// muted while the commit is real here and not yet inked on GitHub; FILLED in
// the blocker colour once the pusher parks it on a branch, the branch named
// where every problem puts its sentence. One device, escalating in place —
// hollow against filled is a shape, so it survives colour-blindness — and
// deliberately not a second `sev-mark`: a record with a validation problem
// already wears ⚠ beside its id, and two identical glyphs meaning two
// different things read as a stutter (seen in the screenshot, not guessed).
function landingMark(id) {
  const branch = STRANDED.get(id);
  if (branch !== undefined) {
    const said = `Saved here, but it could not land on GitHub's main — parked on ${branch}. `
      + 'There is a pull request to resolve it.';
    return ` <span class="stranded" role="img"` +
      ` aria-label="${esc(said)}" title="${esc(said)}"></span>`;
  }
  for (const held of UNLANDED.values()) {
    if (held !== id) continue;
    const said = 'Saved here — not on GitHub yet.';
    return ` <span class="unlanded" role="img" aria-label="${said}" title="${said}"></span>`;
  }
  return '';
}

function rowHtml(place) {
  const row = place.row;
  // The stripe says "something on this row is wrong" before a single cell is
  // read; the glyph in the cell says which thing. The message used to live only
  // in a native tooltip on the row, where it was found by accident or not at all.
  // Both survive the dimming below: a row kept only as context can still be the
  // row with the problem on it.
  const worst = TROUBLE[row.id];
  const classes = [
    worst ? 'sev-row-' + SEV_CLASS[worst] : '',
    place.depth ? 'd' + place.depth : '',
    place.context ? 'context' : '',
    // A write this row is waiting on. Against a plan on the other side of the
    // world that is a fetch, a commit and a push — seconds — and for all of them
    // the page said nothing at all and the row sat where it was, which reads as
    // a drop that did not take.
    row.id === WRITING ? 'writing' : '',
  ].filter(Boolean).join(' ');
  return `<tr data-id="${esc(row.id)}"${classes ? ` class="${classes}"` : ''}>` +
    keys.map(key => cell(row, key, place)).join('') + '</tr>';
}

// Three ways for a table to be empty, and they rendered identically: a header
// row over nothing, which reads as a broken app whichever one it is. Which one
// it is decides what to do next, so the table says which one it is.
function emptyRow() {
  let headline = 'No record matches these filters.';
  let detail = 'Every row is filtered out by the controls above.';
  let clearable = true;
  if (!LOADED) {
    headline = 'The plan could not be loaded.';
    detail = 'This page arrived without its data, so there is nothing to filter or sort.';
    clearable = false;
  } else if (!Object.keys(DATA.rows).length) {
    headline = 'This plan has no records yet.';
    detail = 'Nothing has been pitched, shaped or scheduled.';
    clearable = false;
  } else if (queryError()) {
    // A fourth way to be empty, and the only one the reader caused a keystroke
    // ago. Said here as well as in the bar because this is where the rows were:
    // one sentence, from one function, in the two places a person is looking.
    headline = 'That search cannot be read.';
    detail = esc(queryError()) + '.';
  }
  return `<tr class="nothing"><td colspan="${keys.length}">` +
    `<p class="headline">${headline}</p><p class="hint">${detail}</p>` +
    (clearable ? '<button type="button" id="clear-filters">Clear filters</button>' : '') +
    '</td></tr>';
}

// --------------------------------------------------------------------------
// The tree
//
// A plan is a tree — a project holds pitches, a pitch holds tasks, and a task
// can hang straight off a project — and the table drew it as a flat list of
// seventeen rows sorted by id, which is the tree's own order with the shape
// rubbed off it. Three things put the shape back, and each is narrower than it
// first looks.
// --------------------------------------------------------------------------

// The deepest indent drawn. `PARENT_KINDS` bounds the real answer at two — a
// task under a pitch under a project — and a task hanging off a project is one,
// so this is a cap on a hand-edited file rather than a design for four levels.
// A row deeper than this is drawn at this depth: the indent is a hint about
// where a row sits, and it is not worth a title column's width to be exact about
// a shape the validator is already complaining about.
const TREE_DEPTH = 3;

// Every ancestor of every match, whether or not it matched.
//
// A record that is not an answer to what was asked but *holds* one stays on the
// table, dimmed: filtering to `owner=ann` and getting three tasks with no pitch
// over them is a list of tasks, not a plan, and the row that says which pitch
// they are part of is the one a person is about to want. It is a record like any
// other while it is there — its title still opens it, its cells still edit — it
// simply is not an answer, and `summarise` never counts it as one.
function withAncestors(rows) {
  const kept = new Map(rows.map(row => [row.id, row]));
  for (const row of rows) {
    // Guarded, because a parent chain somebody hand-edited into a loop is a hang
    // rather than a blocker, and the page would take the whole plan with it.
    const seen = new Set([row.id]);
    let at = DATA.rows[row.parent];
    while (at && !seen.has(at.id)) {
      seen.add(at.id);
      kept.set(at.id, at);
      at = DATA.rows[at.parent];
    }
  }
  return [...kept.values()];
}

// Roots in id order, children in id order under each root, depth first.
//
// A childless project sits exactly where its id puts it: this is one rule and
// not five buckets, and "projects with children, then projects without" would be
// a second ordering nobody asked for on top of the one that is on screen.
//
// Descending reverses the siblings at every level and never the walk: a tree
// with the children above their parent is not the same tree upside down, it is a
// list of rows in an order that means nothing.
function ordered(rows, descending) {
  const by = new Map(rows.map(row => [row.id, row]));
  const kids = new Map();
  const roots = [];
  for (const row of rows) {
    const parent = by.has(row.parent) ? row.parent : null;
    if (parent) kids.set(parent, (kids.get(parent) || []).concat(row.id));
    else roots.push(row.id);
  }
  const order = ids =>
    [...ids].sort((a, b) => a.localeCompare(b) * (descending ? -1 : 1));
  const out = [];
  const drawn = new Set();
  const walk = (id, depth) => {
    if (drawn.has(id)) return;
    drawn.add(id);
    out.push({row: by.get(id), depth: Math.min(depth, TREE_DEPTH), rungs: [], context: false});
    for (const child of order(kids.get(id) || [])) walk(child, depth + 1);
  };
  for (const id of order(roots)) walk(id, 0);
  // A loop in the parent chain leaves its members with no root to be reached
  // from. They are drawn flat at the end rather than dropped: a row missing from
  // the table is a row nobody can use the table to fix the loop with.
  for (const id of order(by.keys())) walk(id, 0);
  return out;
}

// Which connector each row draws, computed from the rows that are actually being
// drawn and never from the plan.
//
// That is the whole of this function's difficulty. A pitch whose last task the
// filter removed would otherwise keep a `├─`, promising a sibling under a row
// that ends the branch, and the row above the gap would carry a `└─` that is
// simply untrue. What is on screen is what the connectors describe.
//
// `line` is a level whose branch continues past this row, `blank` one whose
// branch is finished, `tee` a child with a sibling still to come and `end` the
// last child drawn. They are class names: the glyphs are drawn as borders in the
// stylesheet, because `├─` and `└─` only line up in a monospace face — this
// column is proportional — and a screen reader says "box drawings light up and
// right" before every child's title.
function connectors(placed) {
  // Whether each row is the last one drawn at its own level. Depth first means a
  // row's own subtree is the run of deeper rows after it, so the next row that
  // is not deeper answers it.
  const last = placed.map((one, i) => {
    for (let j = i + 1; j < placed.length; j++) {
      if (placed[j].depth < one.depth) return true;
      if (placed[j].depth === one.depth) return false;
    }
    return true;
  });
  const continues = [];
  placed.forEach((one, i) => {
    const rungs = [];
    for (let level = 1; level < one.depth; level++)
      rungs.push(continues[level] ? 'line' : 'blank');
    if (one.depth) rungs.push(last[i] ? 'end' : 'tee');
    continues[one.depth] = !last[i];
    one.rungs = rungs;
  });
}

function draw() {
  const sort = params.get('sort') || 'id';
  const descending = params.get('desc') === '1';
  // A status and a priority are sequences, not words: sorted as text, `done`
  // heads the status column and `high, low, medium` is not an order anybody
  // means by priority. Everything else really is alphabetical.
  const rank = DATA.choices[sort];
  // A column sorts by the number it is showing. On `size` those are two
  // different numbers on a row with work under it — the cell draws what the
  // tasks occupy and the field holds the bet — and sorting a column of `5.6 in
  // tasks` by a bet nobody can see puts a row between two others for a reason
  // that is nowhere on the page. Every other column shows its own field, so this
  // reaches exactly the rows the cell reads differently on.
  const shownBy = row => rollupOn(row, sort) ? rollupOn(row, sort).weeks : row[sort];
  const key = rank
    ? row => String(rank.indexOf(row[sort])).padStart(3, '0')
    : row => String(shownBy(row) ?? '');
  const found = Object.values(DATA.rows).filter(matches);
  // The tree is the id sort's, and no other column's. Sorted by owner, a parent
  // is wherever its owner's name falls and its children are three screens away:
  // an indent that does not point at the row above it is a decoration, and a
  // connector drawn between two rows that are not related is a lie about the
  // plan. So every other column sorts flat — no indent, no connectors, and no
  // ancestors kept for a context they could not provide — which is what those
  // columns were always for.
  let placed;
  if (sort === 'id') {
    placed = ordered(withAncestors(found), descending);
    connectors(placed);
    const answers = new Set(found.map(row => row.id));
    for (const one of placed) one.context = !answers.has(one.row.id);
  } else {
    const rows = found.slice().sort((a, b) => key(a).localeCompare(key(b)));
    if (descending) rows.reverse();
    placed = rows.map(row => ({row, depth: 0, rungs: [], context: false}));
  }
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
  // The `+` row is drawn after whatever the filters left, including after the
  // three empty states: a plan with nothing in it is exactly when the way to put
  // something in it has to be on screen. It is never filtered — it stands for a
  // row that does not exist yet, and nothing that does not exist can match a
  // filter — and on a rendered file it is not drawn at all, because a file has
  // no server to create anything with.
  tbody.innerHTML = (placed.length ? placed.map(rowHtml).join('') : emptyRow())
    + (EDITABLE ? adderHtml() : '');
  if (EDITABLE) {
    rove(null, held);
    RETURN = false;
    sayDraft();
    markTargets();
    // Every element the last row holds is new, so what it is saying has to be
    // said again — this is the redraw that used to blank it mid-move.
    sayMoveOut();
  }
  // How many rows answered the question, which is not how many are drawn: an
  // ancestor kept for context is on screen because of something else that
  // matched, and counting it would make "4 of 17 shown" mean two things at once
  // — the second of which nobody asked for.
  document.getElementById('shown').textContent = found.length;
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
  // Every cell here is new, so every one of them is closed: the column controls
  // are told what they are looking at rather than left saying `−` over a column
  // a sort just collapsed. It is also the whole of "this does not persist" — a
  // redraw is where the state goes, and there is nowhere else it is kept.
  syncExpanders();
}
// The control bar changed the query string; what that means to a table is a
// redraw, and to the graph beside it a different set of nodes.
addEventListener('openproj:filter', draw);

// --- the card, on the title ------------------------------------------------
//
// The body is the one field a row does not show, and in this tool the shaping
// document IS the record — so the title is the cell it hangs off. The same card
// the graph and the timeline draw; see `_SHELL`.
//
// Outside `if (EDITABLE)` on purpose: a rendered file is the copy somebody reads
// on a train, and it is the copy that most needs a way to see what a row is about
// without opening seventeen documents. There the card has no server to ask for a
// body and draws the row's own fields, and the title beside it is still a link
// into `detail.html#id`.
tbody.addEventListener('pointerover', event => {
  const cell = event.target.closest('td[data-col="title"]');
  const row = cell && cell.closest('tr[data-id]');
  // Not over an open editor, and not in the middle of a move: in both the
  // pointer is doing something, and a box under it is in the way of the thing
  // being done.
  if (!row || cell.querySelector('input, textarea') || MOVING) return hideCard();
  const held = DATA.rows[row.dataset.id];
  if (held) queueCard(held, event.clientX, event.clientY);
});
tbody.addEventListener('pointerout', event => {
  if (event.target.closest('td[data-col="title"]')) hideCard();
});
// A cell that opens for editing under a card, and a redraw that replaces the row
// the card is describing: neither is a pointer leaving anything, so neither fires
// `pointerout`.
addEventListener('openproj:filter', hideCardNow);

// The row a write is in the air for, or null. One at a time, because one drag is
// one drop: this is not a queue, it is the row the reader is looking at.
//
// Declared out here rather than beside `reparent`, which is where it is set, and
// outside the editable branch, which is where writes live. `rowHtml` reads it on
// the first draw: further down the file it is in its dead zone then, and inside
// the branch it does not exist at all on a rendered file — both of which are a
// page that throws before a single row is drawn.
let WRITING = null;

// The commits this tab has saved that no landing has confirmed yet, commit sha
// to row id, in the order their answers arrived — which is ancestry order,
// because every save here goes out against the last answer. That order is what
// lets a landing clear by name: a frame naming one of these shas as landed has
// confirmed everything at or before it, and a mark must clear by name because
// recovery re-mints shas — its own sha may never appear on main while its
// content lands anyway (design/deferred-push.md, "Confirmation cannot be 'my sha
// is on main'").
//
// And the rows whose commit the pusher PARKED on a branch, row id to branch
// name: not a clear, a problem — the content is on GitHub but not on main, and
// nothing on this page resolves that. Both live out here for `WRITING`'s
// reason: `landingMark` reads them on every draw, and on a rendered file they
// simply stay empty.
const UNLANDED = new Map();
const STRANDED = new Map();

// Which fields a row's own kind does not read. `_row` already withholds their
// VALUES, so the cells were empty; what they still carried was an editor. A
// product's status cell was blank, double-clickable, tooltipped "Double-click to
// edit status", and on Enter it wrote `status` into a file whose model has no
// such field — a write the validator then reports as a blocker on a record
// nobody meant to break. The draft row has declined to offer these since
// `_new_row_fields` was written; a stored row is the copy that did not.
//
// Outside the `editable` branch below because a rendered file has no `EDITABLE`
// at all and `cellHtml` reads both: one of them being null is what makes every
// cell plain text there, and this must not throw before it gets there.
const UNREAD = DATA.unread || {};
// One question, asked in the one place that decides whether a cell has an editor
// and in the tooltip that promises one.
const reads = (row, key) => !(UNREAD[row.kind] || []).includes(key);

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

// What this status will make the server refuse the row without, and the row has
// not got. `DATA.required` is `required_at()`, which is derived from the gate
// rather than written beside it — the same map the detail page marks its labels
// from.
//
// `review_waived` is honoured here for the reason it is honoured there: it is the
// escape hatch from the reviewer rule, and asking for reviewers on a row that has
// waived them is a nag rather than a question.
function missingFor(row, status) {
  return Object.entries((DATA.required || {})[row.kind] || {})
    .filter(([field, statuses]) => statuses.includes(status))
    .map(([field]) => field)
    .filter(field => EDITABLE[field] && !(field === 'reviewers' && row.review_waived))
    .filter(field => !holds(row, field));
}

// Whether this row has a value for that field at all. Lifted out of the filter
// above because `saveCells` now asks the same question of a whole selection
// before it writes one answer across it, and the four ways a field can be unset
// — absent, null, the empty string, the empty list — are not a list anybody
// would write out twice and get right twice. An `assignees: []` that read as a
// value would be a row silently exempted from a gate; an `assignees: []` that
// read as unset in one copy and as a value in the other would be a row the panel
// asks about and then refuses to write.
function holds(row, field) {
  const value = row[field];
  return !(value === null || value === undefined || value === ''
    || (Array.isArray(value) && value.length === 0));
}

// Fields a span is computed from. Editing one of these from the table changes
// `start` and `end`, which are columns nothing in the browser can work out — so
// the rows are re-read from the server rather than patched in place.
// `end_date` is in it for a reason of its own rather than by symmetry: a done
// record's span ENDS at the date it records, so answering the panel changes the
// End column of a row whose Status cell is what was clicked. Left out, the row
// would go on showing the start date in both date columns, styled `derived` like
// a real forecast, until a reload. The End cell is a control of its own now, and
// the same entry covers it — a date typed there is a date the scheduler ends the
// span at, so the row has to come back from the server rather than be patched.
const DERIVES_DATES = new Set(['start_date', 'end_date', 'person_weeks', 'cycle']);

// The one question a status change is allowed to ask. It is asked BEFORE the
// write, so the answer travels in the same PATCH as the status: a row that goes
// `in_progress` and then has a date added is two commits, and for the length of
// the first one the plan holds a record the validator refuses.
//
// `commit` is what to do with the answers, and it is a parameter because the
// panel now serves both write paths. One cell hands back `saveCell`; a
// selection hands back `saveCells`, whose whole gesture is one answer written
// over every picked row in one commit. The alternative was a second panel with
// the same markup, the same keyboard handling and the same prefill, which is
// the shape that lets one of the two quietly stop prefilling.
//
// `about` is the sentence over the boxes. A selection has to say how far the
// answer reaches, because "Done needs this" over one date box, above a table
// with nine rows marked, does not say that all nine are about to get it.
function askFor(cell, status, fields, commit, about) {
  const panel = document.getElementById('askfor');
  const named = fields.map(field => {
    const label = FIELD_LABELS[field] || field;
    const type = EDITABLE[field] === 'date' ? 'date' : 'text';
    // Every date this panel can ask for is prefilled with today, and the rule is
    // the TYPE rather than a list of field names — which is what it was, naming
    // `start_date` alone, so `end_date` arrived beside it offering an empty box
    // in the one place the answer is nearly always today. A status change is a
    // statement about now: the work started today, or it finished today. Any
    // other field is left blank, because there is no value a form may guess at
    // for an owner or an appetite.
    const value = EDITABLE[field] === 'date' ? today() : '';
    // `data-type` and `data-suggest` are what `openEditor` writes on the box it
    // builds, for the same widget: `data-type` is not decoration — the widget
    // reads `dataset.type === 'list'` to complete the last comma-separated
    // token, and without it picking a second assignee replaced the first.
    const suggest = SUGGESTS[field];
    return `<label>${esc(label)}` +
      `<input type="${type}" data-field="${esc(field)}"` +
      ` data-type="${esc(EDITABLE[field])}"` +
      `${suggest ? ` data-suggest="${esc(suggest)}"` : ''} autocomplete="off"` +
      ` value="${esc(value)}"></label>`;
  }).join('');
  panel.innerHTML =
    `<p class="asking">${esc(about ||
      `${human(status)} needs ${fields.length === 1 ? 'this' : 'these'}`)}` +
    `</p>${named}` +
    `<span class="acts"><button type="button" id="asked" class="primary">Save</button>` +
    `<button type="button" id="unasked">Cancel</button></span>`;
  panel.hidden = false;
  const box = cell.getBoundingClientRect();
  panel.style.left = Math.max(8, Math.min(box.left, innerWidth - panel.offsetWidth - 8)) + 'px';
  panel.style.top = Math.min(box.bottom + 6, innerHeight - panel.offsetHeight - 8) + 'px';
  // The same autocomplete every other box on this page has. `attachSuggest` runs
  // over the page once at load, so a box built at runtime has to ask — exactly
  // as `openEditor` does — and this panel did not: the one place the question is
  // compulsory offered no help answering it. After the panel is placed, because
  // the widget positions its list against the box it completes.
  for (const input of panel.querySelectorAll('input[data-suggest]')) attachSuggest(input);
  panel.querySelector('input').focus();
  panel.querySelector('input').select();

  // The keyboard goes back to the cell the question was asked about. `rove` is
  // what this table hands focus with everywhere else, and it survives the redraw
  // that a save causes.
  const shut = () => { panel.hidden = true; panel.innerHTML = ''; rove(cell, true); };
  panel.querySelector('#unasked').onclick = () => { shut(); announce('nothing was changed'); };
  panel.querySelector('#asked').onclick = () => {
    const extra = {};
    for (const input of panel.querySelectorAll('input')) {
      if (!input.value.trim()) {
        announce(`${FIELD_LABELS[input.dataset.field] || input.dataset.field} is needed`);
        input.focus();
        return;
      }
      extra[input.dataset.field] = input.value.trim();
    }
    panel.hidden = true;
    panel.innerHTML = '';
    commit(extra);
  };
  // Enter saves and Escape gives up, which is what every other box on this page
  // answers to — a panel that has to be dismissed with the mouse is a panel that
  // stops the keyboard path this table is built around.
  panel.onkeydown = event => {
    // Unless the suggestion list already answered the key: this listener is on
    // the panel and fires on the way up, after the widget's own — so without
    // this, Enter picked the highlighted name AND saved the half-answered
    // panel, and Escape closed the list AND cancelled the whole question. One
    // press, one thing done.
    if (event.defaultPrevented) return;
    if (event.key === 'Enter') { event.preventDefault(); panel.querySelector('#asked').click(); }
    if (event.key === 'Escape') { event.preventDefault(); panel.querySelector('#unasked').click(); }
  };
}

// jcanton, 2026-08-26: "would it be possible to edit the same cell in multiple
// rows by something like ctrl/shift+click".
// Declared at the top of this script, above `cell()` — see the note there.

function unpick(redraw) {
  if (!PICKED.size && !PICKED_FIELD) return;
  PICKED.clear();
  PICKED_FIELD = null;
  PICKED_FROM = null;
  if (redraw !== false) draw();
}

// The ids of the rows on screen, in the order they are drawn — which is the
// order a shift range means. Read off the DOM and not off `DATA`, because the
// table is sorted and filtered in the browser and a range is what the reader can
// see between the two cells they clicked.
function pickableRows() {
  return [...tbody.querySelectorAll('tr[data-id]')]
    .map(row => row.dataset.id)
    .filter(id => id !== DRAFT_ID);
}

function pick(cell, extend) {
  const field = cell.dataset.field;
  const id = cell.dataset.record;
  if (!field || !id) return;
  // A different column is a different question, so the old answer goes.
  if (PICKED_FIELD !== field) {
    PICKED.clear();
    PICKED_FIELD = field;
    PICKED_FROM = null;
  }
  if (extend && PICKED_FROM) {
    const rows = pickableRows();
    const from = rows.indexOf(PICKED_FROM);
    const to = rows.indexOf(id);
    if (from !== -1 && to !== -1) {
      for (const between of rows.slice(Math.min(from, to), Math.max(from, to) + 1))
        PICKED.add(between);
      draw();
      sayPicked();
      return;
    }
  }
  // Toggling, so the same gesture takes a cell back out — a selection you can
  // only add to is a selection you have to start again.
  if (PICKED.has(id)) PICKED.delete(id);
  else PICKED.add(id);
  PICKED_FROM = id;
  if (!PICKED.size) PICKED_FIELD = null;
  draw();
  sayPicked();
}

// Said out loud, because the marks on the cells are the only other thing that
// says it and a reader who is not looking at the screen has nothing. The column
// is named as well as counted: "3 cells" is true of a selection in any of
// fourteen columns and useless in all of them.
function sayPicked() {
  if (!PICKED.size) { announce('Selection cleared'); return; }
  const named = (FIELD_LABELS[PICKED_FIELD] || PICKED_FIELD).toLowerCase();
  announce(PICKED.size === 1
    ? `1 ${named} cell selected`
    : `${PICKED.size} ${named} cells selected — editing one writes all of them`);
}

// **One field, every selected record, one commit.** `PATCH /api/records` and not
// a loop over the singular route: the second call in a loop is written against
// the commit the first one made, so a conflict halfway leaves half the selection
// written on a protected branch with no way to say which half.
async function saveCells(cell, value, extra) {
  const field = cell.dataset.field;
  const ids = pickableRows().filter(id => PICKED.has(id));
  const box = document.getElementById('row-conflict');
  box.hidden = true;
  box.textContent = '';
  let coerced;
  let sending;
  try {
    coerced = coerce(EDITABLE[field], value);
    sending = {[field]: coerced};
    for (const [name, raw] of Object.entries(extra || {}))
      sending[name] = coerce(EDITABLE[name], raw);
  } catch (error) {
    announce(`${field} ${error.message}`);
    return;
  }
  // The status gate, asked of every row before any of them is written, and this
  // is where a refusal turned into a question. It used to refuse outright and
  // name the rows — which was right while every field a gate could want was one
  // a person answers per record. `end_date` is not: a done record needs the day
  // it finished, that field is empty on EVERY row anybody is about to mark done,
  // and so "select the finished tasks, set Done, one commit" — the gesture this
  // whole selection mechanism exists for — would have met the refusal every
  // single time, about every single row, for ever.
  //
  // So the panel asks ONCE and the answer travels to every row that was short of
  // it, because "these all finished today" is one fact about the batch — and to
  // those rows only, which is the paragraph below. Anything the panel
  // cannot ask that way still refuses and still names the rows: an owner, an
  // appetite and a reviewer are one fact PER record, and prefilling nine rows
  // with one appetite would commit a number nobody meant, in one commit, on a
  // protected branch. The type is what decides — a date is the shape of thing a
  // batch can share — which is the same rule `askFor` prefills by.
  //
  // **And the one answer only ever lands where there is nothing to overwrite.**
  // It used to land on every selected record, held value included, on the
  // argument that the splat IS the gesture — and that argument is true of
  // `end_date` and was made about every date the gate can ask for. `wanted` is
  // the UNION of what the rows are missing, so one row with nothing raises the
  // question for all of them: select nine rows to mark `in_progress`, three of
  // which were finished in the spring and carry the day they really started,
  // and the panel prefills today because SOME row is short of a date — and
  // three real start dates are replaced with today, in one commit, on a
  // protected branch. `start_date` is history and not a statement about the
  // selection; "these all finished today" is a coherent thing to mean, "these
  // all started today" said over a record that started in March is not.
  //
  // The rule is universal rather than a list of fields allowed to splat, and
  // the reason is that `end_date` only LOOKED safe: it is empty on every row at
  // the moment of the transition, which is a fact about those rows and not
  // about the field. A recorded end is as much history as a recorded start, and
  // there is no field whose stored value one box is entitled to correct nine
  // rows at a time. So a wanted field that any selected row already holds
  // refuses the batch and names those rows, which is the same shape as the
  // refusal above and for the same reason: nothing is written until every row
  // can take the write. Those rows need no answer anyway — the gate they are
  // being held against is already satisfied for them — so the way out is to set
  // them on their own, which is a second deliberate commit rather than a lost
  // gesture.
  //
  // The narrower fix, sending the answer to the rows that lack it and the
  // status to all of them, is two field maps and therefore two PATCHes: the
  // loop `PATCH /api/records` exists to refuse, where the second write is made
  // against the commit the first one made and a conflict between them leaves
  // half a selection written with no way to say which half.
  //
  // A warning would not have done. The panel already says how far the answer
  // reaches — "for all 9 selected records" — and that sentence is what stood
  // between somebody and the overwrite; it is now true rather than load-bearing,
  // because every row it reaches is a row that was missing the field.
  if (field === 'status' && !extra) {
    const wanted = [...new Set(ids.flatMap(id => missingFor(DATA.rows[id] || {}, coerced)))];
    const cannot = wanted.filter(name => EDITABLE[name] !== 'date');
    if (cannot.length) {
      const short = ids.filter(id =>
        missingFor(DATA.rows[id] || {}, coerced).some(name => cannot.includes(name)));
      box.hidden = false;
      // By title. Every row this names is selected and on the screen behind the
      // banner, and both remedies — fix it, or take it out of the selection —
      // are done by finding it in the table, which a person does by its name.
      box.textContent = short.length === ids.length
        ? `None of these can be ${human(coerced)} yet: ${short.map(titleOf).join(', ')}. `
          + 'Each needs a field it has not got.'
        : `${short.map(titleOf).join(', ')} cannot be ${human(coerced)} yet, so nothing `
          + 'was written. Fix those rows, or take them out of the selection.';
      return;
    }
    // Asked of the stored value and not of `missingFor`, which answers a
    // narrower question: a row of a kind the gate does not reach is "not
    // missing" a field it holds, and the answer would have been written over
    // that one too.
    const clashes = wanted.filter(name => ids.some(id => holds(DATA.rows[id] || {}, name)));
    if (clashes.length) {
      const held = ids.filter(id => clashes.some(name => holds(DATA.rows[id] || {}, name)));
      const named = clashes.length === 1
        ? `a ${(FIELD_LABELS[clashes[0]] || clashes[0]).toLowerCase()}`
        : clashes.map(name => (FIELD_LABELS[name] || name).toLowerCase()).join(' and ');
      box.hidden = false;
      // By title, for the reason on the banner above it.
      box.textContent =
        `${held.map(titleOf).join(', ')} already `
        + `${held.length === 1 ? 'has' : 'have'} ${named}, and one `
        + 'answer here is written to every selected record. Nothing was written. Take '
        + `${held.length === 1 ? 'that row' : 'those rows'} out of the selection and set `
        + `${held.length === 1 ? 'it' : 'them'} on ${held.length === 1 ? 'its' : 'their'} own.`;
      return;
    }
    if (wanted.length) {
      askFor(cell, value, wanted, answers => saveCells(cell, value, answers),
        `${human(coerced)} needs ${wanted.length === 1 ? 'this' : 'these'} `
        + `for all ${ids.length} selected record${ids.length === 1 ? '' : 's'}`);
      return;
    }
  }
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  // Whether the commit is known to exist. The `try` below does not stop at the
  // write: `refreshRows` and `refreshProblems` await bare fetches of their own
  // with no `catch`, so a connection dropped AFTER the commit landed rejects
  // inside them and arrives here. Without this flag the catch says "not saved"
  // and "press it again" over a write that is already in git — false in both
  // halves, and the second half is advice to re-send against a `BASE.value` that
  // has already moved on.
  let landed = false;
  try {
    const response = await fetch('/api/records', {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, ids, fields: sending}),
    });
    const answer = await answerOf(response);
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      return;
    }
    if (!response.ok) {
      announce(refusal(answer, response.status));
      return;
    }
    committed = answer.commit;
    landed = true;
    BASE.value = answer.commit;
    for (const id of ids) {
      markSaved(answer, id);
      Object.assign(DATA.rows[id], sending);
    }
    announce(`${ids.length} ${(FIELD_LABELS[field] || field).toLowerCase()} `
      + `cell${ids.length === 1 ? '' : 's'} saved in one commit`);
    // The selection has done its job. Leaving it up invites a second bulk write
    // nobody meant, from a gesture as small as opening the next cell.
    unpick(false);
    draw();
    // The same re-read the single save makes, and for the same reason: a date
    // the Start and End columns of every selected row are derived from has just
    // been written, and those columns are not the one that was edited.
    //
    // Asked of `sending` and not of the panel's answers, exactly as it is asked
    // there: the Start and End cells are pickers now, so a selection of them is
    // a bulk date write that arrives with no `extra` at all.
    if (Object.keys(sending).some(name => DERIVES_DATES.has(name))) await refreshRows();
    await refreshProblems();
    draw();
  } catch (error) {
    // Two different failures reach here, and they get two different sentences.
    //
    // `landed` — the commit came back and the re-read after it did not. The
    // write is in git, `BASE.value` has already moved to it, the selection has
    // already been dropped, and the only thing wrong is that the Start, End and
    // problem columns on screen are one commit behind. Nothing to press again.
    //
    // Otherwise the write itself never got an answer. With no `catch` at all the
    // rejection escaped unhandled and the selection sat there looking exactly as
    // it did before the press — every row still picked, every cell still showing
    // the old value, and nothing to say whether one commit had rewritten all of
    // them. A bulk write is the one gesture here where "nothing happened" and
    // "fifty records changed" look the same on screen. The selection is left up
    // on this branch, unlike the landed one: it is what the repeat needs.
    //
    // No claim about what reached the server — a fetch rejects when the answer
    // is lost as readily as when the request never left. The repeat is safe
    // because it is the SAME write, not because the store would refuse it:
    // `BASE.value` is untouched, the same values go out again, and
    // `_merge_frontmatter` skips every key whose stored value already equals the
    // one being sent, so a write that did land merges with itself and answers
    // 200. This used to promise a refusal the store does not give.
    announce(landed
      ? `${ids.length} cell${ids.length === 1 ? '' : 's'} saved, but the page could `
        + `not read the plan back — ${error.message}. The write went through; `
        + 'reload to see what it changed.'
      : `${ids.length} cell${ids.length === 1 ? '' : 's'} not saved — `
        + `${error.message}. Press it again: it sends the same values against the `
        + 'same base, so a write that did land is not repeated.');
  } finally {
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

async function saveCell(cell, value, extra) {
  const field = cell.dataset.field;
  const box = document.getElementById('row-conflict');
  // Cleared here and nowhere else. This page redraws instead of reloading, so
  // nothing else ever took the banner down: one 409 left "somebody changed this
  // before you" standing over every save that landed afterwards.
  box.hidden = true;
  box.textContent = '';
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
  // A status that demands what this row has not got is a question before it is a
  // write. Asked once — `extra` is what came back from asking, and a second pass
  // through here with it must not ask again.
  if (field === 'status' && !extra) {
    const wanted = missingFor(DATA.rows[cell.dataset.record] || {}, coerced);
    if (wanted.length) {
      askFor(cell, value, wanted, answers => saveCell(cell, value, answers));
      return;
    }
  }
  let sending;
  try {
    sending = {[field]: coerced};
    for (const [name, raw] of Object.entries(extra || {}))
      sending[name] = coerce(EDITABLE[name], raw);
  } catch (error) {
    announce(`${field} ${error.message}`);
    return;
  }
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  // Whether the commit is known to exist — the same flag, for the same reason,
  // as the bulk save above: `refreshRows` and `refreshProblems` are inside this
  // `try` and await bare fetches with no `catch` of their own, so a connection
  // dropped after the commit landed rejects in one of them and arrives at the
  // catch below.
  let landed = false;
  try {
    // One key, taken from the cell. Sending the row would overwrite whatever
    // somebody else changed while this tab was open, and would turn two people
    // editing two different columns into a conflict field-level merge exists to
    // make invisible. No body: an empty string is a replacement, not an omission,
    // and would blank the shaping doc attached to the row.
    //
    // The id is encoded, here and at the three other write sites. A malformed id
    // is a *reported* blocker and not a refusal, so an id with a `#` or a `?` in
    // it does reach the page — and raw in a path, the first one truncates it, so
    // the save somebody pressed on one record addresses something else entirely.
    const response = await fetch(`/api/record/${encodeURIComponent(cell.dataset.record)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: sending, body: null}),
    });
    const answer = await answerOf(response);
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      return;
    }
    if (!response.ok) {
      announce(refusal(answer, response.status));
      return;
    }
    // The page moves forward with the repository, or its next save collides with
    // the commit it just made.
    committed = answer.commit;
    landed = true;
    BASE.value = answer.commit;
    markSaved(answer, cell.dataset.record);
    Object.assign(DATA.rows[cell.dataset.record], sending);
    // A date the schedule is derived FROM has moved, so every date derived from
    // it on this row is now wrong on screen — and `start` and `end` are two
    // columns away from the one that was edited. Re-read rather than recomputed:
    // the scheduler is the server's, and a second copy of it here is the thing
    // this codebase has paid for three times already.
    //
    // **Asked of everything being written, and it used to be asked of `extra`
    // alone** — of the answers the status panel collected, and of nothing else.
    // That was the same question while `start_date` and `end_date` could only
    // reach this line through the panel; the two date columns are pickers now,
    // and a date typed straight into one arrives here with `extra` undefined. It
    // read as a save that did not take: the Start cell draws `row.start`, which
    // is the scheduler's span, the `Object.assign` above writes `row.start_date`,
    // and the redraw below therefore put the OLD forecast straight back into the
    // cell somebody had just typed a date into — still muted and italic, as if
    // nothing had been stated at all. The commit had landed the whole time.
    if (Object.keys(sending).some(name => DERIVES_DATES.has(name))) {
      await refreshRows();
    }
    // Twice: once to put the typed value back into the cell rather than leaving
    // an open editor sitting there for the length of a second round trip, and
    // once when the server has said what that value did to the problems.
    draw();
    await refreshProblems();
    draw();
  } catch (error) {
    // Two different failures reach here, and they get two different sentences.
    //
    // `landed` — the commit came back and the re-read after it did not. The save
    // is in git, `BASE.value` has already moved to it, and what is stale is the
    // Start and End columns and the problem markers. Nothing to edit again.
    //
    // Otherwise the write itself never got an answer. With no `catch` at all the
    // rejection escaped unhandled and nothing was said: the cell simply went back
    // to the value the page holds, which is exactly what a save that landed also
    // looks like on this page. `reparent` one screen down already had this catch,
    // for the same gesture on the same table.
    //
    // Said and not drawn, the way every non-409 refusal on this path is said. No
    // claim about what reached the server — a fetch rejects when the answer is
    // lost as readily as when the request never left. The repeat is safe because
    // it is the SAME write, not because the store would refuse it: `BASE.value`
    // is untouched, the same value goes out again, and `_merge_frontmatter` skips
    // every key whose stored value already equals the one being sent, so a save
    // that did land merges with itself and answers 200.
    //
    // The row by title, like every other sentence this table says about one: the
    // cell is still on screen with the value in it, and "Edit it again" is an
    // instruction about that row and not about a file.
    announce(landed
      ? `${titleOf(cell.dataset.record)}: ${field} saved, but the page could not `
        + `read the plan back — ${error.message}. The save went through; reload to `
        + 'see what it changed.'
      : `${titleOf(cell.dataset.record)}: ${field} not saved — ${error.message}. `
        + 'Edit it again: it sends the same value against the same base, so a save '
        + 'that did land is not written twice.');
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

// Out from under the frozen columns, after the browser has scrolled the box into
// view its own way.
//
// Focusing a control inside a horizontal scroller makes Chrome scroll it into
// view, and "in view" to Chrome means inside the scrollport — it knows nothing
// about the two columns that are `position: sticky` INSIDE that scrollport, so
// the cell it brings to the left edge is the cell it parks underneath them.
// Measured on a phone (390x844, `measured_on_a_phone`) on the demo plan with this
// call taken out: opening a stored row's Start cell put `scrollLeft` at 679 —
// the table's maximum — with the frozen Title column running to x=177 and the
// open box drawn from x=142.5, so 34.5px of its left end sat under a column
// that is opaque by design, and
// `elementFromPoint` at the box's own left edge answers the title's link rather
// than the box. `owner` went under by 37.5px and `assignees` by 40.5, so it was
// never only the one column.
//
// Still true, and still this function's job, now that the open date box is wider
// than its cell: what the box overflows is its RIGHT edge, and this is about its
// left one. The same run with the call back in clears every one of them: the
// text boxes open at x=177.5, half a pixel past the edge, and the date box at
// x=185.5, because a date control sits inside the cell's `.5rem` of padding
// where a text box starts at the border.
//
// It was survivable while the cell held text: what was covered was the left end
// of a date somebody was reading. A picker's first segment is the one it focuses
// and selects the moment it opens — and it is inside the first 44px of the
// control, which is the width at which a box holding 15.09.2026 still draws
// `15.` — so what is under there is the part being typed into. That is why this
// is fixed here rather than lived with, and fixed for every editor rather than
// for dates.
//
// `FROZEN` and not a written-out pair, so that a third frozen column arrives
// here with the stylesheet. Measured off the HEADER of each, which is where
// `stickyOffset` already reads this geometry: a header is in the same column at
// the same `left` and is never replaced, while the row under the pointer is
// rebuilt by every `draw()`. A shed column's header measures zero and so cannot
// raise the edge. And the cell's own column is left out, because the title is
// both a frozen column and an editable one — measured against its own right edge
// it is always "under" by its own width, and would scroll away from nothing.
function clearOfFrozen(cell) {
  const edge = headers
    .filter(th => FROZEN.includes(th.dataset.col) && th.dataset.col !== cell.dataset.col)
    .reduce((most, th) => Math.max(most, th.getBoundingClientRect().right), 0);
  // Rounded UP, because a scroll offset is fractional going in and rounded
  // coming back: 40.5px of overlap paid off exactly left the cell half a pixel
  // short of the edge it was supposed to clear, which is a column drawn over the
  // first thing a reader looks at.
  const under = Math.ceil(edge - cell.getBoundingClientRect().left);
  // Scrolling BACK, never forward: less `scrollLeft` moves the row right, out
  // from under the frozen edge. Floored at 0 because there is nothing to clear
  // there — the sticky columns are sitting in their own places and cover nothing.
  if (under > 0) scroller.scrollLeft = Math.max(0, scroller.scrollLeft - under);
}

function openEditor(cell) {
  // A computed column answers rather than swallowing the key, exactly as it
  // answers a double-click: a cell that ignores Enter is indistinguishable from
  // a cell that is broken.
  if (!cell.classList.contains('edit')) { refuse(cell); return; }
  if (cell.querySelector('input, select')) return;
  rove(cell);
  const field = cell.dataset.field;
  // The record this cell is part of, or the one that does not exist yet: a cell
  // with no `data-record` is a cell of the row being typed, and there is exactly
  // one of those. One editor for both, because a second one is a second set of
  // rules about what a list separator is and which values get selected on open —
  // and the create form is already proof that a differently-shaped way to write
  // the same fields is how a tool comes to feel like two tools.
  const was = stored(cell.dataset.record ? DATA.rows[cell.dataset.record] : DRAFT.fields, field);
  const suggest = SUGGESTS[field];
  const closed = CHOICES[EDITABLE[field]];
  // The name the editor answers to. The cell it replaces carries its column in
  // a header a screen reader reads on the way in; a box conjured inside that
  // cell carries nothing at all unless it is told what it is editing.
  const named = esc(FIELD_LABELS[field] || field);
  // A date is PICKED, not spelled. Every other date this app asks for is a
  // native picker — the detail page's form, the status question `askFor` builds
  // in this same file, the cycle boxes — and the table was the one surface where a
  // date had to be typed as ISO from memory into a box that would take anything.
  // The rule is the TYPE and not a list of field names, for the reason `askFor`
  // gives: written as `field === 'start_date'` it is right until `end_date`
  // arrives beside it.
  //
  // Nothing converts on either side of this. `stored` hands back `YYYY-MM-DD` or
  // an empty string, which is exactly what `type="date"` reads and exactly what
  // it reports back, so the value that opens the box and the value the save
  // sends are the same string they were when this was a text box.
  //
  // And NO prefill, which is where this differs from `askFor` on purpose: that
  // panel is a question a status change just raised and today is nearly always
  // the answer, while this opens on whatever the FIELD holds — empty on a row
  // whose Start cell is showing the scheduler's forecast. Filling it in would
  // put that guess one Enter away from being committed as somebody's choice
  // (`test_the_editor_opens_on_the_written_value_and_not_the_forecast`).
  const type = EDITABLE[field] === 'date' ? 'date' : 'text';
  // A closed set is chosen, never typed. Free text over three options is a way
  // to write `in progres` into the corpus. The option's value is the stored
  // identifier and its text is the word for it, so picking "In progress"
  // still writes `in_progress`.
  // Every interpolation escaped, including the ones that are a closed set today.
  // A rule with an exception in it is a rule nobody applies to the next line.
  // The tree first, rebuilt from the cell's own `data-rungs` rather than kept:
  // this is the one cell whose contents are replaced without a redraw, and the
  // connector belongs to the row rather than to what is in the cell at the time.
  cell.innerHTML = treeHtml(cell.dataset.rungs) + (closed
    // The same mark the cell was showing a moment ago, so opening an editor does
    // not swap a marked value for an unmarked list of words. `markFor` reaches
    // the two maps the payload already carries.
    ? `<select data-type="text" aria-label="${named}">${closed.map(o =>
        `<option value="${esc(o)}" ${o === was ? 'selected' : ''}>` +
        `${esc(markFor(field, o))}${esc(human(o))}</option>`
      ).join('')}</select>`
    // `type` and `data-type` are two different questions and both are asked:
    // `type` is what the browser draws, `data-type` is what `coerce` and the
    // suggestion widget read — the widget completes the last comma-separated
    // token on `dataset.type === 'list'`, and dropping it as a duplicate of
    // `type` is how picking a second assignee came to replace the first.
    : `<input value="${esc(was)}" type="${type}"` +
      ` data-type="${esc(EDITABLE[field])}" aria-label="${named}"` +
      `${suggest ? ` data-suggest="${esc(suggest)}"` : ''} autocomplete="off">`);
  const input = cell.querySelector('select, input');
  // The table gets the autocomplete the detail page has. Suggestions that only
  // appear in one of the two places are suggestions nobody relies on.
  if (suggest) attachSuggest(input);
  input.focus();
  // A single-value cell selects everything, because a double-click leaves the
  // caret where it landed and typing would interleave. A list must NOT: typing
  // over a selected "jcanton, halungge" deletes both reviewers to write one.
  //
  // **Leave this pair as it is now that a date box comes through it.** A date is
  // not a list, so it takes the first branch, and `select()` on `type="date"` is
  // a defined no-op — it does nothing and it throws nothing, which is why the
  // picker needs no case of its own here. The `else` is another matter:
  // `setSelectionRange` raises InvalidStateError on a date box, so anything that
  // merged the two branches, or reordered them, or dropped the `input.select`
  // guard, would take the editor down on the two columns that now open one.
  if (EDITABLE[field] !== 'list' && input.select) input.select();
  else if (input.setSelectionRange)
    input.setSelectionRange(input.value.length, input.value.length);
  clearOfFrozen(cell);

  let abandoned = false;
  input.onblur = () => {
    // **A half-written date must not clear the date that is there.** A native
    // picker reports `value === ''` for anything it cannot read as a whole date
    // — `2026-0`, a day typed into an empty box and then a click elsewhere — and
    // `coerce` maps `''` to `null`, which is right and has to stay right: a date
    // has to be removable from the table. So the two are indistinguishable by
    // value alone, and the fumbled one used to arrive here as a deliberate
    // clear, commit the deletion and say nothing. A text box could not do this:
    // it sends the garbage and earns a 422 naming the field, which is a refusal
    // somebody can read.
    //
    // `validity.badInput` is the browser's own word for exactly that state — set
    // while the control holds something it cannot parse, and false for a box
    // that is genuinely empty — so it is the one thing here that can tell a slip
    // from an intention. Treated as abandoned rather than refused, because
    // nothing was decided: the cell is redrawn on the value it still has.
    //
    // Guarded with `&&` because `validity` belongs to a real form control and
    // the driver the node tests run under builds elements that have none, and
    // behind `!abandoned` because Escape reaches this line through `draw()` with
    // the half-written date still in the box. Escape is an intention rather than
    // a slip, and there is nothing to report about it: it says nothing itself —
    // the `stopPropagation` below is what keeps the grid's own handler from
    // taking the whole draft row and announcing that instead — and the `draw()`
    // it has already done is the redraw this branch would do. All that is left to
    // add is the sentence, and "was left half-written" is a report of a mistake
    // nobody made.
    if (!abandoned && input.validity && input.validity.badInput) {
      draw();
      announce(`${FIELD_LABELS[field] || field} was left half-written, and was not changed`);
      return;
    }
    // A stored cell writes a commit; a draft cell writes into the row nobody has
    // created yet, which is a change to a variable and not to the repository.
    // Same editor, same key handling, one branch at the end of it.
    if (abandoned || input.value === was) draw();
    // A selection of more than one takes the whole selection, and only when the
    // cell being closed is IN it: opening some other cell while a selection is up
    // is an ordinary single edit, and treating it as a bulk one would write a
    // column somebody never touched.
    else if (cell.dataset.record && PICKED.size > 1
             && PICKED_FIELD === cell.dataset.field && PICKED.has(cell.dataset.record))
      saveCells(cell, input.value);
    else if (cell.dataset.record) saveCell(cell, input.value);
    else stage(field, input.value);
  };
  input.onkeydown = e => {
    // A key the suggestion list consumed is not this editor's to act on too:
    // Escape with the list open shipped as "close the list AND discard the
    // whole cell edit". The Escape still must not bubble — the grid's own
    // handler abandons a draft row on it — so the stop the branch below does is
    // done here as well before the early return.
    if (e.defaultPrevented) {
      if (e.key === 'Escape') e.stopPropagation();
      return;
    }
    if (e.key === 'Enter') { RETURN = true; input.blur(); }
    if (e.key === 'Escape') {
      // Escape means discard. Redrawing first would fire blur with the partial
      // value still in the box, and the edit somebody just abandoned gets saved.
      abandoned = true;
      RETURN = true;
      // And it means discard THIS, never the row it is in. The grid answers
      // Escape as well now — it is how a draft is abandoned — and both listeners
      // are on the way up from this box, so without this an Escape meant to undo
      // one mistyped cell would take the whole half-typed row with it. The
      // comment on that handler already says the keys belong to an open editor;
      // this is the line that makes it so rather than leaving it to a test of
      // what an editor looks like from the outside.
      e.stopPropagation();
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

// ---------------------------------------------------------------------------
// A row you type into
// ---------------------------------------------------------------------------

// Which stored field each column of a new row writes to, per kind, and the
// values a record starts life with. Both are built on the server from the models
// themselves — see `_new_row_fields` — so what a project has no box for here and
// what the create form hides there are one answer to one question.
const NEW_ROW = DATA.new_row || {};
const DEFAULTS = DATA.defaults || {};
const TEMPLATES = DATA.templates || {};
// The check and the cross the draft row's two controls are drawn with, rendered
// on the server. A template variable and not a `.replace` into the finished
// page, which is the rule the whole file is held to; and drawings rather than
// the characters `✓` and `✕`, which is argued at `DRAFT_MARKS`.
const MARK = {{ marks|tojson }};
// What the row being typed answers to in the grid. `+` is not an id and cannot
// become one — an id is a prefix and six hex digits — so nothing that walks the
// rows can confuse the draft with a record.
const DRAFT_ID = '+';

// The row that is not a record yet: null while there is none, otherwise the
// kind (null until it is chosen), what has been typed so far, and whatever the
// last refusal said.
//
// One variable, and it is the whole of the draft. That is what makes it survive
// a sort — `draw()` rebuilds every row from state, so re-sorting or filtering
// redraws this one with everything in it — and what makes it not survive a
// reload, which is a decision and not an oversight. A half-filled row kept in
// `localStorage` is a record of the plan that is not in git, that nobody can
// review and that no `base_commit` covers; the one draft this app does keep, on
// the detail page, has to carry the commit it was drafted against precisely so
// it can say it has gone stale. That is worth paying for a shaping document
// somebody spent an hour on. It is not worth paying for four short fields with
// Create sitting directly underneath them, and a draft that outlives the page is
// a draft somebody creates twice.
let DRAFT = null;

// Whether the create this row asked for is still in the air.
//
// A create is a commit and a push to GitHub, which from Cloud Run is 1.5 to 2
// seconds — measured on the deployed service on 2026-08-24: four creates at
// 1.45s, 1.55s, 1.93s and 2.04s. For every one of those seconds the row sat
// there looking exactly as it had before the press, because the only thing the
// press did was dispatch `openproj:writing`, which the shell *counts* to hold
// its banner back and does not draw. A control that does not answer a press is
// a control somebody presses again, and pressing this one again posted a SECOND
// record: two 201s 0.9 seconds apart in that same log, two rows, one of them
// deleted by hand a minute later.
//
// So one flag does both halves of it — the check says it is working and stops
// taking presses — because they are one fact about the row and drawing them
// from two would let them disagree. `draw()` reads it, which is what makes it
// survive the redraws a refusal causes; `createDraft` is the only thing that
// sets it, and its `finally` is the only thing that clears it.
let CREATING = false;

// What a draft cell shows: exactly what will be committed and nothing that is
// only true of a stored row. `shown()` links the title (there is no page to link
// to yet), turns PR references into links and clamps four columns behind a `+N`
// — none of which applies to a row whose entire content is what was just typed
// into it. The one thing it keeps is the status chip, because a status is a rung
// and reads as one everywhere else on the page.
function draftShown(field) {
  const value = DRAFT.fields[field];
  const text = Array.isArray(value) ? value.join(', ') : (value ?? '');
  if (text === '') return '';
  if (field === 'status') return `<span class="chip ${stClass(text)}">${esc(human(text))}</span>`;
  // `human` only where the value is one of a closed set. A title of `done` is a
  // title, and running every cell through the map would print it as "Done".
  return esc(CHOICES[EDITABLE[field]] ? human(text) : text);
}

function draftRowHtml() {
  const fields = NEW_ROW[DRAFT.kind] || {};
  const cells = keys.map(key => {
    // Where the id will be, and until it exists this is the row's controls
    // instead. The id is the server's to mint — a browser that names an id names
    // a path — so this cell has nothing of its own to show, and what stands in
    // for it is the one decision the id will be made out of plus the two answers
    // to whether it should be made at all.
    //
    // It read `new task`, with the kind picker and two word buttons in a bar
    // under the row. The words said what this cell now IS: the kind belongs in
    // the cell that carries the row's identity, and a bar under a row is a
    // second place to look for controls that belong to it.
    //
    // The sentence stays in the tooltip, because this is the narrowest column on
    // the table and beside the word it took the draft to two lines — a row twice
    // the height of every other row reads as a different kind of thing.
    if (key === 'id')
      return `<td data-col="id" class="draft-id"` +
        ` title="The id and the file are the server's to choose">${draftControls()}</td>`;
    const field = fields[key];
    // TWO NAMES, and they are two because they are drawn in two places. The
    // tooltip is prose and says what editing will write — `appetite`, not
    // `size` — so it agrees with the box that then opens. The placeholder is
    // inside a cell of a column fitted to its own contents, and putting the
    // field's name there made `size` read `appetite` and `start` read
    // `start date`: both wider than their columns, both wrapping, and the draft
    // row went from 30px to 50px — a row twice the height of every other row,
    // which `test_the_draft_rows_marks_are_drawn` measures and caught.
    const named = (FIELD_LABELS[field || key] || field || key).toLowerCase();
    const short = (FIELD_LABELS[key] || key).toLowerCase();
    if (!field) {
      // Two different reasons a column takes nothing, and the cell says which:
      // some kind can type into it and this one cannot — a project has no
      // appetite of its own — or nobody can, because it is the scheduler's
      // output. Asked of the map rather than listed here, so a column that
      // becomes kind-only later explains itself without this line changing.
      const anyKind = Object.keys(NEW_ROW).some(kind => key in NEW_ROW[kind]);
      const why = anyKind ? `A ${DRAFT.kind} has no ${named}` : WHY[key] || '';
      return `<td data-col="${key}" class="draft-none"` +
        `${why ? ` title="${esc(why)}"` : ''}></td>`;
    }
    return `<td data-col="${key}" class="edit draft-cell" data-field="${esc(field)}"` +
      ` data-hint="${esc(short)}" tabindex="-1"` +
      ` title="${esc('Double-click to edit ' + named)}">${draftShown(field)}</td>`;
  });
  return `<tr class="draft" data-id="${DRAFT_ID}">${cells.join('')}</tr>`;
}

// The last row of the table, in both of its states: the control that starts a
// row, and — once one is started — the kind picker, Create, Cancel and wherever
// the server's refusal lands.
//
// It is one row and not two because it is one thing: the place at the bottom
// where a plan grows. While a move is in the air it is also where a row goes to
// belong to nothing (see `startMoving`), which is the same place said the same
// way — under everything, outside the tree.
function adderHtml() {
  const wide = ` colspan="${keys.length}"`;
  if (!DRAFT) {
    // "New row" and not "New record", although a record is what it makes: the
    // control beside the heading is already called that and goes to the form
    // that writes one properly. Two controls with one name on one page is how a
    // person learns to trust neither, and what this one does when you press it
    // is put a row on the table.
    // Both of the last row's jobs are drawn every time, and `sayMoveOut` decides
    // which of them is showing. Emitted empty and filled in afterwards rather
    // than written out here, because the words are the same words `startMoving`
    // needs mid-drag, when the table must not be redrawn at all: one function
    // owns them, and a redraw and a pick-up leave this row saying the same thing.
    return `<tr class="adder"><td${wide}>` +
      `<button type="button" id="add-row" class="add">+ New row</button>` +
      `<button type="button" id="unparent" hidden></button>` +
      `<span class="hint" id="rootless" hidden></span>` +
      `</td></tr>`;
  }
  // The kind first, and it stays: it is the decision that says which fields the
  // row even has, and switching it after typing must not cost the typing — the
  // create form learned that one already. The row itself appears only once the
  // kind is chosen, because until then there is no answer to which columns it
  // has — which is the whole reason the kind is asked first.
  //
  // Which is also why the controls are in this bar until there is a row and in
  // the row's id cell afterwards: they belong to the row, and for one press
  // there is no row for them to belong to. One function draws them either way,
  // so the two places cannot come to offer different things.
  //
  // The sentence that used to be here — "Nothing is written until you press
  // Create" — is gone. It named a button that no longer exists: the controls are
  // a check and a cross now, and a hint that explains a control by the wrong
  // name is worse than no hint. The marks carry their own names in `title` and
  // `aria-label`, which is where a control says what it does.
  return (DRAFT.kind ? draftRowHtml() : '') +
    `<tr class="adder open"><td${wide}>` +
    (DRAFT.kind ? '' : draftControls()) +
    `<ul id="draft-problems" role="status" aria-live="polite" hidden></ul>` +
    `</td></tr>`;
}

// Create it, abandon it, and what it will be — the whole of what a row that does
// not exist yet offers, in one line and in that order.
//
// Marks and not words. `Create` and `Cancel` spelled out are two thirds of the
// id column, and this cell is the row's name rather than a toolbar; the marks
// are drawn rather than typed because `✓` and `✕` are in neither the vendored
// face nor anything else this page ships — see `DRAFT_MARKS`, which is where
// that is argued and where the drawings are.
//
// Which means every one of them is an icon-only control, so each carries the
// name twice: `aria-label` for a reader who cannot see it and `title` for one
// who can see it and cannot tell what it is. Never `title` alone — that is a
// hint, and these are the two controls this row has. The third channel is
// Escape, in the grid's key handler, because somebody who arrived here with Tab
// needs a way out that is not hunting for the ✕.
//
// Create names the kind — "Create this task", not "Create" — because it is the
// press that writes a file, and the row above it is not the only draft-shaped
// thing on the page while a filter is drawn.
function draftControls() {
  const kinds = Object.keys(NEW_ROW).map(kind =>
    `<option value="${esc(kind)}"${kind === DRAFT.kind ? ' selected' : ''}>` +
    `${esc(human(kind))}</option>`).join('');
  const named = DRAFT.kind ? esc(human(DRAFT.kind).toLowerCase()) : '';
  // While the write is in the air the whole row stops taking presses, and the
  // check says why. All three and not only the check: cancelling a create that
  // has already been posted does not un-post it — the record lands and the row
  // appears a second after somebody pressed the cross — and changing the kind
  // under a request that is already carrying the old one is the same lie said
  // about a different field. See `CREATING` for what it costs to leave a press
  // unanswered for two seconds.
  const held = CREATING ? ' disabled' : '';
  const says = CREATING ? `Creating this ${named}…` : `Create this ${named}`;
  const create = DRAFT.kind
    ? `<button type="button" id="draft-create" class="draft-do primary"${held}` +
      ` aria-label="${says}" title="${says}">` +
      `${MARK.create}</button>`
    : '';
  // "choose a kind…" and not "choose…": the word `kind` used to be printed
  // beside the picker and there is no room for it in the id column, so the
  // placeholder carries it instead. It is only ever read in the bar — the row
  // does not exist until a kind is chosen — so the narrow cell never has to
  // draw it.
  //
  // Wrapped, and the wrapper is what does the laying out: a `<td>` cannot be the
  // flex container itself without ceasing to be a table cell, which is the same
  // reason the clamped columns have `.clamped` inside them.
  return `<span class="drafting">` + create +
    `<button type="button" id="draft-cancel" class="draft-do"${held}` +
    ` aria-label="Discard this new row" title="Discard this new row">` +
    `${MARK.cancel}</button>` +
    `<select id="draft-kind" aria-label="Kind"${held}` +
    ` title="Which kind of record this row becomes">` +
    `<option value=""${DRAFT.kind ? '' : ' selected'}>choose a kind…</option>` +
    `${kinds}</select></span>`;
}

// Whatever the last attempt was refused with, put in as text.
//
// `replaceChildren` with text nodes and never `innerHTML`: every one of these
// sentences comes back from the server quoting a field this plan holds, and a
// title is a sentence somebody typed. The list is also why the refusal is drawn
// *in* the bar rather than in `#row-conflict` — a create has no row to sit
// beside, and a refusal with nowhere to land is a refusal that gets swallowed.
function sayDraft() {
  const list = document.getElementById('draft-problems');
  if (!list) return;
  const said = (DRAFT && DRAFT.said) || [];
  list.hidden = !said.length;
  list.replaceChildren(...said.map(text => {
    const item = document.createElement('li');
    item.textContent = text;
    return item;
  }));
}

function refused(lines) {
  if (DRAFT) DRAFT.said = lines;
  draw();
  announce(lines.join(' '));
}

// What the server refused a create with, one sentence per line. The create route
// answers 422 with a `problems` list and everything else with a `detail`, and
// the shell's `refusal` already knows which — this only keeps them apart so that
// three blockers read as three lines instead of one long one. It is not
// `refusals()` from the detail form: that one names the control each problem is
// about, and there are no named controls on a table.
function refusalLines(answer, status) {
  const problems = answer.problems || [];
  return problems.length ? problems.map(problem => problem.drawn)
                         : [refusal(answer, status)];
}

// The picker, wherever it was just drawn — in the bar while there is no row, in
// the row's id cell once there is one. Asked of the document rather than kept,
// because every redraw replaces it.
function focusDraftKind() {
  const picker = document.getElementById('draft-kind');
  if (picker) picker.focus();
}

function openDraft() {
  DRAFT = {kind: null, fields: {}, said: []};
  draw();
  focusDraftKind();
}

function closeDraft(said) {
  DRAFT = null;
  draw();
  if (said) announce(said);
  const add = document.getElementById('add-row');
  if (add) add.focus();
}

function chooseKind(kind) {
  if (!NEW_ROW[kind]) {
    // Back to "choose a kind…", which takes the row away and the picker with it
    // — `draw()` rebuilds the whole tbody and the picker is drawn in the bar
    // again. Handed back rather than left on `<body>`: the element that had the
    // keyboard no longer exists, and a person who has just changed their mind
    // about the kind is still answering the same question.
    DRAFT.kind = null;
    draw();
    focusDraftKind();
    return;
  }
  DRAFT.kind = kind;
  // What was typed stays. Except a field this kind has not got: a size typed
  // while the row was a task is not a project's to carry, and sending it is a
  // 422 quoting a field that is no longer on the screen.
  const owned = new Set(Object.values(NEW_ROW[kind]));
  for (const name of Object.keys(DRAFT.fields)) if (!owned.has(name)) delete DRAFT.fields[name];
  // The status and the priority a record is created with, shown rather than left
  // blank. A blank cell that turns into `shaping` on save is the row lying about
  // what it is going to write, and these two are the columns somebody scanning
  // the table reads first.
  for (const [name, value] of Object.entries(DEFAULTS))
    if (owned.has(name) && !(name in DRAFT.fields)) DRAFT.fields[name] = value;
  DRAFT.said = [];
  draw();
  // Straight into the one field the row cannot be created without, so the whole
  // flow is: press +, pick the kind, type, press Create.
  const title = tbody.querySelector('tr.draft td[data-field="title"]');
  if (title) openEditor(title);
}

// A typed value into the draft. The same coercion the save path uses, because
// `1, 2` has to mean the same two tags whichever row it was typed into.
function stage(field, value) {
  let coerced;
  try {
    coerced = coerce(EDITABLE[field], value);
  } catch (error) {
    announce(`${field} ${error.message}`);
    draw();
    return;
  }
  if (coerced === null || (Array.isArray(coerced) && !coerced.length)) delete DRAFT.fields[field];
  else DRAFT.fields[field] = coerced;
  draw();
}

async function createDraft() {
  // The check is drawn `disabled` while this runs, so a mouse cannot reach it a
  // second time — but `disabled` is a property of one element and this is a
  // statement about the page: Enter on the control, a second listener, a script,
  // and the redraws a refusal causes all reach here without going through that
  // button. The flag is the rule; the attribute is how it is shown.
  if (CREATING) return;
  const fields = {kind: DRAFT.kind, ...DRAFT.fields};
  // A title, at minimum. The server refuses a titleless record too, but it
  // refuses it as YAML that will not read back — and the reason a row needs one
  // is not about YAML: a record with no title is a row nobody can find again,
  // in a table whose first column is a mint-fresh id nobody has seen before.
  // Everything else the status demands is left to `validate_all`, which is the
  // only thing that knows the rules and which of them this record is old enough
  // to be held to.
  if (!String(fields.title || '').trim()) {
    refused(['A row needs a title — it is how anybody finds it again.']);
    const cell = tbody.querySelector('tr.draft td[data-field="title"]');
    if (cell) openEditor(cell);
    return;
  }
  // The banner in the shell has to know a write is in the air before it starts,
  // exactly as a cell save does: the server announces a commit to the event
  // stream before it answers the request that made it.
  dispatchEvent(new Event('openproj:writing'));
  // The press is answered here rather than when the server gets back to us. Two
  // seconds of a row that looks untouched is what taught somebody to press twice
  // — and the redraw is also what takes the control away, so the second press
  // has nowhere to land even before `CREATING` refuses it.
  CREATING = true;
  draw();
  announce(`Creating this ${human(DRAFT.kind).toLowerCase()}…`);
  let committed = null;
  try {
    const response = await fetch('/api/record', {
      method: 'POST', headers: {'content-type': 'application/json'},
      // One way in, and it is the one the create form uses: the id, the path and
      // every rule about what a new record must carry are the server's, and two
      // ways to create a record is two sets of rules that disagree by Thursday.
      // The body is the kind's own template — the same map `/new` offers — so a
      // pitch made here is the same document as a pitch made there.
      body: JSON.stringify({base_commit: BASE.value, fields,
                            body: TEMPLATES[DRAFT.kind] ?? ''}),
    });
    const answer = await answerOf(response);
    if (!response.ok) { refused(refusalLines(answer, response.status)); return; }
    committed = answer.commit;
    BASE.value = answer.commit;
    markSaved(answer, answer.id);
    DRAFT = null;
    // Re-read rather than invented. A new row's dates, its size, what it blocks
    // and which project it counts against are all the server's arithmetic, and a
    // row drawn from what was posted would be a row missing every column the
    // scheduler fills in.
    const fresh = await refreshRows();
    draw();
    // Title AND id, and this is the one announcement on the page that needs
    // both. The id was minted by the server a moment ago and nobody has seen it
    // before — it is what a link, a `depends_on` and a `git show` are written
    // with — while the title is the only half the person who just typed it
    // recognises. Off `fields` rather than `namedOf(answer.id)`: on the `!fresh`
    // branch the rows were not re-read, so the new row is not in `DATA.rows` and
    // the name would fall back to the id twice over. `fields.title` is the
    // string this press refused to go out without, six lines up.
    const made = `${String(fields.title).trim()} (${answer.id})`;
    announce(fresh ? `Created ${made}` : `Created ${made} — reload to see it in place`);
    const add = document.getElementById('add-row');
    if (add) add.focus();
  } catch (error) {
    // The connection went while the request was in the air. With no `catch` the
    // rejection escaped unhandled — the `announce` above had already put a
    // present-continuous sentence in the live region ("Creating this task…"),
    // and nothing took it back out, so the page went on saying a record was
    // being made about a request that had stopped.
    //
    // `refused` is the shape a rejected create already has on this page: it puts
    // the draft row back with the reason on it, and the `finally` below clears
    // `CREATING` and redraws. No claim about what reached the server — a fetch
    // rejects when the answer is lost as readily as when the request never
    // left — and this press MINTS a record, so the advice is to look before
    // pressing again rather than to press again.
    //
    // **And the looking must not be a reload.** This said "Reload before pressing
    // Create again", one line under the call that has just put the typed row back
    // on screen: `DRAFT` is a plain `let` that deliberately does not survive a
    // reload (the reason is written at its declaration), so following that
    // instruction threw away everything the sentence had just preserved. A second
    // tab is the place that outlives the draft — and the table is the right page
    // to look at, because its draft row offers planned kinds only (`NEW_ROW`), so
    // anything created here does appear on it. The create FORM's twin sentence
    // cannot say "the table" for the same reason, and does not.
    refused([`Not created — ${error.message}. The row is still here and nothing `
             + 'typed is lost. Look for it in a second tab before pressing Create '
             + 'again, because a second press that both landed would make two '
             + 'records — reloading this tab would take the row with it.']);
  } finally {
    // Cleared on every way out of here — refused, thrown, or a 500 that never
    // parsed — because a flag that survives its own request is a row that can
    // never be created again without a reload. `refused` above has already
    // drawn, while this was still set and the check still disabled, so the
    // redraw that puts the control back has to happen after it: on the success
    // path there is no draft left to draw and `draw()` has run already, and
    // running it again here would throw away the focus just handed to `+`.
    CREATING = false;
    if (DRAFT) draw();
    // Announced even when refused, or one rejected create leaves every event
    // after it held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// ---------------------------------------------------------------------------
// A row you move
// ---------------------------------------------------------------------------

// Which row is being moved, whether it is being dragged or carried by the
// keyboard. One variable for both, because they are one act: what is legal, what
// is drawn and what is written are the same three answers whichever hand is on it.
let MOVING = null;

// Why that row may not hold this one, in words, or '' when it may.
//
// The rule is `PARENT_KINDS`, which is the model's, so this cannot drift from
// what the validator would say about the record afterwards. The sentence is this
// page's own — it is said *before* the write, about a gesture, where the
// validator's is said about a record that already exists.
function refuses(childId, parentId) {
  const child = DATA.rows[childId];
  const parent = DATA.rows[parentId];
  if (!child || !parent) return 'that row is not in this plan';
  // Dropping a row on itself is where it started, not a move, and the kind rule
  // would refuse it anyway — but "a task belongs to a pitch, not to a task" is
  // an odd thing to be told about the row under your own hand.
  //
  // By title throughout, through `titleOf` below. This is said about two rows
  // that are both on the screen — one under the hand, one under the cursor — so
  // what a reader is checking is which pieces of work they are, and a pair of
  // ids is the one form of that answer they cannot check without opening both.
  if (childId === parentId) return `${titleOf(childId)} cannot hold itself`;
  if (!(PARENT_KINDS[child.kind] || []).includes(parent.kind))
    return `a ${child.kind} belongs to ${holders(child.kind)}, not to a ${parent.kind}`;
  if (child.parent === parentId)
    return `${titleOf(childId)} is already in ${titleOf(parentId)}`;
  return '';
}

// Why this row may not be dropped on that target, in words, or '' when it may.
// The `+` row is the one target that is not a record: dropping on it means
// belonging to nothing, which is only a move when there is something to leave.
function whyNotOnto(childId, target) {
  if (target.classList.contains('adder'))
    return (DATA.rows[childId] || {}).parent ? '' : `${titleOf(childId)} is not inside anything`;
  return refuses(childId, target.dataset.id);
}

// Every row says whether it would take the one being moved, before the mouse
// gets anywhere near it. This is the whole of "refused while dragging": a row
// that cannot hold it is drawn refusing it from the moment it is picked up, and
// `dragover` never lets go of the drop on one of them, so a move that breaks
// containment is not a request that gets a 422 — it is a request that is never
// made.
function markTargets() {
  for (const tr of tbody.querySelectorAll('tr[data-id]')) {
    tr.classList.remove('can-hold', 'no-hold', 'over');
    if (!MOVING || tr.dataset.id === MOVING || tr.dataset.id === DRAFT_ID) continue;
    tr.classList.add(refuses(MOVING, tr.dataset.id) ? 'no-hold' : 'can-hold');
  }
  // The label goes with the mark, because they are one answer said twice — the
  // ground under the cursor and the words beside it. No row is `over` after this
  // runs, so a label still naming one is a label naming a row that is not lit,
  // and a redraw mid-drag is exactly when that happens.
  sayInto('');
}

// The row a drop would land in, named, next to the cursor.
//
// Not a dialog. A modal on every drag is a toll on a gesture that is already
// deliberate — you have to pick the row up, carry it and let go on the right one
// — and a reparent is one field and one commit that dragging it back undoes. The
// answer belongs where the hand already is, before the drop, rather than as a
// question after it.
//
// The title and not the id, because the ground under the cursor already says
// which row it is and what a person is checking at that moment is that it is the
// *right* row. `textContent`, so a title somebody typed is text here as it is
// everywhere else on this page.
//
// Parked on the body and positioned fixed, like the cells' suggestion popups:
// `.table-scroll` scrolls and clips its contents, and a label that scrolls out
// from under the cursor is worse than no label at all.
let INTO = null;
function sayInto(text, x, y) {
  // Nothing to say and nothing drawn yet is the state every table opens in, so
  // a page nobody drags anything on never grows the element at all.
  if (!INTO && !text) return;
  if (!INTO) {
    INTO = document.createElement('div');
    INTO.id = 'into';
    INTO.hidden = true;
    document.body.append(INTO);
  }
  INTO.hidden = !text;
  INTO.textContent = text || '';
  if (!text) return;
  // Below and right of the pointer, which is where the drag image is not.
  INTO.style.left = Math.round(x + 16) + 'px';
  INTO.style.top = Math.round(y + 18) + 'px';
}

// A row's own word for itself. The id is the fallback and not the label: a row
// with no title is a row nobody can find again, which the create path already
// refuses, but a plan hand-written in git can hold one.
const titleOf = id => (DATA.rows[id] || {}).title || id;

// The same row, said the other way: `Rewrite the dycore (task-c00001)`.
//
// One caller — `strandMarks`, the sentence about a save parked on a branch,
// which is the one thing this page says that only somebody with a checkout can
// act on, and a checkout finds a record by its id. Everything else here says the
// title alone, because the row is on the screen behind the sentence and the id
// under it answers a question nobody asked. (`createDraft` says both as well and
// does NOT come through here: the row it names was minted a moment ago and is
// not in `DATA.rows` on every branch, so it builds its name from the title the
// person typed. The reason is written there.)
//
// Not `${titleOf(id)} (${id})`: that draws `task-3 (task-3)` for a titleless row,
// where `titleOf`'s own fallback is meant to be the whole answer.
//
// `DATA.rows` and nothing wider, like `titleOf` above it: the plan pages are
// swept for inbox ids AND inbox titles, and a map with more in it than the rows
// is how a hand-written `parent: issue-…` rode onto the move bar once already.
const namedOf = id => {
  const title = (DATA.rows[id] || {}).title;
  return title ? `${title} (${id})` : id;
};

// What the label says over each of the two kinds of target. The `+` row is not a
// parent — it is the way out of the tree — so it says so in the other direction
// rather than naming itself.
function intoWords(target) {
  if (target.classList.contains('adder')) {
    const parent = (DATA.rows[MOVING] || {}).parent;
    return parent ? `→ out of ${titleOf(parent)}` : '';
  }
  return `→ into ${titleOf(target.dataset.id)}`;
}

// What the last row says while a move is in the air, and the whole of it.
//
// It was set imperatively in `startMoving` and nowhere else, which held exactly
// until something redrew the table underneath the move: `draw()` rebuilds the
// whole tbody, `adderHtml` emits the button hidden and wordless, and `moving` is
// still on the table — so `+ New row` stayed hidden, `#unparent:not([hidden])`
// stopped matching, and the sticky bar at the bottom of the plan painted as an
// empty strip while the live region still said "The row at the bottom takes it
// out of pitch-0a0001". Typing one character into the search box did it, as did
// any facet, any sort, and every keyboard move — which is the half of the
// gesture that redraws by design. Empty must not look like broken, and least of
// all while the page is telling somebody the opposite.
//
// So the answer is derived from `MOVING` wherever it is asked for: after every
// redraw, and again when a move starts or ends, which is when a native drag
// forbids a redraw. Both states are drawn, because a row that is already outside
// everything has nothing to be taken out of and the bar has to say so rather
// than go blank — the one control it would otherwise offer is the `+`, and
// pressing that in the middle of a move is not what anybody meant.
function sayMoveOut() {
  const out = document.getElementById('unparent');
  const rootless = document.getElementById('rootless');
  if (!out || !rootless) return;
  const row = MOVING ? DATA.rows[MOVING] : null;
  const parent = row ? row.parent : null;
  out.hidden = !parent;
  // The bar names both rows by title, like the label under the cursor already
  // does: this is a control somebody is about to press, and "Take task-0f1001
  // out of pitch-0f0001" makes them check two ids against a screen that draws
  // neither of them.
  out.textContent = parent ? `Take ${titleOf(MOVING)} out of ${titleOf(parent)}` : '';
  rootless.hidden = !row || !!parent;
  rootless.textContent = row && !parent ? `${titleOf(MOVING)} is not inside anything` : '';
}

function startMoving(id) {
  const row = DATA.rows[id];
  // `movable` asked here as well as where the grip is drawn and where Enter
  // refuses, so no third entry point can pick up a row those two gates hold —
  // the same question, asked of the same function, not a second spelling.
  if (!row || !movable(row)) return;
  MOVING = id;
  // On the table and not on each row: the stylesheet needs one switch to change
  // what the last row offers, and the marks below are per row.
  table.classList.add('moving');
  markTargets();
  sayMoveOut();
  announce(`Moving ${titleOf(id)}. Drop it on ${holders(row.kind)}, or press Enter on one. ` +
           (row.parent
             ? 'The row at the bottom takes it out of ' + titleOf(row.parent) + '. '
             : '') +
           'Escape leaves it where it is.');
}

function stopMoving(said) {
  MOVING = null;
  table.classList.remove('moving');
  markTargets();
  sayMoveOut();
  if (said) announce(said);
}

// The write. A parent is a field like any other, so this is the same PATCH, the
// same base commit, the same 409 and the same announcement as typing into a cell
// — the gesture is new, the save path is not.
async function reparent(childId, parentId) {
  const box = document.getElementById('row-conflict');
  box.hidden = true;
  box.textContent = '';
  // Both rows named HERE, before the write, and held for the sentences after it.
  //
  // Not a tidiness: the landed path calls `refreshRows()`, which REPLACES
  // `DATA.rows` wholesale with what the server just sent — so a `titleOf` after
  // that is a lookup in a map this gesture has already thrown away and rebuilt,
  // and it falls back to the bare id for any row the new payload does not
  // happen to carry. Driven through the shim, that is exactly what came out:
  // `task-c00001 is no longer inside anything` on the one path that is supposed
  // to say the row's name. Naming it at the moment somebody picked it up is also
  // what the sentence means — "this row was moved" is about the row they had.
  const childName = titleOf(childId);
  const parentName = parentId ? titleOf(parentId) : '';
  dispatchEvent(new Event('openproj:writing'));
  // Said before the request rather than after it. Every write here goes through
  // a fetch from the remote, a commit and a push, and against a repository on
  // GitHub that is seconds — during which the old page said nothing and left the
  // row where it was, which is indistinguishable from a drop that did not take.
  WRITING = childId;
  draw();
  announce(parentId ? `moving ${childName} into ${parentName}…`
                    : `taking ${childName} out…`);
  let committed = null;
  try {
    const response = await fetch(`/api/record/${encodeURIComponent(childId)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: {parent: parentId}, body: null}),
    });
    const answer = await answerOf(response);
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      return;
    }
    if (!response.ok) { announce(refusal(answer, response.status)); return; }
    committed = answer.commit;
    BASE.value = answer.commit;
    markSaved(answer, childId);
    // The rows, re-read, and not `DATA.rows[childId].parent = parentId`.
    //
    // `parent` is the one field on this page that nothing on this page can work
    // out the consequences of: it moves the row's cycle, its dates, what it
    // waits for and which project it counts against, and every one of those is a
    // column somebody is looking at. The rule one screen up — that a save
    // re-reads the problems and never the forecast — is about not moving dates
    // under somebody who is mid-edit; a drop is a gesture that is over, and a
    // table that does not move after one looks like a drop that did nothing.
    const fresh = await refreshRows();
    draw();
    announce(!fresh ? `${childName} was moved — reload to see where it landed`
             : parentId ? `${childName} is now in ${parentName}`
                        : `${childName} is no longer inside anything`);
  } catch (error) {
    // The connection went while the request was in the air, and the sentence
    // fifteen lines up says the move is still happening. `e82ce55` fixed exactly
    // this shape on the editing surface and recorded that the uploader and Save
    // were "the ones with a sentence left behind them"; they were not. This
    // gesture and `refile` on the graph both announce a present-continuous
    // sentence BEFORE the request and take it back only when an answer arrives,
    // so a rejection ran the `finally`, undimmed the row, and left the live
    // region reading `moving task-3 into project-a…` for ever — over a row still
    // drawn where it started, with nothing anywhere to say the drop did not take.
    //
    // And it does not guess. A fetch rejects when the ANSWER is lost as readily
    // as when the request never left, so this says what to do rather than what
    // happened: the drag is worth repeating either way, because the second one
    // goes out against the same `base_commit` carrying the same parent, and
    // `_merge_frontmatter` skips every key whose stored value already equals the
    // one being sent — so a drag that did land merges with itself and answers
    // 200 rather than being refused. Repeating it cannot move the row twice.
    announce(`${childName} was not moved — ${error.message}. Drag it again: it `
             + 'sends the same parent against the same base, so a drop that did '
             + 'land is not made twice.');
  } finally {
    // Whatever happened — committed, refused, or the network gone — the row
    // stops waiting. A row left dimmed after a refusal is a row that looks like
    // it is still going.
    WRITING = null;
    draw();
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// A write answered: remember its commit until a landing confirms it. Only when
// the server itself said `pushed: false` — that key absent means a server from
// before the push left the request path, and marking rows a server never
// promised to confirm is a mark that cannot clear.
function markSaved(answer, id) {
  if (answer.pushed !== false || !answer.commit) return;
  UNLANDED.set(answer.commit, id);
  armLandingPoll();
}

// The poll fallback, and it is an invariant rather than a comfort: Cloud Run
// recycles the event stream every 300 seconds and it has NO replay, so the
// frame that would have cleared a mark can be gone for good, and a mark only a
// frame can clear sticks forever on a tab that has been open a while. While
// anything is waiting, the page re-asks `/api/table.json` — the same re-read
// every create and every drop already does, so the rows it missed catch up in
// the same breath. Ten seconds because the pusher lands an ordinary save in
// about two: the frame wins the common case, and this fires for the tab that
// missed one.
const LANDING_POLL_MS = 10000;
let landingPoll = null;

function armLandingPoll() {
  if (landingPoll !== null || !UNLANDED.size) return;
  landingPoll = setTimeout(async () => {
    landingPoll = null;
    if (!UNLANDED.size) return;
    // Never over somebody's typing: the redraw a refresh ends in replaces the
    // whole tbody, and an open editor holds a value that exists nowhere else
    // yet. The poll waits its ten seconds again rather than costing a key.
    if (WRITING || CREATING || tbody.querySelector('td input, td select')
        || !document.getElementById('askfor').hidden) { armLandingPoll(); return; }
    // Guarded, because the fetch rejects in exactly the conditions this poll
    // exists for — a laptop waking onto the tick, a moment offline, a server
    // mid-restart — and the handle is already null by here, so an escaped
    // rejection would skip the re-arm below and end polling for the life of
    // the page. A failed poll is a poll to try again, not the end of polling.
    try {
      if (await refreshRows()) draw();
    } catch (error) {}
    armLandingPoll();
  }, LANDING_POLL_MS);
}

// Everything at or before this sha has landed. The tab's own saves are in
// UNLANDED in ancestry order — each went out against the last answer — so a
// frame naming one of them as landed, or as re-minted onto the landed tip, has
// confirmed every entry up to it. A sha this tab never saved clears nothing:
// clearing on "a landing happened after my save" instead would race the sync
// that read the branch tip just before the save committed, and show a commit
// as landed while it is still only here.
function clearedThrough(sha) {
  if (!UNLANDED.has(sha)) return false;
  for (const [held] of UNLANDED) {
    UNLANDED.delete(held);
    if (held === sha) break;
  }
  return true;
}

// The parked half of both messengers — the frame below and the poll's
// `settleMarks` — because the verdict is the same (sha, branch) pairs on both
// and a second copy would let the two drift into disagreeing about what
// parked means. A parked sha leaves UNLANDED as a PROBLEM, never a clear:
// the content is on GitHub but not on main, and nothing on this page
// resolves that.
function strandMarks(parked) {
  let moved = false;
  for (const [sha, branch] of parked || []) {
    const id = UNLANDED.get(sha);
    if (id === undefined) continue;
    UNLANDED.delete(sha);
    STRANDED.set(id, branch);
    // Into the live region as well as onto the row: the person was answered
    // 200 long ago, and a problem said only visually has not announced itself.
    // Title AND id, through `namedOf`. The only way out of a parked save is
    // somebody with a checkout of the branch this names, where a record is a
    // file called by its id — and the title is how they know which of their own
    // saves this was.
    announce(`${namedOf(id)} could not land on GitHub's main — its save is parked on ${branch}`);
    moved = true;
  }
  return moved;
}

// The pusher's confirmation, rebroadcast by the shell off the page's one event
// stream — see `broadcast` in web.py for the frame. Parked first, because a
// parked sha must leave UNLANDED as a problem BEFORE the clear pass below can
// walk past it. Then every sha the frame names — the tip it landed, and each
// OLD sha of the re-mint map, which is the only name this tab ever saw for
// that commit — clears its mark and every mark before it.
addEventListener('openproj:landed', event => {
  const {landed, remapped, parked} = event.detail;
  let moved = strandMarks(parked);
  for (const sha of [landed, ...Object.keys(remapped || {})])
    moved = clearedThrough(sha) || moved;
  if (moved) draw();
});

// The plan as it is now, in the shape this page was built from.
//
// `/api/table.json` and not `/api/index.json`: the second answers with the plan
// and spans, and turning those into rows means writing `_row` a second time in
// JavaScript — a progress fraction counted out of a body, a blocker count, a
// project walked up the tree. The route hands back the very payload the page was
// rendered with, so the table after a write is built exactly like the table
// before it.
async function refreshRows() {
  // Which marks this read may clear: the ones that existed when it was ASKED.
  // A save that answers while the request is in the air is not in the
  // payload's arithmetic, and clearing its mark off this answer would show a
  // commit as landed while it exists only on this instance.
  const asked = new Set(UNLANDED.keys());
  const response = await fetch('/api/table.json');
  if (!response.ok) return false;
  const fresh = await response.json();
  if (!fresh || !fresh.rows) return false;
  DATA.rows = fresh.rows;
  regroup(fresh.problems || []);
  summarise();
  // The shell's banner compares somebody else's commit against what this page is
  // showing. A row created here and left out of that list is a change to a row in
  // front of you that reads as news about somewhere else.
  window.SHOWING = Object.keys(DATA.rows);
  settleMarks(fresh, asked);
  return true;
}

// The poll half of mark-clearing; the frame half is the `openproj:landed`
// listener above. Parked FIRST, and off the payload by name, because a parked
// recovery leaves the pile honestly drained — the sha left main for a branch,
// so `unpushed` is 0 — and the drained-pile arm below would otherwise clear
// the one mark that had to become the problem: the page telling somebody
// their work is on GitHub when it is waiting on a pull request. (The payload
// can only name the shas this server process parked; a mark from before the
// process is past every messenger's reach.) Then the payload's `landed` — the
// confirmed tip — clears by name exactly as a frame's would; `unpushed === 0`
// covers the tab that reconnected: its own sha may never be spoken again,
// because the tip moved past it or a recovery re-minted it, and either way a
// drained pile means the remote holds it.
function settleMarks(fresh, asked) {
  strandMarks(fresh.parked);
  if (typeof fresh.landed === 'string') clearedThrough(fresh.landed);
  if (fresh.unpushed === 0)
    for (const sha of asked) UNLANDED.delete(sha);
}

if (EDITABLE) {
  // A press on a control in this table must not move the focus first.
  //
  // This is the whole of "the checkmark does nothing". `mousedown` on a button
  // focuses it, which blurs an open cell editor, and this page's blur handler
  // redraws: `stage` and the unchanged-value branch both call `draw()`, and
  // `draw()` replaces the entire `tbody` with `innerHTML`. So the button the
  // press started on is detached before `mouseup`, the two land on different
  // elements with no common ancestor still in the document, and the browser
  // dispatches NO click at all. The listener below never runs and the press is
  // gone — silently, because nothing failed. Reproduced in headless Chrome
  // against the deployed page: mousedown on the check, blur, mouseup, no click,
  // and `isConnected === false` on the button that took the press.
  //
  // Holding the focus is the fix rather than deferring the redraw, because a
  // deferred `draw()` leaves a window in which the DOM disagrees with `DRAFT`
  // and every later reader has to know about it. Nothing is lost by holding it:
  // a button reached with the keyboard is focused by Tab, which this does not
  // touch, and `draft-create` below takes what is in the open box on the way
  // past — which is the job blur would have done.
  //
  // Every button and not only the two that suffered most: the grip is a `<span>`
  // and never matches, so dragging is untouched, and a press that is thrown away
  // is a defect wherever it happens.
  tbody.addEventListener('mousedown', event => {
    if (event.target.closest('button')) event.preventDefault();
  });

  tbody.addEventListener('click', event => {
    const control = event.target.closest('button');
    if (!control) return;
    // Read before anything can redraw: `blur()` below replaces the `tbody`, and
    // the button this was read from is detached by the time it is needed.
    const pressed = control.id;
    // Create acts on what has been typed, and because the press above held the
    // focus, the last cell edited is still open and its value is still only in
    // the box. Closing it here runs the same blur the editor has always run —
    // `stage` for a draft cell, `saveCell` for a stored one — so Create writes
    // the row that is on the screen rather than the row as it was one cell ago.
    if (pressed === 'draft-create') {
      const open = tbody.querySelector('td.edit input, td.edit select');
      if (open) open.blur();
    }
    if (pressed === 'add-row') openDraft();
    else if (pressed === 'draft-cancel') closeDraft('The row was not created');
    else if (pressed === 'draft-create') createDraft();
    else if (pressed === 'unparent' && MOVING) {
      const child = MOVING;
      stopMoving();
      reparent(child, null);
    }
  });

  tbody.addEventListener('change', event => {
    if (event.target.id === 'draft-kind' && DRAFT) chooseKind(event.target.value);
  });

  // Dragging a row lives in `tbody` and resizing a column lives in `thead`, and
  // neither can fire the other: the column grips are `pointerdown` handlers on a
  // `<th>`, this is a native drag that only starts on a handle inside a `<td>`,
  // and there is no element that carries both. The narrower rule — that a row is
  // picked up by its grip rather than anywhere in its body — is the same rule
  // said more strictly, and it is what keeps a cell's text selectable and its
  // editor usable.
  tbody.addEventListener('dragstart', event => {
    const row = event.target.closest('tr[data-id]');
    if (!event.target.closest('.rowgrip') || !row || row.dataset.id === DRAFT_ID) {
      // A selection dragged out of a cell is not a move. Refusing it here is
      // what stops it looking like one.
      event.preventDefault();
      return;
    }
    startMoving(row.dataset.id);
    const carried = event.dataTransfer;
    if (carried) {
      // The id, because a drag that ends outside this table ends in whatever
      // takes text, and the id is the thing worth handing it.
      carried.setData('text/plain', row.dataset.id);
      carried.effectAllowed = 'move';
      if (carried.setDragImage) carried.setDragImage(row, 16, 12);
    }
  });

  tbody.addEventListener('dragover', event => {
    if (!MOVING) return;
    const over = event.target.closest('tr[data-id], tr.adder');
    for (const tr of tbody.querySelectorAll('tr.over')) tr.classList.remove('over');
    // The label goes with the mark, both ways: a row that refuses this one is
    // drawn refusing it and is not named as somewhere it could land.
    if (!over || whyNotOnto(MOVING, over)) { sayInto(''); return; }
    // `preventDefault` is the whole of "you may drop here". Not calling it is
    // how a row refuses: the browser draws its own no-drop cursor over it and
    // `drop` never fires, so the refusal is structural rather than a check
    // somebody has to remember to write at the other end.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    over.classList.add('over');
    sayInto(intoWords(over), event.clientX || 0, event.clientY || 0);
  });

  tbody.addEventListener('drop', event => {
    event.preventDefault();
    const over = event.target.closest('tr[data-id], tr.adder');
    const child = MOVING;
    stopMoving();
    if (!child || !over) return;
    // Asked again here, although `dragover` already refused to let a drop land
    // on a row that cannot take it. What enforces that refusal is the browser,
    // and this file's standing rule is that the browser is assumed to refuse:
    // one implementation that delivers a drop nobody permitted is a blocker
    // committed into the corpus by a hand gesture. `whyNotOnto` is the one
    // answer both handlers ask for, so the two cannot disagree about it.
    const why = whyNotOnto(child, over);
    if (why) { announce(why); return; }
    reparent(child, over.classList.contains('adder') ? null : over.dataset.id);
  });

  // Fires however the drag ended — dropped, cancelled with Escape, let go over
  // the desktop — so it is the one place the marks have to come off.
  tbody.addEventListener('dragend', () => stopMoving());

  tbody.addEventListener('dblclick', event => {
    const cell = event.target.closest('td.edit');
    // The tag reveal is a control inside an editable cell, so a double-click on
    // it would both open the list and open the editor over it.
    if (!cell || event.target.closest('button.more')) return;
    openEditor(cell);
  });

  // **Picking cells for a bulk edit.** cmd on a Mac and ctrl everywhere else —
  // `metaKey || ctrlKey`, which is what every list on either platform means, and
  // asking the platform instead would be a second thing to get wrong.
  //
  // On `click` and not on `mousedown`, so a modifier-drag across cells selects
  // text the way it always has. And `preventDefault` on the press, because
  // cmd-click already means something to the browser on a link and shift-click
  // means "extend the text selection" everywhere — a range picked with shift
  // would otherwise arrive with half the table highlighted behind it.
  tbody.addEventListener('mousedown', event => {
    if ((event.metaKey || event.ctrlKey || event.shiftKey)
        && event.target.closest('td.edit')) event.preventDefault();
  });
  tbody.addEventListener('click', event => {
    const cell = event.target.closest('td.edit');
    if (event.metaKey || event.ctrlKey) {
      if (cell) { event.preventDefault(); pick(cell, false); }
      return;
    }
    if (event.shiftKey) {
      if (cell) { event.preventDefault(); pick(cell, true); }
      return;
    }
    // Any plain click anywhere in the table puts the selection down. A selection
    // that survives an ordinary click is a selection somebody has forgotten
    // about, and the next cell they open writes six records.
    if (PICKED.size) unpick();
  });

  tbody.addEventListener('keydown', event => {
    // Escape abandons the row nobody has created yet, from anywhere inside it.
    // The two controls it has are marks rather than words, and a person who
    // reached them with Tab should not have to work out which drawing is the way
    // out — this is the key every dismissable thing on this page already answers
    // to, and `closeDraft` says out loud what it did.
    //
    // Two things get it first, both by design. A move in the air owns Escape
    // until it lands, which is why `MOVING` is asked here rather than below. And
    // an open cell editor never reaches this line at all: its own Escape stops
    // the bubble, because discarding one cell and discarding the whole row are
    // different sizes of undo and the smaller one is what was pressed.
    if (event.key === 'Escape' && DRAFT && !MOVING
        && event.target.closest('tr.draft, tr.adder')) {
      event.preventDefault();
      closeDraft('The row was not created');
      return;
    }
    const cell = event.target.closest('td[tabindex]');
    // Only a cell's own keys. Once an editor is open the keys belong to it — its
    // Escape discards and its Tab commits — and the grid must not act as well.
    if (!cell || event.target !== cell) return;
    // A move in the air owns Enter and Escape until it lands. The arrows keep
    // working, because moving to the row you mean is the whole of the gesture —
    // this is the drag, walked instead of dragged, and the same rows are lit and
    // the same rows refuse.
    if (MOVING) {
      if (event.key === 'Escape') {
        event.preventDefault();
        stopMoving(`${titleOf(MOVING)} was left where it was`);
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        const onto = cell.parentNode.dataset.id;
        const why = refuses(MOVING, onto);
        // The same sentence the drawn refusal is drawn from, said out loud —
        // because the drawn one is the half a keyboard reader does not get.
        if (why) { refuse(cell, why); return; }
        const child = MOVING;
        stopMoving();
        reparent(child, onto);
        return;
      }
    }
    // The id cell is the handle's keyboard equal: it is the cell that is the
    // row's own name, and it is where the grip is drawn.
    if (event.key === 'Enter' && cell.dataset.col === 'id') {
      event.preventDefault();
      const row = DATA.rows[cell.parentNode.dataset.id];
      if (row && movable(row)) startMoving(row.id);
      else if (row) refuse(cell, moveTip(row));
      return;
    }
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
// One `open` class and two controls that set it — the badge in the cell and the
// `+` in the header — so a cell is in one state however it got there, and there
// is no third one to reason about. Both are toggles, and the badge's name is
// swapped here because an icon-only control's name is the whole of what it says.
function setOpen(td, open) {
  td.classList.toggle('open', open);
  const badge = td.querySelector('button.more');
  if (badge) {
    badge.setAttribute('aria-label', open ? badge.dataset.collapse : badge.dataset.expand);
  }
}

// The cells in one column that have anything to open. A list that already fits
// draws no badge, and counting those would leave a column of seventeen cells
// with nothing hidden in it reporting itself as closed forever — a `+` offering
// to do nothing.
function openable(key) {
  return [...tbody.querySelectorAll(`td[data-col="${key}"].clamp`)]
    .filter(td => td.querySelector('button.more'));
}

tbody.addEventListener('click', event => {
  if (event.target.id === 'clear-filters') { clearFilters(); return; }
  const more = event.target.closest('button.more');
  if (!more) return;
  const td = more.closest('td');
  setOpen(td, !td.classList.contains('open'));
  // The column's control offers whatever the column is not already doing, so
  // opening the last closed cell by hand is what turns its `+` into a `−`.
  syncExpanders();
});
// A derived cell that ignores a double-click looks exactly like a cell that is
// broken. It answers instead, in the same place a refused save answers — and
// through `announce`, so the answer reaches a reader who cannot see that place.
// `why` is a parameter and not only the cell's own: a row refusing to hold
// another one is the same event — a cell answering instead of acting — and the
// sentence belongs to the pair rather than to the cell.
// Escape with nothing open puts the selection down, which is what Escape means
// everywhere else on this page — it closes an editor, it abandons a draft row,
// and it cancels a move. A selection is the fourth thing it can be holding.
addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !PICKED.size) return;
  if (tbody.querySelector('td.edit input, td.edit select')) return;
  unpick();
});

function refuse(cell, why) {
  announce(why || cell.dataset.why);
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
// because the table shows every record rather than one. So the table says what
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
// Bumped a third time when the kind chip left the id cell: a width dragged for
// `PITCH pitch-0c0001` is 60px of empty column beside `pitch-0c0001`.
const WIDTH_KEY = 'openproj:widths:4';
const WIDTHS = trustworthy(remembered.map(WIDTH_KEY));

// A remembered width of zero is not a narrow column, it is a corrupt entry — and
// half-trusting one is worse than ignoring the lot. Skipped at apply time the
// column still DREW, so the table was set narrower than the columns it contains
// and every one of them squeezed until the text wrapped; measured instead, it
// measures the squeeze it is already in and stays there. A stored
// `"progress":0` made the header and the first six rows up to five times their
// height, on one machine, at every window width, until that entry was deleted by
// hand. So a map with a nothing in it is thrown away and the fit runs, which
// heals a browser that already holds one without anybody being told to clear it.
function trustworthy(stored) {
  if (!Object.values(stored).some(width => !(width > 0))) return stored;
  // Cleared, not merely ignored: left in place it is re-read and re-rejected on
  // every load forever, and it is the first thing somebody debugging this would
  // find and have to reason about.
  remembered.forget(WIDTH_KEY);
  return {};
}

// Whether the columns are still the fit's to decide. It goes false the moment a
// grip is let go, and never comes back: after that the widths are a decision
// somebody made, and a refit — on a resize, or when the real face lands — would
// be the page quietly undoing it.
let automatic = !Object.keys(WIDTHS).length;
let dragging = false;
const table = document.getElementById('rows');
const headers = [...table.querySelectorAll('th')];
// The box the rows scroll in. It is what the table is fitted to, and what says
// whether the frozen columns are holding anything back yet.
const scroller = table.parentElement;

// The one column that takes whatever is left over. It clamps to a single line
// and hides the rest behind a `+N`, so it is the only column that can be handed
// space, or refused it, without changing what the row says.
const SPARE_COLUMN = 'tags';

// Who pays for an overflow, in order.
//
// The clamped columns pay first. They already show one item and a `+N`, so a
// narrower one hides an item behind a badge that is right there and says how
// many — the cheapest thing on the page to give up. Then the squeezable ones: the
// title, which is a sentence, and the owner, which is one name. Those degrade by
// wrapping, which costs height on every row that holds a long value.
//
// The order is the whole point, and it was wrong the other way round. With `prs`
// exempt, a 1460px window put `title` on its 110px floor — the column you read —
// while `prs` kept all 172px of a reference you can also get by opening the row.
// Every column named in neither keeps exactly what it measured: a date, a count
// and a cycle number have one right width and no graceful way to be narrower.
// The four columns that hold a list, drawn as one item and a `+N`, and the four
// the fit narrows first. One set, because it is one fact: a column may be made
// narrower exactly when its overflow already has somewhere to go.
const CLAMPED = new Set(['tags', 'prs', 'assignees', 'reviewers']);
const SQUEEZABLE = new Set(['title', 'owner', 'progress']);
// What the table gives up when it runs out of room, in the order it gives them
// up. All four are lookups rather than answers — each is on the detail page and
// each stays filterable in the facets above — so they are what it can lose and
// still answer the question it is open for.
// `prs` goes first: every reference in it is a link the row's own detail page
// carries, and the badge that hides the rest is the same badge there. `progress`
// used to go first and no longer does — it is a bar now rather than a bar and a
// count, so it narrows to a floor instead of leaving, which is a column kept for
// 78px. `tags` is last because it is the column that absorbs whatever is left
// over: while it is drawn the table fills its container exactly, and once it is
// gone the fit can only leave a gap at the right.
const LOOKUPS = ['prs', 'reviewers', 'progress', 'tags'];
// The two columns that are `position: sticky` — see `[data-col="id"]` and
// `[data-col="title"]` in the stylesheet. Named here because the fit has to know
// how wide they are, and a second list of them is a second thing to keep in step;
// if a third column is ever frozen, it is this line and that rule together.
const FROZEN = ['id', 'title'];
// Every column that can go, which is the four lookups plus the id. It is the list
// the shed CLASSES are toggled from, and not the order anything is shed in: the
// lookups go by `LOOKUPS` above and the id goes by a rule of its own — see
// `drawnColumns`.
const SHED = [...LOOKUPS, 'id'];
// One class per column and not one for the set, because they go one at a time.
const shedClass = key => 'shed-' + key;

// A column's identity is the field it stands for. It used to be the column's
// POSITION for the two that do not sort, so inserting a column anywhere to their
// left silently handed prs the width somebody had dragged for blockers — and
// then it was the header's own text, which tied a remembered width to the word
// printed above it rather than to the column.
const keyOf = th => th.dataset.col;
const FLOOR = 110;      // narrower than this and a squeezed column is unreadable
// The title is a SENTENCE and the other squeezable column is a login, so one
// floor cannot serve both: at 110 a title wraps over three lines and the row it
// is in stands three rows tall, which on a laptop is what a screenful of this
// table looked like. 250 is where the seed corpus's and jcanton's own titles
// mostly stop wrapping; below it the fit sheds a lookup column instead, and
// below THAT the table scrolls sideways with the id and the title frozen — which
// is the arrangement jcanton got by double-clicking a column separator and
// asked whether it could be the starting point.
//
// So: the same fit, with the one column that holds prose allowed to keep enough
// room to hold it. Nothing else about the layout moves.
const TITLE_FLOOR = 250;
// **A floor is a promise about the column, and 250 was also a promise about the
// window.** It says "a title should not have to wrap", which is true of a laptop
// and is not a thing a 390px phone can offer anything: at that viewport the table
// has 335px of room, and a column demanding 250 of it left 85 for everything
// else while the frozen pair it is half of measured 372 — wider than the box it
// is frozen inside.
//
// So the floor is the smaller of the promise and a share of the room. 45%, which
// is the same bargain the timeline's label column strikes and for the same
// reason: the identity of the row gets the larger share of a narrow box, and what
// is left is still enough to scroll something into.
//
// 140 underneath it, because a share of nothing is nothing. It is `CLAMP_FLOOR`
// plus a little — the narrowest this table asks any column to be while still
// saying something — and below it a title stops being a name and becomes an
// ellipsis.
//
// It changes nothing a laptop sees: at 45% the share only falls under 250 below
// about 556px of table room, which is a window under 600. Measured at 1400, where
// this and every other resolved width are byte-identical to before.
const titleFloor = room => Math.max(140, Math.min(TITLE_FLOOR, Math.round(room * 0.45)));
// And the progress column is a BAR now, not a bar and a count, so it narrows
// rather than leaving: 78px holds its header on one line and a meter wide enough
// to read a fraction off. It used to be the first thing shed, which was right
// when it was the widest column on the row and is not now.
const PROGRESS_FLOOR = 78;
// A clamped column shows one item and a badge, and its header above them. Set to
// 76 — the badge and a short tag — the fit drove all four to that and `REVIEWERS`
// wrapped over two lines above a truncated login, which is a narrower column and
// a taller row: exactly what the clamp was for, undone. A column is only worth
// narrowing while it still says something.
//
// 116 and not the 112 it was, because these four headers now carry the column's
// `+` as well: `.5rem` of padding, then `REVIEWERS` and its sort glyph, then the
// 2rem the control and the grip stand in. Measured in Chrome at each width in
// turn — at 112 and at 115 `ASSIGNEES` and `REVIEWERS` wrap over two lines, and
// at 116 all four fit on one. The floor went up to pay for the control rather
// than the control shrinking to fit under the old one: it is a 17px target in a
// header that already holds a sort button and a drag handle, and the mis-click
// that sorts the table when somebody meant to expand it is what those four
// pixels of column buy.
const CLAMP_FLOOR = 116;
// Which floor a column has, in one place: `minimumWidth` decides what the table
// can be squeezed to and `fitted` does the squeezing, and two copies of this
// question is how those two come to disagree about a single column.
const floorFor = (key, room) => key === 'title' ? titleFloor(room)
  : key === 'progress' ? PROGRESS_FLOOR
  : CLAMPED.has(key) ? CLAMP_FLOOR
  : SQUEEZABLE.has(key) ? FLOOR : Infinity;

// What each column would need with every cell on one line, so a column ends up
// as wide as its widest value needs and not one character more. Measured from a
// layout that has forgotten the widths already applied, or a column can only
// ever be measured wider than it currently is.
function naturalWidths() {
  const applied = headers.map(th => th.style.width);
  headers.forEach(th => { th.style.width = ''; });
  // Every column, drawn or shed. What a shed column would need is exactly how
  // the fit decides whether there is room to draw it again, and a column that is
  // `display: none` measures zero — so measured with the shedding undone and put
  // back before anything can paint.
  const shedding = SHED.map(shedClass).filter(one => table.classList.contains(one));
  table.classList.remove(...SHED.map(shedClass));
  table.classList.add('measuring');
  table.style.tableLayout = 'auto';
  table.style.width = 'max-content';
  const natural = headers.map(th => Math.ceil(th.getBoundingClientRect().width));
  table.classList.remove('measuring');
  table.classList.add(...shedding);
  headers.forEach((th, i) => { th.style.width = applied[i]; });
  return natural;
}

// The narrowest this set of columns can be drawn: each one on its floor, or at
// what it measured where that is already narrower. It is the same three numbers
// `fitted` works from and the same two floors, so the number below which the
// table starts scrolling and the number that decides which columns are drawn
// cannot disagree.
//
// They did. The shedding was a typed `@media (max-width: 1100px)` while the
// floors put the fourteen-column minimum at 1354px, so every window from 1101 to
// 1393 scrolled sideways with all fourteen columns it had been told it could
// keep — 293px of overflow at the low end. Two numbers that have to agree,
// written in two languages, drifting; now there is one and it is measured.
function minimumWidth(natural, keys, room) {
  return keys.reduce(
    (total, key, i) => total + Math.min(Math.ceil(natural[i]), floorFor(key, room)), 0);
}

// Which columns this much room can hold, as `[key, width]` pairs in the order
// they are drawn — and the whole of the responsive layout, so that it is
// arithmetic a test can run at any window rather than a rule only a browser can
// answer.
//
// One column at a time, and only while what is left over still will not fit: the
// window at which a column goes is the window at which the fit would otherwise
// have to start scrolling, for each of them in turn. All three at once is a cliff
// — at 1354px the table would drop a fifth of what it says to buy 300px it needs
// 112 of.
function drawnColumns(natural, keys, room) {
  let drawn = keys.map((key, i) => [key, natural[i]]);
  const needs = () => minimumWidth(drawn.map(one => one[1]), drawn.map(one => one[0]), room);
  for (const key of LOOKUPS) {
    if (needs() <= room) break;
    drawn = drawn.filter(one => one[0] !== key);
  }
  // **The id goes by a different question, because it answers a different one.**
  // The four above go while the TABLE will not fit. The id and the title are
  // frozen, and a frozen pair is not paid for out of the table's width — it is
  // paid for out of the window, every moment the table is scrolled. At a 390px
  // viewport that pair measured 372px inside a 335px box: the columns that hold
  // still were wider than the box they hold still inside, so scrolling right
  // moved nothing into view because there was no view left to move it into.
  //
  // So the rule is about the reader and not about the fit: **what holds still
  // must leave at least a third of the box to scroll into.** Below that the
  // frozen pair has stopped being a way to keep your place and become the view.
  // The fraction is the only judgement here; everything else is measurement.
  //
  // Two thirds and not half, and CI is why the number is written down rather
  // than chosen. At half, a 700px window sheds the id: the pair is 372px of 660
  // and `test_the_header_and_the_frozen_pair_hold_when_the_rows_are_tall` drives
  // exactly that window, so a test about scrolling a tall table failed on a
  // column that had gone. Nothing was wrong at 700 — 372 of 660 leaves 288px to
  // scroll into, which is four columns. At two thirds the rule bites below about
  // 558px of room, which is a window under 600.
  //
  // Asked of the same `minimumWidth` the fit is decided by, so the pair is
  // measured the way it will be drawn — the title on its floor where the room is
  // tight, and at its natural width where it is not.
  const frozen = drawn.filter(one => FROZEN.includes(one[0]));
  const held = minimumWidth(frozen.map(one => one[1]), frozen.map(one => one[0]), room);
  if (held > room * 2 / 3) drawn = drawn.filter(one => one[0] !== 'id');
  return drawn;
}

// The fit itself, as arithmetic over three numbers per column and nothing else:
// what the column needs on one line, what it is called, and how much room there
// is. Separate from the measuring because the browser is the only thing that
// knows how wide `Second-order Miura least-squares coefficients` is, and the
// decision made from that number needs no browser at all — which is how it gets
// tested against a window it never has to be opened in.
//
// Every width here is the measured one. It used to be `Math.ceil(w * 1.1)`, a
// 10% cushion on twelve columns that was most of a 1792px table inside a 1460px
// window: the table arrived scrolling sideways, on a plan of seventeen rows.
function fitted(natural, keys, room) {
  const width = natural.map(w => Math.ceil(w));
  let over = width.reduce((a, b) => a + b, 0) - room;

  // Worst-first, by levelling: the widest column in the group comes down to the
  // second widest, then those two come down to the third, and so on until the
  // overflow is paid for or the group is on its floor. A proportional cut instead
  // takes the same 18% off a 300px sentence and a 110px login, so the column that
  // was already the narrowest pays as much as the one that caused the overflow.
  const level = group => {
    while (over > 0) {
      const flex = keys.map((_, i) => i)
                       .filter(i => group.has(keys[i]) && width[i] > floorFor(keys[i], room));
      if (!flex.length) return;
      const worst = Math.max(...flex.map(i => width[i]));
      const paying = flex.filter(i => width[i] === worst);
      const floor = Math.max(...paying.map(i => floorFor(keys[i], room)));
      const next = Math.max(floor, ...flex.filter(i => width[i] < worst).map(i => width[i]));
      const step = Math.min(worst - next, Math.ceil(over / paying.length));
      paying.forEach(i => { width[i] -= step; });
      over -= step * paying.length;
    }
  };

  level(CLAMPED);
  level(SQUEEZABLE);

  // Whatever is left over — a window wider than the plan needs, or the pixel or
  // two the levelling overshot by — goes to the one column that can hold it
  // without changing what any row says.
  const spare = keys.indexOf(SPARE_COLUMN);
  if (over < 0 && spare !== -1 && width[spare] > 0) width[spare] -= over;
  return width;
}

// A collapsed border is drawn between the columns, not inside them, so the table
// renders a pixel or two wider than the sum `applyWidths` sets — and two pixels is
// a horizontal scrollbar across the whole plan just as surely as two hundred are.
// Measured rather than assumed: it depends on the border width, the zoom and how
// the browser rounds, and this table is drawn at whatever zoom somebody left it at.
function chromeOverhead() {
  const set = Number.parseFloat(table.style.width) || 0;
  return set ? Math.max(0, Math.ceil(table.getBoundingClientRect().width - set)) : 0;
}

function fitWidths() {
  const keys = headers.map(keyOf);
  const natural = naturalWidths();
  const fit = room => {
    // Which columns are drawn is this measurement and nothing else — it was a
    // typed breakpoint 254px away from the number it had to agree with.
    const drawn = drawnColumns(natural, keys, room);
    const kept = new Set(drawn.map(one => one[0]));
    SHED.forEach(key => table.classList.toggle(shedClass(key), !kept.has(key)));
    const width = fitted(drawn.map(one => one[1]), drawn.map(one => one[0]), room);
    // Floored, because a fit that squeezes a column to nothing writes a nothing
    // into storage that outlives the window it was measured in.
    drawn.forEach(([key], i) => { WIDTHS[key] = Math.max(1, Math.round(width[i])); });
    applyWidths();
  };
  fit(scroller.clientWidth);
  // Once round to find out what the border costs, and once more to pay for it.
  // Not a loop: the second fit cannot change the overhead, only what is left after
  // it, and a fit that chased its own tail would be a fit that never settled.
  const overhead = chromeOverhead();
  if (overhead) fit(scroller.clientWidth - overhead);
}

// The smallest a column is allowed to become when the stored widths are scaled
// down to fit. The same floor the drag uses, for the same reason: past it the
// column is a sliver with nothing readable in it, and a table that fits the
// window by making every column unreadable has not fitted anything.
const COLUMN_FLOOR = 40;

// The dragged widths, scaled so their total is the room there is.
//
// A width somebody dragged is a decision about PROPORTION, not about pixels: it
// says this column deserves twice the room of that one, on the window it was
// dragged in. Replayed as pixels into a different window it is wrong in both
// directions — a gap down the right when the window grows, and a table wider
// than the page when it shrinks, which is what jcanton reported on 2026-08-20.
//
// Derived from the stored numbers every time rather than by scaling what is
// already applied, so it is idempotent: ten resizes give the same answer as one,
// where a compounding scale would drift the layout away from what was dragged.
function scaledWidths(room) {
  const drawn = headers.filter(th => th.offsetParent !== null);
  const stored = drawn.map(th => WIDTHS[keyOf(th)] || 0);
  const total = stored.reduce((sum, one) => sum + one, 0);
  if (!total || !room) return null;

  // A plain multiply does not fit. Any column the factor would push under the
  // floor is held at the floor instead, which takes room from the others — and
  // that can push the NEXT one under it. So the pinning repeats until nothing
  // more goes under, and only then is the rest shared out. Multiplying once and
  // clamping afterwards was 771px of table in a 700px window.
  const pinned = new Array(drawn.length).fill(false);
  let left = room;
  let pool = total;
  for (let pass = 0; pass < drawn.length; pass++) {
    let moved = false;
    for (let i = 0; i < drawn.length; i++) {
      if (pinned[i] || pool <= 0) continue;
      if (stored[i] * (left / pool) < COLUMN_FLOOR) {
        pinned[i] = true;
        left -= COLUMN_FLOOR;
        pool -= stored[i];
        moved = true;
      }
    }
    if (!moved) break;
  }

  const out = {};
  let given = 0;
  let widest = 0;
  drawn.forEach((th, i) => {
    const width = pinned[i] || pool <= 0
      ? COLUMN_FLOOR
      : Math.max(COLUMN_FLOOR, Math.round(stored[i] * (left / pool)));
    out[keyOf(th)] = width;
    given += width;
    if (!pinned[i] && width > out[keyOf(drawn[widest])]) widest = i;
  });
  // The rounding remainder, onto the widest column that is not at its floor. A
  // dozen columns each half a pixel out is six pixels of horizontal scrollbar,
  // and a scrollbar is the thing this whole function exists to avoid.
  const slack = room - given;
  if (slack && !pinned[widest]) {
    const key = keyOf(drawn[widest]);
    out[key] = Math.max(COLUMN_FLOOR, out[key] + slack);
  }
  return out;
}

function applyWidths(widths) {
  widths = widths || WIDTHS;
  if (!Object.keys(widths).length) return;
  table.style.tableLayout = 'fixed';
  let total = 0;
  headers.forEach(th => {
    // A column the narrow breakpoint dropped is not part of the total. Counted
    // in, the table is set wider than the columns it actually draws and the last
    // one floats away from the right edge of nothing.
    if (th.offsetParent === null) { th.style.width = ''; return; }
    const key = keyOf(th);
    if (widths[key]) { th.style.width = widths[key] + 'px'; total += widths[key]; }
  });
  // The table stops being 100% wide once the columns are explicit. Left at 100%,
  // a fixed layout divides the space it is given, so widening one column silently
  // squeezes every other — which is precisely what freezing them was meant to
  // prevent. It scrolls sideways in its own container instead.
  table.style.width = total + 'px';
  tighten();
  stickyOffset();
}

// A column too narrow for its word keeps its MARK and drops the word — jcanton,
// 2026-08-20, having seen `» IN PROGRESSjcanton` run through the Owner column on
// a narrowed window.
//
// The chip cannot wrap: "IN PROGRESS" broken over two lines is not a chip. And it
// had nowhere to put the overflow, because `status` is in neither `CLAMPED` nor
// `SQUEEZABLE`, so the fit hands it a width and nothing clips what does not fit.
// Priority was in neither either and got away with it only because plain text
// wraps — which is the `Medi um` in the same screenshot, the same defect wearing
// different clothes.
//
// Dropping to the mark rather than clipping with an ellipsis: `IN PROG…` teaches
// nothing and reads as a defect, and the marks are already taught — the graph's
// legend explains `»` and the five bars, and the timeline already drops its own
// glyph below `_GLYPH_MIN_PX` when a bar is too narrow to hold it. So a narrow
// column falls back to a notation the reader has been shown rather than to a word
// cut in half.
//
// Asked of the cell rather than answered with a number. A threshold in pixels has
// to be re-derived every time the chip's padding, the mark or the typeface moves,
// and the first version of this was measured against content that had ALREADY
// been shrunk — so priority reported itself too narrow at every width, for ever.
//
// So: show the word, ask whether it fits, then decide. One forced reflow per
// column per fit, which happens on a resize and not on a frame.
const TIGHTENS = ['status', 'priority', 'dates'];

// The two date columns tighten together — `07.14` under START beside `26.08.05`
// under END would read as two different things — so they are one name here and
// the class covers both.
const TIGHT_COLUMNS = {status: ['status'], priority: ['priority'], dates: ['start', 'end']};

function tighten() {
  for (const key of TIGHTENS) {
    table.classList.remove(`tight-${key}`);
  }
  for (const key of TIGHTENS) {
    let over = false;
    const columns = TIGHT_COLUMNS[key] || [key];
    for (const cell of table.querySelectorAll(
        columns.map(one => `td[data-col="${one}"]`).join(', '))) {
      if (!cell.firstElementChild) continue;
      // The CELL's own overflow, not the inner element's. The chip is an
      // inline-flex box that shrinks to whatever it is given and then reports
      // itself content: asking it whether it fits, it always says yes while its
      // contents hang out of the cell — which is why priority went on
      // overflowing after status had been fixed.
      //
      // And it only overflows if the word inside it cannot wrap. `.chip` is
      // `white-space: nowrap`, which is why status has always tightened on time;
      // the old priority cell let its word wrap, so a narrow column turned
      // "Medium" into six lines of one letter and never reported itself over —
      // jcanton, 2026-08-20, with a screenshot of exactly that.
      if (cell.scrollWidth > cell.clientWidth + 1) { over = true; break; }
    }
    table.classList.toggle(`tight-${key}`, over);
  }
}

// The title column has to begin exactly where the id column ends, and that width
// is dragged, remembered and re-fitted — so it is measured after layout rather
// than written into the stylesheet, where it would be wrong the first time
// somebody moved a grip.
function stickyOffset() {
  table.style.setProperty('--sticky-1', headers[0].getBoundingClientRect().width + 'px');
}

// Expanding a whole column: one click opens every clamped cell in it, one more
// closes them again. Built from `CLAMPED` and not from a second list of column
// names — the set that decides which cells clamp is the set that decides which
// headers can unclamp them, or the two drift and a column grows a control for a
// badge it does not draw.
//
// It lands in a `<th>` that already holds a sort button and a drag grip, and a
// mis-click that sorts the table when somebody meant to expand it is the failure
// this is designed against. Three things answer it:
//
//   * it is a sibling of the sort button, never a child of it: inside, its click
//     would be the button's click and sorting would happen on the way;
//   * the click stops here, because the `<th>` itself is what sorts — the grip
//     already had to do exactly this for the same reason;
//   * the room it stands in is reserved in the header's own padding (`.expands`
//     in the stylesheet), so it is never drawn over the label, and `CLAMP_FLOOR`
//     is the width at which the label, the sort glyph, the control and the grip
//     all still fit. That floor went up to pay for the control. The alternative
//     was a smaller target in a 112px column beside two other things to hit,
//     which is the mis-click written down as a decision.
//
// The two header shapes end up as one control: `assignees` and `reviewers` sort
// and hold a button, `prs` and `tags` are bare text, and in both the label is at
// the left of the cell and the `+` is at the right of it.
const expanders = new Map();
for (const th of headers) {
  const key = keyOf(th);
  if (!CLAMPED.has(key)) continue;
  th.classList.add('expands');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'expand';
  // Appended before the grip is, below, so the reading order is label, control,
  // grip — the order they are drawn in.
  th.append(button);
  button.onclick = event => {
    event.stopPropagation();
    // What it does is the inverse of what the column is already doing, and the
    // class it reflects that with is set by `syncExpanders` from the cells
    // themselves. Firing blindly, a `−` on a column somebody had closed by hand
    // would close what was already closed and look broken.
    const open = !button.classList.contains('open');
    for (const td of openable(key)) setOpen(td, open);
    syncExpanders();
  };
  expanders.set(key, button);
}

// What each column control offers, read off the column rather than remembered.
// Nothing here is stored: a redraw replaces every cell and takes the state with
// it, and that is the point — this is a way of reading the plan, not a setting.
// A filter can also leave a column with nothing hidden in it, and a control with
// nothing to do goes rather than sitting there lying about what it will do.
function syncExpanders() {
  for (const [key, button] of expanders) {
    const cells = openable(key);
    const open = cells.length > 0 && cells.every(td => td.classList.contains('open'));
    button.hidden = !cells.length;
    button.classList.toggle('open', open);
    // The column's own word, lowercased the way the cells' tooltips say it, so
    // "Show all reviewers" and "Double-click to edit reviewers" name the same
    // column the same way. A `title` as well, because the sighted reader of an
    // icon has the same question — but never a `title` alone: this is a control,
    // not a hint.
    const named = (FIELD_LABELS[key] || key).toLowerCase();
    const name = open ? `Show fewer ${named}` : `Show all ${named}`;
    button.setAttribute('aria-label', name);
    button.title = name;
  }
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
    const key = keyOf(th);
    WIDTHS[key] = Math.ceil(naturalWidths()[i]);
    remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
    automatic = false;
    applyWidths();
  };
  grip.onpointerdown = event => {
    event.stopPropagation();
    event.preventDefault();
    // The click that follows a drag lands on the header, not the grip, so
    // stopping propagation here is not enough — the sort handler checks this.
    dragging = true;
    grip.classList.add('dragging');
    // Freeze every column at the width it is DRAWN AT, or resizing one reflows
    // all the others.
    //
    // **Measured, never `WIDTHS[key] ||`.** That is the defect jcanton found on
    // 2026-08-25: "it starts full width when loading the page, but grabbing any
    // of the column resize drag handles resizes it weirdly (I believe to laptop
    // screen width)". He was right about the cause as well as the symptom.
    //
    // `refit` applies `scaledWidths(room)` to the DOM — stored widths are a
    // decision about PROPORTION and are re-scaled to whatever window you are in,
    // which is why the table opens correctly on any screen. But it applies them
    // without writing them back, so `WIDTHS` still holds the pixel numbers from
    // the window they were dragged in. The old line read that stale number
    // because it was truthy, and the first `applyWidths()` of the drag snapped
    // every column back to the laptop it came from — the whole table jumping the
    // instant a handle was touched, before the pointer had moved at all.
    //
    // A drag is a decision about the layout in front of the person making it, so
    // it starts from what is on the screen. The stored numbers keep their job:
    // they are what `scaledWidths` re-proportions on the next load.
    headers.forEach(other => {
      if (other.offsetParent === null) return;   // a column this width has shed
      WIDTHS[keyOf(other)] = Math.round(other.getBoundingClientRect().width);
    });
    table.style.tableLayout = 'fixed';
    const key = keyOf(th);
    const from = event.clientX;
    const was = WIDTHS[key];
    const move = e => {
      WIDTHS[key] = Math.max(40, was + e.clientX - from);
      applyWidths();
    };
    const stop = () => {
      grip.classList.remove('dragging');
      setTimeout(() => { dragging = false; }, 0);   // after the click it caused
      remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
      automatic = false;
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
// One name for "make the table the width of the room it is in", so the load, the
// resize and the moment the real face lands cannot answer it differently.
function refit() {
  if (automatic) fitWidths();
  else applyWidths(scaledWidths(scroller.clientWidth - chromeOverhead()) || WIDTHS);
  stickyOffset();
}
refit();
// The typeface arrives as a `data:` URI with `font-display: swap`, so the layout
// this was just measured against may still be the fallback's metrics — and then
// a first load fits to widths a reload does not reproduce, which is exactly the
// "broken until I reloaded" it looked like. Measured once more when the real
// face is in, which is the moment the numbers stop moving.
if (document.fonts) document.fonts.ready.then(refit);
// The fit drops columns as the window narrows, and the sticky title column
// starts where the id column ends — both are facts about a layout that only
// exists once it has been laid out. An automatic fit is a fit to *this* window,
// so a new window gets a new one; a dragged width is a decision and is only
// re-applied.
// Which is also why a dragged layout keeps all fourteen columns however narrow
// the window gets: shedding exists because the fit would otherwise squeeze every
// column past reading, and a column somebody sized by hand is not being squeezed
// out of the table altogether.
//
// It is still fitted to the window, though — scaled, not replayed. Replaying the
// stored pixels left the table at the width of whatever window it was dragged
// in: a gap down the right of a widened page, and a table hanging off the edge
// of a narrowed one.
addEventListener('resize', refit);
// The rule down the right of the frozen title column says "what is to the left
// of this is being held still while the rest passes under it". At scrollLeft 0
// nothing is passing under anything and it reads as a stray separator between
// title and priority, which is the first thing anybody asked about it. Set here
// rather than only on the event, because a reload restores scrollLeft before any
// of this runs.
const frozenEdge = () => scroller.classList.toggle('scrolled', scroller.scrollLeft > 0);
scroller.addEventListener('scroll', frozenEdge);
frozenEdge();
</script>
"""


_TABLE_STYLE = (
    _SCROLL_STYLE
    + _TREE_STYLE
    + """
th[data-sort] { cursor: pointer; user-select: none; }
/* (0,1,1) over the shared block's bare `th` at (0,0,1): the sorted column keeps
   its emphasis whichever order the two blocks are inlined in. */
th.sorted { color: inherit; font-weight: 700; }
/* No `th { position: relative }` here any more: every th this page draws is a
   `thead th`, whose `position: sticky` — (0,0,2) in the shared block against
   the (0,0,1) that used to sit here — is itself a positioned value, so the
   grips and the `+` control anchor to the sticky box and the relative rule
   decided nothing. Gone rather than kept, because an inert rule beside a
   sticky one is exactly the bait the `.table-scroll [data-col]` episode
   below was taken by. */
/* The button is the header: it takes the cell's type so the column still reads
   as a label, and only the focus ring says it is a control. */
th button { font: inherit; color: inherit; letter-spacing: inherit;
            text-transform: inherit; background: none; border: 0; padding: 0;
            cursor: pointer; }
/* Reserved whether or not this is the sorted column, so sorting does not shove
   every header one glyph to the left. */
th .dir { display: inline-block; width: .8em; color: var(--accent); }
/* The two columns that say which row you are looking at. Scrolled right without
   them, fourteen columns of values belong to nobody. They need a ground of their
   own and a layer above the cells passing underneath.

   One bare attribute selector each, which is (0,1,0) — deliberately the lightest
   rule that can reach these cells, because these two lines state a *default*
   ground and a *default* layer that three rules below exist to correct. Each of
   those adds an element or a class, so each is (0,1,1) and each wins on weight
   alone, whichever order the stylesheet ends up in.

   These were briefly `.table-scroll [data-col=…]` — (0,2,0), written to outrank
   `dd, td.edit { position: relative }` in _SUGGEST_STYLE, which was stealing
   `position: sticky` from the title cell so that it kept the `left` meant for a
   sticky box and shifted 187px right over priority and status. It fixed that and
   silently outranked all three corrections: both frozen headers dropped to
   z-index 1 and were painted over by their own rows, the title header lost its
   bottom rule, and a problem on either column lost its ground. The suggestion
   popup is parked on the body now and that rule is gone, so the weight these
   need is the weight that loses to everything meant to correct them. */
[data-col="id"] { position: sticky; left: 0; z-index: 1; background: var(--surface); }
[data-col="title"] { position: sticky; left: var(--sticky-1, 0px); z-index: 1;
                     background: var(--surface); }
thead [data-col="id"], thead [data-col="title"] { z-index: 4; }
thead [data-col="title"] { box-shadow: inset 0 -1px 0 var(--line); }
/* The edge of the frozen pair, drawn only while there is something passing under
   it. Unconditionally it is a vertical rule between title and priority and
   nothing else — the table has no other column separators, so at scrollLeft 0 it
   reads as one column having been singled out for a border.
   Inset, and that is the whole of it: this shipped as `1px 0 0 var(--line)` and
   painted nothing at all, in either state, because Chrome does not paint an
   *outset* box-shadow on a cell in a `border-collapse: collapse` table. The
   comment two rules up already said so about the header's bottom rule and the
   right edge was written outset anyway, so the resting state was accidentally
   right and the scrolled state had no edge — half-clipped `+N` badges sitting
   hard against the title column, looking like a clipping bug.
   Two rules and not one: the header's own bottom rule is drawn inside its box
   too, so both shadows have to be named together or setting one drops the other.
   `.scrolled td[…]` is (0,2,1) and beats the bare (0,1,0) above it;
   `.scrolled thead th[…]` is (0,2,2) and beats that in turn, whatever order this
   file ends up in. */
.scrolled td[data-col="title"] { box-shadow: inset -1px 0 0 var(--line); }
.scrolled thead th[data-col="title"] {
  box-shadow: inset 0 -1px 0 var(--line), inset -1px 0 0 var(--line);
}
/* The tree.

   The indent is the cell's own padding, which is what puts it into
   `naturalWidths()` — a drawing that overlapped the title would be a column
   measured at a width the words do not fit in. 14px a level and three levels at
   most: `PARENT_KINDS` bounds the real depth at two, a task hanging off a
   project is one, and 42px is what the deepest possible plan costs the one
   column that is a sentence. `tr.dN > td[…]` is (0,2,2) and beats the `th, td`
   padding at (0,0,2) and the frozen column's (0,1,0), which is the whole of what
   it has to beat: nothing else on this page sets padding on a cell.

   The drawing itself is `_TREE_STYLE` in `styles.py`, shared with the cycle
   page's betting table, which grew the same tree for the same reason. What stays
   here is the pair of facts that are this table's: the indent, and what the
   absolute boxes are positioned against.

   Absolute, against the title cell's own `position: sticky`. That is a real
   dependency and it is worth writing down: sticky is a positioned value, so it
   is the containing block for these, and it is set by the rule fifteen lines up
   that freezes the column. If that ever stops being sticky the connectors are
   the second thing to go — they would hang off the scroll container and slide
   away from their rows — and this comment is the note that they go together.
   `top: 0; bottom: 0` in the shared block is the reason to do it this way at
   all: the vertical line is then exactly the height of the row it is in,
   whatever that row holds, which an inline box guessing at a line height cannot
   promise. */
tr.d1 > td[data-col="title"] { padding-left: calc(.5rem + 14px); }
tr.d2 > td[data-col="title"] { padding-left: calc(.5rem + 28px); }
tr.d3 > td[data-col="title"] { padding-left: calc(.5rem + 42px); }
/* A row that is not an answer to what was asked, kept because something under it
   is: the pitch over three tasks that matched, so that a filtered table is still
   a plan and not a list of orphans. It is a record like any other — its title
   opens it, its cells still edit, a drop still lands on it — so it is dimmed
   rather than disabled, and `summarise` does not count it.

   `tr.context > td` is (0,1,2), which beats the frozen columns' (0,1,0) and the
   severity grounds' (0,1,1): a dimmed row with a blocker on it loses the fill in
   its cell and keeps both of the other two channels that say so — the stripe,
   which is a border on the `<tr>` and nothing here touches, and the ⚠ in the
   cell, which is text. `table.moving tr.can-hold > td` is (0,2,3) and beats this
   in turn, which is the right way round: for the length of a drag the only thing
   worth knowing about a row is whether it would take the one in your hand.

   The dimming is ink and a ground rather than `opacity` on the row. Opacity
   below 1 makes a stacking context of whatever carries it, and what carries it
   here would be two sticky cells whose whole job is to be opaque while the rest
   of the table passes underneath them — a see-through frozen column is a worse
   defect than the one this is drawing. The chips take theirs on the inside,
   where there is nothing behind them to show through. */
tr.context > td { background: var(--surface-2); color: var(--muted); }
tr.context > td a { color: var(--muted); }
tr.context .chip, tr.context .meter { opacity: .6; }
tr.context .tree .rung::before, tr.context .tree .rung::after { background: var(--line); }
/* One weight heavier than the sticky rules above — an element and a class beats
   a bare attribute selector — so a problem in the id or the title column keeps
   its ground. It is the specificity that does it and not the order: written the
   other way up these would still win, and the comment that said "after the
   sticky rules" was describing a cascade nothing depends on. The `td` is not
   decoration either: the shell already says `.sev-cell-blocker` at (0,1,0) and
   the frozen columns' `background` above would tie it and win on order. */
td.sev-cell-blocker { background: var(--sev-blocker-soft); }
td.sev-cell-warn { background: var(--sev-warn-soft); }
/* Editable and derived cells looked identical, and the only thing that said
   otherwise was a 12px hint at the top of the page. */
td.edit { cursor: cell; }
td.edit:hover { background: var(--surface-2); box-shadow: inset 0 -1px 0 var(--line-strong); }
/* A cell a bulk edit will write. An inset ring and not a ground, for the reason
   the row wash in the shell is not a ground either: these cells already carry
   `td.sev-cell-blocker`, `td.inherited` and the rest, and a selection that
   erased them would hide the thing you are selecting *because of*.
   `inset` so it is drawn inside a collapsed table's borders — an outset shadow
   on a cell in a collapsed table is not a dimmer line, it is no line, which this
   table has already shipped once on its frozen edge.
   `--accent` because it is the same "you did this" colour as the focus ring and
   the chosen facet, and a selection is exactly that. */
td.picked { box-shadow: inset 0 0 0 2px var(--accent); }
/* The pointer's own hover shadow would replace the ring on the one cell you are
   about to open — the two are the same property. Both, so the cell under the
   pointer still says it is editable and still says it is selected. */
td.picked.edit:hover {
  box-shadow: inset 0 0 0 2px var(--accent), inset 0 -1px 0 var(--line-strong);
}
td.refused { background: var(--surface-2); }
/* A value this record did not name: its reviewers, taken from the work filed
   under it. A ground rather than an italic or a bracket, because the cell is a
   list of logins and every other channel in it is already spoken for — and the
   ground is the one that survives a clamped cell showing one name and a `+2`.
   `--st-ready-soft` and not a colour of its own: the five status tints are the
   palette this table already reads in, and this is a tint from it rather than a
   sixth thing to learn.

   `.roll-level` is the same declaration and not a second rule holding the same
   value, because it is the same sentence: a bet whose tasks fill it exactly is a
   cell whose number came from the work underneath, and jcanton settled it that
   way on 2026-08-27 — "the class already means this value came from the work
   under this record, which is what this is". Purple was the alternative and lost
   because purple is shaping's hue; a sixth ground meaning what a fifth already
   means is one visual language becoming two. */
td.inherited, .roll-level { background: var(--st-ready-soft); }
/* How the work under a record reads against the box its bet bought, as a ground
   under `_ROLLUP_GLYPH`'s mark. Two channels, because the fill is the one a
   dichromat loses and this cell is where "will this fit" is answered.

   THREE STATES AND NOT FOUR. `over` is drawn by `td.sev-cell-warn` above,
   because `_rollup_problems` fires on exactly the comparison this ground would
   be describing and `MARK_COLUMN` routes its warning to this column. A
   `.roll-over` rule would be a second copy of `--sev-warn-soft` whose only
   possible future is to disagree with the first — a cell painted warn with no
   sentence to act on, or worse, a green cell over a ⚠.

   `under` takes the ladder's own green rather than `--drop`, which is the other
   pale green in the palette: `--drop` means "the row in your hand would land
   here", a thing that is only ever true for the length of a drag, and a cell
   wearing it permanently teaches that colour a second meaning. The ladder is the
   palette this table already reads in — see `.inherited` above, which borrows
   from it one rung up and gives the argument in full.

   `unsized` is the panel tint and NOT a green, which is the whole reason the
   state exists: a pitch holding three sized tasks and four unsized ones occupies
   only the days of the three, and painting that green says a bet is known to fit
   when nobody has estimated half of it. Recessed says "no answer here", which is
   what it is.

   ONE CLASS EACH AND NO ELEMENT, so these are (0,1,0). Every severity ground is
   (0,1,1) and every one of them beats these on weight alone, whichever order
   this sheet ends up in — a blocker on the appetite of a record whose tasks
   happen to fit must not be painted green. `tr.context > td` at (0,1,2) takes
   them too, which is the same bargain the severity fills already make there: a
   row kept only for context keeps the mark and gives up the fill. */
.roll-under { background: var(--st-done-soft); }
.roll-unsized { background: var(--surface-2); }
/* The mark, in the page's own ink and upright inside a cell that is neither.
   `.derived` in the shell makes every computed cell muted and italic, which is
   right for the number — it is the scheduler's — and wrong for the one glyph
   that has to be legible at a glance in the state that most needs reading. An
   italic `=` at muted weight is the least readable thing this cell could carry.
   Upright also keeps the four marks the same width apart from each other, which
   is what makes a column of them scannable. */
.rollmark { margin-right: .3rem; color: var(--fg); font-style: normal; }
td.clamp { white-space: nowrap; overflow: hidden; }
/* A row, so that what gets cut is the value and never the badge. Laid out
   inline, the `+2` is simply the last thing on an overflowing line: a clamped
   column on its 112px floor cut a third off it, and one sixty-character login
   pushed it 368px past the edge of the cell. The badge is the whole promise the
   clamp makes — it says how many are hidden and it is the control that shows
   them — so it is the one part that cannot be the part that goes.
   Two declarations do the work: `min-width: 0` on the value, because a flex item
   refuses to shrink below its own content without it and we would be back where
   we started, and the ellipsis, so a value that was cut says so.
   `flex: none` on the badge and the glyph is belt and braces. A flex item's
   automatic minimum already keeps them whole — but only while their text has
   nowhere to wrap, and "this one never gives up width" is what they mean rather
   than something the next reader should have to re-derive. */
td.clamp .clamped { display: flex; align-items: baseline; }
td.clamp .clamped > .first { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
td.clamp .clamped > .more, td.clamp .clamped > .sev-mark { flex: none; }
td.clamp .rest { display: none; }
/* The border and the ground are the default's; what is written here is the size
   it has to be to stand inside a table cell, and the muted ink that keeps a
   count of hidden tags from outweighing the tags themselves. */
td.clamp .more { font-size: 11px; line-height: 1.2; margin-left: .3rem;
                padding: 0 .25rem; color: var(--muted); }
/* The sign, from the class that opens the cell rather than from the script that
   sets it: `+2` and `−2` are one count seen from either side, and drawn this way
   the glyph cannot end up disagreeing with the state it is describing. The badge
   used to be `display: none` while the cell was open, which is what made the
   reveal one-way — there was nothing left to click. */
td.clamp .more::before { content: "+"; }
td.clamp.open .more::before { content: "−"; }
td.clamp.open { white-space: normal; }
/* Opened, the cell is a paragraph again: every item on as many lines as it
   takes, which is what the reveal is for. A flex row here would lay the value
   and the rest of the list side by side and clip the pair. */
td.clamp.open .clamped { display: block; }
td.clamp.open .rest { display: inline; }
td .sev-mark { margin-left: .25rem; }
/* A point smaller than the row it sits in, because a monospace face at the same
   nominal size reads larger than the text beside it: wider glyphs, a taller
   x-height, and no two characters closer together than any other pair. At 13px
   the id was the loudest thing on a row where it is the least interesting — it
   is a token to cite, not a heading — and the mono face is already what marks it
   as one. 12px and not `.9em`: this column is what the frozen title column's
   `left` is measured from, and a relative size compounds if anything above it
   ever changes. */
/* 11px, a step below the 12 it was and two below the row's own 13. An id is a
   token to be copied and cited rather than read, and the column it is in is the
   frozen one every row starts with — jcanton, 2026-08-21: "I'd reduce the font
   size of the ids a little further". Monospace holds it legible at that size in
   a way the sans face would not. */
.eid { font-family: var(--font-mono); font-size: 11px; }
/* "Saved here, not on GitHub yet": a ring beside the id — drawn, not typed,
   for `.rowgrip`'s reason: a glyph outside the vendored latin subset is a tofu
   box on a machine without it, and a border follows the theme. Hollow and
   muted while the state is ordinary — the second or two a push takes — because
   a colour from the status ladder or the severity pair would say something is
   wrong when nothing is yet; filled in the blocker colour once the commit is
   parked on a branch, so the mark escalates in place and hollow-against-filled
   is a shape a colour-blind reader still has. Cascade: no rule in the shell or
   this sheet matches a bare span inside the id cell, so these two classes at
   (0,1,0) are the only declaration for every property here — verified with
   tests/cascade.py against the served page. The one resolution inside the pair
   is deliberate: `.stranded`'s colour ties `.unlanded, .stranded` at (0,1,0)
   and wins on ORDER, so it must stay below the shared rule. */
.unlanded, .stranded {
  display: inline-block; width: 7px; height: 7px; margin-left: .3rem;
  border: 1px solid var(--muted); border-radius: 50%; cursor: help;
}
.stranded { border-color: var(--sev-blocker); background: var(--sev-blocker); }
/* And the column keeps a floor the smaller face took away. It is as wide as its
   widest id and nothing more — that is the fit — so a font a step smaller made
   it 114px, and the draft row lives in this column: three mark buttons and a
   kind picker whose width comes from the longest word it can show. At 114 the
   picker came out 51px for a word needing 59 and read `Projec`. 122px is what
   the draft needs, and it is 8px nobody looking at a table of ids will notice. */
#rows th[data-col="id"], #rows td[data-col="id"] { min-width: 122px; }
td[data-col="cycle"], td[data-col="size"], td[data-col="start"], td[data-col="end"],
td[data-col="blocked_by"] { font-variant-numeric: tabular-nums; }
/* A cell with something still in the way. Only when there is: a column tinted on
   every row says nothing, and the whole value of this is that the tinted cells
   are the few worth looking at. The class is written by the same function that
   writes the number, so the tint cannot outlive the count it is about — which is
   what would happen if this were a CSS rule keyed on the text.
   `--waiting` and not `--sev-blocker-soft`: a record waiting on a colleague is
   not a record that is broken, and one tint for both teaches the reader that the
   plan is on fire whenever anybody is waiting. */
td[data-col="blocked_by"].waiting { background: var(--waiting); }
/* The column's `+`, in the header of every column that clamps. It is the badge
   in the cells below it wearing the same border and the same 11px, because it
   means the same thing one level up — `+4` in a cell is four you cannot see,
   `+` in the header is every one of them in the column.

   `th .expand` is (0,1,1) and beats `th button` at (0,0,2) whichever order this
   file ends up in, which is the point: that rule strips a header button of its
   border and its background on purpose, so that a sort control reads as a label,
   and this control has to read as a control.

   Absolute, so it sits at the right of the header rather than after a label
   whose width is a different number in each of the four columns — and clear of
   the grip, which owns the last 7px of the cell. The room it stands in is
   reserved below rather than taken from the label. */
/* The same little rectangle as `td.clamp .more`, and unlike that one it has to
   SAY so: `th button` two rules up strips every control in a header of its border
   and its ground at (0,0,2), which outranks the shell's `button`, so a `+` that
   declared nothing would be drawn as the bare sort control beside it. The corner
   still comes from the default — `th button` says nothing about one — which is
   what keeps this badge on the app's corner without another copy of the number.
   `th .expand` is (0,1,1) and wins on weight rather than on the order two
   stylesheets happen to be concatenated in. */
th .expand {
  position: absolute; top: 50%; right: 9px; transform: translateY(-50%);
  font-size: 11px; line-height: 1.2; padding: 0 .25rem;
  border: 1px solid var(--line-strong); background: none;
  color: var(--muted); cursor: pointer;
}
th .expand::before { content: "+"; }
th .expand.open::before { content: "−"; }
/* Reserved in the header's own box, because a positioned box is in no
   measurement of its own accord. This is the whole of what puts the control into
   `naturalWidths()`: without it a column whose widest cell is narrower than its
   own header — a plan of two-letter logins — is measured at the label's width,
   handed exactly that, and draws the `+` over the end of the word. On the demo
   corpus every one of the four is sized by a cell instead and nothing overlaps,
   which is precisely why this is not a thing to leave to being noticed.
   `CLAMP_FLOOR` is the other half: the width at which what is left of the header
   still holds the longest of the four labels on one line. */
th.expands { padding-right: 2rem; }
th .grip {
  position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize;
}
th .grip::before {
  content: ""; position: absolute; top: 20%; bottom: 20%; right: 3px; width: 1px;
  background: var(--line-strong);
}
th .grip:hover::before, th .grip.dragging::before { background: var(--accent); width: 2px; }
.measuring th, .measuring td { white-space: nowrap; }
/* THE COLUMNS THAT DO NOT WRAP. A title is a sentence and wraps; everything in
   this list is a token — an id, a login, a date, a number, a bar — and a token
   broken over two lines is a row twice as tall for no reading gained. jcanton,
   2026-08-21, on a laptop: "(id, owner, dates, progress) can we have the first
   columns without newlines".

   With the ellipsis that has to come with it: `overflow-wrap: anywhere` above is
   what let a login wrap inside its cell, and taking it away without this would
   let `iomaganaris` hang over the column beside it. A name cut short says it is
   cut short; the cell's tooltip and the card have the whole of it. */
#rows tbody td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                 overflow-wrap: normal; }
/* And the link inside the title cell, which is the one cell whose content is an
   element rather than text: an `<a>` is inline and an inline box does not
   ellipsise, so without this the title runs under the column beside it. */
#rows tbody td[data-col="title"] > a { display: block; overflow: hidden;
                                       text-overflow: ellipsis; }
/* EVERY cell, title included — jcanton, 2026-08-21: "I'd replace the newlines
   with ... and disappearing words (on all cells), titles included". A title is a
   sentence and used to wrap for that reason; the row it wraps in is three rows
   tall, and what a reader loses to the ellipsis is one hover away on the card
   and one click away on the record.

   The four clamped columns are exempt WHILE OPEN. Their header control opens
   every cell to show what the `+N` hides, and a cell that cannot wrap opens to
   exactly the height it had — which the control's own test measures as a column
   that cost no height at all. Closed they are one item and a badge, which is the
   same saving by a different route. */
#rows tbody td.clamp.open { white-space: normal; overflow-wrap: anywhere; }
/* And the two rows that hold CONTROLS rather than values are exempt whole: the
   draft row's kind picker is a `<select>` in a flex wrapper whose width comes
   from the longest word it can show, and a cell that clips shrank it to 51px for
   a word needing 59 — `Projec`. The adder row is the same kind of thing with a
   button in it. Neither has text to ellipsise. */
#rows tbody tr.draft > td, #rows tbody tr.adder > td {
  white-space: normal; overflow: visible; text-overflow: clip;
}
/* THE BOX A DATE CELL OPENS, WHICH IS A PICKER AND NOT A TEXT BOX — AND THE ONE
   EDITOR THAT DOES NOT FIT ITS CELL. A native date box wants 126px at this font,
   measured in a Start cell at `width: auto` and the same 126 whether it is empty
   or holding a date; both date columns measure 74 on the demo plan at 1400.
   There is no width that is both inside the cell and readable. Measured at
   1px widths in Chrome at 13px Inter, a box holding 15.09.2026 reads `15.` at
   44px, `15.09` at 58, `15.09.2` at 74 and the whole date with daylight before
   the indicator at 100 — and 58 is exactly the content box the End column leaves
   it, its 74px cell carrying `.5rem` of padding each side. Chrome spends what it
   has on the calendar indicator, the day and the month, so what a cell-sized box
   loses is the century and the year, which are the two fields somebody opens
   this to change.

   So the box keeps the width it asks for and the CELL gets out of its way. That
   is not a new idea here: `tr.draft > td` and `tr.adder > td` one rule up already
   turn the clip off so that a control can paint over its neighbour, because a
   control is not text and has nothing to ellipsise. What is new is that this one
   is turned off for the length of one edit, on the one cell holding the editor —
   `:has()` asks exactly that question, and the cell goes back to clipping the
   moment `draw()` replaces the box with a value again.

   The alternative — a `min-width` on the two date columns in the measuring pass,
   so that the column was never narrower than the control — was written and taken
   out again. It widened both columns for every reader whether or not anybody
   ever opened a date, and the fit spends that width by dropping a column: at
   1280 the badge test in `test_table.py` lost the clamped column it measures and
   failed saying there was none. The fit tests are the alarm, and this table is a
   laptop's.

   **What this costs instead, which is the honest price:** while the editor is
   open the box covers part of the column to its right, and nothing else. On the
   demo plan at 1400, Start's box runs 60px into End's 74, and End's runs 60px
   into `blocked_by`'s 87 — a whole neighbouring value, not a corner of one.
   Nothing is covered when no editor is open, and the table is the width it was.

   Both declarations are load-bearing and they answer different questions.
   Measured with `elementFromPoint` over the open box, on a row whose End cell
   draws `23.09.26` beside the Start editor:

   - as shipped, the point over the indicator answers the date INPUT;
   - with `position: static`, it answers the span drawing End's own date —
     `overflow: visible` alone
     lets the box out of the cell, but a non-positioned cell's content paints in
     the in-flow inline layer and the neighbouring cell's own text paints in that
     same layer afterwards, so the box goes UNDER the value beside it;
   - with `overflow: hidden`, it answers that same span, because the box is
     clipped at the cell's edge and clipped it is the right-hand end that goes,
     which is where the indicator is.

   `z-index` is deliberately NOT set. The frozen id and title columns are
   `position: sticky; z-index: 1`, so a cell at `position: relative; z-index:
   auto` still passes UNDER them: measured on a phone with `clearOfFrozen` taken
   out, the point at the open box's left edge answers the title column's link,
   not the box. That is the behaviour to keep — the frozen pair is opaque on
   purpose, and `clearOfFrozen` scrolls the cell out from under it rather than
   painting over it.

   `position: relative` here is also the rule the `dd, td.edit { position:
   relative }` episode warns about, and it is scoped so that it cannot repeat:
   `:has(> input[type="date"])` reaches only a cell holding a date box, and
   neither frozen column ever holds one — `id` is not editable and `title` is
   text. Nothing here can steal `position: sticky` from the title cell. */
#rows tbody td.edit:has(> input[type="date"]) { overflow: visible; position: relative; }
/* And the box is drawn at the row's own type rather than the browser's. It is
   also the font the 126px above was measured at: the UA default is a different
   metric and so a different intrinsic width. No `width` and no `box-sizing`,
   which is the whole point — `width: auto` IS the 126px the control asks for. */
#rows tbody td.edit > input[type="date"] { font: inherit; }
/* The bar fills the column it is alone in now, rather than trailing a number. */
#rows td[data-col="progress"] .meter { display: block; width: 100%; min-width: 2.5rem; }
/* And the century goes when the column is squeezed, which is the one part of a
   date a reader can supply. `fitWidths` sets the class from its own arithmetic,
   like the other two tight rules. */
table.tight-dates td[data-col="start"] .dateshort,
table.tight-dates td[data-col="end"] .dateshort { display: none; }
/* One screen is not one width. Below the width the columns need with every
   squeezable one already on its floor, the ones that are lookups rather than
   answers go, one at a time — they are all reachable on the detail page, and the
   filters above still see them.
   Which width that is is not written here. It was, as a media query at a typed
   1100px, and the floors it had to agree with put the real minimum at 1354px:
   every window between them scrolled sideways with all fourteen columns.
   `fitWidths` sets these classes from its own arithmetic now, so there is one
   number and the browser measures it. */
.shed-progress [data-col="progress"],
.shed-reviewers [data-col="reviewers"],
.shed-prs [data-col="prs"],
.shed-tags [data-col="tags"],
/* Last of the five, and the only one that changes what is FROZEN rather than
   what is drawn. `--sticky-1` is set from the first header's measured width, so
   a shed id measures zero, the title's `left` becomes 0, and the frozen column
   is the title alone — by construction rather than by a second rule that has to
   remember to agree. */
.shed-id [data-col="id"] { display: none; }

/* Where a row is picked up. Two dotted rules and not a `⠿`: that glyph is not in
   the vendored face's latin subset, so on a machine with no webfont it is a tofu
   box — the same argument the status marks settle the other way, because those
   five had to be text inside a 14px bar. Drawn, it follows the theme and cannot
   be the one character a reader's font does not have.
   `cursor: grab` is the only thing on the page that says a row can be picked up
   before somebody tries. */
.rowgrip {
  display: inline-block; width: 6px; height: 11px; margin-right: .4rem;
  vertical-align: -1px; cursor: grab;
  border-left: 2px dotted var(--line-strong); border-right: 2px dotted var(--line-strong);
}
.rowgrip:hover { border-left-color: var(--accent); border-right-color: var(--accent); }
/* While a move is in the air the table answers one question, and it answers it
   in the ground of every cell: this row would take it, this one would not.
   On the cells and not on the `<tr>`, because the two frozen columns paint a
   background of their own — a row-level colour is drawn underneath them and the
   id and the title would be the two cells that did not answer.
   `tr.can-hold > td` is (0,1,2) and beats `[data-col="id"]` at (0,1,0), the
   severity grounds at (0,1,1) and `td.edit:hover` at (0,1,1), whatever order
   this file ends up in. Beating the severity grounds is deliberate and it is
   worth saying so: for the length of one gesture the only thing worth knowing
   about a row is whether it can take the one in your hand, and the problem
   grounds come back the moment it is over. */
table.moving tr.can-hold > td { background: var(--surface-2); }
table.moving tr.no-hold > td { background: var(--surface); color: var(--muted); }
table.moving tr.no-hold > td a, table.moving tr.no-hold > td .chip { color: var(--muted); }
/* The row the drop would land in: the would-be parent, in green, and the only
   green on the page. Every other row a drop could legally land on is on the
   panel tint above, so the two questions a hand is asking — where may this go,
   and where is it going right now — are answered in two different channels
   rather than in two shades of one. A row that cannot be a parent is never
   given it: `dragover` returns before the class is added.
   Inset, and that is not a style choice: Chrome does not paint an *outset*
   box-shadow on a cell in a `border-collapse: collapse` table, which is how the
   frozen column's edge came to be a rule that resolved perfectly and drew
   nothing at all for a whole round. */
table.moving tr.over > td {
  background: var(--drop);
  box-shadow: inset 0 2px 0 var(--ok), inset 0 -2px 0 var(--ok);
}
/* What the drop would do, named, beside the cursor.
   No dialog: a modal on every drag is a toll on a gesture that is already
   deliberate, and a reparent is one field and one commit that dragging back
   undoes. `position: fixed` and parked on the body, because `.table-scroll`
   clips its contents and a label that scrolls out from under the pointer is
   worse than none. z-index 5 clears the whole table — the header is 3, its own
   frozen pair 4 — and `pointer-events: none` keeps it out of the way of the very
   `dragover` that positions it. One line, because it names a title and a title
   is a sentence: two-line labels move under the cursor as they rewrap. */
#into {
  position: fixed; z-index: 5; pointer-events: none;
  font-size: 12px; padding: .1rem .4rem; max-width: 22rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  border: 1px solid var(--ok); border-radius: 3px;
  background: var(--drop); color: var(--fg);
}
/* The last row: where a plan grows, and — while a move is in the air — where a
   row goes to belong to nothing.
   Sticky, so that on a plan of two hundred rows the way to add one more is not
   two hundred rows down. z-index 2 puts it over the cells passing under it
   (z-index 1, the frozen columns) and under the header (3, and 4 for its own
   frozen pair), which is the order they are in on screen. */
tr.adder > td {
  position: sticky; bottom: 0; z-index: 2;
  background: var(--surface); border-top: 1px solid var(--line);
  box-shadow: inset 0 1px 0 var(--line);
}
/* And stuck to the LEFT as well as to the bottom, because the row it belongs to
   spans every column: scrolled sideways, its one cell slid away with the rest of
   the table while the id and title columns stayed — so the way to add a row went
   off the side of a page whose first two columns had not moved. jcanton,
   2026-08-21: "the new row button should be fixed underneath the id column".

   The cell keeps its full width, so the row's ground still reaches across; only
   what is inside it is pinned. `left: .5rem` is the cell's own padding, which is
   what puts the button under the id column rather than under the table's edge. */
tr.adder > td > * { position: sticky; left: .5rem; }
/* Only what is this button's own. The rectangle, the border and the ink come
   from the default every control gets — a third copy of them here is how the
   page came to have three slightly different buttons on one screen. */
tr.adder button { font-size: 12px; padding: .1rem .5rem; margin-right: .5rem; }
tr.adder button.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
tr.adder .hint { font-size: 12px; color: var(--muted); }
/* The draft row's controls, in whichever of their two places they were drawn:
   the bar while there is no row, the row's id cell once there is one. The
   wrapper lays them out because a `<td>` that is a flex container stops being a
   table cell — the same reason the clamped columns have a `.clamped` inside
   them. Three rules, and each is a thing that went wrong on the page:

   Laid out at all. Without this the marks and the picker were inline boxes in
   the narrowest column on the table and the picker wrapped under them, so the
   draft stood twice the height of every other row — which is the thing
   `draftControls` says the marks are marks in order to avoid.

   `inline-flex` and not `flex`. In the bar this wrapper shares a line with the
   sentence saying nothing is written yet, and a block-level flex box took the
   whole width: the picker stretched to 1400px and the sentence went to a line
   of its own.

   `max-width` is what makes shrink-to-fit shrink. A `<select>` is as wide as
   its widest option, so in the id cell the wrapper sized itself to
   "choose a kind…" — a string only ever read in the bar — and stood 33px past
   the edge of a cell whose width the fit had already decided. */
.drafting { display: inline-flex; align-items: center; gap: .2rem;
            max-width: 100%; vertical-align: middle; margin-right: .5rem; }
/* And the picker is the part that gives, because `min-width` on a flex item is
   `auto`: without this the marks were pushed out of the cell instead. */
.drafting select { font: inherit; font-size: 12px; min-width: 0; flex: 1 1 auto; }
/* An icon-only control. Square and centred rather than padded like a word: the
   mark has no baseline to sit on, and `tr.adder button`'s `.1rem .5rem` is the
   room a word needs on either side of it. */
.draft-do {
  display: inline-flex; align-items: center; justify-content: center;
  flex: none; margin: 0; padding: .2rem;
  font-size: 12px; line-height: 0;
}
/* The one of the two that writes, in the ink this page gives that press
   everywhere else. `.draft-do.primary` is (0,2,0) and its hover (0,3,0), so the
   two do not have to be read in the order they happen to be written in. */
.draft-do.primary { border-color: var(--accent); color: var(--accent); }
.draft-do.primary:hover { background: var(--surface-2); }
/* **A control that will not act must not look like one that will.** The write
   these belong to is a commit and a push, 1.5 to 2 seconds from Cloud Run, and
   for that window all three of the row's controls are `disabled` — see
   `CREATING`. Drawn the way `button.mark:disabled` is drawn, because a second
   vocabulary for "this is not pressable" is a second thing to keep in step.

   Qualified by `.drafting`, and that is the whole reason this comment is long.
   The obvious `.draft-do:disabled` is (0,2,0) and loses the accent to
   `tr.adder button.primary` at (0,2,2) — a rule written for the `+ New row`
   button four lines up, which these marks inherit by standing in the same row.
   So the control that had just stopped taking presses went on being drawn in
   the ink this page uses for the press that writes. `.drafting` is the wrapper
   both places draw the controls into, which is what makes it the right anchor:
   these marks are in the adder row before a kind is chosen and in the draft
   row's id cell afterwards, and a `tr.adder` qualifier would have covered only
   the half where the check does not exist yet. `.drafting .draft-do:disabled`
   is (0,3,0) and beats (0,2,2) on class count; its `:hover` twin is (0,4,0) and
   beats `.draft-do.primary:hover` at (0,3,0), which would otherwise light the
   background under a cursor resting on a dead control. Resolved with
   `tests/cascade.py` against the served page, not counted by hand — the first
   draft of this rule lost both of those and changed nothing on screen. */
.drafting .draft-do:disabled, .drafting .draft-do:disabled:hover {
  cursor: default; background: var(--surface-2);
  border-color: var(--line); color: var(--muted); opacity: .45;
}
.drafting select:disabled { cursor: default; color: var(--muted); opacity: .45; }
/* The `+` and the way out swap places, because at any moment exactly one of them
   is a thing you can do. `:not([hidden])` because `table.moving #unparent` is
   (1,1,1) and the browser's own `[hidden] { display: none }` is (0,1,0): without
   it, the button that has nothing to take a row out of is shown anyway. */
tr.adder #unparent { display: none; }
table.moving tr.adder #add-row { display: none; }
table.moving tr.adder #unparent:not([hidden]) { display: inline-block; }
table.moving tr.adder > td { box-shadow: inset 0 2px 0 var(--accent); }
table.moving tr.adder.over > td { background: var(--surface-2); }
/* A row with a write in the air. Dimmed rather than spinning: the row is still
   readable, still says what it said a second ago, and the one thing that has
   changed is that it is not settled yet. `cursor: progress` on the whole row is
   the second channel, for a reader who has the animation turned off. */
tr.writing > td { opacity: .55; cursor: progress; }
/* The row being typed. It is a form laid out as a row, so an empty cell has to
   look like a box to fill in rather than like a value nobody has written: the
   column's own word, in the muted ink every hint on this page uses.
   `attr()` in `content` and not a text node, because the hint is furniture — a
   screen reader on the cell hears its column header and the editor's own
   `aria-label`, which is the name of the thing, said once. */
tr.draft > td { background: var(--surface-2); }
/* The controls in a draft row are the size of a row, not the size of a button in
   a bar. Only what is theirs: the rectangle and the ink come from the default
   every control gets, and this says how much room it may take inside a cell that
   has to stay the height of an ordinary one. */
/* Tighter than a control in a bar, in both directions, and it has to be. The row
   must stay the height of an ordinary row, and the picker sits in the id cell
   where a flex `min-width` squeezes it — so every pixel of padding is a pixel
   taken off the word, and the default's `.7rem` cut "Project" to "Projec". Only
   the size is theirs; the rectangle and the ink come from the default. */
tr.draft select { font-size: 11px; padding: .05rem 0; }
tr.draft .draft-do { font-size: 12px; padding: .05rem .3rem; }
/* While this cell holds the row's controls instead of an id it is a strip of
   controls and not a value, so it gives back the room either side of a value:
   at the column's own 8px the picker had 56px to say `Project` in and drew
   `Projec`, in the one cell whose whole job is to say what the row will be. */
tr.draft .draft-id { color: var(--muted); padding-left: .3rem; padding-right: .3rem; }
td.draft-cell:empty::after { content: attr(data-hint); color: var(--empty); }
/* A column this kind has not got, or one nothing may type into. Hatched rather
   than merely empty: every other cell in this row carries its column's word in
   the muted ink, so an empty one would read as a box nobody has filled in yet —
   and this is a box nobody can.
   Drawn at `--line-strong` and at full strength, which is not a taste: at
   `--line` under `opacity: .5` the stripes were, on the screen, nothing at all.
   A hatch nobody can see is an empty cell with a comment attached.
   `tr.draft > td.draft-none` is (0,2,2) because it has to beat the row's own
   ground at (0,2,0) two rules up — and that rule uses the `background`
   SHORTHAND, which resets `background-image` to none. Written as `td.draft-none`
   this resolved perfectly and painted nothing, which is this file's
   characteristic failure and was caught by looking at the pixels. What it now
   outranks is exactly that one rule: nothing else in this stylesheet reaches a
   cell of the draft row. */
tr.draft > td.draft-none {
  background-image: repeating-linear-gradient(-45deg, transparent, transparent 3px,
                    var(--line-strong) 3px, var(--line-strong) 4px);
}
/* The one question a status change may ask, over the row it is about. Fixed, so
   it is not clipped by the table's own scroller — the cell it belongs to can be
   in a frozen column with `overflow: hidden` two ancestors up — and z-index 6,
   which clears the header (3), the frozen pair (4) and the drop label (5). */
#askfor {
  position: fixed; z-index: 6; min-width: 14rem;
  display: flex; flex-direction: column; gap: .35rem;
  padding: .5rem .6rem; background: var(--surface); color: var(--fg);
  border: 1px solid var(--line-strong); border-radius: 3px;
  box-shadow: 0 4px 14px rgba(0,0,0,.12);
}
#askfor[hidden] { display: none; }
#askfor .asking { margin: 0; font-size: 12px; color: var(--muted); }
#askfor label { display: flex; flex-direction: column; gap: .15rem;
                font-size: 11px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .04em; }
#askfor input { font: inherit; font-size: 13px; text-transform: none;
                letter-spacing: 0; color: var(--fg); padding: .15rem .3rem;
                border: 1px solid var(--line-strong); border-radius: 3px; }
#askfor .acts { display: flex; gap: .4rem; margin-top: .15rem; }
#askfor button { font: inherit; font-size: 12px; padding: .15rem .6rem;
                 border: 1px solid var(--line-strong); border-radius: 3px;
                 background: none; color: inherit; cursor: pointer; }
#askfor button.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
/* The create refusal, beside the row it refused. `#row-conflict` is styled in
   the shell and this is the same kind of news, but a create has no row to sit
   next to — so it lands in the bar, where the button that caused it is. */
#draft-problems { margin: .25rem 0 0; padding-left: 1.1rem; color: var(--sev-blocker);
                  font-size: 12px; }
"""
)


def _new_row_fields() -> dict[str, dict[str, str]]:
    """Per kind, which stored field each column of a new row writes to.

    The table's own answer to the question `_new_rows` answers for the create
    form — what a person may type into a record that does not exist yet — and it
    is asked of the same two places rather than written down a third time:
    `EDITABLE` says which fields a person owns at all, and `model_fields` says
    which of them this kind has. A project has no `person_weeks`, so it gets no
    box under Appetite.

    A column missing from a kind's map is a column that kind cannot be typed into
    — which is three different sentences and all of them true: `id` is the
    server's, Blockers is counted rather than written, and Appetite is a thing a
    project does not have. The row draws each of them differently and says which
    it is.

    `size`, `start` and `end` are the columns that are not simply their own
    field, which is why the value in a stored row's cell is never what an editor
    opens on (`_COLUMN_SHOWS`) — and a row that does not exist yet has nothing
    standing in any of the three, so there is nothing here to commit by accident.
    Typing 3 into Appetite writes `person_weeks: 3`, and the cell goes back to
    being the scheduler's the moment the row is a record.
    """
    per_kind: dict[str, dict[str, str]] = {}
    # Planned rungs only: the table is a plan view, and its draft row offers
    # `Object.keys` of this map as the kinds a new row can be. An issue typed
    # into the table would be created and then never appear on it — a control
    # whose result is a vanishing row. /new?kind=issue is that door.
    for kind, model in ((r.name, r.model) for r in KIND_LADDER if r.planned):
        fields = {}
        for column, _ in _TABLE_COLUMNS:
            field = _COLUMN_FIELD.get(column, column)
            if (
                field in EDITABLE
                and field in model.model_fields
                and field not in unread_fields(kind)
            ):
                fields[column] = field
        per_kind[kind] = fields
    return per_kind


def render_table(
    index: Index,
    links: Links = STATIC,
    base_commit: str | None = None,
    may_write: bool = False,
) -> str:
    payload = _payload(index)
    body = _compiled(_TABLE).render(
        payload=payload,
        # "There is a server behind this page AND this person may write" — the
        # first half alone shipped, standing in for the second, so a signed-out
        # visitor got role="grid", the combobox, the draft row's `+`, and a 403
        # for pressing Enter on what all of that offered. `design/QUEUE.md`
        # predicted this flag would have to split rather than narrow, because
        # "the reader still needs to sort, filter, search and follow links" —
        # measured against the template, that is not so: sorting (the `<thead>`
        # buttons and `draw()`), `_FILTER_JS`, the hover card and the row links
        # in `rowHtml` all live OUTSIDE the `{% if not editable %}` branch, and
        # everything inside it is the write machinery (`refreshProblems` and
        # `refreshRows` are reached only from save paths). The rendered-file
        # export has exercised the read-only half since it existed; serving it
        # to a reader is the same page.
        editable=base_commit is not None and may_write,
        base_commit=base_commit or "",
        links=links,
        columns=_columns_for(index),
        # The drawings the draft row's two controls are made of. Sent as values
        # and read by the script, rather than written out as two `<svg>` strings
        # in a template literal: this is the same argument the icon picker makes
        # against rebuilding its own art in JavaScript, one drawing per mark and
        # in the language the rest of this file's drawings are written in.
        marks=DRAFT_MARKS,
        why=_TABLE_WHY,
        rollup_glyph=_ROLLUP_GLYPH,
        fields=_COLUMN_FIELD,
        mark_column=_MARK_COLUMN,
        shows=_TABLE_SHOWS,
        dates=_TABLE_DATES,
        # The sentence about this view, in the slot the graph and the timeline
        # already put theirs in — jcanton, 2026-08-25, asking for the table to be
        # "consistent with the timeline and graph pages". It moved out of the row
        # above with the New record button it was written beside.
        #
        # Only where the gestures exist. On a rendered file there is no server to
        # save to and no editor to double-click into, so the sentence would
        # promise two things the page cannot do — the same rule the button it
        # sat next to was already held to, and the reason both were inside an
        # `{% if editable %}` rather than in the markup unconditionally.
        facets=_facets_html(
            index.facets,
            aside=_TABLE_HINT if base_commit is not None and may_write else _NO_ASIDE,
            titles=_titles(index),
            # `state=True`: this is the one plan view with no commit bar, so the
            # live region a save writes its receipt into belongs here.
            summary=_summary_html(index, len(payload["rows"]), state=True),
        ),
        filters=_FILTER_JS,
        combobox=_combobox_html(index, live=base_commit is not None),
    )
    return _page(
        "openproj — table",
        body,
        _TABLE_STYLE + _SUGGEST_STYLE,
        links,
        "table",
        index.unreadable,
    )
