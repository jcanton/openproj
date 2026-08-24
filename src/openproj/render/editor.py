"""The two editing surfaces — Ace and the plain textarea — and the co-editing script."""

from __future__ import annotations

from markupsafe import Markup

# --- the second editor's adapter, and where it is NOT ------------------------
#
# Out of `_COMBOBOX` and into its own block, on a measurement: `_COMBOBOX` is
# emitted on the table, the create form, the record page and the cycle page
# (grep `combobox=_combobox_html`) — and the table and the cycle page have no
# body editor at all. Leaving this beside `textareaSurface` cost 12,978 B on
# every one of those pages including those two, for an adapter that can only be
# reached where 594 KB of library is also in the page. It goes out with the
# library or it does not go out.
#
# Inlined AFTER `ace.js`, so `ace.require` is there when it parses, and BEFORE
# the page script that calls `bodySurface`.
_ACE_SURFACE = Markup(r"""
<style>
/* Ace's own look, re-expressed in this page's tokens.
   `ace.js` carries 27 hex colours and 53 `rgb()` literals and injects them at
   runtime through `importCssString`, so the second editor arrives wearing a 2010
   TextMate theme on a page with a dark mode. **No new colour value is defined
   here**, and that is deliberate: every declaration below resolves a token that
   already exists in all three of the blocks this repository requires — bare
   `:root`, `:root[data-theme="dark"]` and the guarded `prefers-color-scheme`
   media query — so there is nothing that could be right in one block and wrong
   in another, which is the failure that rule exists to prevent.
   Ace's rules are `.ace-tm .ace_gutter` and the like, (0,2,0); these are the
   same or heavier, and they are inlined in the page while Ace's are injected
   into the head at construction — later in the document either way. */
/* The same box as `textarea.field`, because it is the same box: 3px, the app's
   corner, and not the 4px this was written with — the writing surface and the
   fifteen fields beside it are read together, and one of them rounder than the
   rest is the drift the shell's rule exists to stop. */
.acebox { position: relative; width: 100%; min-height: 60vh; box-sizing: border-box;
          border: 1px solid var(--line-strong); border-radius: 3px; }
.ace_editor { font-family: var(--font-mono); font-size: 13px; line-height: 1.55;
              border-radius: 3px; }
.ace-tm, .ace-tm .ace_scroller { background: var(--surface); color: var(--fg); }
.ace-tm .ace_gutter { background: var(--surface-2); color: var(--muted);
                      border-right: 1px solid var(--line); }
.ace-tm .ace_gutter-active-line { background: var(--surface); }
.ace-tm .ace_cursor { color: var(--fg); }
.ace-tm .ace_marker-layer .ace_selection { background: var(--band); }
.ace-tm .ace_marker-layer .ace_active-line { background: var(--surface-2); }
/* Where everybody else in the room is, drawn in Ace's own marker layer.
   `position` comes from the class because it has to: the layer writes each
   marker's whole `cssText` — height, top, left, right, and whatever this page
   appends — so a `position` written there would be replaced on the next frame,
   which is exactly why Ace's own selection rule supplies it here too.
   The login rides in on a custom property rather than in a child element, and
   that is not a flourish. The layer RECYCLES its divs between markers frame to
   frame and never clears their text, so a name written as a child node would
   sooner or later be drawn inside somebody's selection, with no code left that
   knows it is there. A custom property cannot outlive the recycling: `cssText`
   is replaced wholesale, so the div loses the name in the same instruction that
   takes it away from this feature. */
.ace-tm .ace_marker-layer .op-seat { position: absolute; }
.ace-tm .ace_marker-layer .op-seat::after {
  content: var(--seat-name, ""); background: var(--seat-ink, transparent);
  position: absolute; right: .25rem; top: 0; white-space: pre;
  font-size: 10px; line-height: 1.4; padding: 0 .3rem; border-radius: 3px;
  color: var(--bg); font-family: var(--font-sans); }
.ace-tm .ace_indent-guide { background: none; border-right: 1px solid var(--line); }
/* The keyboard ring, and the reason it needs a rule of its own. Ace's real input
   is a 2.5x1 CSS px `<textarea>` with `opacity: 0` parked at the caret, so the
   shell's floor — `:where(a, button, input, select, textarea, summary,
   [tabindex]) :focus-visible { outline: 2px solid var(--focus) }` — draws a
   two-pixel ring around a two-pixel box in the middle of the document. The ring
   belongs on the thing a person can see, which is the editor. */
.ace_text-input:focus, .ace_text-input:focus-visible { outline: none; }
.acebox:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
/* Full page and the split view, matched to the rules the box already has: the
   pane gives its height and the editor takes all of it, rather than a `60vh`
   minimum pushing the status bar off the bottom of the screen. */
article.record.full .acebox, body.fullpage .acebox { height: 100%; min-height: 0; }
</style>
<script>
// --- Ace, as the same surface ----------------------------------------------
//
// The second editor, and the only ask a textarea cannot have: ask 6, a vim
// keymap. `static/VENDOR.md` records the search and the price — 594,306 B for
// `ace.js` and `keybinding-vim.js`, the markdown mode deliberately dropped — and
// records that this is a HUMAN OVERRIDE of a written rule rather than evidence
// that the rule was wrong. Nobody has been measurably slowed down by the
// textarea, which was the condition written down for revisiting; somebody asked
// for vim, which is a different and legitimate reason.
//
// Everything between this banner and the one that closes it is the only code on
// these pages that knows the document may be being written in Ace. It builds the
// same ten members `textareaSurface` does, so `applyMark`, `indentLines`,
// `attachStatus`, `attachUploads`, the draft writer, the room and the toolbar
// reach it without knowing which one they got.
//
// **The textarea stays in the page and stays in the form**, hidden. `ace.edit`
// on the box itself REMOVES it from the DOM and from the form — measured — and
// every test in `tests/test_seats.py` and every page-mode shim test selects
// `textarea[name=body]` and would have gone on passing against a surface nothing
// reads. It is stale here and nothing reads it: the one place that could,
// `SURFACE.text()`, is this object.
// `seeded` is handed in rather than read off the box, and that is the one-place
// rule holding: `textareaSurface` is still the only code that knows a
// `<textarea>` has a `.value`, and this surface is given the document by it.
// A login, off a socket, put inside a CSS string. Two characters can end that
// string — a backslash and the quote — and a newline ends the declaration around
// it; everything else is inert between quotes. They are ESCAPED rather than
// stripped, because the name somebody chose is the name that should be drawn.
//
// This is the same question `_image`'s allowlist and the `BARS_JSON` title
// answer in their own contexts, and `AGENTS.md` records what happens when a
// value is allowed to equal the mechanism carrying it. Here the mechanism is one
// inline `style`, so the worst a hole would buy is a declaration on one div
// rather than a handler — which is a reason to write the escape, not a reason to
// skip it.
function cssString(text) {
  return String(text).replace(/[\\'\n\r\f]/g, character =>
    character === '\\' ? '\\\\' : character === "'" ? "\\'" : '\\A ');
}


function aceSurface(area, seeded) {
  const Range = ace.require('ace/range').Range;
  // Ace lays out an absolutely-positioned renderer inside a box it is given, so
  // it needs a box of its own rather than the textarea's place in the flow.
  // Inside `.bodywrap`, so the width, the split view's column and the seat
  // layer's containing block are all the ones the textarea had.
  const host = document.createElement('div');
  host.className = 'acebox field';
  area.after(host);
  area.hidden = true;
  const editor = ace.edit(host);
  const session = editor.session;
  const document_ = session.doc;

  // **One line ending, pinned.** Ace's `Document` autodetects a newline
  // sequence and `getValue()` then rejoins EVERY line with it, while a
  // `<textarea>` normalises CRLF to LF unconditionally in both directions — so
  // the two surfaces this application now ships normalise in OPPOSITE
  // directions, and `"a\nb\rc\nd"` is the case no length or index check can
  // see: same length, different bytes.
  //
  // **This is the second of two places, and the first one is the room.**
  // `coedit.one_newline` normalises where text ENTERS the room, so a surface
  // opening on it never sees a carriage return — that is what stops the two
  // rewriting each other's endings once a keystroke, and deleting this line
  // alone does not reintroduce it. What this line answers is the OTHER door:
  // `Document.insert` re-detects when the document is one line
  // (`getLength() <= 1 && this.$detectNewLine(t)`), so pasting Windows text into
  // a new record would set `$autoNewLine` and rejoin the whole document with
  // CRLF. `test_the_second_surface_holds_one_line_ending_whatever_is_pasted_
  // into_it` is that case and it fails without this.
  document_.setNewLineMode('unix');

  // Seeded once, on construction, and this is the ONE `setValue` in the file.
  // It is not a binding operation: nothing observes this document yet and the
  // room has not been joined. `-1` puts the caret at the top. Every write after
  // this one goes through `splice`, and
  // `test_the_second_surface_never_sets_or_replaces_the_whole_document` holds it
  // to that by reading the shipped page.
  editor.setValue(seeded, -1);
  // **The seed is not an edit and does not go on the undo stack.** The comment
  // here used to say `-1` reset Ace's history. It does not: `editor.setValue` is
  // `session.doc.setValue`, an ordinary insert to the manager, while it is
  // `session.setValue` that calls `reset()`. Measured in Chrome the moment the
  // toolbar gained a button that reaches this stack from outside Ace's own key
  // handling — one press of undo on a freshly opened document took it from 119
  // characters to 0, which in a room goes out as an update frame and is
  // committed. There is nothing behind the seed to give anybody back.
  session.getUndoManager().reset();
  // And having seeded it, SAY if that changed anything, rather than silently
  // rewriting somebody's file the moment they opened it in the other editor.
  // Nothing should reach here — the room and `parse_text` both hand over LF —
  // and a branch that decides not to act in silence has shipped here three
  // times, so the one that decides it DID act says so.
  if (session.getValue() !== seeded) {
    announce('This document contains line endings the editor cannot hold, and they '
             + 'have been made ordinary newlines. Saving writes the change.');
  }

  // Ace's own affordances, set from the same preferences the textarea's are.
  editor.setOptions({
    // Ask 5, which Ace answers itself: soft tabs at the remembered width. The
    // page's own `indentLines` does not run here, and the reason is Ace's rather
    // than this page's — its `stopEvent` does `stopPropagation` as well as
    // `preventDefault`, so Tab never reaches the keydown listener `attachEditing`
    // put on this box. Measured, with a listener beside it.
    useSoftTabs: true,
    tabSize: INDENT.length,
    wrap: true,
    showPrintMargin: false,
    // The default is a `<textarea>` 2.5x1 CSS px at the caret with opacity 0,
    // and Ace rewrites its `aria-label` — so the box that used to say "Shaping
    // document" to a screen reader says whatever Ace last put there.
    placeholder: '',
  });
  editor.renderer.setScrollMargin(0, 0);
  if (EDITOR.keymap !== 'default') {
    editor.setKeyboardHandler(EDITOR.keymap === 'vim' ? 'ace/keyboard/vim' : null);
  }
  editor.textInput.getElement().setAttribute('aria-label', area.getAttribute('aria-label') || '');

  // **The five default commands that fetch a module over the network, removed.**
  // Ace's command table calls `config.loadModule`, which is
  // `createElement('script'); i.src = e; head.appendChild(i)` — measured under
  // this exact CSP: Cmd-F gives `defaultPrevented=true`, one injected
  // `ext-searchbox.js`, a `script-src-elem` violation, no searchbox in the DOM
  // and an EMPTY `window.error`. Ace takes Cmd-F away from the browser and gives
  // back nothing, in silence. Removing them hands the key back to Chrome, whose
  // own find works on this document and on the rendered pane beside it.
  //
  // This is application code and not upstream behaviour: the bytes are verbatim,
  // the behaviour deliberately is not, and `docs/EDITOR.md` says why in-editor
  // find is not being bought.
  for (const name of ['find', 'replace', 'showSettingsMenu',
                      'goToNextError', 'goToPreviousError']) {
    editor.commands.removeCommand(name);
  }

  let applying = false;

  // **Undo must never reach a delta this tab did not make**, and until this line
  // it did. Measured in Chrome against a real room: Ann types, Bob types, Ann
  // presses Ctrl+Z — and what came back out was BOB's sentence, not Ann's. Worse
  // than a wrong window: an undo is an ordinary edit as far as the change handler
  // is concerned, so it went out through `spliced` as an `update` frame and
  // deleted Bob's writing in Bob's window too, and then in the commit. One
  // keystroke of somebody else's, taken back for everybody, by the key people
  // press when they want their OWN last thing back.
  //
  // The cause is not this binding's: Ace's `UndoManager` records every delta the
  // session sees, and a delta applied from the socket is a delta the session
  // sees. `applying` already says which are which, so the manager is told to
  // ignore those and nothing else.
  //
  // The PUBLIC `add`, and not `session.$fromUndo` — which is the flag Ace itself
  // uses at this exact seam and which also works, measured. A private field that
  // a re-vendoring renames leaves this silently doing nothing again; `add`
  // missing throws on the line below, at construction, where somebody reads it.
  //
  // What this is NOT: S4. The `<textarea>` still loses its native undo history
  // on every remote keystroke — `splice` under `apply` assigns `.value` there,
  // which is what wipes it — and there are still no undo and redo buttons. This
  // stops the half that destroys somebody else's writing; `Y.UndoManager` is
  // still owed the half that gives you back your own.
  const history = session.getUndoManager();
  const remember = history.add.bind(history);
  history.add = (delta, merge, forSession) => {
    if (!applying) remember(delta, merge, forSession);
  };

  const heard = {input: [], caret: [], splice: []};
  const fire = (kind, ...args) => { for (const listener of heard[kind]) listener(...args); };

  // --- where everybody else is, in Ace's own layer -------------------------
  //
  // **ONE dynamic marker for the whole room, added once here.** A `who` frame
  // arrives every time anybody in the room moves their caret, so a marker added
  // per frame is a marker leaked per frame; `sitting` is the roster and this
  // reads it. `addDynamicMarker` is the API for exactly that shape — a marker
  // with no range of its own, asked to draw itself.
  //
  // The layer calls `update` on the frames it redraws itself on, which are the
  // frames Ace draws the selection and the active line on. So a scroll, a fold,
  // a rewrap, a window resize and somebody else's keystroke each land the band
  // without one line here subscribing to any of them — and that is the whole
  // reason this surface can draw a band at all. `static/VENDOR.md` holds this
  // feature to "a caret one line off is worse than no caret", and the way that
  // sentence is kept is that the screen row is worked out INSIDE `update`, from
  // the document position, every frame, and never remembered from the last one.
  //
  // What the other surface needs a mirror element for, this one gets from the
  // editor that is already laying the text out.
  //
  // **Each seat is an ANCHOR and not the index it arrived as.** An index is a
  // number about a document that has already changed by the time the next frame
  // paints: this surface repaints on its own frames, which are the frames Ace
  // paints a keystroke on, and those run BEFORE the room's own subscribers do —
  // `spliced` is a microtask away and the roster is corrected there. Measured:
  // three characters typed above somebody walked their band up three rows, one
  // per keystroke, before one line of this page's own code had run.
  //
  // An anchor is moved by `applyDelta` itself, in the same instruction that
  // moves the caret and every fold, so there is no window in which it is stale
  // and nothing here has to subscribe to anything to keep it. It is the reason
  // `splice` uses `Document`'s own `remove` and `insert`, applied to somebody
  // else's caret instead of this tab's.
  //
  // They are detached on the way out. An anchor is a listener on the document,
  // and a roster arrives every time anybody in the room moves.
  let sitting = [];
  session.addDynamicMarker({
    update(html, layer, session_, config) {
      for (const seat of sitting) {
        const at = seat.anchor.getPosition();
        // Clipped on the DOCUMENT row and drawn at the SCREEN one, which is the
        // same pair Ace's own `update` uses on a static marker: `config.firstRow`
        // and `lastRow` count lines of the file, while `$getTop` measures from
        // `firstRowScreen`. Ace renders only what is on screen, and a marker
        // outside that is a div in the layer with no text under it.
        if (at.row < config.firstRow || at.row > config.lastRow) continue;
        const row = session_.documentToScreenRow(at.row, at.column);
        layer.drawScreenLineMarker(
          html, new Range(row, 0, row, Infinity), 'op-seat', config,
          `background:hsl(${seat.hue} 70% 60% / .22);`
          + `--seat-ink:hsl(${seat.hue} 70% 60% / .85);`
          + `--seat-name:'${cssString(seat.login)}'`);
      }
    },
  }, false);

  const indexOf = position => document_.positionToIndex(position);
  const positionOf = index => document_.indexToPosition(index);

  // **Ace's own change deltas, converted at the moment they arrive.** This is
  // the binding, and the whole reason it is not `typed()`'s prefix/suffix walk
  // is written in `docs/EDITOR.md`: `session.setValue` and `session.replace` are
  // both remove-then-insert with an EMPTY DOCUMENT between the two events, which
  // no prefix/suffix walk can recover a splice from, and the one measured
  // consequence was a passive tab pushing 97,890 characters up the socket under
  // its own name.
  //
  // A delta arrives AFTER it has been applied, and that is why `start` is
  // converted here and not at flush time: everything before `start` is untouched
  // by the delta, so its index is the same on both sides of it, while everything
  // after it has moved. The length is `lines.join('\n').length` — UTF-16 code
  // units, the same space `Y.Text`, `selectionStart` and `Room.sits` count in.
  const pending = [];
  session.on('change', delta => {
    if (applying) return;
    const at = indexOf(delta.start);
    const run = delta.lines.join('\n');
    pending.push(delta.action === 'insert'
      ? {from: at, to: at, put: run} : {from: at, to: at + run.length, put: ''});
    flush();
  });

  // Batched once per Ace operation, because one gesture is one edit: `:%s/x/y/g`
  // and multi-cursor each fire hundreds of deltas, and measured, one keystroke
  // under multi-cursor deleted 14,789 characters and reinserted 13,345. Sent as
  // one transaction they are one update on the wire; sent one at a time they are
  // hundreds, and `MAX_OUTBOX_BYTES` fills in three.
  //
  // Two ways out of the queue and they drain the same list, so whichever comes
  // first wins and the other finds it empty. `beforeEndOperation` is Ace's own
  // end-of-gesture; the microtask is for a programmatic edit made outside an
  // operation, and it is a MICROtask rather than a timeout because a frame off
  // the socket is a macrotask — a queue still holding this tab's keystrokes when
  // a remote update arrives is a queue `reflect()` would splice away.
  let queued = false;
  function flush() {
    if (queued) return;
    queued = true;
    Promise.resolve().then(drain);
  }
  editor.on('beforeEndOperation', drain);
  function drain() {
    queued = false;
    if (!pending.length) return;
    const runs = pending.splice(0, pending.length);
    fire('splice', runs);
    // ONE `input` for the gesture and not one per delta, and that is the same
    // argument as the transaction above rather than a separate optimisation.
    // `attachStatus`'s refresh splits the whole document to count its lines, the
    // gutter relays out every line, the draft writer serialises the body: a
    // substitution firing them seventy-four times does seventy-four documents'
    // worth of work for one press. The subscribers are all idempotent on the
    // result, which is what makes coalescing them correct rather than merely
    // cheaper.
    fire('input');
    fire('caret');
  }

  // **A caret moves without the document moving, and until this line only the
  // document said so.** `drain` above was the only source of `caret` on this
  // surface, so every subscriber to it heard about an arrow key, a click in the
  // text, `gotoLine` or a fold exactly never. Measured in Chrome on
  // `/detail/…?editor=ace`: `gotoLine(3, 4)` and then one line down left the
  // status bar reading `Line 1, Column 1` — ask 5's whole content — and it
  // corrected itself only at the next keystroke. The other subscriber is
  // `sit()`, so this tab's seat went up the socket once per burst of typing and
  // never on the move between them: everybody else in the room had a band
  // sitting where this person last typed rather than where they are, which is
  // the one thing a band exists to say.
  //
  // `changeCursor` on the selection and not `changeSelection`, which also fires
  // for a range that grew with the caret standing still. `sit()` sends `from`
  // and `attachStatus` reads both ends off `caret()`, so the cursor moving is
  // the event that means what these subscribers ask about.
  //
  // Coalesced onto a microtask for the reason `flush` is, and not as a
  // precaution: `:%s/cycle/bet/g` moves the cursor once per replacement, and
  // `attachStatus`'s refresh splits the whole document to count its lines. The
  // subscribers are idempotent on the position — `sit` compares against what it
  // last sent, `refresh` recomputes — which is what makes coalescing them
  // correct rather than merely cheaper.
  //
  // NOT gated on `applying`, exactly as the textarea's `caret` listeners are
  // not: a remote splice really does move this caret, because `applyDelta`
  // moves Ace's anchors, and a readout that says where it now is is the honest
  // answer.
  let caretQueued = false;
  editor.selection.on('changeCursor', () => {
    if (caretQueued) return;
    caretQueued = true;
    Promise.resolve().then(() => { caretQueued = false; fire('caret'); });
  });

  return {
    // The Ace container, for the questions that are about a box: class names,
    // `closest`, and the events the members below do not cover — keydown, paste
    // and drop, which bubble here from Ace's own hidden input.
    el: host,
    editor,

    text: () => session.getValue(),

    caret() {
      const range = editor.selection.getRange();
      return {from: indexOf(range.start), to: indexOf(range.end)};
    },

    setCaret(from, to) {
      editor.selection.setRange(
        Range.fromPoints(positionOf(from), positionOf(to === undefined ? from : to)));
    },

    // The only write, and NEVER `session.setValue` or `session.replace`. Both
    // are remove-then-insert as far as a change handler can see; `Document`'s
    // own `remove` and `insert` are the two halves said separately, in a bounded
    // range, which is what a person's edit is made of too. Ace's anchors — the
    // caret, every fold, every marker — are moved by `applyDelta` itself, so a
    // remote keystroke leaves this tab's caret where its owner put it without
    // anything here arithmetic-ing it.
    splice(from, to, put) {
      const run = () => {
        if (to > from) document_.remove(Range.fromPoints(positionOf(from), positionOf(to)));
        if (put) document_.insert(positionOf(from), put);
      };
      if (applying) { run(); return; }
      // A person's edit: one undo step, and Ace's history merges by operation
      // exactly as `execCommand` gives the textarea one. Focused first for the
      // same reason `replaceRange` focuses the box — a toolbar press is a
      // continuation of typing, not a departure from it.
      editor.focus();
      editor.startOperation({command: {name: 'openproj'}});
      try { run(); } finally { editor.endOperation(); }
    },

    onInput(listener) { heard.input.push(listener); },
    onCaret(listener) { heard.caret.push(listener); },

    // The eighth capability, and the one a textarea does not have: what changed,
    // as ranges, rather than the whole document to be diffed against. A surface
    // that can say gets asked; one that cannot is recovered from. `_COEDIT`
    // branches on the presence of this member and on nothing else.
    onSplice(listener) { heard.splice.push(listener); },

    // Where everybody else in the room is. A MEMBER and not a `provides` flag —
    // see the note on `textareaSurface`'s own `seats`, which says why the flag
    // that used to be here went away rather than flipping to true.
    //
    // Both halves go through the renderer's public `updateBackMarkers`, which is
    // `session._signal('changeBackMarker')` with a name on it. The private
    // spelling is the one a re-vendoring renames into silence, and this surface
    // has already paid that once — the comment on `history.add` above is the
    // receipt.
    seats: {
      draw(others) {
        for (const seat of sitting) seat.anchor.detach();
        sitting = others.map(seat => {
          const at = document_.indexToPosition(seat.at);
          return {...seat, anchor: document_.createAnchor(at.row, at.column)};
        });
        editor.renderer.updateBackMarkers();
      },
      clear() {
        for (const seat of sitting) seat.anchor.detach();
        sitting = [];
        editor.renderer.updateBackMarkers();
      },
    },

    // `history: true`, and true only because of the four lines above that bind
    // `history.add`. Ace keeps its own stack across a remote change, that stack
    // is right about whose deltas are in it, and Ace's command table is what
    // Ctrl+Z reaches here — `stopEvent` stops propagation, so the key never gets
    // to `attachEditing`. Two histories with the key on one and the button on
    // the other is worse than either, so `historyOf` gives both to this one.
    provides: {gutter: true, history: true},

    // `canUndo`/`canRedo` and not the `hasUndo`/`hasRedo` aliases beside them,
    // for the reason `add` above is the public one: an alias is what a
    // re-vendoring drops. Through `editor` rather than the manager, so the caret
    // and the folds come back with the text.
    history: {
      can: what => what === 'undo' ? history.canUndo() : history.canRedo(),
      step(what) { editor.focus(); if (what === 'undo') editor.undo(); else editor.redo(); },
      keyed: false,
    },

    // Ask 6, and the whole reason 594 KB is in this page. `null` and not
    // `'ace'`: `setKeyboardHandler` with a string that is not `ace` goes through
    // `config.loadModule(['keybinding', name])`, which is the network path the
    // five removed commands were removed for — `ace/keyboard/vim` is the one
    // that is already defined here, by the second file, and every other name
    // would fetch.
    keymaps: KEYMAPS,
    setKeymap(name) {
      editor.setKeyboardHandler(name === 'vim' ? 'ace/keyboard/vim' : null);
    },

    scrolled: () => session.getScrollTop(),
    scrollTo(top) { session.setScrollTop(top); },
    onScroll(listener) { session.on('changeScrollTop', listener); },

    apply(run) {
      const before = applying;
      applying = true;
      try { return run(); } finally { applying = before; }
    },
    applying: () => applying,

    lineCoords() {
      const height = editor.renderer.lineHeight;
      const tops = [];
      for (let row = 0; row < session.getLength(); row++) {
        tops.push(session.documentToScreenRow(row, 0) * height);
      }
      return tops;
    },
  };
}

// --- end of Ace as a surface -----------------------------------------------
</script>
""")


