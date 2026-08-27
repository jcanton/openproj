"""The page every page is inside: links, policy, nav, and the shared `<head>`."""

from __future__ import annotations

from collections.abc import Sequence

from markupsafe import Markup
from pydantic import BaseModel

from .. import __version__
from ..index import Index
from ..model import Unreadable
from ..themes import FAMILIES
from ..vendor import _font_uri
from .env import _compiled
from .hill import hill_geometry
from .icons import _icon_uri
from .styles import STATUS_SLOTS, _scheme_css
from .tokens import HUMAN, KINDS, PRIORITY_GLYPH, STATUS_GLYPH, STATUSES


class Links(BaseModel):
    """Where the pages point at each other.

    Static output links to sibling files; the server links to routes. Everything
    else about the pages is identical, so this is the only thing that knows which
    mode it is in.
    """

    # The landing list — every record, last edited first. It takes the root
    # name in both modes because it is the page the tool opens on.
    records: str = "index.html"
    # The same list held to one kind each: quick access to what would otherwise
    # be a click on a filter.
    issues: str = "issues.html"
    notes: str = "notes.html"
    table: str = "table.html"
    detail: str = "detail.html"
    graph: str = "graph.html"
    timeline: str = "timeline.html"
    people: str = "people.html"
    # One record's page: prefix, then the id. One `s` from `records` above,
    # which is the list of every record — read the trailing letter before
    # trusting a grep hit on either.
    record: str = "detail.html#"
    new: str = ""  # only the server can create; a rendered file has nowhere to post
    cycles: str = "cycles.html"
    cycle: str = "cycles.html#"  # prefix, then the cycle number
    # Every document this tool ships, on one page. A real file in the export and
    # not an empty string like `new` and `deck` below: the documentation is about
    # the tool rather than about a plan, so it is the same page in both modes and
    # an exported plan that has outlived the service carries its own instructions
    # with it. It is also the reason it can be a nav item at all — a nav link into
    # a file nobody wrote is a dead link on every other page of the export.
    help: str = "help.html"
    # Prefix in front of a repository-relative embed path. Empty in the static
    # export, where a rendered file sits beside the `assets/` and `drawings/`
    # directories it names; `/` when a server is answering for them. It was
    # `asset = "assets/"` while there was one directory to name; `_EMBED_SRC`
    # spells the directory itself now, so this is only the prefix.
    repo: str = ""
    # Prefix, then the record id: where the hover card asks for a shaping
    # document. Empty in the static export, where there is no server to ask — the
    # card draws what the row already carries and the title stays what it always
    # was, a link into `detail.html#id` where the whole document is. Same shape as
    # co-editing falling back to a plain textarea.
    body: str = ""
    # Prefix, then the cycle number. Empty for the same reason `new` is empty:
    # a deck is of ONE cycle, and the static export writes one file per view of
    # the whole plan with nowhere to put the number. Where it is empty the cycle
    # page draws no link to it, rather than a link to a file nobody wrote.
    deck: str = ""


# What a page may do, said once. The server sends it as a header and every page
# carries it in a `<meta>`, because half of them are files with no server to speak
# for them — and two spellings of one policy is two policies.
#
# Passed through `Markup` at the one place it is rendered, so the attribute holds
# the policy and not an escaped copy of it. Autoescape turned every `'` into
# `&#39;`, which a browser does unescape before parsing — so it worked, and the
# page and the header then said textually different things, which is the drift
# this constant exists to prevent. The assertion below is what makes that safe:
# a policy is keywords, schemes and punctuation, and the day one needs escaping
# is the day this stops being true rather than the day it silently breaks.
CSP = (
    "default-src 'none'; img-src 'self' data:; font-src data:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    # Every save is a `fetch` and the live update is an `EventSource`, and both
    # are `connect-src` — which was never listed, so both fell back to
    # `default-src 'none'`. The whole app was readable and could write nothing:
    # a save reported "Failed to fetch", the stream closed on open, and the
    # console said so in a line about a directive nobody had typed. `'self'` and
    # not a host, so it is right on localhost and behind the service URL both.
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'self'"
)
assert not set(CSP) & set('<>&"'), "a policy needing escaping cannot be written verbatim"


STATIC = Links()
ROUTES = Links(
    records="/",
    issues="/issues",
    notes="/notes",
    table="/table",
    detail="/detail",
    graph="/graph",
    timeline="/timeline",
    record="/detail/",
    new="/new",
    people="/people",
    cycles="/cycles",
    cycle="/cycle/",
    help="/help",
    repo="/",
    deck="/deck/",
    body="/api/body/",
)


