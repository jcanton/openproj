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

## The second shot: the status bar, and the URL

A full-window shot of the same note, 2026-08-20. Two things in it are worth more than
everything in the first one.

### The view mode is a query parameter, and the spelling is HackMD's

The address bar reads `hackmd.io/ppDzW8W0QnmS2y8eFyU1Tw?both=`. So the mode is not a
client-side class; it is in the URL, which makes a view a link — the same rule this repository
already applies to a filtered table. The plan proposed `?edit` / `?both` / `?view` from
documentation and guessed right down to the word. Build those three spellings and no others.

### The editor's settings live in a bottom status bar, not in a dialog

The strip along the foot of the editor pane, left to right:

| item | what it is |
|---|---|
| `Line 1, Columns 1 — 100 Lines` | caret position, and the document's line count |
| a lightbulb | tips |
| a tick | spellcheck |
| a brush | editor theme |
| **`Spaces: 4`** | **indent type and width — ask 5, and it is a click target, not a dialog** |
| **`Breaks`** | whether a single newline renders as a line break |
| a keyboard glyph | **the keymap selector — ask 6's control** |
| `Length: 1369` | character count |

This is where asks 5 and 6 belong. S5 is already called "The preference, the status bar, and
the draft receipt", so the plan anticipated a status bar; it did not know what goes in one.
Now it does, and the answer is that HackMD exposes indent width and keymap as **two words in a
status bar** rather than as a settings screen — one click, no modal, the current value legible
without opening anything. `Spaces: 4` says what it is and what it is set to in two words.

The autosave interval is **not** there, which is worth stating: nothing in this strip is a
timer. Ask 7 being read as draft autosave with a visible receipt is consistent with what
HackMD actually shows, which is `Length` and a line count rather than a countdown.

### `Breaks` is a renderer setting and it is a real difference from this repository

HackMD lets a note choose whether one newline is a line break. `render.py:941` builds
`MarkdownIt("commonmark", {"html": False}).enable("table")`, and CommonMark's answer is no — a
single newline is a space. So a corpus written in HackMD with breaks on renders differently
here, and the difference is invisible in a diff: no character changes, the paragraphs just
join up. Nobody has checked whether the migrated notes rely on it. That is now the sharpest
reason to want the corpus, sharper than the toolbar question the first shot raised, and it is
a server-side one-word change (`{"breaks": True}`) rather than an editor feature.

### The gutter stripes are more than one colour

The full-height shot shows at least three: green on lines 1–26 and 47, a teal band across
33–44, amber on 48 onward. One colour per author, hue derived from the person, exactly as this
repository already derives a seat's hue from a login. It confirms the reading in the section
above — the stripe marks **who wrote each line** and persists after they leave — and it is
still not being built.

### Also visible

- Each pane has its own scrollbar and they are at different positions, so the panes are
  scrolling independently in this shot. That is not evidence against scroll sync — sync is
  usually driven by the pane with focus — but it is not evidence for it either, and the plan
  still rests on documentation for that one.
- A panel icon at the right of the preview's header, next to the brush, which is most likely
  the outline or table-of-contents toggle. Not confirmed.
- Line 17 wraps to two visual rows under a single gutter number, again.

## S0, answered. The whole corpus, counted — and it corrects the half-answer below

jcanton exported the team's HackMD workspace on 2026-08-20: **735 notes, 81,794 lines, 5.2 MB**,
every one of them carrying YAML frontmatter. The section after this one counted the 29 files that
had already been migrated into the plan repository and drew two conclusions from them. **One of
those conclusions was wrong**, and it is left standing below with this correction above it,
because a sample of 29 out of 735 producing a confident zero is the more useful thing to
remember.

### What people actually write

| construct | lines | notes |
|---|---|---|
| bullet | 17,640 | 676 |
| heading | 7,212 | 719 |
| inline code span | 6,312 | 588 |
| **task list `- [ ]`** | **5,297** | **330** |
| **fenced code block** | **2,960** | **261** |
| **markdown link** | **1,560** | **388** |
| **table row** | **1,530** | **69** |
| bold | 1,455 | 195 |
| hard break (two spaces) | 252 | 77 |
| strikethrough | 188 | 67 |
| image | 173 | 58 |
| PR reference `#1234` | 101 | 40 |
| blockquote | 74 | 25 |

