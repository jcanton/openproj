"""The right-click menu: one floating box, three hosts.

`design/context-menus.md` is the whole argument. Cut 2 built the box, the host
contract and the reader's three items; cut 3 added the submenu machinery and the
three one-field writes (`Status ▸`, `Owner ▸`, `Take out of "X"`). Cut 4 is the
answer to the question that started it — the box's THIRD face, a form of the
record's fields with a Save button, opened by `New child ▸ <kind>`, `Edit…` and
`Assign parent…`, and by a status the gate refuses. `Delete…` is cut 5.

**Four faces, one box, and three of them are here.** `#card` is the reader's
hover card and lives in `shell.py`; the menu, the form and cut 5's delete
confirmation are all `#pop`, and which one is up is `POP_FORM` or `POP_CONFIRM`
being set. They are not three elements for the reason the card is one of its own:
they share a placement, a dismissal, a keyboard and the write doors, and the
form's whole reason for being a face of this box rather than a page is that a
refusal keeps it open with everything typed still in it.

**One door per verb, and everything else shared.** Three doors — `popWrite`,
`popCreate`, `popDelete` — because a single door with the address and the verb
passed in as data is a page carrying one `fetch` whose address is not in the
source a reader sweeps, announcing one write where three can happen. What would
otherwise be copied three times is `popStart`, `popSettled` and `popLost`: the
base commit, the re-entrancy flag, the `POP_GEN` snapshot and the reading of a
refusal. That last one is not a tidiness: a 409 from this server has two shapes,
and every page that decided for itself which key the body holds has got it wrong
— see `popSettled`.

**Here and not in `shell.py`.** That file is 4000 lines and ships on all twelve
pages, including `/help` and `/people`; this menu is wanted by three. A module
imported by the pages that want it is the shape this codebase already uses three
times over — `_FILTER_JS` (`controls.py`), `_REQUIRED_JS` and `_combobox_html`.

**Two boxes and not one.** `#card` is a box with hover-intent, a grip drag that
suspends its own dismissal and a two-pass draw that exists because a one-pass
card visibly grew and re-placed itself after appearing. A menu sharing an element
with all of that is a menu racing it. What the two owe each other is one rule:
opening the menu kills the card, and the card does not come back while the menu
is up — see `cardYields` below, which is `shell.py`'s half of it.

What a view has to do to get the menu is in `popServes` below. What it must NOT
do is anchor anything to a row or a node: the table's `draw()` replaces the whole
tbody and the graph's `relayout()` ends in `cy.fit()`.
"""

from __future__ import annotations

from markupsafe import Markup

from ..index import Index
from ..model import (
    CHILD_KINDS,
    PARENT_KINDS,
    RUNG,
    opens_at,
    required_at,
    unread_fields,
)
from .controls import _suggestions
from .env import _fragment
from .shell import Links
from .tokens import (
    EDITABLE,
    HUMAN,
    LABELS,
    PRIORITIES,
    STATUS_GLYPH,
    SUGGESTS,
    _editable_for,
)

# `_blank` was defined here until the hover card needed the same question
# answered. It lives in `tokens.py` now, beside `_editable_for`, because
# `shell.py` draws the card and cannot import this module — this one imports
# `Links` from it.
from .tokens import blank_record as _blank

# The menu's own stylesheet, and **it lives beside the menu because of which
# pages load what.** `.drawmenu` — this repository's other floating menu — is in
# `_DETAIL_STYLE` (`styles.py`), which the record page and the slide editor load
# and the table, the graph and the timeline do not. `_SUGGEST_STYLE` is the
# table's and not the graph's, `_SCROLL_STYLE` and `_TREE_STYLE` likewise. There
# is no sheet all three of this menu's hosts already load except the shell's, and
# the shell ships on all twelve pages for a thing three of them draw.
#
# So the rules travel with the module that draws them, and each of the three
# views concatenates this into its own `_page(style=...)` — exactly the way
# `table.py` already writes `_TABLE_STYLE + _SUGGEST_STYLE`. `.drawmenu`'s own
# comment made this same call for the same reason a fortnight ago.
#
# No colour token is DEFINED here, only used. So there is no `:root` block to
# write out three times, and nothing in this sheet can be right under the media
# query and wrong under the theme toggle — the rule is met by there being nothing
# for it to bite on.
_POP_STYLE = """
/* The menu box. `position: fixed` and parked on the body, not `position:
   absolute` the way `.drawmenu` is: `.table-scroll`'s `overflow: auto` and the
   frozen columns' sticky stacking contexts clip and under-paint anything
   absolute, and this box opens over both.

   z-index 25 is over `#card` at 20 — the box this one dismisses, and the one it
   must never open behind — and under `#moved` at 40, which the shell puts above
   everything on purpose: news that the plan moved under you is the one thing on
   screen a menu may not cover. */
#pop {
  position: fixed; z-index: 25; min-width: 11rem; max-width: 20rem;
  max-height: 70vh; overflow-y: auto;
  display: flex; flex-direction: column; padding: .25rem 0;
  background: var(--surface); border: 1px solid var(--line-strong);
  border-radius: 3px; box-shadow: 0 4px 14px rgba(0, 0, 0, .12); font-size: 13px;
}
/* `[hidden]` written out, and it is the third rule in this repository that has
   had to be. The UA stylesheet's `[hidden] { display: none }` loses to ANY
   author rule that sets `display`, on cascade origin alone and regardless of
   specificity — `#pop` above sets `display: flex`, so `POP.hidden = true` would
   change nothing about whether the box is laid out. jcanton reported the
   `.drawmenu` version on 2026-08-26 as "the dropdown menu doesn't completely
   disappear sometimes", measured there at 162x10 closed, and what made that one
   look like it mostly worked was the `replaceChildren()` on the same line: an
   emptied box collapses to its own padding and border. This box deliberately
   KEEPS its items when it closes, so it would not even do that — it would stay
   the whole menu, over the page, ignoring every press. */
#pop[hidden] { display: none; }
/* One item. `white-space: nowrap` with an ellipsis rather than wrapping: an item
   carries a record's title (`Take out of "…"`), and a menu whose rows are three
   lines tall is a menu you cannot scan.

   `display: flex` and not the `display: block` this rule was written as, because
   an item now has up to three parts — a status glyph, the word, and the mark
   behind it that says either "there is a list here" or "this is the value the
   record holds". Under `overflow: hidden; text-overflow: ellipsis` on a block,
   the two marks are the FIRST things a long title cuts: the reader loses the
   mark saying which status this is and the mark saying there is a list behind
   it, while the title they can already read is merely shortened. That is
   `clamped()`'s bargain in `table.py` said in one rule — the text is the flex
   item that shrinks and the marks never do. */
#pop .popitem {
  /* **`flex: none` is what makes `max-height` scroll instead of squash**, and it
     is not a tidying. `#pop` is a flex column, so every item is a flex item with
     the default `flex-shrink: 1`, and a column that has met its `max-height:
     70vh` resolves that by taking the overflow out of its children. Measured in
     headless Chrome at a 333px window, 2026-09-18: a twenty-item owner list drew
     every row **11.7px** tall against the 24px it asks for — the words on top of
     each other, the box reporting `scrollHeight === clientHeight`, and therefore
     `overflow-y: auto` never engaging at all. Cut 2's three items could not
     reach the cap, which is exactly why this has to be written now rather than
     found by somebody with more people on their plan. */
  flex: none;
  display: flex; align-items: baseline; gap: .5rem;
  width: 100%; text-align: left; font: inherit; color: inherit;
  background: none; border: none; padding: .35rem .75rem; cursor: pointer;
  text-decoration: none; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;
}
#pop .poptext { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; }
/* Neither mark shrinks, and the glyph keeps a column of its own so the words
   down a status ladder line up whether or not their marks are the same width. */
#pop .popglyph { flex: none; width: 1em; text-align: center; }
#pop .popmark { flex: none; color: var(--muted); }
/* **The marks have to be recoloured on a lit row, not merely dimmed on a cold
   one.** `--muted` is a grey chosen against `--surface`; the rule above fills a
   hovered or focused item with `--accent`, and grey on the accent is the one
   pairing in this sheet with no contrast guarantee behind it. `inherit` takes
   the ink that fill already carries, which is the same argument the focus ring
   two rules down is recoloured by. */
#pop .popitem:hover .popmark, #pop .popitem:focus .popmark { color: inherit; }
#pop .popitem:hover, #pop .popitem:focus {
  background: var(--accent); color: var(--on-accent);
}
/* The ring stays and moves inside the item. `.drawmenu` answers this by switching
   the ring off and filling with the accent instead, which this sheet may not copy:
   `test_every_page_can_draw_a_problem_and_a_focus_ring` forbids that declaration
   anywhere in `table.html` as a plain substring — so it may not be spelled here
   even in a comment, because a comment ships in the page's bytes. Inside rather
   than outside because the shell's ring is `outline-offset: 2px`, and an item is
   the full width of a box whose `overflow-y: auto` makes the other axis `auto`
   too — two pixels past the padding box is two pixels the box clips.

   And recoloured, which is not a refinement: `--focus` IS `--accent`, in all three
   theme blocks, and the rule above fills a focused item with `--accent`. The
   shell's ring was therefore being drawn in the accent on top of the accent, which
   is no ring at all. `--on-accent` is the ink that fill already carries, so its
   contrast against it is guaranteed by construction rather than by a second choice
   of colour. Scoped off the refusals, whose fill is `--surface-2` and against which
   the accent ring is already visible. */
#pop .popitem:focus-visible { outline-offset: -2px; }
#pop .popitem:not([aria-disabled="true"]):focus-visible {
  outline-color: var(--on-accent); outline-offset: -3px;
}
/* Refused, and still focusable — `aria-disabled` and not `disabled`, so it keeps
   its place in the roving focus and can still be asked. It answers with its
   reason instead of acting, so it must not light up like an item that is about
   to do something: the fill says "this is the row you are on", not "this will
   happen". */
#pop .popitem[aria-disabled="true"] { color: var(--muted); cursor: default; }
#pop .popitem[aria-disabled="true"]:hover,
#pop .popitem[aria-disabled="true"]:focus {
  background: var(--surface-2); color: var(--muted);
}
/* The one item whose text may wrap: what the server said about a write it would
   not do. It is drawn as a refused item so that it is a real `menuitem` inside a
   `role="menu"` — a `<p>` in there is not a child a menu may have — and so that
   it takes the dim treatment above for free. What it may not take is the
   ellipsis: a refusal is a sentence, and "somebody else changed this f…" is a
   refusal nobody can act on. `max-width: 20rem` on the box is what keeps it from
   becoming a paragraph. */
#pop .popitem[data-kind="said"] { white-space: normal; }
#pop .popitem[data-kind="said"] .poptext { overflow: visible; text-overflow: clip; }

/* --- the form: the box's third face ---------------------------------------

   A class on the box and deliberately not `#pop:has(.popform)`. The selector
   would be one rule instead of a class toggled in two places, and it would also
   be the first `:has()` in this repository — a selector Chrome has had since
   105 and Firefox since 121, on a page whose whole job at that moment is to be
   the only way to create a record without leaving the view. `popforming` is set
   by `popDrawForm` and cleared by `popDraw`, which are the same two functions
   that already swap the box's `role` between `menu` and `dialog`; the state is
   written down once either way, and this way nothing has to be true of the
   browser. */
/* Wider than the menu, and with a floor under it. The menu's `min-width: 11rem`
   is right for a list of words and wrong for a row of date boxes, and the
   difference between kinds is large — `fields["product"]` is `["title","tags"]`
   and a task's is fifteen controls — so the box is given a range rather than a
   size and the content decides inside it. The padding moves to the form,
   because `#pop`'s `.25rem 0` is the gap above and below a list of full-width
   items and a form needs a margin at the sides as well. */
/* Both bounds are clamped against the window, and `min-width` has to be as well
   because it WINS over `max-width` in the used-value rules — a bare
   `min-width: 17rem` is a box 272px wide in a 260px window, hanging off the far
   edge of a `position: fixed` element there is no way to scroll to. The menu's
   own 20rem happens to fit the narrowest desktop window anybody opens; a form's
   26rem does not. */
/* **26rem is `#card`'s own `max-width`, and the two are the same number on
   purpose.** jcanton, 2026-09-18, on the first form drawn: "can the `edit` box
   be the same as the floating card box, just with clickable/editable fields?
   instead of a new tall, column box" — and, when the first answer widened the
   box without wearing the card: "I meant this card". So the form IS the card:
   its width, its title line, its chip line and its `<dl>`, with a control
   wherever the card draws a value. */
/* The confirmation takes the same range for a different reason and gets it from
   the same rule rather than a second copy of the arithmetic: its lines are
   prose — a sentence with a record's title inside it — and the menu's 20rem is
   sized for single words. */
#pop.popforming, #pop.popasking {
  min-width: min(17rem, calc(100vw - 16px));
  max-width: min(34rem, calc(100vw - 16px));
  padding: 0;
}
#pop .popheading { margin: 0; font-size: 13px; font-weight: 600; }
/* The form's copy of it, off the screen and still in the document. `.sr-only`'s
   own declarations rather than the class, because `#pop .popheading` above is
   (1,1,0) and would win the margin back off a (0,1,0) class — and a rule that
   only half applies is the worst of the two. The confirmation's heading keeps
   the visible one: it is the box's first line there, and there is no title
   above it to say the same thing. */
#pop .popform .popheading {
  position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
  overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0;
}
/* **The box is the hover card**, so the padding is the card's and everything
   inside it is drawn by the card's own rules — see `:is(#card, .popcard)` in
   `shell.py`, which is one block serving both. What is left here is the part
   that is only true of the box you can edit in. */
#pop .popform {
  /* `flex: none` for the reason `.popitem` has it, and the failure is the same
     one: `#pop` is a flex column with a `max-height`, so a card taller than 70vh
     would be resolved by squashing the one child rather than by scrolling. */
  flex: none;
  padding: .4rem .55rem .5rem;
}
/* Something you can click. No border and no fill — a card with twelve outlined
   boxes on it is the form this replaced — so what says a value is a control is
   the cursor, a tint under the pointer, and the focus ring when the keyboard
   arrives. The table says it the same way and for the same reason: a cell is a
   word until you are on it. */
#pop .popopens { cursor: pointer; border-radius: 2px; }
#pop .popopens:hover { background: var(--surface-2); box-shadow: 0 0 0 2px var(--surface-2); }
/* The title line and the chips are not `<dd>`s and have no cell to tint, so the
   ring is drawn on the thing itself. `outline-offset` rather than a margin,
   because a card's chip line must not move when you point at it. */
#pop .popopens:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
/* A field this box will not open: the parent of a new child, a value this view
   does not carry. Dimmed rather than removed, for the reason a refused item is
   drawn rather than left out — a row that disappears teaches nothing about why —
   and the sentence is on `title`, because a card has no room for a paragraph
   per row. */
#pop .poplocked { color: var(--muted); cursor: help; }
/* The cell while it holds a control. It is the one place the card's own
   `overflow: hidden` has to be lifted: a `<select>` inside a clipped cell draws
   its list from a box one line tall. */
#pop .popediting { overflow: visible; }
/* Every control this box opens, and it is the cell editor's shape rather than a
   fourth one. The shell gives an `input` its background and its ink and nothing
   else — "the padding, border and radius of a text box are set where each of
   them is drawn".

   `#pop` is on the front so that the specificity question is settled rather than
   left to source order: the shell's own
   `input:not([type="checkbox"]):not([type="radio"])` is (0,2,1) and an
   unprefixed `.popbox` would be (0,1,0). */
#pop .popbox {
  font: inherit; font-size: 12px; width: 100%; box-sizing: border-box;
  padding: .1rem .25rem; border-radius: 2px;
  border: 1px solid var(--accent);
  background: var(--surface); color: var(--fg);
}
#pop input.popbox[type="checkbox"] { width: auto; }
/* The title line's control is the title's own size and weight, because the line
   it replaces is. */
#pop .card-title .popbox { font-size: 13px; font-weight: 600; }
/* A chip being changed. The chip keeps its tint and its mark — the colour that
   says which rung this is must not blink to grey while you pick the next one —
   and the `<select>` inside it is drawn in nothing at all. */
#pop .card-chips .popbox {
  font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  width: auto; padding: 0 .1rem; border-color: var(--accent);
  background: none; color: inherit;
}
/* The mark on a field the chosen status will make the server refuse the record
   without. `--sev-blocker` and not `--warn`: it is the same news the table's own
   blocker marks carry, which is that a save will be refused rather than
   grumbled at. It is `aria-hidden` and the control carries `aria-required`, so
   this is the sighted half of one fact and never the only half. */
#pop .popreq { color: var(--sev-blocker); }
/* The three rules that dressed a form full of boxes were here, and they are
   gone with it: there is no form full of boxes any more. `#pop .popbox` above is
   the one control this box ever draws, and it is (1,1,0) — an id beats the
   shell's own `input:not([type="checkbox"]):not([type="radio"])` at (0,2,1) on
   the first component, so the question is settled rather than left to which
   stylesheet `_page` inlines second. */
/* A sentence under a control, which only the delete confirmation draws now: the
   card says why a row will not open in its `title` instead, because a card has
   no room for a paragraph per row. */
#pop .popnote { margin: 0; color: var(--muted); font-size: 12px; }
/* What the server, or the gate, said about this save. A list because a create
   is refused with a `problems` array and three blockers read as three lines
   rather than one long one — `refusalLines` (`table.py`) makes the same split.
   No ellipsis and no `nowrap`: a refusal is a sentence. */
#pop .popwhy {
  margin: 0; padding: 0; list-style: none;
  display: flex; flex-direction: column; gap: .25rem;
}
#pop .popwhy[hidden] { display: none; }
#pop .popwhy li {
  font-size: 12px; padding: .3rem .4rem; border-radius: 3px;
  color: var(--sev-blocker); background: var(--sev-blocker-soft);
}
#pop .popwhy:focus-visible { outline-offset: -2px; }
#pop .popacts { display: flex; gap: .4rem; justify-content: flex-end;
                margin-top: .25rem; }
/* The verb. `.button.primary` in the shell is for an `<a class="button">`, and
   this is a real `<button>`, so the fill is written here — two declarations,
   against vendoring a class that would have to be kept in step with a sheet
   this page does not load.

   `#pop .popsave:hover` is (1,2,0) against the shell's `button:hover` at
   (0,1,1), so the accent-on-accent that rule would give a filled button — the
   same collision the focus ring above is recoloured for — does not happen. */
#pop .popsave {
  background: var(--accent); border-color: var(--accent); color: var(--on-accent);
}
#pop .popsave:hover { color: var(--on-accent); opacity: .9; }
/* While the commit is in the air. `POP_WRITING` is the rule and this attribute
   is how it is shown — `CREATING`'s bargain in `table.py`, where two presses
   0.9s apart minted two records on the deployed service. */
#pop .popsave:disabled { opacity: .6; cursor: progress; }

/* --- the confirmation: the box's fourth face -------------------------------

   The record page has asked this question since the record page had a delete
   button, and this is that panel inside a floating box rather than a second
   look for the same decision. Every rule below is `.confirming`'s own
   (`styles.py`), re-scoped: the loud line for the records that GO, the quiet one
   for the records that keep their files and merely lose a dependency, and one
   chip per title.

   Why the two lines are drawn differently is the whole of that sheet's comment
   and it is worth repeating where somebody might tidy them into one: nothing is
   destroyed on the quiet line, a field is edited, and drawing the two the same
   way teaches people to skim both. */
#pop .popconfirm {
  /* `flex: none` for `.popitem`'s reason and `.popform`'s: `#pop` is a flex
     column with a `max-height`, and a cascade of forty titles taller than 70vh
     would be resolved by squashing this one child rather than by scrolling it. */
  flex: none;
  display: flex; flex-direction: column; gap: .5rem;
  padding: .6rem .75rem .7rem;
}
/* The sentences scroll, and nothing else in this panel does.
   `#pop` is `max-height: 70vh`, and a cascade of forty titles makes this panel
   taller than that — at which point the heading, the note and BOTH buttons sit
   below the fold with `POP.scrollTop` still 0 and nothing on screen saying the
   box scrolls. The `Keep it` that `popAsk` focused is off screen too, so the
   panel reads as a destructive question with no way to answer it.
   Capping this box instead means the panel never outgrows `#pop`: the question,
   the hint and the two controls are always on screen, and what scrolls is the
   list of consequences, which is the one part a reader can be trusted to look
   for. `display: flex` with the same gap `.popconfirm` has, because these `<p>`s
   were direct children of that flex column on the record page and inherited it
   there; in a plain block wrapper they would sit flush against each other. */
#pop .popreaches {
  display: flex; flex-direction: column; gap: .5rem;
  max-height: 40vh; overflow-y: auto;
}
#pop .popreach { margin: 0; font-size: 13px; font-weight: 600; color: var(--danger); }
#pop .popreach.popmild { font-weight: 400; color: var(--fg); }
/* The records those sentences name, one element each, and the separator drawn
   rather than written. A title is held to one rule, that it is not blank, so
   there is no character a title cannot contain — comma-joining three titles, one
   of which has a comma in it, offers a reader four items and asks them to press
   Delete on that. A tint and a hairline per name cannot be forged from inside
   one. `font-weight: 400` because `.popreach` is 600 and a name is the data in
   that sentence rather than more of its emphasis. */
#pop .popnames { display: inline; }
#pop .popnamed {
  display: inline-block; margin: 0 .1rem; padding: 0 .3rem;
  border: 1px solid var(--line); border-radius: 3px;
  background: var(--surface-2); font-weight: 400;
}
/* The destructive verb, in its own ink and never the accent fill `.popsave`
   carries: this control is not the one the box wants you to press. `:hover` is
   written out for the reason `.editbar button.delete:hover` is — the shell's own
   `button:hover` is what it has to beat, and a control left with no rule at all
   matches the operating system rather than the page.

   `:disabled` is not a decoration either. It is how this button spends the whole
   window between the panel opening and the plan answering what would go with
   it — see `popAsk`. */
#pop .popreally, #pop .popreally:hover {
  border-color: var(--danger); color: var(--danger);
}
#pop .popreally:disabled { opacity: .6; cursor: default; }
"""


