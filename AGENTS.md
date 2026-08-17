# Working on openproj

Git-backed appetite planning for the icon4py team. `README.md` has the shape of the thing: one
markdown file per entity, the shaping document *is* the record, every date derived from one typed
`assigned_on` and one size, the tool and the plan kept in two repositories on purpose. Read it
first. This file is the part it does not say — the invariants that fail loudly when you step on
them, the rules that eight rounds of audit paid for, and how to find the bug that is already here.

## This branch's history does not move

`review_design` has two other worktrees based on it — `shapeup_feats` and `two_feats`, both
branched from `ca18d60`. **No rebase, no amend, no force-push, no squash, ever.** A rewrite here
does not inconvenience one person; it detaches two other people's work from the commits it was cut
from. Corrections are new commits. If you have concluded that history needs rewriting, that is the
conclusion that is wrong.

## The invariants

Each is load-bearing and each has one place that enforces it. Break one and the damage is not local.

**Only `depends_on` is stored, on the dependent.** `blocks` is the reverse, built in `build_index`
(`index.py`) and never read from a file. A stored copy is stale by construction and lets one record
contradict the graph. Edges to entities that do not exist are dropped from both maps at once, so
the forward and reverse views always agree.

**Derived data never reaches frontmatter.** No computed date in an entity file, ever — rescheduling
one blocker would rewrite fifty files. `serialise` and `patch_text` (`model.py`) round-trip rather
than re-serialise: only keys whose value actually changed are rewritten, and comments, key order,
blank lines and list style survive a save. "Edit it in git if you prefer" stops being true the
first time a save reformats somebody's file, and nobody comes back after that.

**Parse permissively, validate strictly.** Every field is optional at the type level; `status` and
`priority` are plain `str` and deliberately not `Literal`. Requiredness lives in `validate_all`
(`model.py`) and nowhere else. One file written before a vocabulary change took every page down
with a 500 instead of showing a problem beside the record that caused it — a record that fails to
load is worse than a record that is wrong, because it takes the other four hundred with it.

**A file that is not a record costs that file and nothing else.** Permissive parsing covers the
values *inside* a record that loads; it said nothing about a file that will not load at all, and
every plan file was parsed with nothing around the parse. Fifteen ways of writing one — no `---`, a
flow sequence that never closes, `effort_weeks: three`, `assigned_on: next tuesday`, a frontmatter
written as a list, a cycle numbered `forty-one`, `holidays: [not-a-day]` — each answered 500 on ten
of the eleven routes, for everybody, until somebody with a terminal fixed it, while `/healthz` went
on answering. Every plan file now goes through `readable` (`model.py`), which returns what loaded and
one `Unreadable` per file that did not, and the shell draws those on every page by path and reason.
Skipping them silently would have been worse than the 500: a table that draws fifteen of sixteen
tasks and looks completely normal is a thing you cannot act on. `readable` catches `Exception`, and
it is the only place that does — the failures are a ValueError, a ruamel ParserError, a pydantic
ValidationError, a UnicodeDecodeError and an AttributeError, and a tuple of the ones seen so far is
the denylist this file refuses to write everywhere else.

**A rule blocks only entities created after it existed.** Each rule carries the `schema_version`
that introduced it, and `validate_all` demotes a rule newer than the entity it is judging to a
warning. Without grandfathering, adding one required field invalidates the whole corpus at once and
the rule gets reverted rather than adopted. `shaped_by` is the live example.

**A status reaches a class attribute through `_status_class` (`render.py`) and no other way.**
Because `status` is permissive it holds whatever is in the file. Escaping it would have been enough
to stop the injection and would still have written `class="chip st-ready&#34; onmouseover"` into the
page; folding it to a rung means the attribute names a rule the stylesheet actually has.

**Colours are tokens, defined in three blocks.** Bare `:root`, `:root[data-theme="dark"]`, and
`@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`. Most readers
never touch the toggle and match the media query alone, so a value right in one block and wrong in
another is wrong for most of the people who will ever see it. Nothing may have its only definition
inside a block half the readers never match. The five status fills are a *luminance ladder* and not
five hues at one lightness: hue is the channel a dichromat loses, and on the graph and the timeline
the fill used to be the only channel there was.

