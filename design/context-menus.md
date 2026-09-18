# The right-click menu, and the popup it opens

Asked for on 2026-09-18: "can we have contextual right-click menus? e.g. I'd like to be able to
right-click a record in table and graph view and have the option of creating a child record". The
shape below is what that turned into over one conversation, and the parts that were refused are kept
because each of them was refused for a measured reason.

## What it is

Right-click a record — a row in the table, a node in the graph, a bar or a label on the timeline —
and a menu opens at the pointer. Its items act on that record. Two of them open a second face of the
same box: a form with the record's fields in it, a Save button, and nothing else. That form is how a
child record gets made without leaving the page, which was the original ask.

One new module, `src/openproj/render/pop.py`, holds both faces and is imported by the three views
that want them. Not `shell.py`: that file is 4021 lines and ships on all twelve pages, including
`/help` and `/people`, and this thing reads `base_commit` and writes records. A module imported by
the pages that want it is the shape this codebase already uses three times over — `_FILTER_JS`
(`controls.py`), `_REQUIRED_JS`, and `_combobox_html`, which is called from `cycles.py`,
`detail.py`, `slides.py` and `table.py`.

## The hover card does not change

The first draft of this design deleted the hover card. The menu needed a pointer-positioned floating
box with flip-and-clamp placement, an explicit `[hidden]` rule and a shadow; `#card` is exactly that
box, already shipped on three views, and hover-intent was the only thing standing in the way. The
deletion also paid a second time: the 600ms `CARD_DELAY` was the only thing racing cytoscape's 500ms
`taphold`, so long-press on the graph came free with it.

jcanton, reading that: **"I didn't mean kill the card entirely: kill it / hide it if right click is
detected, but it should still show up on hover!"**

So the card stays, whole — `queueCard`, `CARD_DELAY`, `CARD_GRACE`, `warmCardBody`, the drag grip,
the remembered height, all nineteen tests in `tests/test_card.py`. The menu is a **second**
body-mounted singleton beside it, not the same element wearing a mode. Two boxes and not one, and
that is deliberate rather than lazy: the card has a live hover timer, a grip drag that suspends its
own dismissal (`cardResizing`, `shell.py`) and a two-pass draw that exists because a
one-pass card visibly grew and re-placed itself after appearing — reported 2026-08-20. A menu sharing
an element with all of that is a menu racing it.

What the two boxes owe each other is one rule, and it is the whole of the interaction:

> **Opening the menu kills the card, and the card does not come back while the menu is up.**

Which is three things, not one. `hideCardNow()`, unconditionally — including through the
`cardResizing` early-return, because a right-click during a grip drag must still get its menu.
Cancelling `cardTimer`, because a card queued 400ms ago and not yet drawn will otherwise appear on
top of the menu. And a flag that `queueCard` consults, because the pointer is sitting over the row
the menu covers and every `pointermove` re-arms it.

## Desktop only