**This settles the toolbar override, and settles it the other way round from how it was argued.**
`d6997e3` cut the link button and the code-block button on a count of **8** markdown links and
**2** fenced blocks. The real corpus has **1,560 links across 388 notes** and **2,960 fenced
blocks across 261 notes**. That commit's reasoning was sound and its sample was not — it counted
the seed corpus and the fraction of HackMD notes that had been migrated by then, which is the 29
files below. Every one of the fourteen buttons now shipping is backed by four figures in this
table. The override in `ba2cb72` was right, and it is no longer an override of a measurement; it
is a correction of one.

### The renderer gap, which the 29-file sample said did not exist

It does exist, and it is bounded: **640 of 735 notes (87%) render with nothing missing today.**
The other 95 need something this renderer does not have.

| missing | notes |
|---|---|
| raw HTML | 43 |
| math, `$…$` and `$$…$$` | 27 |
| footnotes `[^x]` | 15 |
| `[TOC]` | 14 |
| `:::` containers | 10 |
| `[name=]` / `[color=]` | 2 |
| image sizing `=200x` | 1 |
| `{%youtube%}`-style embeds | **0** |
| mermaid and other diagram fences | 0 outside code blocks |

Three things to say about that list.

**Raw HTML stays off, and 43 notes is not an argument to turn it on.** `render.py:941` sets
`{"html": False}` and that is a security decision with a history: one line of markdown in a plan
anybody can write to became a tracking pixel aimed at everyone who opened it, and it survived into
the static export where there is no origin to appeal to. Allowlists, not denylists. Those 43 notes
show their tags as text, which is visible, recoverable and correct.

**Embeds are zero**, which retires a whole class of work nobody now has to think about.

**Math is the one worth a decision later** — 27 notes, and it is the only entry here whose absence
is silently misleading rather than obviously literal: `$\alpha$` renders as `$\alpha$`, which
reads as a typo rather than as a missing feature. KaTeX is another vendored library and another
byte conversation, and it is not this work.

### `Breaks`: both behaviours are in the corpus, and CommonMark is the lesser harm

2,433 places across 369 notes — half the corpus — have one prose line directly under another,
which is exactly the case `breaks: true` changes. Splitting them by the width of the first line
says what the author meant:

- **1,632 have a first line of 70 characters or more, median 87.** Hard-wrapped prose. The author
  wrapped a sentence at their editor's width and expects it to reflow. `breaks: true` renders
  these as a ragged paragraph broken at column 87 — at the *author's* width, not the reader's,
  which on a narrow screen is a mess.
- **801 have a first line under 70 characters**, and reading them they are deliberate:
  `**File:** …` above `**Status:** VERIFIED`, `Notes:` above `OSM view:`. These want a line break
  and CommonMark joins them onto one line.

So neither setting is right for the whole corpus, and the question is which harm is smaller. It is
CommonMark's, by a two-to-one ratio and by kind: 801 label pairs that read as one slightly-run-on
line are recoverable, while 1,632 paragraphs broken at somebody else's window width look broken.
**The renderer stays CommonMark.** The 801 are a known migration artifact and are written down
here as one; they are not repaired by a pass that rewrites people's text, because a save that
reformats somebody's file is the thing that stops "edit it in git if you prefer" from being true.

Note the corroboration: **77 notes already use the explicit two-space hard break**, 252 times. The
people who wanted a line break and knew how to ask for one asked for it in the portable way.

## S0's first half, superseded above: the migrated corpus, counted

`~/projects/icon4py-plan` is the plan repository — the notes already migrated out of HackMD into
records. It is **part** of the corpus, not all of it; the rest is still in HackMD behind a login.
29 files, 1,090 lines, at `e5dde0e`. Counted 2026-08-20:

| construct | lines |
|---|---|
| heading | 123 |
| bullet | 103 |
| task list `- [ ]` | 26 |
| inline code span | 26 |
| markdown link | 18 |
| fenced block | 6 |
| bold | 2 |
| `[TOC]`, `:::info`, `> [name=`, `{%youtube%}`, `[^fn]`, `$math$`, mermaid fence, `![... =200x]`, table row, raw HTML | **0 each** |

Two things follow, and both are decisions rather than curiosities.

**No HackMD extension appears anywhere.** Not one container, embed, footnote, formula, diagram or
sized image. So the renderer batch owes this corpus no HackMD-specific feature, and the version of
that work carried on the seed counts was carrying the right answer for the wrong reason. If the
un-migrated half contradicts this it will do so loudly — these are constructs you notice.