# The menu itself. One `<script>` block, the shape `_FILTER_JS` already has, put
# into each view's template ABOVE the view's own script — these are classic
# scripts sharing one global scope, and a function in a later block is not
# hoisted into an earlier one, so a `popServes(...)` call in a view's script
# needs this block to have run.
# The menu, in two halves, and **the split is what keeps a write off a page that
# cannot make one.**
#
# `tests/test_table.py` asserts that the static export and a signed-out reader's
# table carry no `/api/record` and no `base_commit` anywhere in their bytes, and
# `tests/test_render.py` asks the same of every rendered file. A rendered file is
# a thing somebody puts on a share and a reader's page is served to anyone; the
# strings being inert behind `POP_HOST.may()` is exactly the argument those tests
# exist to refuse, because inert-by-a-guard is one edit from not inert.
#
# Function declarations hoist within a script block, so the halves concatenate in
# either order and the write doors sit beside the write items rather than below
# `closing`, where it was first written.
_POP_JS_READ = r"""
// --- the right-click menu ---------------------------------------------------
//
// The box is built here and appended to the body rather than emitted into each
// page's markup, and that sidesteps the one ordering trap `shell.py` writes up
// at `#card`: `getElementById` runs while the parser is still above the element,
// so a box written at the foot of the body was null on every page and every view
// drew nothing — in a browser, while a shim that parses the whole file before
// running anything answered that it was fine. A box this script makes cannot be
// above or below itself.
const POP = document.createElement('div');
POP.id = 'pop';
POP.hidden = true;
POP.setAttribute('role', 'menu');
document.body.append(POP);

// Where a record's page is: `/detail/` from the server, `detail.html#` in a
// rendered export. A template variable and not a value read back out of the DOM,
// for the reason `CARD_BODY_URL` is one — the shell knows its links at render
// time, and reading one back is another thing that can be true of the page and
// false of the document a test drives.
//
// Concatenated raw, exactly as every other record link on this site is built
// (`graph.py`'s node tap, `detail.py`'s redirect, and every template that
// renders `links.record`). `Open` has to land precisely where the title link
// lands, and a menu that encodes an id nothing else encodes is a menu that goes
// somewhere else for the one id where it matters.
const POP_RECORD = {{ record|tojson }};

// What the write half is built from, baked by the server — see `_pop_schema`.
// `null` on a page rendered without an index, which is the static export.
//
// **Here and not read out of the host's payload, because the three hosts do not
// have one between them.** The table ships `DATA.editable`, `DATA.required`,
// `DATA.glyphs`, `DATA.labels` and a `#suggest` blob; the graph's payload is
// cytoscape elements and carries none of those; the timeline has neither. A menu
// that read the page it happens to be on would be three menus, and the first
// thing that would go wrong is the thing that already went wrong to the hover
// card — `in_progress` on the graph where the other two said "In progress".
const POP_SCHEMA = {{ schema|tojson }};

// --- the host contract ------------------------------------------------------
//
// A view registers itself once and then knows nothing else about this menu:
//
//   popServes({
//     may: () => EDITABLE,          // may_write, from the server
//     rows: id => DATA.rows[id],    // the row view model — `rows.py:_row`
//     extras: row => [ … ],         // this view's own items
//     wrote: (answer, id) => …,     // what to do after a write lands
//     all: () => [row, …],          // every record, for the parent picker
//     shows: id => true,            // whether that record is on screen NOW
//   });
//
// `all` and `shows` are cut 4's and are optional like `extras` and `wrote`. What
// each one costs when a host leaves it out is written at `popAllRows`, and it is
// never silence: the parent items refuse with a sentence, and the create's
// receipt stops claiming to know where the record went.
//
// `may` gates the write half and is asked on every open, never cached: a page
// that learns it is signed out does not get to go on offering writes until
// somebody reloads.
//
// **A host whose `may()` can answer truthily must be rendered with
// `_pop_js(links, index)`.** That is what bakes `POP_SCHEMA`, and without it the
// write half has nothing to build itself from. The menu says so out loud rather
// than quietly drawing a reader's menu — see `popWriteItems`.
//
// `extras` and `wrote` are optional and both have a safe default, because a
// reader-only host has neither: the timeline registers `may: () => false` and
// gets exactly the three items below, which is the right answer for a page with
// no `#base` element, no `may_write` on its route and not one `fetch` in it.
let POP_HOST = null;
function popServes(host) { POP_HOST = host; }

// Which record the open menu is about, and where the keyboard was when it
// opened. Both cleared on close, so nothing here can answer about a menu that is
// not up.
let POP_ID = null;
// Which opening of the box this is. Bumped on every open and every close, and
// read by `popWrite` so that an answer can tell whether the box it was sent from
// is still the box on screen.
//
// A write here is a commit and a push against a repository on GitHub, so it is
// seconds — and this menu stays up for all of them. In that window a reader can
// dismiss the box and right-click a different record, and the `pointerdown`
// listener in this file documents that exact sequence because it is the ordinary
// way to open a second menu. Without this, the first write's refusal would be
// drawn into the second record's menu and take the keyboard with it, saying
// something true about a record nobody is looking at.
let POP_GEN = 0;
let POP_RETURN = null;

function popIsOpen() { return !POP.hidden; }
function popAbout() { return POP_ID; }

// --- the items --------------------------------------------------------------
//
// An item is `{kind, text, why, run, href}`, and this descriptor is the contract
// the rest of the menu is written against, so all five are built now even though
// cut 2 produces three of them.
//
// `kind` is a stable slug, drawn as `data-kind`. It is the handle a test reaches
// for — never the visible text, which is copy and is expected to change.
//
// `why` present means the item is REFUSED: drawn dim, `aria-disabled` and not
// `disabled` so it stays focusable, and pressing it announces the reason instead
// of acting. An item that would vanish is drawn refused instead, because a
// control that disappears teaches nothing about why. Nothing in cut 2 produces
// one — the reader's three items are always available — and it is built anyway,
// because cut 3's items are mostly refusals and three call sites and a submenu
// are being written against this shape.
//
// `href` present means the item is a real link into a new tab: an `<a
// target="_blank">` and not a `run()`, so middle-click works and the browser's
// own context menu on it — Copy link address, Open in new window — works too.
// There is no separate "new tab" flag, because there is no other kind of link
// this menu wants: an item that stays in this tab is a `run` that navigates.
//
// `run` is what a plain item does, and it runs BEFORE the box is dismissed. See
// `popRan`. A `run` that returns a promise owns the dismissal itself.
//
// `items` present means the item DRILLS DOWN: the list is replaced in this same
// box, with `‹ Back` at the top. It is a FUNCTION and not a list, so a submenu
// is built at the moment somebody opens it rather than when its parent was
// drawn — `attachDrawing`'s rule, and the reason a status submenu cannot show a
// stale word after a save.
//
// `checked` present makes the item one of a set with a current value —
// `role="menuitemradio"` and `aria-checked`, because on a plain `menuitem`
// `aria-checked` is ignored. `glyph` is the mark drawn in front of the word.
//
// `stays` keeps the box up after the run, and it is carried by every item that
// REPLACES the box's contents rather than acting: `‹ Back`, the three that open
// a form, a status choice the gate sends to one, and `Delete…`. It said "exactly
// one item" for as long as that was true, which was cut 3.
function popItems(row) {
  const href = POP_RECORD + row.id;
  const items = [];
  // **The write half**, behind `POP_HOST.may()` — `Status ▸`, `Owner ▸` and
  // `Take out of "X"` here; `New child ▸`, `Edit…` and `Assign parent…` in cut
  // 4, `Delete…` in cut 5. The ORDER is the design: what changes the plan, then
  // what this view can do, then the three that only look — which are the ones a
  // reader gets, and the ones that stay at the bottom so their position does not
  // move when somebody signs in.
  const writes = popWriteItems(row);
  // **`Delete…` is last on the menu, under even the three that only look**, and
  // it is lifted out of the write half by its slug rather than returned
  // separately. The design's table puts it there and the reason is the gesture:
  // a destructive item sitting between `Take out of "X"` and `Focus subtree` is
  // one slip of the wrist away from the two harmless items either side of it.
  //
  // By the slug and not by position, and through the one function this half is
  // allowed to call: the read half may reach exactly `popWriteItems` across the
  // split (see the module comment), so a second crossing named `popDeleteItem`
  // would be a `ReferenceError` on a reader's page — and in a classic script
  // that takes the whole block, including the three items a reader does get.
  for (const item of writes) if (item.kind !== 'delete') items.push(item);
  //
  // This view's own items, spliced in whole. Asked on every open and never
  // stored, which is `attachDrawing`'s rule (`controls.py`) and the reason a
  // host can refuse against state that moved since the last open. A host with
  // none of its own may leave `extras` out entirely.
  for (const extra of (POP_HOST.extras ? POP_HOST.extras(row) : null) || []) items.push(extra);
  items.push({kind: 'open', text: 'Open', run: () => { location.href = href; }});
  items.push({kind: 'open-tab', text: 'Open in new tab', href: href});
  items.push({kind: 'copy-link', text: 'Copy link', run: () => popCopy(href)});
  for (const item of writes) if (item.kind === 'delete') items.push(item);
  return items;
}

// --- opening ----------------------------------------------------------------

// Returns whether this module answered the press, and the call site is
// `if (!event.shiftKey && popMenu(event.clientX, event.clientY, id)) event.preventDefault();`
// — a press on something this view has no row for gets the browser's own menu
// rather than an empty box of ours.
function popMenu(x, y, id) {
  if (!POP_HOST) return false;
  // **A right-click elsewhere does not throw away a form being filled in.** The
  // press would otherwise open a menu into the same box, which is a
  // `replaceChildren` over every control and every word typed into them, with
  // nothing said. Answered — `true`, so the view calls `preventDefault` — rather
  // than declined, because the browser's own menu drawn over the top of our form
  // is a stranger answer than the press doing nothing. Escape and Cancel are how
  // a form is left, and they are both one key and one control away.
  if (POP_FORM) return true;
  const row = POP_HOST.rows(id);
  if (!row) return false;
  // Read before anything of ours takes focus, because `document.activeElement`
  // is what the keyboard fallback measures.
  const at = popAt(x, y);
  const items = popItems(row);
  if (!items.length) return false;
  POP_RETURN = document.activeElement;
  POP_ID = id;
  POP_GEN += 1;
  // **Opening the menu kills the card, and the card does not come back while the
  // menu is up.** Which is three things and not one, all of them inside
  // `cardYields` (`shell.py`): `hideCardNow()` unconditionally, INCLUDING
  // through its `cardResizing` early return, because a right-click during a grip
  // drag must still get its menu; the pending `cardTimer`, because a card queued
  // 400ms ago and not yet drawn will otherwise appear on top of this box; and a
  // flag `queueCard` consults, because the pointer is sitting over the row this
  // box covers and every `pointermove` re-arms it.
  //
  // Called without a `typeof` guard on purpose. This block only ships on pages
  // that draw a card, so a missing `cardYields` is a missing seam and not a
  // page without one — and a loud ReferenceError at the first right-click is
  // the cheapest way to be told, where a guard would leave a card drifting over
  // the menu on three views with nothing said.
  cardYields(true);
  // The pointer the box is anchored to, kept for as long as it is up. Every
  // later draw — a drill-down, a `‹ Back`, a refusal — places against THIS point
  // and never against where the box currently happens to be. See `popPlace`.
  POP_AT = at;
  POP_SAID = '';
  // One level, rebuilt from scratch, and never stored across an open. That is
  // `attachDrawing`'s rule and the reason a status submenu cannot show a stale
  // word after a save.
  POP_STACK = [{label: 'Actions for ' + popTitle(row), from: null, items: items}];
  POP.hidden = false;
  popDraw();
  // Focus the first item on every open, including a pointer's. It is what makes
  // the arrows and Escape work without a click first — and the Escape handler
  // below is bound on this box, so it only ever sees the key because focus is
  // inside it.
  popFocus(0);
  return true;
}

// --- the levels -------------------------------------------------------------
//
// **A submenu drills down in the same box.** The alternative — a second element
// opening beside the item — is the conventional desktop idiom and was refused
// for cost: a second element, a second placement function with its own edge
// flipping, and a hover-intent model this app no longer has anywhere.
//
// The levels the box is showing, innermost last. `from` is the slug of the item
// that was drilled into, so `‹ Back` knows where to put the keyboard down.
let POP_STACK = [];
// The pointer this menu was opened at.
let POP_AT = null;
// What the server said about a write it would not do, drawn as the first item of
// whatever level is up. Cleared by any navigation: it is an answer about the
// press that has just happened, and a `‹ Back` is a different question.
let POP_SAID = '';

function popControls() { return [...POP.querySelectorAll('.popitem')]; }

function popDraw() {
  const level = POP_STACK[POP_STACK.length - 1];
  const items = POP_SAID
    ? [{kind: 'said', text: POP_SAID, why: POP_SAID}, ...level.items]
    : level.items;
  // Back to the menu face. Every part of it, because a `<form>` is not a child a
  // `role="menu"` may have and a list of `menuitem`s is not something a
  // `role="dialog"` should be announcing — the box wears exactly one of its three
  // faces at any moment, and this is the only place the items face is put on.
  POP_FORM = null;
  POP_CONFIRM = null;
  POP.classList.remove('popforming', 'popasking');
  POP.setAttribute('role', 'menu');
  // The box is named for the level it is showing, so a reader who arrives inside
  // the status ladder is told which list they are in rather than being told
  // again which record the menu is about.
  POP.setAttribute('aria-label', level.label);
  POP.replaceChildren(...items.map(popControl));
  // Back to the top on every draw: a drill-down into a long list must not start
  // halfway down it because the list it replaced was scrolled. Assigning
  // `scrollTop` fires `scroll`, which the capture listener below ignores for
  // this box — that guard is cut 2's, written before there was anything to
  // scroll, and this is the second thing standing on it.
  POP.scrollTop = 0;
  popPlace();
}

// **The menu never moves once placed, and a drill-down is not a move.**
//
// The two rules really do meet here, so this resolves them rather than choosing
// one: what is fixed is the ORIGIN, `POP_AT`, and every draw places against that
// same point. The box keeps its corner for as long as the new content fits, and
// flips or clamps exactly as the first placement would have when it does not.
// What the design's rule is actually about stays true — nothing that moves the
// page under the box ever re-places it, it kills it: a scroll, a resize, a pan,
// a filter, a write.
//
// Keeping the old top-left whatever the new content is was the other option, and
// it loses a submenu. A `position: fixed` box that now runs past the bottom of
// the window is not scrolled to by the page, so the last statuses of a ladder
// opened near the foot of a short window would be unreachable altogether.
// `max-height: 70vh; overflow-y: auto` answers a list too tall for the WINDOW;
// it does not answer one placed past its edge.
function popPlace() {
  // Back to the corner BEFORE it is measured. A `position: fixed` box with a
  // `left` and no `right` is shrink-to-fit against what is left of the viewport,
  // so the same three items measured 54.17px wide sitting at the previous menu's
  // `left: 1250px` and 111.56px at the origin — headless Chrome at 1280px,
  // 2026-09-18. `placeFloat` reads that width to decide which side of the
  // pointer to draw on, so a stale one flips a box that fits and clamps one that
  // does not.
  POP.style.left = '0px';
  POP.style.top = '0px';
  placeFloat(POP, POP_AT.x, POP_AT.y);
}

function popDrill(item) {
  // **Exactly one level of nesting**, enforced here rather than promised in a
  // comment. The design traded the flyout for one level; a descriptor carrying
  // `items` two deep would get a `‹ Back` that pops to a list nothing else can
  // reach, and the keyboard would have two meanings for ArrowLeft.
  if (POP_STACK.length > 1) return;
  POP_SAID = '';
  const chosen = item.items() || [];
  POP_STACK.push({
    label: item.text,
    from: item.kind,
    items: [{kind: 'back', text: '‹ Back', stays: true, run: popBack}, ...chosen],
  });
  popDraw();
  // Where the keyboard lands on the way in: the current value if this list has
  // one, because that is where somebody reading a ladder is looking, and the
  // first real item otherwise. Never `‹ Back` — that is the way out of a list
  // nobody has read yet — and never `<body>`.
  const at = chosen.findIndex(one => one.checked);
  popFocus(at === -1 ? 1 : at + 1);
}

function popBack() {
  if (POP_STACK.length < 2) return;
  POP_SAID = '';
  const from = POP_STACK.pop().from;
  popDraw();
  // Back onto the item that was drilled into, found by its stable slug rather
  // than by the index it had. `POP_SAID` is cleared two lines above precisely so
  // that a refusal drawn over the level below cannot shift everything by one —
  // and by name it would not matter if it did.
  const at = popControls().findIndex(one => one.dataset.kind === from);
  popFocus(at === -1 ? 0 : at);
}

// A refusal: said, and drawn where the reader is looking.
//
// `announce` alone is not enough on this app's own pages. It writes into `#state`
// where the page has one — the graph does — and into the shell's hidden region
// otherwise, which is the table: a refusal only a screen reader hears is a menu
// that looks like it did nothing at all. So it is also drawn, as a refused item
// at the top of the level that is up, which keeps it a real `menuitem` inside a
// `role="menu"` and gives it the dim treatment every other refusal has.
//
// The menu stays usable: every item it had is still under this one.
function popSay(text) {
  announce(text);
  // A write whose commit landed has already closed the box, and what failed
  // after it is the re-read. There is nothing to draw in and the sentence has
  // been said, which is the whole of what that case needs.
  if (POP.hidden) return;
  // **A refusal keeps the form open with everything typed still in it**, which
  // is the whole reason the form is a face of this box rather than a navigation
  // to somewhere else. So the sentence goes into the form's own list and nothing
  // is rebuilt — the controls are the same elements they were a moment ago, and
  // the values in them are the reader's.
  if (POP_FORM) {
    popFormSays([text]);
    // Onto the reason. The keyboard was on Save; the control it was on is still
    // there, so this is a move and not a rescue — but what somebody who has just
    // pressed Save needs to read is why it did not happen.
    POP_FORM.why.focus();
    return;
  }
  // And the confirmation keeps what it is asking about, for a sharper version of
  // the same reason. The refusal a delete gets is usually that the plan moved
  // under the panel, and the next thing that has to happen is that the panel
  // asks again — which it cannot do if this call has replaced it with a list of
  // menu items. `popDraw` below is exactly that replacement.
  if (POP_CONFIRM) {
    popConfirmSays([text]);
    POP_CONFIRM.why.focus();
    return;
  }
  POP_SAID = text;
  popDraw();
  // Onto the reason, which is what somebody who has just pressed an item needs
  // to read. Without this the focused control is one `replaceChildren` has
  // thrown away, and focus falls to `<body>`.
  popFocus(0);
}

// Where to open when the coordinates are a pointer's, and where to open when
// they are not. `ContextMenu` and Shift+F10 deliver a `contextmenu` event that
// bubbles like any other, so the menu comes free from the same listener — but
// the coordinates do not: Chrome reports the focused element's box and Firefox
// has reported 0,0. Without this the menu opens in the top-left corner, and on
// the table, where a roving-tabindex grid is the whole keyboard story, that is
// the most likely path a keyboard reader takes.
//
// A real press at exactly 0,0 is placed against the focused element instead.
// That is one pixel of the window traded for every keyboard open, and a press in
// the very corner still gets a menu beside it.
function popAt(x, y) {
  if (Number.isFinite(x) && Number.isFinite(y) && (x || y)) return {x: x, y: y};
  const focused = document.activeElement;
  // `<body>` is what `activeElement` answers when nothing is focused, and its
  // box is the whole document — a bottom edge that can be a screen and a half
  // below the window, which `placeFloat` would then flip and clamp against. The
  // corner is the honest answer when there is nothing to open beside.
  if (!focused || focused === document.body) return {x: 0, y: 0};
  const box = focused.getBoundingClientRect();
  // Under the focused element, at its left edge; `placeFloat` adds its own 14px.
  return {x: box.left, y: box.bottom};
}

// --- closing ----------------------------------------------------------------

// Close it. **No focus is moved**, because most of the signals that reach here
// are somebody reaching for something else — a press outside, a scroll, a
// resize, a filter, a write — and pulling the keyboard back to where the menu
// opened would take it off the thing they just pressed.
//
// **It takes no arguments, and that is a promise to the call sites rather than
// an accident**: the graph closes this with `cy.on('drag pan zoom', popClose)`
// and cytoscape hands a listener its own event object, so a signature with an
// optional flag in it would be called with a truthy one on every pan.
//
// **A form is not dismissed by somebody looking at the page, and that exemption
// is the one place cut 4 changes a rule cut 2 wrote down.** Every one of those
// signals means "the reader is reaching for something else", which for a list of
// words is a reason to get out of the way and for a half-filled form is a silent
// deletion of everything they typed — a click on the row behind it, a scroll of
// the table under it, the graph panned by a stray drag, and the work is gone
// with nothing said. Three of the last four audit rounds shipped a defect of
// exactly that shape. So a form leaves only by a decision: Escape, Cancel, or a
// commit that landed, all three of which go through `popDone`.
//
// The flag and not a parameter, because the signature above is a promise:
// `cy.on('drag pan zoom', popClose)` hands this cytoscape's own event object,
// and an optional argument would be truthy on every pan.
let POP_SHUTTING = false;

function popClose() {
  if (POP.hidden) return;
  if (POP_FORM && !POP_SHUTTING) return;
  POP.hidden = true;
  POP_ID = null;
  POP_GEN += 1;
  // The refusal goes with the box. The levels do not, for the same reason the
  // items do not — the next open replaces both — but a sentence about a write
  // that was refused a minute ago has no business being the first thing on the
  // next menu anybody opens.
  POP_SAID = '';
  // And so do the other two faces. Each is the box's face rather than a thing the
  // box holds, so a closed box is showing none of them and the next open builds
  // whichever one it wants.
  POP_FORM = null;
  POP_CONFIRM = null;
  POP.classList.remove('popforming', 'popasking');
  // The items are deliberately NOT cleared. `.drawmenu` clears its own on close
  // for a reason this box does not have — it had no `[hidden]` rule, so an
  // emptied box was how it stopped being a bar under the button — and clearing
  // here would take an anchor off the page inside the click that is opening its
  // tab. `#pop[hidden] { display: none }` is written out in the stylesheet, and
  // the next open replaces every child anyway.
  cardYields(false);
}

// Close it and give the keyboard back. Escape and a pressed item are the two
// closes where focus is inside this box; without the second half it lands on
// `<body>` and the next Tab starts from the top of the page, which `controls.py`
// records twice — once in the facet bar and once in the draft row.
function popDone() {
  const back = POP_RETURN;
  POP_RETURN = null;
  // **The one close that is a decision**, which is what lets `popClose` refuse
  // every close that is not — see the guard there. `finally`, because a throw
  // anywhere inside that call would otherwise leave the box permanently
  // dismissable by a scroll.
  POP_SHUTTING = true;
  try { popClose(); } finally { POP_SHUTTING = false; }
  // A return that is no longer in the document has nowhere to give the keyboard
  // back to, and there is nothing view-agnostic to fall back on: this box knows
  // a row's data and not the element that drew it. It cannot happen in cut 2 —
  // nothing here writes, and the only closes with focus inside the box are
  // Escape and a pressed item, neither of which replaces a tbody. Cut 3 writes,
  // and the view's own `wrote()` is where the redraw has to answer this.
  if (back && back.isConnected && back !== document.body) back.focus();
}

POP.addEventListener('keydown', event => {
  // Whatever is inside this box gets the key first. Nothing in cut 2 answers one
  // — the items are two buttons and a link — and the combobox and the form that
  // arrive in cut 4 do, which is the same question `table.py`'s `#askfor` panel
  // already asks of the suggestion list inside it: one press, one thing done.
  if (event.defaultPrevented) return;
  // **The form owns every key but one, and so does the confirmation.** ArrowDown
  // in a `<select>` picks the next option, Home and End move a caret, Space types
  // a space, and the block below would `preventDefault` all of them for a roving
  // tabindex over a list that is not on screen. The confirmation's two buttons
  // are walked by Tab like any other pair, which is what a `role="dialog"`
  // promises. Escape is the exception in both, because it has to be arbitrated
  // here whichever face is up — see the note at the foot of this listener for the
  // five meanings it has on the table.
  if (POP_FORM || POP_CONFIRM) {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    event.preventDefault();
    // Escape cancels and closes the box, rather than popping back to the menu
    // this face was opened from. A `‹ Back` into a list of items is the right
    // answer for a submenu, which holds nothing; here it would throw away
    // everything typed to show a menu nobody asked for, and the reader would
    // have pressed one key and lost their work without being asked.
    //
    // Two sentences, because they are two different pieces of news and this app
    // has already had one word mean three things on one screen. `Cancel` and
    // `Keep it` say exactly these, which is the point: a control and the key
    // that does the same thing may not report it differently.
    announce(POP_FORM ? 'nothing was changed' : 'nothing was deleted');
    popDone();
    return;
  }
  const items = popControls();
  const here = items.indexOf(document.activeElement);
  if (event.key === 'ArrowDown') { event.preventDefault(); popFocus(here + 1); return; }
  if (event.key === 'ArrowUp') { event.preventDefault(); popFocus(here - 1); return; }
  if (event.key === 'Home') { event.preventDefault(); popFocus(0); return; }
  if (event.key === 'End') { event.preventDefault(); popFocus(items.length - 1); return; }
  // ArrowRight drills in, ArrowLeft pops out — the two keys a desktop menu binds
  // for a submenu, kept even though this one replaces the list rather than
  // opening a panel to the right.
  //
  // Enter and Space are deliberately NOT answered here. A submenu parent is a
  // `<button>`, the browser fires `click` on both keys by itself, and
  // `popControl` routes that click to this same `popDrill` — so answering them
  // here as well would drill in and immediately drill in again.
  if (event.key === 'ArrowRight') {
    event.preventDefault();
    const item = POP_OF.get(document.activeElement);
    if (item && item.items) popDrill(item);
    return;
  }
  if (event.key === 'ArrowLeft') { event.preventDefault(); popBack(); return; }
  // A `<button>` is activated by both Enter and Space by the browser itself, and
  // an `<a>` only by Enter. So Space on a link is the one key this has to
  // answer; answering Enter as well would activate a button twice.
  if (event.key === ' ' && document.activeElement instanceof HTMLAnchorElement) {
    event.preventDefault();
    document.activeElement.click();
    return;
  }
  if (event.key !== 'Escape') return;
  // **Escape has five meanings on the table, and four of them are routed around
  // structurally rather than arbitrated.** This box is parked on
  // `document.body`, so it is inside none of the elements those four are bound
  // to, and an Escape pressed in here bubbles upwards past all of them:
  //
  //   1. `#askfor`'s own `onkeydown` — cancels the missing-fields question.
  //   2. an open cell editor's input — discards that cell's edit.
  //   3. the suggestion list inside that editor — stops the bubble, so closing
  //      the list does not also cancel the cell.
  //   4. the `tbody` — abandons the draft row, and cancels a move in the air.
  //
  // The fifth is not routed around, and it is why this line exists: the bulk
  // selection's handler is `addEventListener('keydown', …)` on the DOCUMENT, and
  // everything on the page is below that. Escaping out of this menu dropped the
  // reader's whole selection. So it is arbitrated here instead —
  // `test_escape_in_the_menu_does_not_discard_the_bulk_selection` is the test that
  // fails if this box is ever mounted inside the tbody and the four above stop
  // being structural.
  //
  // `stopPropagation` and not `stopImmediatePropagation`: the listener that must
  // not run is on a different element further up, so stopping the bubble is
  // enough, and stopping it immediately would be a claim about listener order on
  // THIS element that nothing here needs to make.
  event.stopPropagation();
  // Escape pops a level before it closes the box — ArrowLeft's other spelling,
  // and what every desktop menu does. At the top level there is nothing to pop
  // and it closes, which is what cut 2 shipped. `stopPropagation` is above the
  // branch on purpose: an Escape that merely backed out of a submenu must not
  // reach the document either, or the table's bulk selection is dropped by a key
  // that did not even shut the menu.
  if (POP_STACK.length > 1) { event.preventDefault(); popBack(); return; }
  popDone();
});

// The roving tabindex. Exactly one item is in the Tab sequence and it is the one
// with focus, so Tab leaves the menu instead of walking it.
function popFocus(at) {
  // `.popitem` and not `POP.children`, which is the same list today and is one
  // element away from not being: everything drawn in this box is an item, and a
  // query that says so cannot be thrown off by whatever a later cut puts beside
  // them.
  const items = popControls();
  if (!items.length) return;
  const want = (at + items.length) % items.length;
  items.forEach((item, index) => { item.tabIndex = index === want ? 0 : -1; });
  items[want].focus();
}

// **The menu never moves once placed; it only dies.** Six signals, and the
// listeners are bound once rather than per open — each is one `hidden` test on a
// page that is doing something else anyway.
//
// `pointerdown` and not `click`, so a menu over the thing somebody is reaching
// for is gone before the press lands rather than after it; the reason is written
// out at `controls.py`. Capture phase, so it is gone before the listener on
// whatever is under it runs.
//
// This is also the whole of the ordering between one menu and the next, and it
// is measured rather than assumed — headless Chrome, 2026-09-18, a trusted right
// press through CDP reports `pointerdown`, then `mousedown`, then `contextmenu`.
// So a right-click on a second row closes the first menu here and opens the
// second from the `contextmenu` that follows, in that order, and there is no
// window in which this listener can shut a box that was opened by the same
// press.
document.addEventListener('pointerdown', event => {
  if (POP.hidden || POP.contains(event.target)) return;
  popClose();
}, true);
// Capture, because `scroll` does not bubble from the element that scrolled: the
// table's rows scroll inside `.table-scroll` and a listener on the window would
// never hear it.
//
// And excluding the box itself, which is the same exclusion the `pointerdown`
// listener above makes and for a sharper reason: `#pop` is `overflow-y: auto`, so
// a menu long enough to overflow scrolls — and ArrowDown onto an item below the
// fold scrolls it, through `popFocus`. Without this, the first long menu closes
// itself the moment somebody arrows down it. Cut 2's three items cannot overflow,
// which is exactly why the guard has to be written now rather than found later.
document.addEventListener('scroll', event => {
  if (!POP.hidden && POP.contains(event.target)) return;
  popClose();
}, true);
addEventListener('resize', popClose);
// And the half of that a form needs instead, because `popClose` refuses to shut
// one. A box placed at a pointer in a 1400px window is a box that can be
// entirely outside a 700px one, and a `position: fixed` element is the one thing
// on the page there is no way to scroll back into view. `placeFloat` clamps at
// 8px and flips against the far gutter, so re-placing is strictly better than
// leaving it where the old window put it.
//
// A second listener on the same event rather than a branch inside `popClose`:
// that function's job is to shut the box, and the two things wanted here are
// "shut it" and "move it", which are opposites.
addEventListener('resize', () => { if (POP_FORM && !POP.hidden) popPlace(); });
addEventListener('openproj:filter', popClose);
// **Only when something was actually committed**, which is what the sha says.
//
// `openproj:wrote` fires in a `finally` on every write path in this app,
// refusals included — it has to, because the shell COUNTS it against
// `openproj:writing` and one event held back stops the moved-banner for ever.
// Cut 2 bound `popClose` to it bare, which was right while nothing here wrote:
// every such event was somebody else's. Now that this menu writes, a bare close
// would take a refusal off the screen along with the reason it gave, half a
// tick after drawing it.
//
// So: a sha means the plan moved and this menu is about a record as it was a
// moment ago, which is a menu that has to die. No sha means nothing moved.
//
// `event.detail` is a `CustomEvent`'s own payload and not a server's answer,
// which is the one receiver `tests/test_writes.py` allows by name.
//
// **A form survives this, along with the other five signals**, and the guard
// that makes it so is in `popClose`. It is not an oversight that a plan which
// moved under a half-filled form does not take it away: the write that form is
// about to make carries the commit the page was rendered at, which is now stale,
// so the store answers 409 and
// `refusal()` reads the compare-and-swap report into the box beside the boxes
// somebody has just typed into. Killing the form instead would throw the typing
// away to deliver the same news less usefully.
//
// (The stale value is not NAMED here, and that is not squeamishness: this half of
// the script ships on the static export and on a reader's page, and
// `test_the_static_export_offers_no_editing_at_all` sweeps those bytes for that
// word as a plain substring. A comment ships in the page. The same trap took a
// CSS comment in cut 2.)
addEventListener('openproj:wrote', event => { if (event.detail) popClose(); });

// A right press INSIDE the menu is the browser's business and not ours. Its
// default action is deliberately left alone — that is half the reason `Open in
// new tab` is a real `<a>` — and it is stopped from reaching the view's own
// `contextmenu` listener, which is on the document on at least one of the three
// and would answer it by rebuilding this box under the press.
POP.addEventListener('contextmenu', event => { event.stopPropagation(); });

// --- copy link --------------------------------------------------------------

// The absolute URL and not the relative one the page links by: what goes on the
// clipboard is pasted somewhere else, and `detail.html#pop-art` is not a link
// anywhere else.
//
// **The hand-made copy first, and the Clipboard API as the fallback.** That is
// the wrong way round by age and the right way round by what each one answers,
// and the reason is a measurement on the case this has to work in. On a
// `file://` page in headless Chrome, 2026-09-18: `isSecureContext` is TRUE and
// `navigator.clipboard.writeText` exists, so a feature test passes — and the
// promise it returns then neither resolved nor rejected within 300ms, because
// there is no clipboard to write to and no prompt to ask with. A `.catch()`
// fallback never runs, and "announce either way" quietly becomes announce
// neither way. `execCommand('copy')` is deprecated, is implemented everywhere,
// and answers `true` or `false` in the same tick, which is the whole of what
// this needs.
function popCopy(href) {
  const url = new URL(href, location.href).href;
  // Said once, by whichever path answers first, and said either way. A refusal
  // carries the link so that hearing it is still worth something: the reader
  // asked for this URL, and a live region that says only "could not copy" has
  // taken the answer away as well as the clipboard.
  let spoken = false;
  const say = copied => {
    if (spoken) return;
    spoken = true;
    announce(copied ? 'Link copied: ' + url : 'Could not copy. The link is ' + url);
  };
  if (popCopiedByHand(url)) { say(true); return; }
  if (!navigator.clipboard || !navigator.clipboard.writeText) { say(false); return; }
  navigator.clipboard.writeText(url).then(() => say(true), () => say(false));
  // **A promise that never settles is not a hypothetical here**, which is the
  // measurement above: on a `file://` page in headless Chrome that `writeText`
  // neither resolved nor rejected, so without this line the item was pressed and
  // nothing at all was announced — checked by driving this menu, 2026-09-18.
  // 600ms because a granted clipboard write resolves in microseconds and a
  // refusal that arrives a second after the press is a refusal about nothing.
  setTimeout(() => say(false), 600);
}

function popCopiedByHand(url) {
  const box = document.createElement('textarea');
  box.value = url;
  // `readonly` so a soft keyboard does not come up, and off the side of the
  // window rather than `hidden` or `display: none`: an unrendered box has no
  // selection, and `execCommand('copy')` copies the selection and nothing else.
  box.setAttribute('readonly', '');
  box.style.position = 'fixed';
  box.style.top = '-1000px';
  document.body.append(box);
  box.select();
  let copied = false;
  try { copied = document.execCommand('copy'); } catch (error) { copied = false; }
  box.remove();
  return copied;
}

// --- drawn and run ----------------------------------------------------------
//
// These live in the READ half although they were written beside the write
// items, and the reason is that a reader's page draws items and runs them too:
// `popControl` builds every control there is, `POP_OF` remembers which
// descriptor each came from, `popRan` is what a press lands in, `popPart` draws
// the spans a control is made of, `popTitle` names a record in a sentence, and
// `POP_FORM` / `popFormSays` are read by `popClose`, which every page has.
//
// The split is by what a name DOES, not by which section it was written in.
// Splitting by the section banners is what shipped a reader's page that threw on
// `POP_OF` — a `const`, so not hoisted, so a ReferenceError rather than an
// `undefined`, which in a classic script takes the whole block and therefore the
// menu with it. CI found that; three review passes had not.

// What to call a record in a sentence. The same fallback the box's own
// `aria-label` uses: a record with no title is still a record you can act on.
const popTitle = row => row.title || row.id;

// --- the form ---------------------------------------------------------------
//
// **Fields only, and that is settled rather than a first cut.** The body stays
// on the record's own page, which has Ace, co-editing seats, a draft receipt and
// a `#grip` to widen it with. A markdown editor in a floating box would be
// competing with the page that does it properly, and the reader would learn that
// two surfaces write the same document differently.
//
// Three modes, one function:
//
//   `new`   a kind, with `parent` filled and LOCKED — `New child ▸ <kind>`.
//   `edit`  every field `_editable_for` offers this kind — `Edit…`.
//   `only`  a named few — `Assign parent…`, and a status the gate refuses.
//
// The live form, or `null` when the box is showing items. Every other function
// in this file asks it to tell the two faces of the box apart.
let POP_FORM = null;

// --- what the form says -----------------------------------------------------

// The refusals, and the ONE place in this box that re-places itself.
//
// **The form is the exception to "the menu never moves once placed; it only
// dies", and the reason is concrete rather than aesthetic.** A menu's content is
// fixed the moment it is drawn; a form's is not — a refusal list growing under a
// box already near the foot of the window pushes its own Save button off the
// bottom, and a `position: fixed` box is not something the page can be scrolled
// to. `popPlace` places against `POP_AT`, the pointer this box was opened at, so
// the corner is kept for as long as the new content fits and flips or clamps
// exactly as the first placement would have. What the design's rule is really
// about stays true: nothing that moves the page UNDER this box re-places it.
function popFormSays(lines) {
  const form = POP_FORM;
  if (!form || !form.why) return;
  popLines(form.why, 'form-why-line', lines);
}

// One refusal list, filled one way, for the two faces of this box that have one.
// The form's and the confirmation's are the same element under the same rules —
// `textContent` and never `innerHTML`, hidden when empty, re-placed afterwards —
// and two copies of that is how one of them comes to draw a record's title as
// markup on the day somebody makes the other one faster.
function popLines(list, slug, lines) {
  list.replaceChildren(...lines.map(line => {
    const said = document.createElement('li');
    said.dataset.kind = slug;
    // `textContent`, never `innerHTML` — a refusal carries a record's title and
    // whatever the server chose to say about it.
    said.textContent = line;
    return said;
  }));
  list.hidden = !lines.length;
  popPlace();
}

// --- the confirmation -------------------------------------------------------
//
// **The box's FOURTH face**, and `POP_CONFIRM` is declared in this half for the
// reason `POP_FORM` is: `popClose`, `popSay` and the key handler all ask which
// face is up, and all three ship on a page that cannot write. What BUILDS this
// face, and everything it asks the server, is in the other half.
//
// The panel that goes with it is the record's own page's, which has asked this
// question with these words since it had a Delete button. It is never a browser
// `confirm()`, and the argument is one this repository has already written down
// twice: a native dialog cannot say which record it is about in the words this
// page uses, cannot show the server's reason when the delete is refused, and
// stops every other script until somebody clicks it. To which this box adds the
// one that decided cut 5 — a `confirm()` cannot list a cascade, and the cascade
// is the whole of what somebody is agreeing to.
//
// **Unlike the form, it does NOT resist dismissal.** A form holds everything
// somebody typed and the six signals would delete it in silence; this panel
// holds a question, and a panel that will not go away when you reach past it is
// a worse thing to put in front of a destructive control than one that closes
// too easily. Reaching for something else cancels it, which is the answer you
// wanted.
let POP_CONFIRM = null;

function popConfirmSays(lines) {
  const asking = POP_CONFIRM;
  if (!asking || !asking.why) return;
  popLines(asking.why, 'confirm-why-line', lines);
}

function popControl(item) {
  const control = document.createElement(item.href ? 'a' : 'button');
  if (item.href) {
    control.href = item.href;
    control.target = '_blank';
    // Implied by `target="_blank"` in every current browser, and written out
    // anyway: it is one attribute, and the implication is a browser default,
    // which is the kind of thing that is true until the page is opened in the
    // one browser where it is not.
    control.rel = 'noopener';
  } else {
    control.type = 'button';
  }
  control.className = 'popitem';
  control.dataset.kind = item.kind;
  // `menuitemradio` where the item is one of a set of values with a current one
  // — the status ladder, the owner list — because `aria-checked` on a plain
  // `menuitem` is ignored, and the check drawn beside it would then be a mark
  // only a sighted reader gets.
  control.setAttribute('role', item.checked === undefined ? 'menuitem' : 'menuitemradio');
  if (item.checked !== undefined) control.setAttribute('aria-checked', String(item.checked));
  // Drills down in the same box, so the list this opens REPLACES this control:
  // there is no moment at which it is expanded, and `aria-expanded` would have
  // to be permanently false. `haspopup` alone is the honest half.
  if (item.items) control.setAttribute('aria-haspopup', 'menu');
  if (item.glyph) control.append(popPart('popglyph', item.glyph, true));
  control.append(popPart('poptext', item.text, false));
  // One slot behind the word, and the two things that can be in it never
  // co-occur: `›` means there is a list behind this, `•` means this is the value
  // the record holds.
  //
  // **Both were measured against the vendored face rather than picked.** The
  // conventional pair is `▸` and `✓`, and each was wrong for its own reason.
  // `▸` (U+25B8) is not in the inlined Inter subset at all — probed in headless
  // Chrome, 2026-09-18, by measuring it under `"Inter var"` alone against a
  // family that does not exist and getting the same width both ways — so it is
  // a tofu box on a machine with no fallback for it, which is the argument that
  // already keeps `⠿` off the table's drag handle. `‹` and `›` ARE in the
  // subset, and they are the pair `‹ Back` is already written with.
  //
  // `✓` is in the subset, and it collides: it is `done`'s own status glyph, so a
  // status ladder would draw one `✓` meaning "this rung is Done" and another
  // meaning "this is the rung it is on", in the same row. `•` is in the subset,
  // is in none of the six status marks, and is what a `menuitemradio` is
  // conventionally drawn with anyway — a filled dot is the radio's mark and a
  // tick is the checkbox's.
  const mark = item.items ? '›' : item.checked ? '•' : '';
  if (mark) control.append(popPart('popmark', mark, true));
  // Roving tabindex, set properly by `popFocus`. -1 here so a control that has
  // never been focused is out of the Tab sequence: Tab leaves the menu, and the
  // arrows are what walks it.
  control.tabIndex = -1;
  if (item.why) {
    control.setAttribute('aria-disabled', 'true');
    control.dataset.why = item.why;
  }
  control.onclick = event => popRan(event, item);
  POP_OF.set(control, item);
  return control;
}

// Which descriptor a drawn control came from, for the keys that act on the item
// rather than on the element — ArrowRight has to know whether there is a list
// behind this row. A WeakMap and not a property on the element: every control is
// thrown away and rebuilt on every draw, and this lets them be collected with
// them.
const POP_OF = new WeakMap();

// One part of an item. Three of them and not one `textContent`, so that the two
// marks can be given a width that does not shrink and hidden from the
// accessibility tree — a reader who hears both the glyph and the word hears the
// status twice.
//
// `textContent`, never `innerHTML`. This is the JavaScript half of the one
// escaping boundary, and an item's text carries a record's title.
function popPart(className, text, decorative) {
  const part = document.createElement('span');
  part.className = className;
  part.textContent = text;
  if (decorative) part.setAttribute('aria-hidden', 'true');
  return part;
}

function popRan(event, item) {
  if (item.why) {
    // A refused item answers and the menu stays up. `preventDefault` because an
    // `aria-disabled` link is still a link: `aria-disabled` is a statement to
    // the accessibility tree and not to the browser, which is exactly why it was
    // chosen over `disabled`.
    event.preventDefault();
    announce(item.why);
    return;
  }
  // A submenu parent replaces the list and the box stays up, so it must not fall
  // through to the dismissal below the way every other item does.
  if (item.items) { popDrill(item); return; }
  // **A `run` that returns a promise owns the dismissal.** Everything else an
  // item does here is instantaneous — navigate, copy, say something — and the
  // box goes with it. A write is not: it has to stay up long enough to draw a
  // refusal in, and a box that closed under an answer which has not arrived
  // makes a refused write look exactly like one that landed. `popWrite` calls
  // `popDone` itself when the commit comes back.
  if (item.run) {
    const going = item.run();
    if (going && typeof going.then === 'function') return;
  }
  // And `stays` for the items whose job is to leave the box open showing
  // something else rather than to act — `popItems` says which those are, and it
  // was only `‹ Back` until the forms and `Delete…` arrived. `‹ Back` is a plain
  // synchronous `run`, so without this the mouse path through it CLOSED the menu
  // while the keyboard path — ArrowLeft and Escape, which call `popBack` directly — popped a level
  // correctly. Two ways to do one thing, one of them wrong, and the keyboard
  // probes could not see it.
  if (item.stays) return;
  // After the run and not before it, which is the opposite of `.drawmenu`'s
  // `choose()`. `Copy link` selects a scratch textarea and takes it off the page
  // again, so it ends with focus on `<body>`; giving the keyboard back has to be
  // the last thing that happens or it is undone a line later.
  //
  // For a link item there is no `run` and this hides the box inside the click
  // that is still being dispatched. The navigation happens anyway — measured in
  // headless Chrome on 2026-09-18, both with the anchor hidden and with it
  // detached outright, and the hash changed in both — and the box keeps its
  // items on close so the anchor is only hidden and not removed.
  popDone();
}
"""


