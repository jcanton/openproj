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

**`vanillajs-datepicker` 1.3.4** — MIT, zero runtime dependencies, 35 KB of minified JS and, in the
plain build this app would have taken, 5,938 B of CSS (4,938 B minified) in 60 declaration blocks
over 71 selectors, shipped as a prebuilt file that can be vendored, checksummed and inlined under
the no-npm rule. Those two CSS figures were "4.9 KB of CSS in 63 rules" and "63 rules and 38
hardcoded hex values" below until they were measured again: 38 hex literals is
`dist/css/datepicker.css`'s neighbour `datepicker-bs5.css`, one of four themed variants the package
also ships, and nothing in the package has 63 of anything. Neither number changed the decision, and
that is the reason a wrong one survives — `static/VENDOR.md` records where 38 came from, and how to
take the count again, because a re-vendoring checks against it. Its `beforeShowDay(date) → {classes, content}` hook is precisely the thing this
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
| what can we hang a redraw on              | `changeView`, `changeMonth`, `changeYear`, `changeDate`            |

`refresh` was in that last row until the bundle was counted rather than read off the probe's notes.
The library dispatches six events and that is not one of them — `show`, `hide`, `changeView`,
`changeYear`, `changeMonth`, `changeDate`. `refresh` is a render *method*, and a listener for it is a
line that never runs, which is worse than no line because it reads as cover.

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
builds_until, closes, alt}`, sorted, unclamped, in dates. The timeline's loop reads it and keeps its
own `x()`; the picker serialises it into the page as a template variable. An invariant written twice
is guarded once, and this one is currently written once by luck rather than by design.

`alt` — which of the two tints a cycle wears — is on that list because the branch put it in both
drawings first and got it wrong in both. It is the RANK in the sorted list, and the sort is why it
belongs here: "which cycle comes next" is a question about the order, and neither a band loop nor a
day cell is where the order is decided.

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
which is the entire question a reader asks of two touching bands — and therefore *adjacent* is the
word that has to be implemented, not *odd*.

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
the cycle page, the cycles listing and the timeline. Not `shell.py`: that file is 4238 lines
and ships on all twelve pages including `/help` and `/people`, neither of which has a date field
anywhere on it. `pop.py` made this same argument for the same reason and it holds here.

The cycle JSON reaches the page as a template variable. Never a substitution — `render.py` and
`web.py` are parsed as syntax to keep `.replace(` out of them, and this is the rule that test exists
for.

Re-tokening the library's stylesheet is 60 declaration blocks and 26 hardcoded colour literals — 20
hex, 14 of them distinct, and six `rgba()` — and the result has to
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


## What it actually cost

Written when the branch closed, against `git log origin/main..cycle-calendar`. A design record whose
predictions are never checked is a design record nobody trusts twice, so this section is the
scorecard and not a summary.

**All three predicted costs were real, and two of them were bigger than the prediction.**

**The ARIA layer.** Real, and the number held: zero `aria-*` and zero `role` in the whole bundle.
What the plan got wrong was the failure mode. It assumed the library rebuilds its cells, so a layer
applied once would be *lost* on a month change — and the test it named asked whether `role` was
still there after pressing Next. The library REUSES its forty-two cells: `renderCell` rewrites
`className`, `textContent` and `dataset.date` on the same `<span>`, so an attribute set at
construction survives the redraw and becomes last month's name on this month's day. `role` therefore
comes back `grid` with the whole wiring deleted, and the predicted test would have passed against a
widget that had never re-run any of it. The assertions that do the work are the three that can only
be right if the layer ran again: a first cell announcing "Monday, 27 July 2026, cycle 36" over
September's grid, a cell no longer selected still reporting `aria-selected="true"`, and a live
region saying August under a header saying September.

**A value set from outside.** Real, and it is two defects rather than one — the channel was empty in
*both* directions. Nothing reached the widget, as predicted. Nothing reached the page either:
`refreshUI` assigns `inputField.value`, a value assigned by script fires no event, and the only
thing the library dispatches is its own `changeDate`, which nothing outside the widget listens for.
Counted with a form listening, a day picked in the popup moved the box to 2026-08-21 and the form
heard nothing at all — on a record page that marks itself dirty from `input` and `change` and a
table that commits a cell from `change`. The plan also named the wrong listener: Reset dispatches
one `input` on the FORM and not on the box, so a handler asking whether `event.target` was a date
box would never have run in the one flow it was written for.

And a third one underneath it, which nothing foresaw: `update()` forces `viewDate: undefined`, so
the library falls back to `defaultViewDate` — today. A native date box reports `value === ''` the
instant any segment is cleared, so one Backspace in the year threw the reader out of the month they
were reading. Measured through CDP with real key events: a popup open on 2026-08-17 followed a typed
2027 correctly and then said "September 2026" on the next keystroke.

**The badge in the cell's name.** Real, and the fix is not the one the plan wrote. `beforeShowDay`'s
`content` takes a fragment, a string of HTML *or* anything with `forEach`, and the plan assumed the
string. A string there would have been the one place in this widget where markup is built from data
— a third escaping boundary in a language that has two — so the badge is a `createElement` plus
`textContent`, and the day number goes back in as a text node because `content` replaces the cell's
whole contents.

### What the plan did not foresee

**The node harness cannot open this picker, and was about to lie about four other tests.** The
bundle's first statements run outside any function: `document.createRange()` and a destructuring of
`EventTarget.prototype`. Neither name exists in `drive.js`'s `vm` context, so the library threw on
line 25, `window.Datepicker` was never defined, and every driven page with a date field came back
with one extra entry in `errors` — which four tests in `tests/test_editor.py` assert is empty. Its
`matchMedia` stub answers `{matches: false}` as well, so `FINE.matches` is false and the widget
stays inert under node even once it loads. Every driven calendar test is Chrome's, through
`tests/browser.py`, and the shim was repaired for the tests that were already there rather than for
these.

**Nothing resolved the re-tokened stylesheet, and it had a cascade bug in it from the first
commit.** `:not()` forwards its argument's weight, so `.datepicker-cell.next:not(.disabled)` is
(0,3,0) and outranked every rule in the `.selected` block that can reach a spill-over cell. A
selected day shown as next month's took `var(--accent)` for its ground and `var(--muted)` for its
ink: 1.36:1 light and 1.12:1 dark, against 7.6:1 for the `--on-accent` it was meant to have, on the
one cell the popup exists to point at. `tests/cascade.py` takes a raw string and needs no rendered
page, so there was never a reason not to ask it; eleven cases now pin every resolution the sheet's
comments state. The census over the real pages had a hole of its own — it skipped any surface with
no `input[type="date"]` in its markup, which is the table, whose boxes `openEditor` builds.

**`--band-alt` had to move, and in the opposite direction from the one the plan assumed.**
`.cycle-cooldown` is `--line` at half alpha over whichever band it lies in, and `--line` sits
between the page and `--band` in every theme, so the tint that was *nearer* the page walked into the
cool-down: dL* 0.56 light and 0.80 dark, under the just-noticeable difference, which is half the
cycles on the chart with no visible cool-down and nothing saying so. It stands further off the page
now, in all four blocks including the base16 derivation. Three separations are wanted — a cycle
against its neighbour, a cool-down against its own band, and a cool-down against the next band — and
a search over every tint of this ink that keeps the 10px cycle number at 4.5:1 buys two of them.

**The guard hunt was three times the size of the one function the plan named.** `Index.build_end`
was the predicted copy. `Config._resolve` and `_proposed` were two more of the same arithmetic, and
`_resolve` is reached from `with_plans`, which `load_repo` calls *outside* every `readable()`
wrapper — so `cooldown_weeks: .inf` in `config/defaults.yaml` 500ed every route and killed `openproj
check` with a traceback, which is worse than the failure the plan set out to fix. `_working_days` in
the scheduler rounds before it bounds and survives only on the `, 6` second argument to `round`, an
argument that is there for a floating-point artefact and is the first thing a tidy-up deletes. And
hoisting the Config into a `cached_property` bought its own defect: `model_copy` copies the instance
`__dict__`, which is exactly where a `cached_property` puts its answer, so a copy carried a Config
built from the field the copy had just replaced.

**And the hunt did not finish, which is the part a scorecard is for.** Two more unbounded floats out
of a plan file reach a rounding that raises, both measured through the file the way the ones above
were. `availability: .inf` in a cycle record renders as `(row.rate * 100)|round|int` in `_CYCLE`'s
roster row and answers `OverflowError` on `/cycle/<n>`. `person_weeks: .nan` on one task reaches
`round(100 * counted.fraction)` (`detail.py`) and answers `ValueError` on its PARENT's record page
and on the static `detail.html`, which is every record at once; the deck spells that expression a
third time and the corpus does not reach it. They are their own branch — jcanton, 2026-09-23 — with a
sweep in both languages and a validation rule in `_problems_for` beside them, and the reason they are
written here is that this branch's own commits read like a finished sweep and are not one.

**Both drawings alternated on the wrong fact, and the words were right the whole time.** The
timeline wrote `"alt" if number % 2 else "main"` and the calendar's `dayInCycle` wrote
`found.number % 2`, so each of them tested the parity of a cycle's NUMBER while the commit subject,
this section and the comment beside the line all said ADJACENCY. The two agree only while the numbers
run consecutively, which both corpora here do, so nothing on any page and nothing in the suite ever
put them side by side: a `config/cycles.yaml` holding 34, 36, 38, 40 with contiguous windows drew
four bands in ONE uniform fill — the exact defect the tint was added to remove — and one cancelled or
renumbered cycle is the whole distance to it. The test could not see it either. It asserted that the
SET of tints drawn was `{"", "alt"}`, which any plan with one odd-numbered cycle anywhere satisfies,
including that one. It asserts the property now: over the bands the page draws, in x order, two that
MEET never share a tint, with the meeting asserted first so that alternation is never claimed across
a gap.

**The phone harness was making the claim it was written to test.** `measured_on_a_phone` set the
viewport and nothing else: a page under it reported `innerWidth` 390 with `(pointer: fine)` true,
`(hover: hover)` true and `maxTouchPoints` 0. Touch emulation went into the helper rather than into
the one test, because a phone that reports a mouse is wrong for every caller.

**The chips needed two options nobody would have guessed.** Not `autohide`, because a chip — unlike
the day cell it stands for — is a focusable control *inside* the popup, so closing on the press left
`document.activeElement` on a `display: none` button. And `forceRefresh`, because the library skips
the re-render when the new date equals the selection, so the chip for the cycle already chosen,
pressed from three months away, moved nothing at all.

### One crossing the sweep found and did not close

`grep -rn 'type="date"' src/openproj/` answers the wrong question, which is the point of reading
each hit: three of the places a date box appears are built at runtime and appear in no markup. Two
of them are the table's, which carries the widget. The third is `popControlOf` (`pop.py`), and
`graph.py` calls `_pop_js(links, index if editable else None)` — so an editable graph page can build
an `input[type="date"]` for `start_date` or `end_date` in the `#pop` card, with no calendar on the
page to catch it. It degrades to the native picker rather than breaking, and the trade is real in
both directions: 60 KB on a page whose date box only appears inside a popup nobody may open. Left
for jcanton, because it is a decision about weight and not a defect to be swept up in a close-out —
and named here rather than in a comment so that the next sweep starts from it.

🤖 Written by an agent on behalf of @jcanton
