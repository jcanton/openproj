# Working on openproj

Git-backed appetite planning for the icon4py team. `README.md` has the shape of the thing: one
markdown file per entity, the shaping document *is* the record, every date derived from one typed
`assigned_on` and one size, the tool and the plan kept in two repositories on purpose. Read it
first. This file is the part it does not say — the invariants that fail loudly when you step on
them, the rules that nine rounds of audit paid for, and how to find the bug that is already here.

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

**A plan directory is flat, and one place decides that for both halves of the app.**
`record_paths_in` (`model.py`) turns a tree — `store.paths` at a commit, or an `rglob` of the disk —
into the record paths plus one `Unreadable` per markdown file below them. Every reader in `web.py`
had a filter of its own asking whether the *first* path segment was `people`, which is true of
`people/team/ann.md`: `login_of` read `ann` off the filename and handed back a second record for a
login that already had one, drawn on every served page, invisible to `openproj check`, and picked
between by which of the two paths sorted last. Nested files are named rather than skipped, for the
same reason the fifteen above are.

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
hand-edit away. If a guard is the same three lines in more than one place, it is one helper. Two
constants that are the same number are the same defect: `MAX_UPDATE_BYTES` and `MAX_BODY_BYTES` were
both written out as `256 * 1024` in two files, one bounding a socket frame and one bounding what may
be committed — and because a Yjs update is always larger than the text inside it, the transport
refused a body the policy would have taken, in silence. One is derived from the other now, and the
comment says which kind of bound each is.

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

**This is the section worth the file.** Twelve rounds of adversarial audit ran on this branch, and a
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
| Two readers walk the same tree — do they agree on which files are records? | `_people_at` matched on the first path segment while `load_repo` globbed one level, so a hand-committed `people/team/ann.md` was a second record for `ann` on every served page, invisible to the CLI, and `openproj check` said nothing. |
| Which index space is that `int` in, and would anything say if it were the other one? | `Room.absorb` measured a splice in Python code points and applied it to `pycrdt`, which addresses UTF-8 bytes. Both are `int`, an index inside a character silently appends at the end instead of raising, and every body with an em dash before the edit was rewritten in the wrong place — and committed. |
| What has already run by the time this line reads that value? | The Yjs observer wrote the room's text over a restored draft *before* the branch that checks for one compared the textarea against what the server rendered. The check was therefore always false in exactly the case it was written for, and somebody's unsaved writing went into the box and then out of `localStorage`. |
| The invariant is written in two languages — which copy is guarded? | `byte_offset` fixed the server and a syntax test held it there. The browser's half of the same splice went on scanning UTF-16 code units, so a boundary between the halves of a surrogate pair spliced half a character: `👍 done` edited to `👎 done` left the browser holding one document and the room another, with nothing raising in either. Emoji were strictly worse with a socket than without one, and the mandated footer of this file is `🤖`. |
| What happens on the branch that decides *not* to act? | Three of them said nothing at all. An update over the frame ceiling was dropped with `continue`, so a 263 kB paste produced no frame back and the room committed the text from before it. A Save with nothing to commit returned without answering, so the page stayed "saving" for ever and the shell queued every later banner behind it. And the two ceilings were the same number, so the transport refused a body the policy would have taken. |
| What does the callee document itself as raising, and what does the handler name? | `store.write` raises `StoreDiverged`, `StoreLocked` and `pygit2.GitError`; the room caught `(HTTPException, ValueError)`. An escape killed the timer task in `_watch`, and a dead timer has exactly one symptom: nothing is committed any more. |
| Is the harness itself lying? | `tests/js/drive.js` handed this realm's `String` into the vm context it built, so `text.constructor === String` — how `YText.insert` tells a string from an embed — was false for every string the page made. Every insert became a one-unit embed with no text in it. A test written against that shim would have reported a defect the editor did not have, and passed one it did. |
| What does *one* participant's socket do to everybody else's? | The room broadcast by awaiting `send_json` per member in turn. uvicorn's send begins `await self.writable.wait()`, cleared when a transport's buffer fills, so one member who stopped draining held that coroutine — and with it every other member's keystroke and the room's own timer, which reaches the same line. Three real sockets: the second member got nothing for thirty seconds, nothing was committed again, and `/healthz` answered 200 throughout. |
| Whose names end up in a line this server signs? | Every write path built its commit message as `', '.join(fields)` — keys off the wire, verbatim. A field named `notes\n\nCo-authored-by: Mallory <…>` committed exactly that trailer, which git's parser, `git shortlog --group=trailer:co-authored-by` and GitHub all honour. On a branch whose whole point is that `Co-authored-by:` records who wrote a document. |
| Is the harness itself lying? (again) | `drive.js` copied a parsed element's text into `textContent` and never into `.value`, so a `<textarea>` answered `''` where a browser answers the record's body. `ORIGINAL_BODY` was therefore always empty in page mode, which flips the one branch in the editor that can lose unsaved work. Two of the three rounds before this one were misled by this same file. |
| Is the picture wrong, or is what we did to it wrong? | The graph drew boxes lying across each other, and the question asked was whether cytoscape and ELK were the right libraries. They were. `packComponents` — written here — re-arranged the drawing afterwards by `cy.elements().components()`, which is edge-connectivity, and an edge on that page is a dependency and never containment. It took every group apart: 0 overlapping boxes became 17-21, 0 foreign cards became 29-70. Fifteen agents and forty-two library options later, the answer was to delete eight lines of ours. Measure immediately before and immediately after your own post-processing before you audit anybody else's library. |
| The page drew. Did the script finish? | Deleting that function took the `cytoscape()` constructor, `route()` and `paint()` with it, because the deleted range ran past the closing brace. The canvas still appeared, so it looked fine; everything after the throw simply never ran, and the error was thrown before any listener existed to report it. What caught it was a test written the same hour, failing for a reason that made no sense. `typeof x` throwing `TDZ` on a `let` is the tell: execution never reached that line. || Which rule gives this drawing a size — and is there one? | The draft row's check and cross are `<svg class="icon">`, which carries a `viewBox` and no `width` or `height`. Every earlier icon sat in a box that sized it (`.avatar svg`, `.picker .art svg`), this one did not, and an SVG nothing sizes lays out at 0x0: the two controls that create and abandon a record were empty boxes on the served page, under a suite that was green because it only ever asked whether the markup was emitted. |
| Does the fix throw out the person who was working? | The first version of the outbox evicted a member whose queue passed a byte ceiling. Three real tabs: a tab applying a burst of whole-document updates goes a megabyte behind for a moment and catches up completely, and it was thrown out beside the tab that was actually suspended — so the room emptied and committed nothing. *Behind* and *not draining* are different things, and only a clock can tell them apart. |