_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{#- The policy travels with the page, because half the pages this renders are
    files. A header is the server's to send and `openproj render` has no server:
    the static export is opened over `file://`, mailed as an attachment, kept on a
    memory stick, and it carries the whole plan and every vendored library inside
    it. A `<meta>` is the only way to say anything at all in that copy.

    This is the second lock on a door already shut once. A remote image was
    rewritten into a link at render time so a shaping document could not become a
    tracking pixel aimed at everyone who opens it — one function, one spelling of
    one rule. `img-src` closes that door for every spelling, including the ones
    nobody has thought of, and `default-src 'none'` closes the doors nobody has
    named: no fetch, no websocket, no worker, no object, no frame.

    `'unsafe-inline'` for script and style, and it is worth being honest about
    what that costs: it is most of what CSP is famous for. Every library is
    inlined here by design — no npm, no CDN, no build step — so the alternatives
    are a nonce, which a `file://` copy cannot have because there is no response
    to put it in, or hashes for every block on every page, which is a build step
    by another name. What is left is still the part this application needs: the
    network, which is the one thing every page here is asserted never to touch.

    `frame-ancestors` is deliberately absent: it is ignored in a `<meta>`, and a
    directive that silently does nothing is worse than a missing one, because it
    reads as covered. It is sent as a header instead, where it works. -#}
<meta http-equiv="Content-Security-Policy" content="{{ csp }}">
<title>{{ title }}</title>
<link rel="icon" href="{{ icon }}">
<script>
// The only way in and out of a browser store, for every script on every page.
//
// `localStorage` denied does not answer null — it THROWS, and it throws on the
// property itself before any method is called: a private window, blocked
// cookies, a third-party frame, some enterprise policies. Three of the twelve
// reads and writes in this file were wrapped in a try and nine were bare, and
// the bare one at the top of the table's script took the whole table with it —
// the script died before the first row was drawn, so the page in front of
// everybody was a heading and "17 of 17 shown" over nothing at all.
//
// A remembered width, a remembered measure and a remembered theme are all
// conveniences; the rows are the page. So a read answers with its default and a
// write is allowed to do nothing, and no caller has to remember that. Declared
// in the head, before the first paint, because the theme below is the first
// thing that needs it and a function in a later <script> is not hoisted into an
// earlier one.
//
// One door, opened twice, because the same policy denies both stores. The cycle
// page's receipt is the only thing that had ever reached for the second one, and
// it carried a `try` of its own around the read — the same rule written twice,
// which is the shape of every guard this file has watched go missing from one
// copy. The store arrives as a thunk and not as a value: the throw is on the
// PROPERTY, so `door(sessionStorage)` would raise here, in the head, on every
// page, for the exact reader this exists to protect.
const door = reach => ({
  get(key, fallback = null) {
    try {
      const held = reach().getItem(key);
      return held === null ? fallback : held;
    } catch (e) { return fallback; }
  },
  // The one structured thing this app stores is the table's widths, and
  // `JSON.parse` throws on a half-written or hand-edited entry exactly where the
  // bare read did — so the parse belongs behind the same door as the read. A
  // stored value that is not an object is not a map of widths either.
  map(key) {
    try {
      const held = JSON.parse(reach().getItem(key));
      return held && typeof held === 'object' ? held : {};
    } catch (e) { return {}; }
  },
  // Writing throws too, and for a second reason: Safari's private mode reports a
  // quota of zero, so the first setItem raises QuotaExceededError. A width
  // nobody can save is still a width.
  //
  // It answers whether the value stuck, and that is not for the callers that
  // ignore it — a remembered width, measure or theme is a convenience and a
  // caller that had to check would be a caller that has to have an opinion about
  // a refusal it does not care about. It is for the one caller that does: the
  // unsaved draft is the only thing here that git cannot get back, and a receipt
  // reading "draft saved just now" over a store that threw is this application
  // claiming somebody's writing is somewhere it is not.
  set(key, value) {
    try { reach().setItem(key, value); return true; } catch (e) { return false; }
  },
  forget(key) {
    try { reach().removeItem(key); } catch (e) { /* nothing to forget */ }
  },
});

// What this browser keeps: the theme, the palette, the table's widths, a draft.
const remembered = door(() => localStorage);
// What this TAB keeps, and forgets when it closes: the cycle page's receipt, and
// the view a record page was opened from. Per tab on purpose — a record opened
// in a new tab has no origin rather than the one belonging to the tab beside it.
const forThisTab = door(() => sessionStorage);

// Before the first paint, or the page renders light and then turns dark in front
// of whoever chose dark — which is worse than not having the choice.
// A name nothing else on any page uses: this is the global lexical scope every
// classic script shares, and a second `const` of the same name anywhere on the
// page is a SyntaxError rather than a shadowing — the whole page, not one line.
const storedTheme = remembered.get('openproj:theme');
if (storedTheme) document.documentElement.dataset.theme = storedTheme;
// The palette, chosen the same way and applied in the same breath. Stored empty
// means the app's own colours, which is the absence of the attribute rather than
// a scheme named "default" — the whole stylesheet above is written for a page
// with no `data-scheme` on it, and every rule that answers a scheme is one
// specificity step above it.
const storedScheme = remembered.get('openproj:scheme');
if (storedScheme) document.documentElement.dataset.scheme = storedScheme;
</script>
<style>
/* Inlined, not linked: a linked face is one more thing a CDN, a proxy or a train
   tunnel can take away, tests/test_render.py asserts no page reaches the network,
   and the static export has to work from file:// where a relative font URL
   resolves against whatever directory somebody dropped the page in. One variable
   file covers 100..900, so this is 48 KB for every weight the app uses.

   Inter, Copyright 2016 The Inter Project Authors, https://github.com/rsms/inter
   SIL Open Font License 1.1 — full text in static/inter-LICENSE.txt, and the file
   this is the base64 of is static/inter-latin-wght-normal.woff2, checksummed in
   static/SHA256SUMS. The licence obliges the notice to travel with the font, and
   every one of these pages IS a copy of the font: the bytes are in the data: URI
   below, so a page handed to somebody on a memory stick has redistributed it. The
   notice therefore has to be in the page and not only in the repository. */
@font-face {
  font-family: "Inter var";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("{{ font }}") format("woff2-variations");
}
/* Three states, not two: an explicit choice stamps data-theme, and the default
   is no stamp at all, where only the media query separates one from the other.
   Every colour is a token so that nothing has its only definition inside a
   block that half the readers never match. */
:root {
  /* Named, not `light dark`: that means "follow the system", so a page stamped
     dark against a light system kept rendering its buttons, scrollbars and date
     pickers light — the parts of the page the stylesheet does not draw. */
  color-scheme: light;
  --font-sans: "Inter var", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --bg: #ffffff; --fg: #14211f; --surface: #ffffff; --surface-2: #f5f8f8;
  /* --line-strong is the only boundary of every drawn input, button and popup,
     so it is a UI boundary and owes 3:1. It was #b4c3c7 — 1.81:1 — which drew a
     text field as a rumour. Measured against --surface-2 and not the page: a
     bordered control sits on the panel tint as often as on white, and #879398
     was 3.15 on the page but 2.95 there — passing the measurement nobody makes
     against the ground the control is actually on. */
  --line: #dce4e5; --line-strong: #859195; --muted: #5a6b70;
  --accent: #0f5c6b; --on-accent: #ffffff;
  --danger: #9a3327; --warn: #8a5308; --ok: #2f7248;
  /* The em dash that means "no value" is *text*, so it owes 4.5:1 and not the
     3.45 it was first given. Whether a field is empty is a fact, not a hint. */
  --empty: #5f7176; --focus: #0f5c6b;
  /* Five tokens per status, not one. Fill, ink and line draw *shapes* — a graph
     node, a timeline bar. Soft and text draw *chips* — the pill in a table cell,
     which needs a ground light enough to sit inside a row of running text.
     The six fills are a *luminance ladder*, not six hues at one lightness:
     hue is the channel a dichromat loses, and on the graph and the timeline the
     fill used to be the only channel there was. Work gets more solid as it
     advances — done is furthest from the page, parked is nearest — so the order
     survives every kind of colour vision.
     THE LADDER WAS RE-CUT FOR A SIXTH RUNG, and that is the part of this change
     nobody asked for and everybody will see. `thinking` could not be INSERTED
     into it: the four gaps that shipped were 1.280, 1.296, 1.313 and 1.416, and
     splitting even the widest of them leaves two of 1.190 — nearer the 1.11 that
     collapsed the old flat palette into one colour than the 1.27 that worked.
     Nor could a rung be APPENDED: the band is pinned at both ends, by `shelved`
     sitting 1.27 from the page above it and by `done` owing its own ink 4.5:1
     below it, and it spans 3.085 where six rungs at the old 1.27 floor need
     3.304. So the two END colours are exactly as they shipped and the three
     between them were re-spaced — same hue, same chroma, lightness only, scaled
     in linear light so the hue is arithmetically unchanged. Six rungs, five gaps:
     1.2527 is the most this band holds and 1.2520 is what the hexes measure after
     rounding to eight bits. `tests/test_render.py` carries that measurement and
     the floor it sets; see its docstring for why 1.25 is the honest number.
     This theme used to run the ladder the other way, with white ink on every
     fill. White ink is what forced it: an ink that light drags every fill down
     the luminance scale to carry it, and a low-luminance amber is brown while a
     low-luminance green is nearly black. So the light theme now inverts exactly
     as the dark one already did — a tint, dark ink on it, and the value that
     used to BE the fill demoted to its border. --st-X-line is that border, and
     it is not decoration: the faintest fill is 1.27:1 against a white page, so
     the border is the only thing making a pale bar a shape, and it is the token
     that owes the 3:1 a drawn boundary owes. Each one is version 2's fill,
     already measured against this page.
     --st-X-ink is one value on all six here, because a ladder of tints has one
     ink that reads on every rung. Five tokens are kept rather than collapsed to
     one: a status added later may sit somewhere that needs its own.
     `thinking` is a teal because it is the teal it already wore — the hill ball
     and the hill's hover chip painted it `var(--accent)` for as long as it was a
     note's word and not a status, and two hand-written rules further down this
     file said so. This is that colour given a rung of its own, which is what
     lets those two rules go: a word drawn in the interface accent on one page
     and in a status hue on the next is one word with two colours. It is a
     DIFFERENT value from --accent (#0f5c6b) on purpose, near it in hue and far
     from it in lightness, so that a chip is never the same paint as a link. */
  --st-thinking: #a1d6e3; --st-thinking-ink: #101416; --st-thinking-line: #1c8da3;
  --st-thinking-soft: #e9f2f4; --st-thinking-text: #135d66;
  --st-shaping: #bfb2d8; --st-shaping-ink: #101416; --st-shaping-line: #7e61c2;
  --st-shaping-soft: #efedf5; --st-shaping-text: #5e3eaa;
  --st-ready: #7ba8d9; --st-ready-ink: #101416; --st-ready-line: #275e92;
  --st-ready-soft: #ecf1f6; --st-ready-text: #22578a;
  --st-in_progress: #d67c07; --st-in_progress-ink: #101416; --st-in_progress-line: #603a04;
  --st-in_progress-soft: #f7f2eb; --st-in_progress-text: #734f1b;
  --st-done: #2b925e; --st-done-ink: #101416; --st-done-line: #0d311f;
  --st-done-soft: #ecf6f1; --st-done-text: #18633d;
  /* #8a979f, the faintest rung's old fill, is 2.9966 against the page. Nudged
     one step rather than rounded up to the 3.00 it was written down as: the
     border of the palest shape on the page is the last place to spend a
     rounding error. */
  --st-shelved: #e1e5e9; --st-shelved-ink: #101416; --st-shelved-line: #88959d;
  --st-shelved-soft: #eff2f3; --st-shelved-text: #495760;
  /* Kind is drawn in ink, never in hue: two colour languages on one row and
     neither one is read. The hairline is the same boundary every input has —
     written as a reference rather than a second copy of the value, because the
     copy is how a boundary token gets fixed in one place and not the other. */
  --kind-ink: var(--muted); --kind-line: var(--line-strong);
  --sev-blocker: #9a3327; --sev-blocker-soft: #f9e9e6;
  --sev-warn: #8a5308; --sev-warn-soft: #f8eedc;
  /* Where a dragged row would land. Its own token and not `--st-done-soft`,
     which is the same kind of pale green: a status ground borrowed to mean
     something that is not a status is a colour that means two things, and the
     ladder is the one palette on this page that is load-bearing. Green because
     the edge drawn on it is `--ok`, which is the only thing on the page that
     already means "this will work" — and because the two other grounds a row
     can take during a move are the panel tint and the severity fills, neither of
     which may be mistaken for it. */
  --drop: #e2f2e8;
  /* The ground a cycle runs over on the timeline. It was --surface-2, which is
     1.07:1 against the page — a band nobody could see, keyed in the legend by a
     different token again. One token, 1.50:1 against the page in both themes,
     and still light enough to carry an accent-coloured cycle number at 5:1. */
  /* Priority, as five rungs of one ladder — jcanton, 2026-08-20: "lows in green,
     med in yellow, highs in red, darker lighter shades for very low/very high".
     Drawn as signal bars beside the border thickness the graph already uses, so
     the same fact is said twice: colour AND count, which is the bargain status
     already makes with its fill and its glyph. Two channels because one of them
     fails for somebody — thickness is hard to judge without a neighbour to
     compare against, and colour is hard for eight percent of men.
     Related to --ok/--warn/--danger and not equal to them: those three say
     good, careful and broken, and a very-low-priority task is none of those. */
  --pri-very-low: #2f7248; --pri-low: #5d9a4e; --pri-medium: #b07d10;
  --pri-high: #c0532f; --pri-very-high: #9a3327;
  /* The ground under a cell that is waiting on something. Its own token and not
     `--sev-blocker-soft`, which is what a validation blocker wears: those two
     are different facts and a reader who learns one tint for both has learned
     that the plan is broken every time somebody is waiting for a colleague.
     Amber rather than red for the same reason — being blocked is normal. */
  --waiting: #fdf0dd;
  --band: #c3d6de;
  /* Where the pointer is, on a table wide enough to lose your place in.
     **Translucent, and that is the whole design.** Every other tint here is an
     opaque colour because it is the cell's ground and stands for something — a
     blocker, a waiting dependency, a row that can take the one in your hand.
     This one stands for nothing about the record at all; it says only "your
     pointer is here", and it has to be able to say that over any of the others
     without taking their meaning away. So it is a wash rather than a ground, it
     is the ONE token defined once instead of four times, and the reason it can
     be is exactly that: a wash over the theme's own ground is right in every
     theme by construction, where an opaque value would need one per block.
     Derived from `--accent`, so a base16 scheme that redefines the accent moves
     this with it — custom properties substitute at use, not here.
     9%: enough to follow at a glance across fourteen columns, light enough that
     the chips and the severity grounds under it read unchanged. */
  --row-hover: color-mix(in srgb, var(--accent) 9%, transparent);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
    --line: #263336; --line-strong: #61767c; --muted: #93a6aa;
    --accent: #5cb9ca; --on-accent: #0b1214;
    --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
    --empty: #84969c; --focus: #5cb9ca;
    /* The same ladder, climbed the other way: parked is the darkest rung here
       and done the lightest, so a shape is always the *more* solid the further
       the work has got. This theme was already tints under dark ink, which is
       what the light one has now been rebuilt to be.
       Re-cut for the sixth rung like the light one, and for a different reason.
       This band spans 4.748 and six rungs fit in it comfortably, but they do not
       fit BY INSERTION either: the widest gap that shipped was 1.541, which
       splits into two of 1.241. The floor is the whole point of the ladder, so
       the three interior rungs moved rather than the floor — same hues, lightness
       only — and the five gaps are now 1.365, 1.372, 1.361, 1.293 and 1.442.
       Neither end moved: `shelved` is pinned by owing this page 3:1 and `done` is
       the lightest a fill gets. `thinking` sits one rung in from `shelved` and is
       lifted a little off the even cut, because on the even cut #101416 reads
       4.57 on it and 4.5 is a floor to clear rather than to graze. It costs the
       gap above it, 1.361 down to 1.293, and pays the gap below, 1.361 up to
       1.442 — both still clear of 1.25, and the ink now reads 4.81.
       --st-X-line here is not the fill's own value. It could have been — every
       fill already clears 3.23:1 against this ground, so nothing needs the
       border for separation. But the graph draws PRIORITY as border *width*,
       and a border the colour of the box it surrounds is a width nobody can
       read: high and low priority would differ only by the size of the node.
       So each border is the contrast midpoint between its own fill and the
       page — the same ratio either side, which is the most an edge can be worth
       when it has to read against both. `shelved` gets 1.79 and 1.81 because
       its fill is only 3.23 from the ground and there is no more room there, and
       `thinking` gets 2.15 and 2.17 for the same reason one rung up.
       --st-shelved-ink stays white. The brief that inverted the light theme
       said this one clears 6.03:1 on #101416 and could join the others; it is
       3.34:1, and this ink is the node's label and the bar's glyph, which is
       text and owes 4.5. Lifting the fill instead would put it 1.07 from its
       neighbour and collapse the bottom of the ladder — and that neighbour is
       `thinking` now, not `shaping`, which is the one thing the sixth rung
       changed about this paragraph. */
    --st-thinking: #448c99; --st-thinking-ink: #101416; --st-thinking-line: #26555d;
    --st-thinking-soft: #182e33; --st-thinking-text: #60becd;
    --st-shaping: #a286e3; --st-shaping-ink: #101416; --st-shaping-line: #5e4d86;
    --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
    --st-ready: #80b4e7; --st-ready-ink: #101416; --st-ready-line: #456381;
    --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
    --st-in_progress: #fbc376; --st-in_progress-ink: #101416; --st-in_progress-line: #84653b;
    --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
    --st-done: #d7f4e6; --st-done-ink: #101416; --st-done-line: #6a7972;
    --st-done-soft: #1d372b; --st-done-text: #5cce97;
    --st-shelved: #5e6a73; --st-shelved-ink: #ffffff; --st-shelved-line: #3c4449;
    --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
    --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
    --sev-warn: #d9a557; --sev-warn-soft: #332409;
    --drop: #1e3a2b;
    --pri-very-low: #6fc095; --pri-low: #8fc772; --pri-medium: #d9a557;
    --pri-high: #e08a5a; --pri-very-high: #e0796a;
    --waiting: #34291a;
    --band: #2a3941;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #11181b; --fg: #dde6e7; --surface: #171f22; --surface-2: #1c262a;
  --line: #263336; --line-strong: #61767c; --muted: #93a6aa;
  --accent: #5cb9ca; --on-accent: #0b1214;
  --danger: #e0796a; --warn: #d9a557; --ok: #6fc095;
  --empty: #84969c; --focus: #5cb9ca;
  --st-thinking: #448c99; --st-thinking-ink: #101416; --st-thinking-line: #26555d;
  --st-thinking-soft: #182e33; --st-thinking-text: #60becd;
  --st-shaping: #a286e3; --st-shaping-ink: #101416; --st-shaping-line: #5e4d86;
  --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
  --st-ready: #80b4e7; --st-ready-ink: #101416; --st-ready-line: #456381;
  --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
  --st-in_progress: #fbc376; --st-in_progress-ink: #101416; --st-in_progress-line: #84653b;
  --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
  --st-done: #d7f4e6; --st-done-ink: #101416; --st-done-line: #6a7972;
  --st-done-soft: #1d372b; --st-done-text: #5cce97;
  --st-shelved: #5e6a73; --st-shelved-ink: #ffffff; --st-shelved-line: #3c4449;
  --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
  --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
  --sev-warn: #d9a557; --sev-warn-soft: #332409;
  --drop: #1e3a2b;
  --band: #2a3941;
  --pri-very-low: #6fc095; --pri-low: #8fc772; --pri-medium: #d9a557;
  --pri-high: #e08a5a; --pri-very-high: #e0796a;
  --waiting: #34291a;
}
{{ schemes }}
/* WHAT SIXTEEN COLOURS BECOME.
   ------------------------------------------------------------------------
   One derivation for every scheme, which is the whole point: a base16 palette
   is sixteen values and this app draws with fifty-five, so the other thirty-nine
   are made here, once, out of those sixteen. Twenty palettes and one mapping,
   not twenty palettes and twenty mappings — and a scheme added later is sixteen
   numbers in `themes.py` and nothing else.

   `color-mix` is what makes that possible. A chip needs a soft ground under
   coloured text, a node needs a fill pale enough to read a title on, and none of
   those exist in a palette meant for a terminal — but all of them are the hue
   and the background in some proportion. Mixed in oklab and not in sRGB, where
   a yellow mixed toward a dark background goes through a muddy green.

   Specificity: this is (0,2,0), the same as `:root[data-theme="dark"]` above it,
   so it wins by coming after. That is deliberate and it is why this block is
   here rather than beside the other palettes.

   The three values a palette cannot be trusted to place — the ink, the secondary
   ink and the link colour — are chosen per palette by contrast and written into
   the block above (see `_chosen`). Everything below is the same arithmetic for
   all of them. */
:root[data-scheme] {
  --bg: var(--base00);
  --surface: var(--base00);
  --surface-2: var(--base01);
  --line: var(--base02);
  --line-strong: var(--base03);
  --on-accent: var(--base00);
  --danger: var(--base08);
  /* base09, the orange, and not base0A: a warning is read as text on the page,
     and a yellow on a light ground is the one hue in the format that reliably
     is not. */
  --warn: var(--base09);
  --ok: var(--base0B);
  --empty: var(--muted);
  --focus: var(--accent);
  --sev-blocker: var(--base08);
  --sev-blocker-soft: color-mix(in oklab, var(--base08) 14%, var(--bg));
  --sev-warn: var(--base09);
  --sev-warn-soft: color-mix(in oklab, var(--base09) 14%, var(--bg));
  --drop: color-mix(in oklab, var(--base0B) 18%, var(--bg));
  --band: color-mix(in oklab, var(--base0C) 30%, var(--bg));
  --waiting: color-mix(in oklab, var(--base09) 18%, var(--bg));
  /* The ladder the meter counts: green, green-yellow, yellow, orange, red. `low`
     is a mix because the format has no slot between green and yellow, and five
     rungs drawn in four hues is a rung nobody can name. */
  --pri-very-low: var(--base0B);
  --pri-low: color-mix(in oklab, var(--base0B) 55%, var(--base0A));
  --pri-medium: var(--base0A);
  --pri-high: var(--base09);
  --pri-very-high: var(--base08);
}
/* A status is a hue, and each one arrives four times: the fill a node or a bar
   is drawn with, the border round it, the soft ground a chip sits on, and the
   ink the chip's word is written in.

   The fill is a TINT and not the hue itself. A saturated red bar wants white
   text and a saturated yellow one wants black, so a single ink token cannot
   serve both — mixed halfway into the background, every fill keeps the ground's
   polarity and the page's own foreground reads on all five. */
{% for status, slot in status_slots %}
:root[data-scheme] {
  --st-{{ status }}: color-mix(in oklab, var(--{{ slot }}) 32%, var(--bg));
  --st-{{ status }}-ink: var(--fg);
  --st-{{ status }}-line: var(--{{ slot }});
  --st-{{ status }}-soft: color-mix(in oklab, var(--{{ slot }}) 16%, var(--bg));
  --st-{{ status }}-text: color-mix(in oklab, var(--{{ slot }}) 38%, var(--fg));
}
{%- endfor %}

/* cv05 gives the l a tail, so l/1/I are three shapes in a login; ss03 fixes the
   spacing of the curly quotes and slashes that PR refs and paths are full of. */
/* A column, so the footer sits at the bottom of the WINDOW on a page too short
   to reach it and at the bottom of the CONTENT on a page that is not. jcanton,
   2026-08-25: the People page has no footer at the foot of the window at all and
   "the timeline page which is shorter vertically, moves it upwards instead of
   having it fixed at the bottom".

   `min-height` and never `height`: a fixed height would make every long page
   overflow its own body, which is the scrollbar this whole line of work has been
   about. `100dvh` because a phone's toolbars come and go and `100vh` is the tall
   reading, which puts the footer under them.

   The fill is `#main`'s `flex: 1 0 auto` below, not a margin on the footer: a
   `margin-top: auto` would push the footer down and leave `<main>` measuring
   whatever its content happens to be, and `--room` is computed from the space
   below the box it fills. Growing MAIN keeps that arithmetic about the same box
   the reader sees. */
body { font-family: var(--font-sans); font-size: 14px; line-height: 1.5;
       font-feature-settings: "cv05" 1, "ss03" 1;
       margin: 0; padding: 1rem 1.25rem 3rem;
       min-height: 100dvh; box-sizing: border-box;
       display: flex; flex-direction: column;
       background: var(--bg); color: var(--fg); }
/* `min-height: 0` beside the grow, because a flex item's automatic minimum is
   its content: without it a page whose main is taller than the window refuses to
   shrink and the two rules fight, which is a scrollbar of its own. */
#main { flex: 1 0 auto; min-height: 0; }
/* Wraps, because the corner grew a third control and a nav that cannot wrap is a
   nav that pushes the whole page sideways instead: at 500px the row came out
   587px wide and every page under it scrolled horizontally. */
nav { display: flex; flex-wrap: wrap; gap: .35rem 1rem; margin-bottom: 1rem;
      font-size: 13px; align-items: center; }
/* Every link, not only the nav. The browser's default blue and its visited
   purple are both close to unreadable on a dark ground, and a link is the most
   clicked thing on every one of these pages. */
a, a:visited { color: var(--accent); }
/* The nav is the one row on the app where every word is already a link, so the
   accent buys nothing there — six accent words said "six links" and left the one
   you are standing on no colour to be. Underlined and in --muted they still read
   as links (5.57:1 on the light page, 7.07:1 on the dark one: text contrast, not
   a hint), and the accent is freed to mean "here".

   `nav a:visited` and not `nav a` alone. The rule above is `a, a:visited`, and
   `a:visited` weighs (0,1,1) against a bare `nav a`'s (0,0,2) — so every nav link
   a reader had already clicked would have stayed in the accent while the rest
   went muted, which is a highlight that means "visited". */
nav a, nav a:visited { color: var(--muted); }
/* Where you are: weight, colour and a box, all three. Colour alone is not a
   signal this app accepts anywhere else — the status ladder is a luminance ramp
   and a glyph for the same reason — and the nav is the one component every page
   carries.
   Quiet on purpose. --surface-2 is 1.07:1 against the light page and 1.16:1
   against the dark one, so the ground is a whisper and the accent hairline is
   what makes it a box; a filled --accent chip across the top of every page would
   be the loudest thing on a screen full of data. 13px of chrome, not a tab bar.
   Drawn from the attribute a screen reader reads, so the two cannot disagree:
   there is no `.current` class to fall out of step with it.
   The `:visited` twin is not decoration either — it is (0,2,2) against
   `nav a:visited`'s (0,1,2), which settles the fight by weight instead of by
   which rule happens to be written last.
   The padding does not make the row taller. Measured in Chrome, not reasoned
   about: the box is 24.69px against a sibling's 19.5, and the nav is 28 either
   way because the theme toggle is a 28px circle and it is the tallest thing in
   the row. Giving a row of space back at the heading and taking it again here
   would be the change undoing itself, so a test measures this too. */
nav a[aria-current="page"], nav a[aria-current="page"]:visited {
  color: var(--accent); font-weight: 600; text-decoration: none;
  background: var(--surface-2); border: 1px solid var(--accent);
  border-radius: 3px; padding: .1rem .45rem; }
/* The page's own name. Four of the six pages had no heading at all, which leaves
   a screen reader with nothing to say the page IS and a skip link with nowhere
   to land. Sized down from the browser's 2em: these are dense pages and the
   heading is a signpost, not a banner. */
h1 { font-size: 1.35rem; margin: .2rem 0 .6rem; }
/* The first stop in the tab order, drawn only once it is reached. Between the
   nav and the content of the table page sit fourteen sort buttons and ten
   dropdowns, and walking them on every visit is what a skip link exists to
   spare. `<main>` carries no tabindex: following a fragment moves the sequential
   focus starting point to the target on its own, and a tabindex there would put
   `main` in the focus-ring rule below — a 2px outline round the whole page. */
.skip { position: absolute; left: .5rem; top: -3rem; z-index: 50;
        background: var(--surface); color: var(--fg); font-size: 13px;
        border: 1px solid var(--line-strong); border-radius: 3px;
        padding: .35rem .6rem; text-decoration: none; }
.skip:focus { top: .5rem; }
/* Announced, not drawn. `display: none` and `visibility: hidden` both take an
   element out of the accessibility tree, so a live region that must stay
   readable to a screen reader and invisible to everybody else is clipped.

   Every nav view's heading wears this — each was the single word already
   sitting in the nav two rows above it. The nav now says which page
   you are on in the item it lights, so on screen that heading was a row of space
   spent saying nothing new. It stays in the document because a page with no
   top-level heading cannot be announced by name, cannot be found in a heading
   list, and leaves the skip link nowhere to land — the fix round six made, which
   this must not undo.

   A heading that names what you are looking at rather than which route you are on
   is not clipped and is not here: a record's own title, a cycle's number, the
   listing of the whole plan, and the create form, whose nav item does not exist
   and whose heading is therefore the only thing on it that says what it makes.

   Nothing in this comment quotes a heading or a control by its exact words. The
   stylesheet is inlined into every page, so a phrase written here is a phrase in
   the served bytes of all eight of them, and two tests that search a page for the
   copy of a control it must not offer found it in this block instead. */
/* The scheme picker, sized to the corner it stands in rather than to the control
   bars: it is the only select on the page that is not a filter, and at the
   filters' size it read as one more thing to answer. */
.schemepick select { font-size: 12px; padding: .1rem 1.4rem .1rem .4rem;
                     background-position: right .3rem center; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
           overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
/* The right end of the nav, as one group rather than two things each pushing
   themselves over. The toggle asked for `margin-left: auto` on its own and was
   the only thing out there; with the identity beside it, two auto margins split
   the free space and put the pair in the middle of the row. */
/* And the corner itself wraps and gives: three controls at their natural widths
   are wider than a phone, and the picker is the one with room to lose — a
   `<select>` is as wide as its longest option, which here is a scheme nobody has
   chosen. */
.corner { margin-left: auto; display: flex; flex-wrap: wrap; align-items: center;
          gap: .4rem .6rem; min-width: 0; }
/* The build row, and its separators. A flex row so the phone rule below — which
   moves the corner in here — is the same layout with a different gap rather than
   a second one, and so the whitespace between the items is a whitespace-only
   text node in a flex container, which is not a flex item and draws nothing.

   The dot is `::before` on every item but the first, which is what makes it
   disappear along with whatever it was separating: `#planhead` is filled by the
   health poll and is empty until it answers, `:empty` takes it out of the flow,
   and a rule that matched siblings by position would then draw a dot with
   nothing on either side of it. `.corner` is excluded because it is a group of
   controls the phone rule parks here and not a fact about the build. */
/* A mermaid block, in the two states it has. Before the bundle arrives — and for
   ever if it never does — the element is showing the diagram's source, and it is
   drawn as the code block it would otherwise have been, so a reader gets the same
   thing the static export gives them rather than a bare wall of text that looks
   like a rendering fault. Mermaid stamps `data-processed` on the element it has
   drawn into, which is what switches the box off.

   In the shell and not in a page's own sheet, because a fence can be in any
   document this app draws: a record's body, the preview beside it, a deck slide,
   and the Help page. Written once, where every one of them already is. */
pre.mermaid { background: var(--surface-2); padding: .6rem .7rem; border-radius: 3px;
              overflow-x: auto; margin: 0 0 1rem; }
pre.mermaid[data-processed] { background: none; padding: 0; overflow-x: auto;
                              text-align: center; }
/* No `max-width` rule here, and that is a measurement rather than an oversight.
   The obvious one — `svg { max-width: 100% !important }`, to outrank mermaid's
   own inline style — was written, and then removed when taking it away changed
   nothing: mermaid's `useMaxWidth` default writes `max-width: <computed>px` and
   `width: 100%` onto the `<svg>`, so a drawing laid out at 716px comes out 460 in
   a 460px column on its own. A rule that does nothing is a rule the next person
   has to work out the purpose of.

   `overflow-x` above is what is left, and it is for the case mermaid does not
   cover: a diagram type that turns `useMaxWidth` off draws at its own size, and
   then the box scrolls rather than the page. */
pre.mermaid[data-processed] svg { height: auto; }
/* What a failed load leaves behind, so raw mermaid source is not mistaken for the
   page working. Drawn by the loader, which is the only thing that knows. */
.mermaidwhy { color: var(--muted); font-size: 12px; margin: -.7rem 0 1rem; }
#build { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem .5rem; }
/* The character itself, and never the CSS escape `\\00B7`. This stylesheet is a
   Python triple-quoted string, so a backslash in it is a PYTHON escape first:
   `\\0` is octal, and the rule shipped a NUL byte followed by the text `B7`.
   Chrome read that as the escape for U+0000 — which CSS replaces with U+FFFD —
   and drew a replacement glyph and two literal characters between the version
   and the plan's sha, on every page of the app. Found by looking at the footer,
   not by reading the rule. */
#build > * + *::before { content: "·"; margin-right: .5rem; }
#build > .corner::before { content: none; }
#planhead:empty { display: none; }
.schemepick { min-width: 0; }
.schemepick select { max-width: 100%; }
#who { display: flex; align-items: center; gap: .5rem; color: var(--muted); }
#who form { margin: 0; }
/* A sign-out that looks like the link it behaves as. It is a POST because a
   GET that ends a session is a session ended by anything that prefetches. */
#who button {
  background: none; border: 0; padding: 0; font: inherit;
  color: var(--muted); text-decoration: underline; cursor: pointer;
}
#who button:hover, #who a:hover { color: var(--accent); }
#who .warn { color: var(--warn); }
#theme {
  width: 28px; height: 28px; border-radius: 50%;
  border: 1px solid var(--line-strong); background: var(--surface); color: var(--fg);
  /* The glyphs are small inside their em box — the sun especially — so the box
     is grown until the drawing fills the button rather than floating in it. */
  font-size: 19px; line-height: 26px; cursor: pointer; padding: 0;
  display: flex; align-items: center; justify-content: center;
}
#theme:hover { border-color: var(--accent); color: var(--accent); }
.derived { color: var(--muted); font-variant-numeric: tabular-nums; font-style: italic; }
/* How much window is left for the one box on a page that is meant to fill it —
   the graph's canvas, the table's rows, the timeline's plot. The number itself is
   measured in JS, because it is a fact about the rows above the box and the bar
   below it and a stylesheet can see neither: `#cy` asked for `78vh`, a fraction
   of the window that knows about neither, and at an 806px window 140px of the
   canvas ran under the sticky commit bar with two nodes loading hidden. The
   declaration here is only what stands until the measurement lands — the same
   guess `.table-scroll` used to carry, with the same floor under it that
   `measureRoom` applies, so the page before the measurement looks like the page
   after it. */
:root { --room: max(9rem, calc(100vh - 15rem)); }
/* 3rem of quiet under the last line of a document. A page whose one box is
   measured to the window has no last line — the box ends where the window does —
   so that 48px is not breathing room, it is drawing that never happens. */
body:has([data-fills]) { padding-bottom: 1rem; }
/* The measurement is of the room the box gets, so the box has to be that size
   including its own frame. On content-box a 1px border makes it 2px taller than
   the room it was handed, which is exactly enough to put the page into the
   scrollbar it was sized to avoid — and the graph's canvas and the timeline's
   plot are both bordered. */
[data-fills] { box-sizing: border-box; }
#controls { margin: .75rem 0; }
/* The search box, and at the far end of the same line whatever the page has to
   say ABOUT the view rather than to it. The graph put its pan/zoom sentence on a
   row of its own and its count on another: six rows of furniture left 268px of an
   806px window for the graph. A sentence beside the search box costs no rows. */
#controls .searching { display: flex; flex-wrap: wrap; align-items: baseline;
                       gap: .35rem 1.5rem; }
#controls .aside { text-align: left; }
/* The slot holds a `<p>`, which arrives with the browser's own margin and would
   make the search row a line taller than the box in it. */
#controls .aside > * { margin: 0; }
#controls .facets { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: baseline;
                    margin-top: .5rem; }
/* The fold's handle, and above 40rem there is nothing to fold: the `<details>`
   ships `open` and stays open, so a summary here would be a control that says
   "Filters" over filters that are already on the screen. `display: none` on a
   summary does not close its details or hide the content — only the marker and
   the word go. The phone block near the foot of this sheet is where it comes
   back, and it is the only thing that ever closes the box. */
#controls .facetbox > summary { display: none; }
.facet { position: relative; font-size: 11px; color: var(--muted);
         text-transform: uppercase; letter-spacing: .04em; }
/* The closed control. It used to be a `<select>` and it still has to read as one
   — this bar has ten of them and a row of buttons that look like buttons reads as
   ten things to press rather than as the state of a filter. */
.facetopen {
  display: flex; align-items: baseline; gap: .35rem;
  font: inherit; color: inherit; letter-spacing: inherit;
  background: none; border: 0; padding: 0; cursor: pointer; text-align: left;
}
.facetopen .facetsaid {
  /* A dropdown and not a text box. The border alone reads as somewhere to type —
     which is what the bar looked like once the `<select>`s became buttons — so
     the caret the browser draws on a real `<select>` is drawn here instead, in
     the same place and pointing the same way. Two borders and no background,
     because a triangle drawn from borders is one element and needs no image, no
     glyph and nothing fetched. */
  display: inline-flex; align-items: center; gap: .35rem;
  font-size: 13px; text-transform: none; letter-spacing: 0; color: var(--fg);
  border: 1px solid var(--line-strong); border-radius: 3px; padding: .1rem .35rem;
  background: var(--surface);
  /* Wide enough for `all` plus the room a value will need, and no wider: ten of
     these on one line is the bar's whole budget, and at 5rem the tenth field
     wrapped to a second row — which costs the drawing below it more than the
     control gains. */
  min-width: 3.5rem;
}
/* What is set, in the ink the rest of the page uses for a choice somebody made.
   Without it a bar with three fields filtered looks exactly like a bar with
   none, which is how a reader comes to believe a plan has four rows in it. */
/* The caret. `margin-left: auto` so it sits at the right edge of a control that
   is wider than its word, which is where a `<select>` puts it. */
.facetopen .facetsaid::after {
  content: ""; margin-left: auto; width: 0; height: 0;
  border: 4px solid transparent; border-top: 5px solid currentColor;
  /* The triangle's own box is 9px tall and its ink is the bottom 5, so it sits
     low without this. */
  transform: translateY(2px);
}
/* Open: the caret turns over, which is the one thing that says a press did
   something on a control whose menu may be off the bottom of a short window. */