_POP_WRITE_JS = r"""
// --- the write half ---------------------------------------------------------
//
// The reader's word for a stored identifier, and a field's label. Both out of
// the schema and never written down here: `HUMAN` and `LABELS` (`tokens.py`) are
// one map each for the whole app, because five pages inventing their own is how
// `in_progress` came to be spelled three ways on one screen.
const popHuman = value => (POP_SCHEMA.human || {})[value] ?? (value ?? '');
const popLabel = field => (POP_SCHEMA.labels || {})[field] || field;
// And what to call one this menu only has the id of — the parent in `Take out of
// "X"`. Asked of the HOST, which is the only thing that knows the other rows:
// `DATA.rows` on the table, the node's own `data()` on the graph.
function popTitleOf(id) {
  const row = POP_HOST && POP_HOST.rows(id);
  return (row && row.title) || id;
}

function popWriteItems(row) {
  if (!POP_HOST.may || !POP_HOST.may()) return [];
  // A host whose reader may write, on a page rendered without a schema, is a
  // wiring mistake and not a reader-only page: `_pop_js` takes the index and
  // this view did not give it one. Said out loud and in the box, for the reason
  // `popMenu` calls `cardYields` with no `typeof` guard — the alternative is a
  // menu that quietly has no write half on the one view somebody has just wired,
  // which looks exactly like a menu that is working.
  if (!POP_SCHEMA)
    return [{kind: 'no-schema', text: 'Editing is unavailable here',
             why: 'This page was rendered without the menu\'s schema.'}];
  // The ORDER is the design's table: what makes a record, what changes this
  // one, where it is filed, then what this view can do, then the three that only
  // look. `New child ▸` is first because it is the thing that was asked for, and
  // `Delete…` is last — `popItems` lifts it out by its slug and puts it under
  // even the three read items, so that the one irreversible thing on this menu
  // has no neighbour anybody reaches for by accident.
  return [popNewChildItem(row), popEditItem(row), popStatusItem(row),
          popPriorityItem(row), popOwnerItem(row), popParentItem(row), popTakeOutItem(row),
          // No refusal arm, and that is the record page's own answer rather than
          // an omission: `may_write` is the only gate on the Delete button there
          // (`detail.py`), because every record a writer may write is a record
          // they may take out of the plan. What the delete would take WITH it is
          // not a reason to withhold the item — it is the question the panel
          // exists to put, and `popAsk` is where it is asked.
          {kind: 'delete', text: 'Delete…', stays: true, run: () => popAsk(row)}];
}

// Whether a field has nothing in it — the four ways one can be unset, in one
// place, because `holds` (`table.py`) records what it costs to have them written
// out twice: an `assignees: []` that read as a value in one copy and as unset in
// the other is a row the gate exempts and the form then asks about.
function popEmpty(value) {
  return value === null || value === undefined || value === ''
    || (Array.isArray(value) && value.length === 0);
}

// Whether this row has a value for that field at all.
function popHolds(row, field) { return !popEmpty(row[field]); }

// What this status will make the server refuse the row without, and the row has
// not got. The same map `missingFor` (`table.py`) asks — `required_at()`, which
// is derived by running the gate over a blank record rather than written beside
// it, so it cannot drift from the rule it mirrors.
//
// **One of that function's filters is deliberately not here.** `missingFor`
// drops any field the table cannot edit, because the panel it feeds has to offer
// a box for every field it names. This menu offers no boxes at all — cut 3 has
// no form — so a field it could not write is still a reason the write would be
// refused, and dropping it would draw the item as available and let the server
// answer for it.
function popMissing(row, status) {
  const gates = (POP_SCHEMA.required || {})[row.kind] || {};
  return Object.keys(gates)
    .filter(field => gates[field].includes(status))
    // `review_waived` is honoured for the reason `missingFor` honours it: it is
    // the escape hatch from the reviewer rule, and asking for reviewers on a row
    // that has waived them is a nag rather than a question.
    .filter(field => !(field === 'reviewers' && row.review_waived))
    .filter(field => !popHolds(row, field));
}

// The gate's refusal, in the app's own words.
//
// **What is shared with `askFor` (`table.py`) is everything that can drift, and
// not the sentence itself.** The fields come from `required_at()` through
// `popMissing`, which is the rule rather than a copy of it; the names come from
// `LABELS` and `human`, which is what every other control here calls them; and
// the opening clause is `askFor`'s. The rest is this box's own wording, because
// `askFor` is a heading over a box per field and this is a refusal with no boxes
// at all — it has to say where to go instead. Do not go looking for a shared
// string; look at the three inputs, which are where a drift would come from.
//
// **This is now the branch that cannot be answered here rather than the whole
// case.** Cut 3 drew every gated status refused because there was no form to
// open; cut 4 opens one on the missing fields with the new status pre-filled and
// saves both in one commit, which is what `askFor` does today. What is left for
// this sentence is a missing field the form has no box for — `popMissing` reads
// `required_at` and the form draws `_editable_for`, and those are two maps — so
// a rule could name a field no form here can offer. Drawing an item that opened
// a form which could not answer the gate would be worse than saying so.
function popNeeds(row, status, fields) {
  const named = fields.map(popLabel).join(' and ');
  return `${popHuman(status)} needs ${named}, and ${popTitle(row)} has not got `
    + `${fields.length === 1 ? 'it' : 'them'}. Add `
    + `${fields.length === 1 ? 'it' : 'them'} on the record's own page.`;
}

function popStatusItem(row) {
  const ladder = (POP_SCHEMA.statuses || {})[row.kind] || [];
  // `statuses: ()` on the ladder is how a rung says it reads no status at all —
  // jcanton, 2026-08-20: a codebase is not `in_progress` — and it is the same
  // fact `_row` empties the cell by. Drawn refused rather than left out, because
  // a control that disappears teaches nothing about why.
  if (!ladder.length)
    return {kind: 'status', text: 'Status', why: `A ${row.kind} has no status.`};
  return {kind: 'status', text: 'Status',
          items: () => ladder.map(status => popStatusChoice(row, status))};
}

function popStatusChoice(row, status) {
  const item = {kind: 'status-' + status, text: popHuman(status),
                glyph: (POP_SCHEMA.glyphs || {})[status] || '',
                checked: row.status === status};
  // The status it already has writes nothing. The server would take it — every
  // write path here relies on `_merge_frontmatter` skipping a key whose stored
  // value equals the one being sent — but a commit is a line in somebody's
  // history, and "set it to what it is" is not a thing anybody meant to do.
  if (item.checked) {
    item.run = () => announce(`${popTitle(row)} is already ${popHuman(status)}`);
    return item;
  }
  // **The gate is answered, not fought and no longer merely reported.** A status
  // whose `required_at` names fields this record has not got cannot be written,
  // so picking it opens the form on exactly those fields with the new status
  // already in its box — and one Save commits the status and the answers
  // together. Two commits would leave the plan holding, for the length of the
  // first one, a record the validator refuses; that is `askFor`'s argument
  // (`table.py`) and it is why the question is asked BEFORE the write there too.
  const missing = popMissing(row, status);
  if (missing.length) {
    // Every missing field has to be one the form can draw, or the form opens on
    // a gate it cannot answer. See `popNeeds`.
    const boxes = (POP_SCHEMA.fields || {})[row.kind] || [];
    if (!missing.every(field => boxes.includes(field))) {
      item.why = popNeeds(row, status, missing);
      return item;
    }
    item.stays = true;
    item.run = () => popForm({
      mode: 'edit', row: row,
      // The status first and then what it needs, which is the order the sentence
      // over the boxes reads in. It is drawn rather than sent invisibly: this
      // form's one job is that nothing is committed that the reader cannot see.
      only: ['status', ...missing],
      // Open, so the box asks rather than waiting to be clicked: somebody who
      // chose a gated status has already said what they are doing.
      opens: missing,
      values: {status: status},
      // `askFor`'s own opening clause, because it is the same question asked by
      // the same rule about the same record — see `popNeeds` for what is shared
      // and what is not.
      label: `${popHuman(status)} needs ${missing.length === 1 ? 'this' : 'these'}`,
      verb: 'Save',
    });
    return item;
  }
  item.run = () => popWrite(row.id, {status: status},
    `${popTitle(row)} is now ${popHuman(status)}`);
  return item;
}

// **Priority, directly below the status and built like it.** jcanton, 2026-09-18:
// "in the right-click menu add priority just below status please, I didn't
// notice we didn't have it there".
//
// Two differences from `popStatusItem`, and both are the ladder's rather than
// this menu's. The vocabulary is ONE list for every kind — `PRIORITIES`, not a
// per-rung tuple — so there is nothing to look up per row; and what varies is
// whether the kind reads the field at all, which is the `unread_fields` question
// the Owner item already asks (`priority` is in `_WORK_FIELDS`, so a product
// holds none).
//
// **And no gate.** `required_at` names no status that demands a priority, so
// there is no `popMissing` arm here and no form to open: every rung of this
// ladder is writable on every record that reads the field, which is the whole
// reason this item is three lines where the status item is sixty.
function popPriorityItem(row) {
  if (((POP_SCHEMA.unread || {})[row.kind] || []).includes('priority'))
    return {kind: 'priority', text: 'Priority', why: `A ${row.kind} holds no priority.`};
  return {kind: 'priority', text: 'Priority',
          items: () => (POP_SCHEMA.priorities || []).map(one => popPriorityChoice(row, one))};
}

function popPriorityChoice(row, priority) {
  const item = {kind: 'priority-' + priority, text: popHuman(priority),
                // The rising block, which is what the chips and the graph's
                // nodes draw — `cardMark` off the shell's own map, so the menu
                // cannot disagree with the card it opens over. The status item
                // reads its glyph out of the schema because a status glyph was
                // shipped there before the card existed; this one has no reason
                // to add a second copy.
                glyph: typeof cardMark === 'function' ? cardMark('priority', priority) : '',
                checked: (row.priority || null) === priority};
  // Already there writes nothing, for the reason the status choice says: the
  // server would take it, and "set it to what it is" is not a line anybody meant
  // to put in the history.
  if (item.checked) {
    item.run = () => announce(`${popTitle(row)} is already ${popHuman(priority)} priority`);
    return item;
  }
  item.run = () => popWrite(row.id, {priority: priority},
    `${popTitle(row)} is now ${popHuman(priority)} priority`);
  return item;
}

// The one value in the owner list that is not a person.
const POP_NOBODY = '— nobody —';

function popOwnerItem(row) {
  // `owner` is one of the nine fields a container does not read
  // (`unread_fields`), which is why `_row` withholds the value and why the
  // table's status cell drew an empty box that still committed. Refused here
  // before anything is sent, the way the graph refuses its edge gestures at tap
  // time.
  if (((POP_SCHEMA.unread || {})[row.kind] || []).includes('owner'))
    return {kind: 'owner', text: 'Owner', why: `A ${row.kind} holds no owner.`};
  return {kind: 'owner', text: 'Owner', items: () => {
    // The same people the table's own suggestion list offers — `_suggestions`
    // (`controls.py`), read off every record in the corpus. A second list would
    // be a second answer to "who is on this plan", and the first thing it would
    // do is disagree with the box next to it.
    const items = (POP_SCHEMA.people || []).map(login => popOwnerChoice(row, login, login));
    // Last, and spelled as a value rather than as a verb: the list is a set of
    // answers to "who owns this" and "nobody" is one of them, not a command.
    items.push(popOwnerChoice(row, null, POP_NOBODY));
    return items;
  }};
}

function popOwnerChoice(row, login, text) {
  // `null` and not `''`: `patch_text` round-trips a value, so `owner: ''` is a
  // field that is present and empty while `owner:` with nothing after it is the
  // shape every other unset field in this corpus already has.
  const item = {kind: login === null ? 'owner-nobody' : 'owner-' + login, text: text,
                checked: (row.owner || null) === login};
  if (item.checked) {
    item.run = () => announce(login
      ? `${popTitle(row)} is already owned by ${login}`
      : `${popTitle(row)} already has no owner`);
    return item;
  }
  item.run = () => popWrite(row.id, {owner: login}, login
    ? `${popTitle(row)} is now owned by ${login}`
    : `${popTitle(row)} has no owner`);
  return item;
}

// **Three sentences, not two.**
//
// `_row` (`rows.py`) nulls a parent that is not in `index.plan` and sets
// `off_plan_parent` beside it, because an inbox id may not reach these pages'
// bytes. So `row.parent` being empty means one of two completely different
// things: nothing holds this record, or something does and this view cannot draw
// it. Telling the second one it is inside nothing is the bug
// `tests/test_exclusion.py` was written for seen from the other side — and
// acting on it would overwrite a line the page never showed anybody, which the
// server cannot tell from the record page legitimately refiling it.
//
// The wording of the third is `moveTip`'s (`table.py`), which says the same
// thing about the same records for the drag gesture.
function popTakeOutItem(row) {
  if (row.off_plan_parent)
    return {kind: 'take-out', text: 'Take out',
            why: `${popTitle(row)} is filed under something this view cannot show `
                 + '— where it belongs is edited on its own page.'};
  if (!row.parent)
    return {kind: 'take-out', text: 'Take out',
            // Two sentences under one branch, because "not inside anything" and
            // "cannot be inside anything" are different news: the first is a
            // state somebody can change and the second is the ladder. `moveTip`
            // (`table.py`) already draws them apart for the drag gesture, off
            // this same map, and an error that implies a fix which does not
            // exist is the copy failure this repository names in as many words.
            //
            // Which kind that is comes off `PARENT_KINDS` and is not written
            // here: it was `project` until a `product` was added above it, and a
            // rule that names the top rung is a rule that is wrong the day the
            // ladder grows.
            why: ((POP_SCHEMA.parent_kinds || {})[row.kind] || []).length
                 ? `${popTitle(row)} is not inside anything.`
                 : `A ${row.kind} belongs to nothing, so there is nothing to take it out of.`};
  return {kind: 'take-out', text: `Take out of "${popTitleOf(row.parent)}"`,
    // `{parent: null}`, which is what `reparent(child, null)` (`table.py`) has
    // sent for this same gesture since it was a drag. Two spellings of "no
    // parent" would not even be the same write: `patch_text` round-trips, so
    // `parent: ''` writes an empty string into the file where `null` writes the
    // key with nothing after it.
    run: () => popWrite(row.id, {parent: null},
      `${popTitle(row)} is no longer inside anything`)};
}

// --- the three items that open a form ---------------------------------------
//
// **This is the answer to the question that started the whole design.** jcanton,
// 2026-09-18: "I'd like to be able to right-click a record in table and graph
// view and have the option of creating a child record", and then "can we make
// new-child stay on the same page? ... in both pages a new popup opens: the same
// as the floating menu but with editable fields (with parent pre-filled) and a
// save button that commits the new record?" — and, of `Edit…`, that it should
// open that same editable card. Yes to both, which is what these three are.

function popNewChildItem(row) {
  // The model's own `CHILD_KINDS`, read downwards off the ladder rather than
  // inverted from `parent_kinds` here. A third spelling of the ladder in the one
  // language nothing tests it in is the drift this schema exists to stop.
  const kinds = (POP_SCHEMA.child_kinds || {})[row.kind] || [];
  // Refused rather than left out, and the sentence is about the LADDER and not
  // about this record: nothing can be filed inside a task, ever, and an error
  // that implies a fix which does not exist is this repository's own named copy
  // failure. `moveTip` (`table.py`) draws the same distinction for the drag.
  if (!kinds.length)
    return {kind: 'new-child', text: 'New child',
            why: `Nothing is filed inside a ${row.kind}.`};
  return {kind: 'new-child', text: 'New child', items: () => kinds.map(kind => ({
    kind: 'new-child-' + kind, text: popHuman(kind),
    // `stays`, because `popRan` dismisses the box after a synchronous `run` and
    // this one has just filled it with a form. The same flag `‹ Back` carries,
    // and for the same reason: the run's whole job is to leave the box open
    // showing something else.
    stays: true,
    run: () => popForm({
      mode: 'new', kind: kind, parent: row,
      label: `New ${popHuman(kind).toLowerCase()} in "${popTitle(row)}"`,
      verb: `Create ${popHuman(kind).toLowerCase()}`,
    }),
  }))};
}

function popEditItem(row) {
  // A kind with no editable field at all would be a form with a heading and a
  // Save button. It cannot happen — every rung has a title — and it is said
  // rather than assumed, because what `_editable_for` offers is a function of
  // the model and this is the one item that draws all of it.
  if (!((POP_SCHEMA.fields || {})[row.kind] || []).length)
    return {kind: 'edit', text: 'Edit…', why: `A ${row.kind} has nothing to edit here.`};
  // The card, with nothing open. Every value in it is a thing you click, and
  // what you type is held in the box until Save — the same bargain as the box a
  // gated status opens, which is the whole of why this one changed. jcanton,
  // 2026-09-18: "I'd like them to be consistent, and I think I'd prefer them
  // both to have the save/cancel buttons and save only when clicking save, not
  // on every edit as I asked before."
  return {kind: 'edit', text: 'Edit…', stays: true, run: () => popForm({
    mode: 'edit', row: row,
    label: `Edit "${popTitle(row)}"`,
    verb: 'Save',
  })};
}

// Where this record is filed, as its own item, because it is the one field the
// menu cannot ask about with a list of words: the answer is another record.
//
// The four refusals are four different sentences and not one, exactly as
// `popTakeOutItem`'s three are. A ladder with nothing above this kind, a parent
// this view cannot show, a view that cannot list what it could be filed under,
// and a plan with nothing of the right kind on it are four states, and only two
// of them are anything a reader can act on.
function popParentItem(row) {
  const named = row.parent || row.off_plan_parent ? 'Change parent…' : 'Assign parent…';
  if (!((POP_SCHEMA.parent_kinds || {})[row.kind] || []).length)
    return {kind: 'parent', text: 'Assign parent…',
            why: `A ${row.kind} belongs to nothing, so there is nowhere to file it.`};
  if (row.off_plan_parent)
    return {kind: 'parent', text: named,
            why: `${popTitle(row)} is filed under something this view cannot show `
                 + '— where it belongs is edited on its own page.'};
  const candidates = popCandidates(row.kind, row.id);
  if (!candidates)
    return {kind: 'parent', text: named, why: popNoRows()};
  if (!candidates.length)
    return {kind: 'parent', text: named,
            why: `There is nothing on this plan that a ${row.kind} may be filed under.`};
  // The same card as `Edit…` — every field on it is still a field — with the one
  // somebody came here to change already open. `only` would draw a box about one
  // field, and the box is a card: a card of one row is not a card.
  return {kind: 'parent', text: named, stays: true, run: () => popForm({
    mode: 'edit', row: row, opens: ['parent'],
    label: `Where "${popTitle(row)}" is filed`,
    verb: 'Save',
  })};
}

// --- what the host knows about the other records ----------------------------
//
// **`rows(id)` answers about one record and the parent picker is a question
// about all of them**, so cut 4 adds two OPTIONAL calls to the host contract.
// Both are optional and both have an honest answer when they are missing,
// because the timeline registers neither and the static export has no host that
// could: `popServes` is a contract three views implement and a fourth might.
//
//   all:   () => [row, …]   every record this view could file something under.
//                           The table: `Object.values(DATA.rows)`. The graph:
//                           `cy.nodes().map(node => node.data())`.
//   shows: id => boolean    whether that record is on screen RIGHT NOW, filter
//                           and window included. The table: whether `draw()` put
//                           a `tr[data-id]` for it in the tbody.
//
// **Not read off the page instead.** `DATA.rows` is a name on the table and on
// the timeline and does not exist on the graph, whose payload is cytoscape
// elements — a menu that reached for it would be three menus, which is the thing
// `POP_SCHEMA` is baked to prevent. And `all()` is asked at the moment the item
// is drawn rather than cached, which is `attachDrawing`'s rule: a picker built
// from rows read when some earlier menu opened would offer a record that has
// since been deleted.
function popAllRows() {
  return (POP_HOST && POP_HOST.all && POP_HOST.all()) || [];
}

// The records this kind may be filed under, or `null` when this view cannot say.
// `null` and not `[]`, because "nothing may hold it" and "I do not know what
// could" are two different sentences and the item draws both.
function popCandidates(kind, exceptId) {
  if (!POP_HOST || !POP_HOST.all) return null;
  const allowed = (POP_SCHEMA.parent_kinds || {})[kind] || [];
  return popAllRows()
    // A record filed under itself is a loop. The server refuses it — `loop_made`
    // (`model.py`) — and the picker not offering it is not a second copy of that
    // rule: it is the one case a reader cannot have meant, and every other loop
    // is still the server's to find.
    .filter(row => row && row.id !== exceptId && allowed.includes(row.kind))
    .sort((one, two) => popTitle(one).localeCompare(popTitle(two)));
}

function popNoRows() {
  return 'This view cannot list the records here, so there is nothing to pick '
    + "from — where a record is filed is edited on its own page.";
}
// One counter for the ids that tie a `<label for>` to its control. Per page and
// not per form, because a `<datalist>` id is a document-wide reference too and
// two forms opened in one page life must not collide.
let POP_FIELD_N = 0;
// The one value in a picker that is not a record.
const POP_NOTHING = '— nothing —';

// **The box a right-click opens to edit a record is the hover card, and it is
// the same markup drawn by the same function.**
//
// jcanton, 2026-09-18, after two passes that merely resembled it: "I meant this
// card", "it should display the editable fields as the edit view", and — for
// how a value becomes a control without the box turning into a form — "it could
// be like the table where you have to click one field to enter edit mode for
// that field?".
//
// So `popDrawForm` calls `cardHtml` (`shell.py`) and wires what comes back.
// There is no second builder and no second stylesheet: what the card draws is
// what this draws, and the whole of the difference is that clicking a value
// here puts a control where the value was.
//
// **One way of committing: the values are held in the box and Save sends them
// together.** There were two, and the second is gone.
//
// A box opened on a record used to write each field as it was answered — blur
// saved, Escape discarded, one PATCH per field, which is `openEditor`'s bargain
// in the table to the letter and is what jcanton asked for on 2026-09-18. Two
// doors on the same box were what made him ask for the other thing later the
// same day: "when changing the status, e.g. to ready which requires reviewers
// and appetite, the editing card is shown (all good to here), this card has the
// save/cancel buttons at the bottom, while the card that shows up when selecting
// the edit menu doesn't and commits on each field change. I'd like them to be
// consistent, and I think I'd prefer them both to have the save/cancel buttons
// and save only when clicking save, not on every edit as I asked before."
//
// Two doors were never a preference — a record that does not exist cannot be
// written one field at a time, because `POST /api/record` needs the whole of it,
// and a `done` with no PRs is refused by the gate whichever order the two
// arrive in. So the staged door had to exist, and the reader met whichever one
// the item they pressed happened to open: the same card, one of them committing
// under them as they typed. Now every box is the staged one, and the only
// difference left between them is the word on the button.
//
// Two things went with the live door and are worth naming, because each was
// paid for once and is now somebody else's job:
//
//   * the per-field PATCH, whose commit message named the one field that moved.
//     `popEdited` sends a diff, so the message still names only what changed —
//     it is now one commit for the several fields one press answered, which is
//     what a Save button means.
//   * the status gate reached on blur, which turned a live box into a staged one
//     asking for what the new status needs. `popSave` asks the same question of
//     the same rule, in the same box, with those fields already on it.
function popForm(spec) {
  const kind = spec.mode === 'new' ? spec.kind : spec.row.kind;
  const every = (POP_SCHEMA.fields || {})[kind] || [];
  // `only` is filtered against the kind's own list rather than trusted. The gate
  // names fields out of `required_at` and the form draws `_editable_for`, and
  // those are two functions: a box drawn for a field this kind has not got is a
  // box the create route answers `a task has no …` to.
  const only = spec.only ? spec.only.filter(name => every.includes(name)) : null;
  POP_FORM = {
    mode: spec.mode, kind: kind, row: spec.row || null, parent: spec.parent || null,
    label: spec.label, verb: spec.verb,
    // What has been typed and not yet written. Empty on a live box — where a
    // field that has been answered is a field that has been saved — and the
    // whole of a staged one's answer.
    values: Object.assign(
      // **The status a new record opens at is an answer, not a default.** The
      // chip says it before anything is typed — `opens_at(kind)` through the
      // schema — and a create that did not send it would be the box lying about
      // what pressing Create writes, which is the draft row's own argument for
      // showing the same value. Staged here rather than read off a control at
      // save time, because on this card there is no control until somebody
      // presses the chip.
      spec.mode === 'new' ? {status: (POP_SCHEMA.opens || {})[kind] || null} : {},
      spec.values || {}),
    names: only || every,
    // Opened the moment the box is drawn, rather than waiting to be clicked.
    // `Assign parent…` is the item that wants this: somebody who chose it has
    // already said which field they came to change. A record that does not exist
    // yet opens on its title, which is the one field it cannot be created
    // without.
    //
    // **Decided here and not in `popDrawForm`, and that is not tidying.** It was
    // decided there, per draw, and a box that draws itself again — the gated
    // status turning one box into another — would re-open the title over
    // whatever the reader had just been asked for.
    opens: spec.opens || (spec.mode === 'new' ? ['title'] : []),
    controls: new Map(), marks: new Map(), why: null, save: null, hill: null,
  };
  popDrawForm();
}

// The record the card is drawn from.
//
// **Re-read from the host rather than held.** The row a box was opened with is
// replaced wholesale when anything writes — the table's `draw()` rebuilds the
// whole tbody — and a box drawing the row it started with would show a value
// somebody else has since changed. A create has no record behind it, and an edit
// has one plus whatever `values` holds over it.
function popFormRow() {
  const form = POP_FORM;
  const base = form.row && POP_HOST && POP_HOST.rows
    ? (POP_HOST.rows(form.row.id) || form.row)
    : form.row;
  if (form.mode !== 'new' && !Object.keys(form.values).length) return base;
  // `kind` and `id` are what `cardHtml` and the writers need and are never
  // typed. A new record's id does not exist yet and nothing here reads it.
  const draft = Object.assign({}, base || {}, {kind: form.kind});
  if (form.mode === 'new') {
    draft.id = '';
    draft.title = '';
    // Nothing until somebody says so. `status` is not here: `popForm` staged the
    // kind's opening one, and the loop below lays `values` over this.
    draft.priority = null;
    draft.status = null;
    // The one field a new child does not ask about, because choosing it again is
    // the gesture said twice. `popCreated` sends it from here too.
    if (form.parent) draft.parent = form.parent.id;
  }
  for (const [name, value] of Object.entries(form.values)) draft[name] = value;
  // **The derived twin moves with the stated date.** `cardFact` (`shell.py`)
  // draws `row.start ?? row.start_date` — the scheduler's span where there is
  // one, which is right for a card that is only read and wrong the moment
  // somebody stages a date: the word under their answer would go on reading the
  // old span, which is the card confidently wrong about the one thing the reader
  // just did. The server recomputes the span on the save; until then what was
  // typed is what the card says.
  if ('start_date' in form.values) draft.start = form.values.start_date;
  if ('end_date' in form.values) draft.end = form.values.end_date;
  return draft;
}

function popDrawForm() {
  const form = POP_FORM;
  const box = document.createElement('form');
  box.className = 'popform popcard';
  box.dataset.kind = 'form';
  // The browser's own validation bubbles are off. They are drawn against the
  // control, anchored outside a `position: fixed` box that has its own
  // scrollbar and flips against the far gutter, and this form answers in a list
  // it places itself — see `popFormSays`.
  box.noValidate = true;
  // The sentence this box is about, for a reader who arrives inside it with no
  // pointer. **`.sr-only` and not drawn**: the card's first line is the record's
  // title, so a visible `Edit "X"` over a box that already shows X is the same
  // fact twice. `[data-kind="form-heading"]` is what the tests read the copy off.
  const heading = document.createElement('p');
  heading.className = 'popheading';
  heading.dataset.kind = 'form-heading';
  // `textContent`, never `innerHTML`. Every heading here carries a record's
  // title, and this is the JavaScript half of the one escaping boundary.
  heading.textContent = form.label;
  box.append(heading);
  // **The card itself.** `cardHtml` escapes everything it writes — it is the
  // function a hover has been putting a record's own text through since the card
  // existed — and this is the same call the hover makes.
  const drawn = document.createElement('template');
  drawn.innerHTML = cardHtml(popFormRow(), []);
  box.append(...drawn.content.children);
  form.why = document.createElement('ul');
  form.why.className = 'popwhy';
  form.why.dataset.kind = 'form-why';
  form.why.hidden = true;
  // Focusable and not tabbable: a refusal is put under the keyboard when it
  // arrives — the same move `popSay` makes in the menu — and Tab out of it then
  // lands on the button, which is the next thing in the document.
  form.why.tabIndex = -1;
  box.append(form.why);
  // Every box, because every box now commits on the button — see the banner
  // above `popForm`.
  const acts = document.createElement('div');
  acts.className = 'popacts';
  form.save = popPress('form-save', form.verb, 'popsave');
  // A real submit, so Enter on the button itself presses it and the box answers
  // one `submit` however it was reached. Enter inside a FIELD does not get here:
  // it takes that field's answer and closes it — see `popOpenField`.
  form.save.type = 'submit';
  const cancel = popPress('form-cancel', 'Cancel', 'popcancel');
  // `askFor`'s own sentence for the same press, because it is the same news.
  cancel.onclick = () => { announce('nothing was changed'); popDone(); };
  acts.append(form.save, cancel);
  box.append(acts);
  box.addEventListener('submit', event => {
    event.preventDefault();
    popSave();
  });
  POP.classList.add('popforming');
  // **`role="dialog"` and not `menu`, and the swap is not cosmetic**: a `<form>`
  // is not a child a `role="menu"` may have, and a reader arriving inside one
  // would be told they were in a menu with no items in it. `popDraw` sets it
  // back for the other face.
  POP.setAttribute('role', 'dialog');
  POP.setAttribute('aria-label', form.label);
  POP.replaceChildren(box);
  POP.scrollTop = 0;
  form.controls = new Map();
  popWireFields(box);
  popMarkRequired();
  popPlace();
  // Into the field somebody came here to change, if there is one.
  for (const name of form.opens.filter(name => form.names.includes(name)))
    popOpenField(name);
  if (!form.controls.size) popFirstSlot(box);
}

// Every part of the card that is a field, made clickable.
//
// **`[data-field]` and nothing else.** `cardHtml` puts it on the title line, on
// each ladder chip the kind reads, and on each row of the list; a part of the
// card that is not a field — the kind chip, the hill, Progress — carries none
// and is therefore not wired here. That is one marker doing the work rather than
// three lists agreeing with each other.
function popWireFields(box) {
  const form = POP_FORM;
  for (const part of box.querySelectorAll('[data-field]')) {
    const name = part.dataset.field;
    if (!form.names.includes(name)) continue;
    const why = popLockedWhy(name);
    if (why) {
      part.classList.add('poplocked');
      // The sentence, on the element rather than under it. A card has no room
      // for a paragraph per row, and the reason a control will not open is a
      // thing you ask about rather than a thing you read down the page.
      part.title = why;
      continue;
    }
    part.classList.add('popopens');
    part.tabIndex = 0;
    // The name, for a reader who arrives here with Tab and finds a row of words.
    // The title line and the two chips have no `<dt>` beside them at all.
    part.setAttribute('role', 'button');
    part.setAttribute('aria-label', popLabel(name) + ': ' + popSaidOf(name));
    part.onclick = () => popOpenField(name);
    part.onkeydown = event => {
      // **Only this element's own keys, and that is the whole of this line.**
      // The control this opens is a CHILD of the element the listener is on, so
      // every key typed into the box bubbles up to here — and a space in a title
      // arrived as "the row was pressed", was swallowed by the `preventDefault`
      // below, and never reached the box. jcanton, 2026-09-18: "when editing the
      // new card I can't add space characters in the fields (tried title and
      // assignees)".
      //
      // `event.target` and not a check for an open control: a `<select>` inside
      // this element answers its own space and arrows too, and this handler has
      // no business with any of them.
      if (event.target !== part) return;
      if (event.key !== 'Enter' && event.key !== ' ') return;
      // The grid's own Escape and the menu's own keys are somebody else's; these
      // two are this element's, and a space that scrolls the page under an open
      // card is the page ignoring you.
      event.preventDefault();
      popOpenField(name);
    };
  }
}

// What this field says right now, as one line of text — the accessible name of
// the thing you are about to click.
function popSaidOf(name) {
  const value = popStartOf(name);
  if (popEmpty(value)) return 'nothing';
  if (Array.isArray(value)) return value.join(', ');
  if (value === true) return 'yes';
  return String(value);
}

// Where the control goes when this field is opened: the `<dd>` of a list row,
// and the element itself for the title line and the chips, which have no inner
// box to put anything in.
function popSlotIn(box, name) {
  const part = (box || POP).querySelector(`[data-field="${name}"]`);
  if (!part) return null;
  return part.matches('.card-fact') ? part.querySelector('dd') : part;
}

// Put a control where the value is.
//
// **The value is remembered and the slot is emptied**, so that Escape can put
// back exactly what was there rather than re-deriving it — a redraw would also
// work and would cost a re-read of the row in the middle of a keystroke.
function popOpenField(name) {
  const form = POP_FORM;
  if (form.controls.has(name)) { form.controls.get(name).focus(); return; }
  const slot = popSlotIn(POP, name);
  if (!slot) return;
  const type = (POP_SCHEMA.types || {})[name] || 'text';
  const control = popControlOf(name, type);
  control.id = 'pop-f-' + (++POP_FIELD_N);
  control.dataset.field = name;
  control.className = 'popbox';
  // No `<label>` to point at: the card names a field with a `<dt>` that is not
  // this control's label, and the title line and the chips name nothing at all.
  control.setAttribute('aria-label', popLabel(name));
  // Every box that is typed into, and not only the ones whose type is the word
  // `text`. A list field's type is `list` and its control is a text box all the
  // same, and gating on the word left `assignees`, `reviewers`, `tags`,
  // `depends_on` and `prs` — five of the seven fields anybody completes —
  // completing nothing at all. jcanton, 2026-09-18: "autocomplete doesn't work
  // in the forms inside our new editable card. can you enable all as in the
  // /detail?".
  //
  // Asked of the CONTROL and not of the schema: a `<select>` has its own options
  // and a date box has a picker, and both would be handed a list they cannot
  // show. `cycle` is a number box and Chrome completes one from a datalist like
  // any other input.
  form.controls.set(name, control);
  const was = slot.innerHTML;
  slot.replaceChildren(control);
  // **After the slot is emptied, and that ordering is the other half of the
  // defect.** `popComplete` parks its `<datalist>` in this slot beside the box,
  // and called before the line above it parked one that `replaceChildren` then
  // threw away — leaving every box pointing `list=` at an element no longer in
  // the document, which is a box that completes nothing. Owner completed nothing
  // either, and that is the half of jcanton's report that a missing `list`
  // attribute would not have explained.
  if (control.tagName === 'INPUT' && (control.type === 'text' || control.type === 'number'))
    popComplete(control, name, slot);
  slot.classList.add('popediting');
  // **No `blur` listener at all**, and two keys close this control. A box is
  // asking a question of several fields at once, so opening the second would
  // blur the first — and while blur committed, that meant pressing one field to
  // answer it saved the one before it. Nothing closes on blur now; the control
  // stays where it is, holding what was typed, and `popSave` reads it there.
  //
  // **Enter takes the answer and closes the field. Escape gives it up.** The two
  // are a pair and neither of them writes: jcanton, 2026-09-18, on the version
  // where Enter reached the form's own submit — "can we instead have 'enter' only
  // close the field being edited, similarly to escape, instead of committing on
  // the floating editing card?". Save is the only thing that commits, which is
  // what the button being there says, and Enter in a box you have just typed
  // into is not a press of it.
  control.onkeydown = event => {
    if (event.key === 'Enter') {
      // **It must not reach the form**, which is the whole of this branch: the
      // control is inside a real `<form>` with a `type="submit"` button, so an
      // Enter left alone here IS the press.
      event.preventDefault();
      popTakeField(name);
      return;
    }
    if (event.key !== 'Escape') return;
    // **It must not bubble**: `popClose` is listening for Escape on the way up
    // and would take the whole box down, when what was asked for was to undo one
    // field. The table's own editor stops it for exactly this reason.
    event.preventDefault();
    event.stopPropagation();
    popShutField(name, slot, was);
  };
  // Every control, and not only the status one. What a status demands moves when
  // the status moves, and `reviewers` stops being demanded the moment
  // `review_waived` is ticked — two controls, one rule, and a listener per
  // special case is how the third one gets forgotten.
  control.addEventListener('change', () => { popMarkRequired(); popPlace(); });
  // And the two that are chips re-dress as they are picked. The box redraws when
  // a value is written, which is too late: while the picker is open the chip
  // around it is still wearing the old rung's tint, and a chip reading `Done` in
  // the ready colour is confidently wrong. `cycles.py` says the same thing about
  // the betting table's picker, and rebuilds its class the same way.
  if (slot.matches('.chip'))
    control.addEventListener('change', () => popDressChip(slot, name, control.value));
  // Again, now that there is a control to say it on. `popDrawForm` runs this
  // over the card's `<dt>`s before anything is open, so a box opened afterwards
  // would carry no `aria-required` at all — and the star and the attribute are
  // the two halves of one fact.
  popMarkRequired();
  control.focus();
  // Selected so that typing replaces it, which is right for the title of a
  // record being edited. Guarded on `type === 'text'` because `select()` is a
  // defined no-op on a date box and a `<select>` has no such method at all —
  // the pair `openEditor` (`table.py`) is careful about for the same two types.
  if (control.type === 'text' && control.select) control.select();
  popPlace();
}

// A chip wearing the value now in it: the class that tints it, the mark inside
// it, and — for status — the picture beside it, which is the same fact drawn a
// second way.
function popDressChip(chip, name, value) {
  const klass = name === 'status' ? stClass(value) : 'pri pri-' + value;
  // Rebuilt from the classes that are not a rung's, rather than toggled, so
  // nothing has to know which rung it was.
  const kept = [...chip.classList].filter(one =>
    one !== 'chip' && one !== 'pri' && one !== 'empty-chip'
    && !one.startsWith('st-') && !one.startsWith('pri-'));
  chip.className = ['chip', klass, ...kept].join(' ');
  const mark = chip.querySelector('.chipmark');
  const glyph = typeof cardMark === 'function' ? cardMark(name, value) : '';
  if (mark) mark.textContent = glyph;
  if (name !== 'status') return;
  const hill = POP.querySelector('.card-chips .card-hill');
  if (hill && typeof hillHtml === 'function') hill.outerHTML = hillHtml(value);
}

// Take the control away again, having either read it or thrown it away.
// The answer taken and the control closed, which is Enter. **It stages and does
// not write**: `form.values` is what Save sends, and until Save is pressed the
// only thing that has happened is that a word on the card now reads what was
// typed instead of what the record holds.
//
// The whole box is drawn again rather than the one slot rewritten, because what
// that word looks like is `cardHtml`'s answer — a chip with its tint and its
// mark, a list joined the card's way, a dash where there is nothing — and a
// second place that renders a value is how two places come to disagree about
// one. The redraw rebuilds every control from `popFormRow`, so every OTHER open
// control is staged first or the redraw would rewrite its answer back to the
// record's.
function popTakeField(name) {
  const form = POP_FORM;
  if (!form.controls.has(name)) return;
  // **A half-written date must not clear the date that is there.** A native
  // picker answers `value === ''` for `2026-0` exactly as it does for a box
  // somebody emptied on purpose — the defect `openEditor` (`table.py`) records
  // in as many words — and `validity.badInput` is the browser's own word for
  // that state. Asked of every open control and not only this one, because the
  // redraw below takes them all: a box left half-written elsewhere would be put
  // back to the record's value with nothing said. So nothing closes, the box
  // says which field it is, and the answer stays on screen to be finished.
  // `&&` guards it because the node driver builds elements that have no
  // `validity` at all.
  for (const [other, box] of form.controls) {
    if (!(box.validity && box.validity.badInput)) continue;
    popFormSays([`${popLabel(other)} is half-written — finish it, or press Escape in it.`]);
    box.focus();
    return;
  }
  for (const [other, box] of form.controls) form.values[other] = popReadOf(other, box);
  form.controls.delete(name);
  // What is still open stays open, and `popDrawForm` opens exactly this list.
  form.opens = [...form.controls.keys()];
  // And the keyboard is `popDrawForm`'s to place: it re-opens what was open, or
  // hands it to `popFirstSlot` when this was the last control.
  popDrawForm();
}

function popShutField(name, slot, was) {
  POP_FORM.controls.delete(name);
  slot.classList.remove('popediting');
  // The word that was there, put back exactly — which is why `popOpenField`
  // remembered the markup rather than re-deriving it.
  slot.innerHTML = was;
  // **And the keyboard back inside the box.** The control that had it has just
  // been removed from the document, so focus falls to `<body>` — which is
  // outside `#pop`, and this box's keydown listener is ON `#pop`. So the next
  // Escape, the one that means "leave this box", reached nothing at all, and Tab
  // started again from the top of the page. It was hidden while blur committed:
  // the write redrew the box and focused it on the way through.
  //
  // **Save and not the word this just put back**, which is what it should be and
  // cannot be: `.card-fact` is `display: contents`, so it generates no box, and
  // Chrome will not focus an element that has none — measured, `focus()` returns
  // with `activeElement` still `<body>`. Save is the next thing in the document
  // after the fields, it is a real control, and it is what Tab would have
  // reached anyway.
  if (POP_FORM.save) POP_FORM.save.focus();
  popPlace();
}

// Focus, when nothing is open: the first field this card can edit, so that a box
// opened from the keyboard has the keyboard in it.
//
// **And Save when that does not take, which is most of the time.** `.card-fact`
// is `display: contents` — it generates no box, and Chrome refuses to focus an
// element that has none, measured: `focus()` returns with `activeElement` still
// `<body>`. That is outside `#pop`, where this box's keydown listener is, so
// Escape reached nothing and Tab started again from the top of the page. Asked
// of the document rather than assumed, because the title line and the chips are
// ordinary boxes and do take it.
function popFirstSlot(box) {
  const first = box.querySelector('.popopens');
  (first || box).focus();
  if (!POP.contains(document.activeElement) && POP_FORM && POP_FORM.save)
    POP_FORM.save.focus();
}

function popPress(kind, text, className) {
  const control = document.createElement('button');
  control.type = 'button';
  control.className = className;
  control.dataset.kind = kind;
  control.textContent = text;
  // **It refuses focus on the way down**, which is the whole of what makes Save
  // reachable while a field is open. Pressing a button blurs whatever had focus,
  // and this box's blur stages the answer and redraws the card — so by `mouseup`
  // the button under the pointer is a different element and the click never
  // lands. `table.py` records the same sequence from the other end: "mousedown
  // on the check, blur, mouseup, no click". `popSave` reads the still-open
  // control itself.
  control.addEventListener('mousedown', event => event.preventDefault());
  return control;
}

// Why this control will not let you change it, or `''` when it will.
function popLockedWhy(name) {
  const form = POP_FORM;
  // The parent of a new child is not a choice — it is the record the menu was
  // opened on, and choosing it again is the gesture said twice. Drawn and
  // disabled rather than hidden, so the form says what it is about to file this
  // under instead of asking the reader to remember.
  if (form.mode === 'new')
    return name === 'parent' && form.parent
      ? `Filed under "${popTitle(form.parent)}", which is what New child means.`
      : '';
  // **A box drawn empty over a field whose value this view does not carry would
  // delete it.** `_row` (`rows.py`) ships `blocked_by` — a COUNT of unfinished
  // blockers — and no `depends_on` at all, so an Edit form would draw an empty
  // list box on a record that has three dependencies; anything typed there
  // REPLACES the list, and anything left alone is caught by the diff and never
  // sent. The first half is a silent deletion, which is the failure this whole
  // repository is most careful about.
  //
  // Asked as "does this view carry the key" rather than "is the value empty",
  // because those are the two states this has to tell apart.
  if (!(name in form.row))
    return 'This view does not carry it — edit it on the record\'s own page.';
  // **The key being present is not the value being whole**, and the graph is
  // where those come apart. `_elements` (`graph.py`) filters `depends_on` to
  // plan members and sets `off_plan_deps` to say it dropped some — so the key IS
  // there, holding a SUBSET of what the file stores. A box drawn from that
  // subset looks complete, and saving rebuilds the whole field from what the box
  // holds, which deletes the edges this view could not draw. That is the same
  // silent deletion the paragraph above is about, arriving through the one door
  // `name in form.row` leaves open.
  //
  // The sentence is `graph.py`'s own, from the refusal its canvas already gives
  // when somebody tries to draw an edge on such a node.
  if (name === 'depends_on' && form.row.off_plan_deps)
    return `${popTitle(form.row)} waits on something this view cannot draw `
         + '— its dependencies are edited on its own page.';
  if (name !== 'parent') return '';
  // The same two sentences `popParentItem` refuses with, here because `Edit…`
  // draws the parent control as one field among fifteen rather than on its own.
  if (form.row.off_plan_parent)
    return `${popTitle(form.row)} is filed under something this view cannot show `
         + '— where it belongs is edited on its own page.';
  return popCandidates(form.kind, form.row.id) ? '' : popNoRows();
}

// What the control opens holding. The form's prefill, which is NOT the same
// question as what the record holds — see `popHeld`, which the diff reads.
function popStartOf(name) {
  const form = POP_FORM;
  if (name in form.values) return form.values[name];
  if (form.mode === 'new') {
    if (name === 'parent') return form.parent ? form.parent.id : null;
    // `opens_at(kind)` through the schema. A status box that starts blank is a
    // required field the reader has to fill before they have said anything, and
    // it would also be the form lying about what pressing Create writes — which
    // is the draft row's argument for showing the same two defaults.
    if (name === 'status') return (POP_SCHEMA.opens || {})[form.kind] || null;
    return null;
  }
  return popHeld(name);
}

// What the RECORD holds, which is what a diff is against. Distinct from
// `popStartOf` on purpose: a gated status opens its form with the new status
// already in the box, and a diff that read the box's starting value would
// conclude the status had not changed and send everything but it.
function popHeld(name) {
  const held = POP_FORM.row ? POP_FORM.row[name] : undefined;
  return held === undefined ? null : held;
}

// A stored value as a box shows it — `stored()` (`table.py`), which exists
// because a status cell shows "In progress" and holds `in_progress`, and reading
// a control back off what it draws would save the label.
function popRawOf(value) {
  if (Array.isArray(value)) return value.join(', ');
  return value === null || value === undefined ? '' : String(value);
}

function popControlOf(name, type) {
  const value = popStartOf(name);
  if (type === 'select') return popSelectOf(name, value);
  const box = document.createElement('input');
  if (type === 'bool') {
    box.type = 'checkbox';
    box.checked = value === true || value === 'true';
    return box;
  }
  // A date is PICKED and not spelled, which is the rule `openEditor` states as a
  // TYPE rather than as a list of field names: written as `name === 'start_date'`
  // it is right until `end_date` arrives beside it. Nothing converts on either
  // side — `popRawOf` hands back `YYYY-MM-DD`, which is exactly what a date box
  // reads and exactly what it reports.
  box.type = type === 'date' ? 'date' : type === 'number' ? 'number' : 'text';
  // Any number this form asks for. An appetite in person-weeks is fractional and
  // a cycle is not; a step of 1 would refuse the halves that the unit this whole
  // application measures work in is written in, and the integer rule is the
  // model's to keep.
  if (type === 'number') box.step = 'any';
  box.autocomplete = 'off';
  box.value = popRawOf(value);
  return box;
}

function popSelectOf(name, value) {
  const box = document.createElement('select');
  const raw = popRawOf(value);
  let options;
  if (name === 'status')
    options = ((POP_SCHEMA.statuses || {})[POP_FORM.kind] || []).map(status => ({
      value: status,
      // The glyph in front of the word, exactly as the status submenu and the
      // table's own `<select>` draw it. `STATUS_GLYPH` is in the vendored
      // subset — that is the argument the six marks are characters at all.
      text: (((POP_SCHEMA.glyphs || {})[status] || '') + ' ' + popHuman(status)).trim(),
    }));
  else if (name === 'priority')
    options = (POP_SCHEMA.priorities || []).map(one => ({value: one, text: popHuman(one)}));
  else options = popParentOptions();
  // **Whatever the file holds, first and selected, even when it is not on the
  // ladder.** `status` and `priority` are plain `str` in the model on purpose —
  // parse permissively, validate strictly — so a record can hold a word no rung
  // lists. Without this line the `<select>` would silently report the first
  // option instead, and a Save on any OTHER field would rewrite the status to
  // something nobody chose.
  if (raw && !options.some(one => one.value === raw)) options.unshift({value: raw, text: raw});
  // The empty option, where empty is a state the field may actually be in: a
  // parent that is not locked, and a ladder the record is somehow on neither
  // rung of. Offering "— nothing —" for a status would be offering a write the
  // gate refuses on every rung that has one.
  //
  // **`priority` on a create is the one box here that does not say what it is
  // going to write**, and it is a gap in the schema rather than a choice.
  // `opens` carries the status a new record of each kind opens at — `opens_at`,
  // the model's own — and there is no such key for the priority, so this form
  // draws "— nothing —" over a field the create route will fill in as `medium`
  // from the model's default. The draft row does not have this problem because
  // the server hands it `DATA.defaults`. Guessing the middle rung of
  // `priorities` here would be a second copy of a default that lives in the
  // model; a `defaults` key beside `opens` is where the answer belongs.
  const locked = POP_FORM.mode === 'new' && name === 'parent' && POP_FORM.parent;
  if ((name === 'parent' && !locked) || !raw) options.unshift({value: '', text: POP_NOTHING});
  for (const one of options) {
    const option = document.createElement('option');
    option.value = one.value;
    option.textContent = one.text;
    if (one.value === raw) option.selected = true;
    box.append(option);
  }
  return box;
}

// **A `<select>` of records that exist, never a box to type an id into.** This
// picker is the only thing that ever stood in front of two holes in the server,
// both measured through the API before they were closed: `_containment_problems`
// returned early on a parent it could not resolve, so a dangling one committed
// in silence and `openproj check` never mentioned it; and PATCH ran `loop_made`
// and no `validate_all` at all, so a wrong-kind parent committed and was
// reported afterwards. Both doors refuse now — `parent_refusal` (`model.py`) —
// and this control is still the right one, because a refusal is a worse answer
// than a list that could not express the mistake.
function popParentOptions() {
  const form = POP_FORM;
  if (form.mode === 'new' && form.parent)
    return [{value: form.parent.id, text: popTitle(form.parent)}];
  return (popCandidates(form.kind, form.row ? form.row.id : null) || [])
    .map(row => ({value: row.id, text: popTitle(row)}));
}

// --- completion --------------------------------------------------------------
//
// **A native `<datalist>`, and not `attachSuggest`.** That widget is the one
// every other box in this application completes through, and it cannot be used
// here: it reads `SUGGEST`, parsed from a `<script id="suggest">` blob that
// `_combobox_html` emits — and of this menu's three hosts only the table loads
// it. A completion that works on one view out of three is a completion nobody
// relies on, which is the argument `attachSuggest` was given to the table with
// in the first place.
//
// **The list field is the whole difficulty, and the prefix is the answer.** A
// datalist matches against the WHOLE value of the box and picking an option
// replaces the whole value, so on `jcanton, hal` it would offer nothing and, if
// it did, would delete the first name to write the second. So the options for a
// list field are rebuilt on every keystroke as `<what is already typed>, <one
// candidate>` — the box's own text carried through — and picking one appends
// instead of replacing. Measured against Chrome's matching, which is a
// case-insensitive prefix test on the option's value.
function popComplete(input, name, field) {
  const source = (POP_SCHEMA.suggests || {})[name];
  if (!source) return;
  const options =
    // The same people the table's own suggestion list offers. A second reading
    // of "who is on this plan" disagrees with the box beside it the first time
    // somebody joins.
    source === 'people'
      ? (POP_SCHEMA.people || []).map(login => ({value: login, label: ''}))
    // And the same rows the parent picker is built from, unfiltered by kind:
    // `depends_on` is an edge and an edge may point anywhere on the plan. Off
    // the host rather than out of the schema, because the host already has them
    // and shipping the plan twice is what would make this payload expensive.
    : source === 'records'
      ? popAllRows().map(row => ({value: row.id, label: popTitle(row)}))
    // Tags, pull requests and cycles, as the server read them out of the corpus.
    // Already `{value, label}` — a cycle's label is the window it covers, which
    // is the whole reason a number is pickable at all.
      : ((POP_SCHEMA.lists || {})[source] || []);
  if (!options.length) return;
  const list = document.createElement('datalist');
  list.id = 'pop-list-' + (++POP_FIELD_N);
  input.setAttribute('list', list.id);
  const many = (POP_SCHEMA.types || {})[name] === 'list';
  const fill = () => {
    const at = input.value.lastIndexOf(',');
    const lead = many && at !== -1 ? input.value.slice(0, at + 1) + ' ' : '';
    // Already chosen, so not offered again: picking a name that is in the list
    // is a slip and not an intent to have it twice, which is the same
    // deduplication `coerce` (`table.py`) does at the other end.
    const taken = many ? input.value.split(',').map(one => one.trim()) : [];
    list.replaceChildren(...options
      .filter(one => !taken.includes(one.value))
      .map(one => {
        const option = document.createElement('option');
        option.value = lead + one.value;
        // The title beside the id, which is the whole reason a record is
        // pickable at all: nobody remembers `task-b4102f`.
        if (one.label) option.label = one.label;
        return option;
      }));
  };
  fill();
  if (many) input.addEventListener('input', fill);
  field.append(list);
}

// The star, and `aria-required`, on every field the status now in the box will
// make the server refuse the record without. Redrawn on every change, because
// the answer moves when the status does — which is the form's whole connection
// to the gate, and the thing that makes picking a refused status from the menu
// land somewhere that explains itself.
function popMarkRequired() {
  const form = POP_FORM;
  if (!form) return;
  const row = popFormRow();
  // The status now in the box: the open control if there is one, else what the
  // card is drawing.
  const box = form.controls.get('status');
  const status = box && !box.disabled ? box.value : popRawOf(row ? row.status : null);
  const gates = (POP_SCHEMA.required || {})[form.kind] || {};
  const waived = form.controls.get('review_waived');
  const off = waived ? waived.checked : !!(row && row.review_waived);
  for (const name of form.names) {
    const wanted = (gates[name] || []).includes(status)
      // `review_waived` is the escape hatch from the reviewer rule, honoured
      // here for the reason `missingFor` (`table.py`) honours it: asking for
      // reviewers on a record that has waived them is a nag.
      && !(name === 'reviewers' && off);
    const control = form.controls.get(name);
    if (control) control.setAttribute('aria-required', String(wanted));
    // **The star goes in the `<dt>`, which is the only name this card has.** The
    // title line and the two chips carry no name at all — that is what the card
    // looks like, and it is what was asked for — so a field on the card's face
    // gets `aria-required` and no mark. Nobody is going to fail to notice that a
    // record needs a title.
    const part = POP.querySelector(`.card-fact[data-field="${name}"] dt`);
    if (!part) continue;
    let star = part.querySelector('.popreq');
    if (!wanted) { if (star) star.remove(); continue; }
    if (star) continue;
    // `aria-hidden` and paired with `aria-required` on the control: a star a
    // screen reader reads as part of the name is a field called "Owner star",
    // and a star nobody but a sighted reader gets is half a fact.
    star = document.createElement('span');
    star.className = 'popreq';
    star.setAttribute('aria-hidden', 'true');
    star.textContent = ' *';
    part.append(star);
  }
}

// --- saving -----------------------------------------------------------------

// **Every box has a Save**, and it is the only thing that writes: the create
// door, the gated-status one, `Edit…` and `Assign parent…`.
async function popSave() {
  const form = POP_FORM;
  if (!form) return;
  const why = [];
  // What has been answered, plus anything still open under the cursor. Which is
  // nearly all of it: a control on this box closes only on Escape, so what Save
  // reads is what is on screen. The buttons refuse focus on `mousedown` (see
  // `popPress`) so that the press does not blur the box it is about to read.
  const values = Object.assign({}, form.values);
  // Where the keyboard goes if this press is refused: the open control when the
  // field is open, and otherwise the field's NAME, which is opened for the
  // reader. The name matters now that a whole card can be saved at once — a
  // status changed on the `Edit…` box is refused for a field nobody has clicked,
  // and sending the keyboard to the first field on the card instead would be the
  // box answering a question about `reviewers` by opening `title`.
  let offender = null;
  let offending = '';
  for (const [name, control] of form.controls) {
    if (!form.names.includes(name) || control.disabled) continue;
    // **A half-written date must not clear the date that is there.** A native
    // picker answers `value === ''` for `2026-0` exactly as it does for a box
    // somebody emptied on purpose, and an empty one here would be committed as a
    // deliberate clear — the defect `openEditor` (`table.py`) records in as many
    // words. `validity.badInput` is the browser's own word for that state and
    // the only thing here that can tell a slip from an intention; `&&` guards it
    // because the node driver builds elements that have no `validity` at all.
    if (control.validity && control.validity.badInput) {
      why.push(`${popLabel(name)} was left half-written, so nothing was saved.`);
      offender = offender || control;
      offending = offending || name;
      continue;
    }
    values[name] = popReadOf(name, control);
  }
  // The gate, asked before the write and only of the fields this box is about. A
  // box of one field cannot answer for a status it is not changing, and a
  // refusal naming a field the payload does not carry is the failure
  // `_reject_a_start_date_this_write_puts_in_the_past` was rewritten to stop
  // making — on the server, about exactly this shape of question.
  const status = 'status' in values ? popRawOf(values.status) : popRawOf(popStartOf('status'));
  // **And only when the status is MOVING.** The gate is a rule about arriving at
  // a status, not about standing in one: `validate_all` reports a record that is
  // already `in_progress` without assignees as a problem beside it, and the plan
  // is full of records in exactly that state because that is what a problem list
  // is for. Gating on the standing value instead would refuse every edit to every
  // one of them.
  //
  // (No record id is spelled in this comment, and that is not fastidiousness:
  // this script ships in the page, `test_a_deleted_record_is_gone_from_every_page_that_drew_it`
  // asks whether a deleted id is still anywhere in `/table`'s bytes, and naming
  // a fixture record here answered yes.)
  //
  // Measured against what the RECORD holds, not against what the box started
  // with: the gated-status box pre-fills exactly the status it is asking for, so
  // comparing with that would say "not moving" on the one path whose entire
  // purpose is to move.
  const held = form.mode === 'new' ? null : popRawOf(popHeld('status'));
  const moving = form.mode === 'new' || status !== held;
  const gates = (POP_SCHEMA.required || {})[form.kind] || {};
  for (const name of moving ? form.names : []) {
    const has = name in values ? values[name] : popStartOf(name);
    if (!popEmpty(has)) continue;
    if (!(gates[name] || []).includes(status)) continue;
    if (name === 'reviewers' && (values.review_waived ?? popStartOf('review_waived'))) continue;
    why.push(`${popHuman(status)} needs ${popLabel(name)}.`);
    offender = offender || form.controls.get(name);
    offending = offending || name;
  }
  // A title, at minimum, and the sentence is `createDraft`'s: the server refuses
  // a titleless record too, but it refuses it as YAML that will not read back,
  // and the reason a record needs one is not about YAML.
  if (form.mode === 'new' && popEmpty(values.title)) {
    why.push('A record needs a title — it is how anybody finds it again.');
    offender = form.controls.get('title');
    offending = 'title';
  }
  if (why.length) {
    popFormSays(why);
    if (offender) offender.focus();
    else popOpenField(offending || form.names[0]);
    return;
  }
  // Held while the commit is in the air. `POP_WRITING`, taken in `popStart` for
  // both write doors, is the rule — a flag is a statement about the page, and
  // Enter, a second listener and a script all reach those doors without going
  // through this button — and this attribute is how the rule is shown.
  // `createDraft` (`table.py`) makes the same split in the same words, and it is
  // there because two presses 0.9s apart minted two records on the deployed
  // service.
  form.save.disabled = true;
  try {
    await (form.mode === 'new' ? popCreated(values) : popEdited(values));
  } finally {
    // The success path has already closed the box and thrown this element away,
    // which is why the assignment is harmless there rather than needing a guard:
    // a detached button is a button nobody can press.
    form.save.disabled = false;
  }
}

function popReadOf(name, control) {
  const type = (POP_SCHEMA.types || {})[name];
  if (type === 'bool') return control.checked;
  const raw = (control.value || '').trim();
  if (type === 'list')
    return raw ? [...new Set(raw.split(',').map(one => one.trim()).filter(Boolean))] : [];
  if (type === 'number') return raw === '' ? null : Number(raw);
  return raw === '' ? null : raw;
}

// Whether two values of a field are the same value. `null`, `undefined` and the
// empty string are one state — a field with nothing in it — because `patch_text`
// round-trips and all three round-trip to a key with nothing after it.
function popAlike(one, two) {
  if (Array.isArray(one) || Array.isArray(two)) {
    const left = Array.isArray(one) ? one : [];
    const right = Array.isArray(two) ? two : [];
    return left.length === right.length && left.every((item, at) => item === right[at]);
  }
  if (popEmpty(one) && popEmpty(two)) return true;
  return one === two;
}

// **Only what changed.** `_merge_frontmatter` would skip a key whose stored value
// already equals the one being sent, so a whole-form PATCH would commit the same
// thing — but the commit MESSAGE names the fields, and a message saying fifteen
// fields were written when one was is a line in somebody's history that is not
// true. `git log --follow` on a record is one of the two ways this plan is read.
function popEdited(values) {
  const form = POP_FORM;
  const diff = {};
  for (const [name, value] of Object.entries(values))
    if (!popAlike(value, popHeld(name))) diff[name] = value;
  const named = Object.keys(diff);
  if (!named.length) {
    // Said in the box and not by closing it. A Save that quietly dismissed the
    // form would be indistinguishable from one that wrote something.
    popFormSays(['Nothing has changed.']);
    form.why.focus();
    return;
  }
  return popWrite(form.row.id, diff, popSavedSaid(form.row, diff));
}

// The receipt. `popWrite` says it into the live region after the commit lands,
// by which time this box is gone — so a sentence that said only "saved" would be
// a receipt about nothing.
function popSavedSaid(row, diff) {
  const named = Object.keys(diff);
  // The one write this form makes that another item already has words for.
  // `Take out of "X"` says it exactly this way, and two sentences for one change
  // is how `in_progress` came to be spelled three ways on one screen.
  if (named.length === 1 && named[0] === 'parent')
    return diff.parent
      ? `${popTitle(row)} is now inside "${popTitleOf(diff.parent)}"`
      : `${popTitle(row)} is no longer inside anything`;
  return `${popTitle(row)}: ${popNamed(named.map(popLabel))} saved`;
}

// `a`, `a and b`, `a, b and c`. The app's own list, so a receipt reads as a
// sentence rather than as a payload.
function popNamed(words) {
  if (words.length < 2) return words.join('');
  return words.slice(0, -1).join(', ') + ' and ' + words[words.length - 1];
}

function popCreated(values) {
  const form = POP_FORM;
  const fields = {kind: form.kind};
  for (const [name, value] of Object.entries(values)) {
    // **Empty is not a value on a create.** `opening_fields` (`model.py`) is what
    // decides what a new record of this kind starts life with — the same one the
    // CLI's `openproj new` uses — and a form that sent `owner: null` for every
    // box nobody filled would write an empty key into the file for each of them,
    // in a corpus whose whole premise is that the file is the document. `false`
    // goes with them for the same reason: it is the model's own default for the
    // one bool here, and naming a default is not saying anything.
    if (popEmpty(value) || value === false) continue;
    fields[name] = value;
  }
  // The parent, which is the whole of what `New child` means and is never read
  // off its control — that control is disabled, so `popSave` skipped it.
  if (form.parent) fields.parent = form.parent.id;
  // The present continuous, before the request rather than after the answer: two
  // seconds of a box that looks untouched is what taught somebody to press
  // Create twice on the deployed service.
  announce(`Creating this ${popHuman(form.kind).toLowerCase()}…`);
  return popCreate(fields, String(fields.title));
}

// **Where the new record went, and whether it can be seen.**
//
// `refreshRows()` replaces `DATA.rows` and `draw()` re-applies the filter, so a
// child created under a parent the current filter excludes appears NOWHERE and
// the only feedback anybody gets is this sentence. The draft row has the same
// hole today and it has never been felt, because the draft row is visible while
// it is being typed; this form is not, and it closes on success.
//
// Three answers, and the third is the one that matters: the host says the record
// is not on screen, so the sentence says so and says why. A host that does not
// register `shows` gets the first — it cannot be asked, and inventing a claim
// about a view this module cannot see would be worse than not making one.
function popLanded(id, title) {
  // Title AND id, and this is the one announcement here that needs both. The id
  // was minted by the server a moment ago and nobody has seen it before — it is
  // what a link, a `depends_on` and a `git show` are written with — while the
  // title is the only half the person who just typed it recognises.
  const made = `${title} (${id})`;
  const row = POP_HOST && POP_HOST.rows(id);
  if (!row) return `Created ${made} — reload to see it`;
  if (POP_HOST.shows && !POP_HOST.shows(id))
    return `Created ${made} — it is not on screen, because the filter this view `
         + 'has set does not match it';
  return `Created ${made}`;
}

// --- deleting -----------------------------------------------------------------
//
// **`Delete…` never asks a bare question.** The record page has confirmed a
// delete with a panel rather than a browser `confirm()` since it had a Delete
// button, and its own comment says why: a native dialog cannot say which record
// it is about in the words this page uses, cannot show the server's reason when
// the delete is refused, and is the one thing on a page that stops every other
// script until somebody clicks it. Cut 5 adds the reason that decided it here —
// **a `confirm()` cannot list a cascade**, and the cascade is the whole of what
// somebody is agreeing to.
//
// **And the cascade is asked of the server, which is not a convenience.**
// `cascade_of` (`index.py`) iterates `index.records`; the host's `all()` on the
// table is `DATA.rows`, which `table.py` builds from `index.plan`, and the
// graph's is narrower still. A cascade worked out in here would therefore miss
// any unplanned issue or note carrying a hand-written `depends_on` — and the
// delete route refuses a deletion whose `also` list is not the one it computes
// itself, so every such delete would be refused against a panel that had listed
// everything it could see. Measured claim, not a worry: that record is
// `test_deleting_what_a_hand_written_issue_waits_on_edits_the_issue`
// (`tests/test_issues.py`), and it is in the route's `edited`.

// The sentence under the question, and it is the record page's own — this panel
// and that one are the same question and may not use two vocabularies for it.
const POP_REVERT = 'Commit deletion? Can only be undone with git revert.';

// Whether the panel an answer was asked for is still the panel on screen.
//
// Identity is the whole test, and `POP_GEN` is not wanted beside it: `popClose`
// nulls this, `popDraw` nulls it, and each face that can replace it builds an
// object of its own — so an answer can only ever find the panel that asked for
// it. `popSaid` takes a generation instead because it is reached from writes
// that have no panel of their own to compare against.
function popAsking(asking) { return POP_CONFIRM === asking; }

function popAsk(row) {
  const asking = {
    id: row.id,
    title: popTitle(row),
    // **What this panel is authorising, and `null` until the plan has said.** It
    // is the list that goes back on the wire, and the delete route compares it
    // against its own answer and refuses the deletion if the two differ —
    // somebody filing a task under this pitch while the panel sat open is the
    // whole reason it exists. A panel that sent a list it had made up in here
    // would be refused every time the plan held a record this view cannot see.
    also: null,
    deletes: [],
  };
  const box = document.createElement('div');
  box.className = 'popconfirm';
  box.dataset.kind = 'confirm';

  const heading = document.createElement('p');
  heading.className = 'popheading';
  heading.dataset.kind = 'confirm-heading';
  // `textContent`, never `innerHTML`. This is a record's title.
  heading.textContent = `Delete "${asking.title}"?`;
  box.append(heading);

  // Where the consequences go once they are known. Empty until then, and empty
  // for ever on a record nothing is filed under and nothing waits on — which is
  // the leaf case the record page draws exactly this way, and it is a plain
  // question rather than a missing one.
  asking.reach = document.createElement('div');
  asking.reach.className = 'popreaches';
  asking.reach.dataset.kind = 'confirm-reach';
  box.append(asking.reach);

  asking.note = document.createElement('p');
  asking.note.className = 'popnote';
  asking.note.dataset.kind = 'confirm-note';
  box.append(asking.note);

  asking.why = document.createElement('ul');
  asking.why.className = 'popwhy';
  asking.why.dataset.kind = 'confirm-why';
  asking.why.hidden = true;
  // Focusable and not tabbable, exactly as the form's is: a refusal is put under
  // the keyboard when it arrives, and Tab out of it then lands on the buttons.
  asking.why.tabIndex = -1;
  box.append(asking.why);

  const acts = document.createElement('div');
  acts.className = 'popacts';
  asking.really = popPress('confirm-delete', 'Delete it', 'popreally');
  // **Disabled from the moment it is drawn**, and this is the repository's
  // answer to a destructive control appearing under a pointer that has just
  // pressed something. The record page arranges it structurally — its Delete
  // button is hidden and the panel is drawn somewhere else, with the keyboard
  // put on `Keep it` — and this box has no somewhere else: it is placed at
  // `POP_AT`, the same pointer, and the press that opened this panel was on an
  // item inside its own outline. So the destructive control cannot be pressed at
  // the instant the panel appears, because it is not pressable until the plan
  // has answered what would go with it — a round trip nobody's second click is
  // inside. That is the same guarantee, earned by the thing this panel was
  // always going to have to wait for.
  asking.really.disabled = true;
  asking.keep = popPress('confirm-keep', 'Keep it', 'popkeep');
  // The record page's word for the same press, and `askFor`'s shape of sentence:
  // the control and the key that does the same thing may not report it in
  // different words.
  asking.keep.onclick = () => { announce('nothing was deleted'); popDone(); };
  asking.really.onclick = () => popReally(asking);
  acts.append(asking.really, asking.keep);
  box.append(acts);

  POP_FORM = null;
  POP_CONFIRM = asking;
  POP.classList.remove('popforming');
  POP.classList.add('popasking');
  // `role="dialog"` for `popDrawForm`'s reason: a heading, two paragraphs and a
  // pair of buttons are not children a `role="menu"` may have, and a reader
  // arriving inside one would be told they were in a menu with no items in it.
  POP.setAttribute('role', 'dialog');
  POP.setAttribute('aria-label', `Delete "${asking.title}"?`);
  POP.replaceChildren(box);
  POP.scrollTop = 0;
  popPlace();
  // Onto `Keep it`, which is the record page's own arrangement — `asking(true)`
  // there focuses `button.keep`. The keyboard lands on the way out of a
  // destructive question, never on the way through it.
  asking.keep.focus();
  popCascade(asking);
}

// What the plan says this delete would take with it, drawn where the question
// is. Asked on every open and never cached: a panel that redrew a cascade read
// when some earlier menu was open would be a panel authorising a commit against
// a plan that has moved, which is `attachDrawing`'s rule pointed at the one
// gesture here that cannot be undone from the page.
async function popCascade(asking) {
  asking.really.disabled = true;
  asking.note.textContent = 'Working out what this would take with it…';
  let answer = null;
  let failed = '';
  try {
    const response = await fetch(`/api/cascade/${encodeURIComponent(asking.id)}`);
    answer = await answerOf(response);
    // Through `refusal()` like every other reading of a refusal in this file.
    // This one is a GET and cannot be a compare-and-swap report, and it is read
    // the same way anyway: a call site that knows which key the body holds is a
    // call site that will be wrong the day it stops being true, and
    // `tests/test_writes.py` sweeps for exactly that.
    if (!response.ok) failed = refusal(answer, response.status);
  } catch (error) {
    failed = error.message;
  }
  if (!popAsking(asking)) return;
  if (failed) {
    asking.note.textContent = '';
    // **And the old sentences go.** Reached from `popReally` after a 409 whose
    // re-ask then fails, this arm would otherwise leave the previous cascade
    // drawn — the very list the server has just said is wrong — under a message
    // saying the consequences could not be read. The button is disabled either
    // way, so nothing can be authorised against it; what it would cost is a
    // reader believing a stale list is still the answer.
    popReach(asking, []);
    // **And the button stays disabled.** Offering a delete whose consequences
    // could not be read would be the bare confirm this panel exists instead of,
    // and it would be worse than one: the list is what the route compares
    // against, so a delete pressed here would be refused anyway — after the
    // reader had agreed to something nobody showed them.
    popConfirmSays([
      `What this would take with it could not be read — ${failed}. Nothing was `
      + 'deleted, and nothing can be until the plan answers. Close this and ask '
      + "again, or delete it from the record's own page.",
    ]);
    return;
  }
  asking.also = answer.also || [];
  asking.deletes = answer.deletes || [];
  popReach(asking, answer.said || []);
  asking.note.textContent = POP_REVERT;
  asking.really.disabled = false;
  popPlace();
}

// The consequences, in the words the record page uses and the markup it draws
// them in — `_cascade_facts` (`detail.py`) answers both panels, so what arrives
// here is `{kind, lead, count, mid, names, tail}` rather than a finished
// sentence.
//
// **The parts are not a fussiness.** The count is drawn in a `<strong>` because
// it is the number somebody is agreeing to, and each title gets a chip of its
// own because a title is held to one rule — that it is not blank — so there is
// no character a title cannot contain. Three comma-joined titles, one of which
// has a comma in it, offer a reader four items and ask them to press Delete on
// that.
//
// `append` with a string inserts a text node, so every title on this panel goes
// in as text. There is no `innerHTML` here and there may not be.
function popReach(asking, said) {
  asking.reach.replaceChildren(...said.map(one => {
    const quiet = one.kind === 'frees';
    const line = document.createElement('p');
    line.className = quiet ? 'popreach popmild' : 'popreach';
    // From the two the server can send and not from the string it sent, so a
    // slug is a slug this page chose. The quiet line is the one where nothing is
    // destroyed and a field is edited instead; drawing the two the same way
    // teaches people to skim both.
    line.dataset.kind = quiet ? 'confirm-frees' : 'confirm-deletes';
    line.append(one.lead + ' ');
    if (one.count) {
      const many = document.createElement('strong');
      many.textContent = String(one.count);
      line.append(many, ' ');
    }
    if (one.mid) line.append(one.mid + ' ');
    const names = document.createElement('span');
    names.className = 'popnames';
    (one.names || []).forEach((name, at) => {
      // One literal space between the chips, so that the paragraph still reads
      // as a list to `innerText` and to continuous reading. Measured in Chrome
      // without it on the record page: three titles ran together into one word,
      // which is what a person copies and what a screen reader says aloud.
      if (at) names.append(' ');
      const chip = document.createElement('span');
      chip.className = 'popnamed';
      chip.textContent = name;
      names.append(chip);
    });
    line.append(names);
    if (one.tail) line.append(' ' + one.tail);
    return line;
  }));
}

// The press, and what happens to the panel when the server will not do it.
//
// **A refusal re-asks the cascade rather than offering the same list again.**
// The refusal a delete gets is almost always that the plan moved under the panel
// — somebody filed a task under this pitch while it sat open — and what the
// panel is showing is then a claim about a plan that no longer exists. Pressing
// again against that list would be refused by the same rule for the same reason,
// for ever. So the sentences are replaced, the `also` that goes on the wire is
// replaced with it, and the reader reads the consequences as they now are before
// the button is pressable again.
//
// `popSaid` has already drawn the reason into `why` above the sentences, and
// `popCascade` does not clear it: the refusal is why the panel changed under
// them, and it has to still be there when it has.
async function popReally(asking) {
  // Cannot happen — the button is disabled until this is filled in — and said
  // rather than assumed, because what it guards is a deletion sent with a list
  // this panel never showed anybody.
  if (!asking.also) return;
  asking.really.disabled = true;
  popConfirmSays([]);
  const done = await popDelete(asking);
  if (!done && popAsking(asking)) popCascade(asking);
}

// --- the write doors --------------------------------------------------------
//
// **Three doors, because there are three writes.** Cut 4 had one, with the
// address and the verb passed in as data, and what that cost is not duplication
// saved: the page then carried a single `fetch` whose address is not in the
// source a reader sweeps, announcing one write where three can happen.
// `test_every_write_a_page_makes_is_announced_before_and_after_it` counts a
// page's write call sites against its `openproj:writing` pairs, and its premise
// is written in its own comment — every write path is one call site because it
// is one write. One call site for three writes breaks that premise as surely as
// the drawing save's two call sites for one write, which it has to special-case.
// So: one door per verb, each with its own literal address, its own body, its
// own event pair and its own `finally`.
//
// The body is built in each door rather than handed to one, and that is the
// same rule again read once further: the delete sends `{base_commit, also}` and
// the two saving verbs send `{base_commit, fields, body}`, so a shared door
// would have taken the body as data too and the page would carry one `fetch`
// whose payload is as invisible to a reader as its address was.
//
// **Everything else is shared and lives in one place**, which is the rule that
// made it one door in the first place — an invariant written twice will be
// guarded once. `popStart` is what all three do before the request, `popSettled`
// what all three do with an answer, and `popLost` what all three do when there
// is none; between them they hold the re-entrancy flag, the `#base` guard and
// its advance, the `POP_GEN` snapshot, the one reading of a refusal, and the
// host's `wrote()`. What is left in each door is the four things that genuinely
// differ: the address, the verb, the body, and what to do about a lost answer.
//
// All three answer a promise for `true` when the commit landed, which is also
// how `popRan` knows the item owns its own dismissal.

// Whether one is in the air. See the re-entrancy note in `popStart`, which is
// where the failure it prevents is written down.
let POP_WRITING = false;

// A refusal, into the box that asked for it — or nowhere, if that box has gone.
//
// `popSay` draws the sentence and moves focus onto it. Both are right for the
// menu that sent the write and wrong for any other: by the time a commit answers,
// the reader may have dismissed that box and opened one on a different record,
// and drawing there would put a true sentence about one record under the title of
// another and take the keyboard with it. `announce` still says it either way,
// because a refusal nobody is told about is a write that looks like it worked.
function popSaid(gen, text) {
  if (POP_GEN === gen && !POP.hidden) popSay(text);
  else announce(text);
}

// **What both doors do before the request, and the two ways they refuse to make
// one.** Answers the write in flight — the `#base` element and the generation it
// belongs to — or nothing at all, having already said why.
//
// On either refusal `POP_WRITING` has NOT been taken and no `openproj:writing`
// has been dispatched: the door returns before its `try`, so the `finally` that
// would clear a flag this write never owned, and announce the end of an event
// pair that never began, does not run.
function popStart() {
  // **Two presses 0.9s apart minted two records on the deployed service**, which
  // is why `CREATING` exists in `table.py`. A status item is easier to press
  // twice than that button was — it sits under the pointer, and this box stays
  // up until the answer comes back — and two PATCHes against one base is a page
  // picking a conflict with itself. Before the event in either door, or the
  // count the shell keeps never comes back down.
  if (POP_WRITING) {
    // Drawn and not merely announced, which every other refusal in this box
    // already is: `popSay`'s own comment says a refusal only a screen reader
    // hears is a menu that looks like it did nothing at all. This one is the
    // easiest of them to meet — the item is under the pointer and the box stays
    // up — so it is the last one that should be invisible.
    popSay('A save is already going out. Wait for it to answer.');
    return null;
  }
  // **`#base` is not on every page this module ships on.** It is inside the
  // `editable` branch of the table's template and of the graph's, so a
  // signed-out reader and the static export have none — and the timeline has
  // none at all, having no `may_write` on its route and not one `fetch` in it.
  // A bare
  // `getElementById('base').value` is a null dereference, and in a classic
  // script that throw takes the rest of the block with it: on the timeline it
  // would take the whole menu, including the three items a reader does get.
  //
  // The write half is already behind `POP_HOST.may()`, so this is the belt and
  // not the braces. It is here because `may()` is the host's answer and this is
  // the page's, and the two have disagreed before — `/graph` served a signed-out
  // reader the whole edit mode for the length of the `reader-table` branch.
  const base = document.getElementById('base');
  if (!base) {
    popSay('This page cannot save. Open the record to edit it.');
    return null;
  }
  POP_WRITING = true;
  // `committed` and `landed` travel with the write because each door's `catch`
  // and `finally` need them and neither can see inside `popSettled`. `landed` is
  // whether the commit is known to exist: `wrote()` is awaited inside the `try`
  // and the host's re-read has no `catch` of its own, so a connection dropped
  // after the commit landed rejects there and arrives in the `catch` with the
  // write already in git.
  return {base: base, gen: POP_GEN, committed: null, landed: false};
}

// **What both doors do with an answer**, from the refusal read to the host's
// re-read. Answers the server's answer, or `null` when the write was refused.
//
// `said` is what the live region gets when the commit lands: a sentence naming
// the record and what is now true of it, because the box is gone by then and a
// receipt that says only "saved" is a receipt about nothing. Falsy on a create,
// whose sentence cannot be said yet — what a create needs to report is where the
// new record went, and that has no answer until the host has re-read the plan.
//
// `about` is the record this write was about: the id in the path for a change,
// and nothing at all for a create, which has no id until the server mints one,
// so there the answer supplies it.
async function popSettled(flight, response, said, about) {
  const answer = await answerOf(response);
  // **One reading of a refusal, and it is `refusal()`'s.** A 409 from this
  // server has two shapes — the store's compare-and-swap report and a rule's
  // own sentence, raised before anything is written — and every page that
  // decided for itself which key the body holds has got it wrong. That
  // function is where the two are read in the right order, and
  // `tests/test_writes.py` sweeps for any call site that reaches past it.
  //
  // No `status === 409` arm, which every other write path in this app has.
  // Those have one because they draw a conflict somewhere of their own and
  // merely ANNOUNCE everything else — so a refusal that fell to the `!ok` arm
  // would stop being drawn. Here both arms end in the same place, `popSay`,
  // which says it and draws it in the box the reader is looking at. A branch
  // whose two sides do the same thing is a branch that will drift.
  if (!response.ok) {
    popSaid(flight.gen, refusal(answer, response.status));
    return null;
  }
  flight.committed = answer.commit;
  flight.landed = true;
  // The page moves forward with the repository, or its next write collides
  // with the commit it just made.
  flight.base.value = answer.commit;
  if (said) announce(said);
  // **The menu closes on a write that lands, and it closes here** — before the
  // host redraws, so the keyboard goes back to the element the menu was opened
  // from while that element is still on the page.
  //
  // Closing rather than staying and redrawing, for three reasons that point
  // the same way: the box is placed against a pointer that is now somewhere
  // else; the row it was built from is about to be replaced wholesale by
  // `wrote()`; and the design's own rule is that this box never moves, it only
  // dies. A menu that survived its own write would have to re-read the row and
  // re-place itself, which is the flyout's bargain arriving through the back
  // door.
  //
  // A host whose `wrote()` replaces the element focus has just gone back to —
  // the table's `draw()` does, it rebuilds the whole tbody — owes the keyboard
  // a home of its own. `rove` is what the table hands focus with, and it
  // survives that redraw.
  // **Every write that lands closes the box.** `stays` used to be the
  // exception, for the live card that wrote a field and went on standing there;
  // with one Save per box there is nothing left to stand there for, so the rule
  // is the rule again.
  if (POP_GEN === flight.gen) popDone();
  // **`wrote` is handed the answer and the id**, which cut 2 declared as
  // taking nothing because nothing here wrote. A host needs both to keep a
  // feature it already has: `markSaved` (`table.py`) remembers a commit the
  // server reported as `pushed: false` and marks that row until a later read
  // confirms it landed, and a menu write that did not hand the answer back
  // would take that mark off the one gesture that has no other way to earn it.
  // Both arguments are optional to a host that ignores them.
  if (POP_HOST && POP_HOST.wrote) await POP_HOST.wrote(answer, about || answer.id);
  return answer;
}

// **What both doors do when the request got no answer at all** — two different
// failures, and the pair of sentences `saveCell` (`table.py`) already tells
// apart.
//
// `landed`: the commit came back and the re-read after it did not. The write is
// in git, `#base` has already moved to it, and what is stale is the page.
//
// Otherwise the write itself never got an answer, and this makes no claim about
// what reached the server: a fetch rejects when the answer is lost as readily as
// when the request never left. **What to do about that is the door's to say and
// not this function's**, because the three verbs have different advice — a PATCH
// repeated is the same write, a POST repeated is a second record, and a DELETE
// repeated is a second deletion aimed at a record that may already be gone.
// `retry` is where each one says so.
//
// **A door whose verb is not "save" hands in a function instead of a clause**,
// and it is the delete. "Saved" and "Not saved" are the wrong verb for a record
// that is gone, and a door owning both sentences is the same mechanism read to
// its end rather than a second one parked beside it — the alternative, a fourth
// parameter naming the other half, is two ways of saying who owns the sentence.
function popLost(flight, error, retry) {
  popSaid(flight.gen, typeof retry === 'function'
    ? retry(error, flight.landed)
    : (flight.landed
       ? `Saved, but the page could not read the plan back — ${error.message}. `
         + 'The save went through; reload to see what it changed.'
       : `Not saved — ${error.message}. ${retry}`));
  return flight.landed;
}

// A change to a record that exists. Three call sites in cut 3 and the form's
// diff-only Save in cut 4.
// `stays` is the card-shaped box saving one field and going on being open.
//
// Every other write here closes the menu, and the reason it closes is in
// `popSettled`: a menu is a list of things to do next, placed against a pointer
// that has since moved. A card you are editing in is the thing you are doing,
// so it stays, re-reads the row the host has just replaced, and redraws.
async function popWrite(id, fields, said) {
  const flight = popStart();
  if (!flight) return false;
  // The shell's banner has to know a write is in the air before it starts: the
  // server announces a commit to the event stream before it answers the request
  // that made it, so the news of your own save can arrive before you know its
  // sha. The create door says the same thing for the same reason.
  dispatchEvent(new Event('openproj:writing'));
  try {
    // The id in the path is encoded here, as it is at every other write site in
    // this app: a malformed id is a reported blocker and not a refusal, so an
    // id with a `#` or a `?` in it does reach the page — and raw in a path, the
    // first one truncates it, so the write somebody pressed on one record
    // addresses something else.
    //
    // `body: null` and not `''`, because on a PATCH an empty string is a
    // REPLACEMENT and would blank the shaping document attached to the record.
    const response = await fetch(`/api/record/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: flight.base.value, fields: fields, body: null}),
    });
    return Boolean(await popSettled(flight, response, said, id));
  } catch (error) {
    // The repeat is safe because it is the SAME write — same value, same base —
    // and `_merge_frontmatter` skips every key whose stored value already equals
    // the one being sent, so a write that did land merges with itself and
    // answers 200.
    return popLost(flight, error, 'Try it again: it sends the same value against '
      + 'the same base, so a write that did land is not written twice.');
  } finally {
    POP_WRITING = false;
    // Announced even when the write was refused, or one refusal leaves every
    // banner after it held back and the news that the plan moved never appears
    // again. In a `finally` for that reason, in both doors.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: flight.committed}));
  }
}

// A record that does not exist yet, which is the same shape and a different verb.
//
// **`POST /api/record` is not idempotent, and that is the whole difference.**
// `CREATING` exists in `table.py` because two presses 0.9s apart minted two
// records on the deployed service; `POP_WRITING` covers the press, and the
// sentence a lost answer gets cannot be the PATCH one — "try it again" against a
// create is advice to make a second record.
async function popCreate(fields, title) {
  const flight = popStart();
  if (!flight) return false;
  // Before the request, for the reason written in `popWrite`.
  dispatchEvent(new Event('openproj:writing'));
  try {
    // `body: null` here means the opposite end of the same wire value: the route
    // reads `_body_in(payload) or ""`, so a create gets an empty document.
    //
    // **That is the one thing this form does not do that `+ New row` does.** The
    // draft row posts `TEMPLATES[kind]`, the same kind template `/new` offers,
    // and that map is the table's payload and is in no schema this module has.
    // A record created from the menu therefore opens with a blank document where
    // one created from the row below opens with the kind's headings.
    const response = await fetch('/api/record', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: flight.base.value, fields: fields, body: null}),
    });
    // Nothing said on the commit itself and no id to name the record by: a
    // create has neither until the answer arrives, and `popSettled` reads the
    // minted id off the answer.
    const answer = await popSettled(flight, response, '', null);
    // After the host has redrawn, which is what makes "it is not on screen" a
    // question with an answer. Inside the `try`, so a throw in here is reported
    // by the same catch as a failed re-read rather than escaping unhandled.
    if (answer) announce(popLanded(answer.id, title));
    return Boolean(answer);
  } catch (error) {
    // `createDraft`'s own advice, for `createDraft`'s own reason. And the
    // looking must not be a reload: this box is gone by then either way, but a
    // reload is what takes a second tab's answer away from somebody who is about
    // to decide whether a record exists.
    return popLost(flight, error, 'Look for it in a second tab before pressing Create '
      + 'again, because a second press that both landed would make two records.');
  } finally {
    POP_WRITING = false;
    // See `popWrite`'s: refused or not, the pair has to close.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: flight.committed}));
  }
}

// A record out of the plan, which is the same shape and a third verb.
//
// **Out of the PLAN and not out of the repository**: the commit takes the file
// off the tip and every version of it stays in history, which is the one
// property that makes a delete button here defensible at all. That is what
// `POP_REVERT` says over the button, and it is why the sentences below are
// allowed to be as calm as they are.
//
// **The one door with no `openproj:writing`/`openproj:wrote` pair around it**,
// and that is not an omission. `test_every_write_a_page_makes_is_announced_
// before_and_after_it` counts a page's write call sites — a `fetch` at a literal
// address with `method: 'POST'`, `'PATCH'` or `'PUT'` — against the pairs the
// page dispatches, and a DELETE matches none of those three. A pair here would
// therefore be an announcement of a write the census cannot see, and the page
// would claim four announcements for three countable writes: `/table` and
// `/graph` both fail that assertion by exactly one. The record page's own
// deletion is bracketed by nothing at all for the same reason, while the rekind
// immediately above it has its pair.
//
// That page can afford it because it leaves: a landed deletion sets
// `location.href` and the banner has nowhere to appear. This one stands still,
// so the two things the pair was buying are bought directly in the `finally`
// below — where the sweep's premise, one countable call site per write, stays
// true.
//
// What is genuinely given up is the third thing: `openproj:writing` also HOLDS
// somebody else's banner for the length of the flight, and a commit from another
// tab arriving while this deletion is in the air now draws one immediately. The
// record page's deletion gives up the same thing, and a banner about a write
// that really was somebody else's is news rather than noise.
async function popDelete(asking) {
  const flight = popStart();
  if (!flight) return false;
  const gone = asking.deletes.length;
  // The receipt names the reach as well as the record, because by the time this
  // is said the panel that listed it is gone — and "deleted" alone is a receipt
  // for one file about a commit that removed eight.
  const said = gone
    ? `${asking.title} is deleted, with ${gone} record${gone === 1 ? '' : 's'} `
      + 'that were filed under it'
    : `${asking.title} is deleted`;
  try {
    const response = await fetch(`/api/record/${encodeURIComponent(asking.id)}`, {
      method: 'DELETE', headers: {'content-type': 'application/json'},
      // **What this verb puts beside the base commit is `also` and nothing
      // else**: the ids the panel showed, so that the question the reader
      // answered is the question the server acts on. No `fields` and no `body`
      // — a `fields: {}` on a deletion would be this page telling the server
      // something it does not mean, and it is why each door builds its own body
      // here rather than being handed one.
      body: JSON.stringify({base_commit: flight.base.value, also: asking.also}),
    });
    return Boolean(await popSettled(flight, response, said, asking.id));
  } catch (error) {
    // The one door whose lost answer cannot be described in `popLost`'s own two
    // sentences, so it passes both of them instead of a retry clause. "Saved"
    // and "Not saved" are the wrong verb for a record that is gone, and the
    // second of them is the expensive one: on a protected branch it invites a
    // second press at a record that may already have been removed, and the
    // cascade goes with it. Neither sentence claims to know what reached the
    // server — a fetch rejects when the ANSWER is lost as readily as when the
    // request never left. The record page's own pair, for the same failure.
    return popLost(flight, error, (failed, landed) => landed
      ? `Deleted, but the page could not read the plan back — ${failed.message}. `
        + 'The deletion went through; reload to see the plan without it.'
      : `Not deleted — ${failed.message}. Look before pressing Delete it again: `
        + 'if the first press landed, this record and everything filed under it '
        + 'are already gone.');
  } finally {
    POP_WRITING = false;
    // What the pair the other two doors dispatch would have done here, said to
    // the two listeners that would have heard it — and only on a commit, because
    // a refusal moved nothing and there is no counter left holding anything back.
    if (flight.committed) {
      // **The shell's own event for a commit that is ours and owes the in-flight
      // counter nothing.** Every commit comes back down the stream including this
      // one, and without this the reader is told "The plan changed" about the
      // record they have just deleted, on a page that is still in front of them.
      // `openproj:ours` is what the co-editing room already uses to say exactly
      // that, and it takes a banner down again if the stream beat us to it —
      // which is the normal case here, not the unlucky one, because the server
      // announces a commit before it answers the request that made it.
      dispatchEvent(new CustomEvent('openproj:ours', {detail: flight.committed}));
      // And the other half: every open box dies on a commit, because the rows it
      // was built from have just been replaced by the host's re-read. `popSettled`
      // has already closed the box that sent this deletion, if that box is still
      // the one on screen; this is for the one it is not — a menu opened on a
      // different record while the deletion was in the air, which is an ordinary
      // thing to do over the seconds a commit and a push take. `popClose` leaves a
      // half-filled form alone, here as everywhere else.
      popClose();
    }
  }
}

"""


