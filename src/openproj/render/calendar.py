"""The calendar a date field opens, and the cycles drawn inside it.

**The native popup is browser chrome.** An `<input type="date">` opens a calendar
no stylesheet in this repository can reach — not a day cell, not a weekend, not
anything. So a cycle band inside one is a widget or it is nothing.

**The input stays; only the popup is replaced.** The table's whole date path is
built on native semantics: a half-typed date reads `value === ''`, which `coerce`
maps to null, so a blur with `validity.badInput` is refused rather than silently
clearing somebody's field. A text box has none of that, and re-deriving it by
hand is how a date gets wiped without a word. So the element is untouched,
`::-webkit-calendar-picker-indicator` is hidden, and `input.value` stays the only
channel between this widget and the rest of the app.

**A coarse pointer keeps the native picker.** The OS wheel beats a hand-rolled
grid under a thumb, and this is the first `pointer: coarse` rule here — the phone
claim is asked through `measured_on_a_phone`, which overrides the viewport rather
than the window, because Chrome will not open a window below 500px and 500px is
above this app's one narrow breakpoint.

**Here and not in `shell.py`.** That file is four thousand lines and ships on all
twelve pages, two of which — `/help` and `/people` — have no date field anywhere
on them. `pop.py` made the same argument for the same reason.

The library is `vanillajs-datepicker`, vendored; `design/cycle-calendar.md` has
the audit, the probe and the three costs it was taken with. The short version of
the costs, because each has a test whose reason is not obvious otherwise: the
bundle carries no ARIA at all, a value set from outside does not reach it, and
content injected into a day lands in that day's accessible name.
"""

from __future__ import annotations

from markupsafe import Markup

from ..index import Index
from ..vendor import _library, _notice
from .env import _fragment

