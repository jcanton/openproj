"""The CSS more than one page inlines, and the colour tokens under it."""

from __future__ import annotations

from ..themes import FAMILIES, contrast

# Which hue each status wears. The one place taste enters the derivation: the
# format's eight hues are red, orange, yellow, green, cyan, blue, magenta, brown,
# and these six choices are the app's own palette read back into them — cyan for
# thinking, violet for shaping, blue for ready, orange for in progress, green for
# done, and the ground's own grey for shelved, which is not a hue because shelved
# is not a state anything is happening in.
#
# `thinking` is not a state anything is happening in either, and that is the
# argument that was weighed here and lost. Grey is what "nothing is happening"
# already wears, and the ladder's whole job is to tell states apart: the ground
# ramp's free slots are base03's own neighbours, so a second grey status would be
# two steps of one grey in most of these palettes and unreadable against
# `shelved` in several. The two words also do not mean the same thing — `shelved`
# is out of the plan and nothing WILL happen; `thinking` is the first rung of it
# and something is about to. So it takes a hue, and cyan is the one it already
# had: `thinking` has worn `--accent`, which is a teal, on the hill ball and the
# hover chip since before it was a status, and base0C is that hue in this format.
# Red is `--danger`'s and yellow is one step from `in_progress`'s orange, which
# left cyan and brown, and brown is the slot base16 schemes agree on least.
STATUS_SLOTS = (
    ("thinking", "base0C"),
    ("shaping", "base0E"),
    ("ready", "base0D"),
    ("in_progress", "base09"),
    ("done", "base0B"),
    ("shelved", "base03"),
)

# How much contrast a page needs from a palette meant for a terminal. The ink is
# held to AAA against its own background, the secondary ink and the link to AA —
# and the link only to 3.5, because Solarized's blue on Solarized's cream is 4.3
# and refusing Solarized over a tenth of a step is refusing the scheme half the
# people who asked for this feature meant by it.
_INK_FLOOR = 7.0
_MUTED_FLOOR = 4.5
_LINK_FLOOR = 3.5


def _chosen(slots: dict[str, str]) -> dict[str, str]:
    """The three values a palette cannot be trusted to place, chosen by contrast.

    base05 is what the format calls the default foreground, and a scheme written
    for a terminal is free to make it a colour that has never had a paragraph set
    in it — Material Lighter's is a teal at 1.8:1 against its own background,
    which is why that family is not offered at all. So the ink is whichever
    ground slot is furthest from the background rather than whichever one the
    spec names, the secondary ink is the closest slot that still clears AA, and
    the link is the first hue that clears the floor.

    Measured here and asserted in `tests/test_themes.py`, against every palette,
    so a family added later cannot arrive unreadable.
    """
    ground = ("base07", "base06", "base05", "base04")
    ink = max(ground, key=lambda slot: contrast(slots[slot], slots["base00"]))
    darkest = contrast(slots[ink], slots["base00"])

    quieter = [
        slot for slot in ("base04", "base03", "base05", "base06")
        if _MUTED_FLOOR <= contrast(slots[slot], slots["base00"]) < darkest
    ]
    # The quietest of the ones that are still legible: a secondary ink that
    # matches the primary is a hierarchy with one level in it.
    muted = min(quieter, key=lambda slot: contrast(slots[slot], slots["base00"]),
                default="base04")

    link = next(
        (slot for slot in ("base0D", "base0C", "base0E", "base0B", "base08")
         if contrast(slots[slot], slots["base00"]) >= _LINK_FLOOR),
        "base0D",
    )
    return {"fg": ink, "muted": muted, "accent": link}


def _slot_css(palette) -> str:
    """One palette as custom properties: the sixteen, and the three picks."""
    slots = palette.slots
    lines = [f"  --{slot}: {value};" for slot, value in slots.items()]
    for token, slot in _chosen(slots).items():
        lines.append(f"  --{token}: var(--{slot});")
    return "\n".join(lines)


def _scheme_css() -> str:
    """Every family, in the three states a theme choice can be in.

    The same three the app's own palette is written in and for the same reason:
    an explicit choice stamps `data-theme`, and the default — no attribute at all
    — follows the system. A scheme has to answer all three or a reader who has
    never touched the switch gets a light palette on a dark desktop.
    """
    blocks = []
    for family in FAMILIES:
        light, dark = _slot_css(family.light), _slot_css(family.dark)
        blocks.append(
            f':root[data-scheme="{family.key}"] {{\n  color-scheme: light;\n{light}\n}}'
        )
        blocks.append(
            "@media (prefers-color-scheme: dark) {\n"
            f'  :root[data-scheme="{family.key}"]:not([data-theme="light"]) {{\n'
            f"    color-scheme: dark;\n{dark}\n  }}\n}}"
        )
        blocks.append(
            f':root[data-scheme="{family.key}"][data-theme="dark"] {{\n'
            f"  color-scheme: dark;\n{dark}\n}}"
        )
    return "\n".join(blocks)


# The scroll-and-freeze mechanism, shared by the pages that draw one full-width
# record table under the control bar — the plan's table and the records list.
# One copy because it is one invariant: the body scrolls inside `.table-scroll`
# while `thead th` holds against it, and a second spelling of that pair is how
# the two pages would drift the first time either was tuned.
#
# Every selector here is deliberately the lightest that can reach its cells —
# bare elements, (0,0,1) and (0,0,2) — so a page that includes this block can
# correct any of it with a single class or attribute. The table page does
# exactly that (`th.sorted`, `[data-col=…]`, `.scrolled td[…]`); what it must
# never do again is qualify a correction so far that it outranks the OTHER
# corrections — the `.table-scroll [data-col=…]` story told above `[data-col]`
# below.
_SCROLL_STYLE = """
/* The table body scrolls in here rather than in the page. `position: sticky` on
   a header needs a scroll container to hold against, and a container the height
   of its own content gives `top: 0` nothing to do.
   `max-height` and not `height`: three rows are three rows, and a table stretched
   to the window with 400px of nothing under the last one is a table that looks
   like it failed to load the rest. The graph's canvas is the other case — it has
   no size of its own — and it takes the same measurement as a `height`.
   That measurement used to be `100vh - 15rem`, a hand-count of the stack above
   the rows written down as a constant, and it had already been wrong once: the
   page gained a heading and the box ran past the bottom of the window. It is
   measured now, in the shell, and the same number answers the graph and the
   timeline.
   The overflow used to cut off the suggestion popups the cells open, on this
   table and on any table that borrowed the class; `attachSuggest` parks its list
   on the body now, so an ancestor's overflow no longer reaches it. */
.table-scroll { overflow: auto; max-height: var(--room);
                min-height: 9rem; overscroll-behavior: contain; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td {
  border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left;
  /* Border-box, or a width set from a measured box gains the padding again and
     every column grows by exactly one cell's worth on the first drag. */
  box-sizing: border-box;
  /* A PR reference has no space in it, so at a narrow width it hangs over the
     next column instead of wrapping inside its own. */
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 400;
     text-transform: uppercase; letter-spacing: .04em; font-size: 11px; }
thead th {
  position: sticky; top: 0; z-index: 3; background: var(--surface);
  /* A collapsed border is not painted on a sticky cell — the first row scrolls
     straight over the top of it — so the rule is drawn inside the box instead. */
  box-shadow: inset 0 -1px 0 var(--line);
}
"""