**No npm, no build step, no CDN.** A Node toolchain that rots is the most common way a small
internal tool becomes unbuildable in two years. Libraries are vendored, checksummed and inlined
(`static/VENDOR.md`); the typeface is a `data:` URI, and because every rendered page is therefore a
copy of Inter, the OFL notice ships inside the `@font-face` block rather than only in the
repository. `test_no_page_reaches_the_network` and `test_no_page_asks_the_network_for_a_font` are
the only things that would notice a regression.

**The bot owns `derived/` and nothing else.** If CI starts patching frontmatter, bot and humans
fight over the same files forever.

## How to write code here

**One escaping boundary per language.** Python builds markup through `Markup(...).format(...)` or
autoescaped Jinja (`_ENV = Environment(autoescape=True)`); JavaScript through `esc` or
`textContent`, and `esc` is declared once, in the shell, for every page. Six injection sites existed
at once because six places each decided for themselves. Fix the seam, then sweep every crossing —
the sweep is the work, not the fix.

**Never assemble a page by substituting into finished markup.** Pages were rendered and then
`str.replace`d over the result. A title that merely *equalled* `BARS_JSON` was substituted, and an
owner of `x onmouseover=alert(1) y` put a live handler on every bar link on the timeline, using no
character any escaper touches. Every JSON block is a template variable now, and
`test_no_page_is_assembled_by_substitution` parses `render.py` and `web.py` as syntax — not as text
— to keep `.replace(` and `.sub(` out of them.

**Allowlists, not denylists.** An image counted as remote if it started with `http://` or
`https://` — two spellings out of an unbounded set. `//host/a.png` and `HTTP://host/a.png` both drew
live `<img>` tags, referer included, which in a plan anybody can write to is one line of markdown
turning a shaping document into a tracking pixel aimed at everyone who opens it. It survived into
the static export, where there is no origin to appeal to. `_image` (`render.py`) now draws an image
only if it matches an asset this tool stored. There is no denylist of URL spellings that is ever
finished.

**A write the model cannot read back must be refused.** `PATCH /api/entity` committed `title: 5`,
and eleven bodies like it, and every page then answered 500 forever — on a protected branch, so the
commit cannot be force-pushed away and the 500ing pages will not hand over the sha to craft a repair
against. `web.py` parses the patched text before writing and answers 422 naming the field and why.

**An invariant written twice will be guarded once.** The date arithmetic existed in three places and
one had the overflow guard: `Cycle.ends_on` and `_month_ticks` did not, so a build-weeks of 500000
typed into a form, or an `assigned_on` of 9999-12-31, killed nine routes permanently. It is one
function now — `days_after` and `within_the_calendar` (`model.py`), which bound *before* rounding,
because `round()` and `math.ceil()` both raise on infinity and `effort_weeks: .inf` is one
hand-edit away. If a guard is the same three lines in more than one place, it is one helper.

**Empty must not look like broken, and neither must a failure.** A filter matching nothing, a plan
that failed to load, and a plan with no entities are three different sentences, drawn inside the
table body with the control that gets you out of it. This is finding F1, and it keeps coming back
through new mechanisms.

**Assume the browser refuses.** `localStorage` throws on the property itself, before any method is
called — a private window, blocked cookies, an enterprise policy — and nine of twelve calls were
bare. The bare one at the top of the table's script killed it before the first row was drawn, so
the page in front of everybody was a heading and "17 of 17 shown" over nothing at all. Everything
goes through `remembered` in the shell now. A remembered width is a convenience; the rows are the
page.

**Comments say WHY** — what went wrong, or what the alternative was and why it lost. Nothing that
restates the line beneath it. `store.py`'s module docstring is the register: eight concurrent
writers sharing one worktree lost 87.5% of their commits to `index.lock` contention, which is why
there is no working copy, and why a single `repo.index` anywhere in that file gives it back.