The first shape of this offered long-press on the graph on the grounds that cytoscape already fires
`taphold` — one event name in an existing string. It also needed a guard that is worth writing down
even though the feature is gone, because it is not obvious and it was nearly shipped without it:
cytoscape's mousedown handler branches `if (3 == t.which) { cxttapstart } else if (1 == t.which) {
… tapholdTimeout = setTimeout(…, 500) }`. **The taphold timer is armed by the left button.** An
unguarded `taphold` handler on a page whose primary gesture is dragging a node opens a menu every
time somebody presses a node and thinks for half a second before moving it.

On the table a long-press was never cheap: a `pointerdown` timer with three cancellation paths, plus
`-webkit-touch-callout: none` and `user-select: none` on the pressed row, which kills text selection
in cells — and iOS Safari's own callout fires on the same gesture, with no iOS in CI, so the claim
could only ever be finished by hand on a phone. A visible `⋯` button under the 40rem breakpoint was
offered as the honest alternative.

jcanton, 2026-09-18: **"make all desktop only then, no touch longpresses, better."**

So: `contextmenu` on the table and the timeline, `cxttap` on graph nodes, and no gesture anywhere
that a mouse does not have. Cytoscape fires `cxttap` for a two-finger tap as well as a right-click;
that is free and harmless and is not a feature this document claims.

**Shift+right-click falls through to the browser's own menu**, on every view including the graph. The
graph was the one that looked impossible: cytoscape binds `registerBinding(e.container,
"contextmenu", e => e.preventDefault())`, so the canvas eats the native menu before anything of ours
sees it. That binding is bubble-phase on the container, which a capture-phase listener on the same
element beats:

```js
CYBOX.addEventListener('contextmenu', e => { if (e.shiftKey) e.stopPropagation(); }, true);
```

`stopPropagation`, not `stopImmediatePropagation` — the listener is on the same element in an earlier
phase, so stopping propagation is enough and stopping it immediately would be a claim about listener
order that nothing here needs to make.

## The host contract

A view registers itself once and then knows nothing else about the menu:

```js
popServes({
  may: () => EDITABLE,          // may_write, from the server
  rows: id => DATA.rows[id],    // the row view model — rows.py:_row, the same object in all three views
  extras: row => [ … ],         // this view's own items, spliced into a marked slot
  wrote: () => refreshRows(),   // what to do after a write lands
});
```

Everything else — which items exist, what they say, which are refused and why — is built inside
`pop.py` from the row and the server-baked schema. The views do not each own a menu; there is one
menu and three hosts. The timeline registers `may: () => false` and gets the reader's menu, which is
the right answer for a page that has no `#base` element, no `may_write` on its route
(`web.py` does not even take a `request`) and not one `fetch` in `timeline.py`.

## The items

An item is `{kind, text, why?, items?, run?, href?}`. `kind` is a stable slug, drawn as `data-kind`,
and it is the test handle. `why` present means the item is **refused**: drawn dim, `aria-disabled`
(not `disabled`, so it stays focusable and can still be asked), and pressing it announces the reason.
An item that would vanish is drawn refused instead — a control that disappears teaches nothing about
why.

In order, with the write half present only when `host.may()`:

| item | what it does |
| --- | --- |
| `New child ▸` | one entry per kind this record may hold; opens the form with `parent` filled and locked |
| `Edit…` | the form, on this record |
| `Status ▸` | one entry per status in this kind's ladder, current one `aria-checked` |
| `Owner ▸` | the people from the suggestion blob, plus "— nobody —" and "Someone else…" |
| `Assign parent…` | the form, `only: ['parent']` |
| `Take out of "X"` | a `{parent: ''}` PATCH |
| *host extras* | graph: "Add dependency from here", "Focus subtree". table: "Focus subtree" |
| `Open` / `Open in new tab` / `Copy link` | |
| `Delete…` | the cascade confirmation |

`Open in new tab` is a real `<a target="_blank">` and not a `run()`, so middle-click works and the
browser's own context menu on it works.

**`Status ▸` honours the status gate rather than fighting it.** Picking a status whose `required_at`
names fields this record does not hold neither writes nor refuses: it opens the form with `only:` the
missing fields and the new status pre-filled, and saves both together. That is exactly what `askFor`
(`table.py`) does today, and it is the reason the gate is worth having.

**"Take out of X" has three sentences, not two.** `_row` nulls a parent that is not in `index.plan`
and sets a separate boolean beside it (`rows.py`). So "it is not inside anything" is
the wrong sentence for a record that *is* inside something this view cannot draw, and
`off_plan_parent` gets its own words. This is the same shape as the bug
`tests/test_exclusion.py` was written for.

### Submenus drill down; they do not fly out

`New child ▸` replaces the item list in the same box, with `‹ Back`, and Escape or ArrowLeft pops a
level. The alternative — a second `#pop-sub` element opening beside the item — is the conventional
desktop idiom and was refused for cost: a second element, a second placement function with its own
edge-flipping, and a hover-intent model this app no longer has anywhere. One box means one placement
and one dismissal. It costs a click on `Status ▸`, and it is reversible if that click annoys.