_SUGGEST_STYLE = """
/* Absolute against the page, not against the cell it belongs to: `attachSuggest`
   parks the list on the body and writes its `top` and `left` in page
   coordinates. As a child of its own cell it was clipped by `overflow` on any
   ancestor — the table's rows scroll inside `.table-scroll` — and trapped in the
   stacking context of a sticky frozen column. Nothing on the page carries
   `position: relative` for this any more; there was such a rule, `dd, td.edit`,
   and it was also stealing `position: sticky` from the table's title column. */
.suggest { position: absolute; z-index: 20; margin: 0; padding: 0; list-style: none;
           background: var(--surface); border: 1px solid var(--line-strong);
           border-radius: 3px; min-width: 14rem; max-height: 16rem; overflow-y: auto;
           box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.suggest li { padding: .25rem .5rem; cursor: pointer; }
.suggest li.on { background: var(--accent); color: var(--on-accent); }
textarea.dropping { outline: 2px dashed var(--accent); outline-offset: -2px; }
/* `flex: none`, and it is the whole of what keeps the toolbar on one row. The
   bar is a flex line the toolbar shares with a status message, and a flex item's
   default `min-width: auto` still lets it shrink to its content — so the marks
   resolved to 430.9px where the fourteen buttons and their two rules need 482.8,
   and wrapped, with the break falling inside the third group and no rule in
   front of the two buttons that landed on the second row. Measured in Chrome at
   1000, 1200, 1440 and 1920 CSS px: two rows at every one of them. The message
   beside it takes the shrink instead, which is the right way round — it is a
   sentence and it can wrap. `flex-wrap` stays as the answer to a window narrower
   than the toolbar itself, where wrapping beats a scrollbar. */
.marks { display: inline-flex; gap: .15rem; align-items: stretch; flex-wrap: wrap;
         flex: none; }
/* And the window the toolbar does not fit in, where `flex: none` is the wrong
   answer and `flex-wrap` above cannot engage without this.

   `0 0 auto` pins the bar at its max-content width whatever the window, so the
   wrap never happens: measured in Chrome at 500px on /detail while editing, on
   /new and on the since-deleted /note/new and /issue/new, the Link, Image,
   Table and Horizontal-rule
   buttons sat 101px past the right edge of `article.record` — off the surface,
   reachable only by scrolling the whole document sideways, which is also what
   took that page's `scrollWidth` to 581.

   **`min-width: 0` is not needed here, and the fix this was written from said it
   was the load-bearing half.** Measured both ways: `flex: 0 1 auto` alone gives
   the same four widths the same answer. A flex item's automatic minimum size is
   its MIN-CONTENT size, and the min-content size of a container that wraps is
   its widest single item — one button, about 40px — not the whole bar. The
   declaration would be inert, and an inert declaration under a comment calling
   it load-bearing is the next reader's wasted hour.

   `@media` and not `@container`, and that is measurement rather than taste: this
   rule was proved at eight widths as a media query, in the days when the issue
   and note pages loaded a stylesheet with no `container-type` in it and a
   container query measured byte-identical to no fix at all on /note/new. Those
   pages are gone and every editor now sits in `article.record`, which IS a
   container — but re-cutting this as a container query is a re-measurement at
   eight widths on the merged page, not an edit.

   40rem and not the 34rem this was first written for: that number was measured
   against fourteen buttons needing 482.8px, and the history group made it
   sixteen needing 561px. Swept in Chrome at eight widths on both surfaces:
   unpatched, the overhang is 101px at 500, 41px at 560 and gone by 620; patched,
   the bar is on two rows to 616 and back on one at 624. The query has to reach
   past both numbers, and between 624 and 640 it applies and does nothing —
   `flex-shrink` only shrinks an item there is not room for. */
@media (max-width: 40rem) {
  .marks { flex: 0 1 auto; }
}
/* The line between one group of marks and the next. `align-self: stretch` so it
   is the height of the buttons rather than of the text inside them. */
.marks .sep { width: 1px; background: var(--line); margin: 0 .3rem; align-self: stretch; }
/* What is left after the shell's rule, and every line of it is DENSITY rather
   than style. The corner is gone from here: 3px was this bar's own, jcanton
   preferred it to the app's 2px, and the app moved — so keeping a copy of it
   here would be an exception about a number that is no longer exceptional.
   `min-width`, the padding and the 12px are what fit sixteen buttons on one row
   above a document; `var(--line)` and `var(--muted)` in place of the default's
   `--line-strong` and `--fg` are the same argument in ink — sixteen controls at
   full contrast would shout over the writing they sit on. */
button.mark {
  font-size: 12px; line-height: 1; min-width: 1.9rem; padding: .3rem .35rem;
  border-color: var(--line); color: var(--muted);
}
button.mark:hover { border-color: var(--accent); color: var(--accent); }
/* The history group. A drawing has no baseline to sit on, so the box centres it
   the way `.draft-do` centres the check and the cross rather than padding it
   like a word. */
.marks .hist { display: inline-flex; align-items: center; justify-content: center;
               line-height: 0; }
/* An SVG nothing sizes lays out at 0x0, and this application has shipped that
   twice. 13px against the 12px letters beside it, because a stroked outline
   reads a shade smaller than a glyph in the same box. */
.marks .hist svg { display: block; width: 13px; height: 13px; }
/* **Empty says so**, which is the failure mode this group was held back for.
   `:hover` is named explicitly because `button.mark:hover` is (0,2,1) and would
   otherwise beat a bare `button.mark:disabled` at (0,2,1) on order alone and
   light up a control that will not act; `button.mark:disabled:hover` is (0,3,1)
   and wins outright — resolved with `tests/cascade.py`, not guessed at. */
button.mark:disabled, button.mark:disabled:hover {
  cursor: default; background: var(--surface-2);
  border-color: var(--line); color: var(--muted); opacity: .45;
}
.doc img { max-width: 100%; height: auto; }
/* A table in a shaping document. Tables have parsed since the day `_MD` was
   given the rule, and drew as four words in a row with no lines anywhere —
   which nobody had to look at until the toolbar gained a button that writes one.
   Here and not beside `_DETAIL_STYLE`'s other `.doc` rules because this
   stylesheet is loaded by the table, the cycle page and the record page in both
   modes (grep `_SUGGEST_STYLE` in the `_page` calls) — which is what kept this
   at one copy while the record pages still carried a `.doc` sheet of their own,
   and is still the reason a second copy would be a place for two pages to
   disagree about what a table is.
   A rule under the headings and a hairline between rows: a full grid is a
   spreadsheet, and what a reader needs is to see where a row stops.
   Resolved with `tests/cascade.py` rather than guessed at, because this
   stylesheet is also loaded by the plan's table, whose own sheet carries a bare
   `th`: `.doc th` is (0,1,1) against that (0,0,1) and wins every property
   declared here, and the table page has no `.doc` on it for the rest of that
   bare rule to reach. */
.doc table { border-collapse: collapse; margin: 0 0 1rem; font-size: 13px; }
.doc th, .doc td { text-align: left; vertical-align: top; padding: .25rem .9rem .25rem 0; }
.doc th { border-bottom: 1px solid var(--line-strong); font-weight: 600; }
.doc tbody tr + tr td { border-top: 1px solid var(--line); }
/* And the rule the toolbar's other new button writes. Chrome's default `hr` is
   a 1px INSET border, which the dark theme renders as a bright bar heavier than
   every other separator on the page — a divider that shouts is a divider that
   reads as a heading. */
.doc hr { border: 0; border-top: 1px solid var(--line-strong); margin: 1.4rem 0; }
.suggest .dim { opacity: .6; }
.suggest li.on .dim { opacity: .85; }
"""