## How to find bugs here

**This is the section worth the file.** Eight rounds of adversarial audit ran on this branch, and a
green test suite missed every defect they found. Each round was cracked by exactly one question.

| Ask this | What it found |
|---|---|
| What if a stylesheet meant for one page is loaded by another? | A capacity-meter `.bar` rule in the shared shell overrode the geometry of every timeline `<rect>`. The whole Gantt drew 140×8 and said nothing about dates. |
| What if a value *equals* the mechanism instead of exploiting it? | Pages were assembled by `str.replace`. A title of `BARS_JSON` and an owner of `x onmouseover=alert(1) y` put a live handler on every bar link, using no character any escaper touches. |
| What if it is spelled a way the check did not enumerate? | `//host/a.png` and `HTTP://host/a.png` both drew live `<img>` tags past a `startswith(("http://", "https://"))`. |
| What does the write path accept that the read path cannot read back? | Eleven PATCH bodies committed and then 500ed every page permanently. |
| The same arithmetic is written three times — which copies got the guard? | Two of three date computations had none. A build-weeks of 500000 killed nine routes. |
| Can the test tell the difference between the value resolving and the pixel appearing? | An outset `box-shadow` on a cell in a `border-collapse: collapse` table is never painted by Chrome. The test asserted the stylesheet resolved correctly, and it did, while nothing was drawn. |
| What do the diagnostic tools say when the thing is broken? | `openproj check` reported "0 blockers, 0 warnings" and `openproj render` wrote no files, on a plan that 500ed every page. |
| What does a person with a terminal commit that this never tries to parse? | Fifteen files that are not records — a pasted note with no `---` among them. Each took ten of eleven routes down permanently; `/healthz` alone answered, and `openproj check` died with a traceback on the first one and never mentioned the second. |

Behind all eight is one habit: **ask the question in the medium where the answer lives.** In
practice that means:

- **Render pages and parse them in a real DOM.** A substring cannot tell markup from text; a parser
  can. Five escaping bugs shipped under tests that all asserted on substrings of the page.
- **Drive the shipped JavaScript rather than grepping it.** The table's rows, the timeline's
  tooltip, the combobox popup and the cycle roster are built at runtime and appear in no rendered
  file. `tests/test_injection.py` runs those exact scripts in node and hands what they assign to
  `innerHTML` back to the same parser.
- **Resolve the real cascade when the claim is about specificity.** `tests/cascade.py` weighs
  selectors the way § Selectors 4 does and answers which rule wins, by name. A rule being *in* the
  stylesheet says nothing about whether it wins, which is the only thing a reader sees.
- **Use a real browser when the claim is about pixels.** `tests/browser.py` drives headless Chrome.
  A resolved value is a promise about pixels that a stylesheet cannot keep on its own.
- **Attack through the API, not by editing files.** The eleven unreadable PATCH bodies went in
  through the write path; nothing you can do by hand-editing a fixture would have found them.
- **Mutation-test your own checker.** Two of the harnesses used here had bugs that made their checks
  pass vacuously. Break the thing on purpose, watch the test fail, then put it back.

And two things that look like evidence and are not:

- **A hostile-versus-benign comparison cannot see a defect that affects both.** The census in
  `test_injection.py` renders the same plan twice, once with a payload in every field and once with
  an ordinary sentence, and demands the same element tree. A marker substituted into both pages
  equally is invisible to it. That is why there is a second corpus.
- **A corpus that does not contain the one string that matters proves nothing.** `markers()` reads
  the marker list out of `render.py`'s own source with `ast`, so a tenth marker lands in the corpus
  on the commit that introduces it. A list written down by hand is a list that goes stale, and going
  stale is exactly how the nine shipped.

## Design

