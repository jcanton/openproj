"""One record's page, and the form that creates one."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date

from markupsafe import Markup, escape

from ..index import Index, _people_on, cascade_of
from ..model import KINDS as KIND_LADDER
from ..model import NOTE_STATES, RUNG, Config, Record, checklist, sections, size_weeks
from ..vendor import _ace, _yjs
from .controls import _REQUIRED_JS, _combobox_html, _control_html
from .editor import (
    _ACE_SURFACE,
    _COEDIT,
    _SPLIT_HANDLE,
    _ace_wanted,
    _editing_possible,
)
from .env import _compiled, _fragment
from .hill import _HILL_JS, _LADDER_OF, _STATE_HINT, _hill_html
from .markdown import _body_html, _pr_link
from .shell import ROUTES, STATIC, Links, _page
from .styles import _DETAIL_STYLE, _SUGGEST_STYLE
from .tokens import (
    _KIND_MODELS,
    _SIZE_FIELD_NAME,
    EDITABLE,
    FIELD_TEACH,
    KINDS,
    LABELS,
    PREFIX,
    PRIORITY_GLYPH,
    STATUS_TEACH,
    STATUSES,
    TEMPLATES,
    _editable_for,
    _human,
    _read_date,
    _status_class,
)

# The three views of one document, drawn as one control.
#
# **Page chrome, not editor chrome.** `docs/hackmd-observed.md` reads it off the
# pixels of a real note: it sits in the header, immediately after the note's
# identity, as a segmented control of three icons with the active one pressed —
# not as three more buttons in the row that already holds a template picker and a
# status message. Three adjacent segments in one bordered box say "three states of
# one thing"; three buttons in a row of unrelated controls say "three unrelated
# actions", which is the thing this is not.
#
# Icons and not words, for the reason `_ICON_ART` gives and by the same means:
# paths, in the page, in `currentColor`, so they follow the theme, scale, and are
# the same drawing on every machine. Each carries the words in `aria-label`, so
# the control is nameable by everybody — an icon that is only an icon is a
# control a screen reader announces as "button".
#
# One constant, emitted once: the create form and the detail page are the same
# template in two modes, and a second copy of this is a second thing to keep in
# step.
_VIEW_SEGMENTS = (
    '<span id="views" class="views" role="group"'
    ' aria-label="How the document is shown">'
    '<button type="button" id="view-edit" class="seg" aria-pressed="false"'
    ' aria-label="Write" title="Write  Ctrl+Shift+1">'
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M4 20h4L19.2 8.8a2.55 2.55 0 0 0-3.6-3.6L4.4 16.4 4 20Z"/></svg></button>'
    '<button type="button" id="view-both" class="seg" aria-pressed="false"'
    ' aria-label="Write and preview" title="Write and preview  Ctrl+Shift+2">'
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<rect x="3" y="5" width="18" height="14" rx="1.6"/><path d="M12 5v14"/></svg></button>'
    '<button type="button" id="preview" class="seg" aria-pressed="false"'
    ' aria-label="Preview" title="Preview  Ctrl+Shift+3">'
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M2.5 12S6 6.2 12 6.2 21.5 12 21.5 12 18 17.8 12 17.8 2.5 12 2.5 12Z"/>'
    '<circle cx="12" cy="12" r="2.7"/></svg></button>'
    "</span>"
)


def _viewbar(editing: bool) -> Markup:
    """The bar of controls that says how, and in what, this document is shown.

    The whole bar is withheld from a reader the server would refuse a write
    from. The segments are the only door into an editing session, so for a
    non-writer they would open an editor whose every save is a 403 — and the
    read page is already the whole page they came for. `editing` carries
    that fact: `_editing_possible` is `base_commit and may_write`, and
    every template that renders this bar sits behind `{% if editable %}`, so
    within a rendered page it reduces to `may_write`.

    **There is no editor switch beside the segments any more**, and this
    function's second argument went with it. jcanton, 2026-08-24: "remove the
    toggle, have ace as default for everybody ... don't delete the plain editor
    but make it only accessible by `/?editor=plain`". So the bar is the three
    views and nothing else, and which editor somebody is writing in is a fact
    about the address rather than a control on the page.
    """
    if not editing:
        return Markup("")
    return Markup(_VIEW_SEGMENTS)


# `_FIELDS` and `_fields_html` were the flat list of `<label>field</label>` this
# replaced, and nothing has called them since the create page became the detail
# page with nothing in it. They were the last place a raw field name reached a
# reader, and dead code that still renders is code somebody wires back up.


# Three views of one document, on the one page the reader was already on.
#
# Emitted by the detail page and the create form and by nothing else, because it
# reaches for `BODY` and `TITLED` — the two boxes those two pages declare — and
# because the table and the cycle page — the other two that inline `_COMBOBOX` —
# have no document to have a view of. The blocks share one lexical scope, so
# this runs after theirs and the names are simply there.
#
# **Three states, and the landing one is `view`.** `view` is the ordinary page —
# the server-rendered document, the facts column — and it is where every session
# ends. `edit` and `both` are sessions: the same page with the box in the
# document's column. No view is a surface over the page any more — jcanton,
# 2026-08-24: the full-page modes moved controls, dropped the nav and jumped the
# layout, and "page elements should not move or appear/disappear when switching
# views". The fourth, unnamed state this used to carry is gone from every record
# page: exactly one segment is always pressed. The one exception is the create
# form, which has no stored document to land on — see `LANDING` and `GROUND` in
# the script below. Creating is a mode of the record page now, and the exception
# is structural: the creating markup carries no `.doc.read`, so there is nothing
# for a sessionless `view` to show.
_VIEWS = Markup(r"""
<script>
const VIEW_ARTICLE = BODY.closest('article.record');
const VIEW_PANE = document.getElementById('body-preview');
// The segment ids: the third is `preview`, which is the id the in-place Preview
// button had. That button is gone — the preview view is the same thing and more
// of it — and the id stays where the control's job stayed, so that `/new` and
// `/detail` still carry the same shapes and the test that says so still passes
// without being rewritten to agree with the change.
const VIEW_IDS = {edit: 'view-edit', both: 'view-both', view: 'preview'};
const VIEWS = ['edit', 'both', 'view'];
// The server-rendered document, present on every record page and absent on the
// create form — the structural fact the whole machine branches on. A page with
// a landing has a sessionless `view` state to come back to; the create form
// has nothing to read yet, so its way out of the views is the old surface-off
// state (`null`). Structural on purpose: the creating mode of the record page
// keeps `.doc.read` out of its markup so this branch cannot drift.
const LANDING = VIEW_ARTICLE.querySelector('.doc.read');
// Where every exit lands: Escape, the pressed segment, the chord, and the end
// of a session all come here.
const GROUND = LANDING ? 'view' : null;
let VIEW = GROUND;

function showView(mode) {
  VIEW = mode;
  for (const name of VIEWS) {
    VIEW_ARTICLE.classList.toggle('view-' + name, mode === name);
    document.getElementById(VIEW_IDS[name]).setAttribute('aria-pressed', String(mode === name));
  }
  // A view is the classes above and nothing else. This function used to build a
  // full-page surface here — `.full` on the article, `body.fullpage`, an
  // `inert` sweep of `body > nav, body > a.skip`, and `#theme` and `#who`
  // physically moved onto the article's back row. All of it is gone with the
  // surface (jcanton, 2026-08-24: "the nav bar disappears when entering edit or
  // side-by-side modes, should not do that ... ideally page elements should not
  // move or appear/disappear when switching views"). The `inert` sweep and the
  // corner move were both corrections for an opaque fixed article painting over
  // the nav; with the article in the page's own flow the nav is never covered,
  // so there is nothing to inert and nothing to move — and deleting the move
  // leaves the two controls in the nav, once, with their listeners.
  //
  // One mechanism for whether the preview pane is on the page, and it is the
  // `hidden` attribute the pane was drawn with. The landing does not use the
  // pane at all: the server already rendered this document into `.doc.read`
  // through the same `_markdown`, and a pane here would be one `/api/preview`
  // round trip to redraw what is on the screen. The create form has no
  // rendered copy, so its `view` still previews the draft.
  VIEW_PANE.hidden = mode === null || mode === 'edit' || (LANDING && mode === 'view');
  // The machine owns the session on the pages that have both: `edit` and
  // `both` ARE sessions, so entering one opens it, and the landing is
  // sessionless, so landing ends it. `VIEW` is already set above, which is
  // what keeps the `openproj:session` listener below out of the loop. The
  // create form never leaves editing, and two locks hold that: it has no
  // landing, so this branch is off, and its `showEditing` returns behind its
  // own `CREATING` guard.
  if (LANDING && typeof showEditing === 'function') {
    const editing = VIEW_ARTICLE.classList.contains('editing');
    if ((mode === 'edit' || mode === 'both') && !editing) showEditing(true);
    if (mode === 'view' && editing) showEditing(false);
  }
  // The room's bands are measured against a box that has a size, and a view
  // change is exactly when the box changes size. The Preview button this
  // replaces took the box away by setting its `hidden` attribute and dispatched
  // nothing, so `drawSeats` never learnt the box had gone and every band stayed
  // where it used to be — a transient wrong that a three-view page would have
  // made the normal case.
  dispatchEvent(new Event('openproj:editing'));
  // The width handle belongs to the measure, and the split view's edge is not
  // the measure — `place` hides it there and parks it on the edge of `.panes`
  // everywhere else, which is the box the measure has been on since 2026-08-24.
  // `place` is the detail page's; the create form has no grip and no such
  // function.
  if (typeof place === 'function') place();
  // And the other handle, whose whole existence is this one view: the classes
  // are on the article by here, so the stylesheet has already decided whether
  // there is a splitter to have and `applySplit` can simply look.
  applySplit();
  sourcePoints = null;
  refreshPreview(true);
}

// --- where the join between the two panes is --------------------------------
//
// The stylesheet beside `.bodysplit` carries the argument: the constant total is
// structural, so what lives here is one ratio, one clamp and the four ways a
// person moves it.
//
// **This is not the width grip and the two are never on screen together.**
// `#grip` drags `--measure`, the reading measure of the page, and `place()`
// hides it in the split view; `#splitter` divides two panes and the stylesheet
// draws it in the split view and nowhere else. Two handles that both change
// widths on one screen would be two controls nobody can tell apart, and the
// answer to that is that there is only ever one of them there.
//
// No null check on the handle, which is the contract this block already keeps
// with `BODY`, `VIEW_PANE` and `TITLED`: the one template that emits `_VIEWS`
// emits `_SPLIT_HANDLE` inside the same `{% if editable %}` as the box this whole
// script is built around.
const SPLITTER = VIEW_ARTICLE.querySelector('#splitter');
const SPLIT = VIEW_ARTICLE.querySelector('.bodysplit');
// Neither pane may collapse, in either direction: a pane dragged to nothing is a
// pane you cannot drag back. In px because a pointer is in px, and 240 is the
// 15rem at which a pane still shows the shape of a document.
const SPLIT_FLOOR = 240;
// What one arrow press moves — small enough to place the join exactly, large
// enough to cross a 1400px window in under twenty presses.
const SPLIT_STEP = 32;
// Written on the root beside `--measure`, for the reason the comment there gives:
// it is a property of the screen this is being read on, not of the plan. `root`
// is the detail page's name for the same element and exists on one of the four
// pages that reach here, so it cannot be reused — one global lexical scope, and a
// second `const root` is a SyntaxError for the whole document.
const SPLIT_ROOT = document.documentElement;

// How much width the two panes have between them, and 0 when there is no handle
// to divide it with. `getClientRects()` rather than reading the breakpoint back
// with `matchMedia`: the width at which the handle stops existing is written
// once, in the stylesheet, and an invariant written in two languages is an
// invariant guarded in one. A box with no rects is one nothing is drawing, which
// is the question actually being asked — `place()` arrived at the same test.
function splitSpace() {
  if (!SPLITTER.getClientRects().length) return 0;
  return SPLIT.clientWidth - SPLITTER.offsetWidth;
}

// The most lopsided this split may be on a screen this wide, and there is ONE of
// these because it has to bound what gets STORED as well as what may be read back.
//
// **It did not, and that was a defect with a monitor size attached to it.** The
// pixel floor alone allows `(space - 240) / 240`, which passes `SPLIT_RANGE` as
// soon as the panes have more than 2,160px between them — a 3440px ultrawide, or
// a 4K screen, both of which are what a plan gets written on. Measured in Chrome
// with a real mouse at 3440: dragging the preview down to its floor stored
// `11.57`, the next load put that through the `<= SPLIT_RANGE` guard in `EDITOR`,
// read it as out of range and drew 50/50 — and then wrote `1` back over it the
// moment the split view opened again. The reader's choice was not ignored, it was
// destroyed, in silence, and only on the big screens. A write path that stores
// what the read path refuses is this repository's oldest recurring bug and it now
// has one fence rather than two.
//
// So `SPLIT_RANGE` is the outer bound in both directions, the floor is the inner
// one, and the smaller of the two wins. Below 2,584px of window nothing changes:
// the floor is still what a drag runs into.
function splitBound(space) {
  return Math.min(SPLIT_RANGE, (space - SPLIT_FLOOR) / SPLIT_FLOOR);
}

// The ratio the panes are drawn at: the remembered one, clamped to what fits on
// THIS screen. Clamped and not written back — a division chosen on a monitor is
// still that person's choice when the same browser opens a narrow window.
function applySplit() {
  const space = splitSpace();
  // The branch that decides not to act, said out loud. Any view but the split,
  // or a window under the width the stylesheet keeps the handle for, and there
  // is nothing to divide: `--split` is cleared, so the panes are `1fr` and `1fr`
  // again rather than holding a ratio nobody on this screen can change.
  if (space < SPLIT_FLOOR * 2) {
    SPLIT_ROOT.style.removeProperty('--split');
    return;
  }
  const most = splitBound(space);
  const ratio = Math.min(most, Math.max(1 / most, EDITOR.split));
  SPLIT_ROOT.style.setProperty('--split', ratio + 'fr');
  // What the separator says it is at: the share of the two PANES, because the
  // handle's own 1.5rem is not width either of them could have had. Both ends
  // come off `most` rather than off the floor, so what is announced as reachable
  // is what a key or a drag can actually reach — where the floor is the tighter
  // of the two bounds this is the same arithmetic it was, `100 * FLOOR / space`.
  const share = Math.round(100 * ratio / (1 + ratio));
  SPLITTER.setAttribute('aria-valuenow', String(share));
  SPLITTER.setAttribute('aria-valuemin', String(Math.round(100 / (1 + most))));
  SPLITTER.setAttribute('aria-valuemax', String(Math.round(100 * most / (1 + most))));
  SPLITTER.setAttribute('aria-valuetext', share + '% writing, ' + (100 - share) + '% preview');
}

// Where a pointer or a key has just put the join, in px of writing box, and the
// one way it moves — so the clamp, the property and the announcement cannot come
// apart. It does not write the preference down: a drag is one gesture, not one
// `localStorage` write per `pointermove`, and both `#grip` and the table's column
// grips already store at the end of theirs.
function moveSplit(paneWidth) {
  const space = splitSpace();
  if (space < SPLIT_FLOOR * 2) return;      // nothing to divide; see `applySplit`
  const want = Math.min(space - SPLIT_FLOOR, Math.max(SPLIT_FLOOR, paneWidth));
  // Through the same fence `applySplit` draws the panes with, so that what is
  // stored is always something a later load can read back. See `splitBound`.
  const most = splitBound(space);
  EDITOR.split = Math.min(most, Math.max(1 / most, want / (space - want)));
  applySplit();
  // Every pixel the gutter, the seat bands and the two scroll maps draw is a
  // function of the box's width, and this control's whole job is to change it.
  // The width grip carries the same line and the measurement behind it: without
  // it, six of nine line numbers sat up to six whole rows off the lines they
  // name until a window resize happened to put them back.
  dispatchEvent(new Event('openproj:editing'));
}

