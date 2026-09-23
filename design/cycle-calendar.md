# The calendar knows about cycles

jcanton, 2026-09-22: *"in the calendar date selectors, can we have cycles start and end dates
somehow highlighted? possibly with a small font number of the cycle?"* — and, in the same breath,
the timeline: *"currently they have the same colour and a dashed line to indicate where they
terminate. could be nice to have slightly different colours, different alpha for cycle vs cooldown,
hover over a cycle on the top of the timeline lightly colours the background."*

Both halves are the same fact drawn twice — where a cycle opens, where it stops building, where it
closes — so they are one branch.

## The constraint that decides the shape

Every date field in this app is a native `<input type="date">`: the record's fields through
`_control_html` (`controls.py`), the table's cells and drafts, the cycle page's setup, the timeline's
window, and the `#pop` form's date boxes. **The calendar a native date input opens is browser chrome.
Page CSS and page script cannot reach a day cell in it.** No stylesheet anywhere in this repository
can paint a band behind the 3rd of September. That is why this is a new widget and not a rule.

**The input stays. Only the popup is replaced.** This is the whole design in one line, and it is not
a preference — the table's date path is built on native semantics that a text box does not have. A
half-typed date reads `value === ''`, which `coerce` maps to null, so a blur with
`validity.badInput` is *refused* rather than silently clearing somebody's field. Swap the element
for a text input and every one of those behaviours has to be re-derived by hand, in the one place
where getting it wrong wipes a date without saying so. So `::-webkit-calendar-picker-indicator` is
hidden, our popup opens on focus, click and `Alt+↓`, and `input.value` remains the only channel
between the widget and the rest of the app.

**A coarse pointer keeps the native picker.** `@media (pointer: coarse)` leaves the indicator alone
and never opens ours. The OS wheel beats a hand-rolled grid under a thumb, and this is the first
`pointer: coarse` rule in the codebase — phone claims go through `measured_on_a_phone`.

## The library audit

Required by `AGENTS.md`, and it came out *yes*, which is the rarer answer here.

**`vanillajs-datepicker` 1.3.4** — MIT, zero runtime dependencies, 35 KB of minified JS and 4.9 KB
of CSS in 63 rules, shipped as a prebuilt file that can be vendored, checksummed and inlined under
the no-npm rule. Its `beforeShowDay(date) → {classes, content}` hook is precisely the thing this
feature needs and precisely the thing that is otherwise impossible.

What was bought is not the grid. It is the *keyboard* — arrows, month navigation, Enter to commit,
focus that survives a redraw — which is the class of gesture this repository has hand-rolled and got
wrong before. `cytoscape-compound-drag-and-drop` is the scar: refiling by drag was written here,
shipped, and removed the same day, and the 14 KB that had already solved it existed the whole time.

**Measured in headless Chrome on 2026-09-23, not assumed.** The probe built a real
`<input type="date">`, attached the library with `format: 'yyyy-mm-dd'`, and asked:

| question                                  | answer                                                             |
| ----------------------------------------- | ------------------------------------------------------------------ |
| does it construct on `type="date"`        | yes; `type` and `readOnly` both untouched                          |
| what does a click write                   | `value="2026-09-03"`, `valueAsDate` agrees, `badInput` false       |
| do `beforeShowDay` classes apply          | 14 banded cells and 5 cool-down cells in one month                 |
| is `content` injected verbatim            | yes — `<span class="n">3</span>1`                                  |
| does the keyboard work                    | arrows move the focused cell; Enter committed `2026-09-11`         |
| what can we hang a redraw on              | `changeView`, `changeMonth`, `changeYear`, `changeDate`, `refresh` |

**Three costs, found by the same probe and all of them ours to pay:**

**It has no accessibility semantics at all.** Not one `aria-*` attribute and not one `role` in the
whole bundle; `.datepicker-grid` is a div. So the roles, the selected state and the announcement of
a month change are a layer we add and re-apply on `changeView`, `changeMonth` and `changeYear`,
because the library rebuilds those cells. This is survivable *only* because the native input stays:
a reader who types the date never opens this popup, so the grid is an enhancement over a path that
already works and is already named. If the input had been replaced, this alone would have been the
reason to refuse the library.

**A value set from outside does not reach it.** `input.value = '2026-12-25'` followed by a `change`
event left `getDate()` on the previous date. Two paths in this app set a date field from outside:
Reset restoring from `BASELINE` (which must restore the base, never `defaultValue`), and the table's
`draw()` replacing its whole tbody. Both must call `setDate`. It is three lines and it is exactly the
kind of coupling that stops matching in silence.

**The injected badge lands in the cell's text.** With the number injected first, day 3 read `"33"` —
a screen reader announces "3 3". So the day number comes first and the badge carries `aria-hidden`.

One thing that looked like a defect and was the probe's own: `getDate()` returns a local-midnight
`Date`, so `toISOString()` prints the day before at UTC+2. Nothing that compares its result may go
through `toISOString`.