.facetopen[aria-expanded="true"] .facetsaid::after {
  border-top-color: transparent; border-bottom: 5px solid currentColor;
  transform: translateY(-2px);
}
.facetopen[aria-expanded="true"] .facetsaid,
.facet.chosen .facetsaid { border-color: var(--accent); color: var(--accent); }
/* The open list. Absolutely positioned so opening one does not push the drawing
   below it down the page — on the graph and the timeline that is a relayout of
   the whole view — and capped in height because `tags` on a real plan is forty
   values and a menu the length of the page is a menu you scroll the document
   for.

   z-index 12 clears everything a menu can open over. Its own page's furniture is
   the small half — the table's header is 3, the frozen pair 4, the drop label 5,
   the graph's key 5 — and the one that actually covered it is the COMMIT BAR,
   which is sticky at 10 on every page that can be edited. On the graph that is
   the row holding "Edit dependencies", and a filter menu opened over it lost its
   middle rows to a button: the labels above and below were the menu's, the ones
   behind the bar were the bar's. jcanton, 2026-08-21.

   Below the hover card at 20 and the drag ghost at 40, both of which follow the
   pointer and should pass over an open menu rather than under it. */
/* `:not([hidden])` on the display, and it is not decoration: the browser's own
   `[hidden] { display: none }` is (0,1,0) in the UA sheet, and ANY author rule
   setting `display` beats it. Without this every menu on the bar is open the
   moment the page loads — which is what shipped for ten minutes, over the plan
   it is meant to filter. `#unparent` two hundred lines down settles the same
   question the same way and says so; this is the second time. */
.facetmenu:not([hidden]) {
  position: absolute; z-index: 12; top: 100%; left: 0; margin-top: .2rem;
  max-height: 15rem; overflow-y: auto; min-width: 100%;
  display: flex; flex-direction: column; gap: .1rem;
  padding: .3rem; background: var(--surface); border: 1px solid var(--line-strong);
  /* The same shadow the combobox and the icon picker float on. A literal
     rather than a token because there is no shadow token: the three popups
     on this site are the only things that lift off the page. */
  border-radius: 3px; box-shadow: 0 4px 14px rgba(0,0,0,.12);
}
.facetmenu label {
  display: flex; align-items: baseline; gap: .35rem; white-space: nowrap;
  font-size: 13px; text-transform: none; letter-spacing: 0; color: var(--fg);
  padding: .1rem .2rem; cursor: pointer;
}
.facetmenu label:hover { background: var(--surface-2); }
/* `.facet` is also the label a plain `<select>` wears elsewhere — the timeline's
   window, the cycle page's three settings.
   Those are one-of-several questions with one answer, so they stay selects, and
   this is the rule that dresses them. */
.facet select { display: block; font: inherit; font-size: 13px; text-transform: none;
                letter-spacing: 0; color: inherit; }
#q { font: inherit; font-size: 13px; padding: .15rem .3rem; min-width: 16rem; }
/* The hover card, on every page, because it is one component drawn by three
   views. Follows the pointer and takes no pointer events of its own, so it never
   becomes the thing under the cursor — which on the graph would mean a card that
   fights the node it describes.
   `position: fixed` so a card on the graph survives the canvas being panned and
   zoomed under it: the anchor moves, the card is placed again from the pointer,
   and neither is inside the transformed layer. */
/* No `pointer-events: none`. The card holds a shaping document that is capped
   and scrollable, and a box the pointer passes straight through is a scrollbar
   nobody can grab — which is exactly what shipped. It does not follow the
   pointer either: it is placed once, where the pointer was when it opened, and
   the gap to it is crossable because leaving the row only starts a timer. */
#card { position: fixed; z-index: 20; max-width: 26rem;
        background: var(--surface); color: var(--fg); font-size: 12px;
        border: 1px solid var(--line-strong); border-radius: 3px;
        padding: .4rem .55rem; box-shadow: 0 4px 14px rgba(0,0,0,.12); }
#card[hidden] { display: none; }
#card .card-title { margin: 0; font-size: 13px; font-weight: 600; }
#card .card-chips { margin: .25rem 0 .35rem; }
#card dl { display: grid; grid-template-columns: auto 1fr; gap: 0 .6rem; margin: 0; }
#card dt { color: var(--muted); font-size: 11px; text-transform: uppercase;
           letter-spacing: .04em; }
#card dd { margin: 0; }
#card .num { font-variant-numeric: tabular-nums; }
#card .guess { color: var(--muted); font-style: italic; }
#card .card-why { margin: .35rem 0 0; color: var(--muted); font-style: italic; }
/* The shaping document. Capped and scrollable rather than as long as it is: a
   900-word pitch drawn in full covers the table it was opened from, and the card
   is a look rather than a read — the title is still a link to where the document
   is read properly. Scrollable and not clipped, because a card that ends
   mid-sentence with no way to see the rest reads as a broken card.
   The cap is in `em` so it is a number of LINES rather than a number of pixels. */
/* 8em, and it has been 12 and then 11: the card gained a Progress row when the
   table's column gave up its count, and then a hill on its chip line. The whole
   box has to stay under half the window — a card that covers the table it was
   opened from has to be dismissed before the plan can be read again, which is
   what `test_a_nine_hundred_word_document_does_not_cover_the_table` measures.
   One line of facts is paid for with one line of document, and the hill is drawn
   beside the status chip rather than under it so that it costs two rather than
   the five a row of its own would have. 9em cleared the cap by six pixels, which
   is not a margin — it is the same number twice with a rounding between them. */
#card .card-body { margin: .4rem 0 0; padding-top: .35rem; max-height: 8em;
                   overflow-y: auto; border-top: 1px solid var(--line); }
#card .card-body > :first-child { margin-top: 0; }
#card .card-body > :last-child { margin-bottom: 0; }
#card .card-body :is(h1, h2, h3, h4) { font-size: 12px; margin: .5rem 0 .2rem; }
#card .card-body p, #card .card-body ul, #card .card-body ol { margin: .2rem 0; }
#card .card-body pre { overflow-x: auto; }
#card .card-body img { max-width: 100%; }
/* A checklist, and the one markdown-body rule in this stylesheet that is not
   scoped to a view. Every other copy of "how a rendered document looks" is
   written three times on purpose — the card here, `.doc` in `_SUGGEST_STYLE`,
   `.slide .doc` in the deck — because each is a different size of the same
   prose. This is not that: without it a task list carries a bullet AND the box
   the renderer drew, on every page that shows a body, and the correction is the
   same two declarations whichever page it is. So it is written once, unscoped,
   against the classes the renderer itself emits. `list-style: none` and a negative
   indent rather than `padding-left: 0`, so the boxes line up with the bullets of
   an ordinary list beside them instead of hanging a character to their left. */
li.task-list-item { list-style: none; margin-left: -1.1em; }
li.task-list-item input { margin-right: .35em; }
.hint { color: var(--muted); font-size: 12px; }
.empty { color: var(--empty); }
.num { font-variant-numeric: tabular-nums; }
/* The hill. One drawing, two sizes, and no token of its own: the curve wears the
   rules' colours and the ball wears the status ladder's, so the picture obeys the
   luminance ladder every other view already uses rather than inventing a hue that
   would be right in one theme block and wrong in the two nobody looks at.
   In the shell and not beside the detail page's stylesheet, because the card
   draws one too and the card is drawn from here on the table, the graph and
   the timeline. */
/* A `<span>` rather than a `<div>`: the read view puts this inside the
   `<span class="read">` every fact row wears, and a block element in there is
   content a parser is entitled to do anything with. */
.hill { --ball: 17px; --ghost: 9px; display: block;
        position: relative; width: 100%; max-width: 15rem; aspect-ratio: 120 / 48; }
/* The control hill follows `.field`'s rule without wearing `.field`: the class
   brings every `.field` rule with it, not only the display toggle — on the
   record pages it also brought a `#facts .field { max-width: 28rem }`, twice
   the width this drawing wants — so the toggle is mirrored in two lines here
   instead of one word in the class list.
   `.hill-control` and not `[role=radiogroup]`, which is what this was: a promoted
   note's hill is still the control in its row, and it has no stops to press
   because `promoted` is derived — so it was the one hill in the app that never
   hid, and that note drew two hills at once, one under the other. What an element
   is FOR is not the same question as whether anything on it can be pressed. */
.hill-control { display: none; }
.record.editing .hill-control { display: block; }
/* A drawing has no text in it and so no baseline of its own, and the record
   pages' facts list aligns its rows on one (`#facts { align-items: baseline }`).
   The label for a hill was therefore hung off the BOTTOM of the picture, a
   hundred pixels below the row it names. The row that holds a hill aligns at the
   top instead — `:has` rather than a class on the `<dt>`, because the two facts
   lists that draw one are built by two different templates and a class would
   have to be remembered in both. */
dt:has(+ dd .hill) { align-self: start; }
/* `overflow: visible`, so a round cap at the foot of the hill is drawn rather
   than sliced off flat by the viewBox it sits exactly on. */
.hill svg { display: block; width: 100%; height: 100%; overflow: visible; }
/* `non-scaling-stroke` so the line is the same weight in a facts column and in a
   card, and — the reason it is load-bearing rather than taste — so that the lift
   below can be exact. The ball is lifted by its own radius plus half the line's
   width; a stroke that scales with the viewBox has a different painted half-width
   at every size, so the ball would rest on the line at one width and be buried in
   it at another. Non-scaling makes `stroke-width: 2` mean two painted pixels
   everywhere, and half of it a constant this stylesheet can add. */
.hill-line, .hill-ground { fill: none; stroke-linecap: round;
                           vector-effect: non-scaling-stroke; }
/* Round and unhurried is the whole of the cartoon: no filter, no gradient,
   nothing that needs a second definition per theme. 2 and not the 2.5 it was —
   jcanton, 2026-08-22, and the thinner line also leaves the ball as the heaviest
   thing in the drawing, which is what a reader should be looking at. */
.hill-line { stroke: var(--line-strong); stroke-width: 2; }
.hill-ground { stroke: var(--line); stroke-width: 1.25; }
/* Lifted along the outward normal, so the ball RESTS on the line instead of
   being run through by it — a stop is a point ON the curve, and a ball centred
   on that point is half buried in the hill.
   The lift is in painted pixels and the direction is a unit vector, which is the
   only combination that is right at every size: the ball is an HTML element sized
   in px so that it can carry a real radio, and the drawing is a viewBox that
   scales with the column it is in. A lift written in viewBox units would be
   correct at exactly one width. `--ny` defaults to straight up, which is the
   answer on level ground and the right answer for anything that forgets to say. */
.hill-ghost, .hill-ball, .hill-stop {
  position: absolute; border-radius: 50%;
  transform: translate(-50%, -50%)
             translate(calc(var(--nx, 0) * var(--lift)), calc(var(--ny, -1) * var(--lift)));
}
/* Hidden until the hill is being used. jcanton, 2026-08-22: the stops should show
   "only when dragging the ball or when hovering over one, not always" — a row of
   grey dots on every record on every page is furniture, and the thing worth
   looking at is where the ball is.
   Revealed by a hover anywhere on the drawing rather than by a hover on one stop:
   a stop that appears only once the pointer is already on it is a target you find
   by accident. Focus reveals them for the same reason, for somebody arriving by
   keyboard who never hovers anything at all.

   **And only on a hill whose ball can actually be moved** — jcanton, 2026-08-25:
   "the hill graph shows all nodes as grey circles on hover even when the editor
   is in preview mode, they should only appear on hover if in the edit or
   side-by-side view". A ghost is where this record COULD stand, which is an
   offer; on a hill with no stops under it there is nothing to accept, so it is a
   row of grey dots that answers a hover and then does nothing. The read-only
   hills are every one on the table's hover card, the people page and the cycle
   roster as well as the record page in preview, and all of them were making it.

   `.hill-live` and not `:has(.hill-stop)`, which says the same thing: the class
   is emitted by the same `{if live}` that emits the stops, so the two cannot
   drift, and a plain descendant selector is one `tests/cascade.py` can actually
   resolve — its `:has()` is weighed for specificity and matched against
   ancestors, which is the wrong question and would have answered "hidden" for
   both hills. The other two reveals need no guard: `dragging` is put on by the
   drag and `input:focus-visible` needs an input, and neither exists on a hill
   with no stops. */
.hill-ghost { width: var(--ghost); height: var(--ghost);
              background: var(--line-strong); opacity: 0; }
.hill-live:hover .hill-ghost, .hill.dragging .hill-ghost,
.hill:has(input:focus-visible) .hill-ghost { opacity: .5; }
/* Half the line, and not a pixel guessed at: `.hill-line` is 2px painted, so the
   surface a ball rests on is 1px above the path's own coordinates. */
.hill-ghost { --lift: calc(var(--ghost) / 2 + 1px); }
.hill-ball, .hill-stop { --lift: calc(var(--ball) / 2 + 1px); }
/* Firmer while the hill is a control: reading a record the other stops are
   context, and editing one they are the places the ball may go. */
.hill[role=radiogroup]:hover .hill-ghost,
.hill[role=radiogroup].dragging .hill-ghost { opacity: .65; }
/* `left`/`top` and not `transform`, so one ball rolls between stops when the
   status changes instead of a second ball lighting up somewhere else. The shell's
   blanket reduced-motion block is inlined before every page's own stylesheet and
   marked `!important`, so this needs no rule of its own to be switched off.
   The roll is a token so that a ball being dragged can stop rolling — under the
   pointer it should be under the pointer — without a second `transition:` in the
   stylesheet. `transition: none` is the absence of motion written in the grammar
   of motion, and `test_the_app_moves_in_exactly_one_place` counts declarations. */