Behind all twelve is one habit: **ask the question in the medium where the answer lives.** In
practice that means:

- **Render pages and parse them in a real DOM.** A substring cannot tell markup from text; a parser
  can. Five escaping bugs shipped under tests that all asserted on substrings of the page.
- **Drive the shipped JavaScript rather than grepping it.** The table's rows, the timeline's
  tooltip, the combobox popup and the cycle roster are built at runtime and appear in no rendered
  file. `tests/test_injection.py` runs those exact scripts in node and hands what they assign to
  `innerHTML` back to the same parser. The room is driven the same way: `{socket: true}` gives
  `drive.js` a `WebSocket` the test moves frame by frame, and what the page puts on that wire is
  applied to a real `Room` — because the claim crosses two CRDT implementations and a copy of
  `typed()` written in the test would only prove the test agrees with itself.
- **A shim is a realm, and a realm is a thing libraries ask about.** `drive.js` builds its sandbox
  out of node's `vm`, and the context it makes already has every ECMAScript intrinsic; handing the
  outer realm's copies in shadows them. Nothing notices until a library compares one —
  `text.constructor === String` is how Yjs tells a string from an embed — and then every insert the
  page makes is stored as an embed with no text in it, silently, in a harness whose whole job is to
  say what the page really does.
- **Resolve the real cascade when the claim is about specificity.** `tests/cascade.py` weighs
  selectors the way § Selectors 4 does and answers which rule wins, by name. A rule being *in* the
  stylesheet says nothing about whether it wins, which is the only thing a reader sees.
- **Use a real browser when the claim is about pixels.** `tests/browser.py` drives headless Chrome.
  A resolved value is a promise about pixels that a stylesheet cannot keep on its own.
- **Use a real server and a real socket when the claim is about backpressure.** `TestClient` speaks
  ASGI directly and its send never blocks, so under it a member who stops draining is merely a
  member who is slower — and the whole defect is that uvicorn's send is not. There is no kernel in
  that harness and therefore no `writable` event to clear. `tests/test_coedit.py`'s `serving`
  fixture is a real uvicorn on a real port, and the unresponsive member is a real client with a
  small receive window that genuinely stops calling `recv`.
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
  watch the test fail, put the fix back. Twelve rounds have each shipped one defect a green suite
  missed, and the last three all destroyed somebody's writing without a word: a splice measured in
  code points and applied in bytes, an observer that overwrote a restored draft before the line
  written to protect it could read the box, and the same splice in the browser cutting emoji in
  half. That last one went out under 1160 passing tests, and the reason is written down — **no test
  drove the editor with anything but ASCII.** A corpus that does not contain the one string that
  matters proves nothing, and "has an emoji in it somewhere" is not that string: the case is a
  splice boundary *inside* a surrogate pair, and two of the five bodies in
  `test_an_edit_across_an_emoji_reaches_the_room_as_the_character_it_was` are there as the controls
  that passed with the defect in place.
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

## Look for it before you write it

