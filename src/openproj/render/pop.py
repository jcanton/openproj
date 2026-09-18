"""The right-click menu: one floating box, three hosts.

`design/context-menus.md` is the whole argument; this is the second cut of it —
the box, the host contract, and the reader's three items. Nothing here writes.
That is deliberate rather than unfinished: the judgement jcanton makes on this
cut is menu-versus-hover, and it has to be made before any of it can change the
plan.

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

from .env import _fragment
from .shell import Links

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
/* One item. `white-space: nowrap` with an ellipsis rather than wrapping: from
   cut 3 an item carries a record's title (`Take out of "…"`), and a menu whose
   rows are three lines tall is a menu you cannot scan. */
#pop .popitem {
  display: block; width: 100%; text-align: left; font: inherit; color: inherit;
  background: none; border: none; padding: .35rem .75rem; cursor: pointer;
  text-decoration: none; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;
}
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
"""


# The menu itself. One `<script>` block, the shape `_FILTER_JS` already has, put
# into each view's template ABOVE the view's own script — these are classic
# scripts sharing one global scope, and a function in a later block is not
# hoisted into an earlier one, so a `popServes(...)` call in a view's script
# needs this block to have run.
_POP_JS = r"""
<script>
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

// --- the host contract ------------------------------------------------------
//
// A view registers itself once and then knows nothing else about this menu:
//
//   popServes({
//     may: () => EDITABLE,          // may_write, from the server
//     rows: id => DATA.rows[id],    // the row view model — `rows.py:_row`
//     extras: row => [ … ],         // this view's own items
//     wrote: () => refreshRows(),   // what to do after a write lands
//   });
//
// `rows` is the only one cut 2 calls. `may` gates the write half, which is cuts
// 3 to 5, and it is deliberately NOT called here — an answer nothing reads is a
// contract nobody is holding to, and a reader who watched `may()` run and saw no
// write item would be right to wonder which of the two was broken.
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
// `popRan`.
function popItems(row) {
  const href = POP_RECORD + row.id;
  const items = [];
  // **The write half lands here**, behind `POP_HOST.may()` — `New child ▸`,
  // `Edit…`, `Status ▸`, `Owner ▸`, `Assign parent…`, `Take out of "X"` in cuts
  // 3 and 4, `Delete…` in cut 5. The slot is named rather than left implicit
  // because the ORDER is the design: what changes the plan, then what this view
  // can do, then the three that only look — which are the ones a reader gets,
  // and the ones that stay at the bottom so their position does not move when
  // somebody signs in.
  //
  // This view's own items, spliced in whole. Asked on every open and never
  // stored, which is `attachDrawing`'s rule (`controls.py`) and the reason a
  // host can refuse against state that moved since the last open. A host with
  // none of its own may leave `extras` out entirely.
  for (const extra of (POP_HOST.extras ? POP_HOST.extras(row) : null) || []) items.push(extra);
  items.push({kind: 'open', text: 'Open', run: () => { location.href = href; }});
  items.push({kind: 'open-tab', text: 'Open in new tab', href: href});
  items.push({kind: 'copy-link', text: 'Copy link', run: () => popCopy(href)});
  return items;
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
  control.setAttribute('role', 'menuitem');
  // `textContent`, never `innerHTML`. This is the JavaScript half of the one
  // escaping boundary, and from cut 3 an item's text carries a record's title.
  control.textContent = item.text;
  // Roving tabindex, set properly by `popFocus`. -1 here so a control that has
  // never been focused is out of the Tab sequence: Tab leaves the menu, and the
  // arrows are what walks it.
  control.tabIndex = -1;
  if (item.why) {
    control.setAttribute('aria-disabled', 'true');
    control.dataset.why = item.why;
  }
  control.onclick = event => popRan(event, item);
  return control;
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
  if (item.run) item.run();
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

// --- opening ----------------------------------------------------------------

// Returns whether a menu was opened, and the call site is
// `if (!event.shiftKey && popMenu(event.clientX, event.clientY, id)) event.preventDefault();`
// — a press on something this view has no row for gets the browser's own menu
// rather than an empty box of ours.
function popMenu(x, y, id) {
  if (!POP_HOST) return false;
  const row = POP_HOST.rows(id);
  if (!row) return false;
  // Read before anything of ours takes focus, because `document.activeElement`
  // is what the keyboard fallback measures.
  const at = popAt(x, y);
  const items = popItems(row);
  if (!items.length) return false;
  POP_RETURN = document.activeElement;
  POP_ID = id;
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
  POP.setAttribute('aria-label', 'Actions for ' + (row.title || row.id));
  // Rebuilt from scratch on every open and never stored, which is
  // `attachDrawing`'s rule and the reason cut 3's status submenu cannot show a
  // stale word after a save.
  POP.replaceChildren(...items.map(popControl));
  // Back to the corner BEFORE it is measured. A `position: fixed` box with a
  // `left` and no `right` is shrink-to-fit against what is left of the viewport,
  // so the same three items measured 54.17px wide sitting at the previous menu's
  // `left: 1250px` and 111.56px at the origin — headless Chrome at 1280px,
  // 2026-09-18. `placeFloat` reads that width to decide which side of the
  // pointer to draw on, so a stale one flips a box that fits and clamps one that
  // does not.
  POP.style.left = '0px';
  POP.style.top = '0px';
  POP.hidden = false;
  placeFloat(POP, at.x, at.y);
  // Focus the first item on every open, including a pointer's. It is what makes
  // the arrows and Escape work without a click first — and the Escape handler
  // below is bound on this box, so it only ever sees the key because focus is
  // inside it.
  popFocus(0);
  return true;
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
function popClose() {
  if (POP.hidden) return;
  POP.hidden = true;
  POP_ID = null;
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
  popClose();
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
  const here = [...POP.children].indexOf(document.activeElement);
  if (event.key === 'ArrowDown') { event.preventDefault(); popFocus(here + 1); return; }
  if (event.key === 'ArrowUp') { event.preventDefault(); popFocus(here - 1); return; }
  if (event.key === 'Home') { event.preventDefault(); popFocus(0); return; }
  if (event.key === 'End') { event.preventDefault(); popFocus(POP.children.length - 1); return; }
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
  popDone();
});

// The roving tabindex. Exactly one item is in the Tab sequence and it is the one
// with focus, so Tab leaves the menu instead of walking it.
function popFocus(at) {
  const items = [...POP.children];
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
addEventListener('openproj:filter', popClose);
addEventListener('openproj:wrote', popClose);

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
</script>
"""


def _pop_js(links: Links) -> Markup:
    """The menu's whole script, with the one thing in it the server decides.

    A function rather than the constant `_FILTER_JS` is, because where a record's
    page lives is a fact about the mode this render is in: `/detail/` from the
    server and `detail.html#` in the export. `_page` takes a style as a finished
    string and a template as finished markup, so a `{{ }}` left in a constant is
    literal text that silently does nothing — which is how one rule in
    `_GRAPH_STYLE` first shipped as a no-op.
    """
    return _fragment(_POP_JS, record=links.record)