# What a page that cannot write gets in the write half's place. Not nothing:
# the call site is unconditional, and a missing `popWriteItems` is a
# ReferenceError that takes the reader's three items with it.
_POP_NO_WRITE_JS = r"""
// The write half is not on this page. `_pop_js` was called without an index,
// which is what a static export and a signed-out reader's page get, and what the
// timeline gets on every render because its route has no `may_write` and its
// module has not one `fetch`. A host on such a page whose `may()` answers truthily
// is a wiring mistake, and this says so in the box rather than drawing a reader's
// menu to somebody who may write — the one failure that would look exactly like
// the feature working.
function popWriteItems(row) {
  if (POP_HOST.may && POP_HOST.may())
    return [{kind: 'no-schema', text: 'Editing is unavailable here',
             why: 'This page was rendered without the menu\'s write half.'}];
  return [];
}
"""


# The three fields whose control is a list to pick from rather than a box to
# type in, spelled once. `EDITABLE`'s values are the types the RECORD PAGE's
# controls are built from, where `status` and `priority` each have a bespoke
# widget — the hill and the meter — and `parent` is a text box with a datalist
# behind it. A floating form has room for none of those, and the form's whole
# reason for existing is that `parent` must be a picker: a `<select>` built from
# rows that exist is the one control that cannot express either of the two holes
# `parent_refusal` (`model.py`) now closes behind it.
_AS_SELECT = ("status", "priority", "parent")


