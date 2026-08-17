# Round two — what the audits found

Three adversarial audits ran against the branch after the 29 findings landed. All
29 are closed; these are the defects the work itself introduced, plus the
accessibility failures that predate it and the residuals it left behind.

Same rule as before: a fix is done when the behaviour is gone, with a test that
would catch it coming back.

---

## A. Regressions this branch created

**REG-1 — BLOCKER. The shared meter `.bar` silently destroys the whole Gantt.**
`_SHELL` defines `.bar { display: inline-block; width: 140px; height: 8px }` so the
capacity meter could be reused. Every timeline bar is a `<rect class="bar ...">`.
`width` and `height` are CSS *geometry* properties on `<rect>` in SVG2, and any
author rule beats a presentation attribute — so every bar on the timeline draws
140x8 regardless of its dates, with a correctly-sized hatch overlay on top of the
wrong rectangle. `_TIMELINE_STYLE` only sets `rect.bar { rx: 3 }` and never restores
the geometry. Before this branch `.bar` lived in `_CYCLE_STYLE` and the timeline
never loaded it. Fix: scope the meter to `span.bar` (every meter site is a span) or
rename the timeline rect's class. **Then look at the rendered timeline and confirm
the bars have their real widths back.** Add a test that pins a bar's width
attribute against the span the scheduler computed — no test saw this.

**REG-2 — F6 is closed on two of five write paths.** `openproj:writing` /
`openproj:wrote` are dispatched by the table's `saveCell` and by the cycle page.
They are not dispatched by the detail-page PATCH, the graph dependency save, the
create POST, or the asset upload. The asset upload is the visible one: `/api/asset`
calls `announce(store.head(), [])`, so pasting an image into an open editor pops
"The plan changed." over your own paste and nothing ever hides it again. Also set
`window.SHOWING` on the detail page — the shell already reads it, only nothing sets
it. The test that claims coverage runs against the table and its one detail-page
assertion passes on the shell's *reader*, so strengthen it too.

**REG-3 — The cycle page's unsaved count and its receipt count different things.**
`mark()` counts fields; `flush()` counts writes. Edit two fields on one row and it
says "2 unsaved changes" then "Saved 1 change". F5 is about a save you can believe,
and that number is the whole claim. Make both count the same unit.

**REG-4 — The blocking count and the filter it links to count different
populations.** The count sums *problems*; `?predicate=has_blocker` matches
*entities*. "3 blocking problems" opens a table of 2 rows — the exact way a count
stops being trusted. Either count entities, or word it "3 blocking problems on 2
entities" and keep the link honest.

**REG-5 — "Start a cycle" takes its defaults from any number an entity mentions.**
`top = max(_cycle_numbers(index))` unions plans, config windows *and* every
`entity.cycle`. One entity bet into an unrecorded cycle makes the form propose the
wrong number starting today, discarding the real last cycle's end date — and the
new index page actively encourages betting into an unrecorded cycle, so this is the
normal case. Derive the proposal from `set(index.plans) | set(index.cycles)` and
leave entity-referenced numbers to the listing.

**REG-6 — Stored text is interpolated into table cells unescaped**, beside new
timeline code that escapes it. Same data, two levels of care. Escape it, and add a
test with a title containing `<`, `&` and a quote.

---

## B. Accessibility failures

Ranked by the audit. Numbers 6, 7 and 8 are fixed by PALETTE_V2.md — apply that
first and they are done.

1. **No form control has an accessible name.** Not on the detail page, not on the
   create page, not on the cycle setup form. A `<dt>`/`<dd>` pair is not a label.
   Give every control a real `<label for>` or an `aria-label`.
2. **The suggestion widget implements none of the combobox ARIA contract** —
   `role="combobox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant`,
   `role="listbox"`/`option` on the popup. It is silent to a screen reader. The
   keyboard handling already exists; only the announcements are missing.