Items are rebuilt from scratch on every open and never stored, which is `attachDrawing`'s rule
(`controls.py`) and the reason a status submenu cannot show a stale word after a save.

## Placement and dismissal

`placeFloat(box, x, y)` is `placeCard` (`shell.py`) extracted as a pure function: 14px from the
pointer, flipped to the other side when the box would cross the far gutter, floored at 8px. Viewport
coordinates, because the box is `position: fixed` — not `position: absolute` and parked the way
`.drawmenu` is, because `.table-scroll`'s `overflow: auto` (`styles.py`) and the frozen columns'
sticky stacking contexts clip and under-paint anything absolute.

**The menu never moves once placed; it only dies.** Six signals close it: `pointerdown` on the
document outside the box (`pointerdown` and not `click`, so a menu over the thing somebody is
reaching for is gone before the press lands — the reason is written out at `controls.py`),
Escape, a capture-phase `scroll`, `resize`, `openproj:filter`, and `openproj:wrote`. The graph adds
`cy.on('drag pan zoom')`. This is why the box is never anchored to a row or a node: the table's
`draw()` replaces the whole tbody, and the graph's `relayout()` ends in `cy.fit()` — a menu anchored
to either is a menu pointing at nothing.

The **form** re-places on every content change, because a refusal list growing under a box already
near the bottom of the window would otherwise push its own Save button off screen.

### Escape has five meanings on the table, not four

Parking the box on `document.body` routes around four of them — they are bound on the tbody or on
cells, and the box is not inside either. The fifth is not: `table.py` is
`addEventListener('keydown', …)` on the **document**, and it drops a bulk selection. An Escape from
the menu bubbles to it. So the box's own Escape handler ends in `stopPropagation()`, after an
`if (event.defaultPrevented) return;` first, and the comment there says which four are structural and
which one is arbitrated. `test_escape_in_the_menu_does_not_discard_the_draft_row` is the test that
fails if the box is ever mounted inside the tbody.

### The keyboard's menu key has no pointer

`ContextMenu` and Shift+F10 deliver a `contextmenu` event that bubbles like any other, so the menu
comes free — but the coordinates do not. Chrome reports the focused element's box; Firefox has
reported `0,0`. Without a fallback to `document.activeElement.getBoundingClientRect()` the menu opens
in the top-left corner, and on the table — where a roving-tabindex grid is the whole keyboard story —
that is the most likely path a keyboard reader takes.

## The form

`_pop_schema(index)` is baked per kind by the server, through `_editable_for` on a blank model. Per
kind and not `_new_rows`' union: that function's `rows.setdefault` (`detail.py`) builds
`parent`'s control from whichever kind reached it first, and cannot express a per-kind picker.

The form draws one control per field, a refusal list filled with `textContent` and never `innerHTML`,
and a primary verb plus Cancel. It is **fields only** — the body stays on the detail page, which has
Ace, co-editing seats and a draft receipt, and a markdown editor in a floating box would be competing
with the page that does it properly.

**The parent control is a `<select>` built from the host's own rows, never free text.** That picker is
the only thing standing in front of two holes in the server: `_containment_problems` returns early on
an unresolvable parent (`model.py`), so a dangling parent commits silently; and PATCH calls
`loop_made` but never `validate_all`, so a wrong-kind parent commits and is reported afterwards.

One re-entrancy flag guards Save. `CREATING` (`table.py`) exists because two presses 0.9s apart
minted two records on the deployed service, and `POST /api/record` is not idempotent.

**A record created under a parent the current filter excludes lands nowhere visible.** `refreshRows()`
replaces `DATA.rows` and `draw()` re-applies `matches()`, so the new child is filtered out and the
only feedback is an `announce`. The draft row has this hole today and it has never been felt, because
the draft row is visible while you type it. The form is not. So the announce after a create says
where it went, and says when the answer is "nowhere you can currently see".

## `+ New row` stays

One design proposed the popup as the single create surface on the table, deleting ~440 lines — the
draft row, `chooseKind`, `draftRowHtml`, `createDraft`, `NEW_ROW`, `_new_row_fields`, and `askFor`
folded into the form. It is a real simplification and it was refused: it deletes a gesture that is in
use, riding in on a feature request about right-click menus.