## One shared fact about cycles

`build_end` (`model.py`) already resolves where building stops, and the timeline's band loop is its
only caller — it turns `index.cycles` plus the cool-down into the three dates and then immediately
into pixels. The picker needs the same three dates and none of the pixels.

So it becomes one helper, `cycle_windows` on `Index`, returning per cycle `{number, opens,
builds_until, closes}`, sorted, unclamped, in dates. The timeline's loop reads it and keeps its own
`x()`; the picker serialises it into the page as a template variable. An invariant written twice is
guarded once, and this one is currently written once by luck rather than by design.

A plan that has dated no cycle returns `[]`, and every consumer below degrades to a plain calendar
rather than to an exception. That is the same rule as everywhere else here: empty must not look like
broken.

## What the grid draws

Days inside a cycle sit on the band token the timeline already uses; cool-down days take the dimmer
fill, so the two halves of a cycle are told apart by the channel that already tells them apart on
the chart. The cycle number rides the first day of build only — small, `aria-hidden`, after the day
number.

**Adjacent cycles alternate two tints of one ink, and do not take hues.** Fifteen cycles in fifteen
colours re-introduces exactly the failure the status ladder was built to avoid: hue is the channel a
dichromat loses. Alternating tints separate the cycle you are looking at from the one beside it,
which is the entire question a reader asks of two touching bands.

Band is not the only channel either. The first build day and the closing day each carry a hairline
edge, so a boundary survives a monochrome screen and survives a band that is one tint away from its
neighbour.

**A row of "jump to cycle N" chips sits under the grid.** It is the fastest path to the date
somebody actually wants — the day a cycle opens — and it is a real control with a real name rather
than a hint.

## Where it attaches

**One delegated listener on `document`, matching `input[type="date"]`.** Three of the places a date
box appears build it at runtime — the table's cells, the table's draft row, and the `#pop` form's
third face — and none of them exists when a page's script first runs. Per-host wiring would be three
hooks that each have to remember to call it, which is three places for one to be forgotten.

**A new module, `render/calendar.py`,** carrying the vendored library, the stylesheet, the glue and
the JSON, imported by the pages that have a date field: the record page, the create form, the table,
the cycle page and the timeline. Not `shell.py`: that file is 4238 lines
and ships on all twelve pages including `/help` and `/people`, neither of which has a date field
anywhere on it. `pop.py` made this same argument for the same reason and it holds here.

The cycle JSON reaches the page as a template variable. Never a substitution — `render.py` and
`web.py` are parsed as syntax to keep `.replace(` out of them, and this is the rule that test exists
for.

Re-tokening the library's stylesheet is 63 rules and 38 hardcoded hex values, and the result has to
be defined in all three colour blocks — bare `:root`, `:root[data-theme="dark"]`, and the media
query guarded by `:root:not([data-theme="light"])`. A value right in one block and wrong in another
is wrong for most of the people who will ever see it, because most readers never touch the toggle.

## The timeline, on the same branch

- Adjacent cycle bands alternate the two tints, so two cycles running up against each other read as
  two things and not one long one.
- The cool-down keeps its own alpha, re-checked against the band once the tints alternate: the fills
  are layered and a value chosen against the old flat band is a value chosen against something else.
- Hovering a cycle's label band lightly tints the full chart height for that cycle's columns. It is
  pointer-only, so it gates nothing — the dashed rule and the labels remain the record of where a
  cycle ends, exactly as they are now.

## The timeline's own date fields get chips and no bands

`tl-from` and `tl-to` pick a *window to look at*, not a date work happens on. A band behind the days
of cycle 3 answers a question nobody is asking of that control. The chip row stays, because "show me
cycle 3" is the most common thing anybody wants that window to be.

## How this gets tested

- Element trees out of a real DOM, never substrings — five escaping bugs shipped under substring
  assertions, and the stylesheet is inlined into every page, so `pages.tags` is the tool.
- The grid's keyboard driven in node through `drive.js`, which is the only place the runtime-built
  cells exist at all. The shim is a realm: nothing from the outer realm gets handed in.
- Pixels in headless Chrome — that the band is *painted*, that the hover tint appears, and that the
  popup is not clipped by the table cell it opens inside. A resolved value is a promise about pixels
  that a stylesheet cannot keep alone, and this repository has an unpainted `box-shadow` on its
  record to prove it.
- Both dark-mode blocks asserted, not only the toggled one.
- The phone claim — that a coarse pointer gets the OS wheel and never our popup — through
  `measured_on_a_phone`.
- Each of them checked by deleting the fix and watching the test fail.

The three integration costs above each get their own test, because each is a thing that works on the
day it is written and stops working silently: the ARIA layer surviving a month change, `setDate`
being called when Reset restores a baseline, and the badge staying out of the cell's accessible
name.

🤖 Written by an agent on behalf of @jcanton
