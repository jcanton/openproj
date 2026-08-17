# Round three — what two independent audits found at HEAD

The suite is green and ruff is clean, and none of these are caught by either. They
were found by rendering a hostile corpus into a real DOM and by resolving the
served stylesheet through a cascade engine. Line numbers are from HEAD at the time
of the audit; confirm before editing.

---

## A. Injection. Plan data reaching markup unescaped.

Every one of these is the same defect wearing five hats: a value a member can type
is interpolated into HTML by string concatenation. The policy is not "escape these
five" — it is **one escaping boundary per language**, applied at the seam:

- **Python** builds markup only through `markupsafe.Markup(...).format(...)` or
  through Jinja with autoescape on. A bare f-string that produces a tag, rendered
  through `|safe`, is the bug.
- **JavaScript** builds markup only through the `esc` helper the table already
  carries, or through `textContent` / `replaceChildren`.

Fix the seam, then sweep for every other site that crosses it.

**A1 — BLOCKER. `_links()` puts a title straight into an anchor.**
`render.py:4075-4080` interpolates `index.entities[i].title` raw, and every
consumer renders it with `|safe` — `{{ e.parent_link|safe }}` (the meta line) and
`{{ row.display|safe }}` (the Parent, Blocked by and Blocks fact rows). Verified:
an entity titled ``A project with a " quote & an <script>alert(1)</script> tag``
fires `alert()` on the server route `/detail/pitch-0a0001` *and* in the static
`detail.html`, on the parent link of any child of that entity. A title is free text
through `PATCH /api/entity` — `_reject_bad_types` does not touch it — so any
signed-in member can plant script that runs for every reader, on a page that then
offers them a Save button. `_pr_link` (`render.py:537-540`) has the identical shape
over `entity.prs`. Pre-existing, but live, and this branch rewrote the code around
it.

**A2 — HIGH. The detail fact row's status chip.** `render.py:4115`:
`display = f'<span class="chip st-{entity.status}">{_human(entity.status)}</span>'`,
rendered with `|safe`. `status` is deliberately a permissive `str` — "a plain
string, not a Literal" — so a hand-edited or migrated file holds anything. Verified:
`status: 'ready" onmouseover=alert(1) x="'` renders a live event handler. The chip
two elements away is written through Jinja and is escaped, so one page disagrees
with itself. **Branch-introduced** (commit 7c99f59). `_status_class()` already folds
an unknown status to `st-ready` — use it, and build the tag with `Markup`.

**A3 — HIGH. The timeline tooltip's chips.** `render.py:2736-2737`:
`class="chip st-${row.status}"` and `kind-${row.kind}` raw, while the same line
wraps the text beside them in `esc()`. Verified in a DOM: the tooltip comes back
with a real `onmouseover` attribute that fires on hover. **Branch-introduced**
(commit 80eee61). The table does this correctly at `render.py:1366`.

**A4 — HIGH. The combobox popup.** `render.py:3113-3115`: `data-value="${m.value}"`
and `${m.label}` go in raw, and for the `entities` source the label *is* the entity
title. Verified: opening the Parent list on the detail page inserted a live
`<img src=x onerror=alert(1)>` into the listbox, and a tag containing a double
quote breaks out of `data-value`. Reachable on the detail page, the create form and
the cycle betting table — every write-enabled session. This branch edited the line
to add the role and aria attributes and did not escape what was already there.

**A5 — MEDIUM. `row.id` in `data-id` / `data-entity`.** `render.py:1402` and
`1418`. An id that fails `^(proj|pitch|task)-[0-9a-f]{6}$` is a *reported* blocker,
not a refusal — the entity still loads and still renders. A fixture with the id
``task-000001"><img src=x onerror=alert(1)>`` injected ten elements into the table
body while the visible text beside them was correctly escaped.

**A6 — LOW. A selector built from typed input.** `render.py:4758`:
``document.querySelector(`#roster tr[data-login="${login}"]`)``. A login with a
quote or a bracket throws inside the click handler and the Add button silently
stops working. `refusals()` in the same file already uses `CSS.escape` for exactly
this.

**The test this needs.** Not five assertions. A fixture plan whose every free-text
field carries `<img src=x onerror=…>`, a double quote, an ampersand and a
`</script>`, rendered through every page in both static and server mode, parsed,
and asserted to contain **zero elements that the plan did not put there**. That is
the only shape of test that would have caught all six at once, and it is the test
the branch is missing.

---

## B. The cascade, and my own regression

**B1 — HIGH. The frozen-column rules outrank the rules meant to override them.**
`render.py:1982-1987`. I qualified the two sticky selectors with `.table-scroll` to
win against `td.edit`, and made them (0,2,0) — which now beats three rules that
exist to override them:

- `thead [data-col="id"], thead [data-col="title"] { z-index: 4 }` loses, so both
  frozen header cells compute `z-index: 1` — not even the 3 that `thead th` gives
  every other header. The frozen *body* cells also compute 1 and come later in the
  DOM, so scrolling vertically paints rows over the sticky id and title headers.