3. **The table's cells are dblclick-only**, so the app's primary editing surface
   has no keyboard path at all. Make a focused cell editable with Enter or F2, and
   make cells focusable in the first place.
4. **The rendered output contains zero live regions.** Every `role="status"` is
   behind `{% if editable %}`, and the static export's `#state` and the SSE
   `#moved` banner are bare. A save that only announces itself visually does not
   announce itself.
5. **`role="img"` on the timeline `<svg>` prunes all 17 bar links** out of the
   accessibility tree. Drop the role, or give the bars a parallel accessible
   representation.
6. `--line-strong` was 1.81:1 and is the sole boundary of every drawn input, button
   and popup — see PALETTE_V2.md.
7. The five status fills were not lightness-separated (1.02–1.11:1 between any
   two) and collapsed under deuteranopia on exactly the two surfaces where fill is
   the only channel — see PALETTE_V2.md, including its redundant-channel section.
8. `--empty` fails AA as text — see PALETTE_V2.md.
9. **The timeline's cycle band is invisible** (1.07:1 light, 1.16:1 dark) and its
   legend key draws the cycle boundary in a different token from the plot. One
   token, visible in both themes.
10. **Four of six pages have no heading, no `<main>` and no skip link.** Give every
    page an `<h1>`, a `<main>`, and the shell a skip link.
11. **The static export renders a "New entity" link to nowhere** and a hint
    promising an editor it does not have. The static pages are a read-only export;
    they must not offer controls that cannot work.

---

## C. Residuals and duplication

- **Graph empty state** is one hardcoded string. Give it the same three states the
  table has (no match / empty plan / failed to load).
- **The graph's action bar is still above the canvas** — F15 moved Create, Edit and
  Save the setup below their forms; the graph is the fourth page and was missed.
- **The table's column header words are a hardcoded literal list**, not read from
  the central label map F11 asked everything to go through. Same words, two sources
  of truth. Related: `const keys = [...]` in the table JS duplicates the Jinja loop
  that emits the headers, with a comment admitting the two must be edited together —
  emit `keys` from the loop. And `const WHY` hard-codes the same four names as
  `_TABLE_DERIVED`, so a fifth derived column would silently lose its class and its
  refusal message.
- **`_CONTROL` still renders raw identifiers as `<option>` text** for status and
  priority on the detail and create forms — the last of F11.
- **Two dead payload keys** (`facets`, `predicates`) are inlined into every table
  page and read by nothing; two test assertions now protect the dead weight. Drop
  all four.
- **`size_label` and its neighbours in `_detail_rows`** reach no template and no
  test. Delete what `_fact_rows` superseded.
- **`preview_html` builds a second MarkdownIt** that neither strips the repeated
  title nor enables tables, so Preview disagrees with the saved page about both.
  Reuse `_MD`.
- **Four copies of `#summary`, three of `#state`**, already drifting, and `#shown`
  re-implements the shell's `.num`. Move them into `_SHELL`.
- **Two facet-bar implementations** — `_FACETS` and the people page's hand-written
  `#controls`. Give `_FACETS` a field-list parameter and render people through it.
- **A second capacity formula** in `_cycle_view` restating `Cycle.capacity()`.
- **Two unnamed magic numbers**: `calc(100vh - 13rem)` and a third copy of `_ROW_PX`
  as a CSS literal.
- **`static/VENDOR.md` never mentions the font**, and its stated update procedure
  (`shasum -a 256 *.js > SHA256SUMS`) would delete the woff2's checksum. Fix the
  table, fix the procedure, and put the OFL notice where the pages that embed the
  face can be traced to it.
- **`render.py` imports model's private `_status_problems` at import time.** Make it
  public or stop reaching for it.
- **The cycle page sets `class="table-scroll"` on the bets table** while that page's
  stylesheet does not include the rule. Inert class — wire it or drop it.
- One comment describes a cascade that specificity makes irrelevant.