# The stylesheet, re-tokened. Upstream's is 60 rules carrying 26 hardcoded colour
# literals, which is 26 values that would be right in one theme and wrong in the
# other three. Only the rules this app actually shows are kept — the package
# styles four framework variants and a range picker, none of which is drawn here.
#
# A plain `str` and not `Markup`, because a page concatenates its sheets —
# `_DETAIL_STYLE + _SUGGEST_STYLE + _CALENDAR_STYLE` — and `str + Markup` takes
# markupsafe's reflected `__radd__`, which would escape every `>` and `&` in the
# sheets in front of it. Every other style constant here is a `str` for the same
# reason, whether or not its author knew it.
_CALENDAR_STYLE = """
.datepicker { width: min-content; }
.datepicker:not(.active) { display: none; }
.datepicker-dropdown { padding-top: 4px; position: absolute; z-index: 40; }
.datepicker-picker {
  background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
  box-shadow: 0 6px 18px rgb(0 0 0 / .18); display: flex; flex-direction: column;
  color: var(--fg); font: inherit;
}
.datepicker-header .datepicker-controls { padding: 4px; }
.datepicker-controls { display: flex; }
.datepicker-controls .button {
  background: var(--surface-2); border: 1px solid var(--line); border-radius: 4px;
  color: var(--fg); cursor: pointer; font: inherit; padding: 2px 8px;
}
.datepicker-controls .button:focus-visible { outline: 2px solid var(--focus); }
.datepicker-grid { display: flex; flex-wrap: wrap; width: 15.5rem; }
.datepicker-cell {
  align-items: center; border-radius: 3px; cursor: pointer; display: flex;
  height: 2rem; justify-content: center; position: relative; width: 14.2857%;
}

/* The ink on a cell is a ladder of three rungs, every one of them (0,2,0) and
   resolved by source order alone: a day spilled over from the neighbouring
   month is muted, a day outside the allowed range is fainter still, and the
   selected day — last block in this sheet — takes the accent's ink to sit on
   the accent's fill.

   The muting used to be `.next:not(.disabled)`, which is (0,3,0), and that is
   the bug this ladder replaces. `:not()` forwards its argument's weight, so
   those two selectors outranked every rule in the `.selected` block below;
   the library's `renderCell` adds `selected` to a spill-over cell as readily
   as to an in-month one, so the day the popup was opened to show rendered
   `var(--muted)` on `var(--accent)` — 1.36:1 in the light theme, 1.12:1 in
   dark, against 7.6:1 for the `--on-accent` it was meant to have. The number
   was there and effectively not drawn. Reachable by opening the picker on any
   record dated mid-month and pressing Next.

   Order now does what the `:not()` did — `.disabled` follows and beats it for
   a spill-over day that is also out of range — and the weakening is the point
   rather than a side effect: a rule that wins only on order can lose ground
   to a rule below it and can never take ground from one, so what this now
   beats is a subset of what it beat before, and the `.selected` block is
   below it. */
.datepicker-cell.next, .datepicker-cell.prev { color: var(--muted); }
.datepicker-cell.disabled { color: var(--empty); }
.datepicker-cell:not(.day) { width: 25%; }

/* A cycle, drawn the way the timeline draws one: the band under the days it runs
   for, the dimmer fill under its cool-down, and an edge on the two days that are
   facts rather than tints. Adjacent cycles alternate two tints of one ink — hue
   is the channel a dichromat loses.

   All four fills are (0,2,0) or (0,3,0) and they are written in the order they
   must resolve in, so say how: `.cyc-alt` follows `.cyc` and beats it on order
   for an odd-numbered cycle; `.cyc-cool` follows both and beats them for a
   cool-down day; and `.cyc-alt.cyc-cool` is (0,3,0) and beats all three, which
   is what keeps an odd cycle's cool-down on the odd cycle's tint instead of
   collapsing every cool-down in the month to one colour. */
.datepicker-cell.cyc { background: var(--band); }
.datepicker-cell.cyc-alt { background: var(--band-alt); }
/* The timeline paints its cool-down as `--line` at 50% OVER the band, so the
   colour a reader has learnt is the mix and not `--line`. A cell has one
   background and nothing to layer over, so the mix is computed rather than
   stacked — the same colour by the other route. */
.datepicker-cell.cyc-cool { background: color-mix(in oklab, var(--line) 50%, var(--band)); }
.datepicker-cell.cyc-alt.cyc-cool {
  background: color-mix(in oklab, var(--line) 50%, var(--band-alt));
}
/* Inset, and on a flex div rather than a cell of a `border-collapse: collapse`
   table — which is where this repository's unpainted `box-shadow` was, resolving
   to exactly the asserted value and drawn as nothing at all. */
.datepicker-cell.cyc-opens { box-shadow: inset 2px 0 0 var(--band-edge); }
.datepicker-cell.cyc-closes { box-shadow: inset -2px 0 0 var(--band-edge); }

/* The library's roving cursor. An outline and not a background, because a
   background here is (0,3,0) and would silently beat all four band rules: the
   band would vanish from whichever day the keyboard is on, which is the one day
   the reader is asking about. */
.datepicker-cell.focused:not(.selected) { outline: 2px solid var(--focus); outline-offset: -2px; }

/* Last, and it has to be: the selected day is the answer to the question the
   popup was opened to ask, so it takes the ground from whatever is under it.

   Three of the four band fills are (0,2,0), and order alone would beat those —
   a bare `.datepicker-cell.selected` here wins them because it is written
   after. The fourth is `.cyc-alt.cyc-cool` at (0,3,0), which order cannot
   reach, so the combinations are spelled out to meet it at (0,3,0) and take
   the tie on order. Without them the one day that broke was an odd cycle's
   cool-down day: it kept the band as its ground and took `--on-accent` as its
   ink — white on pale blue in the light theme.

   The list is the ground and not the ink. A cell's colour is settled by the
   three-rung ladder at the top of this sheet, which is why `.next` and `.prev`
   are absent here and need no entry: they lost their `:not()` weight so that
   `.datepicker-cell.selected` outranks them on order, the way it outranks
   `.cyc`. Anything the library adds to a cell in future is the same case — it
   earns a line here only if it sets a background at (0,3,0). */
.datepicker-cell.selected,
.datepicker-cell.selected.cyc,
.datepicker-cell.selected.cyc-alt,
.datepicker-cell.selected.cyc-cool {
  background: var(--accent); color: var(--on-accent);
}

/* The cycle's number, on its first build day only. Small, and after the day
   number: a badge injected in front of it read "3 3" to a screen reader, so it
   is `aria-hidden` and the day comes first. */
.datepicker-cell .cyc-n {
  color: var(--muted); font-size: 9px; font-weight: 600; line-height: 1;
  position: absolute; right: 2px; top: 2px;
}
/* On the accent ground the muted ink is the one thing on the cell that does not
   follow the fill, so it goes with it. */
.datepicker-cell.selected .cyc-n { color: var(--on-accent); }

/* The fastest path to the date somebody actually wants. A row of real controls
   with real names, not hints. */
.cyc-chips { border-top: 1px solid var(--line); display: flex; flex-wrap: wrap;
  gap: 4px; max-width: 15.5rem; padding: 6px; }
.cyc-chips button {
  background: var(--surface-2); border: 1px solid var(--line); border-radius: 999px;
  color: var(--fg); cursor: pointer; font: inherit; font-size: 11px; padding: 1px 8px;
}
.cyc-chips button:focus-visible { outline: 2px solid var(--focus); }

/* The native indicator is hidden only where our popup actually opens. Under a
   coarse pointer it stays, and so does the OS wheel behind it. */
@media (pointer: fine) {
  input[type="date"]::-webkit-calendar-picker-indicator { display: none; }
}
"""