.hill { --roll: .22s; }
.hill.dragging { --roll: 0s; }
.hill-ball { width: var(--ball); height: var(--ball); border: 2px solid;
             box-sizing: border-box;
             transition: left var(--roll) ease, top var(--roll) ease,
                         transform var(--roll) ease; }
{#- Scoped to the ball, and that is not tidiness: a stop wears `hill-<word>` too,
    so that the chip it shows on hover is that status's own chip — and an unscoped
    fill would paint every hit target on the hill as a solid disc. -#}
{% for s in statuses %}
.hill-ball.hill-{{ s }} { background: var(--st-{{ s }}); border-color: var(--st-{{ s }}-line); }
{%- endfor %}
/* `dropped` is the one word left with no tokens of its own, and it borrows
   shelved's — it is the same sentence in the other vocabulary.
   `thinking` used to be written here too, wearing `var(--accent)`, because it
   was a note's word and not a status. It is a status now, the loop above emits
   `.hill-ball.hill-thinking` from its own tokens, and this rule would have gone
   on beating it: same specificity, (0,2,0) against (0,2,0), and later in the
   sheet. That is one word painted the interface accent on a hill and its own
   teal on the chip beside it, which is exactly the "colour that means two
   things" the drop-target token two blocks up is written to avoid. Deleted, and
   the note's ball changes colour with it — from the accent to `--st-thinking`,
   which is the same hue and now the same paint as everywhere else that word is
   drawn. */
.hill-ball.hill-dropped { background: var(--st-shelved); border-color: var(--st-shelved-line); }
/* Hollow, and the one ball that is: a promoted note is not standing there, the
   record it became is. Filled, it would claim the note is a quarter of the way up
   a hill it never climbed. */
.hill-ball.hill-promoted { background: none; border-color: var(--accent); }
/* Off the path: the hill goes quiet and the ball keeps its colour, because the
   one thing still worth finding on a shelved record is where the ball is. */
.hill-off :is(.hill-line, .hill-ground) { opacity: .4; }
.hill-off .hill-ghost { opacity: .18; }
/* The hit target, present only in edit mode. The input paints its own focus ring
   and nothing else: an `opacity: 0` element takes its outline with it, and the
   ring has to be on the thing a reader is looking at. */
.hill-stop { width: 26px; height: 26px; display: grid; place-items: center; }
.hill-stop input { appearance: none; -webkit-appearance: none; margin: 0; border: 0;
                   width: 24px; height: 24px; border-radius: 50%; background: none;
                   cursor: pointer; }
.hill-stop input:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
/* Where this one would land, said before it is let go. Dashed, so it reads as a
   target rather than as a second ball already there. */
.hill-stop::before { content: ""; position: absolute; inset: 3px; border-radius: 50%;
                     border: 2px dashed transparent; }
.hill-stop:hover::before, .hill-stop:has(input:focus-visible)::before {
  border-color: var(--line-strong); }
/* And the word, because a position is only obvious to somebody who already knows
   what the positions mean — jcanton, 2026-08-22: "people are forced to know". It
   is not printed permanently: the whole argument for replacing the chip was that
   the drawing says something the word cannot, and a word standing beside it all
   the time is the chip back with extra steps. So it is asked for — hover or
   focus a stop and that stop says its name, drag the ball and the ball says the
   name it is about to take.
   No transition on it: the appearing is the answer to a question somebody just
   asked, and `test_the_app_moves_in_two_places` is an inventory worth keeping
   short. */
.hill-stop::after, .hill-ball::after {
  content: attr(data-word); position: absolute; bottom: calc(100% + 4px); left: 50%;
  transform: translateX(-50%); z-index: 2;
  font-family: var(--font-mono); font-size: 11px; line-height: 1.45;
  text-transform: uppercase; letter-spacing: .04em;
  padding: .1rem .4rem; border-radius: 2px; white-space: nowrap;
  background: var(--surface); border: 1px solid var(--line-strong); color: var(--fg);
  visibility: hidden; pointer-events: none;
}
{#- The same chip the table wears, and not a tooltip that merely says the same
    word: `.chip.st-X` above is generated from these tokens too, so the thing that
    appears over a stop is recognisably the thing the rest of the app calls a
    status. Written by the same loop for the same reason — five statuses times
    three tokens is a set that drifts by hand. -#}
{% for s in statuses %}
.hill-stop.hill-{{ s }}::after, .hill-ball.hill-{{ s }}::after {
  background: var(--st-{{ s }}-soft); color: var(--st-{{ s }}-text);
  border-color: var(--st-{{ s }}-line); }
{%- endfor %}
/* `dropped` is not on the status ladder and has no tokens of its own; it borrows
   shelved's, which is the same sentence in the other vocabulary.
   `thinking`'s copy of this rule is gone for the reason the ball's is, and it was
   the worse of the two: it set only `color` and `border-color`, so the chip took
   its ground from the loop above and its ink from the accent — half a chip from
   each of two rules. */
.hill-stop.hill-dropped::after, .hill-ball.hill-dropped::after {
  background: var(--st-shelved-soft); color: var(--st-shelved-text);
  border-color: var(--st-shelved-line); }
.hill-stop:hover::after, .hill-stop:has(input:focus-visible)::after,
.hill-ball:hover::after, .hill.dragging .hill-ball::after { visibility: visible; }
/* The ball is under the stops in the stacking order, so on a live hill a hover
   reaches the stop and not the ball. Reading a record there are no stops, and the
   ball is the only thing to point at. */
.hill-ball { pointer-events: auto; }
/* On the chip line and not under it. A card is a glance and it is drawn over the
   table it was opened from, so every row it grows is a row of the plan it hides —
   `test_a_nine_hundred_word_document_does_not_cover_the_table` holds it under half
   the window. Beside the word, the hill costs the difference between a line of
   chips and a small drawing rather than a whole row of its own. */
#card .hill { --ball: 11px; --ghost: 6px; max-width: 6.5rem; }
#card .card-hill { display: inline-block; vertical-align: middle;
                   margin-left: .35rem; }
#card .card-chips { display: flex; align-items: center; flex-wrap: wrap; gap: .25rem; }
/* The two lines every view writes about itself: the count under the controls of
   what is on screen, and the place a refusal or a receipt is written into. Four
   pages drew `#summary` and three drew `#state`, and the copies had already come
   apart — the table's summary was the one that never got the margin or the size
   the other three share, so this is theirs. `#shown` was three copies of `.num`
   under a different name; it wears `.num` now. */
#summary { color: var(--muted); font-size: 13px; margin: .5rem 0 .25rem; }
/* Except in the control bar, where it is the far end of the search box's line
   rather than a line of its own — the three plan views put it there on
   2026-08-25. `margin-left: auto` is what makes it the far end; the zeros are
   what stop it making the row taller than the box in it, the same reason
   `.keyrow`'s children lose theirs. */
#controls .searching #summary { margin: 0 0 0 auto; text-align: right; }
/* The whole phrase, not the digit: "1 blocking problems" in danger red with the
   count black beside it read as two separate facts. And the colour has to mean
   something — at zero it is muted, because danger nobody can act on is danger
   nobody reads.
   In the shell since 2026-08-25, because the sentence is on three views now and
   it was in the table's own stylesheet: the graph and the timeline drew it as an
   ordinary blue underlined link, which is the drift a shared fragment styled by
   one page's sheet always ends in. */
#blockers { color: var(--sev-blocker); text-decoration: none; }
#blockers:hover { text-decoration: underline; }
#blockers.none { color: var(--muted); }
#state { color: var(--muted); font-size: 12px; }
/* One meter for the whole app: weeks bet against weeks available. It was a rule
   on the cycle page until the cycles index and then the people page needed the
   same picture, and a second copy of a meter is two meters that disagree about
   what full looks like.
   `span.bar` and not `.bar`, because this stylesheet is on every page and every
   timeline bar is a rect wearing the same class. In SVG2 `width` and `height`
   are CSS geometry properties on a rect, and any author rule beats a
   presentation attribute — so a bare `.bar` here drew all seventeen Gantt bars
   at 140x8 and the chart stopped being about dates. Every meter site is a span;
   the element name is the whole of what keeps the two apart. */
span.bar { display: inline-block; width: 140px; height: 8px; background: var(--line);
           border-radius: 4px; overflow: hidden; vertical-align: middle; }
span.bar > span { display: block; height: 100%; background: var(--accent); }
.over span.bar > span { background: var(--danger); }
/* One chip everywhere a status or a kind is named, defined here rather than per
   page because the table, the detail page, the people page and the cycle bet
   table were four different ways of saying the same word. The word is always
   inside the chip, so the colour is redundant encoding and a reader who cannot
   separate the hues loses nothing. */
.chip { display: inline-block; font-family: var(--font-mono); font-size: 11px;
        line-height: 1.45; text-transform: uppercase; letter-spacing: .04em;
        padding: .1rem .4rem; border-radius: 2px; white-space: nowrap; }
{#- Written by the loop rather than by hand: five statuses times four tokens is
    twenty values to keep in step, and the pair that drifts is the pair nobody
    reads until a chip turns white on white.

    A border of its own status colour, like the kind chip's hairline and the
    priority chip's: jcanton, 2026-08-21, having seen all three side by side in a
    hover card — "why type and priority chips look different from the status
    ones, the border!". Three chips on one line that are three shapes read as
    three kinds of thing. -#}
{#- `select.pick` beside the chip: a second RULE and not a second selector on
    the first one, which cost a round — `test_a_status_carries_a_chip_palette_as_
    well_as_a_fill` looks for the literal `.chip.st-thinking {`, and a selector
    list moves the brace off the end of it. Two rules say the same thing to a
    browser and leave that claim readable.

    Generated from the same loop rather than The betting table's status column
    was a chip and is a picker now — it has to be chosen, not typed, because a
    ladder is a closed set — and a control drawn in the page's own ink would have
    taken the ladder away to buy editability. Five hand-written rules there would
    be a second copy of this ladder, which is the thing this loop exists to
    prevent: a rung added in `STATUSES` must not need a second edit to get a
    colour. -#}
{% for s in statuses %}
.chip.st-{{ s }} { background: var(--st-{{ s }}-soft); color: var(--st-{{ s }}-text);
                   border: 1px solid var(--st-{{ s }}-line); }
select.pick.st-{{ s }} { background: var(--st-{{ s }}-soft); color: var(--st-{{ s }}-text);
                   border: 1px solid var(--st-{{ s }}-line); }
{%- endfor %}
/* Kind never competes with status for attention: no hue, only a hairline. One
   rule for all three, because three kinds drawn three ways read as two of them
   being special rather than as three answers to one question — a project used to
   carry the accent and extra weight, a pitch a plain hairline, and a task no
   border at all, which is the first thing anybody noticed about the id column.
   The word inside the chip is what says which kind it is. */
{#- Written by the loop rather than by hand, like the status rules above it: a
    kind added to the ladder arrives with its chip already drawn instead of as the
    one chip on the page with no rule and no border. -#}
{% for k in kinds %}
.chip.kind-{{ k }} { color: var(--kind-ink); border: 1px solid var(--kind-line); }
{%- endfor %}
/* The checklist meter, on the table and on the detail page. Always beside the
   two numbers it draws: a bar alone says "some", and the question a checklist
   answers is "how many left". */
.meter { display: inline-block; width: 4rem; height: .45rem; margin-left: .4rem;
         background: var(--line); border-radius: 3px; overflow: hidden;
         vertical-align: middle; }
.meter > span { display: block; height: 100%; background: var(--accent); }
/* A problem reads the same on every page: a bar down the left of the row, a soft
   ground on the cell that caused it, a glyph carrying the message. Three classes
   rather than one, so a row can be marked without tinting every cell in it. */
.sev-row-blocker { border-left: 3px solid var(--sev-blocker); }
.sev-row-warn { border-left: 3px solid var(--sev-warn); }
.sev-cell-blocker { background: var(--sev-blocker-soft); }
.sev-cell-warn { background: var(--sev-warn-soft); }
.sev-mark { font-family: var(--font-mono); font-size: 11px; cursor: help; }
.sev-mark-blocker { color: var(--sev-blocker); }
.sev-mark-warn { color: var(--sev-warn); }
/* Every interactive thing, and :focus-visible rather than :focus so a mouse
   click does not leave a ring behind it. :where() keeps the specificity at zero,
   so a page stylesheet loaded after this one still wins on colour. */
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
  border-radius: 3px;
}
/* A drawing with no size of its own. `_ICON_SVG` carries a `viewBox` and no
   `width` or `height`, so an SVG that nothing sizes lays out at 0x0. Every use
   of one was inside a box that decided — `.avatar svg` and `.picker .art svg`
   are both `width: 100%` — and the first control to put a mark somewhere else
   shipped two buttons with nothing in them. A default here is the size an icon
   is wherever it is put; a box that wants to decide still does, because those
   two rules are (0,1,1) against this (0,1,0).
   `flex: none` because the places that put one beside text are flex rows, and a
   drawing that shrinks to make room for a word is the word winning an argument
   it should not be in. */
.icon { width: 1em; height: 1em; flex: none; }
/* The key to the one thing on a page that is not a word. Shared, because the
   graph and the timeline draw the same statuses in the same tokens, and every
   swatch is the token the shape is actually filled with — a legend naming a
   different colour from the one on screen is worse than no legend, because it
   is believed. The swatch carries the glyph too: colour is no longer the only
   channel on a bar or a node, so a key to the colour alone keys half the
   drawing. */
/* PRIORITY, AS ONE BLOCK. A character whose height is the rung — `\u2581` up to
   `\u2588` — in the rung's own colour, on the text baseline of whatever word it
   sits beside. It is the second channel for a fact the graph also draws as line
   thickness, and jcanton had seen two earlier answers to the same question: five
   `<i>` elements in an `inline-flex` meter, which had to be aligned against a
   word inside a chip inside a cell inside a column that tightens, and then no
   mark at all in menus, where an element cannot go.

   `PRIORITY_GLYPH` in `render.py` carries the argument for the characters, the
   fallback they rely on, and what it costs.

   The colour is on the mark and not on the chip: a chip with a coloured ground
   in the column next to Status would be two ladders competing at one weight, and
   the ground is what Status uses. */
/* In a table cell the mark leads and the word follows: the mark is what the eye
   picks out of a column of fifteen rows and the word is what settles which rung
   it is — inside the same chip status wears, so two columns saying one kind of
   thing say it the same way.

   No hue on the ground, for the reason above: the mark carries the colour. */
.chip.pri { color: var(--kind-ink); border: 1px solid var(--kind-line);
            padding: .1rem .4rem; }
.chip.pri .chipmark { opacity: 1; font-size: 15px; line-height: 0;
                      vertical-align: -1px; }
.chip.pri-very_low .chipmark  { color: var(--pri-very-low); }
.chip.pri-low .chipmark       { color: var(--pri-low); }
.chip.pri-medium .chipmark    { color: var(--pri-medium); }
.chip.pri-high .chipmark      { color: var(--pri-high); }
.chip.pri-very_high .chipmark { color: var(--pri-very-high); }
/* The status mark inside the chip it has always had. Slightly dimmed, because
   the word is the thing being read and the mark is what finds it — a glyph at
   full weight beside a short word reads as two words. */
.chip .chipmark { font-weight: 700; opacity: .75; margin-right: .3rem; }
/* Too narrow for the word: the mark stays and the word goes. The chip loses its
   right padding and its mark loses its margin with it, or a chip holding one
   glyph is mostly air. */
table.tight-status td[data-col="status"] .chipword { display: none; }
table.tight-status td[data-col="status"] .chipmark { margin-right: 0; }
table.tight-status td[data-col="status"] .chip { padding: .1rem .3rem; }
table.tight-priority td[data-col="priority"] .chipword { display: none; }
table.tight-priority td[data-col="priority"] .chipmark { margin-right: 0; }
table.tight-priority td[data-col="priority"] .chip.pri { padding: .1rem .3rem; }

/* One grid for both rows: the row's name, then one column per rung. Each list is
   `display: contents`, so its keys are the grid's own items and a key in one row
   sits over the key under it in the other. Each column is as wide as the wider of
   its two words and no wider — an earlier attempt padded every key to the widest
   word in EITHER row, which put a hand's width of nothing between Done and
   Shelved.
   The column count is the STATUS ladder's, because it is the longer of the two
   lists. It was the literal `5` until status grew a sixth rung, and both ways of
   leaving it wrong were measured in Chrome at 1400px: at `repeat(5)` the sixth
   status key wrapped to a THIRD row and sat under the word STATUS, and at
   `repeat(6)` — the obvious fix — the grid became seven columns, priority's name
   and its five keys exactly filled row 1, and auto-placement put the word STATUS
   in row 1 column 7 with the whole status row shifted one cell left.
   `grid-column: 1` on the name is what actually holds the shape: it forces each
   list to start a new row, so the two rows stay two rows whatever their lengths
   are. That is the part that was missing, and it is the part that made this a
   grid that only READ as a table while the two lists happened to be the same
   length — three reported rounds of "the legend is not aligned"
   (`design/QUEUE.md` §7.5), each of which this arrangement would have survived.
   Measured, not eyed, in `test_the_legend_is_two_rows_and_the_keys_line_up`. */
.legends { display: inline-grid;
           grid-template-columns: auto repeat({{ statuses|length }}, max-content);
           gap: .2rem .9rem; align-items: center; justify-items: start;
           margin: .75rem 0 0 auto; }
.legends .legendname { grid-column: 1; }
/* On its own — the timeline's markings key — a legend is still one flex row.
   Only inside the grid does a list hand its keys over, and only the graph's two
   rows are in one. */
.legend { display: flex; flex-wrap: wrap; gap: .25rem 1rem; align-items: center;
          list-style: none; margin: .75rem 0 0; padding: 0;
          font-size: 12px; color: var(--muted); }
.legends .legend { display: contents; }
.legend li { display: flex; align-items: center; gap: .35rem; font-size: 12px;
             color: var(--muted); }
/* border-box so a key that carries a border is the same 20x12 as one that does
   not: every status swatch grew a border with the shapes it keys, and on
   content-box the row of keys came out at three different heights.

   12 and not 11, which is the thickest border's doing: a 6px border top and
   bottom is 12px of border, and border-box cannot shrink a box below what its
   own borders need — so the very-high key stood one pixel taller than the other
   nine and the two rows sat off each other by that pixel. */
.legend .swatch { width: 20px; height: 12px; border-radius: 2px; flex: none;
                  box-sizing: border-box; }
/* inline-flex on the span only. Two of these swatches are <svg>, where a flex
   display on the root would be laying out a replaced element as a box. */
.legend span.swatch { display: inline-flex; align-items: center; justify-content: center;
                      font-family: var(--font-sans); font-weight: 700;
                      font-size: 9px; line-height: 1; }
/* What the graph draws priority with, at the size the graph draws it. The five
   numbers are the SAME five in the node style, and they have to stay that way:
   a key that keys nothing is worse than no key, because it is believed. Only
   the ground is neutral — this says thickness and the row beside it says
   colour, and a priority key wearing a status ink would key both at once. */
/* The bars sit ON the box, the way a status glyph sits in its swatch — so the
   key is a small node rather than two things beside each other, and it carries
   both channels at once: the border is the thickness the node is drawn with and
   the meter is the same rung counted.

   ON and not IN. Inside, a 20x11 swatch with a 6px border has nothing left in
   the middle, and the first version of this bought the room by making the
   priority swatch 34x17 — a key row visibly larger than the status row beside
   it, and the two rows no longer level. jcanton, 2026-08-20: "the legend is again
   not vertically aligned and the boxes for priority are larger than those for
   status", and "the very_high has the bars not so visible".

   Absolutely positioned over the border, both rows are the same 20x11 and every
   rung shows its whole meter, thickest border included. */
.legend .swatch.pri { background: var(--surface); border-style: solid;
                      border-color: var(--fg); }
/* The mark inside the key is the mark on the drawing, at the size the key is.
   It sits ON the border rather than inside it, because a 6px border on a 12px
   swatch leaves nothing in the middle — the thickest rung was a box with its own
   meter squeezed out of it. */
.legend .swatch.pri .primark { font-size: 12px; line-height: 1; }
.legend .swatch.pri-very_low .primark  { color: var(--pri-very-low); }
.legend .swatch.pri-low .primark       { color: var(--pri-low); }
.legend .swatch.pri-medium .primark    { color: var(--pri-medium); }
.legend .swatch.pri-high .primark      { color: var(--pri-high); }
.legend .swatch.pri-very_high .primark { color: var(--pri-very-high); }
.legend .swatch.pri-very_high { border-width: 6px; }
.legend .swatch.pri-high      { border-width: 4px; }
.legend .swatch.pri-medium    { border-width: 2px; }
.legend .swatch.pri-low       { border-width: 1.5px; }
.legend .swatch.pri-very_low  { border-width: 1px; }
/* Which of the two rows this is. Not a heading element: the rows are one
   sentence each about the same drawing, and a heading would put them in the
   document outline as sections of the page. */
.legend .legendname { font-weight: 600; letter-spacing: .04em;
                      text-transform: uppercase; font-size: 10px; }
{#- Fill, ink AND border: the shapes these key are bordered now, and a key drawn
    without the border is a key to a different shape — which on the light theme
    is the difference between a pale swatch floating on the page and the bar the
    reader is looking at. -#}
{% for s in statuses %}
.legend .swatch.st-{{ s }} { background: var(--st-{{ s }}); color: var(--st-{{ s }}-ink);
                             border: 1px solid var(--st-{{ s }}-line); }
{%- endfor %}
/* The key to a drawing and the count of what is in it, on one row. Both describe
   the picture below rather than control it, and the count is the short one, so it
   goes to the far end of the key's row instead of taking a row of its own — which
   on the graph and the timeline is the last row before the drawing starts.
   It wraps, because the timeline's markings key is six items wide: a count
   squeezed into the last 40px of a row is a count nobody reads. */
.keyrow { display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1.5rem;
          margin: .75rem 0 .25rem; }
/* Both children carry their own vertical margin for the rows they used to be.
   Inside a flex row those do not collapse, so the row would be as tall as the
   two of them stacked. */
.keyrow > .legend { margin: 0; }
/* The SECOND key hangs off the right end — jcanton, 2026-08-25, of the
   timeline's two: "left-aligned for status and right aligned the others". Written
   as an adjacent sibling and not as `:last-child`, which is also the FIRST child
   on a row that has only one key and would push a lone legend to the right edge
   for no reason anybody asked for. */
.keyrow > .legend + .legend { margin-left: auto; }
/* Nothing to fold above 40rem, and nothing to say so. Same shape as the filter
   bar's summary and for the same reason — see `#controls .facetbox > summary`.
   `.keyrow` keeps its own top margin, so the folded box adds none of its own. */
.keyfold > summary, .windowfold > summary { display: none; }
/* The row a page's own controls stand in — grep `class="editbar`: the table's
   create link, the record page's Delete-and-views row in both modes, the cycle
   page's "add somebody" and its goal bar, the one row of the cycles index's
   create form. The rule was in _DETAIL_STYLE — which the cycle pages load and
   the table does not, so on the table it was a `<p>` with the browser's default
   margin and the create action sat in it as a bare inline link. */
/* `flex-wrap`, because the row now ends in the control that acts on it rather
   than in the last field: unwrapped, a narrow window squeezed three date boxes
   to make room for a button instead of putting the button underneath them. */
.editbar { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center;
           margin: .4rem 0 1rem; }
/* A link that is a control. The only rule was `.tl-controls .button`, scoped to
   the timeline's filter bar, so the table's create link — which was, at the time,
   the one way to bring a record into existence from the UI — rendered as
   underlined blue text. That link is gone (the `+` row at the foot of the table
   replaced it); the rule is not, because the empty states still link to `/new`
   with it and so does the records list.
   `:visited` as well as the base state, because the shell colours every visited
   link with `a:visited`, which is (0,1,1) and would beat a bare `.button`: the
   button turned back into a link the moment somebody had used it once. Written
   in link-visited-hover order, so the states later in the list win the ties they
   are supposed to. */
/* ONE LOOK FOR EVERY CONTROL, and this is the only place it is written.
   jcanton, 2026-08-20: "buttons do not have consistent aesthetic: clear filters,
   the timeline zoom dropdown, the issues state dropdown, notes state, edit record
   are all grey and different from the newer buttons".

   They were grey because they were native — a `<button>` and a `<select>` with no
   rule get the operating system's own chrome, which matches nothing else here and
   changes between two machines looking at the same plan.

   The `<select>`s keep the caret the browser draws them, which is the one thing
   this rule cannot supply — the facet buttons on the table draw their own from
   two borders, and they can only do that because they are buttons rather than
   selects. Same ground, same border, same radius, native caret; that was the
   choice, made deliberately over converting four more controls into popups.

   THE RULE IS THE DEFAULT AND NOT A LIST. It was a list of ids and classes for
   half a day, and in that time it missed twenty of the twenty-eight controls on
   this site — the body preview, the dependency editor, the clear-filters button,
   the promote control, the icon picker, the table's own new-row button. jcanton
   found the first within the hour and asked the right question: "I thought we had
   managed to impose the style of buttons and dropdowns to be coherent across the
   entire app? why did that work?"

   (Named in prose rather than by id, and that is not fussiness: a static export
   is checked for the id of a control it must not carry, and a comment mentioning
   that id put it on the page and turned the check red.)

   It did not work, and a list is why. Every control added from now on would have
   had to be remembered into a selector three thousand lines from where it was
   written, and the failure is silent — the button simply looks like the operating
   system and nobody notices until they are looking at two of them side by side.

   So: every `button` and every `select` gets this, and a control that wants
   something else says so in its own rule. That inverts the burden onto the
   exception, which is the only place it can be paid attention to. A bare rule
   already beats this one on specificity — `.facetopen`, `#who button` and the
   half-dozen icon buttons all set `background: none; border: 0` and all of them
   are a class or an id, which outranks an element selector — so they keep the
   nothing they were drawn with, on purpose and by construction.

   `.field` outranks it too, which is what keeps a `<select>` that is a form field
   looking like a field: a text box is somewhere to TYPE and a control is
   something to PRESS. */
/* 3px and not the 2px this was written with. jcanton looked at the editor's
   toolbar, which had been drawing its own corner, and preferred it — so the
   toolbar stops being the exception and the app moves to its corner. One number,
   here, is what makes that a decision rather than a drift. */
button, select, .button, .button:visited {
  font: inherit; font-size: 13px; line-height: 1.4;
  padding: .2rem .7rem; border-radius: 3px; cursor: pointer;
  border: 1px solid var(--line-strong); background: var(--surface);
  color: var(--fg); text-decoration: none;
}
button:hover, select:hover, .button:hover { border-color: var(--accent);
                                            color: var(--accent); }
/* Every box somebody types into, in the page's own colours rather than the
   browser's. `background` and `color` only: the padding, border and radius of a
   text box are set where each of them is drawn — a search box, a cell editor and
   a form field are three different shapes — and what they had in common was the
   one thing nobody had set, so they were drawn in the UA's Field colour. That is
   white on every light `color-scheme`, which is why a colour scheme left every
   search box on the page a white rectangle. jcanton, 2026-08-20.

   Checkboxes and radios are excluded because their background IS the control:
   painting it is how a checkbox loses its tick. `accent-color` is what tints
   those, and the browser derives it from `color-scheme`, which every scheme
   sets. */
input:not([type="checkbox"]):not([type="radio"]), textarea {
  background: var(--surface); color: var(--fg);
}
::placeholder { color: var(--muted); opacity: 1; }
/* Apply and Reset on the timeline were a button and a bare link, which reads as
   one control and one afterthought. They are the same pair of scissors pointed
   two ways, so they are the same size and shape; only the fill says which one is
   the verb. */
.button.primary { background: var(--accent); border-color: var(--accent);
                  color: var(--on-accent); }
.button.primary:hover { color: var(--on-accent); opacity: .9; }
/* The way out of a filter, on every page that has one. Three pages were drawing
   this button themselves, which is three chances for the way out of a filter to
   look like something else. */
/* What is wrong with the query, beside the box it is in. `--sev-warn` and not
   `--sev-blocker`: nothing is broken, a sentence is half-typed — and the rows
   come back the moment the bracket is closed. */
#query-error { font-size: 12px; color: var(--sev-warn); align-self: center; }
/* Nothing of its own. It carried a full copy of the rectangle above — the same
   border, the same background, the same hover — and the copy is how it came to
   be the one control still drawn with the old corner after the line above moved
   to 3px. A control that wants the default says nothing. */
/* The save, on every page that draws a commit bar, and it is at the TOP of
   what it writes — jcanton, 2026-08-20, "move the create bar up top too,
   consistency!".

   The stickiness is what delivers reachability and the edge it sticks to never
   did: a bar that is on screen wherever you have scrolled to is as reachable
   from the head of a form as from its foot. So the edge is free to be the one
   that puts the controls where the eye already is — under the button that opened
   the edit, beside the record's identity, which is where the detail page put
   Save and Cancel when Edit moved up there.

   `bottom: auto` is as load-bearing as `top`: with both set the browser keeps
   the first and the bar stays at the foot.

   Defined here rather than per page because four pages draw one — the record
   page, the create form, the cycle page and the served graph, the set
   `test_every_commit_bar_sticks_to_the_same_edge_and_one_rule_decides_it`
   resolves by rendering each of them — and four copies of a commit bar is four
   answers to "have I saved this yet". It was per page for half of it, and that
   is exactly how the create form and the cycle page came to have a bar stuck
   to neither edge: `#commitbar { top: 0; bottom: auto }` was written for the
   detail page and put in `_DETAIL_STYLE`, which more pages load than draw a
   bar — so two pages whose bar was still last in the markup lost `bottom: 0`
   to it and became a plain block at the foot, off screen from the top of a
   form that scrolls. Measured in Chrome at 1400x900 before the move: 1178px
   down the create page and 1113px down the cycle page, with nothing on screen
   at all. */
.commitbar {
  /* Under the suggestion popup (20) and under the shell's banner (40): a bar
     that is always on screen is always in front of something. */
  position: sticky; top: 0; bottom: auto; z-index: 10;
  /* `display: flex` beats `[hidden]`'s `display: none` — the attribute is a UA
     rule and this is an author one. Every menu on the table page opened on load
     the day that was forgotten, so it is spelled out here. */
  display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap;
  margin: 1.5rem 0 0; padding: .5rem .75rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: 3px;
}
.commitbar[hidden] { display: none; }
/* Unsaved work is a warning, not decoration: this is the state in which closing
   the tab loses something. */
.commitbar.dirty { border-color: var(--warn); }
#unsaved { font-size: 12px; color: var(--muted); }
.commitbar.dirty #unsaved { color: var(--warn); font-weight: 600; }
/* The shape is the shared rule above. What is left here is what only Save has:
   the two states that say whether pressing it would do anything. */
#save:disabled { color: var(--muted); border-color: var(--line-strong); cursor: default; }
#save:not(:disabled) { border-color: var(--accent); color: var(--accent); }
/* What the status chosen in this form will make the server refuse it without.
   A warning colour because it is a refusal waiting to happen, and a word rather
   than an asterisk because an asterisk means "required" only to people who have
   already been told. */
.req { font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
       color: var(--sev-warn); font-weight: 600; }
/* Inside the body, not above it or beside it: an empty table with the message
   somewhere else is still a header row over a void. Two tables draw one now —
   the plan's rows and the people's — so the shape of "there is nothing here"
   lives with the button that gets you out of it. */
tr.nothing td { padding: 2.5rem .5rem; text-align: center; }
tr.nothing .headline { margin: 0 0 .25rem; color: var(--fg); font-size: 15px; }
tr.nothing .hint { margin: 0 0 .75rem; }
/* What a 409 comes back with: the file, and every field that disagreed, one per
   line. `pre-wrap` because it is a report rather than a sentence, and the rule
   down the side because it is the one answer that means the save did not land.
   It was in _DETAIL_STYLE, which the table does not load — so the table's copy
   of the same box collapsed into one run of unstyled text. */
#conflict, #row-conflict { border-left: 3px solid var(--danger); padding: .5rem .8rem;
                           margin-top: 1rem; white-space: pre-wrap; font-size: 13px; }
/* Anything long in that box is folded — jcanton, 2026-08-24: the draft-versus-room
   report "pushes the editor window up and reduces its height". `white-space:
   pre-wrap` above is what makes the box as tall as its contents, which is right
   for a sentence and wrong for a document, and the one message that carries a
   whole draft was costing the editor nine hundred words of room.

   The fold is a `<details>`, so shut it is one line and there is nothing here to
   size. OPEN it is capped and scrolls INSIDE itself, which is the half that
   matters: without the cap, opening the fold puts the page back exactly where it
   was. 14rem is about ten lines — enough to recognise your own writing, short
   enough that the editor keeps the screen.

   `white-space: pre` and not `pre-wrap` on the payload: a draft is somebody's
   markdown and its line breaks are theirs, so it scrolls sideways rather than
   being re-wrapped into a shape they did not write. The box's own `pre-wrap`
   would otherwise inherit down into it. */
#conflict details { margin-top: .5rem; }
#conflict summary { cursor: pointer; font-weight: 600; }
#conflict details pre { margin: .4rem 0 0; max-height: 14rem; overflow: auto;
                        white-space: pre; font-family: var(--font-mono);
                        font-size: 12px; background: var(--surface-2);
                        padding: .4rem .5rem; border-radius: 3px; }
/* Above everything a page can stick to its own edges — the cycle page's commit
   bar sits in exactly this corner — because news that the plan moved under you
   is the one thing on screen that must not be behind something else. */
#moved { position: fixed; right: 1rem; bottom: 1rem; z-index: 40;
         background: var(--accent); color: var(--on-accent);
         padding: .5rem .8rem; font-size: 13px; border-radius: 3px; }
#moved a { color: var(--on-accent); }
#moved .sha { font-family: var(--font-mono); opacity: .7; }
/* The plan is incomplete, and the page must not be able to look complete. Drawn
   with the blocker severity's own tokens rather than a fourth colour of its own:
   a file that is not a record is the most blocking thing this repository can
   hold, and it should read as the same kind of thing as the mark on a row that
   is missing a required field — the same vocabulary, one level up, about the
   plan instead of about a record. */
.unreadable { border-left: 3px solid var(--sev-blocker); background: var(--sev-blocker-soft);
              padding: .6rem .8rem; margin: 0 0 1rem; font-size: 13px; }
.unreadable .headline { margin: 0 0 .35rem; font-weight: 600; color: var(--fg); }
.unreadable ul { margin: 0; padding-left: 1.1rem; }
.unreadable li { margin: .15rem 0; }
/* A path is a thing you type back into a terminal, so it is set in the face the
   rest of the app sets identifiers in. `overflow-wrap` because the reason beside
   it is a sentence of unbounded length and the box is as narrow as the window: a
   phone at 360px would otherwise scroll the whole page sideways. */
.unreadable code { font-family: var(--font-mono); }
.unreadable li, .unreadable .headline { overflow-wrap: anywhere; }
.unreadable .hint { margin: .35rem 0 0; color: var(--muted); }
/* The pile banner: `.unreadable`'s strip — same position, same shape — one
   severity down, in the warn pair, because while it shows the store is still
   taking writes; the blocker moment is the 503, which arrives with its own
   sentence on the save itself. Loud is the strip's job here, wallpaper the
   risk, and what guards against wallpaper is `showPile`'s threshold, not a
   quieter colour. Cascade: no rule in this sheet or any page's matches a bare
   div child of #main — the id at (1,0,0) is the only source for every property
   except `[hidden]`'s UA `display: none`, which wins while the attribute is
   present exactly as it should (checked with tests/cascade.py, not assumed). */
/* **The row under the pointer, on every table in the app.** Here rather than in
   any one page's sheet because there are five of them — the records list, the
   table, the people page's roles, the cycle's roster and its betting table — and
   only this stylesheet is on all five. A rule per table is five chances to draw
   the same idea four different ways.

   **On the cells and not on the `<tr>`**, which is the same lesson `tr.can-hold`
   already paid for: the table's two frozen columns paint an opaque background of
   their own so the rest of the table can pass underneath them, so a colour on
   the row is drawn *under* the id and the title and those two cells are the ones
   that do not answer.

   **`background-image` and not `background`, and this is the part worth reading.**
   A colour would have to WIN against every ground these cells already carry —
   the frozen `--surface`, `td.sev-cell-blocker`, `td.inherited`, `td.waiting`,
   `tr.context` — and winning means erasing them: hover a blocked row and the
   thing the row is telling you goes away exactly while you are pointing at it. A
   translucent image is a different property, so the cascade never puts the two in
   competition. Each cell keeps its own `background-color` and takes the wash on
   top, and because the wash is over an opaque colour the frozen columns stay
   opaque and nothing shows through them.

   The `#main` is deliberate and it is doing one job: `background:` is a shorthand
   that also sets `background-image: none`, so every one of those rules is a
   competing declaration for this property at its own weight —
   `td[data-col="blocked_by"].waiting` is (0,2,1) and would beat a bare
   `tbody tr:hover > td` at (0,1,3). With the id this is (1,1,4) and the wash
   paints on every cell of the row or on none, which is the only version of this
   that is not a puzzle. Every table in the app is inside the page's one main element.

   `@media (hover: hover)` because a touch device has no pointer to follow and
   keeps the last-tapped `:hover` until something else is tapped — a phone would
   otherwise be left with one row lit for no reason, which is a highlight that
   means the opposite of what this one means. */
@media (hover: hover) {
  #main tbody tr:hover > td,
  #main tbody tr:hover > th {
    background-image: linear-gradient(var(--row-hover), var(--row-hover));
  }
}
#pile { border-left: 3px solid var(--sev-warn); background: var(--sev-warn-soft);
        padding: .6rem .8rem; margin: 0 0 1rem; font-size: 13px; font-weight: 600;
        overflow-wrap: anywhere; }
