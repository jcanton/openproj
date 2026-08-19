# HackMD, observed

One screenshot, 2026-08-20, of a real note — `GridTools / Icon4py Tracer advection state` —
in the split view. jcanton's account is login-gated, so this is the first of several and the
rest arrive tomorrow. Everything below is read off the pixels. Nothing here is inferred, and
the things it does **not** show are listed at the bottom so nobody mistakes silence for
absence.

This file exists because the audit had to reason about HackMD's editor from documentation and
from HedgeDoc's source. Documentation describes the feature; a screenshot settles the shape.

## The view switcher is page chrome, not editor chrome

Three icons in a **segmented control**, top left of the page header, immediately right of the
workspace logo and before `+`, `?` and search: a **pencil** (edit only), a **split rectangle**
(edit and preview), an **eye** (preview only). One is selected and drawn as a pressed segment;
in this shot it is the split.

This contradicts where the plan put it. `2026-08-20-editor-plan.md` S2 places the tri-state in
the existing `bodybar` beside Preview, which is inside the editing surface. HackMD puts it in
the page's own header, next to the document's identity, because it is a property of how you
are looking at the document rather than of the text — the same argument this repository makes
for the width grip being remembered per browser and not per entity. Three adjacent icons that
look like one control also say "these are three states of one thing" in a way three separate
buttons in a row of unrelated controls do not.

## The toolbar is sixteen buttons in four groups

Left to right, with the separators where they actually fall:

| group | buttons |
|---|---|
| history | undo, redo |
| inline marks | **B**, *I*, ~~S~~, **H** |
| block marks | `</>` code, `""` quote, bullet list, numbered list, checkbox |
| insertables | link, image, table, horizontal rule, comment |

Four facts in that worth having:

- **Undo and redo are the first two buttons.** The plan adds `Y.UndoManager` in S4 and gives it
  no buttons. HackMD puts undo at the far left of the toolbar, which is where every editor
  puts it, and this repository has a live defect where `reflect()` wipes the native undo stack
  on every remote keystroke — so the button and the fix belong to each other.
- **Heading is one button, not a level picker.** `H` cycles or inserts; there is no H1/H2/H3
  dropdown to build.
- **Link, image and code all have buttons.** `d6997e3` cut the link button and the code-block
  button deliberately, on counts from the real corpus: 485 lines carry an inline code span and
  161 a bullet, against 8 markdown links and 2 fenced blocks. That decision was right for this
  team and it is in tension with "as close as possible to HackMD". The tension is jcanton's to
  resolve and it is question 1 below; the counts that would settle it are the ones S0 still
  owes.
- **Comment is a HackMD collaboration feature**, not markdown. There is nothing behind it here.

## The gutter carries two things, and the second one is the interesting one

Line numbers are right-aligned and muted. Beside them, a **green vertical stripe on every line
that has text** — lines 1, 3, 6–10, 13, 16–18, 22, 24–25 in this shot — and no stripe on the
blank lines between them. That is HackMD's per-line authorship marker: it says who wrote this
line, in that person's colour, and it persists after they have gone.

This repository's seat bands are a different thing wearing a similar coat. They draw a
translucent band on the line somebody's caret is **currently** in, and they vanish when that
person leaves. HackMD's stripe is a property of the **text**, not of the session.

For a tool whose whole premise is that one Save is one commit authored by whoever typed the
most, a per-line authorship stripe is the better of the two — it is `Room.credits` made
visible while you are still writing, rather than a fact you discover in `git log` afterwards.
It is not in the plan and it is not being built now. It is written down here so it is not
rediscovered.

## Logical line numbers survive soft wrap, which is the thing S3 has to get right

Line 17 — `advect(tracers((Field, config), size)) -> tracers((Field, config), size) {` — wraps
to **two visual rows** and the gutter shows **one number**, 17, aligned to the first row. The
next number is 18. This is exactly the behaviour S3 specifies, and the screenshot is now the
reference for it: number the logical line, position from the top of its first visual row.

## The rest of what the shot shows

- The editor pane is dark and the preview pane is light, in the same window. HackMD themes the
  editor independently of the page. This repository will not copy that: colours here are
  tokens defined in three blocks, and a pane that ignores the reader's theme is a value with
  its only definition inside a block half the readers never match.
- The body text renders in a **monospace italic**. It is a style choice, not information.
- The preview's code block **scrolls horizontally** rather than wrapping — there is a scrollbar
  under it and the long `advect(...)` line is clipped mid-word at the pane edge.
- The two panes scroll independently and are separated by a plain vertical divider, editor
  roughly 52% and preview 48%.
- Above the preview: the note's owner, a collaborator avatar, "Changed 13 hours ago", and a row
  of icons at the right — favourite, bookmark, subscribe, and a brush.
- The page header carries the workspace and the note title as a path (`GridTools / Icon4py
  Tracer advection state`), an info button, a tag button, the account avatar, a history button
  and Share.

## What this screenshot does not settle

It shows one view of one note, so none of the following is answered and none of it should be
guessed at until tomorrow's shots arrive:

- the settings dialog — indent type and width, keymap, spellcheck, theme, and whether the
  autosave interval is exposed there at all;
- the keyboard shortcuts, and which of them collide with the ones this page already claims;
- whether the two panes scroll-sync, which is a real HackMD feature and is in the plan on the
  strength of documentation alone;
- what edit-only and preview-only actually look like, as against the split shown here;
- the vim keymap in use;
- the presence UI when a second person is in the document;
- the outline/table-of-contents panel, find-and-replace, and revision history.

## The question this raises for jcanton

**How close is "as close as possible"?** HackMD's toolbar has link, image and code buttons that
this repository removed on measured evidence about how this team writes. Copying HackMD means
putting them back and overriding that measurement; keeping the measurement means the toolbar is
deliberately shorter than the one in the screenshot. Both are defensible and the plan can build
either. What it cannot do is guess, and S0 — the grep of the migrated corpus — is still the
thing that would answer it with a number rather than a preference.

🤖 Written by an agent on behalf of @jcanton