- `thead [data-col="title"] { box-shadow: inset 0 -1px 0 …, 1px 0 0 … }` loses, so
  the title header has no bottom rule — precisely the failure the inset shadow is
  commented as preventing.
- `td.sev-cell-blocker` / `td.sev-cell-warn` lose, so a problem marked on the id or
  title column gets no ground — and `id` is the catch-all for any problem whose
  field has no column of its own.

My comment above those rules asserts the opposite and is wrong: the selector is not
bare, it carries a class. Drop `.table-scroll` and take `td[data-col="id"], th[...]`
at (0,1,1) so all three overrides land again — and confirm the original title-cell
shift stays fixed, since that is what the qualifier was for. If (0,1,1) is not
enough to beat `td.edit`, raise the overrides instead of the sticky rules, and say
in the comment which way the cascade actually resolves.

**B2 — MEDIUM. The suggestion popup is clipped by the table's own scroll box.**
`render.py:1941`: `.table-scroll { overflow: auto; max-height: … }`. The branch's
own comment at `render.py:4420-4425` states the rule it is breaking — `attachSuggest`
inserts the list as the input's next sibling, so an `overflow` on any ancestor cuts
it off, which is why the cycle page's bet table had `table-scroll` removed. Nine of
the fourteen columns carry a suggest list. Make the table header sticky against the
page the way `#roles thead th` already is on the people page, or give the popup a
home outside the clipping box.

**B3 — MEDIUM. `.editbar` and `.button` are unstyled on the table.** The table
renders `<p class="editbar"><a class="button" …>New entity</a>`, but the only
`.editbar` rule is inside `_DETAIL_STYLE` and the only `.button` rule is scoped
`.tl-controls .button` inside `_TIMELINE_STYLE`. The table's primary create action
is a bare inline link in a default-margin paragraph. This is exactly what commit
1e4449c set out to fix and missed.

---

## C. Writes that fail badly

**C1 — MEDIUM. A blank date is a 500.** `saveSetup()` posts `starts_on` and
`build_weeks` with no client check; `_reject_bad_cycle` validates the others and
skips anything `None`. Verified: `PUT /api/cycle/41 {starts_on: ""}` and
`{build_weeks: null}` reach `parse_cycle_text` and raise an unhandled
`ValidationError` — a 500, not a refusal. Both are one gesture away: clear the date
box, or type `six` into build weeks (`Number('six')` is NaN, which `JSON.stringify`
sends as null). The client compounds it: `put()` calls `response.json()` on a
plain-text 500, so `flush()` never resolves, Save stays disabled, the bar still
claims N unsaved changes, and nothing is announced. Refuse both with a 422 that
says what is wrong, and guard the JSON parse.

**C2 — MEDIUM. A conflict report is thrown away by three of five write paths.**
`_result` returns `{outcome, commit, conflict, head}` on a 409 and there is no
`detail` key, but the cycle setup PUT, the cycle bets PATCH and the graph
dependency save all read `answer.detail || 'refused'`. So the one answer that means
*somebody else moved the plan* is indistinguishable from a type error. The detail
page and the table handle it correctly — fold the three into one shared helper.

**C3 — MEDIUM. The table's conflict banner never clears.** `#row-conflict` is shown
and never hidden again, and unlike the detail page the table does not reload after a
successful save. One 409 leaves a stale "somebody changed this before you" through
every later success. It also has no CSS on the table at all, so the multi-line
report collapses into one run of unstyled text. Hide it on entry to `saveCell`, and
hoist the detail page's `#conflict` rule into the shell.

**C4 — MEDIUM. A typo removes somebody from a cycle.** `saveSetup()`:
`const rate = Number(input.value); if (rate > 0) availability[…] = rate;`. An
availability box left empty, set to 0, or typed as `50%` silently omits that person
from a PUT whose contract is "a missing name means somebody was removed". So a typo
takes somebody out of the cycle, with their capacity, with no confirmation. The bets
table one screen away already refuses with `${field} must be a number, not "…"` —
do the same here.

**C5 — LOW. `announce()` can wipe a later message.** When the new message equals the
current one the region is cleared and re-set on a 0ms timer; the cycle page calls
`say('')` on every staged edit, so two staged edits leave two pending timers that
set `''`. Reproduced: `#state` went to "Saved 2 changes" and was then blanked. The
receipt is the whole of F5's claim.

---

## D. Palette

Apply `PALETTE_V3.md` — light theme only, dark unchanged. It exists because the
light theme put white text on every fill, which forces every fill low on the
luminance scale, and a low-luminance amber is brown.

While you are in there, `--line-strong` is 2.95:1 where a bordered control sits on
`--surface-2` rather than `--surface`, and light `shelved` is 2.9966 against the
page. Both are a hair under 3. Nudge them over and re-measure rather than rounding.
