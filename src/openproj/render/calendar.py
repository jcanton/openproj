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

# Nothing yet, and deliberately: attaching the widget to a date box is the next
# commit on this branch, and the module is landed first so the cycles, the
# stylesheet and the tokens can be asked of a page before anything depends on
# them. An empty fragment renders as nothing rather than as a hole.
_GLUE = Markup("")

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
