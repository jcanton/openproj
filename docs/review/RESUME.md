# Where the UX redesign stands, and how to pick it up

Written at a deliberate pause. Everything below is on branch `review_design` in the
worktree `.worktrees/review_design`. Nothing is in flight; nothing is lost.

## The constraint that outranks everything

`review_design` has two other worktrees based on it — `shapeup_feats` and
`two_feats`, both branched from `ca18d60`. **Its history is immutable.** No rebase,
no amend, no force-push, no squash, ever. Corrections are new commits.

## State

- Branch `review_design`, based on `main` at `fe8b817`.
- Roughly 25 commits, +11,700/−1,060 across 27 files.
- Test suite 402 → ~700, `ruff check` clean.
- `main` is untouched and clean.

## What is done

- **All 29 findings** from the UX review in `FINDINGS.md`, closed and independently
  re-verified on rendered pages rather than in a diff.
- **The design system**: Inter vendored and inlined as a `data:` URI
  (`DESIGN_TOKENS.md`), and the status palette rebuilt twice — once onto a
  luminance ladder that survives colour blindness (`PALETTE_V2.md`), once more to
  invert the light theme so its hues are not muddy (`PALETTE_V3.md`). Every ratio
  in those files was measured, not estimated.
- **Five of the owner's six notes** in `FEEDBACK.md`.
- **Six rounds of adversarial audit**, and the defects they found: `FIXES.md`,
  `FIXES2.md`, `FIXES3.md`, `FIXES4.md`. Sections A and B of `FIXES4.md` — the two
  date-overflow blockers and the two localStorage defects — are committed.

## What is not done

1. **`FIXES4.md` sections C, D and E.** The frozen-column edge is dead code (an
   outset `box-shadow` on a cell inside a `border-collapse: collapse` table is
   never painted by Chrome; the file already knows an *inset* shadow is needed, one
   comment earlier). The table still scrolls sideways between 1101 and 1393px,
   because the fit's minimum is 1354px while the media query that sheds columns
   fires at 1100px — two numbers that must agree, written in two languages. The
   `+N` badge is clipped where a clamped column falls under about 128px. Plus two
   small visible things: the cycle page's bet-table inputs cut text mid-word, and
   the detail page states the status twice.

   This was mid-flight when work paused. Check `git status` before starting: if the
   tree is dirty, read the diff before adding to it.

2. **`AGENTS.md`**, per `GUIDELINES_BRIEF.md`. The valuable part is the table of
   questions — each of the six audit rounds was cracked by exactly one question,
   and a green suite missed every defect they found.

3. **A final verification pass**, and then the answer to: is this safe to serve to
   a room of people who can all write to it?

## How to restart

```bash
cd .worktrees/review_design
uv sync
uv run pytest -q -p no:warnings          # expect ~700 passing
uv run ruff check .
```

To look at it — the server needs a plan repository of its own, because `seed/` is a
subdirectory of the tool's repository rather than a repository in its own right,
and pointing `serve` at it renders an empty plan with no error (which is finding
F1, discovered exactly that way):

```bash
mkdir -p /tmp/plan && cp -R seed/* /tmp/plan/
cd /tmp/plan && git init -q && git add -A && git commit -qm seed && cd -
uv run openproj serve --repo /tmp/plan --auth dev --port 8010
```

## How the bugs were actually found

Worth reading before adding to this branch, because a green test suite missed every
single one of them. The full account is in `GUIDELINES_BRIEF.md`; the short version
is that each round was cracked by one question:

- What if a stylesheet meant for one page is loaded by another?
- What if a value *equals* the mechanism instead of exploiting it?
- What if it is spelled a way the check did not enumerate?
- What does the write path accept that the read path cannot read back?
- The same arithmetic is written three times — which copies got the guard?
- Can the test tell the value resolving from the pixel appearing?
- What do the diagnostic tools say when the thing is broken?

And the practice: render pages and parse them in a real DOM, drive the shipped
JavaScript rather than grepping it, resolve the real cascade when the claim is
about specificity, use a real browser when it is about pixels, attack through the
API rather than by editing files, and mutation-test your own checker — two of the
harnesses used here had bugs that made their checks pass vacuously.