# The two spellings the query string has, and the only two. `ace` is the second
# editor and `plain` is the box that was here before it.
ACE = "ace"
PLAIN = "plain"


def _ace_wanted(editor: str, base_commit: str | None, may_write: bool) -> bool:
    """All three halves, in one place, because the question is asked three times
    on the one template that ships an editor.

    **The parameter is an opt-OUT now, and that is jcanton's decision rather than
    a measurement's.** It was `?editor=ace` opting in; it is `?editor=plain`
    opting out, because "make ace the default, I think it's worth it" — 2026-08-20.
    Nothing in `static/VENDOR.md` moved to make that true: the revisit condition
    that file records is "when somebody is actually slowed down by a textarea",
    and nobody has produced that measurement. A person wanting the editor they
    want is a legitimate reason and it is a different one, and this is the line
    where the difference is decided, so it is written here.

    What did NOT change is who pays, and that is the whole of the rest of this
    docstring. There still has to be an editing surface to put it on, which is
    `editable`, which is `base_commit is not None` everywhere in this file. And
    this reader still has to be somebody the server would take a write from.

    **That second gate is the one the audit found missing, and it is not the same
    as the first.** `editable` is `base_commit is not None` and the served route
    passes a commit for EVERYONE, so a signed-out reader's detail page already
    carries the `<textarea>`, the toolbar and two `attachEditing(` calls. Gating
    594 KB on `editable` alone would have taken that page to 4.19x itself, for a
    keymap whose every save the server refuses. `yjs` and `coedit` already carry
    this same gate, for the same reason. Inverting the parameter is exactly the
    change that could have quietly removed it — the default arm is now the one
    that ships the library — so it is asserted rather than assumed:
    `test_a_reader_who_may_not_write_is_sent_no_editor_library` renders a reader's
    page with no parameter at all and with each of the two.

    `may_write` defaults to False at every caller, so a page rendered by anything
    that has not thought about it — the static export among them — still gets no
    library rather than getting one by omission. The default that flipped is the
    default of the *address*, not the default of this function's other two
    arguments.
    """
    return editor != PLAIN and _editing_possible(base_commit, may_write)