# The editing surface, in one place, because it was once drawn twice. Before the
# record pages folded into `_DETAIL`, `_ISSUE` and `_NOTE` put the mode class on
# `<body>` and kept their own copies of `.bodybar` and `.body-field` — so the
# toolbar, the box and the two bars either side of it were two declarations of
# one thing, and only one of them ever got a fix: the note page had the hill and
# the issue page a bare `<select>`, in the same commit, by the same author. That
# is what a second surface does, and it is why there is no second surface.
#
# **Which way the unification went was decided by a structural fact, not a
# preference.** The detail template is rendered once per record and the static
# export puts every record in ONE document, so "is this being edited" is a
# property of an article and cannot be a class on `<body>`. This block is
# written against `.record.editing` once.
#
# Concatenated at the END of the stylesheet, and that is load-bearing rather
# than tidy. `textarea.body-field` and `textarea.field` are both (0,1,1), and
# `input.field, select.field, textarea.field { font: inherit }` in `_DETAIL_STYLE`
# sets the same two properties the declaration below does — so at the front of
# the sheet the box would resolve to the page's sans face while the column of
# line numbers beside it stayed monospace, which is ask 4 broken by a stylesheet
# reordering. Resolved with `tests/cascade.py` rather than guessed at.
_EDITING_STYLE = """
.bodybar { display: none; gap: .6rem; align-items: baseline; margin: 1rem 0 .3rem; }
/* The second row sits under the first rather than a paragraph's worth away: they
   are two halves of one bar, and the box they belong to is below both. */
.bodybar.markbar { margin-top: .25rem; }
.record.editing .bodybar { display: flex; }
.record.editing .field[hidden] { display: none; }
/* One declaration for the box and for the numbers beside it. Written twice, the
   gutter walks out of step with the lines it names by a pixel a line, which is
   invisible at the top of a document and half a row down at the bottom of one —
   and an invariant written twice is an invariant guarded once. */
/* The seat layer is in the list because `--gutter` is written in `ch`, and `ch`
   is resolved by whoever USES the value: the column and the box's padding both
   resolve it in this face, and `.bodywrap.numbered .seat { left: var(--gutter) }`
   was resolving the same token in the page's sans face and starting the bands a
   pixel to the right of the text they sit behind. */
textarea.body-field, .gutter, .seats { font-family: var(--font-mono);
                                       font-size: 13px; line-height: 1.55; }
/* And `width: 100%` means the box, not the box plus its padding and its border.
   The detail page got this by accident, off `input.field, select.field,
   textarea.field`; the record pages had no such rule, so their `width: 100%`
   textarea was content-box and hung 29px past the container it was in — visible
   the moment that container became a pane of a split rather than a column with
   room to spare. */
textarea.body-field { box-sizing: border-box; }
/* Ask 4. The column is the box's own left padding, so the numbers sit in space
   the text has already been kept out of rather than over the top of it — which
   also means the mirror that measures the lines is measuring the same content
   box the reader is looking at, because it copies the padding.
   `--gutter` is set from the page, in `ch` of this face, so the column is as
   wide as the widest number and no wider. */
.gutter { position: absolute; left: 0; top: 0; bottom: 0; width: var(--gutter, 0);
          overflow: hidden; pointer-events: none; color: var(--muted);
          text-align: right; }
.gutterrows { position: absolute; left: 0; right: 0; top: 0; }
.lineno { position: absolute; right: .45rem; }
.bodywrap.numbered textarea.body-field { padding-left: var(--gutter); }
/* And the bands start where the text does. A band that runs under the numbers
   tints them with somebody else's colour, which reads as the gutter belonging to
   whoever is in the room. */
.bodywrap.numbered .seat { left: var(--gutter); }
/* Asks 5 and 7, and the two facts either side of them: the strip along the FOOT
   of the box, which is where the note this is modelled on puts them. Under the
   box and not above it, and that is the whole reason there are two bars rather
   than one — the toolbar is what you reach for while writing a line and belongs
   above the line; where the caret is and how long the document is are things you
   look down at, and a row of numbers between the toolbar and the text is a row
   between a control and the thing it controls.
   Smaller than the toolbar and in the muted ink: everything in it is a fact
   about the document rather than an instruction, except the two pickers, which
   earn their weight by being the only things in the row that respond to a
   press. */
.statusbar { margin: .25rem 0 0; font-size: 11px; color: var(--muted);
             flex-wrap: wrap; }
.stat { white-space: nowrap; }
/* A picker that looks like the words beside it until you point at it. `Spaces:
   2` is a value that states itself and is its own click target; drawing it as a
   button with a border would make it the loudest thing in a row of quiet facts,
   which is backwards — it is a setting somebody changes twice a year. So this is
   the shell's default declined on purpose, and declining it is what `background:
   none; border: 0` under a class means: the class outranks the element selector,
   which is why the exception can be made here rather than by editing the rule. */
button.stat.pick { font: inherit; color: inherit; background: none; border: 0;
                   border-radius: 3px; padding: 0 .15rem; cursor: pointer; }
button.stat.pick:hover { color: var(--accent); }
/* Over the ceiling. The one thing in this row that is not a fact but a refusal
   waiting to happen, so it is the one thing drawn in the colour of a refusal —
   and the word is in the element too, because a colour on its own is a channel a
   dichromat does not have. */
.stat.over { color: var(--danger); font-weight: 600; }
.bodywrap { position: relative; }
/* Three states of one thing, drawn as one control: adjacent segments inside a
   single bordered box, the pressed one filled. Visible outside a session as
   well as in one, because the segments ARE the door in: `edit` and `both`
   open the session they are views of, and a door drawn only inside the room
   it opens is not a door. A reader the server would refuse a write from gets
   no bar at all — `_viewbar` decides that — so there is no rule here for a
   page that should not have one. */
/* No `overflow: hidden`, and that is a correction rather than a simplification.
   The shell's focus ring is `outline: 2px solid var(--focus)` at `outline-offset:
   2px`, drawn entirely OUTSIDE the segment's border box, and the segments fill
   this container's padding box exactly — so clipping the container clipped the
   ring away on every side. Pixel-diffed against the unfocused shot: 6 differing
   pixels on the first segment, against 404 for Save on the same page. The
   corners the clip existed for are given to the end segments instead. */
.views {
  display: inline-flex; vertical-align: middle;
  border: 1px solid var(--line-strong); border-radius: 3px;
}
/* The one place in the app where a control does NOT wear the shell's rectangle,
   and it says so here because that rule is the default and an exception has to be
   argued where it is made. A segment is not a button that happens to be next to
   two others: the three are one control, the group above draws the one rectangle
   they share, and giving each segment its own would put a doubled border down
   every join. So `border: 0` here, and the corners below are the group's inner
   radius — 3px outside minus the 1px border it is inside of.

   `border-radius: 0` on the segment itself and not merely on the middle one: the
   shell's rule reaches every button, so a segment that declared nothing took the
   app's corner, and the middle of three came out with three rounded pixels at
   each end. Nothing was visible until a segment was pressed, at which point the
   accent fill pulled away from its neighbours and left the group's ground showing
   through four notches. */
.views .seg { font: inherit; line-height: 0; padding: .3rem .55rem; border: 0;
              border-radius: 0; cursor: pointer;
              background: var(--surface); color: var(--muted); }
.views .seg:first-child { border-radius: 2px 0 0 2px; }
.views .seg:last-child { border-radius: 0 2px 2px 0; }
/* And above its neighbours while it has the ring: the segments are adjacent, and
   a later sibling's background paints over the two pixels of ring that reach it. */
.views .seg:focus-visible { position: relative; z-index: 1; }
.views .seg + .seg { border-left: 1px solid var(--line); }
.views .seg:hover { color: var(--accent); }
.views .seg[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
/* An SVG that nothing sizes lays out at 0x0, and this application has already
   shipped two empty boxes where a check and a cross should have been. Sized
   here, drawn in `currentColor`, so a pressed segment's icon is the ink the
   segment sets and not a colour of its own. */
.views .seg svg { display: block; width: 15px; height: 15px; fill: none;
                  stroke: currentColor; stroke-width: 1.6;
                  stroke-linecap: round; stroke-linejoin: round; }
/* Which editor, beside which view — a switch and not a fourth segment, because
   it is a different question: the segments are one control with three states,
   this is two states of a setting. It wears the same rectangle as the group next
   to it by saying NOTHING about border, ground or corner — the shell's `button`
   rule is the app's one look, and a control that wants the default says so by
   not overriding it. Only the arrangement inside that rectangle is here.

   Hidden until the article is editing, like the segments: a choice of editing
   surface is nothing at all when there is no editing surface. */
.eswitch { display: none; }
.record.editing .eswitch { display: inline-flex; align-items: center; gap: .4rem;
                           vertical-align: middle; color: var(--muted); }
.record.editing .eswitch:hover { color: var(--accent); }
/* Every colour here resolves a token already defined in all three blocks, so
   there is no new value that could be right in one and wrong in another — the
   failure that rule exists to prevent. `--line-strong` off, `--accent` on, and
   the knob takes the ink that is legible on each. */
.eswitch .etrack { display: block; width: 26px; height: 14px; border-radius: 7px;
                   background: var(--line-strong); flex: none; padding: 2px;
                   box-sizing: border-box; }
/* No transition on the knob, and it was written and then taken out again rather
   than left in. A switch normally animates because it flips in place; this one
   never flips in place at all — its resting position is rendered by the server
   and the only thing that changes it is a page load, so the travel a transition
   would smooth is travel that never happens. The one move it does make is the
   half-step below, and that one has to be instant: it is the acknowledgement of
   a press, and an acknowledgement racing a navigation is one nobody sees. */
.eswitch .eknob { display: block; width: 10px; height: 10px; border-radius: 50%;
                  background: var(--surface); }
.eswitch[aria-checked="true"] .etrack { background: var(--accent); }
.eswitch[aria-checked="true"] .eknob { background: var(--on-accent);
                                       transform: translateX(12px); }
/* Pressed, and going. The knob stops HALFWAY rather than arriving, because
   halfway is what is true — this page will never be the page with the other
   editor in it, and the one that is has not landed yet. `aria-busy` says the
   same thing to a screen reader and `announce` says it in words. */
.eswitch.waiting .eknob { transform: translateX(6px); }
.eswitch.waiting { opacity: .55; }
/* The three page-chrome controls, while they are lodged on the surface rather
   than in the nav they came from. `showView` puts them in the surface's first
   row — the back link's — so that they stay in the top-right corner of the
   window, which is the only thing about their position anybody has learnt.
   `.corner` brings its own `margin-left: auto`, which is what pushes them to the
   far end here exactly as it does in the nav; what it does not bring is a row to
   be pushed along, because `.back` is a paragraph with one link in it. Hence the
   flex, and hence `min-width: 0` — a `<select>` is as wide as its longest option
   and would otherwise refuse to give the link its room back.

   13px and not the 12px `.back` sets, because these are the same three controls
   as the nav's and the nav is 13px. A control that changes size when it moves
   reads as a different control.

   `.editbar` keeps the rule as the fallback `showView` falls back to: it appends
   to `.back` if there is one, and every record page has one today. */
article.record.full > .back { display: flex; flex-wrap: wrap; align-items: center;
                              gap: .35rem 1rem; min-width: 0; }
article.record.full > .back > .corner,
.editbar > .corner { margin-left: auto; padding-left: .6rem; font-size: 13px; }
/* Ask 3, and ask 1 inside it: the writing surface fills the window, and the two
   panes scroll on their own.
   `position: fixed` rather than a taller box, because the page behind it — the
   nav, the banner, the reading measure — is not part of writing, and because a
   surface that is exactly the window cannot be scrolled past. z-index 15 is
   argued rather than picked: it clears the page (nothing else on it is
   positioned above 10) and stays under the suggestion list and the hover card at
   20, both of which are parked on `<body>` and would otherwise be painted behind
   the surface that opened them. The width handle is 30 and is hidden here; see
   `place`. */
body.fullpage { overflow: hidden; }
article.record.full {
  position: fixed; inset: 0; z-index: 15; overflow: hidden;
  width: auto; max-width: none; margin: 0; padding: .6rem 1.25rem 0;
  background: var(--bg);
  display: flex; flex-direction: column;
}
/* `min-height: 0` at every level between the surface and the panes, and it is
   the whole of what makes them scroll instead of the page. A flex item's default
   `min-height: auto` is its content, and a four-hundred-line textarea's content
   is taller than any window — so without these the box grows past the bottom of
   the screen and takes the commit bar with it. */
article.record.full > form { flex: 1 1 auto; min-height: 0;
                             display: flex; flex-direction: column; }
article.record.full > .commitbar { flex: none; }
/* `align-items: stretch`, against the container query that sets `start`: outside
   full page the facts are a short column beside a long document and should not
   be stretched to its height; inside it, a pane that is its content's height is
   a pane that overflows the window. The at-rule adds no specificity, so this
   (0,3,1) wins wherever both apply. */
/* The floor on that row, and the `order` below it, are one fix and it is worth
   saying what went wrong. Below the container query the panes are ONE column and
   `.facts` comes first in the markup, so the facts took the explicit
   `minmax(0, 1fr)` row and the document got the implicit `auto` one — and a
   `height: 100%` box in an auto row is a box the size of its `rows` attribute.
   Measured in Chrome at every width from 900px down, in all three views and on
   both surfaces: the writing box was 50px, two lines, with six hundred pixels of
   metadata above it. Full page is the feature this branch is for and under
   ~960px of window it was a dead end.
   `1fr` alone could not have fixed it: `fr` distributes FREE space, and the
   facts' auto row leaves 60px of it. So the row gets a floor as well — `min()`
   rather than a flat `30rem`, because on a window shorter than that the floor
   would push the commit bar off the bottom, and a pane the height of the window
   is the honest answer there.
   And `grid-auto-rows: max-content` for the row the facts then land in. It only
   exists in the stacked case, so it is inert in the two-column one; without it
   the facts drew as a 59px box with fifteen fields scrolling inside it, because
   `overflow-y: auto` on that pane makes its automatic minimum size zero and an
   `auto` track with no space left gives it exactly that. `.panes` is the
   scroller here, so the facts get their whole height one flick below the
   document rather than a scrollbar of their own inside three lines. */
article.record.full .panes { flex: 1 1 auto; min-height: 0; overflow: auto;
                             align-items: stretch;
                             grid-template-rows: minmax(min(30rem, 100%), 1fr);
                             grid-auto-rows: max-content; }
article.record.full .panes > .facts { min-height: 0; overflow-y: auto; }
/* `order: -1` so the document takes that row and not the facts. It changes
   nothing in the two-column case — the container query places BOTH panes
   explicitly, at `grid-row: 1`, and `order` has no say over an item that is
   definitely placed — and everything in the stacked one, where both are
   auto-placed in modified document order. Reordering here rather than reversing
   the markup, because the markup order is the reading order of the page outside
   full page and the facts lead it there on purpose. */
article.record.full .panes > .main { min-height: 0; display: flex; flex-direction: column;
                                     order: -1; }
article.record.full .bodysplit { flex: 1 1 auto; min-height: 0; display: grid;
                                 gap: 0 1.5rem; grid-template-columns: minmax(0, 1fr); }
article.record.full .bodywrap { min-height: 0; }
/* `max-width: none` guarded the full page against the record pages' 44rem cap
   on this box. No sheet caps the box any more — the measure lives on the
   article, and `.full` overrides it above — but a cap somebody writes tomorrow
   must still lose here, where the pane IS the window. */
article.record.full textarea.body-field { height: 100%; min-height: 0; resize: none;
                                          max-width: none; }
/* The rendered pane is a document, not a field: it loses the rule and the space
   above it that separate a shaping document from the facts, because in this view
   there is nothing above it to be separated from. */
article.record.full #body-preview { min-height: 0; overflow-y: auto;
                                    border-top: 0; padding-top: 0; }
/* Two columns in the middle view, and the reader says where the join is —
   jcanton, 2026-08-20: "in the side-by-side edit-preview view, can you make it
   possible to horizontally resize the editor vs the preview boxes? keeping their
   total width constant (so they don't move the fields which are displayed on
   their right)".

   **The constant total is structural, not arithmetic**, and that is why this is
   one property and a track rather than a layout engine: `.panes` gives `.facts` a
   fixed `20rem` track beside this whole grid, so a ratio inside `.bodysplit`
   cannot move that column however far the handle is dragged. There is no sum to
   keep balanced and so nothing that can drift out of balance.

   **One number, and the second track takes the remainder** — no second value that
   can disagree with the first. `fr` shares out what is left after the handle's
   own track, so that number IS the two panes' share of each other at every
   window width, and a window resize cannot make it stale.

   `minmax(0, …)` on both prose tracks and not a bare fraction, which is older
   than this change and must not be lost: a grid track's default minimum is its
   content, and one unbroken line of prose is wider than half a window — which
   pushed the other pane off the side instead of wrapping.

   The middle track is the 1.5rem this grid used to spend on `column-gap`, so the
   handle lands exactly where the space between the panes already was. */
article.record.full.view-both .bodysplit {
  grid-template-columns: minmax(0, var(--split, 1fr)) 1.5rem minmax(0, 1fr);
  column-gap: 0;
}
/* Not a control in either of the other two views, on the pages that inline this
   sheet with no document to split — the cycle page, the cycles index and the
   deck, the `_DETAIL_STYLE` loaders with no `.bodysplit` in their markup — or
   outside the surface. Absent rather than disabled: a separator in the tab
   order that divides nothing is a control that lies about what the page can
   do. */
#splitter { display: none; }
/* `touch-action: none` because the alternative is the browser deciding this drag
   was a pan: it then revokes the pointer with a `pointercancel` and no `pointerup`
   at all, which is the one way a captured pointer can still leave a handle stuck
   to the cursor. The script carries the branch for when it happens anyway; this
   is what stops it being asked for. */
article.record.full.view-both #splitter {
  display: block; position: relative; cursor: col-resize; touch-action: none;
}
/* The line down the middle, which was `#body-preview`'s `border-left` and its
   centring padding and negative margin. The same pixel in the same place, drawn
   by the handle now, because the affordance has to land on the line that is
   already there and two lines down the middle is worse than none. The rule this
   replaces is in the `width <` block below, where there is no handle to draw it. */
article.record.full.view-both #splitter::before {
  content: ""; position: absolute; top: 0; bottom: 0; left: 50%;
  width: 1px; background: var(--line);
}
/* And the grip, which is `#grip::before` in every dimension the two can share.
   What it does not copy is the fade, deliberately: the width grip floats in the
   page's margin with nothing else to say it is there, this one is an ink change
   on a rule the reader can already see, and a second animated rule in an app
   whose motion is one rule, one comment and one inventory test would cost all
   three to buy nothing. */
article.record.full.view-both #splitter::after {
  content: ""; position: absolute; left: 2px; right: 2px; top: 50%; height: 48px;
  transform: translateY(-50%); border-radius: 2px; background: var(--line-strong);
  opacity: .35;
}
article.record.full.view-both #splitter:hover::after,
article.record.full.view-both #splitter.dragging::after {
  opacity: 1; background: var(--accent);
}
/* Below the width where the facts stop being a column on the right there is
   nothing to hold still, which is the whole of what this handle is for — so it
   goes, and what is left is exactly the layout of the two panes before it
   existed.

   58.5rem is arithmetic rather than taste. `.panes` hands the facts their own
   track at a CONTAINER width of 56rem; the container is `article.record.full`,
   which is `position: fixed; inset: 0` with `1.25rem` of padding a side. So the
   two agree at 56 + 2 × 1.25, and there is no room below it either: the panes
   have `window - 424px` between them on that page, which is 512 here against a
   floor of 240 each.

   `@media` and not `@container`, for the reason the `.marks` block gives at
   length — historical since the inbox pages folded into `_DETAIL`. On this
   element the viewport is not a proxy for the container anyway: the surface
   IS the window.

   Same selectors as above, so this takes the ties on order and not on weight.
   `cascade.py` skips at-rules by construction, so that half is asked of Chrome. */
@media (width < 58.5rem) {
  article.record.full.view-both .bodysplit {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); column-gap: 1.5rem;
  }
  article.record.full.view-both #splitter { display: none; }
  article.record.full.view-both #body-preview {
    border-left: 1px solid var(--line); padding-left: .75rem; margin-left: -.75rem;
  }
}
/* Preview only is reading, and reading has a measure — the one the reader set
   with the grip on the page they came from, which is still in `--measure` and
   still theirs. Capped per block rather than on the pane, because the pane is
   the scroll container and a narrow scroll container puts its scrollbar down the
   middle of the window. */
article.record.full.view-view #body-preview > * { max-width: var(--measure, 64rem); }
/* Preview only: the box goes, and the two bars of CONTROLS go with it. A toolbar
   over no box is sixteen buttons that write into nothing, and a status bar over
   no box is a caret position for a caret nobody can see.

   **`#seatbar` is the third `.bodybar` here and it stays, deliberately.** The
   list used to be described as "the two bars" over three class names, on a
   surface that has four — which is how the next one added gets forgotten the
   same way. So the rule is what a bar IS, not how many there are: the two named
   below are controls for a box, and the seat bar is not a control at all. It is
   a fact about the document — who else is in it — and the document is still on
   the screen. It is also the ONLY live signal left in this view: the room goes
   on applying somebody else's keystrokes to the text under the rendered pane,
   and a reader watching a preview change under them with nothing on the page to
   say why is the worse of the two silences. It costs no space when nobody else
   is here, which is most of the time, because `#seatbar` carries no margin. */
article.record.full.view-view .bodywrap,
article.record.full.view-view .statusbar,
article.record.full.view-view .markbar { display: none; }
"""


