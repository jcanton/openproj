"""The right-click menu: one floating box, three hosts.

`design/context-menus.md` is the whole argument. Cut 2 built the box, the host
contract and the reader's three items; cut 3 is the one below it — the submenu
machinery, the three one-field writes (`Status ▸`, `Owner ▸`, `Take out of "X"`)
and `popWrite`, which is the only door any of them goes out through. The form,
and the two items that need one, are cut 4; `Delete…` is cut 5.

**One write door.** Three call sites here and six by cut 5, each of which would
otherwise carry its own copy of the base commit, the re-entrancy flag, the
`openproj:writing`/`openproj:wrote` pair and the reading of a refusal. That last
one is not a tidiness: a 409 from this server has two shapes, and every page that
decided for itself which key the body holds has got it wrong — see `popWrite`.

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
from ..model import PARENT_KINDS, RUNG, required_at, unread_fields
from .controls import _suggestions
from .env import _fragment
from .shell import Links
from .tokens import HUMAN, LABELS, STATUS_GLYPH

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
//   });
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
// `stays` keeps the box up after the run. Exactly one item has it — `‹ Back`,
// whose whole job is to leave the box open showing something else.
function popItems(row) {
  const href = POP_RECORD + row.id;
  const items = [];
  // **The write half**, behind `POP_HOST.may()` — `Status ▸`, `Owner ▸` and
  // `Take out of "X"` here; `New child ▸`, `Edit…` and `Assign parent…` in cut
  // 4, `Delete…` in cut 5. The ORDER is the design: what changes the plan, then
  // what this view can do, then the three that only look — which are the ones a
  // reader gets, and the ones that stay at the bottom so their position does not
  // move when somebody signs in.
  for (const item of popWriteItems(row)) items.push(item);
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

// --- the write half ---------------------------------------------------------
//
// The reader's word for a stored identifier, and a field's label. Both out of
// the schema and never written down here: `HUMAN` and `LABELS` (`tokens.py`) are
// one map each for the whole app, because five pages inventing their own is how
// `in_progress` came to be spelled three ways on one screen.
const popHuman = value => (POP_SCHEMA.human || {})[value] ?? (value ?? '');
const popLabel = field => (POP_SCHEMA.labels || {})[field] || field;
// What to call a record in a sentence. The same fallback the box's own
// `aria-label` uses: a record with no title is still a record you can act on.
const popTitle = row => row.title || row.id;
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
  return [popStatusItem(row), popOwnerItem(row), popTakeOutItem(row)];
}

// Whether this row has a value for that field at all — `holds` (`table.py`),
// which is where the four ways a field can be unset are enumerated. An
// `assignees: []` that read as a value would be a row silently exempted from a
// gate.
function popHolds(row, field) {
  const value = row[field];
  return !(value === null || value === undefined || value === ''
    || (Array.isArray(value) && value.length === 0));
}

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
// **In cut 4 this item stops being refused at all**: the design has it open the
// form with `only:` the missing fields and the new status pre-filled, and save
// both in one commit, which is exactly what `askFor` does today. Until there is
// a form to open, the honest thing is to name what is missing and where to put
// it — an error says what went wrong and how to fix it.
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
  // **The gate is honoured, not fought.** A status whose `required_at` names
  // fields this record does not hold cannot be written, so the item says so
  // rather than sending a PATCH the server will refuse.
  const missing = popMissing(row, status);
  if (missing.length) {
    item.why = popNeeds(row, status, missing);
    return item;
  }
  item.run = () => popWrite(row.id, {status: status},
    `${popTitle(row)} is now ${popHuman(status)}`);
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

// Which descriptor a drawn control came from, for the keys that act on the item
// rather than on the element — ArrowRight has to know whether there is a list
// behind this row. A WeakMap and not a property on the element: every control is
// thrown away and rebuilt on every draw, and this lets them be collected with
// them.
const POP_OF = new WeakMap();

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
  // And `stays` for the one item whose whole job is to leave the box open and
  // showing something else: `‹ Back`. It is a plain synchronous `run`, so
  // without this the mouse path through it CLOSED the menu while the keyboard
  // path — ArrowLeft and Escape, which call `popBack` directly — popped a level
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
function popClose() {
  if (POP.hidden) return;
  POP.hidden = true;
  POP_ID = null;
  POP_GEN += 1;
  // The refusal goes with the box. The levels do not, for the same reason the
  // items do not — the next open replaces both — but a sentence about a write
  // that was refused a minute ago has no business being the first thing on the
  // next menu anybody opens.
  POP_SAID = '';
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
addEventListener('openproj:wrote', event => { if (event.detail) popClose(); });

// A right press INSIDE the menu is the browser's business and not ours. Its
// default action is deliberately left alone — that is half the reason `Open in
// new tab` is a real `<a>` — and it is stopped from reaching the view's own
// `contextmenu` listener, which is on the document on at least one of the three
// and would answer it by rebuilding this box under the press.
POP.addEventListener('contextmenu', event => { event.stopPropagation(); });

// --- the write door ---------------------------------------------------------
//
// **One door, and every write this menu makes goes through it.** Three call
// sites today and six by cut 5; a second copy of the base commit, the
// re-entrancy flag, the event pair and the refusal reading is the shape this
// repository has paid for four times over — an invariant written twice will be
// guarded once.
//
// `said` is what the live region gets when the commit lands: a sentence naming
// the record and what is now true of it, because this box is gone by then and a
// receipt that says only "saved" is a receipt about nothing.
//
// Answers a promise for `true` when the commit landed, which is also how
// `popRan` knows the item owns its own dismissal.
//
// Whether one is in the air. See the re-entrancy note at the top of the
// function, which is where the failure it prevents is written down.
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


async function popWrite(id, fields, said) {
  // **Two presses 0.9s apart minted two records on the deployed service**, which
  // is why `CREATING` exists in `table.py`. A status item is easier to press
  // twice than that button was — it sits under the pointer, and this box stays
  // up until the answer comes back — and two PATCHes against one base is a page
  // picking a conflict with itself. Before the event below, or the count the
  // shell keeps never comes back down.
  if (POP_WRITING) {
    // Drawn and not merely announced, which every other refusal in this box
    // already is: `popSay`'s own comment says a refusal only a screen reader
    // hears is a menu that looks like it did nothing at all. This one is the
    // easiest of them to meet — the item is under the pointer and the box stays
    // up — so it is the last one that should be invisible.
    popSay('A save is already going out. Wait for it to answer.');
    return false;
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
    return false;
  }
  POP_WRITING = true;
  // The shell's banner has to know a write is in the air before it starts: the
  // server announces a commit to the event stream before it answers the request
  // that made it, so the news of your own save can arrive before you know its
  // sha.
  dispatchEvent(new Event('openproj:writing'));
  const mine = POP_GEN;
  let committed = null;
  // Whether the commit is known to exist. `wrote()` is awaited inside the `try`
  // and the host's re-read has no `catch` of its own, so a connection dropped
  // after the commit landed rejects there and arrives below.
  let landed = false;
  try {
    // The id is encoded, as it is at every other write site here: a malformed id
    // is a reported blocker and not a refusal, so an id with a `#` or a `?` in
    // it does reach the page — and raw in a path, the first one truncates it, so
    // the write somebody pressed on one record addresses something else.
    //
    // `body: null` because an empty string is a replacement and not an
    // omission, and would blank the shaping document attached to the record.
    const response = await fetch(`/api/record/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: base.value, fields: fields, body: null}),
    });
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
      popSaid(mine, refusal(answer, response.status));
      return false;
    }
    committed = answer.commit;
    landed = true;
    // The page moves forward with the repository, or its next write collides
    // with the commit it just made.
    base.value = answer.commit;
    announce(said);
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
    if (POP_GEN === mine) popDone();
    // **`wrote` is handed the answer and the id**, which cut 2 declared as
    // taking nothing because nothing here wrote. A host needs both to keep a
    // feature it already has: `markSaved` (`table.py`) remembers a commit the
    // server reported as `pushed: false` and marks that row until a later read
    // confirms it landed, and a menu write that did not hand the answer back
    // would take that mark off the one gesture that has no other way to earn it.
    // Both arguments are optional to a host that ignores them.
    if (POP_HOST && POP_HOST.wrote) await POP_HOST.wrote(answer, id);
    return true;
  } catch (error) {
    // Two different failures reach here and they get two different sentences —
    // the pair `saveCell` (`table.py`) already tells apart.
    //
    // `landed`: the commit came back and the re-read after it did not. The write
    // is in git, `base.value` has already moved to it, and what is stale is the
    // page.
    //
    // Otherwise the write itself never got an answer, and this makes no claim
    // about what reached the server: a fetch rejects when the answer is lost as
    // readily as when the request never left. The repeat is safe because it is
    // the SAME write — same value, same base — and `_merge_frontmatter` skips
    // every key whose stored value already equals the one being sent, so a write
    // that did land merges with itself and answers 200.
    popSaid(mine, landed
      ? `Saved, but the page could not read the plan back — ${error.message}. `
        + 'The save went through; reload to see what it changed.'
      : `Not saved — ${error.message}. Try it again: it sends the same value `
        + 'against the same base, so a write that did land is not written twice.');
    return landed;
  } finally {
    POP_WRITING = false;
    // Announced even when the write was refused, or one refusal leaves every
    // banner after it held back and the news that the plan moved never appears
    // again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

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
        # The people the page already knows, from the same function the table's
        # suggestion list is filled by. A second reading of "who is on this plan"
        # would disagree with the box beside it the first time somebody joined.
        # Values only: the menu writes a login, and the `{value, label}` shape is
        # for a control that completes as you type.
        "people": [person["value"] for person in _suggestions(index)["people"]],
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
    return _fragment(_POP_JS, record=links.record, schema=_pop_schema(index))