/* **Sixteen pixels, because below sixteen Safari zooms.** Focus a control whose
   text is smaller than 16px on iOS and the browser scales the whole page up to
   make it legible — and it does not scale back when the control blurs. The
   reader is left on a page 1.2x too wide, scrolling sideways through a layout
   that fitted a moment ago, and nothing on screen says what happened or how to
   undo it. Measured on this app at a 390px viewport: the search box is 13px, the
   scheme picker 12px, the timeline's two date boxes and its zoom 13px, and the
   cycle page's rate and bet boxes 13-14px. Every read surface has at least one.

   `input, select, textarea` and deliberately not `button`: the zoom is a
   text-entry behaviour, and the editor's sixteen 12px marks are a toolbar that
   16px would break onto three rows to fix a problem it does not have.

   A `maximum-scale=1` viewport would also stop it, and it is the wrong fix — it
   takes pinch-zoom away from everybody to spare a reader one surprise, which is
   the accessibility floor traded for a layout.

   `!important` for the same reason the block below it is important, and the
   comment there is the one to read: each page's stylesheet is inlined immediately
   after this block, so `.tl-controls input` (0,1,1) beats a bare `input` (0,0,1)
   on specificity AND takes every tie on order. Importance is what is left.
   Resolved against the real sheets, not assumed.

   40rem is the app's one narrow breakpoint — the width `.marks` already wraps
   at — and a second number meaning "narrow" is two numbers to keep in step. */
/* **A table with no fit of its own would rather scroll than wrap.** jcanton,
   2026-08-26: "the /table table renders well, without newlines and scrollable
   content, but all other tables do not: they introduce newlines and do not
   scroll horizontally. can you make them all like the /table table?"

   `/table` is the only one with a measured column fit — `fitWidths` sizes every
   column from its content and sheds what will not go, which is a few hundred
   lines of arithmetic this table's own file explains. The other four have
   `width: 100%` and let the browser wrap: at 390px that turns a login into three
   lines and a title into six, and every row on the screen grows to match, so a
   roster of five people is a page and a half of stacked syllables.

   These four take the other half of what `/table` does and none of the fit:
   size to the CONTENT and scroll inside the box they are already in. All four
   were already in a scroller — `.table-scroll` for the records list and the
   roles table, `.sideways` for the cycle's two — and none of them ever scrolled,
   because a table told to be 100% wide always fits.

   `min-width: 100%` beside `max-content`, or a table narrower than the phone
   stops short of the right edge and reads as a column of something.

   A class and not `.table-scroll table`, because `#rows` is in a `.table-scroll`
   too and it is the one table this must not touch: its widths are set inline by
   the fit, and `white-space: nowrap` on its cells would undo the clamped columns
   it draws instead of wrapping. Named for what these tables ARE rather than for
   what the rule does to them. */