Before building a feature, look for the library or extension that already does it, and weigh
that against writing it. Write down what you found and why you chose as you did — in the commit
that builds it, so the next person inherits the search rather than repeating it.

This is not a preference for dependencies. `No npm, no build step, no CDN` is still the rule, and
it decides most of the answer: a candidate is only a candidate if it ships a file that can be
vendored into `static/`, checksummed in `SHA256SUMS`, inlined into a page, and read by a person —
and if its licence is compatible with BSD-3. What it costs is bytes on one page, and that is a
number you can put beside the alternative.

What it saves is usually not the happy path. The gestures this repository has hand-rolled and got
wrong are the ones a library gets right: drawing a dependency by clicking two nodes was written
here and works; dragging a node into another box to refile it was written here, shipped, and had
to be removed the same day because a compound's outline follows the child being dragged and there
was no point on the canvas that meant "outside". `cytoscape-compound-drag-and-drop` is 14 KB and
had solved that; it existed the whole time.

And the answer is allowed to be no. `cytoscape-edgehandles` draws exactly the connection preview
that was hand-rolled here, and it was refused in the same pass: it reaches for `lodash.memoize`
and `lodash.throttle` as globals, so taking it means vendoring lodash to draw a line. Written
down here because "we looked and it did not fit" is the finding somebody would otherwise spend an
afternoon re-discovering.

The same question applies to the layouts underneath: dagre knows nothing about compound nodes, so
it lays a nested plan out as though it were flat, which is why the graph fitted into 7% of its
canvas and drew edges through boxes. ELK's layered algorithm is hierarchy-aware. That is a 1.5 MB
answer to a problem no amount of parameter tuning here was going to solve.

It also returns routed bend points, and this said so for a fortnight while the page threw them
away: `cytoscape-elk` applies positions to the non-parent nodes and never reads an edge's
`sections`, so every edge on the graph is cytoscape's own `round-taxi`. Audit what a library
gives you, and then audit whether the adapter in between is passing it on — the second question
is the one nobody asks.

The audit is three questions: does something already do this; can it be vendored under the rules
above; and what does it cost against what it replaces. A "no" to any of them is a fine answer —
it is the unasked question that is expensive.

## Tag when you deploy

The running revision has to have a name. Cloud Run knows a container digest and the service page
shows a revision id; neither of those is something you can check out, and "which commit is live" was
answered for months by reading a sha out of a deploy log. So: bump `pyproject.toml` and
`src/openproj/__init__.py` — they are two files and they have already disagreed with each other and
with the newest tag — run `uv lock`, because CI installs `--locked` and a bump without it goes red,
then tag `main` and deploy that commit.

Versions are cheap here. The plan is on GitHub and this service holds no data, so a tag costs one
command and buys the ability to say what is running, and to put a release beside it saying what
changed. 1.0.0 waits for adoption, per jcanton.

## Type checking: measured, not adopted

Measured on 2026-08-18, with `ty` 0.0.72 and `mypy` 2.3.1:

```bash
uvx ty check src/     # 41 diagnostics
uvx ty check          # 419, once the tests are included
uvx mypy src/         # 44 errors in 9 files
```

Neither is in CI. The reason is not "too many to fix" — it is what the errors turn out to be when
you read them. They do not scatter across the code; they fall in two heaps, and the larger heap is a
rule this file argues for.

**Most of them are `validate_all` seen from outside.** Every field is optional at the type level and
requiredness lives in one function, so nothing reading a signature can know that a gate already ran.
`build_end` is `date | None` where `_matches_predicate` (`index.py`) compares it against `span.end`,
although that function returned already if the cycle's window was missing — the guard is real, it
just lives in a different expression than the call, and no checker connects the two. `Entity` has no
`shaped_by` at all, because `kind == "pitch"` is a runtime discriminator rather than a tagged union.
Going green on this heap means an `assert` or a `cast` at each site, which takes the guarantee out
of the one place this file says it lives and scatters copies of it across the callers. That is the
trade the number is quietly asking for, and by the rule above — an invariant written twice will be
guarded once — it is the wrong one.

**The rest is the shape of other people's stubs.** Thirteen of the 41 are one call, in `app_jwt`
(`github.py`): `load_pem_private_key` returns a union of fifteen key types, and every one of them
files its own complaint about the `key.sign` beneath it. Most of what is left is pygit2's
`Tree | Blob` and `None | Object` in `store.py`, and a missing `uvicorn` stub in `cli.py`. Six files,
and nothing like 41 separate problems.

So: not wired in, and the number written down instead. A gate nobody can go green against is a gate
that gets switched off, and a config carrying a hundred ignores is a worse lie than an honest count.
Re-run the three commands before arguing about this — the first heap is the kind of narrowing `ty` is
still growing, and some of it will go away without anybody editing a line of `src/`.

🤖 Written by an agent on behalf of @jcanton