SPLITTER.onpointerdown = event => {
  // `setPointerCapture`, and the move listener added on down and removed on up,
  // exactly as `#grip` does it: a drag that loses the pointer outside the window
  // is a handle stuck to the cursor.
  SPLITTER.setPointerCapture(event.pointerId);
  SPLITTER.classList.add('dragging');
  // Or the drag selects the prose in whichever pane it crosses. The focus the
  // default would have given is taken by hand instead, so that letting go and
  // then nudging with the arrow keys is one gesture.
  event.preventDefault();
  SPLITTER.focus();
  // Measured from the left edge of the grid rather than from where the pointer
  // started, so the join lands under the pointer instead of a handle's width
  // away from it wherever along the handle it was taken hold of.
  const from = SPLIT.getBoundingClientRect().left;
  const move = e => moveSplit(e.clientX - from - SPLITTER.offsetWidth / 2);
  const stop = () => {
    SPLITTER.classList.remove('dragging');
    rememberEditor({});
    removeEventListener('pointermove', move);
    removeEventListener('pointerup', stop);
    removeEventListener('pointercancel', stop);
  };
  addEventListener('pointermove', move);
  addEventListener('pointerup', stop);
  // **A drag does not always end in a `pointerup`.** The browser can take the
  // gesture away — a touch it decides is a pan, a pointer the platform revokes —
  // and what it sends then is `pointercancel` and no up at all. Measured in
  // Chrome before this line: after a cancel the handle kept `.dragging`, the move
  // listener stayed on the window, and the next `pointermove` with nothing held
  // down moved the join 248px. That is precisely the handle stuck to the cursor
  // that `setPointerCapture` is up there to prevent, arrived at through the one
  // door capture does not close. `touch-action: none` beside the rule stops the
  // browser wanting the gesture in the first place; this is the branch for when
  // it takes it anyway.
  //
  // `#grip` and the table's column grips have the same gap. They are not touched
  // here: this is one control's commit and a sweep of the other two is its own.
  addEventListener('pointercancel', stop);
};
// Both directions and both extremes, because a separator that answers only a
// mouse is the same defect as the thirteen mouse-only toolbar buttons this branch
// shipped and had to fix. `moveSplit` clamps, so Home and End are written as the
// ends of the space and arrive at the floor.
SPLITTER.onkeydown = event => {
  // **A modifier means the key is not this control's**, and until this line the
  // separator ate four that belong to the browser and the platform. Alt+Left is
  // Back on Windows and Linux; measured in Chrome with focus on the handle, it
  // was `preventDefault`ed and moved the join instead of going back a page, and
  // Ctrl+Home and Cmd+Right went the same way. This is the trap the view chord
  // two hundred lines down already carries a paragraph about — a binding that
  // swallows a keystroke somebody meant for something else — and the guard is the
  // one used there.
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const at = SPLITTER.getBoundingClientRect().left - SPLIT.getBoundingClientRect().left;
  const to = {
    ArrowLeft: at - SPLIT_STEP, ArrowRight: at + SPLIT_STEP,
    Home: 0, End: splitSpace(),
  }[event.key];
  if (to === undefined) return;           // every other key is still the page's
  event.preventDefault();
  moveSplit(to);
  rememberEditor({});
};
// The way back to even, which is the one position a drag cannot be trusted to hit
// and which the table's column grips already use this gesture for.
SPLITTER.ondblclick = () => {
  moveSplit(splitSpace() / 2);
  rememberEditor({});
};

// A remembered ratio is a ratio and the floor is pixels: the 70/30 that leaves
// 400px of preview on a monitor leaves 150px on a laptop. So the clamp is redone
// when the window changes, without touching what is remembered.
addEventListener('resize', applySplit);

// --- the preview, live ------------------------------------------------------
//
// Still the server's markdown, and still the same round trip: two renderers
// disagree eventually and the one people would trust is not the one whose output
// gets committed. What is new is that it keeps up — debounced, skipped when
// nothing changed, aborted when it is overtaken, and with the pane's own scroll
// left where the reader put it. A naive `innerHTML` on every keystroke scrolls
// the pane back to the top on every keystroke, which is worse than no live
// preview at all.
const PREVIEW_MS = 300;
let previewTimer = 0;
let previewFlight = null;
// The exact request body the pane is currently showing, which doubles as the
// skip: one string, compared once, rather than two fields compared separately
// and then rebuilt into the same JSON anyway.
let previewShown = null;

function refreshPreview(now) {
  // The timer is cleared before the guard and not after it. A debounce armed
  // while the pane was on the page outlived the pane being taken off it: type in
  // the split view and press Write inside 300ms, and a round trip went out for a
  // pane nobody is looking at.
  clearTimeout(previewTimer);
  if (VIEW_PANE.hidden) return;
  previewTimer = setTimeout(askPreview, now ? 0 : PREVIEW_MS);
}

async function askPreview() {
  if (VIEW_PANE.hidden) return;
  // The title goes with it: the page drops a leading heading that only restates
  // the title, so a preview without one shows a heading the saved page will not.
  // The title in the FORM, not the stored one — this same Save may change it.
  const want = JSON.stringify({body: SURFACE.text(), title: TITLED.value});
  if (want === previewShown) return;
  if (previewFlight) previewFlight.abort();
  previewFlight = new AbortController();
  let html;
  try {
    const response = await fetch('/api/preview', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: want, signal: previewFlight.signal,
    });
    // Both halves of the answer are checked, because neither is guaranteed and
    // the failure of the second is silent. A 400 or a 422 from this server
    // answers JSON with a `detail` and no `html`, and so does a proxy's own
    // error page — and `innerHTML = undefined` writes the six letters of the
    // word `undefined` into the pane, which reads as a document that renders to
    // that.
    if (!response.ok) throw new Error('the server answered ' + response.status);
    html = (await response.json()).html;
    if (typeof html !== 'string') throw new Error('the answer carried no document');
  } catch (error) {
    // An abort is this function overtaking itself and is not news, and it is the
    // one case told apart by name rather than by the comment above it claiming
    // it is. Everything else is a branch that decided not to act, which this
    // application has now shipped three of in silence: it says so once, in the
    // live region, and leaves the pane showing the last thing that rendered —
    // except on the first open, where the last thing that rendered is nothing
    // and an empty pane beside a document full of text reads as a document that
    // renders to nothing. `previewShown` is deliberately not moved, so the next
    // keystroke asks again rather than the pane being stuck on this text for
    // ever.
    if (error.name === 'AbortError') return;
    announce('the preview could not be rendered — ' + error.message);
    if (previewShown === null) {
      VIEW_PANE.textContent = 'The preview could not be rendered. The document is unchanged.';
    }
    return;
  }
  previewShown = want;
  // `innerHTML` and nothing around it. The plan this was built from says a naive
  // replace scrolls the pane to the top on every keystroke and that the offset
  // has to be saved and put back; measured in Chrome, that is not true — a
  // scroller keeps its offset across a wholesale replacement of its contents as
  // long as the new contents are still tall enough to hold it, with content of
  // the same height and of a different one. The save and the restore were
  // written, and then deleted rather than left in: three lines that look like a
  // guarantee and change nothing are worse than the absence of them, because the
  // next person reads them as the reason it works.
  //
  // What does move the pane is text getting SHORTER than the offset, and no
  // amount of saving fixes that — there is nowhere to put it back to.
  VIEW_PANE.innerHTML = html;
  previewPoints = null;
}

// --- the two panes, scrolled together ---------------------------------------
//
// Both sides of the split are a list of (source line, pixel top), so both
// directions are one interpolation read the other way round. The rendered side
// gets its lines from `data-startline`, which the renderer stamps on every
// top-level block from markdown-it's own token map; the source side gets its
// pixels from `lineTops`, which measures rather than assuming that one line is
// one row — in a pane half a window wide most lines wrap, and `scrollTop /
// lineHeight` is only right for a document in which none of them do.
let sourcePoints = null;
let previewPoints = null;

function sourceMap() {
  if (!sourcePoints) sourcePoints = SURFACE.lineCoords().map((top, at) => ({line: at + 1, top}));
  return sourcePoints;
}

function previewMap() {
  if (!previewPoints) {
    // A point at the top, because the first block of a document need not start
    // on line 1 and without it every line above it interpolates off the end.
    previewPoints = [{line: 1, top: 0}];
    // Measured against the SCROLLER, and that is the whole of the accuracy on
    // this side. `offsetTop` is a distance from whatever happens to be
    // positioned, and nothing positions the pane — the offset parent is the
    // article, so every block reported its distance from the top of the ARTICLE
    // while the two synthetic points above and below it, and the `scrollTop`
    // this map is read against, were in the pane's own scroll space. Measured
    // in Chrome at 1400x900 in the full-page era: a constant 283.625px out, the
    // pane's own top inside the article, on a pane 458px tall — the rendered
    // side sat a third of a screen past the heading the source side was
    // showing. Adding `position: relative` to the pane would also have worked
    // and would have left the number silently depending on a positioning rule
    // staying put; this arithmetic asks the question that is actually being
    // asked.
    const zero = VIEW_PANE.getBoundingClientRect().top - VIEW_PANE.scrollTop;
    for (const block of VIEW_PANE.querySelectorAll('[data-startline]')) {
      const line = Number(block.dataset.startline);
      if (line > previewPoints[previewPoints.length - 1].line) {
        previewPoints.push({line, top: block.getBoundingClientRect().top - zero});
      }
    }
    previewPoints.push({
      line: previewPoints[previewPoints.length - 1].line + 1,
      top: VIEW_PANE.scrollHeight,
    });
  }
  return previewPoints;
}

function pixelOfLine(points, line) {
  let at = 0;
  while (at + 1 < points.length && points[at + 1].line <= line) at++;
  const here = points[at];
  const next = points[at + 1];
  if (!next) return here.top;
  const span = next.line - here.line;
  return here.top + (next.top - here.top) * (span ? (line - here.line) / span : 0);
}

function lineOfPixel(points, top) {
  let at = 0;
  while (at + 1 < points.length && points[at + 1].top <= top) at++;
  const here = points[at];
  const next = points[at + 1];
  if (!next) return here.line;
  const span = next.top - here.top;
  return here.line + (next.line - here.line) * (span ? (top - here.top) / span : 0);
}

// One flag each way, because setting the other pane's `scrollTop` fires its
// scroll event and that would set this one's back — a loop that does not
// diverge but does fight the hand on the wheel. Whoever is scrolling drives, and
// the pane being driven does not drive back.
//
// Cleared on a timer and not on a frame, which is the same finding `announce`
// records two hundred lines up: a frame never comes in a tab nobody is looking
// at, so a flag cleared in `requestAnimationFrame` is a flag that stays set for
// as long as the tab is in the background — and a sync that is switched off
// until the page is next reloaded is worse than one that lags. The delay is long
// enough to be after the scroll event this write is about to cause and short
// enough that letting go of one pane and taking hold of the other feels like one
// gesture.
const SYNC_MS = 50;
let editScrolling = false;
let viewScrolling = false;

function syncFromSource() {
  if (VIEW !== 'both' || viewScrolling) return;
  editScrolling = true;
  VIEW_PANE.scrollTop = pixelOfLine(previewMap(), lineOfPixel(sourceMap(), SURFACE.scrolled()));
  setTimeout(() => { editScrolling = false; }, SYNC_MS);
}

function syncFromPreview() {
  if (VIEW !== 'both' || editScrolling) return;
  viewScrolling = true;
  SURFACE.scrollTo(pixelOfLine(sourceMap(), lineOfPixel(previewMap(), VIEW_PANE.scrollTop)));
  setTimeout(() => { viewScrolling = false; }, SYNC_MS);
}

// Through the surface and not through the box: a `<textarea>` scrolls itself and
// fires `scroll`, Ace scrolls an inner element and reports `changeScrollTop` on
// its session, and this listener was the last of the four places that reached
// past the boundary for `el.scrollTop`.
SURFACE.onScroll(syncFromSource);
VIEW_PANE.addEventListener('scroll', syncFromPreview);
SURFACE.onInput(() => { sourcePoints = null; refreshPreview(); });
TITLED.addEventListener('input', () => refreshPreview());
// Both maps are in pixels and every pixel here is a function of the width.
addEventListener('resize', () => { sourcePoints = null; previewPoints = null; });
// Both maps again, on anything that moves the box or changes the text under it
// without an `input` event — a view change, the gutter's column, the width
// handle, somebody else's keystroke. The same event the seat layer and the
// gutter are woken by, for the same reason: every number in both lists is a
// pixel, and all four of those change pixels.
//
// The rendered side matters as much as the source side and was being thrown away
// only on a window resize: going from the split to preview-only doubles the
// pane's width and rewraps every block in it, so the map the sync reads was
// measured in a pane half that wide.
//
// **And no preview is asked for here**, which is the line that is deliberately
// absent. The rendered document is a function of the text and the title and of
// nothing about the box, so a render on a view change is a round trip for a
// document the server has already been sent — measured, one extra per view
// opened, arriving on top of the one `showView` asks for itself.
addEventListener('openproj:editing', () => {
  sourcePoints = null;
  previewPoints = null;
});

// --- how a view is asked for ------------------------------------------------

// Chosen, as against merely shown. The preference records what a person picked,
// and only `chooseView` writes it: `showView` is also what the load branch, the
// Escape hatch and the session listener call, and a preference written there
// would record arrivals nobody chose.
function chooseView(mode) {
  showView(mode);
  // Only a session mode is a preference. `EDITOR.mode` answers one question —
  // which view a session opens in — and leaving a session is not an answer to
  // it: recording the exit would take the split away from somebody who edits,
  // lands back on the page, and edits again.
  if (mode === 'edit' || mode === 'both') rememberEditor({mode});
}

for (const name of VIEWS) {
  // Pressing the pressed segment is how you come back out with a pointer — to
  // the landing where the page has one, to the old surface-off state on the
  // create form, which has no landing to come back to.
  document.getElementById(VIEW_IDS[name]).onclick =
    () => chooseView(VIEW === name ? GROUND : name);
}