**Task lists and links are real, and the toolbar was right to gain them.** 26 lines carry a
checkbox and 18 carry a markdown link, against the 8 links `d6997e3` counted when it cut the link
button. The override recorded in `ba2cb72` now rests on a number rather than only on a request.

### `Breaks` is answered for this half, and the answer is no

57 places have one prose line directly under another — the case CommonMark joins into one
paragraph and `breaks: true` would separate. Reading them settles what they are: **hard-wrapped
paragraphs.** `README.md:3` is one sentence wrapped across two lines at about column 90, and so
are the rest.

So `{"breaks": True}` would be actively wrong here. It would not restore anyone's intent; it would
split every wrapped sentence mid-line, 57 times in the migrated half alone. **The renderer stays
CommonMark**, written down so it is not revisited as an obvious improvement.

The caveat is real. This half is hard-wrapped because it was written into files by people using
editors that wrap at 90 columns. Notes still living in HackMD are written in a soft-wrapping
editor where `breaks` is on by default, and the screenshot shows exactly that style — line 17 is a
single logical line the editor wraps for display. Those notes may hold consecutive short prose
lines that do rely on it. Until the other half is counted, the finding is "no for what has been
migrated", not "no".

### How the rest of the corpus can be counted

A link to one note cannot answer a question that is a count across many, and
`hackmd.io/ppDzW8W0QnmS2y8eFyU1Tw?both=` is gated to anything without jcanton's session — fetched
2026-08-20, it returns the login page.

The route already exists here. `docs/probes/hackmd_probe.py` speaks the HackMD API, and its
`inspect` phase already lists a team's notes:

    GET /teams/<team>/notes         -> every note's id
    GET /teams/<team>/notes/<id>    -> that note's `content`

One token — hackmd.io, settings, API, new token — exported as `HACKMD_TOKEN` makes the whole
corpus countable in a single read-only pass, with the same greps as the table above and no note
written to. That is the cheapest thing that finishes S0.

## The third shot: the team overview, which is where a person lands

One screenshot, 2026-08-22, of `hackmd.io/team/gridtools?nav=overview` — the page HackMD opens
on. It arrives because openproj is replacing the table as its own landing page, and "something
like it's done in hackmd" needed pixels rather than a memory of them.

**It is a card grid by default, not a list.** Two icons at the top right toggle between them and
the grid is the one selected in the shot, so the list exists and is not what a person gets
without asking. jcanton asked for a list; that is a departure from what HackMD does and not a
copy of it, and it is the right departure — a card is mostly whitespace, and the thing openproj
has that HackMD has not is a *kind*, which is one short word and wants a column rather than a
card.

**A card carries four things and no more**: a document icon, a globe when the note is published
and a pin when it is pinned, the title, and one date. No author, no tags, no excerpt, no size.
The count of what is absent is the finding — this is the most reduced surface in the product,
and it is the one people live on.

**The date is relative when it is recent and absolute when it is not.** Read straight off the
pixels, in one column, top to bottom: `17 hours ago`, `19 hours ago`, `20 hours ago`,
`A day ago`, `3 days ago`, `10 days ago`, and then `2026-07-08`, `2026-05-26`, `2024-06-21`,
`2024-02-08`. So there is a threshold somewhere past ten days, and past it the relative form is
abandoned rather than extended — nobody is shown "2 years ago". The shot does not settle where
the threshold falls; it settles that there is one, and that the answer to "how long ago" stops
being useful before the answer to "when" does.

**Sorting and grouping are two controls, not one.** There is a `Sort` dropdown, and separately
the body is cut into labelled sections — `Pinned 3`, then `cycle 38 09/26 6`, then
`Untagged 79` — each with its own count. So the grid is grouped by tag with a sort inside the
groups, which is a different thing from the flat most-recent-first list jcanton asked for. Worth
knowing that the product this is modelled on found a flat list insufficient at 88 notes; worth
knowing too that it needed a `Tags` dropdown, a tag list in the sidebar with per-tag counts, and
folders to get there. openproj has a query language instead, and `tag:gpu and tag:distributed`
is the thing the sidebar cannot express.

**The search box is in the sidebar, above everything, and it searches keyword or tag** — one box
for both, which is the shape openproj's own box already has.

What this shot does not settle: where the relative/absolute threshold falls; what the list view
looks like; whether the date is created or last-modified (HackMD's sort menu has both, and the
shot does not show which is selected).

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
