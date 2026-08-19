# The editor jcanton asked for

Written 2026-08-19, for whoever picks this up in a fresh session. Nothing here is
built. The point of the file is that the next person starts from the decisions
rather than from the search.

## What was asked for

A body editor as close to HackMD's as we can get, in this order of importance:

1. Three views: edit only, edit with live preview, preview only.
2. The buttons along the top of the editor.
3. A full-page interface rather than a resizable text box.
4. Line numbers.
5. Tabs to spaces, and a choice of how many.
6. A vim keymap that can be toggled.
7. Autosave, with the interval settable.

And, added by jcanton in the same breath:

* **Whatever is chosen, the co-editing has to keep working.** Two people, one
  document, one commit — see `coedit.py` and the room in `web.py`.
* **Keep both editors and let a person choose.** The textarea that is there now
  stays as an option; the library one is the other option. This is a preference
  like the theme and the measure, and `remembered` in the shell is where those
  live.
* Keep the hover cards and double-click-to-open, which are not the editor's, but
  say it anyway: nothing about this work should cost them.

## What has to be audited before anything is written

`AGENTS.md` has a section called **Look for it before you write it**, added the
same day and for this reason. The rule is three questions: does something already
do this, can it be vendored under `No npm, no build step, no CDN`, and what does
it cost against what it replaces. Write the answer down in the commit.

The obvious candidate is CodeMirror, and jcanton remembers it being discussed and
turned down without remembering why. **Find out before re-deciding it.** The
likely reason is in the constraint above: CodeMirror 6 is ESM-only and expects a
bundler, which this repository does not have.

That is not the end of the question, because `yjs.bundle.mjs` is already vendored
from `esm.sh` — a prebuilt bundle fetched once at development time and committed
verbatim, with two of its lines rewritten so a `<script>` block can run it. See
`static/VENDOR.md`, which explains that rewrite and why the bytes in git are
still upstream's. Whatever is chosen for the editor can be vendored the same way,
or it cannot; that is the thing to establish first.

What matters for the shortlist:

| candidate | what it gives | the catch to check |
|---|---|---|
| CodeMirror 6 + `y-codemirror.next` | every item on the list; the Yjs binding is the canonical one and brings remote cursors with it | ESM-only, so it needs a prebuilt bundle in the `yjs.bundle.mjs` shape |
| CodeMirror 5 + `y-codemirror` | same list, UMD single file, no bundling | version 5 is in maintenance; the vim addon is a separate file |
| Toast UI Editor | the three views and the toolbar, out of the box | Yjs integration would be ours to write, which is the part that must not break |
| Ace | line numbers, vim, UMD | no maintained Yjs binding |

The one that matters most is the third column of row one: **if the editor brings
its own Yjs binding, the remote-cursor work in `_COEDIT` becomes the library's
job**, including the bands drawn on the line somebody else is editing (added
2026-08-19, see `test_seats.py`). That is a feature to hand over, not to keep
twice.

## What the current editor already does, and must not lose

* **A room, not a socket.** `COEDIT.live()`, `COEDIT.save(fields)`; the socket is
  offered only to somebody the server would accept a write from (`may_write` in
  `web.py`).
* **One Save is one commit**, authored by whoever typed the most, with everybody
  else as `Co-authored-by` (`Room.credits`).
* **A draft survives a reload** — `remembered`, keyed per entity, carrying the
  base commit it was written against.
* **Where everybody is**: a translucent band per person on the line their caret
  is in, with their login on it, hue derived from the name.
* **Escape, Save and Cancel** — Edit at the top of the record, Save and Cancel
  together in the sticky bar, and a save leaves edit mode.
* **The preview is the server's markdown**, through `/api/preview`, because a
  second markdown implementation in JavaScript would eventually disagree with
  the one whose output gets committed. A live preview pane has to keep that
  property or explain why not.
* **`ORIGINAL_BODY` and the conflict box**: a save sends only what changed, and a
  409 lands in its own box rather than in the textarea.

## The trap that is already written down

`tests/js/drive.js` is a DOM shim, not a browser. It has misled three rounds of
this work — see the two `Is the harness itself lying?` rows in `AGENTS.md`. An
editor is layout, selection and key handling; ask it in Chrome
(`tests/browser.py`), not in the shim.

## Where the work would go

`_DETAIL` and `_COEDIT` in `render.py`, the `bodybar` markup, `_DETAIL_STYLE`.
The preference would sit beside the others in the shell's `remembered`.