addEventListener('keydown', event => {
  // Ctrl+Shift and a digit, and both halves of that are a correction.
  //
  // **Not Cmd**, because the page already claims ⌘S, and ⌘B ⌘I ⌘⇧X ⌘2 ⌘E ⌘⇧E ⌘.
  // ⌘8 ⌘7 ⌘⇧L ⌘K through `attachEditing`. That much was right the first time.
  //
  // **Not Ctrl+Alt either**, which is what it was and what cannot stay. Ctrl+Alt
  // IS AltGr: Chrome on Windows delivers the AltGr key as `ctrlKey` and `altKey`
  // together, and on the Swiss-German layout that half this team types on — the
  // mix `FORMATS` names by hand two hundred lines up — AltGr+E is the euro sign.
  // Verified in Chrome: an AltGr+E keydown opened the split view and
  // `preventDefault`ed the euro, so the chord ate a character people type. A
  // guard on `getModifierState('AltGraph')` would tell the two apart on the
  // engines that set it, and it would leave the binding resting on a modifier
  // state that not every layout, engine and remote-desktop stack reports — for a
  // shortcut, on a key somebody types. Moving off Alt entirely costs nothing and
  // asks nobody to trust that report: this chord carries no Alt, so an AltGr
  // keystroke cannot match it however it is reported. `!event.altKey` is what
  // says so, and it is the whole of the AltGr answer.
  //
  // **Digits, not letters**, because Ctrl+Shift+B is Chrome's bookmarks bar on
  // Windows and Linux and Ctrl+Shift+V is paste-as-plain-text in the box below.
  // Ctrl+Shift+1/2/3 is unclaimed on all three platforms, and one-two-three for
  // write / split / preview is the order the segments are drawn in.
  //
  // Matched on `event.code`, and that is not a preference either: shift-1 on a
  // US layout is `!`, on a Swiss-German layout it is `+`, and a binding read off
  // `key` here is one that could never once fire — the trap the shifted marks
  // fell into when ⌘⇧8 was tried and shift-8 turned out to be `*`.
  if (!event.ctrlKey || !event.shiftKey || event.altKey || event.metaKey) return;
  const mode = {Digit1: 'edit', Digit2: 'both', Digit3: 'view'}[event.code];
  if (!mode) return;
  event.preventDefault();
  chooseView(VIEW === mode ? GROUND : mode);
});

// Escape, arbitrated: see the block in `attachEditing` that dispatches this.
// Answered here only when there is a session view to leave, so on the landing
// — and on the create form's ordinary page — the hatch that gives Tab back
// opens on the first press. Leaving lands on `GROUND`: on a record page that
// is the sessionless landing, so Escape ends the session — and ends it
// without discarding anything, because the text stays in the surface and the
// draft store is the body-undo; only Cancel restores fields.
BODY.addEventListener('openproj:escaped', event => {
  if (VIEW === GROUND) return;
  event.preventDefault();
  showView(GROUND);
});

// `?edit`, `?both`, `?view`, read once at load. Flags and not values: the
// address bar in the observed note reads `?both=`, so `has` is the question and
// `get` — which answers the empty string — would read as false. Off the search
// and not the hash, which this page's router already owns and uses to say which
// record you are looking at.
const VIEW_ASKED = new URLSearchParams(location.search);
const VIEW_LINKED = VIEWS.find(name => VIEW_ASKED.has(name)) || null;

// And then the remembered one, which is the second half of the preference this
// stage carries. Two decisions in it, and both are arguments rather than
// defaults:
//
// **A link beats the preference.** Somebody handed `?view` was handed a way of
// looking at this particular document; a stored mode is only what this browser
// last chose for itself.
//
// **The preference is applied when a session starts, not when the page
// loads.** Sticky-at-load would mean that after once choosing the split,
// every record anybody opened afterwards opened as a full-screen editor over
// a record they had come to read — and reading is the ordinary case.
if (VIEW_LINKED) {
  // `?view` is a sessionless read link: it lands on the page, not in a
  // session. `?edit` and `?both` are views OF a session and `showView` opens
  // the session they are views of — including for the editor switch, which
  // re-adds the flag when it reloads so the session survives the navigation.
  showView(VIEW_LINKED);
} else if (VIEW_ARTICLE.classList.contains('editing')) {
  // A session that existed before this script ran: a restored draft — the one
  // place where landing does not mean sessionless — or the create form, which
  // is always editing. It lands in the mode a session opens in.
  showView(EDITOR.mode);
} else {
  // The ordinary page IS a state now, with its segment pressed and the
  // switcher on it: the segments are the door into a session, and a door
  // drawn only inside the room it opens is not a door.
  showView('view');
}

