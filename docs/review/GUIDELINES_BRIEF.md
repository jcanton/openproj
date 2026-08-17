# Write the repository's guidelines: `AGENTS.md`

There is no AGENTS.md, no CONTRIBUTING, no CLAUDE.md. The conventions exist — they
are strong and consistent — but they live in the comments and in the reviewer's
head, which is why six rounds of agents each had to be told them again.

Write `AGENTS.md` at the repository root. It is read by whoever works here next,
human or agent, and it has one job: **make the next person good at this codebase
faster than reading 6,500 lines of `render.py` would.**

## Voice

Match the repository. Its prose is opinionated, concrete and short on hedging: it
says what went wrong and what the alternative was and why it lost. Read
`README.md`, `static/VENDOR.md` and thirty comments in `render.py`, `store.py` and
`schedule.py` before writing a line. Do not write a generic style guide; every
generic sentence you include makes the specific ones cheaper to skip.

No bullet lists of platitudes. Rules earn their place by naming the failure they
prevent, and this repository has a real one for almost every rule.

## What it has to cover

### 1. What this is, in a paragraph

Git-backed appetite planning for the icon4py team. Markdown files in a git
repository are the source of truth; the shaping document *is* the record; every
date is derived. The tool and the plan are two repositories and stay that way. The
README has this — do not restate it at length, point at it and cover what it does
not.

### 2. The invariants that are load-bearing

Each with the failure it prevents, which the code comments already explain:

- Only `depends_on` is stored, on the dependent; `blocks` is derived by reversing.
- Derived data never reaches frontmatter.
- Parse permissively, validate strictly. Requiredness lives in `validate_all`,
  never in the parse types.
- Grandfathering: a rule blocks only entities created after it existed.
- No npm, no CDN, no build step; vendored assets are inlined, and
  `tests/test_render.py` asserts no rendered page reaches the network.
- The bot owns `derived/` and nothing else.
- Colours come from tokens, in three theme blocks, and never only from inside a
  media query or a `[data-theme]` block.

### 3. How to write code here

The rules this work actually established, each with its incident:

- **One escaping boundary per language.** Python builds markup only through
  `Markup(...).format(...)` or autoescaped Jinja; JavaScript only through `esc` or
  `textContent`. Six separate injection sites existed because six places each
  decided for themselves. Fix the seam, then sweep every crossing.
- **Allowlists, not denylists.** An image was called remote if it started with
  `http://` or `https://` — two spellings out of an unbounded set. `//host` and
  `HTTP://host` both fetched. There is no denylist of URL spellings that is ever
  finished.
- **Never assemble a page by substituting into finished markup.** Rendering and
  then `str.replace`-ing over the result meant a title that merely *equalled*
  `BARS_JSON` was substituted. Template variables, always.
- **A write the model cannot read back must be refused.** `PATCH /api/entity`
  committed `title: 5` and every page answered 500 forever, on a protected branch.
  Parse before write, and say which field and why.
- **An invariant written twice will be guarded once.** The date arithmetic existed
  in three places and one had the overflow guard. If the guard is the same three
  lines in more than one place, it is one helper.
- **Empty must not look like broken**, and neither must a failure. This is the
  original UX finding and it keeps recurring through new mechanisms — a filter
  matching nothing, a plan that failed to load, and a `localStorage` read that
  threw all rendered the same empty page.
- **Assume the browser refuses.** `localStorage` throws in private mode and under
  some policies; nine of twelve calls were bare.
- Comments say WHY. The register is: what went wrong, or what the alternative was
  and why it lost. Nothing that restates the line beneath it.

### 4. How to find bugs here

**This is the most valuable section and the reason to write the file.** Six rounds
of adversarial audit ran on this branch. A green test suite missed every single one
of the defects below. Each was found by asking one question:

| The question | What it found |
|---|---|
| What if a stylesheet meant for one page is loaded by another? | A capacity-meter `.bar` rule in the shared shell overrode the geometry of every timeline `<rect>`; the whole Gantt drew 140×8 and said nothing about dates. |
| What if a value *equals* the mechanism instead of exploiting it? | Pages were assembled by `str.replace`; a title of `BARS_JSON` and an owner of `x onmouseover=alert(1) y` put a live handler on every bar link, using no character any escaper touches. |
| What if it is spelled a way the check did not enumerate? | `//host/a.png` and `HTTP://host/a.png` both drew live `<img>` tags past a `startswith(("http://", "https://"))`. |
| What does the write path accept that the read path cannot read back? | Eleven PATCH bodies committed and then 500ed every page permanently. |
| The same arithmetic is written three times — which copies got the guard? | Two of three date computations had no overflow guard; a build-weeks of 500000 killed nine routes. |
| Can the test tell the difference between the value resolving and the pixel appearing? | An outset `box-shadow` on a cell in a `border-collapse: collapse` table is never painted by Chrome. The test asserted the stylesheet resolved correctly, and it did, while nothing was drawn. |
| What do the diagnostic tools say when the thing is broken? | `openproj check` reported "0 blockers, 0 warnings" and `openproj render` wrote no files, on a plan that 500ed every page. |

Generalise those into the habits that produced them, and say what to actually do:
render pages and parse them in a real DOM; drive the shipped JavaScript rather than
grepping it; resolve the real cascade when a claim is about specificity; use a real
browser when a claim is about pixels; attack through the API rather than by editing
files; and mutation-test your own checker, because two of the harnesses used here
had bugs that made checks pass vacuously.

Say plainly that a hostile-versus-benign comparison cannot see a defect that
affects both, and that a corpus which does not contain the one string that matters
proves nothing.

### 5. How to test here

- Test the behaviour in the medium where it happens.
- Derive fixtures from the code where the code is what varies — the marker corpus
  reads the marker list out of the source, so a new marker cannot be added without
  the test knowing.
- A test that would not have caught the defect it is written for is not a test.
- Report skips. `addopts = "-q"` plus a documented `pytest -q` became `-qq` and
  suppressed the summary; 34 JS tests skipped silently when node was absent.
- Node is needed for the JS-driven tests. Say so.

### 6. Working on this branch

State it plainly, because it is now a constraint on everybody:

`review_design` has two other worktrees based on it — `shapeup_feats` and
`two_feats`, both branched from `ca18d60`. **Its history is immutable.** No rebase,
no amend, no force-push, no squash. Corrections are new commits.

### 7. Commit messages

The convention is visible in `git log` and worth stating: a short imperative
subject that states the change as a fact about the product — "A status is a rung on
a ladder and a shape, not a hue" — then a body explaining what was wrong and why
this is the fix. Every message written on jcanton's behalf ends with exactly:

```
🤖 Written by an agent on behalf of @jcanton
```

and nothing after it. No `Co-Authored-By`, no `Claude-Session` trailers.

## Length

Long enough to be worth reading and short enough to be read. If a section is
generic, cut it. Better six hundred words that could only have been written about
this repository than three thousand that could have been written about any.