**When you qualify a selector to win a fight, work out what else it now beats.** Twice in one file
in one week. `dd, td.edit { position: relative }` in one page's stylesheet stole `position: sticky`
from the table's title column, so it kept the `left` meant for a sticky box and shifted 187px right
over priority and status. The `.table-scroll` qualifier added to fix *that* made the frozen columns
(0,2,0) and silently outranked all three rules written to correct them: both frozen headers dropped
to z-index 1 and were painted over by their own rows, the title header lost its bottom rule, and a
problem on either column lost its ground. CSS classes cancelling each other out is this file's
characteristic failure. Say in the comment which way the cascade resolves, and resolve it rather
than guessing.

**Structure is information.** A structural device should encode something true rather than
decorate. The status ladder is the example: its order means "how far this is from the page's
ground", which is why it survives colour blindness instead of merely looking tidy. A device that
encodes nothing is a device to cut.

**Copy is design material.** Name things by what a person controls, never by how the system is
built — `missing_required_fields` was on screen for months, and `HUMAN` in `render.py` is now the
one map, because five pages inventing their own is how `in_progress` became "In progress", "in
progress" and "in_progress" on the same screen. A control says exactly what will happen and keeps
the same word through the flow. An error says what went wrong and how to fix it, without
apologising and without vagueness. An empty screen is an invitation to act.

**There is a quality floor, and you meet it without announcing it**: responsive, visible keyboard
focus (`:focus-visible` with `outline: 2px solid var(--focus)`, asserted on every page), reduced
motion respected. That last one is true of the code rather than aspirational. The shell carries one
`@media (prefers-reduced-motion: reduce)` block, blanket and `!important` — each page's own
stylesheet is inlined immediately after it and would otherwise take the tie on order. The app's one
animated rule is `#grip::before`, the detail page's width handle, and it is not the only page that
carries it: `_DETAIL_STYLE` is inlined by the detail page, the cycles index, the cycle page and the
create form, so three pages ship a fade with no `#grip` to move. Inert here, and exactly why the
floor belongs in the shell rather than beside the rule it switches off. CSS cannot reach a canvas:
cytoscape's layout runs at `animate: false` and has to stay there, or the graph moves for a reader
who asked it not to.

**Take a screenshot.** The defects that survived longest are the ones no agent could see. The frozen
column's edge resolved to exactly the value every test asserted, on exactly the element they
asserted it on, and Chrome painted nothing — an outset `box-shadow` on a cell in a collapsed table
is not a dimmer line, it is no line. The Gantt drew every bar 140px wide for a whole round. If a
claim is about pixels, look at the pixels.

## How to test here

- **Test the behaviour in the medium where it happens.** If the claim is about pixels, the test has
  to tell painted from unpainted, or say in its own words why it cannot.
- **A test that would not have caught the defect it is written for is not a test.** Delete the fix,
  watch the test fail, put the fix back. Seven rounds have each shipped one defect a green suite
  missed; the last survived because a test asserted a stylesheet resolved to a value while nothing
  was painted.
- **Derive fixtures from the code where the code is what varies.** `markers()` reads `render.py`;
  `required_at()` runs the gate over a blank entity rather than restating it, so it cannot drift
  from the rule it mirrors — it *is* the rule.
- **Report skips.** `addopts = "-ra"`, deliberately not `-q`: a `-q` there turned the documented
  `pytest -q` into `-qq`, which suppresses the summary line entirely, and thirty-four JS tests
  skipped silently when node was absent.
- **`node` and Chrome are needed to test, not to build or run.** The JS-driven tests and the pixel
  tests skip with a stated reason when the binary is missing, and a suite missing them is green for
  the wrong reason. A machine that gates a merge should have both.

```bash
uv sync
uv run pytest -q -p no:warnings
uv run ruff check .
```

ruff: line length 100, target py312, `E,F,I,UP,B`.

## Commits

A short imperative subject that states the change as a fact about the product rather than as a
description of a diff — "A status is a rung on a ladder and a shape, not a hue", "A page is
rendered, not rendered and then edited" — then a body saying what was wrong and why this is the fix.

Anything written on jcanton's behalf ends with exactly this line, and nothing after it:

```
🤖 Written by an agent on behalf of @jcanton
```

No `Co-Authored-By`, no `Claude-Session` trailers.

🤖 Written by an agent on behalf of @jcanton