// A session beginning or ending through any door this script did not open —
// the restored draft's `showEditing(true)` runs before this script, Cancel and
// the room's save run after it. One listener on the one event that means "a
// session began or ended", rather than a copy at every call site: an invariant
// written four times is an invariant guarded three. `VIEW` is set before
// `showView` touches the session, which is what keeps this from looping.
addEventListener('openproj:session', event => {
  if (event.detail && VIEW === GROUND) showView(EDITOR.mode);
  if (!event.detail && VIEW !== GROUND) showView(GROUND);
});
</script>
""")


_DETAIL = """
{#- The index view is one of the views this page routes between, and it had no
    heading of its own — so with no hash in the URL the page was a list of links
    under nothing. Each `<article>` below carries its own `<h1>`, because each of
    them is a document and exactly one of them is ever displayed. -#}
{% if not single %}<div class="toc">
  <h1>Every record in this plan</h1>
  {% for group in groups %}
  <h2 class="tocgroup">{{ group.status|human }}
    <span class="tally">{{ group.records|length }}</span></h2>
  <ul>
    {% for e in group.records %}
    {#- The kind first, because it is the thing every row in this list has and
        the thing a reader is scanning for; a chip trailing the title arrived
        after the answer and moved with the title's length. The owner is gone
        from here: this index exists to get you to a record, and the owner is on
        the record, one click away, next to the four other fields you actually
        came for. -#}
    <li><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span
      ><a href="{{ links.record }}{{ e.id }}">{{ e.title }}</a></li>
    {% endfor %}
  </ul>
  {% endfor %}
</div>{% endif %}
{% for e in records %}
<article {% if not creating %}id="{{ e.id }}" {% endif -%}
  class="record{% if creating %} editing{% endif %}">
  {#- Back to where you came from, and to the records list when nothing knows.
      It pointed at the table once — a list a note or an issue never appears on,
      so for two of the six kinds "back" led somewhere the record just read
      does not exist. Then it pointed at Records always, which is right for a
      reader who arrived from Records and wrong for the table, the graph, the
      timeline and a cycle: four views with a filter, a sort and a scroll
      position, and one link that threw all of it away.

      What is rendered is the destination for a page opened cold — a bookmark, a
      link in chat, a fresh tab — and the shell's script rewrites it when the tab
      it is in remembers a view. `class="origin"` is that script's hook. -#}
  <p class="back"><a class="origin" href="{{ links.records }}">← all records</a></p>
  {% if editable %}
  {#- The switcher is the way in: pressing Write or Write-and-preview opens
      the session it is a view of, so there is no Edit button beside it — two
      adjacent doors into one session are two controls nobody can tell apart.
      Delete is the other thing a writer may do to a record and it leaves the
      moment a session begins. The whole line is a writer's: a reader the
      server would refuse gets no door at all, which makes the read page the
      whole page for them instead of an editor whose every save is a 403. -#}
  {% if may_write %}
  <p class="editbar">{% if not creating %}<button type="button" class="delete">Delete</button>
    {% endif %}{{ viewbar }}</p>
  {% endif %}
  {#- Save, Cancel and the count of what is unsaved, directly under the button
      that started the editing rather than at the far end of the document —
      jcanton, 2026-08-20. The old argument for the foot was that a commit bar
      belongs where the thing being committed ends. What that actually decided
      was whether the three controls which begin, end and abandon one edit were
      in one place, and they were not: Edit was here and the other two were a
      shaping document away.

      Still sticky, so it is still reachable from the bottom of a long record —
      but stuck to the TOP now, which is where it is. Hidden in the markup and
      revealed by `dirty()`, so it does not flash on every load before the script
      decides it had nothing to say.

      Except when creating, where the bar is visible from birth with a static
      sentence: the page IS the session, and a form whose only way to commit it
      appears later is a form with no way to commit it. Creating has no Delete
      and no Cancel — the article never leaves edit mode and there is nothing
      stored to go back to or delete. -#}
  <div class="commitbar" id="commitbar"{% if not creating %} hidden{% endif %}>
    {% if creating %}
    <span id="unsaved">Nothing is written until you press Create</span>
    <button type="button" id="save">Create</button>
    <span id="state" role="status"></span>
    {% else %}
    <span id="unsaved">Nothing to save</span>
    {#- Ask 7's receipt, beside the count of what is unsaved because that is the
        sentence it qualifies: a draft is what is holding the writing that has
        not been committed, and "3 unsaved changes" with nothing beside it reads
        as work that is nowhere. Empty until something has actually been
        written — an autosave that says "saved" before it has saved anything is
        the worst thing in this row. -#}
    <span id="draftsaved" class="hint"></span>
    <button type="button" id="save" hidden>Save</button>
    {#- Cancel stays beside Save and never beside Edit. They are the two ways one
        editing session can end, and putting them in two places is how somebody
        closes a tab believing the other one was the way out. -#}
    <button type="button" id="cancel" hidden>Cancel</button>
    <span id="state" role="status"></span>
    {% endif %}
  </div>
  {% if may_write and not creating %}
  {#- The question, under the button that asks it. Hidden until then: a page that
      is always showing a way to delete the thing you are reading is a page that
      is always slightly threatening you. A record that does not exist yet cannot
      be deleted, and `cascade_of` was never asked about it. -#}
  <div class="confirming" data-also="{{ (e.deletes + e.frees)|join(" ") }}" hidden>
    <p class="asking">Delete <strong>{{ e.title }}</strong>
      (<code>{{ e.id }}</code>)?<br>
      <span class="hint">Commit deletion? Can only be undone with
        <code>git revert</code>.</span></p>
    {#- The reach of it, before the press and not after. A record filed under this
        one has nowhere to be once it is gone, so it goes too; a record that merely
        depends on this one is somebody else's work waiting for it, and deleting
        that would be this gesture reaching across the plan. Two sentences because
        they are two different things happening to two different sets of files. -#}
    {% if e.deletes %}
    <p class="reach">This also deletes
      <strong>{{ e.deletes|length }}</strong> record{{
        "" if e.deletes|length == 1 else "s" }} filed under it:
      <span class="ids">{{ e.deletes|join(", ") }}</span></p>
    {% endif %}
    {% if e.frees %}
    <p class="reach mild">It also stops
      <span class="ids">{{ e.frees|join(", ") }}</span>
      depending on it. {{ "That record keeps" if e.frees|length == 1
        else "Those records keep" }} {{ "its" if e.frees|length == 1 else "their"
        }} file.</p>
    {% endif %}
    <p class="why" role="alert" hidden></p>
    <span class="acts">
      <button type="button" class="really">Delete it</button>
      <button type="button" class="keep">Keep it</button>
    </span>
  </div>
  {% endif %}
  {#- The form opens ABOVE the heading so the title box can live inside it and
      still be one of `FORM`'s own controls — `CONTROLS` is a `querySelectorAll`
      over the form's subtree, and a title outside it is a title no save sends. -#}
  <form id="edit" data-id="{{ e.id }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
  {% endif %}
  {#- The header, BELOW the two bars of controls — jcanton, 2026-08-24: the
      title "should always be below" the view buttons, in every view. It used to
      sit above them as a heading while the box the form held sat below them, so
      starting an edit moved the record's name down the page; the two are one
      slot now and the slot does not travel. What a thing *is* is still read
      first within the header: kind, then name, then the meta line. -#}
  {%- if creating %}
  {#- The kind sits where the stored record's kind chip sits: the two are the
      same document in two modes, and this is the control that decides which
      kind the reader will be looking at afterwards. Options come off `KINDS`,
      never written out — a rung added to the ladder is on this menu the day it
      lands. -#}
  <p class="eyebrow"><label class="kindpick">kind
      <select id="kind">
        {% for k in kinds %}<option value="{{ k }}"
          {% if k == creating %}selected{% endif %}>{{ k|human }}</option>{% endfor %}
      </select>
    </label></p>
  {%- else %}
  <p class="eyebrow"><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span></p>
  {%- endif %}
  {#- One slot for the record's name in both modes: the read span and the title
      box swap inside the heading, so pressing Write changes what the name is
      drawn in and never where it is. The create page is the exception its own
      comment has always argued: a heading whose only content is an empty input
      is a page with no name and a box with no name either, so it keeps the
      words "New record" and takes the box on the line below. -#}
  <h1>{% if creating %}New record{% else %}<span class="read">{{ e.title }}</span>{%
    if editable %}<input name="title" data-type="text" value="{{ e.title }}"
           aria-label="Title" class="field title-field">{% endif %}{% endif %}</h1>
  {#- No status chip. It was here as well as in the facts column forty pixels
      below — the same word, in the same colour, twice, and in edit mode the
      lower one is the select that changes it. A field that can be changed is
      stated where it can be changed: STATUS is the first row of the facts
      column, level with the title, so nothing is further away than it was. -#}
  {% if creating %}
  <input name="title" data-type="text" value="" aria-label="Title"
         class="field title-field" placeholder="Title">
  <p class="meta">the id and the file are the server's to choose</p>
  {% else %}
  <p class="meta"><code>{{ e.id }}</code>
     {% if e.parent %}· in {{ e.parent_link }}{% endif %}</p>
  {% endif %}
  <div class="panes">
    <aside class="facts">
      {#- The id only where there is one of these on the page. This template is
          rendered once per record, and the static export puts every record in
          one document — so the export carried seventeen elements with the same
          id, which is invalid, and which makes `getElementById('facts')` answer
          with the first record's list whatever the hash says. Nothing calls it
          today: the styling is `.panes > .facts dl` and the class beside it, so
          the id is a hook rather than a rule. A hook that answers the wrong
          element is worse than no hook, and `{% if single %}` is what an id
          means. -#}
      <dl{% if single %} id="facts"{% endif %}>
        {#- The label only where the control it names is on the page. In read
            mode there is no control and a `<label for>` would point at nothing;
            in edit mode it is the only thing giving the box a name, because a
            `<dt>`/`<dd>` pair reads as a caption to a person and as two
            unrelated blocks of text to everything else. -#}
        {% for row in e.rows %}
        {% if creating %}
        {#- The `_NEW` row shape, absorbed: every kind's fields are on the page
            and `data-kinds` says whose each one is — this hide/show IS the kind
            switch. No `for` on the row whose control is a radio group: a label
            can name one element, and naming one stop of a hill would tell a
            screen reader that "Status" is the word for `shaping`. -#}
        <dt data-kinds="{{ row.kinds }}">{% if row.for %}<label for="{{ row.for
          }}">{{ row.label }}</label>{% else %}{{ row.label }}{% endif %}{% if row.gates %}
          <span class="req" hidden>required</span>{% endif %}</dt>
        <dd data-kinds="{{ row.kinds }}">{{ row.control }}</dd>
        {% else %}
        <dt class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">{% if
          editable and row.control and row.for %}<label for="{{ row.for
          }}">{{ row.label }}</label>{%
          else %}{{ row.label }}{% endif %}{% if
          editable and row.gates %} <span class="req" hidden>required</span>{% endif %}</dt>
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display }}</span>
          {% if editable and row.control %}{{ row.control }}{% endif %}
          {#- Why this value is what it is, when it is derived from a link: "from
              the work it was pitched into", "from what it became". Outside both
              the `.read` span and the control, so it reads in both modes — the
              two pages this copy comes from showed it in both. The id is what
              the locked control's `aria-describedby` points at, so the sentence
              reaches a screen reader as the control's own description and not
              only as nearby text. -#}
          {% if row.hint %}<span class="hint" id="{{ row.hint_id }}">{{ row.hint }}</span>
          {% endif %}
          {#- And what the FIELD means, which is a different question from the one
              above and reaches a different reader. `.editing-only` because a read
              is roughly nine views in ten since preview became the landing view,
              and teaching copy on all of them is how the sentence above stops
              being read. Emitted only where there is something to say — except on
              status, which emits an empty one on purpose because `attachHill`
              fills it as the ball moves.

              `{{- -}}` on both sides, and it is load-bearing: the span has to be
              genuinely empty for `.record.editing .teach:empty` to hide it, and a
              newline between the tags is a text node. -#}
          {% if editable and row.teach_id %}
          <span class="hint teach editing-only" id="{{ row.teach_id }}"
                {% if row.teach_data %}data-teach="{{ row.teach_data }}"{% endif
                %}>{{- row.teach -}}</span>
          {% endif %}
        </dd>
        {% endif %}
        {% endfor %}
      </dl>
    </aside>
    <div class="main">
      {#- What the form or the server refused a create with: empty markup filled
          by script, news arriving on a page that is already open. The stored
          page's problems are the index's own, rendered by the server. -#}
      {% if creating %}
      <ul id="problems" class="problems" role="status" aria-live="polite" hidden></ul>
      {% elif e.problems %}<ul class="problems">
        {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
      {% if e.hints %}<ul class="hints">
        {% for h in e.hints %}<li>{{ h }}</li>{% endfor %}</ul>{% endif %}
      {#- The tasks this is made of, above the document rather than inside it: a
          pitch is read to find out where it has got to, and that was a checklist
          somebody had to scroll a shaping document to find. Every tick is the
          task's own status, so there is nothing here to keep in step by hand. -#}
      {% if e.progress %}
      <section class="progress read">
        <h2>Progress <span class="tally">{{ e.progress.text }}</span>
          <span class="meter" role="img"
                aria-label="{{ e.progress.percent }} per cent of this bet is done"
            ><span style="width: {{ e.progress.percent }}%"></span></span></h2>
        <ul>
          {% for item in e.progress.tasks %}
          <li class="{{ 'ticked' if item.done else '' }}">
            <span class="box" aria-hidden="true">{{ '☑' if item.done else '☐' }}</span>
            <a href="{{ links.record }}{{ item.id }}">{{ item.title }}</a>
            <span class="chip {{ item.status_class }}">{{ item.status|human }}</span>
            <span class="tally">{{ item.size }} wk{% if item.people %}
              · {{ item.people }}{% endif %}</span>
          </li>
          {% endfor %}
        </ul>
      </section>
      {% endif %}
      {#- The landing document. Absent when creating, and structurally so: the
          view machine's `LANDING` looks for exactly this element, and the
          create form having nothing to land on is what keeps its `view` a
          draft preview instead of a sessionless page. -#}
      {% if not creating %}<div class="doc read">{{ e.body }}</div>{% endif %}
      {% if editable %}
      {#- Who else is in this document, by name. A name is the channel that
          survives every reader; a colour is not, and a caret drawn one line off
          a `<textarea>` through a mirror element is worse than no caret at all.
          Empty when nobody else is here, which is most of the time — and this
          row carries no margin of its own for exactly that reason, so an empty
          room costs no space above the toolbar and somebody arriving pushes it
          down by the one line they are announced on. -#}
      {%- if not creating %}
      <p id="seatbar" class="field bodybar">
        <span id="together" class="together" role="status" aria-live="polite"></span>
      </p>
      {%- endif %}
      {% if creating %}
      {#- The template is offered, never imposed: it fills an untouched box and
          refuses to overwrite one somebody has typed in. `template` and not
          `start from`: the label names the control, and the sentence it was
          part of ended in the option list. -#}
      <p class="field bodybar">
        <label class="tplpick">template
          <select id="template">
            <option value="pitch">the shaping template</option>
            <option value="task">a task</option>
            <option value="project">a project</option>
            <option value="product">a product</option>
            <option value="blank">nothing</option>
          </select>
        </label>
        <span class="hint" id="tplnote" role="status" aria-live="polite"></span>
      </p>
      {% endif %}
      {#- The hint that was here — "paste or drop an image to put it in the
          plan" — is gone, and it is the Image button that replaced it: a
          sentence describing a gesture is what a toolbar puts in a control. It
          was also 214px of a flex line the toolbar had to share, which is what
          wrapped the toolbar onto two rows. -#}
      <p class="field bodybar markbar">
        <span id="marks" class="marks"></span>
        <span class="hint" id="upload" role="status" aria-live="polite"></span>
        {#- Where the gutter says it has switched itself off, and why. A count of
            lines is a fact about the document, so it belongs beside the box and
            not in a banner: a gutter that simply vanishes on a long document is
            the one somebody reports as broken. -#}
        <span class="hint" id="gutter-note" role="status" aria-live="polite"></span>
      </p>
      {#- The two panes of the split view, in one box so the view can hand them a
          column each and so each scrolls on its own. The box, and a layer over it
          for where everybody else is: the layer is a sibling rather than a
          background, because a `<textarea>` cannot hold anything but text — the
          bands are drawn on top, translucent, and take no pointer events, so the
          thing under them is the thing being typed in. -#}
      <div class="bodysplit">
        <div class="bodywrap">
          {% if not creating %}<div id="seats" class="seats" aria-hidden="true"></div>{% endif %}
          <textarea name="body" class="field body-field"
                    {% if creating %}rows="14" placeholder="The shaping document."
                    {% endif %}aria-label="Shaping document">{{ e.raw_body }}</textarea>
        </div>
        {{ splitter }}
        <div id="body-preview" class="field doc" hidden></div>
      </div>
      {#- The strip along the foot of the box. Filled by `attachStatus`, which
          wraps whatever the page put in it — here the draft's interval, because
          this is the one page with a draft and because an interval is a setting
          and this is where the settings are. -#}
      <p class="field bodybar statusbar" id="statusbar">
        {% if not creating %}<button type="button" id="draftevery"></button>{% endif %}
      </p>
      {#- No draft and no 409-with-a-report on a create; a refused create lands
          in `#problems` above. -#}
      {% if not creating %}
      <div id="conflict" role="status" aria-live="polite" hidden></div>
      {% endif %}
      {% endif %}
    </div>
  </div>
  {% if editable %}
  </form>
  {% endif %}
  {{ e.promote }}
</article>
{% endfor %}
<div id="grip" title="drag to set the width"></div>
<script>
// What this page is looking at, for the shell's "somebody else changed this"
// banner. The shell falls back to the last segment of the URL, which is the id
// on /detail/<id> and the word "detail" on every other shape this page takes —
// the static export holds all of them in one file, and a write to any of them
// read as a write to nothing.
window.SHOWING = {{ showing|tojson }};

// The reader decides how wide prose should be. Remembered per browser rather than
// per record: it is a property of the screen it is being read on, not of the plan.
const grip = document.getElementById('grip');
const root = document.documentElement;
const saved = remembered.get('openproj:measure');
if (saved) root.style.setProperty('--measure', saved);

function shown() {
  // The visible one. On the index view every article is hidden, and measuring a
  // hidden element gives zero — which parked the handle against the left edge of
  // the page, a rule down the side of a list it has nothing to do with.
  //
  // `getClientRects()` and not `offsetParent`: a box with no rects is one
  // nothing is drawing, which is the question actually being asked — and it
  // stays the test after surviving the full-page era, when a `position: fixed`
  // article had no offset parent and an `offsetParent` check would have parked
  // the handle at the left edge through a second door.
  return [...document.querySelectorAll('article.record')]
    .find(candidate => candidate.getClientRects().length > 0);
}

// The box the measure is on, and since 2026-08-24 that is `.panes` and not the
// article: the article is the width of the page in every view — which is what
// stops the header moving when the split opens — so a handle on ITS edge would
// park against the window. Written once because `place` and the drag below have
// to agree about which edge is being dragged; two spellings of that is a handle
// that sits on one box and resizes another.
function column(article) { return article.querySelector('.panes'); }

function place() {
  const article = shown();
  // And not in the split view, whose width handle is the splitter. The grip
  // sets `--measure` as the column's own width, and in the split the column is
  // one measure plus one body wide — so a grip on that edge would move it twice
  // the drag and land the measure somewhere nobody chose. Two handles that both
  // change widths on one screen is the confusion `#splitter`'s comment already
  // refuses; one of them is on the page at a time.
  grip.hidden = !article || article.classList.contains('view-both');
  if (!grip.hidden) grip.style.left = column(article).getBoundingClientRect().right + 'px';
}
place();
addEventListener('resize', place);

grip.onpointerdown = event => {
  grip.setPointerCapture(event.pointerId);
  grip.classList.add('dragging');
  const move = e => {
    // The column is pinned to the page's left edge — it was centred until
    // 2026-08-24, when the header took the page's width and left a centred
    // document indented from its own title — so the width IS the distance from
    // that edge to the pointer. One pixel of drag is one pixel of column now,
    // where the centred box moved half a pixel each way and needed the double.
    const article = shown();
    if (!article) return;
    const width = Math.max(
      320, e.clientX - column(article).getBoundingClientRect().left);
    root.style.setProperty('--measure', width + 'px');
    place();
    // The one control whose entire job is to change the width of the box has to
    // tell the two layers drawn over it, because every pixel either of them draws
    // is a function of that width. Measured before this: dragging to 30rem left
    // six of nine line numbers between 20.8 and 122.1px off their lines — up to
    // six whole rows — and the seat bands with them, until a window resize
    // happened to put them back. A `ResizeObserver` also catches this and is
    // installed for the box's own resize handle, but it is delivered on the
    // rendering step, which the headless clock every pixel question here is asked
    // through runs exactly once; a redraw only an observer can cause is a redraw
    // no test in this repository can see.
    dispatchEvent(new Event('openproj:editing'));
  };
  const stop = () => {
    grip.classList.remove('dragging');
    remembered.set('openproj:measure', root.style.getPropertyValue('--measure'));
    removeEventListener('pointermove', move);
    removeEventListener('pointerup', stop);
  };
  addEventListener('pointermove', move);
  addEventListener('pointerup', stop);
};
</script>
{#- The second editor, and 594 KB of it. It is what a writer gets unless the
    address said `?editor=plain` — jcanton, 2026-08-20, "make ace the default, I
    think it's worth it" — and `_ace_wanted` is where that decision is recorded
    as his rather than as a measurement's. Since 2026-08-24 the address is the
    ONLY thing that says so: there is no switch on the bar and no preference
    behind it, so the plain box is `?editor=plain` on the page you are on and
    nothing else. What did NOT move is who pays: `editable` is gated on
    `base_commit` alone, so a signed-out reader already receives the box and the
    toolbar, and putting Ace at that gate would have shipped this to every public
    reader at 4.19x their page for a keymap whose every save is a 403. -#}
{% if ace %}<script>{{ ace }}</script>
{{ acesurface }}{% endif %}
{% if editable %}{{ combobox }}{% endif %}
{% if editable %}<script>{{ required }}</script><script>{{ hill }}</script>{% endif %}
{% if editable %}<script>
// Only what changed travels. Serialising the whole form would send back every
// field as this tab last saw it, overwriting whatever somebody else changed while
// it sat open — which is exactly what scoped compare-and-swap exists to prevent.
const FORM = document.getElementById('edit');
// Creating or editing: one template, one script, two write paths. `null` on a
// stored record's page; the kind being made on `/new`. This is the same flag
// the issue and note pages grew for their create modes — theirs died with
// those templates, and this copy is the only one.
const CREATING = {{ creating|tojson }};
// Create-page furniture: null on a stored record, dereferenced only behind
// `CREATING`.
const KIND = document.getElementById('kind');
const PROBLEMS = document.getElementById('problems');
const ORIGINAL = {};
const CONTROLS = [...FORM.querySelectorAll('[data-type]')];
const BODY = FORM.querySelector('[name=body]');
// The box holding the title, for the preview: the page suppresses the document's
// own leading heading when it repeats the title, and a preview that does not know
// the title cannot suppress it. Found by class: it once had to be, when the
// create page kept this box outside `<form>`, and the class find is the one
// that keeps working wherever the box sits.
const TITLED = document.querySelector('.title-field');
// The one place any of this reads or writes the document. Seven operations,
// every index in UTF-16 code units, one implementation — see the banner in the
// shared block. Nothing below this line touches `.value` or a selection.
const SURFACE = bodySurface(BODY);
attachUploads(SURFACE, document.getElementById('upload'));
attachEditing(SURFACE, document.getElementById('marks'));
attachGutter(SURFACE, document.getElementById('gutter-note'));
attachStatus(SURFACE, document.getElementById('statusbar'));
// The commit this page was rendered at, and what every save is compared against.
// Read through this one box rather than looked up at each write, because a
// restored draft moves it back to the commit that draft was written on top of.
const BASE = FORM.querySelector('[name=base_commit]');
// The draft's key, version 2: a draft is now `{base, text}` rather than text.
// Bumped rather than parsed loosely, so a body that happens to be valid JSON
// cannot be mistaken for the new shape.
const DRAFT = `openproj:draft:2:${FORM.dataset.id}`;
// One sentence, handed from the page that saved to the page that comes back.
// A save in a room reloads, and "saved, and somebody else's change to this file
// was merged in" is news — it means the file holds a paragraph this person has
// not read — announced to a page that is already on its way out. Not scoped to
// the record: it is read and dropped by the first page that loads, which is the
// one that was reloaded.
const SAID = 'openproj:said';

// Whatever the page before the reload was told. Read once and forgotten, so a
// reload of the reload is silent rather than saying "saved" again.
{
  const before = remembered.get(SAID);
  if (before) {
    remembered.forget(SAID);
    announce(before);
  }
}

function read(control) {
  const type = control.dataset.type;
  // `!!`, so a bool is always a bool rather than whatever the DOM happens to
  // answer. A browser answers `checked` with `false` on a box carrying no
  // attribute and this was never wrong in one; the JS harness answers `undefined`,
  // and `JSON.stringify(undefined)` is the VALUE undefined rather than the string
  // "undefined" — so `ORIGINAL.review_waived` was not a JSON document there at
  // all. Harmless while `changed()` only ever compared it, and a thrown
  // `JSON.parse` the moment Cancel started reading `ORIGINAL` back. The contract
  // is now the same in both.
  if (type === 'bool') return !!control.checked;
  const raw = control.value.trim();
  // Deduplicated: picking a name already in the list is a slip, not an intent to
  // have it twice, and a duplicate reviewer reads as two people.
  if (type === 'list')
    return raw ? [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))] : [];
  if (type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    // A form returns strings, and `priority: soon` is valid YAML that breaks the
    // scheduler on the next read. Refuse it here rather than commit it.
    if (Number.isNaN(n)) throw new Error(`${control.name} must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

for (const control of CONTROLS) ORIGINAL[control.name] = JSON.stringify(read(control));
// `let`, because a room can commit this body without this tab pressing anything:
// after that commit the saved text IS the baseline, and a `const` here left the
// bar claiming one unsaved change forever over text that is already in git.
let ORIGINAL_BODY = SURFACE.text();

function changed() {
  const fields = {};
  for (const control of CONTROLS) {
    const now = read(control);
    if (JSON.stringify(now) !== ORIGINAL[control.name]) fields[control.name] = now;
  }
  return fields;
}

// What has been typed and not committed, said out loud in the bar that commits
// it. An editor whose only signal is a button that always looks the same is an
// editor you close with work in it.
const BAR = document.getElementById('commitbar');
const UNSAVED = document.getElementById('unsaved');

function dirty() {
  // The create bar's sentence is static — "Nothing is written until you press
  // Create". A counter here would count fields against defaults nobody typed.
  if (CREATING) return;
  let fields = {};
  // A number typed as a word throws in `read`; that is Save's message to deliver,
  // not a reason for the counter to stop counting the rest.
  try { fields = changed(); } catch (error) { fields = {}; }
  const count = Object.keys(fields).length + (SURFACE.text() === ORIGINAL_BODY ? 0 : 1);
  const editing = document.querySelector('article.record').classList.contains('editing');
  // Gone entirely when there is nothing for it to say. It is a sticky bar, so it
  // was on screen the whole time somebody was READING a record, reporting
  // "Nothing to save" about a form they had not opened — a permanent answer to a
  // question nobody had asked, taking up the foot of every page.
  //
  // Not simply `!editing`: a draft restored from a previous visit is unsaved work
  // sitting in the page before edit mode is entered, and that is exactly when the
  // count needs saying.
  BAR.hidden = !editing && count === 0;
  BAR.classList.toggle('dirty', count > 0);
  UNSAVED.textContent = count
    ? `${count} unsaved change${count === 1 ? '' : 's'}`
    : (editing ? 'Nothing changed yet' : 'Nothing to save');
}
FORM.addEventListener('input', dirty);
FORM.addEventListener('change', dirty);
// Once at load, because nothing else asks until somebody types. Its job here is
// mostly to reveal the bar for a restored draft — unsaved work sitting in the
// page before edit mode has been entered.
dirty();
// The status select decides which fields the server will refuse this without,
// and the checkbox beside it lets one of those rules off.
watchRequired(FORM);
// The same form, and the same status: the hill is the control that sets it.
attachHill(FORM);

// The create mode's two pickers. Everything here exists only on `/new`; a
// stored record has a kind already and a body somebody wrote. Declarations,
// not consts, and indented inside the block on purpose: the pinned suite
// reads them by their `function` spelling, and the collision test only counts
// names declared at column 0.
if (CREATING) {
  // Every kind's fields are on the page and the ones this kind does not have
  // are hidden, rather than each kind being its own round trip — switching
  // kind after typing a title used to mean typing it again. This hide/show is
  // the kind switch the merged page runs on.
  function showKind() {
    for (const element of FORM.querySelectorAll('[data-kinds]'))
      element.hidden = !element.dataset.kinds.split(' ').includes(KIND.value);
  }
  showKind();

  // The body a new record starts from. Switching kind switches template, but
  // only while the box is still one of ours: once somebody has typed, the box
  // is theirs — the template never changes underneath a sentence, and the
  // picker says so rather than appearing to do nothing.
  const TEMPLATES = {{ templates|tojson }};
  const TPL = document.getElementById('template');
  // Named for the element it addresses — the template picker's own message
  // line — and never anything ending in STATE: the page has a real `#state`
  // region beside it, every write to which must go through `announce()`.
  const TPLNOTE = document.getElementById('tplnote');
  function untouched() {
    return Object.values(TEMPLATES).some(text => text.trim() === SURFACE.text().trim());
  }
  function applyTemplate(name) {
    if (!untouched()) {
      TPLNOTE.textContent = 'the body has been edited — clear it to start from a template';
      return false;
    }
    // A whole-document replacement, said in those words and made once. `apply`
    // marks it as the page writing rather than a person typing, and the event
    // tells the layers drawn beside the box, because `apply` deliberately
    // fires no `input` — without it, choosing `blank` left twenty-one line
    // numbers down the side of an empty box.
    SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, TEMPLATES[name] ?? ''));
    dispatchEvent(new Event('openproj:editing'));
    TPLNOTE.textContent = '';
    return true;
  }
  TPL.onchange = () => { applyTemplate(TPL.value); };
  KIND.onchange = () => {
    showKind();
    if (untouched() && TEMPLATES[KIND.value] !== undefined) {
      TPL.value = KIND.value;
      applyTemplate(KIND.value);
    }
  };
  TPL.value = TEMPLATES[KIND.value] !== undefined ? KIND.value : 'blank';
  applyTemplate(TPL.value);
}

// `showEditing` and not `show`: the detail page's hash router declares a `show`
// of its own in another `<script>`, and two top-level functions of one name in
// one page are one function. The two blocks are never emitted together today —
// the index is read-only and the single view has no router — so this was a trap
// rather than a defect, and one condition changing anywhere above makes it one.
// (Written without naming the tag: this block is a Jinja template, and a comment
// that mentions one is a comment the template engine reads.)
function showEditing(editing) {
  // Unreachable when creating — `showView` touches the session only where a
  // landing exists and the create page has none, and neither Cancel nor
  // Delete is on the page to reach it through `flipEditing` — and guarded
  // anyway, because the failure if that ordering ever changed is a null deref
  // that takes the whole script.
  if (CREATING) return;
  // One class on the article. Each fact is a single row whose value swaps for its
  // control, so nothing is shown twice and the page does not jump when you start.
  document.querySelector('article.record').classList.toggle('editing', editing);
  document.getElementById('save').hidden = !editing;
  // Save and Cancel are the two ways one editing session ends, and they
  // arrive together at the top of the record. The way IN is the view switcher
  // on the editbar; the Edit button that used to be here was a second door
  // into the same session, one control's width from the first.
  document.getElementById('cancel').hidden = !editing;
  // Delete leaves while an edit is open. Two destructive-ish answers to "I am
  // done with this record" on one line is one too many, and the one that throws
  // the record away should not be a slip of the hand from the one that keeps it.
  // It comes back when the edit ends, by either door.
  const remove = document.querySelector('.editbar button.delete');
  if (remove) remove.hidden = editing;
  dirty();
  // The room's bands are measured against a box that has a size. The socket
  // opens on load and the roster arrives while the page is still in read mode,
  // where the textarea is `display: none` and every measurement is zero — so the
  // first thing anybody saw on entering edit mode was no bands at all, on a
  // document somebody else was demonstrably in.
  dispatchEvent(new Event('openproj:editing'));
  // And a second event, which is a different fact and not a louder version of
  // the first. `openproj:editing` means "the box moved" and is dispatched by the
  // width grip, the gutter's column and every view change; this means "a session
  // began or ended", which happens twice a page. The view preference hangs off
  // this one, and hanging it off the other would restore the remembered mode
  // every time anybody dragged the width handle.
  dispatchEvent(new CustomEvent('openproj:session', {detail: editing}));
}

// Cancel's handler — and still the one programmatic door: called on a page in
// read mode it opens the session instead (the segments do the same through
// `showView`), which is what the tests and the room's plumbing drive it by.
// A second copy of what ending a session means is how two doors come to
// disagree about the draft.
function flipEditing() {
  // Nothing binds this when creating — no Cancel on the page — but called
  // anyway it would put every field back to its load-time default before
  // `showEditing`'s guard could refuse, so the door is barred here too.
  if (CREATING) return;
  const editing = !document.querySelector('article.record').classList.contains('editing');
  // The fields go back BEFORE the session is ended, and the order is the whole
  // point. `showEditing` dispatches `openproj:session`, and what listens for the
  // end of a session includes the hill, which has to read the status it is going
  // to keep rather than the one that is about to be undone. Ended first, Cancel
  // put `in_progress` back into the field and left the ball sitting on `ready`,
  // with the picture and the value disagreeing on a page nobody was editing.
  let undone = 0;
  if (!editing) {
    // Cancel puts the FIELDS back to what the server rendered. It used to put
    // nothing back: it dropped the saved draft and left every typed value sitting
    // in its control, so the page returned to a read view showing the old value
    // while the commit bar went on reporting "1 unsaved change" about a change
    // nothing on screen was holding — and the count cleared only on a reload,
    // which is also the moment that value was silently lost. jcanton, 2026-08-22.
    try { undone = Object.keys(changed()).length; } catch (error) { undone = 0; }
    for (const control of CONTROLS) {
      const was = JSON.parse(ORIGINAL[control.name]);
      if (control.dataset.type === 'bool') control.checked = !!was;
      else control.value = Array.isArray(was) ? was.join(', ') : (was ?? '');
    }
    // The fields and NOT the document, which the issue page and the note page
    // used to put back. The difference is deliberate and is written down in
    // `test_cancelling_a_restored_draft_keeps_the_commit_it_was_written_against`:
    // the text stays in the box on purpose, so that a page holding work written
    // against an older commit goes on holding it and `base_commit` is never
    // sprung forward underneath it. A field is a discrete choice somebody can
    // choose again in one press; a shaping document is writing, and the three worst
    // rounds this repository has had each destroyed somebody's writing without a
    // word.
    //
    // So the bar may still be up after a cancel — and when it is, it is telling
    // the truth: there is a paragraph in the box that is not in git, and pressing
    // Edit shows it. What it may no longer do is count a field nothing is holding.
    //
    // The stored draft still goes, and the base it arrived with still stays:
    // moving that forward here would be the silent overwrite by another route.
    forgetDraft();
  }
  // Ending the session leaves the surface the session was in — and the line that
  // does it is not here any more. It was here, and in the issue page's toggle,
  // and in the note page's, and the fourth door out of a session had no copy:
  // a Save made in a room ends it with a bare `showEditing(false)`. It is one
  // listener on `openproj:session` in `_VIEWS` now, which this dispatches, so
  // every door is the same door. See the comment there.
  showEditing(editing);
  // Said out loud. Discarding is still discarding, even when what is discarded
  // is a menu choice, and a page that quietly puts a value back is a page you
  // have to re-check to trust.
  if (undone) {
    announce(`Edit cancelled, ${undone} change${undone === 1 ? '' : 's'} discarded`);
  }
}
if (!CREATING) {
  document.getElementById('cancel').onclick = flipEditing;
}

// Deleting a record. Two presses and a named record between them, and every
// element found through the article it belongs to rather than by id — this page
// can hold more than one record, and a destructive control resolved by
// `getElementById` is one that acts on whichever record happens to be first.
for (const article of document.querySelectorAll('article.record')) {
  const open = article.querySelector('.editbar button.delete');
  if (!open) continue;
  const ask = article.querySelector('.confirming');
  const why = ask.querySelector('.why');

  // Shown and hidden rather than a `confirm()`. A native dialog cannot say which
  // record it is about in the words this page uses, cannot show the server's
  // reason when the delete is refused, and is the one thing on a page that stops
  // every other script until somebody clicks it.
  const asking = state => {
    ask.hidden = !state;
    open.hidden = state;
    why.hidden = true;
    if (state) ask.querySelector('button.keep').focus();
  };
  open.onclick = () => asking(true);
  ask.querySelector('button.keep').onclick = () => asking(false);
  // Escape backs out of the question, the way it backs out of everything else
  // here. Bound on the panel and not on the document, so it cannot swallow the
  // key from the editor when nothing is being confirmed.
  ask.onkeydown = event => { if (event.key === 'Escape') asking(false); };

  ask.querySelector('button.really').onclick = async () => {
    const acts = ask.querySelector('.acts');
    acts.hidden = true;
    // The base commit the page was rendered against, the same one every other
    // write here sends: a delete is a compare-and-swap like the rest, and the
    // server refuses it if somebody has edited the record since this page drew
    // it. Read off the form so there is one answer on the page and not two.
    const base = article.querySelector('input[name=base_commit]').value;
    const also = (ask.dataset.also || '').split(' ').filter(Boolean);
    let answer;
    try {
      answer = await fetch('/api/record/' + encodeURIComponent(article.id), {
        method: 'DELETE',
        headers: {'content-type': 'application/json'},
        // The ids the panel showed, sent back so the question that was answered
        // is the question the server acts on. Somebody filing a task under this
        // pitch while the panel sat open is the whole reason: without this the
        // cascade takes a record it never named.
        body: JSON.stringify({base_commit: base, also: also}),
      });
    } catch (error) {
      acts.hidden = false;
      why.hidden = false;
      why.textContent = 'The server could not be reached. Nothing was deleted.';
      return;
    }
    if (answer.ok) {
      // To the landing, because the page you are on is about a record that no
      // longer exists: staying here would show a 404 on the next reload, and
      // reloading it is what the shell does when it hears the commit. The
      // landing and not the table — this page belongs to every record, and a
      // deleted issue's or note's reader sent to the table lands on a plan
      // view that never showed the record they came from. Same retarget as
      // the back link at the top of the page.
      location.href = {{ links.records|tojson }};
      return;
    }
    // Refused, and the reason is the useful part: "pitch-b20000 cannot be
    // deleted while task-c00001, task-c00002 and task-c00003 are filed under it"
    // is the difference between a button that does not work and a plan that says
    // what to do next. `detail` for an HTTPException, `conflict` for a write
    // that lost the swap; the two routes to a refusal spell it differently.
    acts.hidden = false;
    why.hidden = false;
    const said = await answer.json().catch(() => ({}));
    why.textContent = said.detail || said.conflict ||
      ('The server refused: ' + answer.status);
  };
}

async function save() {
  // One button, two verbs: a record that exists is PATCHed with what changed;
  // a record that does not exist yet is POSTed whole. The branch is the entire
  // difference between the two modes' write paths — everything around it,
  // Cmd+S included, is shared.
  if (CREATING) { await createRecord(); return; }
  let fields;
  try {
    fields = changed();
  } catch (error) {
    announce(error.message);
    return;
  }
  // While a room is live the body is not this tab's to send: it is the room's,
  // and Save is one commit made over the socket against the room's base, with
  // the fields from this form. Sending both down this path would be two commits
  // for one press, and the second would be racing the first.
  if (COEDIT.live()) { COEDIT.save(fields); return; }
  const body = SURFACE.text() === ORIGINAL_BODY ? null : SURFACE.text();
  if (!Object.keys(fields).length && body === null) {
    announce('nothing changed');
    return;
  }

  announce('saving…');
  // The shell's banner has to know a write is in the air before it starts: the
  // server announces a commit to the event stream before it answers the request
  // that made it, so the news of your own save can arrive before you know its
  // sha. Without this, saving this page told you this page had just been changed
  // by somebody else.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/record/${encodeURIComponent(FORM.dataset.id)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields, body}),
    });
    const answer = await answerOf(response);
    const box = document.getElementById('conflict');
    if (response.status === 409) {
      // Into its own box, never into the textarea: text pasted into the editing
      // surface is text somebody saves back.
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      announce('not saved');
      return;
    }
    if (!response.ok) { announce(refusal(answer, response.status)); return; }
    committed = answer.commit;
    forgetDraft();
    location.reload();
  } catch (error) {
    // The same missing `catch` as the uploader's, and worse, because this is the
    // path everybody walks. `announce('saving…')` above puts a word in the live
    // region that only the answer takes back out; with the rejection escaping,
    // the page went on saying "saving…" for ever, with Save still enabled and
    // nothing anywhere to say whether the work had landed.
    //
    // And it does not claim to know. A fetch rejects when the answer is lost as
    // readily as when the request never left, so "nothing was sent" would be a
    // guess. Pressing Save again is the whole of the recovery either way: the
    // draft is still in this browser, `BASE.value` still holds the commit this
    // page was rendered at, and if the write did land, the compare-and-swap
    // refuses the second press with the conflict report rather than repeating it.
    announce(`not saved — ${error.message}. Press Save again: if it did land, `
             + 'the next press is refused rather than repeated.');
  } finally {
    // Announced even when refused, or one 409 leaves every event after it held
    // back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}



// The create half of Save, from the page this one absorbed: collect every
// visible field, check the gates the labels are marked from, POST once, land
// on the record that now exists. One drift from the absorbed copy: the title
// box sits inside `<form>` here, so the field loop collects `title` too — the
// explicit `TITLED` line below then overwrites it with the same trimmed value.
async function createRecord() {
  const fields = {kind: KIND.value};
  // `OPENS` and not a word typed here: it is declared once beside `markRequired`
  // in `_REQUIRED_JS`, which this script already depends on for `labelOf`, and
  // it is the model's own opening status. Two hand-written copies of one default
  // is how the form comes to check the gates of a status the server will not
  // give the record it is about to create.
  const status = FORM.querySelector('[name=status]')?.value || OPENS;
  const missing = [];
  for (const control of FORM.querySelectorAll('[data-type]')) {
    // A field this kind does not have is not empty, it is absent — sending it
    // would ask the server to set an attribute the model does not define.
    if (control.closest('[data-kinds]')?.hidden) continue;
    let value;
    try { value = read(control); } catch (error) { announce(error.message); return; }
    const empty = value === null || (Array.isArray(value) && !value.length);
    const waived = control.name === 'reviewers' &&
      FORM.querySelector('[name=review_waived]')?.checked;
    // The same gates the labels are marked from, so what the form refuses and
    // what it warned you about cannot be two different lists.
    const gates = control.dataset.requiredAt;
    if (gates && empty && !waived && gates.split(' ').includes(status))
      missing.push(labelOf(control));
    if (!empty) fields[control.name] = value;
  }
  if (TITLED.value.trim()) fields.title = TITLED.value.trim(); else missing.push('Title');
  if (missing.length) {
    // The words on the page, not the words in the file: `person_weeks` is what
    // git holds, and a refusal that names it sends somebody looking for a
    // field with that label.
    const chosen = FORM.querySelector('[name=status]');
    PROBLEMS.hidden = false;
    // `replaceChildren` with one line of text, not `innerHTML`: every word in
    // this sentence comes off the page, and the page's fields hold whatever
    // the plan holds. There is no markup wanted here at all, so none is built.
    const line = document.createElement('li');
    line.textContent = 'still needed at status '
      + `${chosen?.selectedOptions[0]?.textContent.trim() || status}: `
      + missing.join(', ');
    PROBLEMS.replaceChildren(line);
    return;
  }
  // The shell's banner is told before the request goes and the sha after,
  // because the server announces a commit to the event stream before it
  // answers the request that made it.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/record', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: BASE.value, fields,
        body: SURFACE.text() || '',
      }),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      // The client check is a courtesy; this is the truth, and swallowing it
      // leaves somebody staring at a form that looks fine. Built as text
      // nodes, because `answer.detail` quotes back whatever key was posted.
      PROBLEMS.hidden = false;
      PROBLEMS.replaceChildren(...refusals(answer, response.status).map(text => {
        const item = document.createElement('li');
        item.textContent = text;
        return item;
      }));
      return;
    }
    committed = answer.commit;
    location.href = '/detail/' + answer.id;
  } finally {
    // Announced even when refused, or one rejected form leaves every later
    // event held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

document.getElementById('save').onclick = save;
addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); save(); }
});

// One Save is one commit, so an unsaved draft is the only thing git cannot get
// back. It survives a closed tab and is dropped the moment it is committed.
//
// Stored with the commit it was written on top of, and not as bare text. A
// draft restored into a page rendered an hour later paired hour-old text with
// today's `base_commit`, so `store.write` compared the two things that agreed,
// found nothing to refuse, and committed a body that reverted whoever had saved
// in between — no 409, no conflict report, their paragraph simply gone. The
// base travels with the text, which is what makes the save that follows a
// restore a compare-and-swap against the right commit: a merge where the edits
// do not overlap, and the same 409 and the same report as every other write
// path where they do.
// Ask 7, and the whole of it: a throttle with a ceiling, and a receipt.
//
// It used to be written on every keystroke — a whole document serialised and
// pushed into `localStorage`, synchronously, on the main thread, per character.
// The interval is settable because that is what was asked for; it has a ceiling
// because a settable one otherwise lets somebody set their own floor coarser
// than the thing that backstops it (`DRAFT_SECONDS`, where the offers are, says
// which thing and why).
//
// **Nothing here reaches git on a timer**, and that is the part of ask 7 that
// was answered with a no. A draft lives in this browser. The only writers to the
// repository are Save and — while somebody else is in the document — the room's
// own commit once everybody has been quiet, which is what `#draftevery`'s title
// says out loud rather than leaving somebody to assume one or the other.
//
// Leading edge and trailing edge both, which is what makes it a throttle rather
// than a debounce. The first keystroke of a burst is written at once, so a tab
// closed a second after somebody starts typing still holds their sentence; the
// last one is written when the interval is up. A debounce is the version that
// writes nothing at all while somebody types steadily for a minute, which is
// exactly the person this feature exists for.
const RECEIPT = document.getElementById('draftsaved');
let draftMs = EDITOR.autosave * 1000;
// Two clocks, and they mean different things. `draftWritten` is when a draft
// last LANDED, which is the only thing `sayDraft` may count from — a receipt
// reading "draft saved 4s ago" over a store that refused the write is this
// application claiming somebody's writing is somewhere it is not, so a refusal
// has to put it back to zero. `draftTried` is when the last ATTEMPT was made,
// which is what the throttle is throttling.
//
// One variable for both is the bug: with the store refusing, `draftWritten` was
// zeroed on every refusal and then read as "when the last write happened", so
// `wait` came out at about minus fifty-seven years and every keystroke re-entered
// `remembered.set` — a synchronous `setItem`, a throw and a catch, per character,
// on the main thread, in exactly the browser the throttle was worth adding for.
// The `if (!draftRefused)` guard suppressed the announcement, never the work.
let draftWritten = 0;
let draftTried = 0;
let draftTimer = 0;
let draftTicker = 0;
let draftRefused = false;

function sayDraft() {
  // `#draftsaved` is not in the creating commitbar: no draft, no receipt.
  if (!RECEIPT) return;
  if (!draftWritten) { RECEIPT.textContent = ''; return; }
  const seconds = Math.round((Date.now() - draftWritten) / 1000);
  // "just now" rather than "0s ago", and minutes past ninety seconds: a counter
  // ticking 1s 2s 3s in the corner of the bar is a thing that draws the eye
  // every second and says nothing new.
  RECEIPT.textContent = seconds < 5 ? 'draft saved just now'
    : seconds < 90 ? `draft saved ${seconds}s ago`
    : `draft saved ${Math.round(seconds / 60)}m ago`;
}

function writeDraft() {
  clearTimeout(draftTimer);
  draftTimer = 0;
  // Before the attempt, not after it, and on both branches: a store that refuses
  // still costs a `setItem` and a throw, which is the cost the interval is here
  // to bound.
  draftTried = Date.now();
  if (remembered.set(DRAFT, JSON.stringify({base: BASE.value, text: SURFACE.text()}))) {
    draftRefused = false;
    draftWritten = Date.now();
    sayDraft();
    // The receipt is a relative time, so it goes stale on its own even when
    // nothing happens. One ticker for the page, started when there is something
    // to count from and stopped when there is not.
    if (!draftTicker) draftTicker = setInterval(sayDraft, 1000);
    return;
  }
  // And the branch that decides not to act, saying so — which is the whole
  // reason `remembered.set` now answers. A private window, a blocked cookie, an
  // enterprise policy or a full store all end here, and every one of them is a
  // tab whose unsaved writing is in one box and nowhere else. Said once, because
  // it will keep being true on every keystroke; the label beside Save stays,
  // because that is the one a person looks at before closing the tab.
  draftWritten = 0;
  clearInterval(draftTicker);
  draftTicker = 0;
  RECEIPT.textContent = 'this browser is not keeping drafts';
  if (!draftRefused) {
    announce('This browser will not keep an unsaved draft — a private window, a blocked '
             + 'cookie or a full store. Press Save before closing this tab.');
  }
  draftRefused = true;
}

// The draft is gone — committed, or cancelled — so the receipt is gone with it.
// One function for the three places that forget it, because a receipt left
// saying "draft saved 4s ago" over a draft that no longer exists is the counter
// claiming work is safe somewhere it is not.
function forgetDraft() {
  clearTimeout(draftTimer);
  clearInterval(draftTicker);
  draftTimer = 0;
  draftTicker = 0;
  draftWritten = 0;
  // The attempt clock goes too: the draft this page was holding is gone, so the
  // next keystroke starts a burst of its own and the leading edge of a burst is
  // written at once. Leaving it set would throttle the first character typed
  // after a save against a write that no longer has anything to do with it.
  draftTried = 0;
  remembered.forget(DRAFT);
  sayDraft();
}

// No draft on the create page: nothing stored means nothing to restore over a
// room, and no key with no id to hang one on.
if (!CREATING) SURFACE.onInput(() => {
  if (draftTimer) return;
  const wait = draftTried + draftMs - Date.now();
  if (wait <= 0) writeDraft();
  else draftTimer = setTimeout(writeDraft, wait);
});

// A throttle with nothing to flush it is a throttle that loses the last thing
// somebody typed, which is the one thing this feature exists to keep. `pagehide`
// covers a closed tab, a navigation and a back/forward-cache eviction;
// `visibilitychange` covers the phone and the tab that is frozen and then killed
// without `pagehide` ever firing. Both, because `writeDraft` writing twice costs
// one `setItem` and missing once costs a paragraph.
addEventListener('pagehide', () => { if (draftTimer) writeDraft(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && draftTimer) writeDraft();
});

// The interval is a draft setting, and the button it fills is not on the
// creating page.
if (!CREATING) {
  statusPick(document.getElementById('draftevery'), 'Draft', DRAFT_SECONDS, EDITOR.autosave,
             seconds => {
               draftMs = seconds * 1000;
               rememberEditor({autosave: seconds});
               announce(`An unsaved draft is kept in this browser every ${seconds} seconds. `
                        + 'Nothing is committed on a timer.');
             });
}

// No restore on the create page: with no stored record there is no id, and a
// draft key built from an empty id would be every create page's at once. The
// restore-forces-a-session rule for stored records is untouched by this gate.
if (!CREATING) {
  const draft = remembered.map(DRAFT);
  // A draft from before this — bare text under the old key — records no commit,
  // and there is nothing honest to do with one: pairing it with today's base is
  // the defect above, and inventing a base is worse. Dropped, and said out loud
  // unless a newer draft supersedes it, because work that goes quietly is the
  // other half of this section.
  const older = `openproj:${FORM.dataset.id}`;
  if (remembered.get(older) !== null) {
    remembered.forget(older);
    if (typeof draft.text !== 'string') {
      announce('a draft saved by an older version of this page was discarded');
    }
  }
  if (typeof draft.text === 'string' && draft.text !== SURFACE.text()) {
    // The page is at HEAD and this text is not. Saving it is compared against the
    // commit it was drafted against, so the server can tell a merge from an
    // overwrite — and whoever restores it is told the ground moved rather than
    // finding out from a refusal one keystroke later.
    const moved = draft.base && draft.base !== BASE.value;
    if (draft.base) BASE.value = draft.base;
    announce(moved
      ? 'unsaved draft restored — somebody else has changed this since it was written'
      : 'unsaved draft restored');
    // The whole document, replaced once and said so. `apply` because this is the
    // page restoring, not a person typing: at load there is no history to protect
    // and nothing may be told that somebody just wrote 400 lines.
    SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, draft.text));
    showEditing(true);
  }
}
</script>{% endif %}
{% if editable %}{{ views }}{% endif %}
{% if editable %}<script>{{ yjs }}</script>
<script>{{ coedit }}</script>{% endif %}
{% if not single %}<script>
// One page, hash-routed: a stable shareable link per record without a file each.
// With no hash you get an index; with a hash you get exactly one document. Never
// every document at once — that is a wall of text, not a detail view.
function show() {
  const wanted = location.hash.slice(1);
  let found = false;
  for (const article of document.querySelectorAll('article.record')) {
    const match = article.id === wanted;
    article.style.display = match ? '' : 'none';
    found = found || match;
  }
  document.querySelector('.toc').style.display = found ? 'none' : '';
  if (found) scrollTo(0, 0);
  // The width handle belongs to whichever document is on screen, and to no
  // document when the page is the index.
  place();
}
addEventListener('hashchange', show);
show();
</script>{% endif %}
"""


def _links(ids: list[str], index: Index, links: Links = STATIC) -> Markup:
    """Ids as titles, linked. Every one of the three values in here is free text.

    A title arrives through `PATCH /api/record`, which does not police it, and an
    id that fails its pattern is a reported problem and not a refusal — so both
    reach this line as whatever somebody typed. Built with an f-string, a title
    holding a `<script>` ran on the parent link of every child of that record,
    on the page that then offers the reader a Save button. `Markup(...).format`
    escapes each value as it goes in, which is the only version of this that
    stays correct when a fourth value is added to it.
    """
    return Markup(", ").join(
        Markup('<a href="{}{}">{}</a>').format(
            links.record, i, index.plan[i].title if i in index.plan else i
        )
        for i in ids
    )


def _fact_rows(index: Index, record: Record, links: Links, signed_in: str = "") -> list[dict]:
    """The rows of the facts list, each carrying both how it reads and how it edits.

    One row per fact, not two lists: the edit view is the read view with the values
    swapped for controls, so nothing is ever shown twice and the layout does not
    move when you press Edit.

    Every `display` is a `Markup`, including the ones that are only ever a word.
    The template renders it without `|safe`, so the type is what decides whether
    a value is markup or text: a bare `str` that turned up here would be escaped
    rather than injected. That is the wrong way round from how this started —
    one `|safe` in the template covered eighteen values, of which five were
    somebody's free text and one of those was `status`, which arrived straight
    out of a file and into a class attribute.
    """
    span = index.spans.get(record.id)
    why = index.explanations.get(record.id)
    rows = []
    # One mark for "there is nothing here", everywhere. Spelled-out words —
    # `nothing`, `none`, `no` — sit at the same weight as a real value and have
    # to be read before you know the row is empty; a dash is empty at a glance.
    empty = Markup('<span class="empty">—</span>')
    for field in _editable_for(record, record.id, signed_in):
        name = field["name"]
        if name == "title":
            continue
        control = None
        hint = ""
        hint_id = ""
        # The other tenant of the same slot, and the two are different in kind:
        # `hint` is a fact about THIS record and reads in both modes, `teach` is
        # what the field means and reads only while there is a control to set.
        #
        # Separate variables and separate spans, because one row can carry both.
        # The two SHIPPED dicts happen not to overlap — `_STATE_HINT` holds the
        # two inbox kinds and those are the two ladders `STATUS_TEACH` is not read
        # on — but that is a coincidence of today's data and not a property of
        # this code. A planned kind whose `state()` disagrees with its `status`
        # locks the control AND stands on the `record` ladder, so it wants the
        # lock sentence and the word's meaning at the same time; `Handed` in
        # `test_hill.py` is that record, and it exists because the lock was built
        # against it before any kind derived anything.
        #
        # Which is also why the `describedby` below is joined rather than picked
        # between. It is a token list, and an earlier version of this comment
        # claimed the overlap could not happen — the test that had been sitting
        # there since the lock was written disagreed, correctly.
        teach = FIELD_TEACH.get(name, "")
        teach_id = f"teach-{field['id']}" if teach else ""
        teach_data = ""
        if name == "depends_on":
            display = _links(index.blocked_by[record.id], index, links) or empty
        elif name == "parent":
            # By title and linked, the way blockers already read. An id is what
            # the field stores; it is not what anybody is looking for when they
            # ask what this belongs to.
            display = _links([record.parent], index, links) if record.parent else empty
        elif name in ("pitched_into", "became"):
            # Links, not the bare ids the two old pages' edit boxes held: the
            # question a reader asks of this row is "what did it become", and an
            # id is not an answer anybody can press.
            display = _links(getattr(record, name), index, links) or empty
        elif name == "prs":
            display = Markup(", ").join(_pr_link(ref) for ref in record.prs) or empty
        elif name == "review_waived":
            display = Markup("waived") if record.review_waived else empty
        elif name == "status":
            # The ball on the hill, and not the chip the table wears. The chip says
            # the word; the hill says the shape the word means — `shaping` and
            # `in_progress` are one rung apart on a ladder and opposite sides of a
            # hill, which is the distinction the whole method turns on and the one
            # a list cannot draw. Read-only here and live in `control`, the same
            # row and the same picture, so pressing Edit moves nothing.
            #
            # The word is `state()`, never `status`: an issue whose pitch has
            # shipped would otherwise read "ready" on its own page. Over `records`
            # because a derived state may follow a link to any kind. For every
            # planned kind `Record.state` answers `status`, so only the two
            # inbox kinds ever read differently here.
            ladder = _LADDER_OF.get(record.kind, "record")
            said = record.state(index.records)
            display = _hill_html(said, ladder)
            # The lock, expressed once. A derived state cannot also be set by
            # hand — two ways to say one thing disagree the moment one is used —
            # so the control keeps the derived picture, loses its stops, and the
            # hint says where the word comes from. `state() != status` and not
            # the old pages' `bool(pitched_into)`: a link whose targets are all
            # dangling derives nothing and should stay fixable, and a stored
            # word that equals the derived one is harmless to retype.
            if said != record.status:
                hint = _STATE_HINT.get(record.kind, "")
                hint_id = f"hint-{field['id']}" if hint else ""
            # The one row whose teaching sentence is not fixed at render time:
            # its control is six places to stand, and the sentence belongs to the
            # stop rather than to the field. The span is therefore emitted EMPTY
            # for the three words with nothing to teach — `attachHill` fills the
            # same one as the ball moves, and it needs the element to exist
            # before the first drag. `.record.editing .teach:empty` in
            # `_DETAIL_STYLE` is what keeps an empty one from taking a line.
            #
            # Only on the `record` ladder. An issue never stands at `thinking`
            # and a note's `thinking` means something else, so the map is wrong
            # for both and the two inbox kinds keep this slot for their lock.
            if ladder == "record":
                teach = STATUS_TEACH.get(said, "")
                teach_id = f"teach-{field['id']}"
                teach_data = json.dumps(STATUS_TEACH)
            control = _control_html(
                field,
                ladder=ladder,
                live=said == record.status,
                shown=said,
                # Both, space-separated, which is what `aria-describedby` takes.
                # A hidden target is not announced, so in read mode this resolves
                # to the lock alone without either end knowing about the other.
                describedby=" ".join(one for one in (hint_id, teach_id) if one),
            )
        elif name == "priority":
            # The same chip the table wears, mark and all: this row and that cell
            # are the same fact, and the menu below this row already leads with
            # the mark.
            display = Markup(
                '<span class="chip pri pri-{}">'
                '<span class="chipmark" aria-hidden="true">{}</span>'
                '<span class="chipword">{}</span></span>'
            ).format(
                record.priority,
                PRIORITY_GLYPH.get(str(record.priority), ""),
                _human(record.priority),
            )
        elif name == _SIZE_FIELD_NAME and _tasks_add_up_to(index, record) is not None:
            # The bet, and what its tasks propose to put inside it. Two numbers on
            # one line because they are one question: an appetite read on its own
            # says nothing about whether the work still fits, and the answer was
            # only ever visible by adding the tasks up by hand.
            #
            # Warned about only against a bet somebody actually made. A pitch with
            # no appetite yet is not over it, and `_rollup_problems` says nothing
            # about that case either — a page that shouts where the validator is
            # silent teaches people that one of the two is lying.
            total = _tasks_add_up_to(index, record)
            stated = field["text"]
            over = bool(stated) and total > float(stated)
            display = Markup('{} · <span class="{}">{} in tasks</span>').format(
                stated or "—", "overrun" if over else "quiet", f"{total:g}"
            )
        elif field["type"] == "date":
            # Drawn day-first like every other date on the page; the control
            # under it is an `<input type="date">` and keeps the ISO string,
            # which is what the browser's own picker and the API both read.
            display = escape(_read_date(field["text"])) if field["text"] else empty
        elif field["type"] == "list":
            display = escape(field["text"]) if field["text"] else empty
        else:
            display = escape(field["text"]) if field["text"] not in ("", None) else empty
        rows.append(
            {
                "label": LABELS.get(name, name),
                # What the `<dt>`'s label points at. The derived rows below have
                # no control, so they get no label — a `for` naming nothing is a
                # label the reader is told about and cannot reach.
                #
                # Status points at nothing on purpose. Its control is a group of
                # radios, and a `<label for>` can only name one element: naming one
                # stop of five would tell a screen reader that "Status" is the word
                # for `shaping`. The group carries its own `aria-label` instead, and
                # the `<dt>` falls back to plain text.
                "for": "" if name == "status" else field["id"],
                "display": display,
                "control": (
                    control
                    if control is not None
                    else _control_html(field, describedby=teach_id)
                ),
                "gates": field["gates"],
                "derived": False,
                # Only a locked status row carries these; the other appends in
                # this function omit them, and Jinja reads a missing key as
                # falsy, which is the correct answer for "no hint".
                "hint": hint,
                "hint_id": hint_id,
                # And the teaching sentence beside it. `teach_id` is what decides
                # whether a span is emitted at all, so a field with nothing to
                # say grows no element; status is the exception and says why
                # above. `teach_data` is only ever on the status row.
                "teach": teach,
                "teach_id": teach_id,
                "teach_data": teach_data,
                # "Review waived: no" is a line that says nothing. The row still
                # exists while editing, because turning the waiver on is the whole
                # point of having it; it just does not clutter the read view.
                "editing_only": name == "review_waived" and not record.review_waived,
            }
        )
    # The server's two creation stamps, shown and never offered. `opened_on` and
    # `written_on` are set by `POST /api/record` when the record is made; a box
    # for one would invite a hand-typed lie about the file's own history. Guarded
    # on the model rather than the rung, so only the kinds that carry them ever
    # grow the row.
    for stamped in ("opened_on", "written_on"):
        if stamped in type(record).model_fields:
            written = getattr(record, stamped)
            rows.append(
                {
                    "label": LABELS[stamped],
                    "for": "",
                    "display": escape(_read_date(written.isoformat())) if written else empty,
                    "control": "",
                    "gates": (),
                    "derived": True,
                    "editing_only": False,
                }
            )
    # The one derived line on the page that is a decision and not a fact. It wore
    # the same muted italic as every other computed value, so the sentence that
    # says this bet does not fit read exactly like the sentence saying when it
    # starts. It keeps the italic — it is still computed, and pretending otherwise
    # would invite somebody to edit it — and gains the warning colour on top.
    overrun = (
        Markup(
            ' · <span class="overrun"><span class="sev-mark sev-mark-warn"'
            ' aria-hidden="true">▲</span> overruns cycle {} by {} weeks</span>'
        ).format(record.cycle, f"{span.overruns_cycle_weeks:.1f}")
        if span and span.overruns_cycle_weeks
        else Markup("")
    )
    # Only for kinds the scheduler dates. On an issue or a product the em-dash
    # would mean "cannot exist" while everywhere else on this page it means
    # "not set yet" — empty must not look like broken, and this dash was both.
    if RUNG[record.kind].schedules:
        rows.append(
            {
                "label": "Scheduled",
                "for": "",
                "display": (
                    Markup("{} → {}{}").format(span.start, span.end, overrun)
                    if span
                    else empty
                ),
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    if why:
        rows.append(
            {
                "label": "Why then",
                "for": "",
                # An explanation names the person who is busy and the record that
                # finishes first — a login and an id, both free text, both
                # concatenated into the sentence by the scheduler. The one row on
                # this page that reads as prose is still two stored values.
                "display": escape(why.text),
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    # For kinds that may wait on things — and for any record something actually
    # waits on. The disjunct is load-bearing: a hand-written `depends_on` can
    # name an issue, and on that issue's page a populated Blocks row is true
    # and useful (the delete cascade even edits it). What goes for the kinds
    # that cannot depend is only the permanent em-dash.
    if RUNG[record.kind].depends or index.blocks[record.id]:
        rows.append(
            {
                "label": "Blocks",
                "for": "",
                "display": _links(index.blocks[record.id], index, links) or empty,
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    # Derived, never written: from the tasks under it where there are any, and
    # from the body's own checklist where there are none. The full list is a panel
    # of its own beside the document (`_progress_view`); this line is the number,
    # in the column of facts where every other number about this record is.
    counted = index.progress.get(record.id)
    if counted is not None:
        rows.append(
            {
                "label": "Progress",
                "for": "",
                "display": Markup(
                    '{} <span class="meter" role="img" aria-label="{} of {} {} done">'
                    '<span style="width: {}%"></span></span>'
                ).format(
                    counted.text,
                    f"{counted.done:g}",
                    f"{counted.total:g}",
                    counted.unit,
                    round(100 * counted.fraction),
                ),
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    later = sections(record.body).get(_FOR_LATER_HEADING, "")
    if later:
        # Deferred scope is the only record the plan keeps of a bet being trimmed
        # to fit its appetite, and it was invisible on every page. Named here and
        # left where it was written — repeating the text beside the body it is
        # already in would be two copies of one list.
        items = sum(1 for line in later.splitlines() if line.strip().startswith(("-", "*", "+")))
        rows.append(
            {
                "label": "For later",
                "for": "",
                "display": escape(f"{items} item{'s' if items != 1 else ''} kept for later")
                if items
                else escape("noted at the end of the body"),
                "control": "",
                "gates": (),
                "derived": True,
                "editing_only": False,
            }
        )
    return rows


def _tasks_add_up_to(index: Index, record: Record) -> float | None:
    """What the tasks under this one propose to spend, or None if it has none.

    The same number `_rollup_problems` compares against the appetite, read from
    the same place, so the sentence on the page and the sentence in `check`
    cannot disagree about the arithmetic.
    """
    counted = index.progress.get(record.id)
    return counted.total if counted is not None and counted.unit == "weeks" else None


def _progress_view(index: Index, record: Record) -> dict | None:
    """The tasks a pitch is made of, and how much of it they have finished.

    Only where there are tasks. A leaf's checklist is already in its body, drawn
    where its author put it, and lifting it into a panel above would print the
    same list on the page twice — the fact row carries its count instead.

    Every line is derived from the task it names: the tick is that task's
    `status`, so closing one from the table moves this the next time the index is
    built, and there is no checkbox here for the two to disagree about.
    """
    counted = index.progress.get(record.id)
    if counted is None or not counted.of:
        return None
    config = Config(default_task_effort=index.default_task_effort)
    items = []
    for child_id in counted.of:
        child = index.plan[child_id]
        size, defaulted = size_weeks(child, config)
        items.append(
            {
                "id": child_id,
                "title": child.title,
                "done": child.status == "done",
                "status": child.status,
                "status_class": _status_class(child.status),
                "size": f"{size:g}" + ("*" if defaulted else ""),
                "people": ", ".join(_people_on(child)),
            }
        )
    return {
        "text": counted.text,
        "percent": round(100 * counted.fraction),
        # `tasks` and not `items`: a Jinja lookup finds `dict.items` first, so
        # `progress.items` was the built-in method and the template raised
        # `'builtin_function_or_method' object is not iterable` on every page
        # that draws a record.
        "tasks": items,
    }


_FOR_LATER_HEADING = "for later"
# The two sections the team's own pitch template asks for and the corpus most
# often leaves empty. Both spellings of each, because both are in use.
_WANTED_SECTIONS = {
    "Rabbit holes": ("rabbit holes", "rabbit hole"),
    "No-gos": ("no-gos", "no-go", "no gos", "no go"),
}


def _shaping_hints(record: Record, has_tasks: bool = False) -> list[str]:
    """Sections the pitch template asks for that this body does not have.

    A printed note on one page, deliberately not a `Problem`: it never reaches
    `openproj check`, never fails CI and never blocks a save. The body is prose,
    and a validator with an opinion about prose is a validator people route
    around. This is here to be read by the person already editing the pitch.
    """
    # Only while it is a live bet. An idea nobody has bet on owes nothing yet, and
    # nagging finished work about a section it will never gain is how a note stops
    # being read at all.
    if record.kind != "pitch" or record.status not in ("ready", "in_progress"):
        return []
    written = sections(record.body)
    notes = [
        f"No {label} section. The pitch template asks for one — it is what keeps "
        f"the appetite honest."
        for label, spellings in _WANTED_SECTIONS.items()
        if not any(written.get(spelling) for spelling in spellings)
    ]
    # Said rather than silently resolved. A pitch with tasks is measured by them,
    # so a checklist in its body counts for nothing — and a list somebody is
    # ticking that moves no number on the page is worse than no list at all.
    if has_tasks and checklist(record.body)[1]:
        notes.append(
            "This pitch keeps a checklist in its body and has tasks under it. The "
            "tasks are what its progress is counted from; the checklist is not."
        )
    return notes


def _detail_rows(index: Index, links: Links = STATIC, only: str | None = None) -> list[dict]:
    """One entry per record: what the page's own furniture needs, and nothing else.

    Every fact this page prints comes from `_fact_rows`, which builds each line
    with its value AND its control so the read view and the edit view cannot show
    different things. This carried a second, read-only copy of thirteen of those
    facts — a size, a span, an overrun, a why, blockers, blocks, PRs, tags — that
    reached no template and no test after `_fact_rows` superseded them. A field
    formatted in two places is a field that will be formatted two ways.
    """
    # Over `records`, not `plan`: the record page is the one page every
    # kind gets (spec §2). Until an unplanned rung exists the two maps are
    # equal, so nothing changes at this commit — the line is here so the flip
    # commit ships pages, not KeyErrors.
    #
    # `only` is applied HERE and not by the caller, and the difference is the
    # cost of the page. Each row carries `_body_html`, which is a full
    # `markdown_it` render; building every record's and keeping one made
    # `/detail/<id>` cost 55 ms plus 0.32 ms per record IN THE PLAN rather than
    # per record on the page. Measured under twenty readers on a 561-record
    # corpus, 369 of those renders were 92.6 of the server's 113.4 CPU-seconds —
    # about 63% of the machine spent on markdown nobody would ever see.
    #
    # `None` still builds all of them, and that is not an oversight: the static
    # export puts every record into one file, which is what makes a plan
    # readable with no server. The two callers want different things and each
    # now asks for what it wants.
    #
    # A missing `only` yields an empty list, exactly as the caller's filter did.
    # The route 404s before it gets here, so only a non-route caller sees it.
    chosen = (
        sorted(index.records.items())
        if only is None
        else [(only, index.records[only])] if only in index.records else []
    )
    return [
        {
            "id": record_id,
            "title": record.title,
            "kind": record.kind,
            # `state()`, never the stored word: this key's one reader is
            # `_by_status`, whose ladder (`_TOC_LADDER`) is built from
            # `NOTE_STATES` precisely so `promoted` gets a heading — and fed
            # the stored status it filed every promoted note under "Thinking"
            # and left that rung unreachable. Statuses are what may be
            # written; what a page draws and sorts by is the state, the same
            # rule the hill in `_fact_rows` already follows.
            "status": record.state(index.records),
            # `parent` decides whether the meta line says "in" at all; the link is
            # what it says. Both, because an id that is not in this plan still
            # names a parent and `_links` renders it as itself.
            "parent": record.parent,
            "parent_link": _links([record.parent], index, links) if record.parent else "",
            "problems": [p.message for p in index.problems if p.record_id == record_id],
            # Not problems: notes about the shaping document, printed here and
            # nowhere else. See `_shaping_hints`.
            "hints": _shaping_hints(record, bool(index.children.get(record_id))),
            # The tasks this pitch is made of, ticked from their own statuses.
            "progress": _progress_view(index, record),
            "body": _body_html(record, links),
        }
        for record_id, record in chosen
    ]


def _new_rows() -> list[dict]:
    """One row per field any kind has, each saying which kinds have it.

    The union rather than one kind's worth, because the page carries every
    kind's fields and hides what does not apply. Rendering only the chosen kind
    meant switching kind
    was a fresh page, and a title typed before switching was gone.

    Emitted in `EDITABLE` order, not in the order the union discovered them.
    Building kind by kind put each field where the FIRST kind to own it landed
    it — the first rung is `product`, which reads only `tags`, so the create
    form opened with Tags above Status while the record page opened with
    Status: two orders for one form.
    """
    rows: dict[str, dict] = {}
    for kind in KINDS:
        blank = _KIND_MODELS[kind](
            id=f"{PREFIX[kind]}-000000",
            kind=kind,
            title="",
            # Today, because a date field that starts empty is a date field
            # somebody leaves empty. This is a blank; nothing is overwritten.
            assigned_on=date.today(),
        )
        # One form on the page, so one prefix. The detail page's is the record's
        # id, because that page can hold sixteen of them at once.
        for field in _editable_for(blank, "new"):
            if field["name"] == "title":
                continue          # the title is the heading, not a row
            if field["name"] == "status" and not RUNG[kind].planned:
                # The one status control on this form is the plan ladder, and
                # `shaping` on an issue is a word the server refuses — the form
                # and the validator disagreeing in the most annoying possible
                # order. `thinking` now sits on that ladder too and is refused on
                # an issue for its own reason (see `ISSUE_STATUS`), so this stays
                # a per-rung question and not a per-word one. A fresh inbox
                # record's opening status is the server's stamp (`web.opens_at`,
                # which is the model's own default), and the record page's own
                # per-kind hill is one save away.
                continue
            row = rows.setdefault(
                field["name"],
                {"label": LABELS.get(field["name"], field["name"]),
                 # Empty for status, for the reason the `<dt>` above gives: its
                 # control is a group, and a label names one element.
                 "for": "" if field["name"] == "status" else field["id"],
                 "control": _control_html(field), "gates": field["gates"], "kinds": []},
            )
            row["kinds"].append(kind)
    # `EDITABLE` decides the order, so this form and the facts column cannot
    # disagree; the loops above only decide which rows exist.
    return [
        {**rows[name], "kinds": " ".join(rows[name]["kinds"])}
        for name in EDITABLE
        if name in rows
    ]


# What a promotion offers, per inbox, and the word for each.
#
# A note gets all three because a note is genuinely unshaped: nobody knows yet
# whether the thing being thought about is a milestone, a bet or half a day's
# work, and asking the person who is still confused to decide is the whole
# service this button provides.
#
# An issue gets two. It got one, and the argument for that was that promoting
# straight to a task would "mint a chore nobody pitched" — which is true of a
# task under a pitch, because that task is a piece of somebody else's bet. A
# parentless task is not that: `is_bettable` says one is bet in its own right,
# `PARENT_KINDS` lets one hang straight off a project, and the betting table
# draws it beside the pitches. So the rule was refusing the one shape that
# already exists for exactly this case.
#
# What the old rule cost was paid on the way out rather than here: a broken
# symlink and a one-line fix had to go through Shaping, Appetite, Rabbit holes
# and No-gos to leave this tool, or it left round the side of it. An inbox whose
# only exit is bigger than most of what is in it is an inbox nobody empties,
# which is the defect `/api/promote` exists to fix in the first place.
#
# A project is still not on offer here, and that absence is the load-bearing one:
# a project is a container for bets, and "we found something broken" is not a
# milestone. A note gets it because a note can be an idea about the shape of the
# year; an issue never is.
PROMOTABLE = {"note": ("pitch", "task", "project"), "issue": ("pitch", "task")}
_ARTICLE = {"pitch": "a pitch", "task": "a task", "project": "a project"}

# The sentence above the Promote button, per inbox. Two entries because the two
# records make two different promises about what happens to the source: an
# issue stays OPEN until the work lands (its state derives from the link), a
# note simply stays and points. Same first sentence on purpose — the control
# keeps the same words through the flow.
_PROMOTE_HINTS = {
    "issue": "The new record starts in Shaping, carrying this issue’s title, its "
             "tags and its text, and saying in its own document that it came from "
             "here. Nothing else is carried: an issue has no owner and no size to "
             "give it. The issue stays open until what it became is done.",
    "note": "The new record starts in Shaping, carrying this note’s title, its "
            "tags and its text, and saying in its own document that it came from "
            "here. Nothing else is carried: a note has no owner and no size to "
            "give it. This note stays, and points at what it became.",
}


def _promote_html(
    source_id: str, kinds: Sequence[str], hint: str, base_commit: str,
    links: Links = ROUTES,
) -> Markup:
    """The promotion control, for either inbox.

    One fragment because the two differ in exactly one thing — the sentence above
    the button — and in nothing else. Written twice, the second copy is where the
    base commit stops being sent.

    The word on the button was a parameter as well, and the issue's read "Shape it
    into a pitch". That was the better copy while there was one destination: a
    control that names what will happen beats a control naming the mechanism. It
    stops being available with two, because "Shape it into a pitch or a task" is a
    button arguing with the picker next to it, and picking the destination is now
    the picker's job for either kind. So both say Promote — the word the label above
    the picker already uses, kept the same through the flow, because five pages
    inventing their own word for one act is how `in_progress` came to be spelled
    three ways on one screen.

    `only` survives a `kinds` of length one, which no inbox has today. It is kept
    because the alternative it guards against is drawn rather than argued: a
    `<select>` holding a single option is a control that cannot be used and looks
    exactly like one that can.
    """
    return _fragment(
        _PROMOTE,
        source=source_id,
        kinds=[(kind, _ARTICLE[kind]) for kind in kinds],
        only=kinds[0],
        hint=hint,
        base_commit=base_commit,
        record=links.record,
    )


# Every word a record's `state()` can answer, in ladder order, kind by kind.
# Derived from the rungs rather than written out: a seventh kind's vocabulary
# joins this list on the commit that adds the rung, instead of tumbling into
# the alphabetical tail below. The note rung contributes `NOTE_STATES` and not
# `rung.statuses`, because `promoted` is derived from `became` and never stored
# — `model.py` says so beside `NOTE_STATES` itself: statuses are what may be
# written, states are what a page may draw and sort by. The issue rung adds no
# new words; `ISSUE_STATUS` is a subset of the plan ladder, and the dedup keeps
# the plan's order for it.
_TOC_LADDER = tuple(dict.fromkeys(
    word
    for rung in KIND_LADDER
    for word in (NOTE_STATES if rung.name == "note" else rung.statuses)
))


def _by_status(rows: list[dict]) -> list[dict]:
    """The index, in the order work moves through: shaping first, dropped last.

    A status nobody uses is left out rather than shown empty, and a status the
    validator does not know still gets a heading — the index is a way in, and a
    record missing from it because its status is misspelt is invisible.
    """
    known = list(_TOC_LADDER)
    seen = sorted({row["status"] for row in rows}, key=lambda s: (s not in known, s))
    order = [s for s in known if s in seen] + [s for s in seen if s not in known]
    return [
        {"status": status, "records": [r for r in rows if r["status"] == status]}
        for status in order
    ]


def render_detail(
    index: Index,
    links: Links = STATIC,
    only: str | None = None,
    base_commit: str | None = None,
    may_write: bool = False,
    editor: str = "",
    creating: str | None = None,
    signed_in: str = "",
) -> str:
    """Every record, exactly one — or one that does not exist yet.

    The server serves one per route; the static build serves them all in a page
    that hides everything but the hash. Same markup, so the two cannot drift.

    `creating` is the kind being made. The create page was a forked template
    once (`_NEW`), and a fork is what the issue and note pages proved a fork
    does; it is now this template with a blank record, the union of every
    kind's fields, and `data-kinds` deciding what shows.
    """
    if creating is not None:
        # A blank record through the same row machinery. No id (the server
        # mints it), no cascade (nothing to delete), no problems (nothing has
        # been refused yet).
        rows: list[dict] = [{
            "id": "",
            "title": "",
            "kind": creating,
            "parent": None,
            "parent_link": "",
            "problems": [],
            "hints": [],
            "progress": None,
            "body": Markup(""),
            "rows": _new_rows(),
            "raw_body": "",
            "deletes": [],
            "frees": [],
            # Explicit rather than riding Jinja's default Undefined
            # stringifying to "": the "never on the creating article" rule
            # below must survive a move to StrictUndefined, not hold by
            # accident.
            "promote": Markup(""),
        }]
    else:
        rows = _detail_rows(index, links, only)
        # Every record gets its facts, not only the one being served on its own
        # route: the static export renders them all, and it is the same page.
        # `records`, not `plan`: this page is every record's page — spec §2
        # puts it on the total side of the inversion, and the day an unplanned
        # rung lands its records get their pages through this line unchanged.
        for row in rows:
            record = index.records[row["id"]]
            row["rows"] = _fact_rows(index, record, links, signed_in)
            row["raw_body"] = record.body
            # What deleting it would take with it, drawn into the confirmation
            # before anybody presses anything. From `cascade_of`, which is what
            # the route itself asks — a panel that listed the consequences from
            # a second derivation of them would be a panel that can be wrong
            # about the commit it is authorising.
            row["deletes"], row["frees"] = cascade_of(index, row["id"])
            # The promote panel, where the record is. It lived on the two
            # deleted inbox pages; a kind that is not promotable gets an empty
            # Markup, and the static export gets one for everything because
            # there is no server to post to. Never on the creating article:
            # there is nothing to promote yet, and a control whose only answer
            # is a refusal is a dead end a person can only find by pressing it.
            # And never for a reader the server would refuse — `may_write`,
            # the question the Delete control and the view switcher already
            # ask (see the render kwargs below): reads here are public, and a
            # Promote whose one answer for this person is a 401 is a dead end
            # of the same shape.
            row["promote"] = (
                _promote_html(
                    row["id"], PROMOTABLE[record.kind], _PROMOTE_HINTS[record.kind],
                    base_commit or "", links,
                )
                if base_commit is not None and may_write and record.kind in PROMOTABLE
                else Markup("")
            )
    body = _compiled(_DETAIL).render(
        records=rows,
        groups=[] if creating else _by_status(rows),
        # Every record this page holds, not the one in the URL: the static export
        # is all of them in one file, and the shell's banner has no other way to
        # tell "somebody changed what you are reading" from "somebody changed
        # something".
        showing=[] if creating else [row["id"] for row in rows],
        single=creating is not None or only is not None,
        creating=creating,
        kinds=KINDS,
        templates=TEMPLATES if creating else {},
        links=links,
        editable=base_commit is not None,
        # The Delete control asks for both, and `editable` alone is not enough.
        # `editable` means "there is a server to talk to"; this asks "would that
        # server take a write from you", which is the question `may_write`
        # answers — see the note on `yjs` below, and `may_write` in `web.py`.
        # A reader offered a Delete button is offered a 401 dressed as a control.
        may_write=may_write,
        base_commit=base_commit or "",
        statuses=STATUSES,
        combobox=_combobox_html(index),
        required=_REQUIRED_JS,
        hill=_HILL_JS,
        viewbar=_viewbar(_editing_possible(base_commit, may_write)),
        # The machine drives the segments; a non-writer has neither, or the
        # script would throw on `getElementById` of a control `_viewbar`
        # deliberately withheld.
        views=_VIEWS if may_write else Markup(""),
        splitter=_SPLIT_HANDLE,
        # The same gate the two lines below carry, and one more: the address had
        # to ask. See `_ace`.
        ace=_ace() if _ace_wanted(editor, base_commit, may_write) else Markup(""),
        acesurface=_ACE_SURFACE if _ace_wanted(editor, base_commit, may_write) else Markup(""),
        # Only where there is a server to talk to, and only for somebody it would
        # take a frame from. The static export renders the same template with
        # `editable` false, so it carries neither the library nor the script — a
        # page opened from a memory stick has no socket to open and nothing in it
        # that would try.
        #
        # `may_write` is the second half and it is newer: reads here are public,
        # so most page loads are readers, and a reader was given the socket code
        # anyway. It knocked five times, was correctly refused five times, and put
        # five red lines in the console of a page that was working exactly as
        # designed — which is how a real error comes to be ignored. It also
        # carried the Yjs bundle to do it.
        #
        # The answer comes from `writer` on the server (see `may_write` in
        # `web.py`) and not from `/api/me`, which the shell already fetches: that
        # route answers `viewer`, and under `--auth dev` there is no session while
        # the write is permitted. A gate on the corner would silence the editor in
        # exactly the mode this tool is tried in.
        #
        # And never when creating: a record with no id has no room to join,
        # exactly as the old create page never carried these bytes.
        yjs=_yjs() if base_commit is not None and may_write and creating is None else Markup(""),
        coedit=(
            _COEDIT if base_commit is not None and may_write and creating is None else Markup("")
        ),
    )
    if creating is not None:
        # No nav item marked, deliberately: `aria-current="page"` claims a page
        # within the set, and pressing Table from this form abandons it rather
        # than staying put. With nothing lit, the <h1> is what names the page.
        return _page(
            f"openproj — new {creating}", body, _DETAIL_STYLE + _SUGGEST_STYLE, links,
            unreadable=index.unreadable,
        )
    return _page(
        "openproj — detail", body, _DETAIL_STYLE + _SUGGEST_STYLE, links, "detail",
        index.unreadable,
    )


_PROMOTE = """
<div id="promote">
  {% if kinds|length > 1 %}
  <label for="into">Promote this into</label>
  <select id="into">
    {% for value, label in kinds %}<option value="{{ value }}">{{ label }}</option>
    {% endfor %}
  </select>
  {% endif %}
  <button type="button" id="promote-go" class="button primary">Promote</button>
  <span id="promoted" role="status" aria-live="polite"></span>
  <p class="hint">{{ hint }}</p>
</div>
<script>
{#- An IIFE, because this fragment lands on a page that has already declared
    FORM, SAVE and BASE at top level and a second `const` of any of them is a
    SyntaxError that takes the whole script block with it — including the save
    button, which is the control this bar sits beneath. -#}
(() => {
  const GO = document.getElementById('promote-go');
  const INTO = document.getElementById('into');
  const SAID = document.getElementById('promoted');
  GO.onclick = async () => {
    // Disabled first and never re-enabled on success. Promotion mints a record,
    // so a second press is a second pitch — and the page navigates away rather
    // than staying on a note that now has to be reloaded to look right.
    GO.disabled = true;
    SAID.textContent = '';
    const response = await fetch('/api/promote', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        source: {{ source|tojson }},
        kind: INTO ? INTO.value : {{ only|tojson }},
        base_commit: {{ base_commit|tojson }},
      }),
    });
    const answer = await response.json();
    if (!response.ok) {
      GO.disabled = false;
      SAID.textContent = refusal(answer, response.status);
      return;
    }
    location.href = {{ record|tojson }} + answer.id;
  };
})();
</script>
"""