The two also answer different questions, which is the stronger reason. `+ New row` is "another row
like these" — and it **cannot** express a parent at all, because `parent` is not a table column
(`table.py`). The menu's `New child` is "a child of this record", which is the only thing anybody
asked for. Revisit after a cycle of use, as its own change with its own release note.

`askFor` is likewise left alone. It anchors to a **cell rect** rather than a pointer, clamps rather
than flips (`table.py`), and closes with `rove(cell, true)`. Folding it into a pointer-anchored
flip-placer is a behaviour change to the status gate smuggled inside a refactor.

## Delete goes through the server

`GET /api/cascade/{record_id}`, new, answering `{also, deletes, frees, said}` from `cascade_of`, with
the sentences extracted from the record page's `.confirming` panel (`detail.py`) so the two
panels cannot drift.

The route is not a convenience. `cascade_of` iterates `index.records`, while `DATA.rows` is
`index.plan` only — so a cascade computed in the browser would miss any unplanned issue carrying a
hand-written `depends_on`, and every such delete would 409 against the compare-and-swap the DELETE
route holds.

## Two things found on the way, both unrelated to the menu

**`/graph` had no `may_write` gate.** The route never passed one, so a signed-out reader was served
"Edit dependencies" and the whole edit mode. `/table`, immediately above it, has asked since the
`reader-table` branch, and never carried across. Fixed in the first cut.

**`tests/test_table.py` was vacuous on both halves, not one.** It carved the hover-card JS out of the
served page with `body.split("// --- the hover card")[0] + body.split("function hideCard()")[-1]` and
then asserted `"chip kind-" not in table_only` — no kind chip is built for any cell of this table.

Two things were wrong with that. The marker was hunted in `table.py`, but the card's JS is the
**shell's**, so the split found nothing and `[0]` was the whole body: `table_only` was the page twice
over rather than the page minus the card. And the needle never matched anything anyway — the page
writes `class="chip kind-${…}"`, so `chip kind-` is absent in every render mode, card or no card.

So the fix is not a restored marker. `str.split` is replaced by `body.index`, which **raises** when
the marker moves, and the needle is `kind-${`, which is what a chip being built actually looks like.
The marker itself now sits in `shell.py` where the card is. A test that cannot fail is worse than no
test, and this one could not fail twice over.

## The cuts

| cut | what | rough size |
| --- | --- | --- |
| 1 | Groundwork, no behaviour change: `placeFloat` extracted, `may_write` on `/graph`, `CHILD_KINDS` on the ladder, a right button in `pressed_in`, the doubly-vacuous table assertion made
capable of failing | ~150 |
| 2 | The menu: `pop.py`, the host contract, the reader's items, card dismissal, three call sites, shift-through, the Escape arbitration | ~450 |
| 3 | One-field writes: `Status ▸`, `Owner ▸`, `Take out of X`, `Add dependency from here`, `Focus subtree` | ~400 |
| 4 | The form: `_pop_schema`, `New child ▸`, `Edit…`, `Assign parent…` — the answer to the original question | ~600 |
| 5 | `Delete…` and `GET /api/cascade/{id}` | ~200 |

Each cut is shippable on its own. Cut 2 is where the menu-versus-hover judgement gets made in use,
and it is deliberately reader-only so that judgement is made before any of it can write.

## What the tests have to learn

`pressed_in` (`tests/browser.py`) dispatches `button: "left"` and nothing else; a right press
needs the button and the `buttons` mask. That is the only harness change, and it is in cut 1 so the
cuts that follow can assume it.

`tests/test_writes.py` is the sweep that will actually fail, and it is worth naming here because
it is not the one anybody reaches for: it forbids reading a `detail` key off any receiver outside
`refusal()` itself, with a companion mutation test proving it still catches the two that shipped. A
new refusal reader in `pop.py` spelled `said.detail || said.conflict` looks perfectly reasonable and
will not pass.

🤖 Written by an agent on behalf of @jcanton