# The glue: what turns a date box into this widget, and what the widget says to a
# reader who is not looking at it.
#
# `Markup` and not a plain `str`, because it is rendered into `_CALENDAR_JS`
# through `{{ glue }}`: an autoescaped template hands a `str` back with every `<`
# and `&` spelled out, and a script whose `&&` has become `&amp;&amp;` is a
# script that throws on its first line.
_GLUE = Markup("""
// Every picker this page has made, keyed by the box it belongs to. Weak, so that
// the table — which replaces its whole tbody on every `draw()` — drops the
// pickers belonging to the rows it threw away, without this file having to know
// that the table does that.
const CALENDARS = new WeakMap();

// The picker hands `beforeShowDay` a LOCAL-midnight Date. `toISOString()` on one
// of those prints the day BEFORE anywhere east of Greenwich, so every cell is
// judged as its own predecessor and every edge lands a day late: measured at
// UTC+2, a cycle opening on the 17th drew its edge and its number on the 18th.
// One cell out for every reader in Europe, exactly right for every reader in
// London, and no reader can tell which of the two they are. So the date is read
// in local parts — the same three numbers the picker used to build the cell.
function isoOf(day) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

// A day, spelled out for a reader who is not looking at it. The one place an ISO
// string becomes a sentence here, because the cells and the chips are naming the
// same fact and two formatters is two shapes for it.
//
// `${iso}T00:00` and not `new Date(iso)`: a bare ISO date is parsed as UTC, so
// west of Greenwich it spells the day before. That is `isoOf`'s defect arriving
// by the other door — one cell out for a whole hemisphere, exactly right for
// London, and no reader can tell which of the two they are.
//
// `undefined` as the locale, which is the reader's own: a date is one of the few
// things every locale writes differently and the app has no better answer than
// the machine's. The library's own furniture — the header, Today, Clear — is its
// `en` table and stays English; that difference is the library's and not ours.
function spelled(iso) {
  return new Date(`${iso}T00:00`).toLocaleDateString(undefined,
    { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

// What `beforeShowDay` gives back per day: the band classes, the edges, and the
// cycle's number on the day it opens.
//
// **Nodes and not a string.** `content` may be a fragment, a string of HTML or
// anything with `forEach` — the library appends the last as it stands. A string
// would make this the one place in the widget where markup is built from data,
// which is a third escaping boundary in a language that has two here (`esc` and
// `textContent`); six injection sites existed at once because six places each
// decided for themselves. Nothing here is typed by a person today, and that is
// an argument for the cheap boundary rather than against it.
//
// **Day number first, badge second, badge `aria-hidden`.** `content` replaces the
// cell's WHOLE contents — `textContent` was set to the day number a line earlier
// and is thrown away — so the day has to be back in it or the calendar draws a
// month of cycle numbers. With the badge in front, day 3 of cycle 3 read "3 3".
function dayInCycle(day) {
  const iso = isoOf(day);
  const found = cycleOf(iso);
  if (!found) return null;
  const classes = ['cyc'];
  if (found.number % 2) classes.push('cyc-alt');
  if (found.phase === 'cool') classes.push('cyc-cool');
  if (iso === found.window.opens) classes.push('cyc-opens');
  if (iso === found.window.closes) classes.push('cyc-closes');
  if (iso !== found.window.opens) return { classes: classes.join(' ') };
  const badge = document.createElement('span');
  badge.className = 'cyc-n';
  badge.setAttribute('aria-hidden', 'true');
  badge.textContent = String(found.number);
  return {
    classes: classes.join(' '),
    content: [document.createTextNode(String(day.getDate())), badge],
  };
}

// The semantics the library does not have. Counted rather than assumed: zero
// `aria-*` attributes and zero `role`s in the whole 35 KB. The grid is a div, the
// selected day announces nothing, and a month change is silent.
//
// **Re-applied on every redraw, and the reason is not the one it looks like.**
// The library reuses its forty-two cells — `renderCell` rewrites `className`,
// `textContent` and `dataset.date` on the same `<span>` — so an attribute set
// here SURVIVES a month change. That is worse than losing it: `role` and
// `aria-selected` and the name are then last month's, on this month's day, and a
// reader is told the 14th of August while looking at the 14th of September. A
// test that asked only whether `role` was still there after Next would pass
// against a widget that had never re-run this at all.
function describeGrid(picker) {
  const root = picker.picker.element;
  const grid = root.querySelector('.datepicker-grid');
  if (!grid) return;
  grid.setAttribute('role', 'grid');
  for (const cell of grid.querySelectorAll('.datepicker-cell')) {
    cell.setAttribute('role', 'gridcell');
    // `dataset.date` is the cell's own timestamp and the library sets it on the
    // day view alone; the month and year views have none, and a name read off
    // their text is the right name there.
    const iso = cell.dataset.date ? isoOf(new Date(Number(cell.dataset.date))) : null;
    const found = iso ? cycleOf(iso) : null;
    // Written rather than left to the cell's contents: the contents are a day
    // number and a badge, and the badge is hidden precisely so it is not read —
    // which leaves "14" as the whole of what the cell would otherwise announce.
    const said = iso ? spelled(iso) : cell.textContent;
    cell.setAttribute('aria-label', found
      ? `${said}, cycle ${found.number}${found.phase === 'cool' ? ' cool-down' : ''}`
      : said);
    cell.setAttribute('aria-selected', cell.classList.contains('selected') ? 'true' : 'false');
  }
  // The popup's own region, and not the page's `announce()`. That one writes into
  // `#state` where a page has one, which is the save bar — so a month change
  // would blank "Saved" on the record page, in the one place a reader looks to
  // find out whether their edit landed.
  let live = root.querySelector('[aria-live="polite"]');
  if (!live) {
    live = document.createElement('p');
    live.setAttribute('aria-live', 'polite');
    // `sr-only` is the shell's own name for this and its rule is already on every
    // page that will carry this widget. A second name for it would be a class
    // nothing defines, which is not an invisible region — it is the month drawn
    // twice, once in the header and once underneath it.
    live.className = 'sr-only';
    root.appendChild(live);
  }
  const title = root.querySelector('.datepicker-controls .view-switch');
  if (title) live.textContent = title.textContent;
}

function calendarFor(box) {
  let picker = CALENDARS.get(box);
  if (picker) return picker;
  picker = new Datepicker(box, {
    // The native value format, because `input.value` stays the only channel
    // between this widget and the rest of the app: a picker writing `25/12/2026`
    // into a date box writes nothing at all, since the element refuses it.
    format: 'yyyy-mm-dd',
    weekStart: 1,
    autohide: true,
    beforeShowDay: dayInCycle,
  });
  CALENDARS.set(box, picker);
  // The six events this library has, counted out of the bundle rather than taken
  // from a list: `show`, `hide`, `changeView`, `changeYear`, `changeMonth`,
  // `changeDate`. There is no `refresh` — a listener for one would be a line that
  // never runs, which is worse than no line because it reads as cover. `hide` is
  // left out on its own merits: nothing needs describing on the way down.
  //
  // They are dispatched on the INPUT and not on the picker, and — measured, by
  // reading the grid from inside the handler — AFTER the render they describe,
  // so this sees the days it is naming. A layer applied once at construction is
  // a layer that is gone the first time anybody presses Next.
  for (const when of ['show', 'changeView', 'changeYear', 'changeMonth', 'changeDate']) {
    box.addEventListener(when, () => describeGrid(picker));
  }
  // **The widget writes the box and the page hears nothing.** Measured, by
  // counting what a `<form>` saw when a day was clicked: the box went to
  // 2026-08-21 and the form heard nothing at all. `refreshUI` ASSIGNS
  // `inputField.value`, and a value assigned by script fires no event — the same
  // fact `resetEdits` in `detail.py` is written around — while the only thing
  // the library does dispatch is its own `changeDate`, which nothing outside
  // this file listens for. The record page marks itself dirty from `input` and
  // `change` on the form and the table commits a cell from `change`, so a day
  // picked in this popup was an edit the save bar did not know about and a cell
  // that never committed: the value on screen, and nothing holding it.
  //
  // Both events and in that order, because that is what a native date field
  // fires when a person picks a date, and every page here was written against a
  // native date field. This is not a loop: `syncCalendar` answers the `change`
  // with `update()`, which compares before it renders and re-dispatches
  // `changeDate` only when the dates actually differ — measured at a recursion
  // depth of one.
  box.addEventListener('changeDate', () => {
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.dispatchEvent(new Event('change', { bubbles: true }));
  });
  return picker;
}

function openCalendar(box) {
  const picker = calendarFor(box);
  picker.show();
  // `show` fires only when the picker was hidden, and this is also the path a
  // second open takes on a picker that is already up. Cheap and idempotent.
  describeGrid(picker);
  return picker;
}

// **A value set from outside does not reach the widget.** Measured:
// `box.value = '2026-12-25'` and a dispatched `change` left `getDate()` on the
// old date and the grid on the old month — a calendar disagreeing with the box
// it belongs to, silently.
//
// `update()` and not `setDate(box.value)`, because it is the library's own "read
// the input field again": an empty box — which is what a cleared field and a
// half-typed date both read as — clears the selection instead of being parsed as
// a date, and a value that already agrees costs a comparison and no render.
// `autohide` is forced off because it defaults to `config.autohide`, which is
// true here, and a popup that shut itself on a Reset would be the widget
// answering a question nobody asked.
function syncCalendar(box) {
  const picker = CALENDARS.get(box);
  if (picker) picker.update({ autohide: false });
}

// **The event arrives on the FORM and not on the box, and that is measured too.**
// The record page's Reset assigns every control and then dispatches ONE `input`
// on the form — `resetEdits` in `detail.py`, whose own comment says why: a value
// assigned by script fires nothing. So a listener that asked whether
// `event.target` was a date box would never run in the one flow this exists for,
// the flow whose entire job is undoing a mistake. The target is therefore asked
// for the date boxes UNDER it as well as for itself, which costs an empty
// `querySelectorAll` on a keystroke in a text field and finds every box a Reset
// just rewrote.
function syncCalendarsIn(target) {
  if (!target || !target.matches) return;
  if (target.matches('input[type="date"]')) syncCalendar(target);
  else for (const box of target.querySelectorAll('input[type="date"]')) syncCalendar(box);
}

// Both events, because the two writers use two. Reset dispatches `input`; a
// `change` is what the boxes themselves announce, including the one this file
// dispatches when the picker writes the value.
for (const when of ['change', 'input']) {
  document.addEventListener(when, (event) => syncCalendarsIn(event.target));
}

// The native indicator is hidden under a fine pointer and left alone under a
// coarse one, so this asks the stylesheet's own question. A phone keeps the OS
// wheel, which beats any grid this size under a thumb.
const FINE = window.matchMedia('(pointer: fine)');

// One delegated listener and not a hook per host. Three of the places a date box
// appears are built at runtime — the table's cells, its draft row and the `#pop`
// form's third face — and none of them exists when this script first runs, so a
// per-host hook is three places for one to be forgotten and a fourth host to
// arrive with none.
document.addEventListener('focusin', (event) => {
  const box = event.target;
  if (box.matches && box.matches('input[type="date"]') && FINE.matches) openCalendar(box);
});

// The keyboard's own way in, which is what a combobox uses and what this needs
// for the reader who tabs to the field rather than clicking it: focus alone
// opens the popup, and Alt+Down opens it again after an Escape closed it.
document.addEventListener('keydown', (event) => {
  const box = event.target;
  if (event.altKey && event.key === 'ArrowDown' && box.matches
      && box.matches('input[type="date"]') && FINE.matches) {
    event.preventDefault();
    openCalendar(box);
  }
});
""")