_DETAIL_STYLE = """
/* No `#commitbar` here. The bar sticks to the top on this page because the SHELL
   says every commit bar does — one rule for every page that draws one — and an
   id override in this sheet was the wrong shape for it twice over: it beat the
   shell only on the pages that load this sheet, and the create form and the
   cycle page, bars still last in their markup, ended up stuck to neither edge.
   See `.commitbar` in the shell. */

.tocgroup { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
            color: var(--muted); font-weight: 600; margin: 1.4rem 0 .3rem; }
.tocgroup .tally { font-weight: 400; letter-spacing: 0; }
.toc ul { margin: 0; }
/* The kind chip leads each row, so the titles have to start at one x — a chip
   is as wide as the word inside it and "Project", "Pitch" and "Task" are three
   widths, which ragged the whole column. A fixed inline-block wide enough for
   the longest of the three, with the gap inside it rather than as a margin, so
   a row that wraps wraps its title and not its marker. */
{% for k in kinds %}
.toc li .chip.kind-{{ k }} {
  display: inline-block; min-width: 5.4rem; text-align: center;
  margin-right: .5rem; vertical-align: baseline;
}
{%- endfor %}
/* Centred, and a container so the panes below can ask how wide the column
   actually is. It sat flush left with a full-height rule down its right edge,
   which on a wide screen is not a document — it is the left half of a two-pane
   layout whose right half failed to load. */
article.record {
  width: var(--measure, 64rem); max-width: 100%; margin: 0 auto 3rem; position: relative;
  container-type: inline-size;
}
/* The facts beside the document rather than stacked on top of it: the reader
   comes for the shaping doc and glances at the facts, and a screen-and-a-half of
   metadata before the first sentence is the wrong way round. A container query
   and not a media query, because the width that decides this is the column's,
   which the reader sets with the grip — not the window's. */
.panes { display: grid; gap: 0 2.5rem; }
@container (min-width: 56rem) {
  /* 20rem and not less: these are the controls the record is edited through, and
     a reviewers box too narrow to show three logins is a sidebar that looks
     tidier than the page it replaced and is worse to use. */
  .panes { grid-template-columns: minmax(0, 1fr) 20rem; align-items: start; }
  .panes > .main { grid-column: 1; grid-row: 1; }
  .panes > .facts { grid-column: 2; grid-row: 1; border-left: 1px solid var(--line);
                    padding-left: 1.5rem; }
  /* Half a sidebar is not two columns. Stacked, each fact is a caption over its
     value and reads down the edge of the page. */
  .panes > .facts dl { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .panes > .facts dt { padding-top: .7rem; }
  .panes > .facts dt:first-child { padding-top: 0; }
}
/* A handle, not a border. It was a full-height 2px rule in --line, which is
   exactly how a page draws the edge of a pane; this is a short grip that says
   what it is when you reach for it. */
#grip {
  position: fixed; top: 0; bottom: 0; width: 10px; cursor: col-resize; z-index: 30;
}
#grip::before {
  content: ""; position: absolute; left: 3px; right: 3px; top: 50%; height: 48px;
  transform: translateY(-50%); border-radius: 2px; background: var(--line-strong);
  opacity: .35; transition: opacity .15s, background .15s;
}
#grip:hover::before, #grip.dragging::before { opacity: 1; background: var(--accent); }
article.record h1 { font-size: 1.5rem; margin: .2rem 0; }
.meta { color: var(--muted); margin-top: 0; display: flex; flex-wrap: wrap;
        gap: .4rem; align-items: baseline; }
.meta code { font-family: var(--font-mono); font-size: 12px; }
/* The line above the title. It carries the one fact that has to be read before
   the name — on the detail page the kind, on the create form the picker that
   decides it — and it is tucked tight against the heading so the two read as one
   header rather than as a paragraph with a heading under it. */
.eyebrow { margin: 0 0 .15rem; color: var(--muted); }
.back { margin: 0 0 .5rem; font-size: 12px; }
/* `.editbar` is the shell's. It was written here, and the table — which wears the
   class on the row holding its only create action — does not load this
   stylesheet. */

dl { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: .45rem 1rem; margin: 1rem 0; }
dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
     padding-top: .35rem; }
dd { margin: 0; }
dt.derived, dd.derived { font-style: italic; }
/* Still italic, because it is still computed and typing over it would change
   nothing. Coloured, because it is the one computed line that is a problem. */
.overrun { color: var(--sev-warn); font-weight: 600; }
/* The same sentence when the tasks still fit: said, but not shouted. A number
   that only appears when something is wrong is a number people learn to fear
   rather than to read. */
.quiet { color: var(--muted); }
/* The marks belong to the form, so they are not on the page when there is no
   form on it — in read mode a row saying REQUIRED beside a filled-in value is
   an instruction with nothing to do. */
article.record:not(.editing) .req { display: none; }
.problems { color: var(--warn); padding-left: 1.1rem; }
/* Not a problem, and it must not read as one: a note about the shaping document
   sits at the weight of the muted text around it, below anything the validator
   actually refused. */
.hints { color: var(--muted); padding-left: 1.1rem; font-size: 13px; }
/* The tasks a pitch is made of. Its own block above the document, because
   "where has this got to" is the question a pitch page is opened for and the
   answer was a checklist somewhere in the middle of the prose. */
.progress { border-top: 1px solid var(--line); padding-top: .6rem; margin-bottom: 1rem; }
.progress h2 { font-size: 1rem; margin: 0 0 .4rem; display: flex; align-items: center;
               gap: .5rem; }
.progress .tally { color: var(--muted); font-weight: 400; font-size: 12px; }
.progress ul { list-style: none; margin: 0; padding: 0; }
.progress li { display: flex; align-items: baseline; gap: .4rem; padding: .15rem 0;
               font-size: 13px; }
.progress li.ticked a { color: var(--muted); text-decoration: line-through; }
.progress .box { color: var(--muted); }

/* The two modes of the same rows. Controls are hidden until the article is
   editing, and the values they replace are hidden once it is. */
.field { display: none; }
.record.editing .field { display: block; }
/* Where the other people in the room are. One band per person on the line their
   caret is in, translucent so the text keeps its own contrast, with the login on
   the right — a colour on its own is a colour a reader has to be told the
   meaning of, and the two channels together need no legend.
   `pointer-events: none` throughout: the thing under this is the box being typed
   in, and a layer that takes a click is a click that does not reach it. */
.seats { position: absolute; inset: 0; overflow: hidden; pointer-events: none;
         border-radius: 3px; }
.seat { position: absolute; left: 0; right: 0; }
.seatname { position: absolute; right: .25rem; top: 0;
            font-size: 10px; line-height: 1.4; padding: 0 .3rem; border-radius: 3px;
            color: var(--bg); font-family: var(--font-sans); }
/* Who else is typing in this document, first in the bar because it is the one
   thing here that changes what you are about to do. `:empty` and not a `hidden`
   attribute somebody has to remember to set: the list is written with
   `textContent`, an empty string is the honest spelling of "nobody else", and a
   flex gap around an empty span is .6rem of nothing between two controls. */
.together { color: var(--accent); font-weight: 600; }
.together:empty { display: none; }
.editing-only { display: none; }
.record.editing .editing-only { display: block; }
/* Teaching copy under a control carries `.editing-only` and needs no rule of its
   own to appear — `.hint` gives it the ink, the line above gives it the mode.
   What it needs is a way to say nothing: the status row emits its span EMPTY for
   the three words with nothing to teach, because `attachHill` fills that same
   element as the ball moves and cannot fill one that was never rendered.

   Which way this resolves, since qualifying a selector to win one fight in this
   file has twice lost three: `.record.editing .editing-only` is (0,3,0) and
   would give an empty span a block box, so the rule that hides it repeats both
   ancestors and lands at (0,4,0). It wins on specificity and not on order, which
   is what keeps it correct if either rule moves. Deliberately not `.hint:empty`,
   which is lower AND would reach four spans on this page that are empty until a
   script has news for them — the draft stamp, the template note, the upload line
   and the gutter note. */
.record.editing .teach:empty { display: none; }
.record.editing .read { display: none; }
.record.editing dd .field[type=checkbox] { display: inline-block; }
label { display: block; }
/* Except in a fact list, where the label is one word in a line that also carries
   the REQUIRED mark. Block, the mark dropped onto a line of its own beside every
   gated field — an instruction shouting from its own row. */
dt > label { display: inline; }
/* The kind picker sits in the meta line, so it is a word in a sentence rather
   than a block that pushes the rest of the sentence onto its own row. */
.kindpick { display: inline; }
.kindpick select { font: inherit; }
/* In the bodybar beside the preview button, at the weight of the hints around
   it: a template is an offer, not a step. */
.tplpick { display: inline; color: var(--muted); font-size: 12px; }
.tplpick select { font: inherit; }
input.field, select.field, textarea.field {
  width: 100%; box-sizing: border-box; font: inherit; padding: .25rem .4rem;
  border: 1px solid var(--line-strong); border-radius: 3px;
  background: var(--surface); color: inherit;
}
input.title-field { font-size: 1.4rem; font-weight: 600; margin-bottom: .6rem; }
textarea.body-field { min-height: 60vh; resize: vertical; }
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2); padding: 0 .25em; }
/* Where a promoted record says where it came from. It is the first thing in the
   document and it is not part of the problem statement, so it is set apart
   rather than left as an indented paragraph that reads like one. One copy now:
   the record pages kept a second, identical declaration for as long as they had
   a stylesheet of their own, and it went with the stylesheet. */
.doc blockquote { margin: 0 0 1rem; padding-left: .8rem; color: var(--muted);
                  border-left: 2px solid var(--line-strong); }
/* No margin of its own: this row holds one live region that is empty whenever
   nobody else is in the document, which is most of the time, and a margin around
   nothing is a gap above the toolbar that nothing explains. */
#seatbar { margin: 0; }

/* `#conflict` is the shell's. It was written here, and the table draws the same
   box — `#row-conflict` — without loading this stylesheet, so the same report
   was a bordered block on one page and unstyled text on the other. */
/* Delete sits beside Edit and wears what Edit wears — no font, no padding, no
   border of its own, so the two cannot drift apart as one of them is restyled.
   Only the colour it turns on hover is its own, and only on hover: a red button
   sitting under every record is a page that looks like it is warning you about
   something when nothing is wrong. */
/* Delete is the shared shape and its own ink — declared after the shared hover
   above, because that rule is what it has to beat. It was left with NO rule at
   all when this was written, on the argument that carrying nothing meant
   matching Edit by construction; Edit was in the shared rule and Delete was not,
   so what it actually matched was the operating system. */
.editbar button.delete:hover, .confirming button.really:hover {
  border-color: var(--danger); color: var(--danger); }
.confirming button.really { border-color: var(--danger); color: var(--danger); }

/* The question, under the button that asks it. */
.confirming { display: flex; flex-direction: column; align-items: flex-start;
        gap: .5rem; max-width: 46ch; margin: 0 0 1rem;
        padding: .6rem .75rem; border: 1px solid var(--danger);
        border-radius: 3px; background: var(--surface); }
.confirming[hidden] { display: none; }
.confirming .asking { margin: 0; font-size: 13px; }
.confirming .acts { display: flex; gap: .4rem; }

/* What else this takes with it. The loud one is the deletion of other records —
   that is the sentence somebody has to read before pressing, so it is the danger
   colour and it is bold. The dependency line is quieter on purpose: nothing is
   destroyed there, a field is edited, and drawing the two the same way would
   teach people to skim both. */
.confirming .reach { margin: 0; font-size: 13px; font-weight: 600;
                     color: var(--danger); }
.confirming .reach.mild { font-weight: 400; color: var(--fg); }
.confirming .reach .ids { font-family: var(--font-mono); font-size: 12px;
                          font-weight: 400; }
/* The server's reason, where the question was asked. A refusal that names three
   tasks is the useful half of this feature and it must not go to the console. */
.confirming .why { margin: 0; font-size: 12px; color: var(--danger); }
.confirming .why[hidden] { display: none; }

/* The promotion bar. Hidden while the record is being edited: promoting carries
   the STORED body across, so offering it over a textarea somebody is halfway
   through is offering to promote a document they cannot see. */
#promote { display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap;
           border-top: 1px solid var(--line); margin-top: 1.5rem; padding-top: 1rem; }
.record.editing #promote { display: none; }
#promote select { font: inherit; font-size: 13px; }
#promote .hint { margin: 0; }
""" + _EDITING_STYLE