@media (max-width: 40rem) {
  table.unfitted { width: max-content; min-width: 100%; }
  table.unfitted th, table.unfitted td { white-space: nowrap; }
}
@media (max-width: 40rem) {
  input, select, textarea { font-size: 16px !important; }
  /* The search box is `min-width: 16rem`, which was 256px of 13px text and is
     256px of 16px text — the same box holding a fifth fewer characters, so
     "Search titles, tags, PRs, people" came back from this change clipped at
     "peopl". A minimum is the wrong shape for it here anyway: on a page 350px
     wide there is nothing else on the row and no reason for the box not to be
     the row. `min-width: 0` first, or the 16rem floors the 100%. */
  #q { width: 100%; min-width: 0; box-sizing: border-box; }
  /* The handle for the filter fold, and the only width at which the box is ever
     closed. It reads as a control rather than as a heading — the marker is the
     browser's own triangle, and the whole row is the hit target, which is the
     one control on a phone that has to be easy to hit with a thumb. */
  /* `list-item` and NOT `flex`, and it is the difference between a control and
     a caption. A `<summary>` draws the browser's own disclosure triangle because
     its default display is `list-item`; setting `display: flex` — which is what
     this was, to put the count beside the word — takes the marker with it, and
     what is left is the word FILTERS in muted small caps over nothing, which
     reads as a heading for a section that is not there. There is no other mark
     on the page saying the row can be opened.

     The triangle is the browser's rather than a glyph or a drawing of one, for
     the reason `.rowgrip` gives about `⠿`: a character outside the vendored
     latin subset is a tofu box wherever the webfont did not land, and a marker
     that is sometimes a box is worse than none. This one is also the shape every
     other `<details>` the reader has ever opened uses, and it turns on its own.

     The count beside the word is an inline span, which needs no flex to sit
     there — `gap` was the only thing flex was buying and a space is enough. */
  #controls .facetbox > summary {
    display: list-item; list-style-position: inside;
    padding: .45rem .1rem; margin-top: .35rem; cursor: pointer;
    font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }
  #controls .facetbox > summary .facetboxname { margin-left: .2rem; }
  /* What is set, said in the closed state. `--accent` and not the muted ink
     beside it, for the same reason `.facet.chosen` is accented: a count that
     reads at the weight of the word next to it is a count nobody notices, and
     the whole risk of folding this away is a filter somebody forgot. */
  #controls .facetbox > summary .facetboxsaid { color: var(--accent); margin-left: .35rem; }
  #controls .facetbox > summary .facetboxsaid:empty { display: none; }
  /* The footer holds the corner on a phone — see `stowCorner`. A row rather than
     a stack, and wrapping, because the three controls in it are narrow and the
     version line beside them is short: on a 390px page they come out as two
     lines where the nav was spending one on its own. `margin-left: auto` is the
     corner's own rule and still right here — it pushes the controls away from
     the version line, which is the only other thing on the row. */
  #build { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .75rem; }
  /* The nav loses the element that was forcing it wide, so what is left is
     links. Nothing else changes: they were already wrapping. */
  #build .corner { font-size: 13px; }
  /* The key's handle and the window controls', drawn as the filter bar's is. One
     phone, one way of folding something away, so the second and third cost no
     learning. */
  .keyfold > summary, .windowfold > summary {
    display: list-item; list-style-position: inside;
    padding: .45rem .1rem; cursor: pointer;
    font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }
}
/* A reader who has told their operating system they want less motion gets none.
   It is a system setting and not a preference this app keeps, so there is no
   toggle for it and nothing in `remembered` — the browser answers, every page.

   One blanket block rather than a `transition: none` beside each animated rule the
   app owns, because the next person to write a transition will not come back here
   to add it. There are two: `#grip::before`, the width handle's fade on the
   record page and the create form, and `.hill-ball`, which rolls between its
   stops when a status changes and
   is in this shell and therefore on every page. `test_the_app_moves_in_two_places`
   is the inventory, and it is a tripwire rather than a ban — what a new one has to
   pass is that it is inside this block's reach and not on a canvas.

   `!important` is load-bearing rather than shouting. Each page's own stylesheet is
   inlined immediately below this block, so a page rule is *later* in the sheet and
   takes every tie on order — which is precisely what the grip's rule does at equal
   specificity. Importance is the only thing that outranks it, and the browser test
   for this asks about that exact rule so the ordering is proved rather than
   assumed.

   `.01ms` and not `0s`: a zero-duration transition never fires `transitionend`, so
   a listener waiting on one would wait for good. Nothing waits today; the block
   should not be the reason the first one hangs.

   CSS does not reach a canvas. The graph is cytoscape, whose layout runs with
   `animate: false` — its default, and `LAYOUT` does not turn it on. Turning it on
   means reading the media query in JavaScript, because this block cannot. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: .01ms !important;
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
  }
}
{{ style }}
</style></head><body>
<a class="skip" href="#main">Skip to the content</a>
{#- One `<a>` per row of `_NAV`, and the row already carries whether it is the
    page you are on. Six hand-written links were six places to forget the mark;
    the mark is `aria-current="page"` and the stylesheet draws from that attribute
    and from nothing else, so what a screen reader announces and what a reader
    sees cannot come apart. Whitespace between the links is a whitespace-only text
    node in a flex container, which is not a flex item and draws nothing. -#}
<nav>{% for item in nav %}<a href="{{ item.href }}"
  {%- if item.current %} aria-current="page"{% endif %}>{{ item.label }}</a>
{% endfor %}<span class="corner">
{#- Who you are, and the only way in from the page. Reads are public here by
    design, so nothing forces a sign-in and nothing ever offered one: `/login`
    existed and was reachable only by typing it into the address bar, and a write
    answered "sign in to make changes" with no way to do that.

    Drawn empty and filled by the script below, because the shell is rendered by
    eight entry points and threading a viewer through all eight is eight chances
    to forget — and the static export, which has no server and no session, must
    end up with nothing here at all. It does: the fetch fails over file:// and
    this stays hidden. -#}
<span id="who" hidden></span>
{#- Between the two, because that is the order they are reached for: who you are,
    then which palette, then how bright. A native select for the same reason the
    filter bars use one — see `_CONTROL` — and it carries the app's own control
    styling rather than the platform's. -#}
{#- `aria-label` and not a wrapping label with hidden text: this app's rule is
    that every control is named where a reader can find the name, and the check
    that holds it (`test_every_control_on_the_cycle_page_has_a_name`) reads the
    served markup. A label whose only text is invisible is a name for one of the
    two readers. -#}
<span class="schemepick">
  <select id="scheme" title="Colour scheme" aria-label="Colour scheme">
    <option value="">openproj</option>
    {% for family in families %}
    <option value="{{ family.key }}">{{ family.label }}</option>
    {% endfor %}
  </select></span>
<button type="button" id="theme"></button></span></nav>
{#- The home for a message on the pages that have nowhere to put one. Every page
    that announces anything had a `#state` of its own and every one of those was
    inside `{% if editable %}`, so a page you can only read carried no live
    region at all — and a save, a refusal or an explanation that is only drawn is
    one nobody is told about. -#}
{#- One card, three views. The timeline had it and it was good; a graph node
    carries a title and a status glyph and nothing else, and the table's title is
    the one cell whose field — the shaping document — is not on the row at all.
    Drawn from the shell because it is one component: `appetite_weeks` reading as
    three different numbers on three pages is what this codebase has already paid
    for once.

    Outside `live`, which is the block below: a rendered file has no server to
    stream from and every page here draws a card. The first version of this was
    inside it, so the static export — the copy somebody reads on a train, and the
    one that most needs a way to see what a row is about without opening
    seventeen documents — had nowhere to draw one. -#}
<div id="card" role="tooltip" hidden></div>
{#- Before the script that finds it, and not at the end of the body where a
    fixed-position overlay would naturally live: `const CARD = getElementById`
    runs while the parser is here, and an element further down the document does
    not exist yet. It was further down, so `CARD` was null on every page and
    every view drew nothing — in a browser. The shim parses the whole file before
    running anything and answered that the card was fine. -#}
<p id="announce" class="sr-only" role="status" aria-live="polite"></p>
{#- The vocabulary every page draws words from. A `<script type=application/json>`
    and not a template variable inside the script, because that is how every other
    payload on this site travels and it is the one shape `test_no_page_is_assembled_by_substitution`
    already understands. -#}
<script id="words" type="application/json">{{ words|tojson }}</script>
{#- The two ladders' marks, beside the words and for the same reason: the card is
    drawn on the table, the graph and the timeline, and the graph has no `DATA`
    of its own — its payload is cytoscape elements — so a mark read from a
    page's payload is a mark the card carries on two of the three.

    `chipmarks` and not `marks`. The editor's toolbar owns `id="marks"` on the
    record page and the create form — it is the span the mark buttons are drawn
    into — and a second element of that id in the shell made
    `getElementById('marks')` answer with this block
    instead: the toolbar drew its buttons into a script tag, and the editor's own
    tests caught it as an SVG laid out at 0x0. -#}
<script id="chipmarks" type="application/json">{{ cardmarks|tojson }}</script>
{#- The hill's geometry, beside them and for the same reason again. The detail
    page's hill is drawn in Jinja and the card's is drawn in JavaScript, and this
    is the one set of numbers both read: a second implementation of the curve is
    two pages disagreeing about where `ready` is, which is the mistake this
    codebase has already paid for once under the name `appetite_weeks`.

    `id="hill"` here and the `hill` variable the two forms render are different
    things: that one is the script that moves the ball, and this is the payload
    every page that can draw a card carries. -#}
<script id="hill" type="application/json">{{ hillgeom|tojson }}</script>
<script>
// Declared before the content, because the pages' own scripts are inside it and
// some of them announce while loading — the cycle page's receipt, the detail
// page's restored draft. A function in a later <script> is not hoisted into an
// earlier one, so defining this alongside the theme toggle below would have made
// those two messages a ReferenceError instead.
const ANNOUNCE = document.getElementById('announce');

// Stored text into markup, for every script on every page. Page scripts
// build markup by string concatenation out of a file in the plan repository,
// and a title, a login, a tag and an id are all sentences somebody typed: `<`
// opens a tag on everybody else's screen and `"` ends the attribute it is
// sitting in. This lived in the table's script and again in the timeline's,
// which is why the tooltip escaped the text of a chip and not the class beside
// it, and why the combobox — in a third script that had no copy at all —
// escaped nothing. One definition, declared before the content for the same
// reason `announce` is: two classic scripts share one global scope, so a second
// `const esc` anywhere on the page is a SyntaxError rather than a duplicate.
//
// Four characters and not five: `'` is never used to quote an attribute in this
// file, and `&` has to be in the list or `&amp;` in a title comes back out as
// `&` and the escaping is not idempotent.
const esc = value => String(value ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// The ladder the stylesheet actually has rules for, and `_status_class` in
// Python written once more in the language that draws the other half of these
// chips. Escaping an unknown status would be enough to make it harmless and
// would still put `class="chip st-&quot; onmouseover"` in the page: a class
// attribute names a rule, so a status nobody has heard of gets the rung the
// server would have given it rather than its own text.
const STATUS_RUNGS = {{ statuses|tojson }};
const stClass = status => STATUS_RUNGS.includes(status) ? `st-${status}` : 'st-ready';

// --- the hover card ---------------------------------------------------------
//
// One card, three views: the timeline's bars, the graph's nodes and the table's
// titles. It was the timeline's alone, and the other two are the views that need
// it most — a node carries a title and a status glyph, and the title cell is the
// one cell whose real field, the shaping document, is not on the row at all.
//
// One function and not three. This codebase has already paid for one fact
// formatted three ways: `appetite_weeks` read as three different numbers on
// three pages, and the fix was one function every page calls. A card is a
// stronger version of the same risk, because most of what it says is a fact
// somebody else's column also draws.
//
// In the shell rather than in a per-view block, so a page that draws a card and a
// page that does not both have exactly this one.

const CARD = document.getElementById('card');
// The whole prefix, given by the server and empty in a rendered file. A card in
// a static export therefore draws what the row carries and stops; the title
// beside it is still a link into `detail.html#id`, where the document is — the
// same shape as co-editing falling back to a plain textarea.
//
// A template variable rather than a data attribute on `<html>`: the shell knows
// its links at render time, and reading it back out of the DOM is one more thing
// that can be true of the page and false of the document a test drives.
const CARD_BODY_URL = {{ links.body|tojson }};
const CARD_DASH = '<span class="empty">—</span>';

// The word a value is drawn as. From the shell's own map and not from a page's
// payload: the graph has no `DATA` — its payload is cytoscape elements — so a
// card drawn there said `in_progress` where the other two said `In progress`,
// which is the exact failure `HUMAN` exists to prevent, in the one component
// whose whole job is to say the same thing on three pages.
const CARD_WORDS = (() => {
  try { return JSON.parse(document.getElementById('words').textContent); }
  catch (error) { return {}; }
})();
function cardWord(value) { return CARD_WORDS[value] || value; }

// `2026-07-14` as `14.07.2026`. The card's dates keep the century — it is the one
// place a date is read rather than scanned, and there is room for four digits —
// and they are day-first like every other date the app draws.
function longDate(iso) {
  const [year, month, day] = String(iso).split('-');
  return day ? `${esc(day)}.${esc(month)}.${esc(year)}` : esc(iso);
}

// `{status: {...}, priority: {...}}` — the same two maps the table's chips and
// the graph's nodes draw from, off the shell rather than off a page's payload.
const CARD_MARKS = (() => {
  try { return JSON.parse(document.getElementById('chipmarks').textContent); }
  catch (error) { return {status: {}, priority: {}}; }
})();
function cardMark(ladder, value) {
  return (CARD_MARKS[ladder] || {})[value] || '';
}

// Bodies already fetched, by id. A pointer crossing a column of rows asks for the
// same document several times a second otherwise — and the answer cannot change
// under a page that has not been reloaded, because a save reloads the rows.
const CARD_BODIES = new Map();

// The curve, the stops and the sentence each stop means, drawn by the server and
// read here rather than worked out again. Absent on a page with no card, which is
// why every use of it is guarded.
const HILL = JSON.parse(document.getElementById('hill')?.textContent || 'null');

// The card's hill: the same picture as the detail page's, at two thirds the size
// and with no stops on it. A card is a look and not a control — every gesture it
// could offer would commit a status change from a box that disappears when the
// pointer moves.
function hillHtml(status) {
  if (!HILL) return '';
  const ladder = HILL.ladders.record;
  const place = word => `left: ${100 * HILL.stops[word][0] / HILL.box[0]}%; `
    + `top: ${100 * HILL.stops[word][1] / HILL.box[1]}%; `
    + `--nx: ${HILL.normals[word][0]}; --ny: ${HILL.normals[word][1]}`;
  const ghosts = ladder
    .map(word => `<span class="hill-ghost" style="${place(word)}"></span>`)
    .join('');
  // A word this ladder does not have gets no ball, exactly as the server does it:
  // `status` holds whatever a hand-edited file holds, and the alternative — the
  // chip's `st-ready` fallback — would put an unrecognised status on the summit.
  // It is also what makes `hill-${status}` safe to write into a class at all.
  const known = ladder.includes(status);
  const ball = known
    ? `<span class="hill-ball hill-${status}" data-word="${esc(cardWord(status))}"`
      + ` style="${place(status)}"></span>`
    : '';
  const said = `${cardWord(status)} — ${known ? HILL.where[status] : 'not on the hill'}`;
  const dim = !known || HILL.off.includes(status);
  return `<span class="card-hill"><span class="hill${dim ? ' hill-off' : ''}"`
    + ` role="img" aria-label="${esc(said)}">`
    + `<svg viewBox="0 0 ${HILL.box[0]} ${HILL.box[1]}" aria-hidden="true" focusable="false">`
    + `<path class="hill-ground" d="M${HILL.apron[0]} ${HILL.ground}`
    + `L${HILL.apron[1]} ${HILL.ground}"/>`
    + `<path class="hill-line" d="${HILL.path}"/></svg>`
    + ghosts + ball + '</span></span>';
}

function cardHtml(row, extra) {
  // An owner who is also an assignee is one person, not two. The scheduler reads
  // them that way — `_people_on` dedupes — and a box that says "ann, ann" is a
  // box nobody trusts the rest of.
  const others = (row.assignees || []).filter(who => who && who !== row.owner);
  const size = row.weeks ?? row.size;
  const facts = [
    ['Owner', row.owner ? esc(row.owner) : CARD_DASH],
    ...(others.length ? [['With', esc(others.join(', '))]] : []),
    ...(row.cycle ? [['Cycle', esc(String(row.cycle))]] : []),
    ...(size == null ? [] : [['Appetite', esc(String(size))
      + (Number(size) === 1 ? ' week' : ' weeks')
      + (row.estimated ? ' <span class="guess">(assumed)</span>' : '')]]),
    // The count the table's column gave up, with the bar it draws there — the
    // card is where a number that is read rather than scanned belongs, and it is
    // beside what the number was counted from.
    ...(row.progress == null ? [] : [['Progress',
      `<span class="num">${esc(row.progress_text)}</span>`
      + `<span class="meter"><span style="width: `
      + `${Math.round(row.progress * 100)}%"></span></span>`]]),
    ['Scheduled', row.start && row.end
      // The card has room for the century, and it is the one place a date is read
      // rather than scanned: `14.07.2026`, day first like every other date here.
      ? `<span class="num">${longDate(row.start)}</span> to `
        + `<span class="num">${longDate(row.end)}</span>`
      : CARD_DASH],
    ...((row.tags || []).length ? [['Tags', esc(row.tags.join(', '))]] : []),
    ...extra,
  ];
  // The class attributes are escaped too, and not only the words beside them.
  // They were not: a status reading `ready" onmouseover=alert(1) x="` came back
  // out of this line as a real event handler that fired on hover, on the one
  // element of the box a pointer is guaranteed to cross.
  // Kind, then priority, then status — the order jcanton asked for on
  // 2026-08-21, and the two ladders drawn exactly as the table draws them: mark
  // and word inside the same chip, so a card and a row say one fact one way. The
  // maps are the control bar's (`_FILTER_JS`), read through `typeof` because a
  // page can carry a card without carrying a filter bar.
  const chip = (klass, glyph, word) =>
    `<span class="chip ${klass}">` +
    (glyph ? `<span class="chipmark" aria-hidden="true">${esc(glyph)}</span>` : '') +
    `<span class="chipword">${esc(word)}</span></span>`;
  const marks = [
    chip(`kind-${esc(row.kind)}`, '', cardWord(row.kind)),
    ...(row.priority
      ? [chip(`pri pri-${esc(row.priority)}`, cardMark('priority', row.priority),
              cardWord(row.priority))]
      : []),
    // The status chip stays, and the hill goes under it. On the detail page the
    // hill replaces the chip because a `<dt>` beside it says STATUS; a card has
    // no labels on its chip line, so the hill alone would be a picture with no
    // word — and the two are not the same fact twice here, because the word says
    // which status and the shape says which side of the hill that is.
    ...(row.status
      ? [chip(stClass(row.status), cardMark('status', row.status),
              cardWord(row.status))]
      : []),
  ];
  return `<p class="card-title">${esc(row.title)}</p>` +
    `<p class="card-chips">${marks.join(' ')}` +
    (row.status ? hillHtml(row.status) : '') + '</p>' +
    '<dl>' + facts.map(([name, value]) => `<dt>${name}</dt><dd>${value}</dd>`).join('') +
    '</dl>' + (row.tip ? `<p class="card-why">${esc(row.tip)}</p>` : '');
}

// What is on the row, immediately; the document underneath it when it arrives.
// Two steps rather than one await, because a card that appears only once a fetch
// has answered is a card that flickers in behind the pointer — and on a plan
// served over a slow link, one that arrives after the pointer has moved on.
let cardShowing = null;

// Returns the promise the document arrives on, which nothing in the pages waits
// for and every test does: a fire-and-forget fetch is a thing a test can only
// wait for by guessing, and a guess that is too short reports a card that works
// as a card that draws nothing.
function showCard(row, x, y, extra) {
  if (!CARD || !row) return Promise.resolve();
  clearTimeout(cardTimer);
  clearTimeout(cardLeaving);
  cardShowing = row.id;
  CARD.innerHTML = cardHtml(row, extra || []);
  CARD.hidden = false;
  placeCard(x, y);
  // The body, in the same paint as the fields where it can be. `queueCard`
  // starts the fetch when the pointer arrives and this runs 400ms later, so by
  // now the answer is usually sitting in `CARD_BODIES` — and drawing it in a
  // second pass made the card visibly grow and re-place itself a moment after
  // appearing, which is what jcanton reported on 2026-08-20. Only the fields
  // were ever certain, so a slow answer still falls back to the two passes
  // rather than holding the card back and showing nothing at all.
  if (CARD_BODY_URL && CARD_BODIES.has(row.id)) {
    fillCardBody(row.id);
    return Promise.resolve();
  }
  return CARD_BODY_URL ? fillCardBody(row.id) : Promise.resolve();
}

// A pointer crossing a table on its way somewhere else is not a question, and a
// card that answers it anyway flashes a box over every row on the way past. So
// hovering ASKS for a card and waits; the wait is cancelled by leaving.
//
// 600ms, raised from 400 — jcanton, 2026-08-24: the card came up too eagerly
// while reading the table. This is the only hover-intent delay in the app, so
// the number is this app's own judgement, not a convention: long enough that
// pausing over a row while reading it does not open a box over the next one,
// short enough that pointing and waiting does not feel broken. The keyboard
// path on the timeline does not go through here — focus is deliberate, and a
// delay after a deliberate act is a page that ignored you.
const CARD_DELAY = 600;
// And the grace on the way out, which is the whole reason the card can be
// scrolled: the pointer has to cross the gap between the row and the box, and a
// card that goes the instant the row is left cannot be reached.
const CARD_GRACE = 220;
let cardTimer = 0;
let cardLeaving = 0;

function queueCard(row, x, y, extra) {
  if (!CARD || !row) return;
  clearTimeout(cardTimer);
  clearTimeout(cardLeaving);
  // Ask for the document NOW, and draw it in 600ms. The wait before a card
  // appears is hover-intent, not politeness, and spending it on the round trip
  // is free: by the time the card is drawn the answer is normally already here,
  // so the fields and the body arrive in one paint. Nothing is drawn from this —
  // `warmCardBody` only fills the cache — so a pointer crossing a table still
  // opens no card, it just leaves a few bodies behind it.
  if (CARD_BODY_URL) warmCardBody(row.id);
  // Already showing this one: the pointer moved inside the same row, which is
  // not a new question. Notably it does NOT move the card — a box that follows
  // the pointer is a box you cannot put the pointer into.
  if (!CARD.hidden && cardShowing === row.id) return;
  cardTimer = setTimeout(() => showCard(row, x, y, extra), CARD_DELAY);
}

// The fetch on its own, with nothing drawn from it. Two callers: the hover, which
// wants the answer before it needs it, and `fillCardBody`, which needs it now.
// One in-flight request per id, because a pointer that leaves a row and comes
// back within the delay would otherwise ask twice for the same document.
const CARD_ASKED = new Map();
function warmCardBody(id) {
  if (CARD_BODIES.has(id)) return Promise.resolve();
  if (CARD_ASKED.has(id)) return CARD_ASKED.get(id);
  const asking = fetch(CARD_BODY_URL + encodeURIComponent(id))
    // A refusal is not a document. `ok` and not a `catch` alone: a 404 is a
    // resolved promise with an error page in it, and `.json()` on that throws
    // somewhere far away from the request that caused it.
    .then(response => response.ok ? response.json().then(said => said.html || '') : '')
    // Offline, or a policy that refuses the request. The card keeps what it
    // already drew; the row's own fields are the part that was never in doubt.
    .catch(() => '')
    .then(html => { CARD_BODIES.set(id, html); CARD_ASKED.delete(id); });
  CARD_ASKED.set(id, asking);
  return asking;
}

async function fillCardBody(id) {
  if (!CARD_BODIES.has(id)) await warmCardBody(id);
  // The pointer may have moved on while the answer was in flight, and the card
  // may already be describing something else — or nothing.
  if (cardShowing !== id || CARD.hidden) return;
  const html = CARD_BODIES.get(id);
  if (!html) return;
  // Replaced and never appended. Two answers can be in flight for one card — the
  // pointer leaves and comes back, or a cached body lands in the same tick as a
  // fetched one — and appending drew the shaping document twice inside one box,
  // which is what jcanton saw and could not reproduce.
  const already = CARD.querySelector('.card-body');
  const body = already || document.createElement('div');
  body.className = 'card-body';
  // The server rendered this markdown, with HTML disabled in the parser, through
  // the same function the detail page uses. It is the one string on this page
  // that is markup on purpose.
  body.innerHTML = html;
  if (!already) CARD.appendChild(body);
  placeCard(cardAt.x, cardAt.y);
}

// Where the pointer was, kept so a card that grows a body when the fetch lands
// can be placed again without one.
let cardAt = {x: 0, y: 0};

function placeCard(x, y) {
  cardAt = {x, y};
  const box = CARD.getBoundingClientRect();
  const left = x + 14 + box.width > innerWidth - 8 ? x - 14 - box.width : x + 14;
  const top = y + 14 + box.height > innerHeight - 8 ? y - 14 - box.height : y + 14;
  CARD.style.left = Math.max(8, left) + 'px';
  CARD.style.top = Math.max(8, top) + 'px';
}

// Asked for by a pointer leaving, and answered a moment later: the gap between
// the row and the card is a place the pointer has to be allowed to cross.
function hideCard() {
  if (!CARD) return;
  clearTimeout(cardTimer);
  clearTimeout(cardLeaving);
  cardLeaving = setTimeout(hideCardNow, CARD_GRACE);
}

// No grace. For the things that are not a pointer leaving a row: a node dragged
// out from under the card, a canvas panned, a filter redrawing the rows.
function hideCardNow() {
  if (!CARD) return;
  clearTimeout(cardTimer);
  clearTimeout(cardLeaving);
  cardShowing = null;
  CARD.hidden = true;
}

// The card is a thing you can put the pointer in, which is what makes a long
// document readable: it takes pointer events, it does not follow the pointer
// once it is up, and it stays while the pointer is inside it.
if (CARD) {
  CARD.addEventListener('pointerenter', () => clearTimeout(cardLeaving));
  CARD.addEventListener('pointerleave', hideCard);
}

// The re-set a repeated message is waiting on. One variable and not one per
// region, because `announce` picks the same region every time on a given page:
// `#state` if the page has one, the hidden region otherwise.
let repeating = 0;

// `announce` and not `say`: two classic scripts on one page share one global
// scope, and the graph and the cycle page each already own a `say`.
function announce(message) {
  // The page's own place for a message where it has one, which is visible and is
  // already a live region — announcing into both would say everything twice.
  const where = document.getElementById('state') || ANNOUNCE;
  // Whatever the last repeat was waiting to put back is no longer the message.
  // Without this, the cycle page's `say('')` on every staged edit left one timer
  // per edit, each of them holding an empty string, and they fired *after* the
  // save that followed — so "Saved 2 changes" appeared and was then blanked by
  // an edit made before it.
  clearTimeout(repeating);
  if (where.textContent === message) {
    // Nothing was said and nothing is being said: no region to change, and no
    // timer to leave behind for a later message to trip over.
    if (message === '') return;
    // A live region speaks when its contents CHANGE, so refusing the same cell
    // twice would have been announced once. Cleared and re-set on a timer rather
    // than a frame, because a frame never comes in a tab nobody is looking at —
    // and the two-minute autosave says its receipt into exactly that tab.
    where.textContent = '';
    repeating = setTimeout(() => { where.textContent = message; }, 0);
    return;
  }
  where.textContent = message;
}

// One reading of a write's answer, for every page that writes.
//
// A 500 answers in `text/plain`, and `response.json()` on one rejects — which
// left `flush()` unresolved with Save disabled and the bar still claiming N
// unsaved changes, and nothing said about any of it. An answer nobody can parse
// is an answer with no keys in it, which every caller below already handles.
async function answerOf(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

// What to say about a write the server would not do.
//
// There is no `detail` on a 409: the answer carries `conflict`, the report
// naming the file and every field that disagreed. Three of the five write paths
// read `answer.detail` there, so the one answer that means *somebody else moved
// the plan* printed as "refused".
//
// 409 is the only status this reads by number, and adding a second one is a
// bigger decision than it looks. A plan whose history has forked answers 503
// with a `detail` — `_refusal` in `web.py` argues the code — and it falls
// through to the line below on purpose: the sentence it carries names the two
// commits and says what has to happen to the repository, which is more than any
// wording this file could invent for it. Special-casing it here would replace
// that with a guess.
function refusal(answer, status) {
  if (status === 409) return answer.conflict || 'somebody else changed this first';
  return answer.detail
    || (answer.problems || []).map(problem => problem.message).join('; ')
    || 'refused';
}

// How much window is left for the one box on a page that is meant to fill it,
// answered the same way by the three views that have one: the graph's canvas, the
// table's rows, the timeline's plot. The box says which it is with `data-fills`.
//
// Both previous answers were guesses at the same measurement. `#cy` asked for
// `78vh`, a fraction of the window that knows nothing about the rows above the
// canvas or the sticky commit bar below it — at an 806px window the canvas ran
// from 268 to 899 while the bar sat across 759–806, so 140px of it was underneath
// the bar and two nodes loaded hidden there. `.table-scroll` asked for
// `100vh - 15rem`, which is the same guess with the stack counted by hand, and it
// had already been wrong once: the page gained a heading and the box ran off the
// bottom of the window.
//
// So nothing below enumerates what is above the box or below it. `above` is where
// the box begins and `below` is everything after it as far as the end of the
// body — commit bar, its margin, the page's own bottom padding — which means a
// row added, moved or dropped is measured rather than re-counted. Being
// re-counted by hand is how both of those guesses went wrong.
const ROOT = document.documentElement;
// Under this the window has nothing left to give and the page scrolls instead —
// which is the honest answer at a window that short, and better than a canvas
// sized to a sliver. It is a floor on the number REPORTED, not a height the box
// is padded to: the table and the timeline take it as a cap, so a plan of two
// bars is still two bars tall and only the graph, which has no size of its own,
// is actually this tall.
// 9rem, resolved against the root's own font size rather than assumed to be
// 144px: a reader who has asked for larger text has taller rows to fit as well.
const ROOM_FLOOR = 9 * parseFloat(getComputedStyle(document.documentElement).fontSize);
let roomIs = '';
// What the subtraction above cannot see, learned by looking at the result.
//
// `--room` is `innerHeight - above - below`, and `below` is measured as
// `document.body`'s bottom less the box's. That is every element after the box
// AS THE BODY REPORTS IT, which is not always every pixel the page turns out to
// be: a margin that collapses through the body, a sub-pixel that rounds the
// wrong way, a root-level padding the body's own border box excludes, or simply
// a browser that computes one of those differently — jcanton, 2026-08-25, still
// seeing a page scrollbar on `/table` in Firefox at a window where Chrome has
// none, on a build where the arithmetic says there should be nothing left over.
//
// So the formula is the estimate and the PAGE is the authority. After the box is
// given its height, whatever the document still overflows by is added here and
// taken off the next answer. It is remembered rather than recomputed from
// nothing each time, because the thing it is correcting for does not go away
// when the window moves.
//
// This is `chromeOverhead`'s bargain in `table.py`, one level up: "Once round to
// find out what the border costs, and once more to pay for it." A measurement
// that can be checked against reality should be.
let roomSlack = 0;
function measureRoom() {
  const box = document.querySelector('[data-fills]');
  // The timeline hides its plot when there are no bars, and a box with no layout
  // reports zeros — which would hand every page with an empty view a room of one
  // window minus nothing.
  if (!box || !box.getClientRects().length) return false;
  const rect = box.getBoundingClientRect();
  // From the top of the document, so a page that happens to be scrolled when this
  // runs measures the same as one that is not.
  const above = rect.top + scrollY;
  // **What is actually after the box, element by element, and not the distance
  // to the body's bottom.**
  //
  // It was `document.body.getBoundingClientRect().bottom - rect.bottom`, and
  // that stopped being the same question the moment the body became a column
  // with a pinned footer: `#main` grows to fill the window, so the space it
  // grew into sits between this box and the body's bottom and was counted as
  // something to leave room for. The box could then never grow into it — the
  // formula returned the height it already had, a fixed point, and the deck sat
  // with a band of empty page between its last slide and the footer.
  //
  // Walking the elements says what a reader means by "below": the things that
  // have to stay visible. Flex slack is not an element, so it is not counted,
  // and the box grows until there is none left. `offsetHeight` plus margins,
  // because a margin is room the layout takes and a border box does not report —
  // the same omission that let the footer's own margins go unmeasured.
  let below = 0;
  for (let el = box; el && el !== document.body; el = el.parentElement) {
    for (let after = el.nextElementSibling; after; after = after.nextElementSibling) {
      const style = getComputedStyle(after);
      if (style.display === 'none' || style.position === 'fixed' ||
          style.position === 'absolute') continue;
      below += after.getBoundingClientRect().height
        + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
    }
    const own = getComputedStyle(el.parentElement || document.body);
    below += parseFloat(own.paddingBottom) || 0;
  }
  // Floor, not round. These are sub-pixel measurements and the whole point of the
  // number is that the page does not scroll: half a pixel rounded up is a
  // scrollbar, and half a pixel rounded down is invisible.
  // **One pixel given away, on purpose.** `above` and `below` are sub-pixel
  // measurements and the height applied from them is an integer, so the two can
  // disagree by a fraction — and a fraction of a pixel of overflow is a real
  // scrollbar in Firefox while `scrollHeight` and `clientHeight`, which are
  // rounded integers, report no overflow at all. That is why the slack above
  // could not see it: the correction asks the document a question the document
  // answers in whole pixels.
  //
  // jcanton, 2026-08-25, after the slack shipped: still a scrollbar on `/table`
  // in Firefox, "only at 100% page zoom" — the one zoom where CSS pixels and
  // device pixels line up and nothing else rounds the fraction away — "and it
  // must be just 1-2px because there is nothing to scroll".
  //
  // A pixel of a box that is hundreds tall is invisible. A scrollbar is not.
  const value = Math.max(
    ROOM_FLOOR, Math.floor(innerHeight - above - below - roomSlack) - 1) + 'px';
  if (value === roomIs) return false;
  roomIs = value;
  ROOT.style.setProperty('--room', value);
  // For anything that has to be told in its own language rather than in CSS:
  // cytoscape measures its container when it is built and never looks again.
  dispatchEvent(new Event('openproj:room'));
  return true;
}

// Measured again until the answer stops moving, and at most a few times.
//
// Giving the box its height can take the page's own scrollbar away, and on a
// platform whose scrollbar has width that widens the page and rewraps the filter
// bar above the box — so the first answer was measured against a layout that the
// answer itself replaced. Where scrollbars are overlays it settles on the first
// pass and the second is one subtraction; the bound is what says a layout that
// has not settled in four frames is not going to.
//
// `fitRoom` takes no arguments on purpose: it is handed straight to
// `addEventListener`, and a counter as a default parameter would have been
// re-seeded with an Event on every resize.
function settleRoom(passes) {
  const moved = measureRoom();
  // What the page still overflows by, asked AFTER the box has been given its
  // height. Anything here is height the subtraction did not know about, so it
  // goes into the slack and comes off next pass. Bounded by the same pass count
  // as the loop it lives in: a layout that has not settled in four frames is not
  // going to, and a correction that keeps growing is better stopped than
  // trusted.
  const over = ROOT.scrollHeight - ROOT.clientHeight;
  if (over > 0 && passes > 1) {
    roomSlack += over;
    requestAnimationFrame(() => settleRoom(passes - 1));
    return;
  }
  if (moved && passes > 1) requestAnimationFrame(() => settleRoom(passes - 1));
}
// The slack is forgotten before each fresh settle and learned again. It corrects
// for whatever the current layout hides, and a window that has just grown may
// hide less — so carrying the old number forward would leave the box short of
// the room it now has, for ever, with nothing on screen to say why.
function fitRoom() { roomSlack = 0; settleRoom(4); }
</script>
<main id="main">
{#- What the plan holds that is not a record, on every page because the shell
    draws it and no page can forget. Inside `<main>` and first, so "Skip to the
    content" lands on it: everything in these files is missing from every count,
    every row, every bar and every node on the page, and there is nothing else
    that says so.

    The quiet failure is the one this is here for. Before it, a file that would
    not parse answered 500 on all eight routes — loud, permanent, and at least
    unmistakable. Skipping the file and saying nothing would trade that for a
    table that draws fifteen of sixteen tasks and looks completely normal, which
    is worse: you cannot act on what you cannot see is missing. -#}
{% if unreadable %}<section id="unreadable" class="unreadable">
<p class="headline">{{ headline }}</p>
<ul>{% for one in unreadable %}
  <li><code>{{ one.path }}</code> — {{ one.why }}</li>{% endfor %}
</ul>
<p class="hint">Fix them in git and reload. Everything else in the plan is here.</p>
</section>
{% endif -%}
{#- The pile banner: the loud middle of the deferred push's escalation, between
    the table's quiet per-row mark and the 503 the store answers past the pile
    ceiling (design/deferred-push.md, "Saying it on the page"). In the shell
    because the graph, the timeline, the cycles and the record page have no
    mark of their own and rely on it; in flow at the top of <main>, in the
    `.unreadable` strip's own position and shape, because "saves that have not
    reached GitHub" is the same KIND of news as "files that are not on this
    page" — about the plan, not about a control. Live pages only: a rendered
    file has no server whose pile this could be. Filled by `showPile` below,
    numbers only, through textContent. -#}
{% if live %}<div id="pile" role="status" aria-live="polite" hidden></div>
{% endif -%}
{{ content }}
</main>
{#- What is running, and what it is running ON. jcanton, 2026-08-25: "can we have
    the app version show up in the web interface?"

    Two facts and not one, because they answer different questions and reading
    one for the other has already cost this project an afternoon — `AGENTS.md`
    says so in as many words: the version moves only on a deploy and names this
    CODE; the plan's sha moves whenever anybody saves a record and names the
    DATA. Somebody who reads a moving sha as the version concludes a deploy
    landed because a colleague edited a pitch.

    The version is rendered; the sha is filled in by the health poll that is
    already running for the pile banner — no second request for it, and on a
    rendered file there is no server to ask, so that half simply stays empty.

    In the footer because it is reference and not news. It is on every page, out
    of the reading column, and it is the first thing anybody asks for when a
    page behaves unexpectedly. -#}
{#- Three facts, and the separators between them are the stylesheet's rather than
    the template's. Written as literal ` · ` text this row said `openproj 0.37.0 ·
    · Report issue` for the whole of the second or two before the health poll
    answered, and permanently on any page where it never did — a dangling
    separator beside an empty box, which reads as a page that failed to draw
    something rather than as a fact that has not arrived. `#planhead:empty` takes
    the span out and `* + *::before` takes its dot with it. -#}
<footer id="build">
  <a href="https://github.com/jcanton/openproj/releases/tag/v{{ version }}">openproj
    {{ version }}</a>
  {%- if live %}<span id="planhead" title="the plan's own commit"></span>{% endif %}
  {#- jcanton, 2026-08-27, asking for it here and not in the nav: it is the thing
      you reach for at the moment the page in front of you is wrong, which is the
      moment you are already reading this row for the version to quote. `issues/new`
      on the TOOL's repository and never the plan's — a bug in the app is not a
      record in somebody's plan, and the two repositories stay two. -#}
  <a href="https://github.com/jcanton/openproj/issues/new">Report issue</a>
</footer>
<script>
// **Sign-in, the plan picker and the theme toggle move to the footer on a
// phone.** jcanton, 2026-08-26: "I'd move the sign-in and theme and light/dark
// pickers to the footer, or an overflow hamburger menu in the nav: currently
// they occupy one extra row".
//
// The footer and not a hamburger, and the reason is what each of these three
// controls is. A hamburger is for things you go looking for; these are things
// you set once — which plan, which theme — and then never touch, plus a sign-in
// that reads are deliberately public without. A row of its own above the plan is
// the most expensive place on a phone to keep three controls nobody presses
// twice, and the footer already exists on every page with a line of room in it.
//
// **A relocation and not a second copy.** CSS cannot move a node between
// parents, and rendering the corner twice would be two sign-in buttons in one
// document — two ids, two `#who` fills, and a script that writes to whichever it
// finds first. So the one element is appended to whichever parent the width
// calls for, both ways, whenever the query changes: a phone turned to landscape
// mid-session must not leave the theme toggle in a footer the nav has room for.
//
// `NARROW` and not `PHONE`, which `_FILTER_JS` already declares on the three
// filtering views — these two scripts share one global scope and a page carrying
// both would redeclare it. Same number, and it is the app's one narrow
// breakpoint; the CSS above says it in `@media (max-width: 40rem)`.
const NARROW = matchMedia('(max-width: 40rem)');
const CORNER = document.querySelector('nav .corner');
const NAVBAR = document.querySelector('nav');
const BUILD = document.getElementById('build');

function stowCorner(narrow) {
  if (!CORNER || !BUILD || !NAVBAR) return;
  const home = narrow ? BUILD : NAVBAR;
  // Appending a node that is already the last child of `home` is a no-op that
  // still moves focus off it in some browsers, so the question is asked first.
  if (CORNER.parentElement !== home) home.append(CORNER);
}
stowCorner(NARROW.matches);
NARROW.addEventListener('change', event => stowCorner(event.matches));

// No third state to cycle through: with nothing stored the page follows the
// system, and the first click stores the opposite of whatever is on screen.
const THEME = document.getElementById('theme');

function theme() {
  return document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function labelTheme() {
  const dark = theme() === 'dark';
  THEME.textContent = dark ? '\u2600' : '\u263e';
  THEME.title = dark ? 'Light mode' : 'Dark mode';
  THEME.setAttribute('aria-label', THEME.title);
}

THEME.onclick = () => {
  const next = theme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  remembered.set('openproj:theme', next);   // and a browser that refuses still switches
  labelTheme();
  // Anything painted by script rather than by the stylesheet — the graph — has
  // to be told, because its colours were read once when it was built.
  dispatchEvent(new Event('themechange'));
};

// A page opened while the system is dark and never clicked has no stored value,
// so it follows the system as it changes.
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', labelTheme);
labelTheme();

// The palette. A scheme is sixteen colours on the root element and nothing else,
// so switching one is one attribute — and the graph, which read its colours once
// when it was built, is told the same way the light/dark switch tells it.
const SCHEME = document.getElementById('scheme');
if (SCHEME) {
  SCHEME.value = document.documentElement.dataset.scheme || '';
  SCHEME.onchange = () => {
    const chosen = SCHEME.value;
    if (chosen) document.documentElement.dataset.scheme = chosen;
    else delete document.documentElement.dataset.scheme;
    remembered.set('openproj:scheme', chosen);
    dispatchEvent(new Event('themechange'));
  };
}

// Who is signed in, asked rather than rendered.
//
// The session is an HttpOnly cookie, so a script cannot read it and the server
// is the only one who knows. `/api/me` answers `{}` for a stranger rather than
// 401: a page nobody has to sign in to read would otherwise log an error on
// every load for the ordinary case, and an error that means "everything is fine"
// is an error nobody reads twice.
//
// The whole thing is behind a catch because the static export runs this same
// script from file://, where there is no server to ask. The corner stays hidden,
// which is what a file with no session should show.
(async () => {
  const WHO = document.getElementById('who');
  let me = {};
  try {
    const response = await fetch('/api/me', {headers: {'Accept': 'application/json'}});
    if (!response.ok) return;
    me = await response.json();
  } catch (error) { return; }

  // Built as elements rather than as a string of markup, for two reasons that
  // point the same way. A login is somebody's typed text, and `textContent`
  // cannot be talked into being a tag. And the export's dead-link check reads
  // every href attribute in the file as a page that must exist — the check reads
  // the source, not the DOM, so a link that only ever exists where a server
  // answered would have had to be written in as an exception, and an exception
  // is a hole somebody has to keep true. (The check is literal enough that this
  // very comment failed it once, spelling the attribute out.)
  const element = (tag, text, klass) => {
    const made = document.createElement(tag);
    if (text !== undefined) made.textContent = text;
    if (klass) made.className = klass;
    return made;
  };

  WHO.replaceChildren();
  if (!me.login) {
    // A link and not a form: `/login` starts an OAuth redirect, which is a
    // navigation, and the state cookie it sets is what makes the callback safe.
    const link = element('a', 'Sign in');
    link.href = '/login';
    WHO.append(link);
  } else {
    WHO.append(element('span', me.login));
    // Signed in and not a member is signed in and still cannot write, and that
    // is the state worth saying out loud: the alternative is a refusal at the
    // moment of saving, which reads like the tool is broken.
    if (!me.member) WHO.append(element('span', `(not in ${me.org})`, 'warn'));
    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/logout';
    form.append(element('button', 'Sign out'));
    WHO.append(form);
  }
  WHO.hidden = false;
})();

// `2026-09-01` as `01.09.2026` — `_read_date`'s twin, and the second copy of a
// format written in two languages.
//
// It has to be in both: the server prints the dates a page is rendered with, and
// this one has to change as somebody picks a date, which is a thing only the
// browser sees. `test_both_halves_of_the_app_write_a_date_the_same_way` drives
// the two against the same strings rather than trusting them to agree.
//
// Anything that is not three dash-separated parts comes back untouched, which
// covers the empty box and the em dash below.
function readDate(iso) {
  const parts = String(iso || '').split('-');
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : String(iso || '');
}

// **There is no echo beside a date box any more**, and the trade is worth
// stating because it is one.
//
// Every `<input type=date>` was followed by a `.iso` span repeating the value in
// dd.mm.YYYY, because the box itself is drawn by the browser in the READER's
// locale — the same stored 2026-09-01 reads as 01/09/2026 at one desk and
// 09/01/2026 at the next, and neither reader can tell which. The echo said which
// day it was in the app's own format.
//
// jcanton, 2026-08-25, having used it: "the date pickers in the cycle are still
// mm/dd/yyyy and on their right is the date reprinted as dd.mm.yyy ... delete the
// echo: it's confusing to have both formats." Two formats on one line is a
// question rather than an answer, and he is the reader.
//
// What comes back is the original ambiguity, for anybody whose browser draws a
// month first. Chrome and Safari honour the document's `lang` and already draw
// 25.08.2026; Firefox follows the operating system and will not. That is the
// cost, it is known, and it was chosen — this note is here so the next person to
// meet a misread date finds the decision rather than the bug.
//
// `readDate` stays. It is the browser's half of one format written in two
// languages, `test_both_halves_of_the_app_write_a_date_the_same_way` drives it
// against `_read_date`, and it is what any future date this page draws goes
// through.

// The box is measured once the page around it exists, and again on each of the
// two things that move the answer.
//
// A `ResizeObserver` on the body was the first version of this and it is not
// here, because it could not be tested: an observer is delivered on a rendering
// frame, and a headless run under a virtual clock produces two frames in three
// seconds while a background tab produces none — so a run that reported "it
// works" and a run of an observer that had been deleted were the same run. A
// mechanism whose absence no test can see is the shape of every defect the six
// audits before this one turned up. These two are events, and an event fires
// whether or not anybody is looking at the page.
//
// What that costs is the case neither event covers: a row that appears below the
// box after load without the window changing. There is one — the graph's commit
// bar, which grows a line of buttons on entering edit mode — and it calls
// `fitRoom` itself.
fitRoom();
addEventListener('resize', fitRoom);
// The inlined face swaps in after the first layout, and every row above the box
// changes height with it. Same hook the graph repaints its own tokens on, and for
// the same reason: a measurement taken before the face lands is a measurement of
// the fallback's metrics.
if (document.fonts) document.fonts.ready.then(() => fitRoom());

// --- where "back" goes ------------------------------------------------------
//
// The record page's back link read "← all records" and went to the records list
// from wherever you had arrived: open a record off the table, the graph or a
// cycle, press back, and you landed on a third page with the filter, the sort
// and the scroll you had left behind all gone. The page that knows where you
// came from is the page you came FROM, so it says so on the way out.
//
// A stamp in the tab's own store and not `document.referrer`, which is empty
// over `file://` and would therefore have been dead in the static export — the
// copy that is hardest to get back to a view in — in every browser there is.
// A store is dead there in some of them and not others: Chrome 151 on macOS
// gives a `file://` document the origin `file://` and a working store, and the
// Linux headless build the tests run on gives it an opaque `null` origin and
// refuses. So the export is best-effort by construction, which is what the
// rendered link being the answer already means: where the store is refused the
// back link is the records list, exactly as it was before any of this.
//
// The switch is `ORIGIN`, which the shell fills in for a view and leaves empty
// for the two pages that are reached from one. Nothing here decides between
// them twice: a page with a name stamps, a page without one reads.
const ORIGIN_KEY = 'openproj:origin';
const ORIGIN = {{ origin|tojson }};
if (ORIGIN) {
  // `pathname` and `search`, not `href`. It is what makes the stamp a same-page
  // return rather than a same-view one — `/table?owner=ann` and `/cycle/37` are
  // both somewhere you were standing — and it is the allowlist the read below
  // leans on: every address this app serves begins with a slash, and so does
  // every file it exports, whose `pathname` is an absolute path on disk.
  forThisTab.set(ORIGIN_KEY, JSON.stringify({
    href: location.pathname + location.search, label: ORIGIN,
  }));
}

// An address off a store is an address somebody's devtools can write, and an
// `href` is the one field here a scheme can be smuggled into. `ORIGIN_PATH` is
// the allowlist, and it is a template variable rather than a literal for a
// reason worth knowing: this block is inside a Python string that is not raw, so
// a backslash written here is eaten before the browser ever sees it. Writing the
// pattern here first made it an unterminated character class — a SyntaxError
// that costs the whole script and not one line.
const ORIGIN_PATH = new RegExp({{ origin_path|tojson }});

// **Where you came from, or nothing.** A function rather than the inline read it
// was, because a second caller turned up: deleting a record navigates away, and
// the page it should navigate to is the page the back link would have taken you
// to. Two reads of one store, with one allowlist between them and one place to
// change if the shape ever moves.
//
// Guarded, so a caller may ask on a page that stamped rather than read — the
// question "where did I come from" is answerable anywhere, and the answer on a
// view is simply the view before it, which is nothing anybody wants.
function cameFrom() {
  const from = forThisTab.map(ORIGIN_KEY);
  if (typeof from.href !== 'string' || !ORIGIN_PATH.test(from.href) || !from.label) return null;
  return {href: from.href, label: from.label};
}

if (!ORIGIN) {
  const from = cameFrom() || {};
  if (from.href) {
    // Every article, because the static export writes the whole corpus into one
    // `detail.html` and each record in it carries its own back link. `a.origin`
    // and not `.back a`: the sign-in control the shell fills in later is also
    // an `<a>`, and in the full-page era (gone 2026-08-24) the record page
    // moved it and the theme toggle into this very row — the selector names
    // the one link it means, and stays right if anything joins it again.
    for (const back of document.querySelectorAll('a.origin')) {
      // `setAttribute` and not `back.href =`, which are the same thing in a
      // browser and not in `tests/js/drive.js`: the shim has no reflection, so
      // the property would be set, the attribute would still hold the rendered
      // address, and a test reading either one would be reading a different
      // page from the one a reader gets. Say the thing that is meant.
      back.setAttribute('href', from.href);
      back.textContent = `← ${from.label}`;
    }
  }
}
</script>
{% if live %}
{#- role="status" and not a bare div: news that somebody else moved the plan
    under you is the one thing on screen that must reach a reader who is not
    looking at that corner. Polite, because it is not an emergency — the banner
    deliberately does nothing until you press reload. -#}
<div id="moved" role="status" aria-live="polite" hidden></div>
<script>
// Somebody else committed. Say so and get out of the way: reloading over an open
// editor would throw away work that is not in git yet, and the whole point of one
// Save being one commit is that nothing moves under you until you ask.
const moved = document.getElementById('moved');
// Commits this tab produced. Every commit comes back down this stream including
// your own, and being told "the plan changed" one keystroke after changing it is
// how a banner becomes wallpaper.
const movedOurs = new Set();
// A write is announced to the stream before the request that made it is
// answered, so the news of your own save can arrive before you know its sha.
// Anything that lands mid-write waits until it does.
let movedWriting = 0;
const movedHeld = [];
addEventListener('openproj:writing', () => { movedWriting++; });
addEventListener('openproj:wrote', event => {
  movedWriting = Math.max(0, movedWriting - 1);
  if (event.detail) movedOurs.add(event.detail);
  if (!movedWriting) while (movedHeld.length) showMoved(movedHeld.shift());
});

// A commit somebody else in your co-editing room made is not somebody changing
// the file under you: the text it holds is already in the box in front of you,
// letter by letter, which is what the room is. The banner appeared anyway —
// "this was just changed by somebody else" over a document that had just been
// synced, which is jcanton's report from the deployed service.
//
// Its own event rather than `openproj:wrote`, which also decrements the
// in-flight counter: only the tab that pressed Save owes that one, and every tab
// in the room hears this.
addEventListener('openproj:ours', event => {
  if (!event.detail) return;
  movedOurs.add(event.detail);
  // And if the stream beat the socket to it, the banner is already up about a
  // commit we now know was the room's. Racing is the normal case, not the
  // unlucky one: both arrive from the same write.
  if (movedShowing === event.detail) {
    moved.hidden = true;
    movedShowing = null;
  }
});

// Which commit the banner is currently about, so a late "that one was ours" can
// take it down again.
let movedShowing = null;

function showMoved(message) {
  // Only the stream's bare {commit, changed} frame is a plan change; a typed
  // frame (`t` present, see web.py's `broadcast`) is other news riding the
  // same stream. Assuming every frame was a change would pop "The plan
  // changed." over pages the pusher had just confirmed, not moved.
  if (message.t !== undefined) return;
  const {commit, changed} = message;
  if (movedOurs.has(commit)) return;
  movedShowing = commit;
  // What this page is looking at. A page showing one record has it in its URL;
  // the table shows all of them and has nothing in its URL, so it says so — and
  // said nothing, every write anywhere read as unrelated to what was on screen.
  const here = location.pathname.split('/').pop();
  const showing = window.SHOWING || (here ? [here] : []);
  const seen = changed.some(id => showing.includes(id));
  moved.hidden = false;
  // The sha comes off a stream, so it is escaped like anything else that
  // arrives from outside this script — a value nothing on this page validates.
  moved.innerHTML = (seen ? 'This was just changed by somebody else. ' : 'The plan changed. ')
    + `<a href="">reload</a> <span class="sha">${esc(String(commit).slice(0, 7))}</span>`;
}

const source = new EventSource('/api/events');
source.onmessage = event => {
  const message = JSON.parse(event.data);
  // The pusher's landed frame — {t: 'landed', landed, remapped, parked},
  // defined at web.py's `broadcast` — re-broadcast as a DOM event because its
  // consumers (the table's row marks, the editor's save state) live in other
  // scripts and this EventSource is the page's only one. Immediately, not held
  // behind an in-flight write like a plan change: a frame cannot name a sha
  // whose request has not answered yet, so there is nothing to race.
  if (message.t === 'landed') {
    dispatchEvent(new CustomEvent('openproj:landed', {detail: message}));
  }
  if (movedWriting) movedHeld.push(message); else showMoved(message);
};
</script>
<script>
// The pile banner (design/deferred-push.md, "Saying it on the page"): loud when
// the saves already made here are not landing on GitHub, quiet otherwise. It
// reads the numbers /api/health reports — the reading the store's write gate
// also refuses on, so this banner and the 503 cannot disagree about the pile.
const pile = document.getElementById('pile');

// When "not on GitHub yet" stops being ordinary. A push lands in about two
// seconds, so a save still here after a minute means the pusher is failing or
// GitHub is away — said now, well before store.py's ten-minute refusal,
// because a warning that arrives with the refusal has warned nobody. Not
// lower: every save is briefly unpushed by design, and a banner that spoke on
// that window would speak on every save and be wallpaper by the day it
// matters — the same alarm-fatigue argument that keeps /api/health green
// below the ceiling.
const PILE_LOUD_AGE_S = 60;
// The poll is the backbone, not a comfort: Cloud Run recycles the event
// stream every 300s with no replay, so a landed frame proves a landing and
// its absence proves nothing — only asking again can notice a pusher that has
// gone quiet. Slow, because a page that is just sitting open owes the server
// almost nothing; the landed listener below re-asks the moment there is news.
const PILE_POLL_MS = 60000;

// The plan's own commit, in the footer, off the poll that is already happening.
// A second request for seven characters would be a second request.
function showHead(health) {
  const at = document.getElementById('planhead');
  if (at && health.head) at.textContent = 'plan ' + String(health.head).slice(0, 7);
}

function showPile(health) {
  const stranded = health.unpushed || 0;
  const age = health.oldest_unpushed_age || 0;
  const parked = health.parked || 0;
  if (!parked && !(stranded && age >= PILE_LOUD_AGE_S)) {
    pile.hidden = true;
    return;
  }
  const minutes = Math.max(1, Math.floor(age / 60));
  const said = [];
  // "Saves", not commits: named by what a person did, and it is their save
  // the mark on the table row is quietly saying the same thing about.
  if (stranded) said.push(
    `${stranded} save${stranded === 1 ? ' is' : 's are'} on this server and `
    + `not on GitHub yet — the oldest has waited ${minutes} `
    + `minute${minutes === 1 ? '' : 's'}.`);
  // `parked` counts the local refs/openproj/stranded-* refs, and store.py's
  // `_settle` deletes each one THE MOMENT its branch push is confirmed on the
  // remote — so a nonzero count is precisely the saves GitHub does not hold
  // in any form yet, the ones a recycled container takes with it. The branch
  // and its pull request describe the state AFTER that push lands, which is
  // when this count is zero and the sentence is gone: this line once promised
  // them here, calling the work safe at the one moment it was not.
  if (parked) said.push(
    `${parked} save${parked === 1 ? '' : 's'} could not land on GitHub's main `
    + `and ${parked === 1 ? 'is' : 'are'} still only on this server — headed `
    + 'for openproj/stranded-* branches, but not on GitHub in any form until '
    + 'that push is confirmed.');
  const sentence = said.join(' ');
  // Numbers and fixed words only, but through textContent all the same: one
  // escaping boundary, no exceptions to reason about. Re-set only on change —
  // a polite live region speaks when its contents move, and the same report
  // re-said every poll is the wallpaper this banner exists to not be.
  if (pile.textContent !== sentence) pile.textContent = sentence;
  pile.hidden = false;
}

async function readPile() {
  // The body is read whatever the status: past the ceiling the route answers
  // 503 and still carries the numbers, and that answer is exactly the one
  // this banner exists for. A network failure or a non-JSON body from
  // something in front of the service is caught and the banner keeps its last
  // word — the next poll asks again.
  try {
    const health = await (await fetch('/api/health')).json();
    showPile(health);
    showHead(health);
  } catch {}
}

readPile();
setInterval(readPile, PILE_POLL_MS);
// A landing is the moment the news changes, so re-ask at once rather than in
// up to a minute — but only while the banner is up: on the quiet day this
// frame follows every save, and a health read per save per open tab is a poll
// pretending to be an event.
addEventListener('openproj:landed', () => { if (!pile.hidden) readPile(); });
</script>
{% endif %}
{% if mermaid %}
<script>
// **The diagrams, and 3.5 MB that only a page with one on it ever pays for.**
//
// Fetch-and-inject, and every word of `excalidraw()`'s reasoning in `controls.py`
// applies here unchanged: the policy's `script-src 'unsafe-inline'` allows a
// script whose BODY is written in and grants no `'self'` a `src` could be allowed
// by, while `connect-src 'self'` grants the fetch — so fetch-and-inject is the one
// door that opens. `response.ok` is checked, because `.text()` on a 404 resolves
// with the error page's body and this would otherwise inject it.
//
// It is not inlined for two reasons and the second is the one that decides it.
// Bytes: 3,572,661 of them, against a Help page that is 400 KB in total, and most
// readers of most pages never meet a diagram. And the bundle contains eighty
// `url(` tokens — SVG filter and marker references built out of template
// literals — so a page carrying it fails `test_no_page_asks_the_network_for_a_font`,
// which reads every `url(` on the page and demands `data:` or `#`. That rule is
// right and the bundle is harmless; the way to have both is for the bundle never
// to be on a page.
//
// This block is emitted only where `_page` found a `pre.mermaid` element, so
// nothing here runs on a page with no diagram, and the static export never has
// one — see `_fence` in `markdown.py`. Written as a selector and not as the tag
// it looks for: the literal in a comment is a literal in the served bytes, and it
// would make "does this page have a diagram on it" answer yes for every page
// carrying this loader — a marker that matches its own detector.
(() => {
  const BLOCKS = () => document.querySelectorAll('pre.mermaid');

  // The source, stashed before mermaid replaces it with an `<svg>`. A theme
  // change re-renders, and mermaid re-renders from the element's text — which by
  // then is the previous drawing's markup. Read once, kept, written back each
  // time.
  for (const block of BLOCKS()) block.dataset.src = block.textContent;

  function why(block, said) {
    // Beside the block rather than inside it: the source stays legible, which is
    // exactly what the static export shows, and the line says which of the two
    // this is.
    //
    // Built here rather than through the shell's `element` helper, which reads
    // like the obvious reuse and is not available: that one is a `const` inside
    // another block, so it is not on the global scope these separate `<script>`
    // elements actually share. Written the other way it threw a ReferenceError
    // inside the render loop — which took the diagrams AFTER the failed one down
    // with it, silently, because the loop is inside an async function nobody
    // awaits. Measured: one bad fence cost the other two.
    if (block.nextElementSibling && block.nextElementSibling.className === 'mermaidwhy') return;
    const note = document.createElement('p');
    note.className = 'mermaidwhy';
    note.textContent = said;
    block.after(note);
  }

  // Mermaid's `base` theme takes its colours from variables rather than from a
  // palette of its own, which is the only shape that can follow nine schemes and
  // two polarities. Read off the root element at render time, so a scheme change
  // is a re-read rather than a table written down here — the same arrangement
  // `paint()` on the graph has, and for the same reason: a colour resolved once
  // at build time is a colour that stops matching the page.
  function palette() {
    const style = getComputedStyle(document.documentElement);
    const token = name => style.getPropertyValue(name).trim();
    return {
      background: token('--surface'),
      primaryColor: token('--surface-2'),
      primaryTextColor: token('--fg'),
      primaryBorderColor: token('--line-strong'),
      secondaryColor: token('--surface-2'),
      tertiaryColor: token('--surface'),
      lineColor: token('--line-strong'),
      textColor: token('--fg'),
      // A subgraph's box. The app draws a container as a quiet ground with a
      // drawn edge — the graph page's compounds do the same — so the two views of
      // one plan do not disagree about what "inside" looks like.
      clusterBkg: token('--surface'),
      clusterBorder: token('--line'),
      titleColor: token('--muted'),
      edgeLabelBackground: token('--surface'),
      fontFamily: token('--font-sans'),
      fontSize: '13px',
    };
  }

  let LIBRARY = null;
  async function mermaidLibrary() {
    if (LIBRARY) return LIBRARY;
    const response = await fetch('/static/mermaid.min.js');
    if (!response.ok) throw new Error(`the bundle answered ${response.status}`);
    const source = await response.text();
    const tag = document.createElement('script');
    tag.textContent = source;
    // The same marker `excalidraw()` writes, so the editor's script probe reads a
    // second injected bundle as a known one rather than as a surprise.
    tag.dataset.injectedBundle = 'mermaid';
    document.head.appendChild(tag);
    LIBRARY = window.mermaid;
    if (!LIBRARY) throw new Error('the bundle ran and defined no mermaid');
    return LIBRARY;
  }

  async function draw() {
    const blocks = [...BLOCKS()];
    if (!blocks.length) return;
    let mermaid;
    try {
      mermaid = await mermaidLibrary();
    } catch (error) {
      // One line per block and then nothing further: a failed fetch is a failed
      // fetch on every diagram on the page, and the source is still readable
      // under each of them.
      for (const block of blocks) why(block, 'The diagram could not be drawn: ' + error.message);
      return;
    }
    // **`securityLevel: 'strict'` and `htmlLabels: false`, said rather than
    // inherited.** A shaping document is written by anybody who can push to the
    // plan, and mermaid at `loose` puts that text into the DOM as markup and
    // honours `click` directives. Strict is mermaid's own default today; a
    // default is a thing that changes in a minor release, and this one is load
    // bearing enough to be written down.
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      themeVariables: palette(),
      // **`htmlLabels: false` in both places, which is not belt and braces.** Set
      // on `flowchart` alone it drew five `<foreignObject>` elements anyway,
      // measured on this page — the top-level key is the one a flowchart's labels
      // actually read in mermaid 11, and the nested one is what the other diagram
      // types read. An HTML label is a `<foreignObject>`: it holds real markup
      // rather than SVG text, it is the surface `securityLevel` is doing the most
      // work on, and it is the part of an SVG that does not survive the drawing
      // being copied out of the page or printed onto a deck slide.
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      // **A diagram that will not parse leaves the source, not a picture of a
      // bomb.** Left at the default, mermaid draws its own error graphic into the
      // element — a "Syntax error in text" card with an illustration — which is a
      // second design language on the page, says nothing about which line is
      // wrong, and replaces the one thing the writer needs to see. With this on,
      // `run` throws instead, the loop below puts the source back, and the line
      // beside it says what happened. Measured: without it, a fence reading
      // `flowchart TD` and `a[["` drew a picture and reported success.
      suppressErrorRendering: true,
    });
    // **One `run` per block, not one for the batch.** A diagram that will not
    // parse is somebody's typo in a document, and `run` over a list stops being
    // able to say which one failed — worse, a throw part way through leaves the
    // diagrams after it undrawn. A file that is not a record costs that file and
    // nothing else; a fence that is not a diagram costs that fence.
    for (const block of blocks) {
      try {
        block.removeAttribute('data-processed');
        block.textContent = block.dataset.src;
        try {
          await mermaid.run({ nodes: [block] });
        } catch {}
        // **Asked of the element, not of the promise.** `suppressErrorRendering`
        // makes `run` reject, but mermaid has already stamped `data-processed`
        // and emptied the block by then — measured: a fence reading `a[["` left
        // an empty box with the attribute set and no error anywhere on the page,
        // which is the "empty must not look like broken" failure exactly. The
        // only honest question is whether there is a drawing in there.
        if (!block.querySelector('svg')) {
          block.removeAttribute('data-processed');
          block.textContent = block.dataset.src;
          why(block, 'This diagram could not be drawn. Its text is below.');
        }
      } catch {
        // The outer net, and it is not theoretical: the first version of `why`
        // called a helper that is not on this scope, threw a ReferenceError here,
        // and took every diagram after the failed one down with it — silently,
        // because this loop is inside an async function nobody awaits.
      }
    }
  }

  draw();
  // A palette or a polarity change is a re-render, because every colour above was
  // read off the root element when the drawing was built.
  addEventListener('themechange', draw);
})();
</script>
{% endif %}
</body></html>
"""


def _titles(index: Index) -> dict[str, str]:
    """What each record is called, for the menus whose values are ids.

    Only the Project facet has any today. It is the whole plan rather than the
    projects alone because a value in a menu is a value in a menu — the day
    something else is filtered by id, this already knows its name.
    """
    return {record_id: record.title for record_id, record in index.plan.items()}


# The nav, as the field on `Links` each item points at and the word it wears. One
# list, because the mark for "you are here" has to be decided once: six links
# written out by hand were six places for a seventh page to be added and marked
# nowhere.
_NAV = (
    ("records", "Records"),
    ("table", "Table"),
    ("graph", "Graph"),
    ("timeline", "Timeline"),
    ("cycles", "Cycles"),
    ("people", "People"),
    # The two inbox views of the landing list, back in the nav on jcanton's
    # ruling: quick access to what would otherwise be a click on a filter. At
    # the end, where they sat before the records flip retired their own pages.
    ("issues", "Issues"),
    ("notes", "Notes"),
    # Last, and after the two inboxes, because it is the one item that is not a
    # view of the plan: everything to its left answers "what is in the plan" and
    # this answers "what is this tool". jcanton, 2026-08-27, given the choice
    # between a nav item and a `?` in the corner beside the sign-in — the corner
    # already wraps at 500px with three controls in it, and an item here gets the
    # `aria-current` mark every other page has for free.
    ("help", "Help"),
)
_NAV_KEYS = frozenset(key for key, _ in _NAV)
# What a record page's back link calls the view it was opened from. The nav's own
# word for all but one of them: the link has read "all records" since it could
# only ever go there, and that is still what it says when there is no origin to
# go back to — so taking the nav's "Records" here would have been one link
# wearing two names for one destination, depending on how you arrived.
_BACK_LABEL = {"records": "all records"}
# What a stamped address is allowed to be: one slash, then either the end of it
# or a character that is not another slash.
#
# An allowlist, because there is no list of URL spellings that is ever finished —
# and the second half of it is not decoration. A leading slash alone was the first
# spelling of this check and `//host/x` walks straight through it: a
# protocol-relative URL to somebody else's host, which is the exact spelling that
# already got past this repository's image check once. The backslash is in the
# class beside it because the URL parser folds `/\host` into the same thing.
#
# Here rather than in the template, where it would be a regex inside a Python
# string that is not raw: `\\` there reaches the browser as `\`, and written
# there first this was an unterminated character class — a SyntaxError costing
# the whole page script, which is what a probe caught before it was a commit.
_ORIGIN_PATH = r"^/($|[^/\\])"
# Pages that exist and are not in the nav, and may still say which item to light.
#
# `detail` was the seventh nav item and was the table with fewer features: the
# same records, grouped by status, with no filter, no search, no sort and no
# inline editing. It is still the page every title links to, and in the static
# export `detail.html` is the whole corpus in one file — so the page stays and
# only the nav slot goes.
#
# The distinction is worth encoding rather than deleting the guard: `/deck/<n>`
# is in the same position already, and the next page will be too. A `current`
# that is neither a nav item nor a page is still a typo and still raises.
_OFF_NAV = frozenset({"detail"})
_PAGE_KEYS = _NAV_KEYS | _OFF_NAV


def _page(
    title: str,
    content: str,
    style: str = "",
    links: Links = STATIC,
    current: str = "",
    unreadable: Sequence[Unreadable] = (),
    origin: str | None = None,
) -> str:
    """Autoescaping protects record titles inside the inner templates; the already
    rendered body and stylesheet are marked safe here so the shell does not escape
    them a second time.

    `current` is which nav item this page is, by `Links` field — and it is not
    derived from the href, because two of the routes that must mark one are not
    the href of the link that leads to them: `/detail/<id>` marks Detail and
    `/cycle/<n>` marks Cycles, and a static export has no server to ask which page
    it is serving. The caller knows; nothing else does.

    Empty means no item is marked, which `/new` uses deliberately: it is not one
    of the nav's views, and pressing Table from it leaves the form.
    `aria-current="page"` claims a page *within* the set, and a form that is not in
    the set gets a visible `<h1>` instead — the one page that names itself on
    screen. Said as "the set" and not as a number: the count has been written into
    three docstrings twice now, and has been wrong in all of them each time a page
    was added or taken away.

    A `current` that is not a nav key raises rather than quietly marking nothing,
    because marking nothing is the exact defect this round is here to fix.

    `unreadable` is the plan files that are not records. It is drawn here rather
    than by each page for the same reason the nav mark is decided here: eight
    entry points is eight places to forget, and the one page that forgot would be
    a page that silently draws a plan short.
    """
    if current and current not in _PAGE_KEYS:
        raise ValueError(f"{current!r} is not a page: {sorted(_PAGE_KEYS)}")
    return _compiled(_SHELL).render(
        title=title,
        content=Markup(content),
        style=Markup(style),
        csp=Markup(CSP),
        font=_font_uri(),
        icon=_icon_uri(),
        links=links,
        # The word map, on every page rather than in the three payloads that
        # happened to carry it. The hover card is drawn by the table, the graph
        # and the timeline, and the graph's payload is cytoscape elements — no
        # `DATA` at all — so the card
        # read `in_progress` off a node and drew it as itself. `HUMAN` exists
        # because five pages inventing their own capitalisation is how one status
        # came to be spelled three ways on one screen; a card is the fourth page.
        words=HUMAN,
        # The marks that go with those words, for the hover card: one map per
        # ladder, so a card says the rung the same way on all three views.
        cardmarks={"status": STATUS_GLYPH, "priority": PRIORITY_GLYPH},
        hillgeom=hill_geometry(),
        unreadable=list(unreadable),
        # The sentence is built here rather than in the template, because English
        # is not something Jinja should be doing arithmetic about and "1 files
        # are not records" is the kind of copy that tells a reader nobody looked.
        headline=(
            "One file in the plan is not a record, so nothing in it is on this page."
            if len(unreadable) == 1
            else f"{len(unreadable)} files in the plan are not records, "
            "so nothing in them is on this page."
        ),
        nav=[
            {"href": getattr(links, key), "label": label, "current": key == current}
            for key, label in _NAV
        ],
        # What a record page reached from this one should call it, and empty on
        # the pages that are not a view: the record page itself and the create
        # form. That is the whole switch the script below turns on — a page with
        # a name leaves it behind, a page without one picks it up. `current` and
        # not the route, because `/cycle/37` and `/deck/37` are both Cycles and
        # neither of them is the href of the link that leads there.
        # What this page calls itself when a record page later asks where it was
        # opened from. Normally the nav's own word for whichever item is marked;
        # `origin` overrides it for a page that IS somewhere to come back from
        # but shares its nav item with another — the deck marks Cycles, and a
        # back link reading "← Cycles" while pointing at `/deck/37` names the
        # wrong place. A page that is only ever reached FROM somewhere passes
        # neither and reads the stamp instead.
        origin=(
            origin
            if origin is not None
            else next((_BACK_LABEL.get(key, label) for key, label in _NAV if key == current), "")
        ),
        origin_path=_ORIGIN_PATH,
        # The shell writes the chip and legend rules for every status, so a
        # status added to the model cannot arrive with three of its four tokens
        # wired up and the fourth still spelled out on a line nobody edited. The
        # kinds are here for the same reason and were not: their chip rule named
        # three of them, so `product` was the one chip on the page with no border.
        statuses=STATUSES,
        kinds=KINDS,
        # The colour schemes: the families the picker offers, the block of slots
        # they put on the root element, and which hue each status takes. One
        # source, so a family added to `themes.py` reaches the menu and the
        # stylesheet on the same commit.
        families=FAMILIES,
        schemes=Markup(_scheme_css()),
        status_slots=STATUS_SLOTS,
        # Only the server has an event stream to listen to. A static page opening a
        # connection to nothing would retry forever in the console.
        live=links.table.startswith("/"),
        # Whether this page has a diagram on it, and therefore whether it should
        # carry the loader that fetches 3.5 MB of mermaid.
        #
        # Decided here for the reason the nav mark and the unreadable banner are:
        # a fence can be in a record's body, in the preview beside it, on a deck
        # slide or on the Help page, and eight entry points is eight places for
        # the ninth to forget. The page that forgot would draw mermaid source
        # under a heading and look like a rendering fault.
        #
        # **Searching the finished markup for a string, which this file otherwise
        # refuses to do — so here is why it is safe.** `_ENV` autoescapes, so a
        # title, a body or a login containing these characters reaches the page as
        # `&lt;pre class=&#34;mermaid&#34;&gt;`: the literal below cannot be
        # produced by anything a person typed, only by `_fence` in `markdown.py`.
        # That is the difference between this and the substitution defect this
        # repository keeps meeting — nothing is written INTO the page here, and the
        # question asked is one only the renderer can have answered.
        mermaid='<pre class="mermaid">' in content,
        # This code's own version, in the footer. Imported from the package
        # rather than passed in by each caller: it is a fact about the build and
        # not about the page, and `pyproject.toml` and `__init__.py` have already
        # disagreed with each other and with the newest tag once.
        version=__version__,
    )