_CALENDAR_JS = """
<script>{{ library }}</script>
<script>
const CYCLE_WINDOWS = {{ windows|tojson }};

// Which cycle a day belongs to, and which half of it. Linear over a list that is
// one entry per cycle a plan has ever had — the corpus this was written against
// holds forty-odd, and a binary search over forty is a thing to get wrong rather
// than a thing to gain.
function cycleOf(iso) {
  for (const w of CYCLE_WINDOWS) {
    if (iso >= w.opens && iso <= w.closes) {
      return { number: w.n, phase: iso > w.builds ? 'cool' : 'build', window: w };
    }
  }
  return null;
}
{{ glue }}
</script>
"""


def _calendar_js(index: Index) -> Markup:
    """The library, the plan's cycles and the glue, for a page's template slot.

    The cycles are a template *variable*. A page assembled by substituting into
    finished markup is how a record titled `BARS_JSON` re-inlined a data block
    and how an owner of `x onmouseover=alert(1) y` put a live handler on every
    bar link on the timeline — using no character any escaper touches.

    Always the whole block, including for a plan that has dated no cycle: the
    array is then `[]` and the reader gets a plain calendar. Empty must not look
    like broken, and a field whose popup is missing on some plans and present on
    others is a field nobody can learn.
    """
    windows = [
        {
            "n": window.number,
            "opens": window.opens.isoformat(),
            "builds": window.builds_until.isoformat(),
            "closes": window.closes.isoformat(),
        }
        for window in index.cycle_windows()
    ]
    return _fragment(
        _CALENDAR_JS,
        # MIT asks for the notice in every copy, the minified bundle carries zero
        # occurrences of `Copyright` and zero of `MIT` — upstream's minifier
        # strips the block — and this file is inlined into every page that has a
        # date field. Same reading, same shape and the same helper as Ace's
        # stripped BSD notice and Inter's OFL one: every rendered page is a copy,
        # a static export mailed to somebody is a redistribution, and a notice
        # that lives only in the repository does not travel with either.
        library=Markup(_notice("datepicker-LICENSE.txt", "vanillajs-datepicker 1.3.4, MIT."))
        + _library("datepicker.min.js"),
        # `|tojson` is `_script_json`, which is this app's one JSON boundary: it
        # spells out `<`, `>` and `&`, so nothing here can end the block it sits
        # in. No cycle window holds one of those characters today, which is
        # exactly the argument against writing a second, narrower boundary for
        # this one payload.
        windows=windows,
        glue=_GLUE,
    )