def _pop_schema(index: Index | None) -> dict | None:
    """What the write half is built from, per render.

    **Baked here rather than read out of the host's payload, because the three
    hosts do not have one between them.** The table ships every map below in
    `DATA`; the graph's payload is cytoscape elements and carries none of them;
    the timeline has neither. A menu that read the page it happened to be on
    would be three menus, and the first thing to go wrong would be the thing that
    already went wrong to the hover card — `in_progress` drawn on the graph where
    the other two views said "In progress".

    Every value is the app's own one map for that fact, imported rather than
    restated: an invariant written twice will be guarded once, and three
    hand-written status maps beside the ladder is a failure this repository has
    already had.

    `None` where there is no index, which is the static export: there is nothing
    to write to there, and a schema would be bytes on every page of it.

    **Bytes, measured.** It ships in every writer's copy of three pages, so its
    size is a real cost and the shape below is chosen around it. Over `seed/` on
    2026-09-18, as minified JSON: **3396 bytes before cut 4 and 4882 after**, and
    5366 as `tojson` actually writes it into `/table` (the difference is its
    `<`/`>`/`&` escaping, which is not optional). Of the 1486 added, the per-kind
    field lists are 636, the type map 353 and the four small maps beside them 428.
    `people` is the only key that grows with the plan. Two things keep the total
    from being half as large again: a field's TYPE ships once rather than once
    per kind, and the two lists that already existed for the menu — `statuses`
    and `required` — are the form's choices and its gate as well.
    """
    if index is None:
        return None
    return {
        # The status vocabulary per kind, off the ladder itself. `()` is how a
        # rung says it reads no status at all — a product is not `in_progress` —
        # and the menu draws that as a refusal rather than an empty list.
        "statuses": {name: list(rung.statuses) for name, rung in RUNG.items()},
        # And which fields a rung does not read, the same list `_row` empties a
        # container's cells by. `owner` is in it for a product, which is why the
        # Owner submenu is refused there before anything is sent.
        "unread": {name: list(unread_fields(name)) for name in RUNG},
        "glyphs": STATUS_GLYPH,
        "human": HUMAN,
        "labels": LABELS,
        # Which statuses demand which fields, derived by running the gate over a
        # blank record rather than written beside it — so it cannot drift from
        # the rule it mirrors. Per kind, because a row is one kind: merged, the
        # map says a project is missing `person_weeks` at `ready` and a project
        # has no such field.
        "required": {name: required_at(name) for name in RUNG},
        # Which kind may hold which, from the model's own map. It decides one
        # thing in cut 3 — whether a record with no parent is one nothing holds
        # or one nothing CAN hold — and it is the picker `Assign parent…` is
        # built from in cut 4.
        "parent_kinds": {kind: list(kinds) for kind, kinds in PARENT_KINDS.items()},
        # The same ladder read downwards, from the model's own second map rather
        # than inverted here or in the browser. `New child ▸` asks the question
        # about the record under the pointer — which kinds can be made INSIDE
        # this one — and `test_the_ladder_reads_the_same_in_both_directions`
        # already holds the two maps to being exact inverses. Three lines of
        # JavaScript rebuilding it would be a third spelling of the ladder, in
        # the one language nothing here tests it in.
        "child_kinds": {kind: list(kinds) for kind, kinds in CHILD_KINDS.items()},
        # -- what the FORM is drawn from ------------------------------------
        #
        # **Which fields, per kind; what type each is, once.** Membership is the
        # part that varies — a project has no appetite, a product is filed under
        # nothing, `reported_by` exists on two rungs out of six — and it is asked
        # of `_editable_for` over a blank record, which is the same function the
        # record page and the create form draw their boxes from. So a form here
        # cannot offer a box the validator then complains about, which is the
        # failure `unread_fields`' own docstring names.
        #
        # Deliberately NOT `_new_rows`' union (`detail.py`): its `rows.setdefault`
        # builds each control from whichever kind reached it first, and the first
        # rung is `product` — so the union has exactly one `parent` control, built
        # for the kind that may not have a parent at all, and cannot express the
        # per-kind picker this form is about.
        "fields": {kind: [field["name"] for field in _editable_for(_blank(kind))] for kind in RUNG},
        # A field's type does not vary by kind — `EDITABLE` is one map — so it
        # ships once beside the per-kind lists rather than repeated inside them.
        # Six kinds times fourteen names is where this schema's bytes are, and
        # this is the one place they can be halved without losing a fact.
        "types": {
            name: ("select" if name in _AS_SELECT else kind) for name, kind in EDITABLE.items()
        },
        # Where a field's completion comes from: `parent` and `depends_on` from
        # the host's own rows, and everything else from one of the lists below.
        #
        # It shipped filtered to `people` and `records` when the box this menu
        # opened was a form of its own; jcanton asked for the rest once that form
        # became the card — 2026-09-18, "autocomplete doesn't work in the forms
        # inside our new editable card. can you enable all as in the /detail?" —
        # and a field pointing at a list nobody serves is the control that
        # silently completes nothing, so the lists come with it.
        "suggests": dict(SUGGESTS),
        # The one select whose options are neither per kind nor per plan.
        "priorities": list(PRIORITIES),
        # The status a record of this kind is created in, off the model's own
        # default through `opens_at`. `New child ▸` opens a form with nothing in
        # it, and a status box that starts blank is a required field the reader
        # has to fill before they have said anything. Only the rungs that read a
        # status at all: a product opens at nothing, and a map claiming otherwise
        # would put a word in a box that is not drawn.
        "opens": {kind: opens_at(kind) for kind, rung in RUNG.items() if rung.statuses},
        # The people the page already knows, from the same function the table's
        # suggestion list is filled by. A second reading of "who is on this plan"
        # would disagree with the box beside it the first time somebody joined.
        # Values only: the menu writes a login, and the `{value, label}` shape is
        # for a control that completes as you type.
        "people": [person["value"] for person in _suggestions(index)["people"]],
        # And the three lists that are neither a person nor a record, from the
        # same function, in the same `{value, label}` shape the detail form's own
        # completion reads them in: a tag is a bare word, a pull request carries
        # the `org/repo#` half nobody remembers, and a cycle NUMBER means nothing
        # without the window beside it.
        #
        # **`records` is deliberately not here.** `parent` and `depends_on`
        # complete off `popAllRows()`, which is the host's own rows — the same
        # list the parent picker is built from — and a second copy of every
        # record in the plan is the one key that would double this payload.
        "lists": {
            source: _suggestions(index)[source] for source in ("tags", "prs", "cycles")
        },
    }


def _pop_js(links: Links, index: Index | None = None) -> Markup:
    """The menu's whole script, with the two things in it the server decides.

    A function rather than the constant `_FILTER_JS` is, because where a record's
    page lives is a fact about the mode this render is in: `/detail/` from the
    server and `detail.html#` in the export. `_page` takes a style as a finished
    string and a template as finished markup, so a `{{ }}` left in a constant is
    literal text that silently does nothing — which is how one rule in
    `_GRAPH_STYLE` first shipped as a no-op.

    **A view whose `popServes({may})` can answer truthily has to pass `index`.**
    Left out, the write half has nothing to build itself from and the menu says
    so in the box rather than quietly drawing a reader's menu to somebody who may
    write — which is the one failure that would look exactly like the feature
    working. The default is for the export and for a view that is reader-only by
    construction, which is the timeline.
    """
    half = _POP_WRITE_JS if index is not None else _POP_NO_WRITE_JS
    return _fragment(
        "<script>" + _POP_JS_READ + half + "</script>",
        record=links.record,
        schema=_pop_schema(index),
    )