def _editing_possible(base_commit: str | None, may_write: bool) -> bool:
    """The two gates that are not the address: is there an editing session here
    at all.

    It was `_either_editor_possible` and it was named for the switch beside the
    three views — a control offering a choice this page could not honour either
    way is a control that lies about what the page can do. The switch is gone
    (2026-08-24, the plain box is `?editor=plain` and nothing else), and the name
    outlived it by one commit: what this actually gates is the view bar, whose
    three segments are the only door into an editing session, and the second half
    of `_ace_wanted`. Neither is about a choice between two editors any more.

    Still split out rather than written twice, for the reason it always was: two
    copies of one gate is how a control and the bytes come to disagree.
    """
    return base_commit is not None and may_write


# The join between the two panes of the split view, and the one control that
# moves it — jcanton, 2026-08-20: "in the side-by-side edit-preview view, can you
# make it possible to horizontally resize the editor vs the preview boxes?"
#
# **A real separator, not a div with a drag handler.** `role="separator"` with a
# `tabindex` is the window-splitter pattern: it is announced as what it is, it
# carries its position as a value, and it answers the arrow keys and Home and End
# as well as a pointer. A splitter that answers only a mouse is the same defect as
# the thirteen mouse-only toolbar buttons earlier in this branch, which jcanton's
# reviewers caught and which cost a commit each to put right.
#
# The three `aria-value*` numbers are the writing box's share of the two panes as
# a percentage, and they are corrected by `applySplit` the moment the split view
# opens — the floor is measured in pixels against the window, so what 0 and 100
# actually resolve to is not knowable from here. `aria-valuetext` because "62"
# read out on its own says nothing about what it is 62 of.
#
# One constant, emitted once, for the same reason `_VIEW_SEGMENTS` is one: every
# page that draws this surface draws the one template's copy, and a second copy
# of a control is a second place for it to drift.
_SPLIT_HANDLE = Markup(
    '<div id="splitter" role="separator" tabindex="0" aria-orientation="vertical"'
    ' aria-label="Split between the writing box and the preview"'
    ' aria-valuemin="0" aria-valuemax="100" aria-valuenow="50"'
    ' aria-valuetext="50% writing, 50% preview"'
    ' title="Drag, or use the arrow keys, to divide the two panes.'
    ' Double-click evens them."></div>'
)


_COEDIT = Markup(r"""
// Several people typing in one shaping document, arriving at one commit.
//
// The floor is a page with no socket at all, and it is the ordinary case rather
// than the edge: the static export is opened over `file://`, which has an opaque
// origin and no server; a proxy may drop the upgrade; Cloud Run tears every
// socket down at five minutes; and a reader who is not signed in is refused the
// handshake. Every path below ends at the same place — a `<textarea>`, a draft,
// a `base_commit`, Save, and a 409 — which is exactly this page without this
// script. Nothing here is allowed to be a prerequisite for editing.
//
// The socket needs no change to the policy. `connect-src 'self'` matches the
// `ws`/`wss` variant of this document's origin under CSP 3, which is a claim
// about browsers rather than about this code, so `tests/browser.py` asks Chrome
// instead of believing this comment.
const COEDIT = (() => {
  // What every refusal returns: an object that says it is not live, so `save()`
  // above takes the path it took before any of this existed.
  const asleep = {live: () => false, save: () => {}};
  if (typeof YJS === 'undefined' || typeof WebSocket === 'undefined') return asleep;

  const doc = new YJS.Doc();
  // Never zero. The room seeds its document with client id 0 so that a browser
  // seeding itself from the same commit produces the same bytes — that equality
  // is what makes a server restart a reconnection rather than a document merged
  // into itself twice — and a second writer sharing that id would be
  // indistinguishable from the seed.
  if (doc.clientID === 0) doc.clientID = 1;
  const text = doc.getText('body');
  const together = document.getElementById('together');
  const box = document.getElementById('conflict');

  let socket = null;
  let seed = null;      // the commit this tab's document was built from
  let me = '';
  let bound = false;    // the textarea and the document are wired together
  let dead = false;     // asked to reload, or given up on: stay degraded
  let saving = false;   // an `openproj:writing` this owes an `openproj:wrote`
  let arrived = false;  // the socket has worked at least once
  let attempts = 0;

  // --- undo, in a document somebody else is also writing ---------------------
  //
  // **This defect needs no action from you at all — only somebody else typing.**
  // A remote keystroke reaches the box through `reflect()`, which splices under
  // `apply`, which assigns `.value` — the correct write for a change nobody here
  // made, since a remote change cannot be merged into a native undo stack. What
  // was never written down is the cost: in a live room every character somebody
  // else types destroys your undo history. And it does not come up empty, it
  // lies — measured in Chrome, `queryCommandEnabled('undo')` still answers TRUE
  // afterwards. That is `d6997e3`'s image-upload data loss by another road, and
  // worse, because that one at least needed you to do something.
  //
  // `trackedOrigins` is the whole design, in one line: `'typed'` is what
  // `typed()` and `spliced()` already pass to `doc.transact`, and a frame off the
  // socket arrives as `'remote'`. So one press gives back YOUR last thing and
  // never Bob's sentence, which is the failure `f7bde59` measured on the other
  // surface. The default `captureTimeout` of 500ms stands: it is what makes a
  // run of typing one step rather than one per character.
  //
  // Zero new vendored bytes — `UndoManager` is in the bundle's export clause and
  // `_yjs()` carries that clause over verbatim, asserted in
  // `test_the_yjs_bundle_inlines_as_a_classic_script`.
  const undos = new YJS.UndoManager(text, {trackedOrigins: new Set(['typed'])});
  // Said rather than polled, so the buttons are honest about an empty stack the
  // instant it becomes one.
  const toldHistory = () => dispatchEvent(new Event('openproj:history'));
  for (const when of ['stack-item-added', 'stack-item-popped', 'stack-cleared']) {
    undos.on(when, toldHistory);
  }

  // Who answers the toolbar's history buttons, handed over through the one `let`
  // the shared block declares for it.
  //
  // **Not gated on the socket being open.** A room that has bound has spliced
  // under `apply` at least once, so from then on the box's native stack is a
  // lying stack whether or not the connection survives — and Cloud Run closes
  // every socket at five minutes, so a down socket is ordinary rather than a
  // fault. `bound` is the condition; `stop()` is the one place that ends it.
  function ownHistory() {
    COEDIT_HISTORY = bound && !dead ? {
      can: what => what === 'undo' ? undos.canUndo() : undos.canRedo(),
      step(what) {
        // Anything typed since the last `input` event first, so the step taken
        // back is the whole of the last thing. `save()` opens with it too.
        typed();
        if (what === 'undo') undos.undo(); else undos.redo();
      },
      // Here the page HAS to take ⌘Z: the stack the browser would reach is the
      // one `reflect()` destroyed.
      keyed: true,
    } : null;
    dispatchEvent(new Event('openproj:history'));
  }

  // `btoa` over a spread argument list throws on a document of any size, and a
  // full state update is tens of kilobytes. In chunks, which is the only reason
  // this is not one line.
  function b64(bytes) {
    let out = '';
    for (let at = 0; at < bytes.length; at += 0x8000)
      out += String.fromCharCode.apply(null, bytes.subarray(at, at + 0x8000));
    return btoa(out);
  }
  const raw = held => Uint8Array.from(atob(held), letter => letter.charCodeAt(0));

  function send(message) {
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  }

  function live() {
    return bound && !dead && socket !== null && socket.readyState === WebSocket.OPEN;
  }

  // Where an offset counted in characters lands in the document's index space.
  //
  // Two index spaces, and they are not the same one. `[...text]` walks code
  // points — characters, the things a person typed — while `Y.Text`, `.length`
  // and `.slice` are all counted in UTF-16 code units, and every emoji, every
  // flag and this repository's own robot is one of the first and two of the
  // second. This is the browser's `byte_offset` (`coedit.py`): the same rule
  // for the same reason, one conversion at one boundary rather than arithmetic
  // at each call site, and `test_the_browser_splices_on_a_whole_character`
  // holds every index handed to the document to coming from here.
  function units(chars, at) {
    let n = 0;
    for (let i = 0; i < at; i++) n += chars[i].length;
    return n;
  }

  // The textarea into the document. A textarea reports its whole value, so the
  // edit has to be recovered from it: the common prefix and suffix bound what
  // changed, which is one delete, one insert, or one of each. Recovered rather
  // than replaced wholesale, because replacing the text would delete every
  // character somebody else is standing in and reinsert it — their caret would
  // jump to the top of the document on every keystroke of mine, and the commit
  // would credit whoever typed last with the whole file.
  function typed() {
    const now = SURFACE.text(), was = text.toString();
    if (now === was) return;
    // Scanned a character at a time and not a code unit at a time. Two emoji
    // that share a leading half — a thumb up and a thumb down differ only in
    // their second unit — stop a unit-at-a-time scan *between* the halves of a
    // surrogate pair, and the splice then took out and put back half a
    // character at each end. This document was left holding one thing and the
    // room another, silently: a lone surrogate cannot be encoded, so the update
    // carried a replacement character where the half was, and the two copies
    // never converged again. An emoji picker, a flag, replacing one emoji or
    // backspacing one of two adjacent ones is all it takes — and a PATCH, which
    // sends the whole body, cannot do it, so the socket made emoji strictly
    // worse than the editor it replaced.
    const nowChars = [...now], wasChars = [...was];
    let head = 0;
    while (head < nowChars.length && head < wasChars.length
           && nowChars[head] === wasChars[head]) head++;
    let tail = 0;
    while (tail < nowChars.length - head && tail < wasChars.length - head
           && nowChars[nowChars.length - 1 - tail]
              === wasChars[wasChars.length - 1 - tail]) tail++;
    doc.transact(() => {
      // `wasChars.slice(0, head)` and `nowChars.slice(0, head)` are the same
      // characters by construction, so converting against either gives the same
      // unit — and the delete starts at it, so it is still where the insert goes.
      const cut = units(wasChars, wasChars.length - tail) - units(wasChars, head);
      if (cut > 0) text.delete(units(wasChars, head), cut);
      const put = nowChars.slice(head, nowChars.length - tail).join('');
      if (put) text.insert(units(nowChars, head), put);
    }, 'typed');
  }

  // A bulk gesture is announced before it goes to everybody, and the measure is
  // HOW MANY PLACES rather than how many characters — which is not the obvious
  // choice and is the right one.
  //
  // A keystroke is one run. A toolbar mark is two, a delete and an insert. A
  // paste is one, however long: it is a thing somebody did on purpose with
  // content they can see, and announcing it would be noise on the ordinary case.
  // `:%s/cycle/bet/g`, `gg=G`, Replace All and a multi-cursor edit are one press
  // and HUNDREDS of runs, in places nobody is looking at — one of them measured
  // deleting 14,789 characters and reinserting 13,345 on a 14,810-character
  // document, as one frame of 234,892 B, three of which fill the room's outbox.
  // That is the difference worth saying out loud.
  //
  // Said rather than refused: it is a legitimate thing to do to your own
  // document. The ceiling above it is the server's, and `web.py` answers it with
  // a `reload` frame rather than a bare `continue` — which it does because a
  // branch that decided not to act in silence has shipped here three times.
  //
  // Four, because a mark is two and an unwrap is two: five separate places in one
  // press is a gesture and not a keystroke.
  const BULK_PLACES = 4;

  function spliced(runs) {
    if (runs.length > BULK_PLACES) {
      const touched = runs.reduce((n, run) => n + (run.to - run.from) + run.put.length, 0);
      announce(`${touched.toLocaleString()} characters changed at once, in `
               + `${runs.length.toLocaleString()} places, and everybody in this document `
               + 'has them.');
    }
    doc.transact(() => {
      for (const run of runs) {
        if (run.to > run.from) text.delete(run.from, run.to - run.from);
        if (run.put) text.insert(run.from, run.put);
      }
    }, 'typed');
  }

  // The document back into the textarea, with the caret left where the reader
  // put it. Setting `.value` collapses the selection to the end, which on a page
  // where somebody else is typing means the caret walks to the bottom of the
  // document once a second.
  function reflect() {
    const want = text.toString(), was = SURFACE.text();
    if (want === was) return;
    // A SPLICE, bounded at BOTH ends, and never "set the text" — the whole of
    // the argument is on `textareaSurface`. Counted in UTF-16 code units, which
    // is what both of these strings and `Y.Text` are counted in.
    let head = 0;
    while (head < want.length && head < was.length && want[head] === was[head]) head++;
    let tail = 0;
    while (tail < want.length - head && tail < was.length - head
           && want[want.length - 1 - tail] === was[was.length - 1 - tail]) tail++;
    // Inside `apply`: this is the page writing, not a person. On a textarea that
    // is observably nothing, which is why the flag has a test of its own rather
    // than a behaviour to hide behind.
    SURFACE.apply(
      () => SURFACE.splice(head, was.length - tail, want.slice(head, want.length - tail)));
    dirty();
    // Assigning `.value` fires no `input` event, and everything drawn over this
    // box hangs off one. `heard` already calls `drawSeats(); sit();` here for
    // exactly that reason and says so; the gutter, the source line map and the
    // live preview were added later and were not given the same wake-up, so
    // somebody else adding a line left your numbers with the wrong count, the
    // scroll sync reading a stale map, and the rendered pane showing a document
    // nobody has any more. One event, dispatched from the one place that changes
    // the text without typing it, rather than a fourth call added here every time
    // something new listens.
    dispatchEvent(new Event('openproj:editing'));
    // And the rendered pane, asked for by name rather than folded into the event
    // above: this is the one caller of the four that changed a CHARACTER, and the
    // other three would each be paying for a render of a document the server has
    // already been sent. `_VIEWS` is a block above this one in the same scope, and
    // the guard is for the pages that do not carry it.
    if (typeof refreshPreview === 'function') refreshPreview();
  }

  doc.on('update', (update, origin) => {
    // What came down the socket does not go back up it.
    if (origin !== 'remote') send({t: 'update', u: b64(update)});
  });
  // Only once the box and the document have been wired together, which is what
  // `bound` means. The welcome carries the room's whole text, and applying it
  // fires this observer *synchronously* — so an unconditional reflect wrote the
  // room over a restored draft before `welcomed` had looked at it, and the
  // `mine` test below then read the value it had just been overwritten with.
  // `mine` was therefore always false on exactly the first connection it was
  // written for, the draft branch was unreachable, and somebody's unsaved
  // writing went into the box and then out of `localStorage` at the next
  // commit, silently. The document does not own this textarea until the one
  // decision that can lose work has been made.
  text.observe(event => {
    // **Everybody else's caret, carried across whatever just changed, BEFORE the
    // box is rewritten.** `seats` holds an absolute index — where the room last
    // said each person was — and `drawSeats` repaints on every keystroke this
    // tab makes, so without this line each of those keystrokes paints their band
    // against an index it has just invalidated. The correction was a full round
    // trip away (this update reaches them, their `splice` carries their caret,
    // their `sit()` goes to the server, a `who` comes back), so the band
    // alternated between the wrong row and the right one, once per character.
    //
    // Reported by two people in one document: "the other user's presence line
    // was jumping up and down 2-3 lines while I was typing, one jump per char".
    // Two to three lines and not two to three characters because a stale index
    // walks back through CHARACTERS: three of them are three characters of
    // prose, or the whole of a blank line, a `- one` and another blank line —
    // and a shaping document is made of the second kind.
    //
    // Here rather than in `typed` and `spliced`, which is where it was first
    // written, and the difference is not tidiness. This is the one place that
    // sees EVERY change to the document — this tab's, and everybody else's — so
    // a third person typing above the second one moves the second one's band
    // too, and neither of the other two sites could have said that.
    carry(event.delta);
    if (bound) reflect();
  });

  function names(people) {
    if (!together) return;
    const others = people.filter(login => login !== me);
    // `textContent`, so a login off the wire is text and stays text.
    together.textContent = others.length ? `also editing: ${others.join(', ')}` : '';
  }

  // --- where everybody is ---------------------------------------------------
  //
  // A name says somebody else is in the document. It does not say which
  // paragraph they are in, which is the thing you need in order not to rewrite
  // the sentence somebody is halfway through — and in a shaping document that is
  // the whole risk, because two people work on two sections of one file.
  //
  // A band on the line, not a caret. A caret drawn through a mirror element is
  // wrong by a pixel or two and reads as a claim about a character; a translucent
  // band is right about the line or visibly wrong about it, and being visibly
  // wrong is a state somebody can act on.

  let seats = [];

  // Where an index in the document as it WAS lands in the document as it now is.
  //
  // The rule is `splice`'s own `moved` — an index before the change does not
  // move, one after it moves by the difference, one inside a deletion lands
  // where the deletion started — applied op by op along a `Y.Text` delta rather
  // than to one splice, because a delta is what a transaction of several is.
  // Counted in UTF-16 code units at both ends: that is what a `Y.Text` delta
  // measures in a browser and what `Room.sits` relays.
  function carried(index, delta) {
    let was = 0, now = 0;
    for (const op of delta) {
      if (op.insert !== undefined) {
        // An index sitting exactly where the insert lands stays in FRONT of it,
        // which is `at <= from ? at` in `splice`, said the other way round.
        if (index <= was) return now;
        now += typeof op.insert === 'string' ? op.insert.length : 1;
      } else if (op.delete !== undefined) {
        if (index < was + op.delete) return now;
        was += op.delete;
      } else {
        if (index < was + op.retain) return now + (index - was);
        was += op.retain;
        now += op.retain;
      }
    }
    return now + (index - was);
  }

  function carry(delta) {
    if (!seats.length) return;
    seats = seats.map(seat => ({...seat, at: carried(seat.at, delta)}));
  }

  // Drawn again when the box appears. See `showEditing`.
  addEventListener('openproj:editing', () => { drawSeats(); sit(); });
  // And again whenever the box changes shape, which no event on this page says.
  // Three ways it happens and one observer for all three, because all three are
  // the content box changing: the width grip writes `--measure` and dispatches
  // nothing, the gutter's column is the box's own left padding so switching it on
  // rewraps every line under the bands, and the box has a `resize: vertical`
  // handle. Measured before this: turning the gutter on left the band for a caret
  // below a wrapping paragraph a whole 20.15px row above where it belonged, and
  // it stayed there until something else forced a redraw.
  if (BODY && typeof ResizeObserver === 'function') {
    new ResizeObserver(() => drawSeats()).observe(BODY);
  }

  // One hue per login, from the name itself: no server-side allocation, no
  // colour that changes when somebody leaves and rejoins, and the same person is
  // the same colour in everybody's window. The other two channels are fixed, so
  // every band is equally light — a colour that also varies in lightness is one
  // that means "more" to a reader who cannot separate hues.
  function hueOf(login) {
    let hash = 0;
    for (const character of login) hash = (hash * 31 + character.charCodeAt(0)) % 360;
    return hash;
  }

  // The roster, and nothing about pixels. Which line somebody is on is drawn by
  // the surface they are being drawn over — through a mirror on the `<textarea>`
  // and through Ace's own marker layer on the other — and what is left here is
  // the part that is the same either way: who is in the room, who is not this
  // tab, what colour each of them is, and an index the document is long enough
  // to hold.
  //
  // It used to be the whole drawing, with a `provides.seats` flag deciding
  // whether to do it. See `textareaSurface`'s `seats` for why that flag is gone
  // rather than merely flipped to true.
  let saidNoSeats = false;
  function drawSeats() {
    if (!BODY) return;
    const others = seats.filter(seat => seat.login !== me);
    // A surface that cannot draw them says so, once, rather than leaving an
    // empty layer for somebody to report as broken. Neither shipped surface is
    // in this arm any more; it is here for the third one, and it is asked as
    // member presence for the same reason `onSplice` is.
    if (!SURFACE.seats) {
      if (!saidNoSeats && others.length) {
        saidNoSeats = true;
        announce('Who else is in this document is named beside the title. Which line they '
                 + 'are on is not drawn in this editor.');
      }
      return;
    }
    if (!others.length) { SURFACE.seats.clear(); return; }
    const length = SURFACE.text().length;
    SURFACE.seats.draw(others.map(seat => ({
      login: seat.login,
      // Clamped HERE and in neither surface: an index past the end is a roster
      // frame that arrived before this tab's copy of the text caught up, which
      // is a fact about the room rather than about a box.
      at: Math.min(seat.at, length),
      hue: hueOf(seat.login),
    })));
  }

  // Where this tab's caret is, when it moves to a different place. Sent on the
  // index the two ends already agree on — UTF-16 code units, which is what
  // `selectionStart` counts and what a Yjs text is made of in a browser. The
  // server relays it and never reads it; see `Room.sits`.
  let sentAt = -1;
  function sit() {
    if (!BODY || !bound) return;
    const at = SURFACE.caret().from;
    if (at === sentAt) return;
    sentAt = at;
    send({t: 'at', at});
  }

  // The shell counts these in pairs, so they are announced from one place each
  // and guarded by the same flag. Pressing Save both dispatches here and hears
  // the room say `saving` a moment later; two writings against one wrote left
  // the counter permanently above zero, which holds every later event back and
  // means the banner never appears again for the life of the page.
  function writing() {
    if (saving) return;
    saving = true;
    dispatchEvent(new Event('openproj:writing'));
  }

  function settle(commit) {
    if (!saving) return;
    saving = false;
    // Announced even when the write was refused, and from `onclose` when the
    // socket goes mid-write: this is what a `finally` is on the paths that have
    // a request to end.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: commit}));
  }

  function stop(why) {
    dead = true;
    bound = false;
    settle(null);
    names([]);
    // The room no longer answers for the document, so it no longer answers for
    // the undo buttons: they go back to the box's own stack rather than staying
    // pressable over a history nothing will send.
    ownHistory();
    if (why) {
      // Into its own box, never into the textarea: text put into the editing
      // surface is text somebody saves back.
      box.hidden = false;
      box.textContent = why;
    }
    if (socket) socket.close();
  }

  function welcomed(message) {
    const first = !bound;
    if (seed && seed !== message.seed) return stop(message.why || 'reload this page');
    seed = message.seed;
    BASE.value = message.base;
    me = message.you;
    if (message.update) YJS.applyUpdate(doc, raw(message.update), 'remote');
    if (first) {
      // The first arrival is the one moment there is no shared history to
      // reason with, so the three answers are decided by hand. `ORIGINAL_BODY`
      // is what the server rendered into this page, which is the only marker of
      // whether anything here is unsent work.
      const mine = SURFACE.text() !== ORIGINAL_BODY;
      const theirs = text.toString() !== ORIGINAL_BODY;
      if (mine && theirs) {
        // Two edits and no common base — a restored draft against a room that
        // has already moved. Refuse to guess: the room's text is what is in the
        // box, and the draft goes in the conflict report to be pasted back by
        // the person who wrote it.
        const draft = SURFACE.text();
        reflect();
        box.hidden = false;
        box.textContent = 'Somebody is editing this document, and it has moved since your '
          + 'unsaved draft was written. The document is what is in the box now; your draft '
          + 'was:\n\n' + draft;
      } else if (mine) {
        typed();
      } else {
        reflect();
      }
      bound = true;
      // **A surface that can say what changed is asked; one that cannot is
      // recovered from.** The branch is on the capability and never on a name,
      // and each side is the right answer for the surface it is on rather than
      // one being a workaround for the other:
      //
      // * A `<textarea>` reports its whole value and nothing else, so `typed()`
      //   recovers the splice from a common prefix and suffix. That is the path
      //   that has shipped since rooms existed and it is not touched here.
      // * Ace reports its own deltas, with a position and the lines, per edit.
      //   Diffing its value instead would throw that away and buy back the two
      //   measured failures `docs/EDITOR.md` records: `:%s/x/y/g` and
      //   multi-cursor arrive as ONE splice of the whole document, credited to
      //   whoever pressed the key rather than to the characters they typed, and
      //   `typed()` materialises two full code-point arrays per call — 1.90ms on
      //   a 250 KB body, ~1.4s of blocked main thread for one Replace All.
      if (SURFACE.onSplice) SURFACE.onSplice(spliced); else SURFACE.onInput(typed);
      // Where this tab is sitting, and where everybody else's band should be
      // drawn. Four things move a band: the caret moving, the text moving under
      // it, the box scrolling, and the window changing the wrap. Two of those
      // are the surface's own subscriptions and two are the box's, and that
      // split is the boundary rather than an accident — a caret and a document
      // are the surface's, a scroll offset and a window are a box's.
      SURFACE.onInput(drawSeats);
      SURFACE.onCaret(sit);
      SURFACE.onScroll(drawSeats);
      addEventListener('resize', drawSeats);
      sit();
      // **The ground state is the document as you first see it.** Exactly one
      // thing above this line can have left a step on the stack: the `mine`
      // branch's `typed()`, which pushes a restored draft in as one tracked
      // transaction — so without this, the first press of undo throws that draft
      // away in one go. Undo is for what you type from here; the draft banner is
      // the control for the other thing.
      undos.clear();
      // And only NOW does the room own the buttons. `bound` is what makes
      // `reflect()` write to the box, and that write is what makes the native
      // stack untrustworthy; before this line the browser's own is correct.
      ownHistory();
    } else {
      // A reconnection. The document already merged everything typed while the
      // socket was down, so there is nothing to decide.
      reflect();
    }
    // Whatever this tab has that the room has not seen: nothing on a first
    // connection to a room that seeded it, every keystroke made while the socket
    // was down on a reconnection.
    send({t: 'update', u: b64(YJS.encodeStateAsUpdate(doc, raw(message.sv)))});
  }

  function heard(message) {
    if (message.t === 'welcome') return welcomed(message);
    if (message.t === 'update') {
      YJS.applyUpdate(doc, raw(message.u), 'remote');
      // Somebody else's text arrived, so every band below the change is now on
      // the wrong line — including this tab's own idea of where it is sitting.
      drawSeats();
      sit();
      return;
    }
    if (message.t === 'who') {
      names(message.people);
      seats = Array.isArray(message.where) ? message.where : [];
      drawSeats();
      return;
    }
    if (message.t === 'reload') return stop(message.why);
    if (message.t === 'saving') {
      // The shell's banner has to know a write is in the air before it lands:
      // the server announces a commit to the event stream before this socket
      // hears about it, and without this a room commit that nobody pressed
      // arrives as news that a stranger moved the plan.
      writing();
      return;
    }
    if (message.t === 'nothing') {
      // A Save with nothing to commit. The room answers nothing else, and
      // without this the page stayed in `saving` for ever: `settle` never ran,
      // `openproj:wrote` never fired, and the shell's counter never came back to
      // zero — so every "somebody else changed this" banner after it was queued
      // and never drawn. Said only by the tab that pressed the button, because
      // this frame goes to everybody in the room and nobody else asked.
      if (saving) { settle(null); announce('nothing changed'); }
      return;
    }
    if (message.t === 'saved') {
      // Whether this tab is the one that asked, read BEFORE `settle` clears it:
      // the frame goes to everybody in the room, and only the tab that pressed
      // the button should be told anything or have its editor closed.
      const mine = saving;
      if (message.update) YJS.applyUpdate(doc, raw(message.update), 'remote');
      BASE.value = message.commit;
      ORIGINAL_BODY = text.toString();
      // Through the page's own `forgetDraft` and not a bare `remembered.forget`:
      // the room committing this document is one of the three ways a draft stops
      // existing, and a receipt left saying "draft saved 4s ago" over a draft
      // that no longer exists is the counter claiming work is somewhere it is
      // not.
      forgetDraft();
      box.hidden = true;
      settle(message.commit);
      dirty();
      const said = message.outcome === 'merged'
        ? 'saved, and somebody else’s change to this file was merged in'
        : (message.pushed === false ? 'saved here, not yet pushed' : 'saved');
      announce(said);
      // Everybody in the room, not only the tab that pressed the button: this
      // commit holds text that is already in every one of these editors, so the
      // shell's "somebody else changed this" banner is wrong about all of them.
      dispatchEvent(new CustomEvent('openproj:ours', {detail: message.commit}));
      // And the tab that pressed Save leaves edit mode, which is what pressing
      // it means — by reloading, exactly as the path without a room does. Only
      // the tab that asked: everybody else in the room is still typing, and a
      // commit somebody else made is not a reason to close the box in front of
      // you.
      //
      // This used to close the editor without reloading, on the grounds that the
      // document is already what everybody in the room has. That was right about
      // the document and wrong about the page: the read view underneath is HTML
      // the server rendered at the commit this page LOADED at, so the editor
      // closed onto the body as it was and the facts as they were, and it stayed
      // that way until somebody refreshed. The text being in every editor in the
      // room says nothing about the one part of the page that is not an editor.
      if (mine) {
        remembered.set(SAID, said);
        location.reload();
      }
      return;
    }
    if (message.t === 'refused') {
      box.hidden = false;
      box.textContent = message.why;
      settle(null);
      announce('not saved');
    }
  }

  function connect() {
    if (dead || !wanted) return;
    const where = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
      + '/api/coedit/' + encodeURIComponent(FORM.dataset.id);
    try {
      socket = new WebSocket(where);
    } catch (error) {
      return stop('');
    }
    // Which construction this closure belongs to. A session can end and the
    // next one connect before the ended session's socket has delivered its
    // queued events — every one of them is a task, and the reconnect is a click
    // apart — so a socket can speak for a room that has been replaced, or for a
    // session that has ended and not been replaced at all. A stale close must
    // neither wipe the live room's roster nor arm a reconnect BESIDE the live
    // socket (measured before this guard: two open sockets in one tab, one
    // person seated twice); and what is true of the close is true of every
    // frame in flight when the session ended: `heard()` against a landed page
    // is the silent-overwrite family by wire — a stale `update` splices
    // somebody's change into text Escape deliberately kept in the box, a stale
    // `saved` moves `base_commit` and `ORIGINAL_BODY` and drops the draft.
    //
    // Guarded IN the handlers (`opened !== socket || !wanted`) rather than by
    // nulling them at session end: the wiring stays in this one function, and
    // the guard does not rest on the browser's promise that no message follows
    // a close — a promise the suite's hand-driven sockets do not keep, and the
    // `!wanted` half of which nulling would need a second site to cover anyway.
    // `onclose` alone answers for the ended session's own socket, because its
    // settle-and-clear IS that session's cleanup; it stops before the reconnect.
    const opened = socket;
    socket.onopen = () => {
      if (opened !== socket || !wanted) return;
      arrived = true;
      attempts = 0;
      send({t: 'hello', seed: seed, sv: b64(YJS.encodeStateVector(doc))});
    };
    socket.onmessage = event => {
      if (opened !== socket || !wanted) return;
      let message;
      try { message = JSON.parse(event.data); } catch (error) { return; }
      heard(message);
    };
    // Nothing to say here: a failed handshake fires this and then `onclose`,
    // which is where the one decision lives.
    socket.onerror = () => {};
    socket.onclose = event => {
      if (opened !== socket) return;
      settle(null);
      names([]);
      if (dead) return;
      if (!wanted) return;
      // The server said why, so stop and say it. 4000-4999 is the range the
      // protocol reserves for an application, and every code the server sends in
      // it is permanent for this page: the session expired, this login may not
      // write here, the record is gone, two files claim its id. Read as a range
      // and not as a list, so a fifth reason added on the server reaches a tab
      // that shipped before it — see `_SOCKET_REFUSALS` in `web.py`, which is
      // also where it is written down that a refusal has to be *accepted* before
      // it can carry any of this.
      if (event && event.code >= 4000 && event.code <= 4999)
        return stop(event.reason || 'you can no longer edit this — reload the page');
      // A socket that has worked once and then closed is the normal case, not a
      // fault: Cloud Run closes every one of them at five minutes. A socket that
      // has never worked is a deployment without websockets, a proxy that drops
      // the upgrade, or a reader who may not write — and asking it again forever
      // is a red line in the console of a page that is working as designed.
      if (!arrived && attempts >= 4) return stop('');
      // And a ceiling that holds when nobody said anything at all. `arrived`
      // never resets, so the guard above stops covering a tab the moment its
      // first socket succeeds — which is how one tab came to spend 49 hours
      // knocking once a minute, roughly 2,900 refused handshakes, after its
      // session quietly passed 24 hours. `attempts` is only cleared in `onopen`,
      // so this counts consecutive failures rather than a lifetime, and a deploy
      // is still ridden out: ten tries on the schedule below — .5, 1, 2, 4, 8,
      // 16 seconds and then the 30-second cap four times — is about two and a
      // half minutes, which is longer than a Cloud Run revision takes to come up.
      if (attempts >= 10)
        return stop('the connection kept being refused — reload the page to edit again');
      retry = setTimeout(connect, Math.min(30000, 500 * Math.pow(2, attempts++)));
    };
  }

  // --- when a seat is taken --------------------------------------------------
  //
  // At session start, never at script load. `connect()` ran right here, at
  // load, and that was a shipped bug with a cost at both ends of the wire: a
  // signed-in person who merely OPENED a record took a co-editing seat, was
  // listed to everyone else as "also editing", and left the server holding a
  // Room, a `_watch` task and an outbox task per record they visited, kept
  // warm for LINGER_SECONDS after they had gone. The landing list is a page
  // whose whole purpose is opening records; it would have multiplied that.
  //
  // Deferring is safe because nothing above keys off "connected at load": the
  // draft-versus-room arbitration in `welcomed` keys off `ORIGINAL_BODY`, a
  // non-writer is refused at the handshake (and no longer even carries this
  // script), and a non-member learns of moves from the shell's events banner.
  let wanted = false;
  let retry = 0;

  addEventListener('openproj:session', event => {
    if (event.detail && !wanted) {
      wanted = true;
      connect();
    }
    if (!event.detail && wanted) {
      wanted = false;
      // A reconnect armed while the session was open would take the seat back.
      clearTimeout(retry);
      settle(null);
      names([]);
      if (socket) socket.close();
    }
  });
  // A session that began before this script ran, whose `openproj:session` had
  // no listener yet: a restored draft — the one place where landing does not
  // mean sessionless — or a `?edit`/`?both` link, which `_VIEWS` (inlined
  // above) answered at load. The ORDER is the load-bearing half: the restore
  // has already spliced the draft into the surface by the time this line
  // runs, so the room is joined by a page that is visibly holding unsent work
  // and `welcomed` can see two histories and refuse to guess. Restored lazily
  // on the Write press instead, the draft would be spliced in AFTER binding,
  // leave as ordinary typing, and bypass that refusal — the exact class of
  // silent overwrite this branch has shipped three times.
  if (FORM.closest('article.record').classList.contains('editing')) {
    wanted = true;
    connect();
  }
  return {live, save(fields) {
    // Anything typed since the last input event, then one commit over the
    // socket: the fields from this form, the body from the room, one
    // `store.write` against the room's base.
    typed();
    writing();
    announce('saving…');
    send({t: 'save', fields});
  }};
})();
""")
